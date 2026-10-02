"""Frozen quantile/calibration bundles, explicit selection and independent tracking."""

import argparse
import io
import json
import logging
import os
import subprocess
import uuid
from pathlib import Path

import catboost
import pyarrow.parquet as pq
from psycopg.types.json import Jsonb

from ..argo import evidence
from ..argo.storage import digest, put_immutable, read_object, store
from ..climatology import pipeline as climate
from ..expected_state import pipeline as expected
from ..expected_state.features import NAMES, validate_profiles
from .quantiles import METHOD, coverage_gate, fit, load_policy, native, validate_policy

MAX_ARTIFACT = 32 * 1024 * 1024


def code_hash():
    return digest(
        b"\n".join(
            Path(__file__).with_name(n).read_bytes()
            for n in (
                "__init__.py",
                "calibration.py",
                "quantiles.py",
                "pipeline.py",
                "serving.py",
                "jobs.py",
                "monitoring.py",
                "tracking.py",
            )
        )
    )


def environment():
    return {
        **expected.environment(),
        "catboost": catboost.__version__,
        "uncertainty_dependency_lock_sha256": digest(
            (
                Path(__file__).resolve().parents[2] / "requirements-uncertainty.lock"
            ).read_bytes()
        ),
    }


def build(expected_id, policy_path, s3=None, track=True):
    p = load_policy(policy_path)
    s3 = s3 or store()
    parent, mean_bundle = expected.load_release(expected_id, s3)
    if parent["status"] != "ready":
        raise ValueError("uncertainty_expected_unsupported")
    with climate.connect() as db:
        ref = db.execute(
            "SELECT * FROM climatology_releases WHERE release_id=%s",
            (parent["reference_id"],),
        ).fetchone()
        snapshot = db.execute(
            "SELECT * FROM training_snapshots WHERE snapshot_id=%s",
            (parent["snapshot_id"],),
        ).fetchone()
    reference = climate.release_bundle(ref, s3)
    grid = pq.read_table(
        io.BytesIO(read_object(s3, ref["grid_key"], ref["grid_sha256"], limit=16777216))
    ).to_pylist()
    for row in grid:
        row["coverage"] = json.loads(row["coverage"])
    validate_profiles(grid, snapshot["manifest"]["policy"]["training_policy"])
    result = fit(grid, reference, p)
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
        "expected_state": mean_bundle,
        "expected_id": str(expected_id),
        "expected_bundle_sha256": parent["bundle_sha256"],
        "reference_id": str(ref["release_id"]),
        "snapshot_id": str(parent["snapshot_id"]),
        "climatology": reference,
        "reference_bundle_sha256": ref["bundle_sha256"],
        "fitting_period": reference["fitting_period"],
        "dataset_baseline": reference["dataset_baseline"],
        "calibration_period": {"start_year": 2020, "end_year": 2021},
        "code_sha256": code_hash(),
        "source_git_commit": commit,
        "environment": environment(),
    }
    report = {
        k: v
        for k, v in bundle.items()
        if k not in ("models", "climatology", "expected_state")
    }
    data, evaluated = evidence.canonical(bundle), evidence.canonical(report)
    if max(len(data), len(evaluated)) > MAX_ARTIFACT:
        raise ValueError("uncertainty_artifact_budget")
    identity = digest(
        evidence.canonical(
            {"bundle_sha256": digest(data), "report_sha256": digest(evaluated)}
        )
    )
    rid = str(uuid.uuid5(uuid.NAMESPACE_URL, "uncertainty|" + identity))
    prefix = f"lake/uncertainty/{rid}/"
    put_immutable(s3, prefix + "bundle.json", data)
    put_immutable(s3, prefix + "report.json", evaluated)
    supported = any(
        a["calibration"]["groups"]["global"]["correction"] is not None
        for families in result["models"].values()
        for a in families.values()
    )
    output = {
        "release_id": rid,
        "release_sha256": identity,
        "expected_id": str(expected_id),
        "reference_id": str(ref["release_id"]),
        "snapshot_id": str(parent["snapshot_id"]),
        "bundle_key": prefix + "bundle.json",
        "bundle_sha256": digest(data),
        "report_key": prefix + "report.json",
        "report_sha256": digest(evaluated),
        "status": "ready" if supported else "unsupported",
        "selected_families": {
            v: r.get("selected_family") for v, r in result["variables"].items()
        },
        "qualified": {
            v: r["coverage_gate"]["qualified"] for v, r in result["variables"].items()
        },
        "nominal_coverage": result["nominal_coverage"],
        "coverage_unit": result["coverage_unit"],
        "fitting_period": reference["fitting_period"],
        "calibration_period": bundle["calibration_period"],
        "release_approved": False,
    }
    calc = evidence.publish(
        s3,
        "uncertainty_fit",
        METHOD,
        parent["manifest"]["inputs"],
        output,
        {
            "uncertainty_policy": p,
            "expected_calculation_id": str(parent["calculation_id"]),
            "expected_bundle_sha256": parent["bundle_sha256"],
            "reference_calculation_id": str(ref["calculation_id"]),
            "grid_sha256": ref["grid_sha256"],
        },
        parent["manifest"]["evaluation_time"],
        code_hash(),
    )
    with climate.connect() as db:
        evidence.record(db, calc, parent["manifest"]["inputs"], "frozen")
        db.execute(
            "INSERT INTO uncertainty_releases(release_id,release_sha256,expected_id,reference_id,snapshot_id,calculation_id,manifest,bundle_key,bundle_sha256,report_key,report_sha256,report,status) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(release_sha256) DO NOTHING",
            (
                rid,
                identity,
                expected_id,
                ref["release_id"],
                parent["snapshot_id"],
                calc["id"],
                Jsonb(calc["manifest"]),
                output["bundle_key"],
                output["bundle_sha256"],
                output["report_key"],
                output["report_sha256"],
                Jsonb(report),
                output["status"],
            ),
        )
    summary = {"calculation_id": calc["id"], **output}
    if track:
        from .tracking import log_release

        summary["tracking"] = log_release(
            {
                "release_id": rid,
                "bundle_sha256": output["bundle_sha256"],
                "manifest": calc["manifest"],
            },
            bundle,
        )
    return summary


