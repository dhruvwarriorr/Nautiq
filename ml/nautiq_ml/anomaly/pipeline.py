"""Immutable diagnostic anomaly releases with explicit four-generation lineage."""

import argparse
import io
import json
import os
import subprocess
import uuid
from pathlib import Path

import pyarrow.parquet as pq
from psycopg.types.json import Jsonb

from ..argo import evidence
from ..argo.storage import digest, put_immutable, read_object, store
from ..climatology.pipeline import connect
from ..uncertainty import pipeline as uncertainty
from . import METHOD
from .model import benchmark_latency, fit, load_policy, validate_policy

MAX_ARTIFACT = 48 * 1024 * 1024
EXCLUDE = ("models", "uncertainty")


def code_hash():
    return digest(
        b"\n".join(
            Path(__file__).with_name(n).read_bytes()
            for n in (
                "__init__.py",
                "model.py",
                "pipeline.py",
                "serving.py",
                "jobs.py",
                "tracking.py",
            )
        )
    )


def report_for(bundle):
    return {k: v for k, v in bundle.items() if k not in EXCLUDE}


def build(uncertainty_id, policy_path, s3=None, track=True):
    p = load_policy(policy_path)
    s3 = s3 or store()
    parent, parent_bundle = uncertainty.load_release(uncertainty_id, s3)
    if parent["status"] != "ready":
        raise ValueError("anomaly_parent_unsupported")
    with connect() as db:
        ref = db.execute(
            "SELECT * FROM climatology_releases WHERE release_id=%s",
            (parent["reference_id"],),
        ).fetchone()
    grid = pq.read_table(
        io.BytesIO(read_object(s3, ref["grid_key"], ref["grid_sha256"], limit=16777216))
    ).to_pylist()
    for r in grid:
        r["coverage"] = json.loads(r["coverage"])
    result = fit(grid, parent_bundle, p)
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = os.environ.get("SOURCE_GIT_COMMIT", "unavailable")
    bundle = {
        **result,
        "schema_version": 1,
        "method_version": METHOD,
        "policy": p,
        "uncertainty": parent_bundle,
        "uncertainty_id": str(uncertainty_id),
        "uncertainty_bundle_sha256": parent["bundle_sha256"],
        "expected_id": str(parent["expected_id"]),
        "reference_id": str(parent["reference_id"]),
        "snapshot_id": str(parent["snapshot_id"]),
        "fitting_period": parent_bundle["fitting_period"],
        "calibration_period": parent_bundle["calibration_period"],
        "dataset_baseline": parent_bundle["dataset_baseline"],
        "code_sha256": code_hash(),
        "source_git_commit": commit,
        "environment": uncertainty.environment(),
    }
    data, report = evidence.canonical(bundle), evidence.canonical(report_for(bundle))
    if max(len(data), len(report)) > MAX_ARTIFACT:
        raise ValueError("anomaly_artifact_budget")
    identity = digest(
        evidence.canonical(
            {"bundle_sha256": digest(data), "report_sha256": digest(report)}
        )
    )
    rid = str(uuid.uuid5(uuid.NAMESPACE_URL, "anomaly|" + identity))
    prefix = f"lake/anomaly/{rid}/"
    put_immutable(s3, prefix + "bundle.json", data)
    put_immutable(s3, prefix + "report.json", report)
    output = {
        "release_id": rid,
        "release_sha256": identity,
        "uncertainty_id": str(uncertainty_id),
        "expected_id": bundle["expected_id"],
        "reference_id": bundle["reference_id"],
        "snapshot_id": bundle["snapshot_id"],
        "bundle_key": prefix + "bundle.json",
        "bundle_sha256": digest(data),
        "report_key": prefix + "report.json",
        "report_sha256": digest(report),
        "status": "ready" if result["models"] else "unsupported",
        "release_approved": False,
        "depths_m": p["depths_m"],
        "coverage_policy": p["coverage_policy"],
        "scale_estimator": p["scale_estimator"],
        "supported_variables": list(result["models"]),
    }
    inputs = parent["manifest"]["inputs"]
    calc = evidence.publish(
        s3,
        "anomaly_fit",
        METHOD,
        inputs,
        output,
        {
            "anomaly_policy": p,
            "uncertainty_calculation_id": str(parent["calculation_id"]),
            "uncertainty_bundle_sha256": parent["bundle_sha256"],
            "grid_sha256": ref["grid_sha256"],
        },
        parent["manifest"]["evaluation_time"],
        code_hash(),
    )
    with connect() as db:
        evidence.record(db, calc, inputs, "frozen")
        db.execute(
            "INSERT INTO anomaly_releases(release_id,release_sha256,uncertainty_id,expected_id,reference_id,snapshot_id,calculation_id,manifest,bundle_key,bundle_sha256,report_key,report_sha256,report,status) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(release_sha256) DO NOTHING",
            (
                rid,
                identity,
                uncertainty_id,
                parent["expected_id"],
                parent["reference_id"],
                parent["snapshot_id"],
                calc["id"],
                Jsonb(calc["manifest"]),
                output["bundle_key"],
                output["bundle_sha256"],
                output["report_key"],
                output["report_sha256"],
                Jsonb(report_for(bundle)),
                output["status"],
            ),
        )
    summary = {"calculation_id": calc["id"], **output}
    if track:
        from .tracking import log_release

        summary["tracking"] = log_release(
            {**output, "manifest": calc["manifest"]}, bundle
        )
    return summary


def compatible(bundle):
    return (
        bundle["code_sha256"] == code_hash()
        and bundle["environment"] == uncertainty.environment()
        and uncertainty.compatible(bundle["uncertainty"])
    )


