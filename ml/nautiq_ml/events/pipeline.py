"""Explicit immutable event workflows, frozen snapshots, atomic publication and recovery."""

import argparse
import json
import os
from datetime import timezone

import numpy as np
from psycopg.types.json import Jsonb

from ..argo.storage import digest, put_immutable, read_object, store
from ..fields.core import canonical
from ..fields.pipeline import connection
from .core import (
    POLICY,
    METHOD,
    EventError,
    detect_thermal,
    fit_baseline,
    group_profiles,
    days,
)
from .providers import acquire
from .storage import (
    publish_dataset,
    load_dataset,
    calculation,
    identifier,
    code_hash,
    runtime,
    verify_calculation,
)


def profile_identities(rows):
    return {
        (
            str(p["profile_id"]),
            p["revision_sha256"],
            str(p["calculation_id"]) if p["calculation_id"] else None,
        )
        for p in rows
    }


def history(db, s3, start, end, bbox, offline=False, receipts=None, refresh=False):
    values, dates, lat, lon, raw = acquire(
        db, s3, start, end, bbox, offline, receipts, refresh
    )
    metadata = {
        "dates": dates,
        "bbox": list(bbox),
        "source": POLICY["source"],
        "raw": raw,
        "missing_cells": int(np.isnan(values).sum()),
        "shape": list(values.shape),
    }
    return publish_dataset(
        db, s3, "history", {"lat": lat, "lon": lon, "sst": values}, metadata
    )


def baseline(db, s3, did):
    row, arrays = load_dataset(db, s3, did, raw=True)
    if row["kind"] != "history":
        raise EventError("daily_history_required")
    fitted = fit_baseline(
        arrays["sst"],
        row["manifest"]["metadata"]["dates"],
        arrays["lat"],
        arrays["lon"],
    )
    return publish_dataset(
        db,
        s3,
        "baseline",
        {"lat": arrays["lat"], "lon": arrays["lon"], **fitted},
        {
            "baseline_years": POLICY["baseline_years"],
            "source": POLICY["source"],
            "supported_seasonal_cells": int(np.isfinite(fitted["threshold"]).sum()),
            "shape": list(fitted["mean"].shape),
        },
        str(did),
    )