def load_release(release_id, s3=None, current_code=True):
    s3 = s3 or store()
    with climate.connect() as db:
        release = db.execute(
            "SELECT * FROM uncertainty_releases WHERE release_id=%s", (release_id,)
        ).fetchone()
        if not release:
            raise ValueError("uncertainty_release_not_found")
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
        or report
        != {
            k: v
            for k, v in bundle.items()
            if k not in ("models", "climatology", "expected_state")
        }
    ):
        raise ValueError("uncertainty_manifest_mismatch")
    validate_policy(bundle["policy"])
    if (
        bundle["method_version"] != METHOD
        or bundle["release_approved"] is not False
        or bundle["feature_schema"]["names"] != list(NAMES)
    ):
        raise ValueError("uncertainty_bundle_version_mismatch")
    if current_code and not compatible(bundle):
        raise ValueError("uncertainty_code_environment_mismatch")
    if (
        digest(evidence.canonical(bundle["expected_state"]))
        != bundle["expected_bundle_sha256"]
        or digest(evidence.canonical(bundle["climatology"]))
        != bundle["reference_bundle_sha256"]
    ):
        raise ValueError("uncertainty_parent_checksum")
    for v, families in bundle["models"].items():
        if (
            coverage_gate(bundle["variables"][v], v, bundle["policy"])
            != bundle["variables"][v]["coverage_gate"]
        ):
            raise ValueError("uncertainty_coverage_gate_mismatch")
        for artifact in families.values():
            if artifact["model_sha256"] != [
                digest(t.encode()) for t in artifact["model_texts"]
            ] or artifact["feature_names"] != list(NAMES):
                raise ValueError("uncertainty_native_checksum")
            model = native(artifact)
            names = (
                model[0].feature_name()
                if artifact["family"] == "lightgbm"
                else model.feature_names_
            )
            if names != list(NAMES):
                raise ValueError("uncertainty_native_features")
            if (
                artifact["calibration"]
                != bundle["variables"][v]["families"][artifact["family"]]["calibration"]
            ):
                raise ValueError("uncertainty_calibration_mismatch")
    return release, bundle


def compatible(bundle):
    return (
        bundle["code_sha256"] == code_hash()
        and bundle["environment"] == environment()
        and bundle["expected_state"]["code_sha256"] == expected.code_hash()
        and bundle["climatology"]["code_sha256"] == climate.code_hash()
    )


