"""Immutable climatology bundles and revision/selection-safe comparison jobs."""

import argparse
import io
import json
import logging
import os
import uuid
from contextlib import contextmanager
from pathlib import Path

import psycopg
import pyarrow as pa
import pyarrow.parquet as pq
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..argo import evidence
from ..argo.parser import InvalidProfile
from ..argo.snapshots import split
from ..argo.storage import digest, put_immutable, read_object, store
from .grid import VARIABLES, profile_grid, standardize
from .model import METHOD, compare, evaluate, fit, load_policy


def code_hash():
    return digest(
        b"\n".join(
            Path(__file__).with_name(name).read_bytes()
            for name in ("grid.py", "model.py", "pipeline.py")
        )
    )


@contextmanager
def connect():
    with psycopg.connect(
        os.environ["DATABASE_URL"], row_factory=dict_row, connect_timeout=5
    ) as db:
        db.execute("SET statement_timeout='30s'; SET lock_timeout='5s'")
        yield db


def grid_bytes(grid):
    schema = pa.schema(
        [
            (
                key,
                pa.float64()
                if key in ("latitude", "longitude", "depth_m", *VARIABLES)
                else pa.string(),
            )
            for key in (
                "profile_id",
                "revision_sha256",
                "raw_sha256",
                "platform_id",
                "observed_at",
                "latitude",
                "longitude",
                "split",
                "depth_m",
                *VARIABLES,
                "coverage",
                "grid_version",
            )
        ]
    )
    rows = [
        dict(row, coverage=evidence.canonical(row["coverage"]).decode()) for row in grid
    ]
    stream = io.BytesIO()
    pq.write_table(
        pa.Table.from_pylist(rows, schema=schema),
        stream,
        compression="zstd",
        version="2.6",
    )
    data = stream.getvalue()
    if len(data) > 16777216:
        raise ValueError("climatology_grid_budget")
    return data


def build(snapshot_id, policy_path, s3=None):
    policy = load_policy(policy_path)
    s3 = s3 or store()
    with connect() as db:
        source = db.execute(
            "SELECT * FROM training_snapshots WHERE snapshot_id=%s", (snapshot_id,)
        ).fetchone()
    if not source:
        raise ValueError("training_snapshot_not_found")
    manifest = json.loads(
        read_object(
            s3, source["manifest_key"], source["manifest_sha256"], limit=16777216
        )
    )
    if (
        manifest != source["manifest"]
        or manifest["output"]["representation"] != "original_levels_no_interpolation"
    ):
        raise ValueError("snapshot_manifest_mismatch")
    training_policy = manifest["policy"]["training_policy"]
    if policy["domain"] != training_policy["domain"]:
        raise ValueError("snapshot_domain_mismatch")
    rows = pq.read_table(
        io.BytesIO(
            read_object(
                s3, source["parquet_key"], source["parquet_sha256"], limit=134217728
            )
        )
    ).to_pylist()
    if (
        len(rows) != source["row_count"]
        or len({r["profile_id"] for r in rows}) != source["profile_count"]
    ):
        raise ValueError("snapshot_counts_mismatch")
    for row in rows:
        if (
            split(row["observed_at"], training_policy) != row["split"]
            or row["training_qc_version"] != training_policy["qc_version"]
        ):
            raise ValueError("snapshot_split_or_qc_mismatch")
    refs = {i["profile_id"]: i for i in manifest["inputs"]}
    for row in rows:
        ref = refs.get(row["profile_id"])
        if not ref or any(row[k] != ref[k] for k in ("revision_sha256", "raw_sha256")):
            raise ValueError("snapshot_input_mismatch")
    grid = standardize(rows, policy)
    bundle = fit(grid, policy)
    evaluation = evaluate(grid, bundle)
    bundle.update(
        dataset_snapshot_id=str(snapshot_id),
        dataset_snapshot_sha256=source["snapshot_sha256"],
        dataset_baseline=training_policy["baseline"],
        fitting_period={
            "start_year": training_policy["baseline"]["start_year"],
            "end_year": training_policy["splits"]["train_end"],
        },
        code_sha256=code_hash(),
        environment=evidence.environment(),
    )
    encoded = evidence.canonical(bundle)
    grid_data = grid_bytes(grid)
    evaluated = evidence.canonical(evaluation)
    if max(len(encoded), len(evaluated)) > 16777216:
        raise ValueError("climatology_bundle_budget")
    identity = digest(
        evidence.canonical(
            {
                "bundle_sha256": digest(encoded),
                "grid_sha256": digest(grid_data),
                "evaluation_sha256": digest(evaluated),
            }
        )
    )
    rid = str(uuid.uuid5(uuid.NAMESPACE_URL, "climatology|" + identity))
    prefix = f"lake/climatology/{rid}/"
    for name, data in (
        ("bundle.json", encoded),
        ("standard-grid.parquet", grid_data),
        ("evaluation.json", evaluated),
    ):
        put_immutable(s3, prefix + name, data)
    output = {
        "release_id": rid,
        "release_sha256": identity,
        "snapshot_id": str(snapshot_id),
        "fit_hash": bundle["fit_hash"],
        "standard_grid_rows": len(grid),
        "profile_count": source["profile_count"],
        "model_count": len(bundle["models"]),
        "bundle_key": prefix + "bundle.json",
        "bundle_sha256": digest(encoded),
        "grid_key": prefix + "standard-grid.parquet",
        "grid_sha256": digest(grid_data),
        "evaluation_key": prefix + "evaluation.json",
        "evaluation_sha256": digest(evaluated),
        "fitting_period": bundle["fitting_period"],
        "dataset_baseline": bundle["dataset_baseline"],
        "support_models": [
            {
                "model_key": key,
                **{
                    k: m[k]
                    for k in (
                        "profile_count",
                        "platform_count",
                        "months",
                        "years",
                        "depth_range",
                        "latitude_range",
                        "longitude_range",
                    )
                },
            }
            for key, m in sorted(bundle["models"].items())
        ],
        "status": "ready" if bundle["models"] else "unsupported",
        "release_approved": False,
        "limitations": [
            "Local prototype; cadence, representative coastal coverage, spatial/platform independence and scientific release validation remain unverified.",
            bundle["spread_interpretation"],
        ],
    }
    calc = evidence.publish(
        s3,
        "climatology_fit",
        METHOD,
        manifest["inputs"],
        output,
        {
            "climatology_policy": policy,
            "training_policy": training_policy,
            "source_snapshot_calculation_id": manifest["calculation_id"],
            "source_snapshot_manifest_sha256": source["manifest_sha256"],
        },
        manifest["evaluation_time"],
        code_hash(),
    )
    with connect() as db:
        evidence.record(db, calc, manifest["inputs"], "frozen")
        db.execute(
            """INSERT INTO climatology_releases(release_id,release_sha256,snapshot_id,calculation_id,manifest,bundle_key,bundle_sha256,grid_key,grid_sha256,evaluation_key,evaluation_sha256,evaluation,status)
VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(release_sha256) DO NOTHING""",
            (
                rid,
                identity,
                snapshot_id,
                calc["id"],
                Jsonb(calc["manifest"]),
                output["bundle_key"],
                output["bundle_sha256"],
                output["grid_key"],
                output["grid_sha256"],
                output["evaluation_key"],
                output["evaluation_sha256"],
                Jsonb(evaluation),
                output["status"],
            ),
        )
    return {"release_id": rid, "calculation_id": calc["id"], **output}