def publish_run(
    db,
    s3,
    report,
    inputs,
    baseline_id=None,
    history_id=None,
    anomaly_id=None,
    strict=False,
    before_commit=None,
):
    identity = {
        "report": report,
        "inputs": inputs,
        "policy_sha256": digest(canonical(POLICY)),
        "code_sha256": code_hash(),
        "runtime": runtime(),
        "source_git_commit": os.environ.get("SOURCE_GIT_COMMIT", "unavailable"),
    }
    sha = digest(canonical(identity))
    rid = identifier(sha)
    output = json.loads(canonical(report))
    for event in output["events"]:
        event["event_id"] = identifier(sha + digest(canonical(event)))
    data = canonical(output)
    if len(data) > POLICY["limits"]["report_bytes"]:
        raise EventError("event_report_budget")
    key = "events/runs/" + sha + "/report.json"
    put_immutable(s3, key, data)
    manifest = {
        **{k: v for k, v in identity.items() if k != "report"},
        "run_id": rid,
        "run_sha256": sha,
        "report_sha256": digest(data),
    }
    with db.transaction():
        db.execute("SELECT pg_advisory_xact_lock(78192402)")
        if before_commit:
            before_commit()
        if strict:
            selected = db.execute(
                "SELECT 1 FROM anomaly_selection s JOIN anomaly_releases a USING(release_id) JOIN uncertainty_selection u ON u.release_id=a.uncertainty_id JOIN expected_state_selection e ON e.release_id=a.expected_id JOIN climatology_selection c ON c.release_id=a.reference_id WHERE s.release_id=%s",
                (anomaly_id,),
            ).fetchone()
            if not selected:
                raise EventError("profile_parent_changed_before_publication")
            west, south, east, north = report["extent"]
            current = db.execute(
                """SELECT r.profile_id,r.revision_sha256,c.calculation_id FROM profile_revisions r
LEFT JOIN anomaly_comparisons a ON a.profile_id=r.profile_id AND a.revision_sha256=r.revision_sha256 AND a.release_id=%s
LEFT JOIN calculations c ON c.calculation_id=a.calculation_id AND c.state='current'
WHERE r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL AND r.observed_at>=%s::date AND r.observed_at<%s::date+interval '1 day'
AND r.longitude BETWEEN %s AND %s AND r.latitude BETWEEN %s AND %s""",
                (anomaly_id, report["start"], report["end"], west, east, south, north),
            ).fetchall()
            if profile_identities(current) != profile_identities(inputs["profiles"]):
                raise EventError("profile_snapshot_changed_before_publication")
            for p in inputs["profiles"]:
                current = db.execute(
                    "SELECT 1 FROM profile_revisions r WHERE r.profile_id=%s AND r.revision_sha256=%s AND r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL",
                    (p["profile_id"], p["revision_sha256"]),
                ).fetchone()
                if not current:
                    raise EventError("profile_revision_changed_before_publication")
                if (
                    p["calculation_id"]
                    and not db.execute(
                        "SELECT 1 FROM calculations WHERE calculation_id=%s AND state='current'",
                        (p["calculation_id"],),
                    ).fetchone()
                ):
                    raise EventError("profile_comparison_stale_before_publication")
        cid = calculation(
            db,
            s3,
            "event_detection",
            inputs,
            {"run_id": rid, "report_sha256": digest(data), "release_approved": False},
        )
        db.execute(
            "INSERT INTO event_runs(run_id,run_sha256,kind,baseline_id,history_id,anomaly_id,calculation_id,manifest,report,report_key,report_sha256) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(run_sha256) DO NOTHING",
            (
                rid,
                sha,
                report["kind"],
                baseline_id,
                history_id,
                anomaly_id,
                cid,
                Jsonb(manifest),
                Jsonb(output),
                key,
                digest(data),
            ),
        )
        retained = db.execute(
            "SELECT report_sha256 FROM event_runs WHERE run_id=%s", (rid,)
        ).fetchone()
        if retained["report_sha256"] != digest(data):
            raise EventError("immutable_run_conflict")
        for event in output["events"]:
            db.execute(
                "INSERT INTO regional_events(event_id,run_id,kind,variable,start_day,end_day,geometry,evidence) VALUES(%s,%s,%s,%s,%s,%s,ST_SetSRID(ST_GeomFromGeoJSON(%s),4326),%s) ON CONFLICT(event_id) DO NOTHING",
                (
                    event["event_id"],
                    rid,
                    event["kind"],
                    event["variable"],
                    event["start"],
                    event["end"],
                    json.dumps(event["geometry"]),
                    Jsonb(event),
                ),
            )
        for p in inputs.get("profiles", []):
            db.execute(
                "INSERT INTO event_profile_inputs(run_id,profile_id,revision_sha256,calculation_id) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (rid, p["profile_id"], p["revision_sha256"], p["calculation_id"]),
            )
        db.execute(
            "INSERT INTO event_outbox(event_id,event_type,schema_version,aggregate_key,revision_sha256,payload) VALUES(%s,'regional.event.ready',1,%s,%s,%s) ON CONFLICT(event_id) DO NOTHING",
            (
                identifier("event:" + sha),
                "event-run:" + rid,
                sha,
                Jsonb(
                    {
                        "run_id": rid,
                        "report_sha256": digest(data),
                        "release_approved": False,
                    }
                ),
            ),
        )
    return {
        "run_id": rid,
        "kind": report["kind"],
        "calculation_id": cid,
        "report_sha256": digest(data),
        "event_count": len(output["events"]),
        "release_approved": False,
    }


def thermal(db, s3, baseline_id, history_id):
    b, base = load_dataset(db, s3, baseline_id, raw=True)
    h, values = load_dataset(db, s3, history_id, raw=True)
    if (
        b["kind"] != "baseline"
        or h["kind"] != "history"
        or b["manifest"]["policy_sha256"] != digest(canonical(POLICY))
    ):
        raise EventError("compatible_fixed_baseline_required")
    if not np.array_equal(base["lat"], values["lat"]) or not np.array_equal(
        base["lon"], values["lon"]
    ):
        raise EventError("baseline_history_native_grid_mismatch")
    report = detect_thermal(
        values["sst"],
        h["manifest"]["metadata"]["dates"],
        values["lat"],
        values["lon"],
        base,
    )
    report.update(
        baseline_id=str(baseline_id),
        history_id=str(history_id),
        source=POLICY["source"],
    )
    return publish_run(
        db,
        s3,
        report,
        {
            "baseline_id": str(baseline_id),
            "baseline_sha256": b["manifest_sha256"],
            "history_id": str(history_id),
            "history_sha256": h["manifest_sha256"],
        },
        str(baseline_id),
        str(history_id),
    )


