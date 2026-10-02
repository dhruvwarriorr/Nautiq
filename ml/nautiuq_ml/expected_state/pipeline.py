"""Explicit offline builds, immutable model manifests and local selection."""

import argparse
import io
import json
import logging
import os
import subprocess
import uuid
from pathlib import Path

import lightgbm
import pyarrow.parquet as pq
import sklearn
import scipy
from psycopg.types.json import Jsonb

from ..argo import evidence
from ..argo.storage import digest, put_immutable, read_object, store
from ..climatology import pipeline as climate
from .features import validate_profiles
from .model import METHOD, fit, load_policy

MAX_ARTIFACT = 32 * 1024 * 1024


def code_hash():
    return digest(
        b"\n".join(
            Path(__file__).with_name(name).read_bytes()
            for name in (
                "features.py",
                "model.py",
                "pipeline.py",
                "tracking.py",
                "serving.py",
                "jobs.py",
            )
        )
    )


def environment():
    return {
        **evidence.environment(),
        "lightgbm": lightgbm.__version__,
        "scikit_learn": sklearn.__version__,
        "scipy": scipy.__version__,
        "dependency_lock_sha256": digest(
            (
                Path(__file__).resolve().parents[2] / "requirements-expected.lock"
            ).read_bytes()
        ),
    }