def load_release(release_id, s3=None, current_code=True):
    s3 = s3 or store()
    with connect() as db:
        release = db.execute(
            "SELECT * FROM anomaly_releases WHERE release_id=%s", (release_id,)
        ).fetchone()
        if not release:
            raise ValueError("anomaly_release_not_found")
        calc = db.execute(
            "SELECT * FROM calculations WHERE calculation_id=%s",
            (release["calculation_id"],),
        ).fetchone()
    bundle = json.loads(
        read_object(
            s3, release["bundle_key"], release["bundle_sha256"], limit=MAX_ARTIFACT
        )
    )
    report = json.loads(
        read_object(
            s3, release["report_key"], release["report_sha256"], limit=MAX_ARTIFACT
        )
    )
    manifest = json.loads(
        read_object(
            s3, calc["manifest_key"], calc["manifest_sha256"], limit=MAX_ARTIFACT
        )
    )
    if (
        manifest != release["manifest"]
        or report != release["report"]
        or report != report_for(bundle)
    ):
        raise ValueError("anomaly_manifest_mismatch")
    validate_policy(bundle["policy"])
    if (
        bundle["method_version"] != METHOD
        or bundle["release_approved"] is not False
        or bundle["depths_m"] != bundle["policy"]["depths_m"]
    ):
        raise ValueError("anomaly_bundle_version_mismatch")
    if (
        digest(evidence.canonical(bundle["uncertainty"]))
        != bundle["uncertainty_bundle_sha256"]
    ):
        raise ValueError("anomaly_parent_checksum")
    parent, _ = uncertainty.load_release(
        release["uncertainty_id"], s3, current_code=current_code
    )
    if (
        parent["bundle_sha256"] != bundle["uncertainty_bundle_sha256"]
        or any(
            str(release[k]) != bundle[k]
            for k in ("uncertainty_id", "expected_id", "reference_id", "snapshot_id")
        )
        or any(
            release[k] != parent[k]
            for k in ("expected_id", "reference_id", "snapshot_id")
        )
    ):
        raise ValueError("anomaly_parent_lineage_mismatch")
    if current_code and not compatible(bundle):
        raise ValueError("anomaly_code_environment_mismatch")
    return release, bundle


def verify(release_id, s3=None):
    release, bundle = load_release(release_id, s3, current_code=False)
    return {
        "release_id": str(release_id),
        "verified": True,
        "current_code_compatible": compatible(bundle),
        "status": release["status"],
        "release_approved": False,
    }


def select(release_id, s3=None):
    release, bundle = load_release(release_id, s3)
    if release["status"] != "ready":
        raise ValueError("anomaly_model_unsupported")
    if any(
        v["p95_score_ms"] > bundle["policy"]["max_predict_p95_ms"]
        for v in benchmark_latency(bundle).values()
    ):
        raise ValueError("anomaly_latency_budget")
    from .jobs import queue

    with connect() as db:
        db.execute("SELECT pg_advisory_xact_lock(78192402)")
        if not db.execute(
            "SELECT 1 FROM uncertainty_selection u JOIN expected_state_selection e ON e.release_id=%s JOIN climatology_selection c ON c.release_id=%s WHERE u.release_id=%s",
            (
                release["expected_id"],
                release["reference_id"],
                release["uncertainty_id"],
            ),
        ).fetchone():
            raise ValueError("anomaly_parent_selection_mismatch")
        db.execute(
            "INSERT INTO anomaly_selection(singleton,release_id) VALUES(true,%s) ON CONFLICT(singleton) DO UPDATE SET release_id=excluded.release_id,selected_at=clock_timestamp()",
            (release_id,),
        )
        db.execute(
            "UPDATE anomaly_jobs SET status='obsolete',lease_until=NULL,lease_token=NULL,completed_at=clock_timestamp() WHERE release_id<>%s AND status IN ('pending','running')",
            (release_id,),
        )
        rows = db.execute(
            "SELECT profile_id,revision_sha256 FROM profile_revisions WHERE science_ready AND selected_at IS NOT NULL AND superseded_at IS NULL ORDER BY profile_id LIMIT 2001"
        ).fetchall()
        if len(rows) > 2000:
            raise ValueError("anomaly_selection_budget")
        for row in rows:
            queue(db, row["profile_id"], row["revision_sha256"], release_id)
    return {
        "selected_release_id": str(release_id),
        "profiles_queued": len(rows),
        "runtime_configuration": "Set ANOMALY_RELEASE_ID to this exact ID and retain its UNCERTAINTY_RELEASE_ID and ML_RELEASE_ID parent pins; restart ml-inference",
        "release_approved": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("build")
    command.add_argument("uncertainty_id")
    command.add_argument("--policy", default="/anomaly.json")
    for name in ("verify", "select", "log", "benchmark"):
        sub.add_parser(name).add_argument("release_id")
    sub.add_parser("maintain").add_argument("--limit", type=int, default=500)
    args = parser.parse_args()
    if args.command == "build":
        result = build(args.uncertainty_id, args.policy)
    elif args.command == "verify":
        result = verify(args.release_id)
    elif args.command == "select":
        result = select(args.release_id)
    elif args.command == "maintain":
        from .jobs import recompute

        result = {"comparisons_completed": recompute(args.limit)}
    else:
        release, bundle = load_release(args.release_id)
        if args.command == "benchmark":
            result = benchmark_latency(bundle)
        else:
            from .tracking import log_release

            result = log_release(release, bundle)
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