def profiles(db, s3, anomaly_id, start, end, bbox):
    days(start, end, POLICY["limits"]["detection_days"])
    west, south, east, north = bbox
    from ..fields.providers import bbox_values

    bbox_values(bbox)
    with db.transaction():
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        as_of = (
            db.execute("SELECT transaction_timestamp() as as_of")
            .fetchone()["as_of"]
            .isoformat()
        )
        selected = db.execute(
            "SELECT a.* FROM anomaly_releases a JOIN anomaly_selection s USING(release_id) JOIN uncertainty_selection u ON u.release_id=a.uncertainty_id JOIN expected_state_selection e ON e.release_id=a.expected_id JOIN climatology_selection c ON c.release_id=a.reference_id WHERE a.release_id=%s AND a.status=%s",
            (anomaly_id, "ready"),
        ).fetchone()
        if not selected:
            raise EventError("exact_selected_profile_lineage_required")
        rows = db.execute(
            """SELECT p.profile_id,p.platform_id,r.revision_sha256,r.observed_at,r.latitude,r.longitude,c.calculation_id,c.manifest,c.manifest_key,c.manifest_sha256,a.result
FROM profiles p JOIN profile_revisions r USING(profile_id)
LEFT JOIN anomaly_comparisons a ON a.profile_id=r.profile_id AND a.revision_sha256=r.revision_sha256 AND a.release_id=%s
LEFT JOIN calculations c ON c.calculation_id=a.calculation_id AND c.state='current'
WHERE r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL AND r.observed_at>=%s::date AND r.observed_at<%s::date+interval '1 day'
AND r.longitude BETWEEN %s AND %s AND r.latitude BETWEEN %s AND %s ORDER BY r.observed_at,p.profile_id LIMIT 2001""",
            (anomaly_id, start, end, west, east, south, north),
        ).fetchall()
    if len(rows) > POLICY["limits"]["profiles"]:
        raise EventError("profile_snapshot_budget")
    read_object(s3, selected["bundle_key"], selected["bundle_sha256"], 64 * 1024 * 1024)
    points, inputs, reasons = (
        [],
        [],
        {"missing_comparison": 0, "missing_percentile": 0, "below_threshold": 0},
    )
    for r in rows:
        ref = {
            "profile_id": str(r["profile_id"]),
            "revision_sha256": r["revision_sha256"],
            "calculation_id": str(r["calculation_id"]) if r["calculation_id"] else None,
            "manifest_sha256": r["manifest_sha256"],
        }
        inputs.append(ref)
        if not r["calculation_id"]:
            reasons["missing_comparison"] += 1
            continue
        manifest = json.loads(
            read_object(
                s3,
                r["manifest_key"],
                r["manifest_sha256"],
                POLICY["limits"]["report_bytes"],
            )
        )
        if (
            canonical(manifest) != canonical(r["manifest"])
            or canonical(manifest["output"]) != canonical(r["result"])
            or manifest["policy"]["release_id"] != str(anomaly_id)
            or manifest["policy"]["bundle_sha256"] != selected["bundle_sha256"]
        ):
            raise EventError("profile_evidence_sql_lake_mismatch")
        for variable, v in r["result"]["variables"].items():
            rank = v.get("percentiles")
            percentile = rank["values"].get(POLICY["profile_lens"]) if rank else None
            if percentile is None:
                reasons["missing_percentile"] += 1
                continue
            if percentile < POLICY["profile_percentile"]:
                reasons["below_threshold"] += 1
                continue
            points.append(
                {
                    **ref,
                    "platform_id": r["platform_id"],
                    "latitude": float(r["latitude"]),
                    "longitude": float(r["longitude"]),
                    "day": r["observed_at"].astimezone(timezone.utc).date().isoformat(),
                    "observed_at": r["observed_at"].isoformat(),
                    "variable": variable,
                    "direction": "positive"
                    if v["max_signed_standardized_residual"] > 0
                    else "negative",
                    "percentile": percentile,
                    "intensity": v["score_evidence"]["scores"][POLICY["profile_lens"]],
                    "comparison_profiles": rank["profiles"],
                }
            )
    events = group_profiles(points)
    report = {
        "kind": "profile_groups",
        "method_version": METHOD,
        "status": "diagnostic",
        "start": start,
        "end": end,
        "extent": list(bbox),
        "as_of": as_of,
        "anomaly_id": str(anomaly_id),
        "events": events,
        "source_points": points,
        "coverage": {
            "queried_profiles": len(rows),
            "exceedance_variable_points": len(points),
            "reasons": reasons,
            "state": "sparse_profiles_not_dense_spatial_coverage",
        },
        "regional_groups": sum(
            e["kind"] == "regional_profile_candidate" for e in events
        ),
        "isolated_groups": sum(
            e["kind"] == "isolated_profile_anomalies" for e in events
        ),
        "release_approved": False,
        "limitations": POLICY["limitations"],
    }
    return publish_run(
        db,
        s3,
        report,
        {
            "anomaly_id": str(anomaly_id),
            "bundle_sha256": selected["bundle_sha256"],
            "profiles": inputs,
        },
        anomaly_id=str(anomaly_id),
        strict=True,
    )


