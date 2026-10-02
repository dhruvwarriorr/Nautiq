"""Fixed-reference coverage monitoring; suspect observations never retune calibration."""

import copy
from datetime import timedelta

import numpy as np
from psycopg.types.json import Jsonb

from ..argo import evidence, snapshots
from ..climatology.grid import VARIABLES, standardize
from ..climatology.pipeline import connect
from .calibration import metrics


def summarize(rows, variable, climate_policy, policy):
    available = [
        r
        for r in rows
        if r[variable]["observed"] is not None and r[variable]["q10"] is not None
    ]
    truth = np.array([r[variable]["observed"] for r in available])
    q = np.array(
        [[r[variable][k] for k in ("q10", "q50", "q90")] for r in available]
    ).reshape(-1, 3)
    bounds = np.array(
        [
            [
                r[variable][k] if r[variable][k] is not None else np.nan
                for k in ("lower", "upper")
            ]
            for r in available
        ]
    ).reshape(-1, 2)
    result = metrics(
        available,
        truth,
        q,
        bounds,
        selections=[r[variable] for r in available],
        climate_policy=climate_policy,
    )
    suspects = set()
    for row in available:
        p = row[variable]
        score = max(p["q10"] - p["observed"], p["observed"] - p["q90"], 0)
        if (
            p["correction"] is not None
            and score
            > max(p["correction"], 1e-12) * policy["monitor_suspect_score_multiplier"]
        ):
            suspects.add(row["profile_id"])
    result["suspect_profiles_for_adaptation"] = len(suspects)
    result["suspect_profile_ids"] = sorted(suspects)
    result["crossing_rate"] = (
        sum(r[variable]["quantile_crossing"] for r in available) / len(available)
        if available
        else None
    )
    result["unmodeled_label_rows"] = sum(
        r[variable]["observed"] is not None and r[variable]["q10"] is None for r in rows
    )
    adequate = (
        result["profiles"] >= policy["monitor_min_profiles"]
        and result["profile_group_coverage"] is not None
        and result["unavailable_rows"] == 0
        and result["unmodeled_label_rows"] == 0
    )
    result["status"] = (
        "insufficient_trusted_profiles"
        if not adequate
        else "coverage_degraded"
        if abs(result["profile_group_coverage"] - (1 - policy["alpha"]))
        > policy["coverage_gate"]["coverage_tolerance"]
        else "diagnostic_coverage_on_target"
    )
    result["groups"] = {}
    from .calibration import groups

    for area in ("arabian", "bay_bengal"):
        for depth in range(len(climate_policy["depth_bands_m"])):
            key = f"region_depth:{area}:{depth}"
            indices = [
                i
                for i, r in enumerate(available)
                if groups(r, climate_policy)[0] == key
            ]
            selected = [available[i] for i in indices]
            result["groups"][key] = metrics(
                selected,
                truth[indices],
                q[indices],
                bounds[indices],
                selections=[r[variable] for r in selected],
                climate_policy=climate_policy,
            )
    return result


