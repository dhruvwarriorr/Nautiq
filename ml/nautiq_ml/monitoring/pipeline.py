"""Unified model monitoring: inputs, expected-state outcomes, profile detector and calibration.

A drift signal starts an investigation. This module never selects, retrains, recalibrates or promotes
a model, never adapts a reference during an event, and never reads the absence of trusted labels as
model health. Numerical thresholds are unreviewed engineering defaults and are recorded in every report.
"""

import io
import math
from collections import Counter
from datetime import timedelta
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
from psycopg.types.json import Jsonb
from scipy import stats

from ..argo import evidence
from ..argo.storage import digest, read_object, store
from ..climatology import pipeline as climate
from ..climatology.grid import instant

VERSION = "unified-model-monitoring-v1"
VARIABLES = ("temperature_c", "practical_salinity")
POLICY = {
    "window_days": 90,
    "min_recent_profiles": 30,
    "max_profiles": 5000,
    "psi_bins": 10,
    "psi_watch": 0.10,
    "psi_investigate": 0.25,
    "cell_degrees": 5,
    "novel_cell_share_investigate": 0.20,
    "depth_coverage_shift_investigate": 0.25,
    "min_scored_profiles": 30,
    "min_trusted_label_profiles": 30,
    "rank_primary": "mahalanobis_squared",
    "rank_bands_percentile": {"p90": 90.0, "p97_5": 97.5, "p99_5": 99.5},
    "rank_binomial_alpha": 0.01,
    "trusted_data_mode": "D",
    "thresholds_reviewed": False,
    "threshold_note": "Engineering defaults. Frozen release gates are set after baseline experiments and independent review; these values only start investigations.",
}


def code_hash():
    return digest(Path(__file__).read_bytes())


