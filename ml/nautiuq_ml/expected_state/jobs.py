"""Durable revision/reference/lease-safe comparisons through the real gRPC boundary."""

import io
import json
import os
import uuid

import grpc
import pyarrow.parquet as pq
from psycopg.types.json import Jsonb

from ..argo import evidence
from ..argo.parser import InvalidProfile
from ..argo.storage import read_object, store
from ..climatology.grid import VARIABLES, profile_grid
from ..climatology.pipeline import connect
from ..gen.nautiuq.platform.v1 import platform_pb2 as pb, platform_pb2_grpc as rpc


def queue(db, profile_id, revision, release_id=None):
    if release_id is None:
        selected = db.execute(
            "SELECT release_id FROM expected_state_selection WHERE singleton"
        ).fetchone()
        if not selected:
            return
        release_id = (
            selected["release_id"] if isinstance(selected, dict) else selected[0]
        )
    jid = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL, f"expected-job|{profile_id}|{revision}|{release_id}"
        )
    )
    db.execute(
        """INSERT INTO expected_state_jobs(job_id,profile_id,revision_sha256,release_id) VALUES(%s,%s,%s,%s)
ON CONFLICT(profile_id,revision_sha256,release_id) DO UPDATE SET status='pending',lease_until=NULL,lease_token=NULL,next_attempt_at=clock_timestamp(),completed_at=NULL,reason_code=NULL
WHERE expected_state_jobs.status='obsolete' AND EXISTS(SELECT 1 FROM profile_revisions r JOIN expected_state_selection s ON s.release_id=excluded.release_id
WHERE r.profile_id=excluded.profile_id AND r.revision_sha256=excluded.revision_sha256 AND r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL)""",
        (jid, profile_id, revision, release_id),
    )


def canonical_profile(row, s3):
    read_object(s3, row["object_key"], row["raw_sha"])
    pinned = pq.read_table(
        io.BytesIO(read_object(s3, row["parquet_key"], row["parquet_sha256"]))
    ).to_pylist()
    if len(pinned) != len(row["levels"]):
        raise ValueError("canonical_lake_mismatch")
    for saved, level in zip(pinned, row["levels"], strict=True):
        original = {k: saved[k] for k in VARIABLES + ("pressure_dbar", "depth_m")}
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


def decode(response, grid):
    if (
        len(response.rows) != len(grid)
        or response.estimand != "conditional_mean"
        or response.release_approved
        or response.method_version != "residual-expected-mean-v1"
        or response.feature_version != "ocean-reference-features-v1"
    ):
        raise ValueError("expected_rpc_contract_mismatch")
    rows = []
    supported = 0
    for point, observed in zip(response.rows, grid, strict=True):
        if point.depth_m != observed["depth_m"]:
            raise ValueError("expected_rpc_depth_mismatch")
        entry = {"depth_m": point.depth_m}
        for v in VARIABLES:
            prediction = getattr(point, v)
            saved = {
                name: getattr(prediction, name) if prediction.HasField(name) else None
                for name in (
                    "climatology_mean",
                    "candidate_mean",
                    "candidate_residual",
                    "expected_mean",
                    "ml_residual",
                    "contribution_bias",
                )
            }
            saved.update(
                active_method=prediction.active_method,
                reason=prediction.reason or None,
                candidate_reason=prediction.candidate_reason or None,
                promotion_reasons=list(prediction.promotion_reasons),
                feature_contributions=[
                    {"feature": c.feature, "contribution": c.contribution}
                    for c in prediction.feature_contributions
                ],
                baseline_support=json.loads(prediction.baseline_support_json),
            )
            difference = (
                observed[v] - saved["expected_mean"]
                if observed[v] is not None and saved["expected_mean"] is not None
                else None
            )
            supported += difference is not None
            positive, negative = (
                ("warmer", "cooler") if v == "temperature_c" else ("saltier", "fresher")
            )
            saved.update(
                observed=observed[v],
                observed_method=observed["coverage"][v]["method"],
                observed_reason=observed["coverage"][v]["reason"],
                difference=difference,
                direction=positive
                if difference is not None and difference > 0
                else negative
                if difference is not None and difference < 0
                else "equal"
                if difference is not None
                else "unavailable",
            )
            entry[v] = saved
        rows.append(entry)
    return {
        "rows": rows,
        "supported_pairs": supported,
        "status": "ready"
        if supported == len(grid) * 2
        else "partial"
        if supported
        else "unavailable",
        "estimand": response.estimand,
        "method_version": response.method_version,
        "feature_version": response.feature_version,
        "release_approved": False,
        "interval_status": response.interval_status,
        "explanation_interpretation": response.explanation_interpretation,
    }


