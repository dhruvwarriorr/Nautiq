"""Content-addressed calculation evidence and revision-safe descriptive recomputation."""

import json
import os
import platform
import sys
import uuid
from pathlib import Path

import gsw
import netCDF4
import numpy
import psycopg
import pyarrow
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import parser
from .storage import digest, put_immutable, store

SUMMARY_VERSION = "original-level-summary-v1"


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def environment():
    return {
        "python": platform.python_version(),
        "platform": sys.platform,
        "machine": platform.machine(),
        "numpy": numpy.__version__,
        "netcdf4": netCDF4.__version__,
        "gsw": gsw.__version__,
        "pyarrow": pyarrow.__version__,
    }


def code_digest(*names):
    return digest(
        b"\n".join(Path(__file__).with_name(name).read_bytes() for name in names)
    )


def publish(
    s3, kind, method_version, inputs, output, policy, evaluation_time, code_sha
):
    body = {
        "schema_version": 1,
        "kind": kind,
        "method_version": method_version,
        "inputs": inputs,
        "output": output,
        "policy": policy,
        "evaluation_time": evaluation_time,
        "code_sha256": code_sha,
        "environment": environment(),
    }
    sha = digest(canonical(body))
    cid = str(uuid.uuid5(uuid.NAMESPACE_URL, "calculation|" + sha))
    manifest = dict(body, calculation_id=cid, calculation_sha256=sha)
    data = canonical(manifest)
    key = f"lake/calculations/{cid}.json"
    put_immutable(s3, key, data)
    return {
        "id": cid,
        "sha": sha,
        "kind": kind,
        "method_version": method_version,
        "manifest": manifest,
        "key": key,
        "manifest_sha": digest(data),
    }


def record(db, evidence, inputs, state="current"):
    db.execute(
        """INSERT INTO calculations(calculation_id,calculation_sha256,kind,method_version,manifest,manifest_key,manifest_sha256,state)
VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(calculation_sha256) DO NOTHING""",
        (
            evidence["id"],
            evidence["sha"],
            evidence["kind"],
            evidence["method_version"],
            Jsonb(evidence["manifest"]),
            evidence["key"],
            evidence["manifest_sha"],
            state,
        ),
    )
    for item in inputs:
        db.execute(
            "INSERT INTO calculation_inputs VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
            (evidence["id"], item["profile_id"], item["revision_sha256"]),
        )


def input_ref(profile_id, revision, raw_sha):
    return {
        "profile_id": str(profile_id),
        "revision_sha256": revision,
        "raw_sha256": raw_sha,
    }


def normalization(s3, profile, revision, raw_sha):
    pid = str(uuid.uuid5(uuid.NAMESPACE_URL, profile["native_key"]))
    return publish(
        s3,
        "normalization",
        profile["normalizer_version"],
        [input_ref(pid, revision, raw_sha)],
        {"canonical_revision_sha256": revision, "level_count": len(profile["levels"])},
        {
            "qc_version": profile["qc_version"],
            "depth_conversion_version": profile["depth_conversion_version"],
            "feature_schema": "original-levels-v1",
            "parameter_modes": profile["parameter_modes"],
        },
        profile["observed_at"],
        code_digest("parser.py"),
    )