def release_bundle(release, s3):
    bundle = json.loads(
        read_object(s3, release["bundle_key"], release["bundle_sha256"], limit=16777216)
    )
    if (
        bundle["method_version"] != METHOD
        or bundle["code_sha256"] != code_hash()
        or bundle["release_approved"] is not False
    ):
        raise ValueError("climatology_bundle_version_mismatch")
    return bundle


def verify(release_id, s3=None):
    s3 = s3 or store()
    with connect() as db:
        release = db.execute(
            "SELECT * FROM climatology_releases WHERE release_id=%s", (release_id,)
        ).fetchone()
        if not release:
            raise ValueError("climatology_release_not_found")
        calc = db.execute(
            "SELECT * FROM calculations WHERE calculation_id=%s",
            (release["calculation_id"],),
        ).fetchone()
    bundle = release_bundle(release, s3)
    stored = json.loads(
        read_object(s3, calc["manifest_key"], calc["manifest_sha256"], limit=16777216)
    )
    if stored != release["manifest"]:
        raise ValueError("climatology_manifest_mismatch")
    grid = pq.read_table(
        io.BytesIO(
            read_object(s3, release["grid_key"], release["grid_sha256"], limit=16777216)
        )
    )
    evaluation = json.loads(
        read_object(
            s3, release["evaluation_key"], release["evaluation_sha256"], limit=16777216
        )
    )
    if (
        evaluation != release["evaluation"]
        or len(grid) != stored["output"]["standard_grid_rows"]
    ):
        raise ValueError("climatology_artifact_mismatch")
    return {
        "release_id": str(release_id),
        "verified": True,
        "models": len(bundle["models"]),
        "standard_grid_rows": len(grid),
    }