def recompute(limit=5, s3=None, client=None):
    if not 1 <= limit <= 2000:
        raise ValueError("expected_job_budget")
    s3 = s3 or store()
    completed = 0
    channel = None
    if client is None:
        channel = grpc.insecure_channel(
            os.environ.get("ML_GRPC_ADDR", "ml-inference:50051"),
            options=[
                ("grpc.max_receive_message_length", 1024 * 1024),
                ("grpc.max_send_message_length", 1024 * 1024),
            ],
        )
        client = rpc.ExpectedStateServiceStub(channel)
    try:
        for _ in range(limit):
            token = str(uuid.uuid4())
            with connect() as db:
                job = db.execute(
                    """WITH picked AS (SELECT job_id FROM expected_state_jobs WHERE status IN ('pending','running') AND next_attempt_at<=now() AND (lease_until IS NULL OR lease_until<now()) ORDER BY created_at,job_id FOR UPDATE SKIP LOCKED LIMIT 1)
UPDATE expected_state_jobs j SET status='running',lease_token=%s,lease_until=now()+interval '60 seconds',attempts=attempts+1 FROM picked p WHERE j.job_id=p.job_id RETURNING j.*""",
                    (token,),
                ).fetchone()
            if not job:
                break
            try:
                with connect() as db:
                    row = db.execute(
                        """SELECT p.platform_id,r.*,a.sha256 raw_sha,a.object_key FROM profile_revisions r JOIN profiles p USING(profile_id) JOIN raw_artifacts a ON a.artifact_id=r.raw_artifact_id
JOIN expected_state_selection s ON s.release_id=%s JOIN expected_state_releases m ON m.release_id=s.release_id JOIN climatology_selection c ON c.release_id=m.reference_id
WHERE r.profile_id=%s AND r.revision_sha256=%s AND r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL""",
                        (job["release_id"], job["profile_id"], job["revision_sha256"]),
                    ).fetchone()
                    if not row:
                        db.execute(
                            "UPDATE expected_state_jobs SET status='obsolete',lease_until=NULL,completed_at=now() WHERE job_id=%s AND lease_token=%s",
                            (job["job_id"], token),
                        )
                        continue
                    release = db.execute(
                        "SELECT m.*,c.manifest->'policy'->'climatology_policy' AS grid_policy FROM expected_state_releases m JOIN climatology_releases c ON c.release_id=m.reference_id WHERE m.release_id=%s",
                        (job["release_id"],),
                    ).fetchone()
                    canonical_profile(row, s3)
                    grid = profile_grid(row, release["grid_policy"])
                    request = pb.ExpectedStateRequest(
                        release_id=str(release["release_id"]),
                        explain=True,
                        points=[
                            pb.ReferencePoint(
                                latitude=r["latitude"],
                                longitude=r["longitude"],
                                depth_m=r["depth_m"],
                                observed_at=r["observed_at"],
                            )
                            for r in grid
                        ],
                    )
                    response = client.Infer(request, timeout=3)
                    if (
                        response.release_id != str(release["release_id"])
                        or response.bundle_sha256 != release["bundle_sha256"]
                    ):
                        raise ValueError("expected_rpc_release_mismatch")
                    result = decode(response, grid)
                    inputs = [
                        evidence.input_ref(
                            row["profile_id"], row["revision_sha256"], row["raw_sha"]
                        )
                    ]
                    calc = evidence.publish(
                        s3,
                        "expected_state_comparison",
                        response.method_version,
                        inputs,
                        result,
                        {
                            "release_id": str(release["release_id"]),
                            "reference_id": str(release["reference_id"]),
                            "reference_calculation_id": str(release["calculation_id"]),
                            "snapshot_id": str(release["snapshot_id"]),
                            "bundle_sha256": release["bundle_sha256"],
                            "feature_version": response.feature_version,
                            "grid_version": release["grid_policy"]["grid_version"],
                            "display_qc_version": row["qc_version"],
                        },
                        row["observed_at"].isoformat(),
                        release["manifest"]["code_sha256"],
                    )
                    db.execute("SELECT pg_advisory_xact_lock(78192402)")
                    valid = db.execute(
                        """SELECT 1 FROM profile_revisions r JOIN expected_state_selection s ON s.release_id=%s JOIN expected_state_releases m ON m.release_id=s.release_id JOIN climatology_selection c ON c.release_id=m.reference_id
WHERE r.profile_id=%s AND r.revision_sha256=%s AND r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL FOR UPDATE OF r""",
                        (
                            release["release_id"],
                            row["profile_id"],
                            row["revision_sha256"],
                        ),
                    ).fetchone()
                    owns = db.execute(
                        "SELECT 1 FROM expected_state_jobs WHERE job_id=%s AND lease_token=%s AND status='running' AND lease_until>clock_timestamp() FOR UPDATE",
                        (job["job_id"], token),
                    ).fetchone()
                    if not owns:
                        continue
                    if not valid:
                        db.execute(
                            "UPDATE expected_state_jobs SET status='obsolete',lease_until=NULL,completed_at=now() WHERE job_id=%s",
                            (job["job_id"],),
                        )
                        continue
                    evidence.record(db, calc, inputs)
                    db.execute(
                        "INSERT INTO expected_state_comparisons(profile_id,revision_sha256,release_id,calculation_id,result) VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                        (
                            row["profile_id"],
                            row["revision_sha256"],
                            release["release_id"],
                            calc["id"],
                            Jsonb(result),
                        ),
                    )
                    db.execute(
                        "UPDATE expected_state_jobs SET status='complete',lease_until=NULL,completed_at=now(),reason_code=NULL WHERE job_id=%s",
                        (job["job_id"],),
                    )
                    completed += 1
            except Exception as error:
                reason = (
                    "expected_runtime_deferred"
                    if isinstance(error, grpc.RpcError)
                    else "expected_artifact_deferred"
                    if isinstance(error, InvalidProfile)
                    else str(error)
                    if isinstance(error, ValueError)
                    else "expected_comparison_deferred"
                )
                status = (
                    "quarantined"
                    if isinstance(error, ValueError)
                    and not isinstance(error, InvalidProfile)
                    else "pending"
                )
                with connect() as db:
                    db.execute(
                        "UPDATE expected_state_jobs SET status=%s,lease_until=NULL,next_attempt_at=now()+least(attempts,60)*interval '1 second',reason_code=%s WHERE job_id=%s AND lease_token=%s AND status='running'",
                        (status, reason, job["job_id"], token),
                    )
                raise
    finally:
        if channel:
            channel.close()
    return completed