def verify(release_id, s3=None):
    release, bundle = load_release(release_id, s3, current_code=False)
    return {
        "release_id": str(release_id),
        "verified": True,
        "current_code_compatible": compatible(bundle),
        "status": release["status"],
        "selected_families": release["manifest"]["output"]["selected_families"],
        "release_approved": False,
    }


def select(release_id, s3=None):
    release, bundle = load_release(release_id, s3)
    if release["status"] != "ready":
        raise ValueError("uncertainty_calibration_unsupported")
    from .quantiles import benchmark_latency

    performance = benchmark_latency(bundle)
    if any(
        performance[v][info["selected_family"]]["p95_predict_ms"]
        > bundle["policy"]["max_predict_p95_ms"]
        for v, info in bundle["variables"].items()
        if info["status"] == "trained"
    ):
        raise ValueError("uncertainty_latency_budget")
    from .jobs import queue

    with climate.connect() as db:
        db.execute("SELECT pg_advisory_xact_lock(78192402)")
        if not db.execute(
            "SELECT 1 FROM expected_state_selection e JOIN climatology_selection c ON c.release_id=%s WHERE e.release_id=%s",
            (release["reference_id"], release["expected_id"]),
        ).fetchone():
            raise ValueError("uncertainty_parent_selection_mismatch")
        db.execute(
            "UPDATE calculations SET state='stale' WHERE kind IN ('uncertainty_comparison','uncertainty_monitor') AND state='current' AND manifest->'policy'->>'release_id'<>%s",
            (str(release_id),),
        )
        db.execute(
            "INSERT INTO uncertainty_selection(singleton,release_id) VALUES(true,%s) ON CONFLICT(singleton) DO UPDATE SET release_id=excluded.release_id,selected_at=clock_timestamp()",
            (release_id,),
        )
        db.execute(
            "UPDATE uncertainty_jobs SET status='obsolete',lease_until=NULL,lease_token=NULL,completed_at=clock_timestamp() WHERE release_id<>%s AND status IN ('pending','running')",
            (release_id,),
        )
        rows = db.execute(
            "SELECT profile_id,revision_sha256 FROM profile_revisions WHERE science_ready AND selected_at IS NOT NULL AND superseded_at IS NULL ORDER BY profile_id LIMIT 2001"
        ).fetchall()
        if len(rows) > 2000:
            raise ValueError("uncertainty_selection_budget")
        for row in rows:
            queue(db, row["profile_id"], row["revision_sha256"], release_id)
        db.execute(
            "UPDATE calculations c SET state='current' FROM uncertainty_comparisons p JOIN profile_revisions r USING(profile_id,revision_sha256) WHERE p.calculation_id=c.calculation_id AND p.release_id=%s AND r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL",
            (release_id,),
        )
    return {
        "selected_release_id": str(release_id),
        "profiles_queued": len(rows),
        "runtime_configuration": "Set UNCERTAINTY_RELEASE_ID to this exact ID and keep ML_RELEASE_ID equal to its expected_id, then restart ml-inference",
        "release_approved": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("build")
    command.add_argument("expected_id")
    command.add_argument("--policy", default="/uncertainty.json")
    for name in ("verify", "select", "log", "benchmark"):
        sub.add_parser(name).add_argument("release_id")
    sub.add_parser("maintain").add_argument("--limit", type=int, default=500)
    sub.add_parser("monitor")
    args = parser.parse_args()
    try:
        if args.command == "build":
            result = build(args.expected_id, args.policy)
        elif args.command == "verify":
            result = verify(args.release_id)
        elif args.command == "select":
            result = select(args.release_id)
        elif args.command in ("log", "benchmark"):
            release, bundle = load_release(args.release_id)
            if args.command == "log":
                from .tracking import log_release

                result = log_release(release, bundle)
            else:
                from .quantiles import benchmark_latency

                result = benchmark_latency(bundle)
        elif args.command == "monitor":
            from .monitoring import monitor

            result = monitor()
        else:
            from .jobs import recompute

            result = {"comparisons_completed": recompute(args.limit)}
    except ValueError as error:
        parser.exit(2, str(error) + "\n")
    except Exception:
        logging.error(
            "Uncertainty task deferred; verify model, tracking and artifact readiness"
        )
        parser.exit(1)
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