def build(reference_id, policy_path, s3=None, *, track=True):
    policy = load_policy(policy_path)
    s3 = s3 or store()
    climate.verify(reference_id, s3)
    with climate.connect() as db:
        source = db.execute(
            "SELECT * FROM climatology_releases WHERE release_id=%s", (reference_id,)
        ).fetchone()
        snapshot = db.execute(
            "SELECT * FROM training_snapshots WHERE snapshot_id=%s",
            (source["snapshot_id"],),
        ).fetchone()
    if source["status"] != "ready":
        raise ValueError("climatology_reference_unsupported")
    reference = climate.release_bundle(source, s3)
    grid = pq.read_table(
        io.BytesIO(
            read_object(s3, source["grid_key"], source["grid_sha256"], limit=16777216)
        )
    ).to_pylist()
    for row in grid:
        row["coverage"] = json.loads(row["coverage"])
    training_policy = snapshot["manifest"]["policy"]["training_policy"]
    validate_profiles(grid, training_policy)
    result = fit(grid, reference, policy)
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
        "policy": policy,
        "climatology": reference,
        "reference_id": str(reference_id),
        "reference_bundle_sha256": source["bundle_sha256"],
        "snapshot_id": str(source["snapshot_id"]),
        "dataset_baseline": reference["dataset_baseline"],
        "fitting_period": reference["fitting_period"],
        "code_sha256": code_hash(),
        "source_git_commit": commit,
        "environment": environment(),
    }
    report = {k: v for k, v in bundle.items() if k not in ("models", "climatology")}
    data = evidence.canonical(bundle)
    report_data = evidence.canonical(report)
    if max(len(data), len(report_data)) > MAX_ARTIFACT:
        raise ValueError("expected_bundle_budget")
    identity = digest(
        evidence.canonical(
            {"bundle_sha256": digest(data), "report_sha256": digest(report_data)}
        )
    )
    rid = str(uuid.uuid5(uuid.NAMESPACE_URL, "expected-state|" + identity))
    prefix = f"lake/expected-state/{rid}/"
    put_immutable(s3, prefix + "bundle.json", data)
    put_immutable(s3, prefix + "report.json", report_data)
    output = {
        "release_id": rid,
        "release_sha256": identity,
        "reference_id": str(reference_id),
        "snapshot_id": str(source["snapshot_id"]),
        "bundle_key": prefix + "bundle.json",
        "bundle_sha256": digest(data),
        "report_key": prefix + "report.json",
        "report_sha256": digest(report_data),
        "model_count": len(result["models"]),
        "status": "ready" if result["models"] else "unsupported",
        "active_methods": {
            v: r["promotion"]["active_method"] for v, r in result["variables"].items()
        },
        "release_approved": False,
        "feature_version": policy["feature_version"],
        "fitting_period": reference["fitting_period"],
        "dataset_baseline": reference["dataset_baseline"],
    }
    calc = evidence.publish(
        s3,
        "expected_state_fit",
        METHOD,
        source["manifest"]["inputs"],
        output,
        {
            "expected_state_policy": policy,
            "reference_calculation_id": str(source["calculation_id"]),
            "reference_calculation_sha256": source["manifest"]["calculation_sha256"],
        },
        source["manifest"]["evaluation_time"],
        code_hash(),
    )
    with climate.connect() as db:
        evidence.record(db, calc, source["manifest"]["inputs"], "frozen")
        db.execute(
            """INSERT INTO expected_state_releases(release_id,release_sha256,reference_id,snapshot_id,calculation_id,manifest,bundle_key,bundle_sha256,report_key,report_sha256,report,status) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(release_sha256) DO NOTHING""",
            (
                rid,
                identity,
                reference_id,
                source["snapshot_id"],
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


def load_release(release_id, s3=None, *, current_code=True):
    s3 = s3 or store()
    with climate.connect() as db:
        release = db.execute(
            "SELECT * FROM expected_state_releases WHERE release_id=%s", (release_id,)
        ).fetchone()
        if not release:
            raise ValueError("expected_release_not_found")
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
        != {k: v for k, v in bundle.items() if k not in ("models", "climatology")}
    ):
        raise ValueError("expected_manifest_mismatch")
    if (
        bundle["release_approved"] is not False
        or bundle["method_version"] != METHOD
        or (
            current_code
            and (
                bundle["code_sha256"] != code_hash()
                or bundle["environment"] != environment()
                or bundle["climatology"]["code_sha256"] != climate.code_hash()
            )
        )
    ):
        raise ValueError("expected_bundle_version_mismatch")
    if (
        digest(evidence.canonical(bundle["climatology"]))
        != bundle["reference_bundle_sha256"]
    ):
        raise ValueError("expected_reference_checksum")
    policy = load_policy_data(bundle["policy"])
    if bundle["feature_schema"]["names"] != policy["features"]:
        raise ValueError("expected_feature_schema_mismatch")
    from .model import promotion

    for variable, model in bundle["models"].items():
        if digest(model["model_text"].encode()) != model["model_sha256"]:
            raise ValueError("expected_model_checksum")
        booster = lightgbm.Booster(model_str=model["model_text"])
        if booster.feature_name() != policy["features"]:
            raise ValueError("expected_model_features")
        if (
            promotion(bundle["variables"][variable], variable, policy)
            != bundle["variables"][variable]["promotion"]
        ):
            raise ValueError("expected_promotion_mismatch")
    return release, bundle


def load_policy_data(value):
    # Validate the bundled policy with the same parser without writing user-supplied files.
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as f:
        json.dump(value, f)
        f.flush()
        return load_policy(f.name)


def verify(release_id, s3=None):
    release, bundle = load_release(release_id, s3, current_code=False)
    return {
        "release_id": str(release_id),
        "verified": True,
        "current_code_compatible": bundle["code_sha256"] == code_hash()
        and bundle["environment"] == environment()
        and bundle["climatology"]["code_sha256"] == climate.code_hash(),
        "models": len(bundle["models"]),
        "active_methods": release["manifest"]["output"]["active_methods"],
        "release_approved": False,
    }


def select(release_id, s3=None):
    release, bundle = load_release(release_id, s3)
    if release["status"] != "ready":
        raise ValueError("expected_reference_unsupported")
    from .jobs import queue

    with climate.connect() as db:
        db.execute("SELECT pg_advisory_xact_lock(78192402)")
        if not db.execute(
            "SELECT 1 FROM climatology_selection WHERE release_id=%s",
            (release["reference_id"],),
        ).fetchone():
            raise ValueError("expected_climatology_selection_mismatch")
        db.execute(
            "UPDATE calculations SET state='stale' WHERE kind='expected_state_comparison' AND state='current' AND manifest->'policy'->>'release_id'<>%s",
            (str(release_id),),
        )
        db.execute(
            "INSERT INTO expected_state_selection(singleton,release_id) VALUES(true,%s) ON CONFLICT(singleton) DO UPDATE SET release_id=excluded.release_id,selected_at=clock_timestamp()",
            (release_id,),
        )
        rows = db.execute(
            "SELECT profile_id,revision_sha256 FROM profile_revisions WHERE science_ready AND selected_at IS NOT NULL AND superseded_at IS NULL ORDER BY profile_id LIMIT 2001"
        ).fetchall()
        if len(rows) > 2000:
            raise ValueError("expected_selection_budget")
        for row in rows:
            queue(db, row["profile_id"], row["revision_sha256"], release_id)
        db.execute(
            """UPDATE calculations c SET state='current' FROM expected_state_comparisons p JOIN profile_revisions r USING(profile_id,revision_sha256) WHERE p.calculation_id=c.calculation_id AND p.release_id=%s AND r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL""",
            (release_id,),
        )
    return {
        "selected_release_id": str(release_id),
        "profiles_queued": len(rows),
        "active_methods": release["manifest"]["output"]["active_methods"],
        "release_approved": False,
        "runtime_configuration": "Set ML_RELEASE_ID to this exact ID and restart ml-inference",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build_cmd = sub.add_parser("build")
    build_cmd.add_argument("reference_id")
    build_cmd.add_argument("--policy", default="/expected-state.json")
    for name in ("verify", "select", "log"):
        command = sub.add_parser(name)
        command.add_argument("release_id")
    command = sub.add_parser("maintain")
    command.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()
    try:
        if args.command == "build":
            result = build(args.reference_id, args.policy)
        elif args.command == "verify":
            result = verify(args.release_id)
        elif args.command == "select":
            result = select(args.release_id)
        elif args.command == "log":
            from .tracking import log_release

            release, bundle = load_release(args.release_id)
            result = log_release(release, bundle)
        else:
            from .jobs import recompute

            result = {"comparisons_completed": recompute(args.limit)}
    except ValueError as error:
        parser.exit(2, str(error) + "\n")
    except Exception:
        logging.error(
            "Expected-state task deferred; verify model, tracking and artifact readiness"
        )
        parser.exit(1)
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