def queue(db, profile_id, revision, release_id=None):
    if release_id is None:
        selected = db.execute(
            "SELECT release_id FROM climatology_selection WHERE singleton"
        ).fetchone()
        if not selected:
            return
        release_id = (
            selected[0] if not isinstance(selected, dict) else selected["release_id"]
        )
    jid = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL, f"climatology-job|{profile_id}|{revision}|{release_id}"
        )
    )
    db.execute(
        """INSERT INTO climatology_jobs(job_id,profile_id,revision_sha256,release_id) VALUES(%s,%s,%s,%s)
ON CONFLICT(profile_id,revision_sha256,release_id) DO UPDATE SET status='pending',lease_until=NULL,lease_token=NULL,next_attempt_at=clock_timestamp(),completed_at=NULL,reason_code=NULL
WHERE climatology_jobs.status='obsolete' AND EXISTS(SELECT 1 FROM profile_revisions r JOIN climatology_selection s ON s.release_id=excluded.release_id
WHERE r.profile_id=excluded.profile_id AND r.revision_sha256=excluded.revision_sha256 AND r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL)""",
        (jid, profile_id, revision, release_id),
    )


def select(release_id, s3=None):
    s3 = s3 or store()
    verify(release_id, s3)
    with connect() as db:
        db.execute("SELECT pg_advisory_xact_lock(78192402)")
        release = db.execute(
            "SELECT status FROM climatology_releases WHERE release_id=%s", (release_id,)
        ).fetchone()
        if release["status"] != "ready":
            raise ValueError("climatology_reference_unsupported")
        db.execute(
            """UPDATE calculations SET state='stale' WHERE kind='climatology_comparison' AND state='current' AND manifest->'policy'->>'release_id'<>%s""",
            (str(release_id),),
        )
        db.execute(
            "INSERT INTO climatology_selection(singleton,release_id) VALUES(true,%s) ON CONFLICT(singleton) DO UPDATE SET release_id=excluded.release_id,selected_at=clock_timestamp()",
            (release_id,),
        )
        rows = db.execute(
            "SELECT profile_id,revision_sha256 FROM profile_revisions WHERE science_ready AND selected_at IS NOT NULL AND superseded_at IS NULL ORDER BY profile_id LIMIT 2001"
        ).fetchall()
        if len(rows) > 2000:
            raise ValueError("climatology_selection_budget")
        for row in rows:
            queue(db, row["profile_id"], row["revision_sha256"], release_id)
        # Re-selecting an already computed frozen reference restores accurate live evidence state.
        db.execute(
            """UPDATE calculations c SET state='current' FROM climatology_comparisons p JOIN profile_revisions r USING(profile_id,revision_sha256)
WHERE p.calculation_id=c.calculation_id AND p.release_id=%s AND r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL""",
            (release_id,),
        )
    return {
        "selected_release_id": str(release_id),
        "profiles_queued": len(rows),
        "release_approved": False,
    }