def qc_record(db, artifact_id, source_id, entry):
    body = {
        "artifact_id": str(artifact_id) if artifact_id else None,
        "profile_index": entry.get("profile_index"),
        "variable": entry.get("variable"),
        "reason_code": entry["reason_code"],
        "qc_version": parser.QC_VERSION,
        "normalizer_version": parser.NORMALIZER_VERSION,
        "rule_id": entry.get("rule_id", "profile.validation"),
    }
    rid = str(uuid.uuid5(uuid.NAMESPACE_URL, "qc|" + digest(canonical(body))))
    db.execute(
        """INSERT INTO qc_rejections(rejection_id,artifact_id,source_id,profile_index,variable,rule_id,reason_code,qc_version,normalizer_version,rejected_count,context)
VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
        (
            rid,
            artifact_id,
            source_id,
            body["profile_index"],
            body["variable"],
            body["rule_id"],
            body["reason_code"],
            body["qc_version"],
            body["normalizer_version"],
            entry.get("rejected_count", 1),
            Jsonb(entry.get("context", {})),
        ),
    )


def queue_summary(db, profile_id, revision):
    jid = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL, f"summary|{profile_id}|{revision}|{SUMMARY_VERSION}"
        )
    )
    db.execute(
        """INSERT INTO recomputation_jobs(job_id,profile_id,revision_sha256,method_version)
VALUES(%s,%s,%s,%s) ON CONFLICT(profile_id,revision_sha256,method_version) DO UPDATE
SET status='pending',lease_until=NULL,lease_token=NULL,next_attempt_at=clock_timestamp(),completed_at=NULL,reason_code=NULL
WHERE recomputation_jobs.status='obsolete' AND EXISTS(SELECT 1 FROM profile_revisions r
WHERE r.profile_id=excluded.profile_id AND r.revision_sha256=excluded.revision_sha256
AND r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL)""",
        (jid, profile_id, revision, SUMMARY_VERSION),
    )


def invalidate(db, profile_id, revision):
    # Frozen historical snapshot evidence must remain frozen, even after upstream revision.
    db.execute(
        """UPDATE calculations c SET state='stale' FROM calculation_inputs i
WHERE c.calculation_id=i.calculation_id AND i.profile_id=%s AND i.revision_sha256=%s
AND c.kind IN ('normalization','profile_summary') AND c.state='current'""",
        (profile_id, revision),
    )


def statistics(levels):
    result = {
        "level_count": len(levels),
        "pressure_unit": "dbar",
        "depth_unit": "m",
        "pressure_range": [
            min(p["pressure_dbar"] for p in levels),
            max(p["pressure_dbar"] for p in levels),
        ],
        "depth_range": [
            min(p["depth_m"] for p in levels),
            max(p["depth_m"] for p in levels),
        ],
    }
    for variable in ("temperature_c", "practical_salinity"):
        values = [p[variable] for p in levels if p[variable] is not None]
        result[variable] = {
            "accepted_count": len(values),
            "missing_count": len(levels) - len(values),
            "minimum": min(values) if values else None,
            "maximum": max(values) if values else None,
        }
    return result


def recompute(limit=10, s3=None):
    s3 = s3 or store()
    completed = 0
    for _ in range(limit):
        token = str(uuid.uuid4())
        with psycopg.connect(
            os.environ["DATABASE_URL"], row_factory=dict_row, connect_timeout=5
        ) as db:
            db.execute("SET statement_timeout='15s'; SET lock_timeout='5s'")
            job = db.execute(
                """WITH picked AS (SELECT job_id FROM recomputation_jobs
WHERE status IN ('pending','running') AND next_attempt_at<=now() AND (lease_until IS NULL OR lease_until<now())
ORDER BY created_at,job_id FOR UPDATE SKIP LOCKED LIMIT 1)
UPDATE recomputation_jobs j SET status='running',lease_token=%s,lease_until=now()+interval '60 seconds',attempts=attempts+1
FROM picked p WHERE j.job_id=p.job_id RETURNING j.*""",
                (token,),
            ).fetchone()
        if not job:
            break
        try:
            with psycopg.connect(
                os.environ["DATABASE_URL"], row_factory=dict_row, connect_timeout=5
            ) as db:
                db.execute("SET statement_timeout='15s'; SET lock_timeout='5s'")
                row = db.execute(
                    """SELECT r.*,a.sha256 raw_sha FROM profile_revisions r JOIN raw_artifacts a ON a.artifact_id=r.raw_artifact_id
WHERE r.profile_id=%s AND r.revision_sha256=%s AND r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL""",
                    (job["profile_id"], job["revision_sha256"]),
                ).fetchone()
                if row is None:
                    db.execute(
                        "UPDATE recomputation_jobs SET status='obsolete',completed_at=now(),lease_until=NULL WHERE job_id=%s AND lease_token=%s",
                        (job["job_id"], token),
                    )
                    continue
                output = statistics(row["levels"])
                inputs = [
                    input_ref(row["profile_id"], row["revision_sha256"], row["raw_sha"])
                ]
                evidence = publish(
                    s3,
                    "profile_summary",
                    SUMMARY_VERSION,
                    inputs,
                    output,
                    {
                        "qc_version": row["qc_version"],
                        "depth_conversion_version": row["depth_conversion_version"],
                        "feature_schema": "original-level-summary-v1",
                    },
                    row["observed_at"].isoformat(),
                    code_digest("evidence.py"),
                )
                # Only the still-current expected revision and lease may publish a live aggregate.
                db.execute("SELECT pg_advisory_xact_lock(78192402)")
                current = db.execute(
                    """SELECT 1 FROM profile_revisions WHERE profile_id=%s AND revision_sha256=%s
AND science_ready AND selected_at IS NOT NULL AND superseded_at IS NULL FOR UPDATE""",
                    (row["profile_id"], row["revision_sha256"]),
                ).fetchone()
                owns = db.execute(
                    "SELECT 1 FROM recomputation_jobs WHERE job_id=%s AND lease_token=%s AND status='running' AND lease_until>clock_timestamp() FOR UPDATE",
                    (job["job_id"], token),
                ).fetchone()
                if not owns:
                    continue
                if not current:
                    db.execute(
                        "UPDATE recomputation_jobs SET status='obsolete',completed_at=now(),lease_until=NULL WHERE job_id=%s",
                        (job["job_id"],),
                    )
                    continue
                record(db, evidence, inputs)
                db.execute(
                    """INSERT INTO profile_statistics(profile_id,revision_sha256,calculation_id,statistics) VALUES(%s,%s,%s,%s)
ON CONFLICT(profile_id) DO UPDATE SET revision_sha256=excluded.revision_sha256,calculation_id=excluded.calculation_id,statistics=excluded.statistics,updated_at=now()""",
                    (
                        row["profile_id"],
                        row["revision_sha256"],
                        evidence["id"],
                        Jsonb(output),
                    ),
                )
                db.execute(
                    "UPDATE recomputation_jobs SET status='complete',completed_at=now(),lease_until=NULL,calculation_id=%s WHERE job_id=%s",
                    (evidence["id"], job["job_id"]),
                )
                completed += 1
        except Exception:
            with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=5) as db:
                db.execute(
                    """UPDATE recomputation_jobs SET status='pending',lease_until=NULL,next_attempt_at=now()+least(attempts,60)*interval '1 second',reason_code='calculation_deferred'
WHERE job_id=%s AND lease_token=%s AND status='running'""",
                    (job["job_id"], token),
                )
            raise
    return completed