def monitor():
    from ..argo.storage import store
    from ..expected_state.jobs import canonical_profile

    s3 = store()
    with connect() as db:
        source = db.execute(
            "SELECT u.*,c.manifest->'policy'->'climatology_policy' AS climate_policy,t.manifest->'policy'->'training_policy' AS training_policy FROM uncertainty_selection s JOIN uncertainty_releases u USING(release_id) JOIN expected_state_selection e ON e.release_id=u.expected_id JOIN climatology_selection b ON b.release_id=u.reference_id JOIN climatology_releases c ON c.release_id=u.reference_id JOIN training_snapshots t ON t.snapshot_id=u.snapshot_id"
        ).fetchone()
        if not source:
            return {"status": "reference_unavailable"}
        policy = source["report"]["policy"]
        now = db.execute("SELECT clock_timestamp() AS instant").fetchone()["instant"]
        start = now - timedelta(days=policy["monitor_window_days"])
        candidates = db.execute(
            """SELECT p.platform_id,r.*,a.sha256 raw_sha,a.object_key,v.result,v.calculation_id comparison_calculation_id FROM profile_revisions r JOIN profiles p USING(profile_id) JOIN raw_artifacts a ON a.artifact_id=r.raw_artifact_id
LEFT JOIN uncertainty_comparisons v ON v.profile_id=r.profile_id AND v.revision_sha256=r.revision_sha256 AND v.release_id=%s
WHERE r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL AND r.observed_at BETWEEN %s AND %s AND extract(year FROM r.observed_at)>2024
ORDER BY r.observed_at DESC,r.profile_id LIMIT %s""",
            (source["release_id"], start, now, policy["monitor_max_profiles"] + 1),
        ).fetchall()
        if len(candidates) > policy["monitor_max_profiles"]:
            return {
                "status": "monitor_budget_exceeded",
                "max_profiles": policy["monitor_max_profiles"],
            }
        strict = copy.deepcopy(source["training_policy"])
        strict["baseline"]["end_year"] = (
            2100  # Same D/adjusted/QC1 rules; monitoring admits post-test dates without fitting.
        )
        inputs, rows, skipped, pending = [], [], 0, 0
        comparison_ids = []
        for candidate in candidates:
            if candidate["result"] is None:
                pending += 1
                continue
            canonical_profile(candidate, s3)
            values = dict(
                candidate,
                observed_at=candidate["observed_at"].isoformat(),
                profile_id=str(candidate["profile_id"]),
                raw_sha256=candidate["raw_sha"],
            )
            labels, reason = snapshots.training_rows(values, strict)
            if reason:
                skipped += 1
                continue
            grid = standardize(labels, source["climate_policy"])
            predicted = {r["depth_m"]: r for r in candidate["result"]["rows"]}
            for row in grid:
                record = {
                    "profile_id": values["profile_id"],
                    "latitude": values["latitude"],
                    "longitude": values["longitude"],
                    "depth_m": row["depth_m"],
                }
                for v in VARIABLES:
                    record[v] = {**predicted[row["depth_m"]][v], "observed": row[v]}
                rows.append(record)
            inputs.append(
                evidence.input_ref(
                    candidate["profile_id"],
                    candidate["revision_sha256"],
                    candidate["raw_sha"],
                )
            )
            comparison_ids.append(str(candidate["comparison_calculation_id"]))
        report = {
            "schema_version": 1,
            "release_id": str(source["release_id"]),
            "checked_at": now.isoformat(),
            "window_start": start.isoformat(),
            "window_end": now.isoformat(),
            "candidate_profiles": len(candidates),
            "trusted_profiles": len(inputs),
            "skipped_untrusted_profiles": skipped,
            "pending_profiles": pending,
            "nominal_coverage": 1 - policy["alpha"],
            "coverage_unit": policy["calibration_unit"],
            "variables": {
                v: summarize(rows, v, source["climate_policy"], policy)
                for v in VARIABLES
            },
            "calibration_updated": False,
            "adaptation_policy": "Monitor all trusted outcomes, including misses and suspects. Suspects are excluded from any future adaptive candidate window; updates require a separate reviewed version. No automatic recalibration or retraining.",
            "release_approved": False,
        }
        calc = evidence.publish(
            s3,
            "uncertainty_monitor",
            source["manifest"]["method_version"],
            inputs,
            report,
            {
                "release_id": str(source["release_id"]),
                "expected_id": str(source["expected_id"]),
                "reference_id": str(source["reference_id"]),
                "comparison_calculation_ids": comparison_ids,
                "label_policy": "post-test D/adjusted QC1 monitor; original snapshot selection unchanged",
            },
            now.isoformat(),
            source["manifest"]["code_sha256"],
        )
        db.execute("SELECT pg_advisory_xact_lock(78192402)")
        valid = db.execute(
            "SELECT 1 FROM uncertainty_selection s JOIN uncertainty_releases u USING(release_id) JOIN expected_state_selection e ON e.release_id=u.expected_id JOIN climatology_selection c ON c.release_id=u.reference_id WHERE s.release_id=%s",
            (source["release_id"],),
        ).fetchone()
        for item in inputs:
            if not db.execute(
                "SELECT 1 FROM profile_revisions WHERE profile_id=%s AND revision_sha256=%s AND science_ready AND selected_at IS NOT NULL AND superseded_at IS NULL FOR UPDATE",
                (item["profile_id"], item["revision_sha256"]),
            ).fetchone():
                valid = False
                break
        if not valid:
            return {"status": "monitor_selection_changed"}
        db.execute(
            "UPDATE calculations SET state='stale' WHERE kind='uncertainty_monitor' AND state='current'"
        )
        evidence.record(db, calc, inputs)
        db.execute(
            "INSERT INTO uncertainty_health(release_id,checked_at,calculation_id,report) VALUES(%s,%s,%s,%s) ON CONFLICT(release_id) DO UPDATE SET checked_at=excluded.checked_at,calculation_id=excluded.calculation_id,report=excluded.report",
            (source["release_id"], now, calc["id"], Jsonb(report)),
        )
    return {
        "status": "monitored",
        "calculation_id": calc["id"],
        "trusted_profiles": len(inputs),
        "calibration_updated": False,
    }