def verify_run(db, s3, rid):
    row = db.execute("SELECT * FROM event_runs WHERE run_id=%s", (rid,)).fetchone()
    if not row:
        raise EventError("event_run_not_found")
    report = json.loads(
        read_object(
            s3,
            row["report_key"],
            row["report_sha256"],
            POLICY["limits"]["report_bytes"],
        )
    )
    if (
        canonical(report) != canonical(row["report"])
        or report["release_approved"] is not False
    ):
        raise EventError("event_report_sql_lake_mismatch")
    clean = json.loads(canonical(report))
    for event in clean["events"]:
        event.pop("event_id", None)
    manifest = row["manifest"]
    identity = {
        k: v
        for k, v in manifest.items()
        if k not in ("run_id", "run_sha256", "report_sha256")
    }
    identity["report"] = clean
    sha = digest(canonical(identity))
    if (
        sha != row["run_sha256"]
        or manifest["run_sha256"] != sha
        or manifest["run_id"] != str(row["run_id"])
        or manifest["report_sha256"] != row["report_sha256"]
        or row["report_key"] != "events/runs/" + sha + "/report.json"
        or report["kind"] != row["kind"]
    ):
        raise EventError("event_run_identity_mismatch")
    calc = verify_calculation(
        db,
        s3,
        row["calculation_id"],
        "event_detection",
        {
            "run_id": str(row["run_id"]),
            "report_sha256": row["report_sha256"],
            "release_approved": False,
        },
    )
    if canonical(calc["input"]) != canonical(manifest["inputs"]):
        raise EventError("event_run_inputs_mismatch")
    projected = db.execute(
        "SELECT event_id,evidence,variable,start_day,end_day,ST_AsBinary(geometry) geometry FROM regional_events WHERE run_id=%s",
        (rid,),
    ).fetchall()
    mirrors = {str(p["event_id"]): p for p in projected}
    if len(mirrors) != len(report["events"]):
        raise EventError("event_projection_mismatch")
    for event, bare in zip(report["events"], clean["events"]):
        p = mirrors.get(event["event_id"])
        if (
            event["event_id"] != identifier(sha + digest(canonical(bare)))
            or not p
            or canonical(p["evidence"]) != canonical(event)
            or p["variable"] != event["variable"]
            or p["start_day"].isoformat() != event["start"]
            or p["end_day"].isoformat() != event["end"]
        ):
            raise EventError("event_projection_mismatch")
        from shapely.geometry import shape
        from shapely import from_wkb

        if not from_wkb(bytes(p["geometry"])).equals(shape(event["geometry"])):
            raise EventError("event_geometry_mismatch")
    for did in (row["baseline_id"], row["history_id"]):
        if did:
            dataset, _ = load_dataset(db, s3, did, raw=True)
            key = "baseline" if did == row["baseline_id"] else "history"
            if (
                str(did) != manifest["inputs"][key + "_id"]
                or dataset["manifest_sha256"] != manifest["inputs"][key + "_sha256"]
            ):
                raise EventError("event_dataset_pin_mismatch")
    if row["kind"] == "profile_groups":
        parent = db.execute(
            "SELECT bundle_key,bundle_sha256 FROM anomaly_releases WHERE release_id=%s",
            (row["anomaly_id"],),
        ).fetchone()
        if (
            not parent
            or parent["bundle_sha256"] != manifest["inputs"]["bundle_sha256"]
            or str(row["anomaly_id"]) != manifest["inputs"]["anomaly_id"]
        ):
            raise EventError("profile_parent_pin_mismatch")
        read_object(s3, parent["bundle_key"], parent["bundle_sha256"], 64 * 1024 * 1024)
        projected = db.execute(
            "SELECT profile_id,revision_sha256,calculation_id FROM event_profile_inputs WHERE run_id=%s",
            (rid,),
        ).fetchall()
        if profile_identities(projected) != profile_identities(
            manifest["inputs"]["profiles"]
        ):
            raise EventError("profile_snapshot_projection_mismatch")
        for p in row["manifest"]["inputs"]["profiles"]:
            if p["calculation_id"]:
                calc = db.execute(
                    "SELECT * FROM calculations WHERE calculation_id=%s",
                    (p["calculation_id"],),
                ).fetchone()
                raw = read_object(
                    s3,
                    calc["manifest_key"],
                    p["manifest_sha256"],
                    POLICY["limits"]["report_bytes"],
                )
                if (
                    canonical(json.loads(raw)) != canonical(calc["manifest"])
                    or calc["manifest_sha256"] != p["manifest_sha256"]
                    or calc["manifest"]["policy"]["release_id"]
                    != str(row["anomaly_id"])
                    or calc["manifest"]["policy"]["bundle_sha256"]
                    != parent["bundle_sha256"]
                ):
                    raise EventError("profile_input_changed")
    return row, report