def recompute(limit=10, s3=None):
    if not 1 <= limit <= 2000:
        raise ValueError("climatology_job_budget")
    s3 = s3 or store()
    bundles = {}
    completed = 0
    for _ in range(limit):
        token = str(uuid.uuid4())
        with connect() as db:
            job = db.execute(
                """WITH picked AS (SELECT job_id FROM climatology_jobs WHERE status IN ('pending','running') AND next_attempt_at<=now() AND (lease_until IS NULL OR lease_until<now())
ORDER BY created_at,job_id FOR UPDATE SKIP LOCKED LIMIT 1)
UPDATE climatology_jobs j SET status='running',lease_token=%s,lease_until=now()+interval '60 seconds',attempts=attempts+1 FROM picked p WHERE j.job_id=p.job_id RETURNING j.*""",
                (token,),
            ).fetchone()
        if not job:
            break
        try:
            with connect() as db:
                row = db.execute(
                    """SELECT p.platform_id,r.*,a.sha256 raw_sha,a.object_key FROM profile_revisions r JOIN profiles p USING(profile_id) JOIN raw_artifacts a ON a.artifact_id=r.raw_artifact_id
JOIN climatology_selection s ON s.release_id=%s WHERE r.profile_id=%s AND r.revision_sha256=%s AND r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL""",
                    (job["release_id"], job["profile_id"], job["revision_sha256"]),
                ).fetchone()
                if not row:
                    db.execute(
                        "UPDATE climatology_jobs SET status='obsolete',lease_until=NULL,completed_at=now() WHERE job_id=%s AND lease_token=%s",
                        (job["job_id"], token),
                    )
                    continue
                rid = str(job["release_id"])
                if rid not in bundles:
                    release = db.execute(
                        "SELECT * FROM climatology_releases WHERE release_id=%s", (rid,)
                    ).fetchone()
                    bundles[rid] = (release, release_bundle(release, s3))
                release, bundle = bundles[rid]
                read_object(s3, row["object_key"], row["raw_sha"])
                pinned = pq.read_table(
                    io.BytesIO(
                        read_object(s3, row["parquet_key"], row["parquet_sha256"])
                    )
                ).to_pylist()
                if len(pinned) != len(row["levels"]):
                    raise ValueError("canonical_lake_mismatch")
                for saved, level in zip(pinned, row["levels"], strict=True):
                    original = {
                        k: saved[k] for k in VARIABLES + ("pressure_dbar", "depth_m")
                    }
                    original.update(
                        qc_flags=json.loads(saved["qc_flags"]),
                        missing_reasons=json.loads(saved["missing_reasons"]),
                    )
                    if (
                        original != level
                        or any(
                            saved[k] != (str(row[k]) if k == "profile_id" else row[k])
                            for k in (
                                "profile_id",
                                "revision_sha256",
                                "latitude",
                                "longitude",
                                "data_mode",
                                "qc_version",
                            )
                        )
                        or saved["observed_at"] != row["observed_at"].isoformat()
                        or saved["raw_sha256"] != row["raw_sha"]
                    ):
                        raise ValueError("canonical_lake_mismatch")
                result = compare(profile_grid(row, bundle["policy"]), bundle)
                inputs = [
                    evidence.input_ref(
                        row["profile_id"], row["revision_sha256"], row["raw_sha"]
                    )
                ]
                calc = evidence.publish(
                    s3,
                    "climatology_comparison",
                    METHOD,
                    inputs,
                    result,
                    {
                        "release_id": rid,
                        "reference_calculation_id": str(release["calculation_id"]),
                        "snapshot_id": str(release["snapshot_id"]),
                        "bundle_sha256": release["bundle_sha256"],
                        "grid_version": bundle["policy"]["grid_version"],
                        "display_qc_version": row["qc_version"],
                        "fitting_period": bundle["fitting_period"],
                        "dataset_baseline": bundle["dataset_baseline"],
                    },
                    row["observed_at"].isoformat(),
                    code_hash(),
                )
                db.execute("SELECT pg_advisory_xact_lock(78192402)")
                valid = db.execute(
                    """SELECT 1 FROM profile_revisions r JOIN climatology_selection s ON s.release_id=%s WHERE r.profile_id=%s AND r.revision_sha256=%s
AND r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL FOR UPDATE OF r""",
                    (rid, row["profile_id"], row["revision_sha256"]),
                ).fetchone()
                owns = db.execute(
                    "SELECT 1 FROM climatology_jobs WHERE job_id=%s AND lease_token=%s AND status='running' AND lease_until>clock_timestamp() FOR UPDATE",
                    (job["job_id"], token),
                ).fetchone()
                if not owns:
                    continue
                if not valid:
                    db.execute(
                        "UPDATE climatology_jobs SET status='obsolete',lease_until=NULL,completed_at=now() WHERE job_id=%s",
                        (job["job_id"],),
                    )
                    continue
                evidence.record(db, calc, inputs)
                db.execute(
                    """INSERT INTO climatology_comparisons(profile_id,revision_sha256,release_id,calculation_id,result) VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                    (
                        row["profile_id"],
                        row["revision_sha256"],
                        rid,
                        calc["id"],
                        Jsonb(result),
                    ),
                )
                db.execute(
                    "UPDATE climatology_jobs SET status='complete',lease_until=NULL,completed_at=now(),reason_code=NULL WHERE job_id=%s",
                    (job["job_id"],),
                )
                completed += 1
        except ValueError as error:
            with connect() as db:
                db.execute(
                    "UPDATE climatology_jobs SET status=%s,lease_until=NULL,next_attempt_at=now()+least(attempts,60)*interval '1 second',reason_code=%s WHERE job_id=%s AND lease_token=%s AND status='running'",
                    (
                        "pending"
                        if isinstance(error, InvalidProfile)
                        else "quarantined",
                        str(error),
                        job["job_id"],
                        token,
                    ),
                )
            raise
        except Exception:
            with connect() as db:
                db.execute(
                    "UPDATE climatology_jobs SET status='pending',lease_until=NULL,next_attempt_at=now()+least(attempts,60)*interval '1 second',reason_code='climatology_deferred' WHERE job_id=%s AND lease_token=%s AND status='running'",
                    (job["job_id"], token),
                )
            raise
    return completed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    task = sub.add_parser("build")
    task.add_argument("snapshot_id")
    task.add_argument("--policy", default="/climatology.json")
    for name in ("verify", "select"):
        task = sub.add_parser(name)
        task.add_argument("release_id")
    task = sub.add_parser("maintain")
    task.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()
    try:
        if args.command == "build":
            result = build(args.snapshot_id, args.policy)
        elif args.command == "verify":
            result = verify(args.release_id)
        elif args.command == "select":
            result = select(args.release_id)
        else:
            result = {"comparisons_completed": recompute(args.limit)}
    except ValueError as error:
        parser.exit(2, str(error) + "\n")
    except Exception:
        logging.error(
            "Climatology task deferred; verify snapshot, release and artifact readiness"
        )
        parser.exit(1)
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