def psi(baseline, recent, bins):
    """Population stability index with baseline-quantile bins; None when it cannot be computed."""
    baseline = np.asarray(baseline, float)
    recent = np.asarray(recent, float)
    if len(baseline) < 10 or len(recent) < 10:
        return None
    edges = np.unique(np.quantile(baseline, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return None
    edges[0], edges[-1] = -np.inf, np.inf
    a = np.histogram(baseline, edges)[0] / len(baseline)
    b = np.histogram(recent, edges)[0] / len(recent)
    a, b = np.clip(a, 1e-4, None), np.clip(b, 1e-4, None)
    return float(np.sum((b - a) * np.log(b / a)))


def psi_categorical(baseline, recent, categories):
    if len(baseline) < 10 or len(recent) < 10:
        return None
    a = np.array([sum(1 for v in baseline if v == c) for c in categories], float) / len(
        baseline
    )
    b = np.array([sum(1 for v in recent if v == c) for c in categories], float) / len(
        recent
    )
    a, b = np.clip(a, 1e-4, None), np.clip(b, 1e-4, None)
    return float(np.sum((b - a) * np.log(b / a)))


def drift_status(value, policy):
    if value is None:
        return "insufficient_evidence"
    if value >= policy["psi_investigate"]:
        return "investigate"
    return "watch" if value >= policy["psi_watch"] else "within_expectation"


def cell(lat, lon, width):
    return (math.floor(lat / width), math.floor(lon / width))


def mean(values):
    return float(np.mean(values)) if values else None


def input_section(recent, baseline, expected_rows, policy):
    width = policy["cell_degrees"]
    out = {
        "recent_profiles": len(recent),
        "baseline_profiles": len(baseline),
        "baseline_definition": "profiles of the pinned climatology training grid (all splits)",
    }
    if len(recent) < policy["min_recent_profiles"]:
        out["status"] = "insufficient_evidence"
        out["reason"] = "too_few_recent_profiles"
    reasons, total, missing = Counter(), 0, 0
    observed_by_depth, profiles_with_rows = Counter(), 0
    for _, result in expected_rows:
        profiles_with_rows += 1
        for row in result.get("rows", []):
            for v in VARIABLES:
                p = row.get(v) or {}
                total += 1
                if p.get("expected_mean") is None:
                    missing += 1
                    reasons[p.get("reason") or "unspecified"] += 1
            if any((row.get(v) or {}).get("observed") is not None for v in VARIABLES):
                observed_by_depth[row["depth_m"]] += 1
    out["feature_availability"] = {
        "profiles_with_expected_comparison": profiles_with_rows,
        "profile_depth_variable_cells": total,
        "cells_without_expected_mean": missing,
        "missing_rate": missing / total if total else None,
        "reasons": dict(reasons.most_common(8)),
        "interpretation": "Cells outside the training domain, depth envelope or supported pools receive no expected mean. This is the input-coverage signal; it is not a model error.",
    }
    drift = {}
    base = {
        "latitude": [b["latitude"] for b in baseline],
        "longitude": [b["longitude"] for b in baseline],
        "month": [instant(b["observed_at"]).month for b in baseline],
    }
    now = {
        "latitude": [r["latitude"] for r in recent],
        "longitude": [r["longitude"] for r in recent],
        "month": [r["observed_at"].month for r in recent],
    }
    for name in ("latitude", "longitude"):
        value = psi(base[name], now[name], policy["psi_bins"])
        drift[name] = {"psi": value, "status": drift_status(value, policy)}
    value = psi_categorical(base["month"], now["month"], range(1, 13))
    drift["season_month"] = {
        "psi": value,
        "status": drift_status(value, policy),
        "note": "Recent windows cover few months by construction; seasonal PSI is expected to be high for short windows and is informative only for windows of a year or more.",
    }
    if policy["window_days"] < 365:
        drift["season_month"]["status"] = "informative_only"
    out["distribution_drift"] = drift
    baseline_cells = {cell(b["latitude"], b["longitude"], width) for b in baseline}
    novel = [
        r
        for r in recent
        if cell(r["latitude"], r["longitude"], width) not in baseline_cells
    ]
    recent_cells = Counter(cell(r["latitude"], r["longitude"], width) for r in recent)
    out["spatial_coverage"] = {
        "cell_degrees": width,
        "recent_cells": len(recent_cells),
        "baseline_cells": len(baseline_cells),
        "recent_profiles_in_cells_without_training_profiles": len(novel),
        "novel_cell_share": len(novel) / len(recent) if recent else None,
    }
    depth = {}
    if profiles_with_rows:
        for d, count in sorted(observed_by_depth.items()):
            depth[str(d)] = {"recent_observed_share": count / profiles_with_rows}
    out["depth_coverage"] = {"by_depth_m": depth}
    flags = []
    if out.get("status") != "insufficient_evidence":
        for name, item in drift.items():
            if name != "season_month" and item["status"] == "investigate":
                flags.append(
                    {
                        "code": f"{name}_distribution_shift",
                        "message": f"Recent {name} distribution differs from the training baseline (PSI {item['psi']:.2f}).",
                    }
                )
        share = out["spatial_coverage"]["novel_cell_share"]
        if share is not None and share >= policy["novel_cell_share_investigate"]:
            flags.append(
                {
                    "code": "novel_spatial_cells",
                    "message": f"{share:.0%} of recent profiles lie in 5-degree cells with no training profile.",
                }
            )
        rate = out["feature_availability"]["missing_rate"]
        if rate is not None and rate >= 0.5:
            flags.append(
                {
                    "code": "expected_mean_unsupported_majority",
                    "message": f"{rate:.0%} of profile-depth cells have no supported expected mean.",
                }
            )
        out["status"] = "investigate" if flags else "within_expectation"
    out["flags"] = flags
    return out


def outcome_section(recent, expected_rows, policy):
    modes = {str(r["profile_id"]): r["data_mode"] for r in recent}
    out = {
        "variables": {},
        "label_policy": f"Trusted outcomes are data mode {policy['trusted_data_mode']} (delayed-mode). Real-time and adjusted-mode values are shown only as unverified residual size.",
    }
    trusted_ids = {pid for pid, m in modes.items() if m == policy["trusted_data_mode"]}
    out["trusted_profiles"] = len(trusted_ids)
    out["recent_profiles_with_comparison"] = len({str(p) for p, _ in expected_rows})
    for v in VARIABLES:
        groups = {"trusted": {}, "unverified_realtime": {}}
        for pid, result in expected_rows:
            key = "trusted" if str(pid) in trusted_ids else "unverified_realtime"
            g = groups[key].setdefault(
                str(pid), {"active": [], "candidate": [], "climatology": []}
            )
            for row in result.get("rows", []):
                p = row.get(v) or {}
                if p.get("observed") is None or p.get("expected_mean") is None:
                    continue
                g["active"].append(p["observed"] - p["expected_mean"])
                if p.get("candidate_mean") is not None:
                    g["candidate"].append(p["observed"] - p["candidate_mean"])
                if p.get("climatology_mean") is not None:
                    g["climatology"].append(p["observed"] - p["climatology_mean"])
        summary = {}
        for key, profiles in groups.items():

            def stat(name):
                per = [x[name] for x in profiles.values() if x[name]]
                if not per:
                    return {
                        "profiles": 0,
                        "profile_weighted_mae": None,
                        "profile_weighted_bias": None,
                    }
                return {
                    "profiles": len(per),
                    "profile_weighted_mae": mean(
                        [float(np.mean(np.abs(e))) for e in per]
                    ),
                    "profile_weighted_bias": mean([float(np.mean(e)) for e in per]),
                }

            summary[key] = {
                "active_method": stat("active"),
                "residual_candidate": stat("candidate"),
                "climatology": stat("climatology"),
            }
        out["variables"][v] = summary
    out["status"] = (
        "insufficient_evidence"
        if len(trusted_ids) < policy["min_trusted_label_profiles"]
        else "within_expectation"
    )
    out["reason"] = (
        "Delayed-mode labels arrive one to two years after observation, so recent profiles rarely have trusted outcomes. This is verification lag, not model health."
        if out["status"] == "insufficient_evidence"
        else "Trusted outcomes are summarized without a frozen reference threshold; compare with the release evaluation before concluding anything."
    )
    out["flags"] = []
    return out


def detector_section(anomaly_rows, policy):
    """Rank-share check. A band finer than the reference can resolve is reported but never tested:
    with n reference profiles a profile above all of them ranks 100, so the smallest honest share is 1/(n+1)."""
    out = {"primary_measure": policy["rank_primary"], "variables": {}, "flags": []}
    bands = policy["rank_bands_percentile"]
    nominal = {"p90": 0.10, "p97_5": 0.025, "p99_5": 0.005}
    names = {"temperature_c": "temperature", "practical_salinity": "salinity"}
    statuses = []
    for v in VARIABLES:
        ranks, fallback, resolutions = [], 0, []
        for _, result in anomaly_rows:
            item = (result.get("variables") or {}).get(v) or {}
            pct = item.get("percentiles")
            if item.get("status") != "diagnostic" or not pct:
                continue
            value = (pct.get("values") or {}).get(policy["rank_primary"])
            if value is None:
                continue
            ranks.append(float(value))
            fallback += bool(pct.get("fallback"))
            if pct.get("resolution_percent") is not None:
                resolutions.append(float(pct["resolution_percent"]) / 100)
        n = len(ranks)
        resolution = float(np.median(resolutions)) if resolutions else None
        info = {
            "scored_profiles": n,
            "regional_fallback_share": fallback / n if n else None,
            "reference_resolution_share": resolution,
        }
        if n:
            info["histogram_deciles"] = [
                int(c) for c in np.histogram(ranks, bins=10, range=(0, 100))[0]
            ]
        info["tail_shares"] = {}
        flagged = []
        for key, cutoff in bands.items():
            k = sum(1 for r in ranks if r >= cutoff)
            resolvable = resolution is not None and nominal[key] >= resolution
            p = None
            if resolvable and n >= policy["min_scored_profiles"]:
                p = float(
                    stats.binomtest(k, n, nominal[key], alternative="greater").pvalue
                )
            info["tail_shares"][key] = {
                "percentile_at_least": cutoff,
                "profiles": k,
                "share": k / n if n else None,
                "reference_share": nominal[key],
                "resolvable_with_reference": resolvable,
                "p_value_excess": p,
            }
            if p is not None and p < policy["rank_binomial_alpha"]:
                flagged.append(key)
        tested = [
            t for t in info["tail_shares"].values() if t["p_value_excess"] is not None
        ]
        if n < policy["min_scored_profiles"] or not tested:
            info["status"] = "insufficient_evidence"
            info["reason"] = (
                "too_few_scored_profiles"
                if n < policy["min_scored_profiles"]
                else "reference_too_small_to_resolve_any_tail_band"
            )
        elif flagged:
            info["status"] = "investigate"
            out["flags"].append(
                {
                    "code": f"{v}_rank_excess",
                    "message": f"More {names[v]} profiles than the reference share rank at or above the {', '.join(str(bands[k]) for k in flagged)}th percentile. Investigate source, coverage or a real regional change; do not retrain automatically.",
                }
            )
        else:
            info["status"] = "within_expectation"
        statuses.append(info["status"])
        out["variables"][v] = info
    out["status"] = (
        "investigate"
        if "investigate" in statuses
        else "within_expectation"
        if statuses and all(s == "within_expectation" for s in statuses)
        else "insufficient_evidence"
    )
    out["note"] = (
        "Ranks are descriptive and compared with the frozen calibration reference. They are not event probabilities; false-alert review by experts remains outstanding. Bands finer than the reference resolution are shown but not tested."
    )
    return out


def calibration_section(health, interval_rows):
    out = {"flags": []}
    if not health:
        out.update(
            status="insufficient_evidence", reason="interval_coverage_monitor_not_run"
        )
        return out
    report = health["report"]
    out["coverage_monitor"] = {
        "checked_at": health["checked_at"].isoformat(),
        "calculation_id": str(health["calculation_id"]),
        "nominal_coverage": report.get("nominal_coverage"),
        "trusted_profiles": report.get("trusted_profiles"),
        "candidate_profiles": report.get("candidate_profiles"),
        "pending_profiles": report.get("pending_profiles"),
        "variables": {
            v: {
                "status": (report.get("variables", {}).get(v) or {}).get("status"),
                "profile_group_coverage": (
                    report.get("variables", {}).get(v) or {}
                ).get("profile_group_coverage"),
            }
            for v in VARIABLES
        },
    }
    fallback = {}
    for v in VARIABLES:
        calibrated = fell_back = 0
        widths = []
        for _, result in interval_rows:
            for row in result.get("rows", []):
                p = row.get(v) or {}
                if p.get("lower") is None:
                    continue
                calibrated += 1
                fell_back += bool(p.get("fallback"))
                if p.get("width") is not None:
                    widths.append(p["width"])
        fallback[v] = {
            "interval_cells": calibrated,
            "fallback_group_share": fell_back / calibrated if calibrated else None,
            "median_width": float(np.median(widths)) if widths else None,
        }
    out["recent_interval_usage"] = fallback
    statuses = [
        (report.get("variables", {}).get(v) or {}).get("status") for v in VARIABLES
    ]
    if any(s == "coverage_degraded" for s in statuses):
        out["status"] = "investigate"
        out["flags"].append(
            {
                "code": "coverage_degraded",
                "message": "Trusted outcomes fall outside the nominal interval coverage tolerance.",
            }
        )
    elif all(s == "diagnostic_coverage_on_target" for s in statuses):
        out["status"] = "within_expectation"
    else:
        out["status"] = "insufficient_evidence"
        out["reason"] = (
            "No trusted delayed-mode outcomes exist yet for the calibrated interval. Empirical coverage is unproven."
        )
    return out


def overall(sections):
    statuses = [s["status"] for s in sections.values()]
    if "investigate" in statuses:
        return "investigate"
    return (
        "within_expectation"
        if all(s == "within_expectation" for s in statuses)
        else "insufficient_evidence"
    )


def monitor(window_days=None, s3=None):
    s3 = s3 or store()
    policy = dict(POLICY, window_days=window_days or POLICY["window_days"])
    with climate.connect() as db:
        pins = db.execute(
            """SELECT a.release_id anomaly_id,a.uncertainty_id,a.expected_id,a.reference_id,a.snapshot_id
FROM anomaly_selection s JOIN anomaly_releases a USING(release_id)
JOIN uncertainty_selection u ON u.release_id=a.uncertainty_id
JOIN expected_state_selection e ON e.release_id=a.expected_id
JOIN climatology_selection c ON c.release_id=a.reference_id"""
        ).fetchone()
        now = db.execute("SELECT clock_timestamp() AS instant").fetchone()["instant"]
        if not pins:
            return {"status": "reference_unavailable"}
        start = now - timedelta(days=policy["window_days"])
        recent = db.execute(
            """SELECT r.profile_id,r.revision_sha256,r.latitude,r.longitude,r.observed_at,r.data_mode
FROM profile_revisions r WHERE r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL AND r.observed_at BETWEEN %s AND %s
ORDER BY r.observed_at DESC,r.profile_id LIMIT %s""",
            (start, now, policy["max_profiles"] + 1),
        ).fetchall()
        if len(recent) > policy["max_profiles"]:
            return {
                "status": "monitor_budget_exceeded",
                "max_profiles": policy["max_profiles"],
            }

        def comparisons(table, release_id):
            return db.execute(
                f"""SELECT c.profile_id,c.result FROM {table} c JOIN profile_revisions r USING(profile_id,revision_sha256)
WHERE c.release_id=%s AND r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL AND r.observed_at BETWEEN %s AND %s""",
                (release_id, start, now),
            ).fetchall()

        expected = [
            (r["profile_id"], r["result"])
            for r in comparisons("expected_state_comparisons", pins["expected_id"])
        ]
        intervals = [
            (r["profile_id"], r["result"])
            for r in comparisons("uncertainty_comparisons", pins["uncertainty_id"])
        ]
        anomalies = [
            (r["profile_id"], r["result"])
            for r in comparisons("anomaly_comparisons", pins["anomaly_id"])
        ]
        health = db.execute(
            "SELECT * FROM uncertainty_health WHERE release_id=%s",
            (pins["uncertainty_id"],),
        ).fetchone()
        reference = db.execute(
            "SELECT * FROM climatology_releases WHERE release_id=%s",
            (pins["reference_id"],),
        ).fetchone()
        grid = pq.read_table(
            io.BytesIO(
                read_object(
                    s3, reference["grid_key"], reference["grid_sha256"], limit=16777216
                )
            )
        ).to_pylist()
        seen = {}
        for row in grid:
            seen.setdefault(row["profile_id"], row)
        baseline = list(seen.values())
        sections = {
            "inputs": input_section(recent, baseline, expected, policy),
            "expected_state_outcomes": outcome_section(recent, expected, policy),
            "profile_detector": detector_section(anomalies, policy),
            "calibration": calibration_section(health, intervals),
        }
        status = overall(sections)
        report = {
            "schema_version": 1,
            "method_version": VERSION,
            "checked_at": now.isoformat(),
            "window_start": start.isoformat(),
            "window_end": now.isoformat(),
            "pins": {k: str(v) for k, v in pins.items()},
            "policy": policy,
            "status": status,
            "sections": sections,
            "flags": [
                dict(f, section=name)
                for name, s in sections.items()
                for f in s.get("flags", [])
            ],
            "actions": "A flag starts an investigation. Nautiq never retrains, recalibrates, selects or promotes a model automatically, and a reference is never adapted during an event.",
            "release_approved": False,
        }
        calc = evidence.publish(
            s3,
            "model_monitor",
            VERSION,
            [],
            report,
            {"pins": report["pins"], "policy": policy},
            now.isoformat(),
            code_hash(),
        )
        db.execute(
            "UPDATE calculations SET state='stale' WHERE kind='model_monitor' AND state='current'"
        )
        evidence.record(db, calc, [])
        db.execute(
            """INSERT INTO model_monitoring_reports(report_id,checked_at,calculation_id,expected_id,uncertainty_id,anomaly_id,status,report,report_sha256)
VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                calc["id"],
                now,
                calc["id"],
                pins["expected_id"],
                pins["uncertainty_id"],
                pins["anomaly_id"],
                status,
                Jsonb(report),
                calc["manifest_sha"],
            ),
        )
    return {
        "status": status,
        "report_id": calc["id"],
        "flags": len(report["flags"]),
        "recent_profiles": len(recent),
    }


def main():
    import argparse
    import json

    parser = argparse.ArgumentParser()
    parser.add_argument("--window-days", type=int)
    args = parser.parse_args()
    print(json.dumps(monitor(args.window_days), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