def maintain(db, s3):
    results = []
    for r in db.execute(
        "SELECT dataset_id FROM event_datasets ORDER BY created_at DESC LIMIT 500"
    ).fetchall():
        try:
            load_dataset(db, s3, r["dataset_id"], raw=True)
            state = "ready"
        except Exception:
            state = "unavailable"
        db.execute(
            "UPDATE event_datasets SET status=%s WHERE dataset_id=%s",
            (state, r["dataset_id"]),
        )
        results.append({"dataset_id": str(r["dataset_id"]), "status": state})
    for r in db.execute(
        "SELECT run_id FROM event_runs ORDER BY created_at DESC LIMIT 500"
    ).fetchall():
        try:
            verify_run(db, s3, r["run_id"])
            state = "ready"
        except Exception:
            state = "unavailable"
        db.execute(
            "UPDATE event_runs SET status=%s WHERE run_id=%s", (state, r["run_id"])
        )
        results.append({"run_id": str(r["run_id"]), "status": state})
    return results


def replay(db, s3, rid):
    row, report = verify_run(db, s3, rid)
    if row["kind"] == "surface_thermal":
        return thermal(db, s3, row["baseline_id"], row["history_id"])
    report["events"] = group_profiles(report["source_points"])
    return publish_run(
        db, s3, report, row["manifest"]["inputs"], anomaly_id=str(row["anomaly_id"])
    )


def main():
    parser = argparse.ArgumentParser(
        description="Nautiq fixed-reference regional event diagnostics"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    h = sub.add_parser("history")
    h.add_argument("--start", required=True)
    h.add_argument("--end", required=True)
    h.add_argument("--bbox", nargs=4, type=float, default=POLICY["pilot_bbox"])
    h.add_argument(
        "--refresh",
        action="store_true",
        help="Fetch a new source revision; retained datasets stay immutable",
    )
    b = sub.add_parser("baseline")
    b.add_argument("dataset_id")
    t = sub.add_parser("thermal")
    t.add_argument("baseline_id")
    t.add_argument("history_id")
    p = sub.add_parser("profiles")
    p.add_argument("anomaly_id")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--bbox", nargs=4, type=float, default=[50, -10, 100, 30])
    for name in ("verify", "replay"):
        s = sub.add_parser(name)
        s.add_argument("run_id")
    for name in ("verify-dataset", "replay-dataset"):
        s = sub.add_parser(name)
        s.add_argument("dataset_id")
    sub.add_parser("maintain")
    args = parser.parse_args()
    with connection() as db:
        s3 = store()
        if args.command == "history":
            result = history(
                db, s3, args.start, args.end, args.bbox, refresh=args.refresh
            )
        elif args.command == "baseline":
            result = baseline(db, s3, args.dataset_id)
        elif args.command == "thermal":
            result = thermal(db, s3, args.baseline_id, args.history_id)
        elif args.command == "profiles":
            result = profiles(db, s3, args.anomaly_id, args.start, args.end, args.bbox)
        elif args.command == "replay":
            result = replay(db, s3, args.run_id)
        elif args.command == "maintain":
            result = maintain(db, s3)
        elif args.command in ("verify-dataset", "replay-dataset"):
            r, _ = load_dataset(db, s3, args.dataset_id, raw=True)
            if args.command == "verify-dataset":
                result = {
                    "dataset_id": str(r["dataset_id"]),
                    "manifest_sha256": r["manifest_sha256"],
                    "verified": True,
                }
            elif r["kind"] == "baseline":
                result = baseline(db, s3, r["parent_id"])
            else:
                m = r["manifest"]["metadata"]
                result = history(
                    db,
                    s3,
                    m["dates"][0],
                    m["dates"][-1],
                    m["bbox"],
                    offline=True,
                    receipts=m["raw"],
                )
        else:
            r, report = verify_run(db, s3, args.run_id)
            result = {
                "run_id": str(r["run_id"]),
                "report_sha256": r["report_sha256"],
                "event_count": len(report["events"]),
            }
    print(json.dumps(result, default=str, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
