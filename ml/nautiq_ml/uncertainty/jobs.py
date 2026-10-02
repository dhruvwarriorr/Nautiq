"""Revision, parent-selection and lease-safe predictive interval publication."""

import os
import math
import uuid

import grpc
from psycopg.types.json import Jsonb

from ..argo import evidence
from ..argo.parser import InvalidProfile
from ..argo.storage import store
from ..climatology.grid import VARIABLES, profile_grid
from ..climatology.pipeline import connect
from ..expected_state.jobs import canonical_profile
from ..gen.nautiq.platform.v1 import platform_pb2 as pb, platform_pb2_grpc as rpc
from .calibration import UNIT
from . import METHOD


def queue(db, profile_id, revision, release_id=None):
    if release_id is None:
        row = db.execute(
            "SELECT release_id FROM uncertainty_selection WHERE singleton"
        ).fetchone()
        if not row:
            return
        release_id = row["release_id"] if isinstance(row, dict) else row[0]
    jid = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL, f"uncertainty-job|{profile_id}|{revision}|{release_id}"
        )
    )
    db.execute(
        """INSERT INTO uncertainty_jobs(job_id,profile_id,revision_sha256,release_id) VALUES(%s,%s,%s,%s)
ON CONFLICT(profile_id,revision_sha256,release_id) DO UPDATE SET status='pending',lease_until=NULL,lease_token=NULL,next_attempt_at=clock_timestamp(),completed_at=NULL,reason_code=NULL
WHERE uncertainty_jobs.status='obsolete' AND EXISTS(SELECT 1 FROM profile_revisions r JOIN uncertainty_selection s ON s.release_id=excluded.release_id WHERE r.profile_id=excluded.profile_id AND r.revision_sha256=excluded.revision_sha256 AND r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL)""",
        (jid, profile_id, revision, release_id),
    )


def decode(response, grid):
    if (
        len(response.rows) != len(grid)
        or response.release_approved
        or response.method_version != METHOD
        or response.feature_version != "ocean-reference-features-v1"
        or response.coverage_unit != UNIT
        or response.nominal_coverage != 0.8
    ):
        raise ValueError("uncertainty_rpc_contract_mismatch")
    rows, supported = [], 0
    for point, observed in zip(response.rows, grid, strict=True):
        if point.depth_m != observed["depth_m"]:
            raise ValueError("uncertainty_rpc_depth_mismatch")
        row = {"depth_m": point.depth_m}
        for v in VARIABLES:
            prediction = getattr(point, v)
            saved = {
                name: getattr(prediction, name) if prediction.HasField(name) else None
                for name in (
                    "expected_mean",
                    "q10",
                    "q50",
                    "q90",
                    "lower",
                    "upper",
                    "correction",
                )
            }
            saved.update(
                {
                    k: getattr(prediction, k)
                    for k in (
                        "status",
                        "family",
                        "calibration_profiles",
                        "fallback",
                        "quantile_crossing",
                        "coverage_qualified",
                    )
                }
            )
            saved.update(
                {
                    k: getattr(prediction, k) or None
                    for k in (
                        "reason",
                        "calibration_group",
                        "requested_group",
                        "calibration_rank",
                    )
                }
            )
            if any(
                value is not None and not math.isfinite(value)
                for value in saved.values()
                if isinstance(value, (float, int)) and not isinstance(value, bool)
            ):
                raise ValueError("uncertainty_rpc_nonfinite")
            if (saved["lower"] is None) != (saved["upper"] is None):
                raise ValueError("uncertainty_rpc_incomplete_interval")
            qs = [saved[k] for k in ("q10", "q50", "q90")]
            if any(q is not None for q in qs) and (
                any(q is None for q in qs) or not qs[0] <= qs[1] <= qs[2]
            ):
                raise ValueError("uncertainty_rpc_incomplete_quantiles")
            if saved["correction"] is not None and saved["correction"] < 0:
                raise ValueError("uncertainty_rpc_negative_correction")
            if saved["lower"] is not None and (
                not saved["calibration_group"]
                or not saved["calibration_rank"]
                or saved["calibration_rank"] > saved["calibration_profiles"]
                or saved["status"]
                not in ("diagnostic_calibrated", "qualified_calibrated")
            ):
                raise ValueError("uncertainty_rpc_calibration_support")
            saved["fallback_reasons"] = list(prediction.fallback_reasons)
            if saved["lower"] is not None:
                if (
                    saved["upper"] is None
                    or saved["q10"] is None
                    or saved["q50"] is None
                    or saved["q90"] is None
                    or saved["correction"] is None
                    or not saved["lower"]
                    <= saved["q10"]
                    <= saved["q50"]
                    <= saved["q90"]
                    <= saved["upper"]
                ):
                    raise ValueError("uncertainty_rpc_interval_order")
                if (
                    abs(saved["lower"] - (saved["q10"] - saved["correction"])) > 1e-8
                    or abs(saved["upper"] - (saved["q90"] + saved["correction"])) > 1e-8
                ):
                    raise ValueError("uncertainty_rpc_cqr_mismatch")
                supported += 1
            covered = (
                saved["lower"] <= observed[v] <= saved["upper"]
                if saved["lower"] is not None and observed[v] is not None
                else None
            )
            saved.update(
                observed=observed[v],
                observed_method=observed["coverage"][v]["method"],
                observed_reason=observed["coverage"][v]["reason"],
                covered=covered,
                width=saved["upper"] - saved["lower"]
                if saved["lower"] is not None
                else None,
            )
            row[v] = saved
        rows.append(row)
    return {
        "rows": rows,
        "supported_intervals": supported,
        "status": "ready"
        if supported == len(grid) * 2
        else "partial"
        if supported
        else "unavailable",
        "method_version": METHOD,
        "feature_version": response.feature_version,
        "nominal_coverage": response.nominal_coverage,
        "coverage_unit": response.coverage_unit,
        "interval_interpretation": response.interval_interpretation,
        "median_estimand": "rearranged_predictive_q50; separate from expected conditional mean",
        "release_approved": False,
    }


def recompute(limit=5, s3=None, client=None):
    if not 1 <= limit <= 2000:
        raise ValueError("uncertainty_job_budget")
    s3 = s3 or store()
    channel = None
    if client is None:
        channel = grpc.insecure_channel(
            os.environ.get("ML_GRPC_ADDR", "ml-inference:50051"),
            options=[
                ("grpc.max_receive_message_length", 1024 * 1024),
                ("grpc.max_send_message_length", 1024 * 1024),
            ],
        )
        client = rpc.UncertaintyServiceStub(channel)
    completed = 0
    try:
        for _ in range(limit):
            token = str(uuid.uuid4())
            with connect() as db:
                job = db.execute(
                    """WITH picked AS (SELECT job_id FROM uncertainty_jobs WHERE status IN ('pending','running') AND next_attempt_at<=now() AND (lease_until IS NULL OR lease_until<now()) ORDER BY created_at,job_id FOR UPDATE SKIP LOCKED LIMIT 1)
UPDATE uncertainty_jobs j SET status='running',lease_token=%s,lease_until=now()+interval '60 seconds',attempts=attempts+1 FROM picked p WHERE j.job_id=p.job_id RETURNING j.*""",
                    (token,),
                ).fetchone()
            if not job:
                break
            try:
                with connect() as db:
                    row = db.execute(
                        """SELECT p.platform_id,r.*,a.sha256 raw_sha,a.object_key FROM profile_revisions r JOIN profiles p USING(profile_id) JOIN raw_artifacts a ON a.artifact_id=r.raw_artifact_id
JOIN uncertainty_selection s ON s.release_id=%s JOIN uncertainty_releases u ON u.release_id=s.release_id JOIN expected_state_selection e ON e.release_id=u.expected_id JOIN climatology_selection c ON c.release_id=u.reference_id
WHERE r.profile_id=%s AND r.revision_sha256=%s AND r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL""",
                        (job["release_id"], job["profile_id"], job["revision_sha256"]),
                    ).fetchone()
                    if not row:
                        db.execute(
                            "UPDATE uncertainty_jobs SET status='obsolete',lease_until=NULL,completed_at=now() WHERE job_id=%s AND lease_token=%s",
                            (job["job_id"], token),
                        )
                        continue
                    release = db.execute(
                        "SELECT u.*,c.manifest->'policy'->'climatology_policy' AS grid_policy FROM uncertainty_releases u JOIN climatology_releases c ON c.release_id=u.reference_id WHERE u.release_id=%s",
                        (job["release_id"],),
                    ).fetchone()
                    canonical_profile(row, s3)
                    grid = profile_grid(row, release["grid_policy"])
                    request = pb.UncertaintyRequest(
                        release_id=str(release["release_id"]),
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
                        or response.expected_id != str(release["expected_id"])
                        or response.reference_id != str(release["reference_id"])
                    ):
                        raise ValueError("uncertainty_rpc_release_mismatch")
                    result = decode(response, grid)
                    inputs = [
                        evidence.input_ref(
                            row["profile_id"], row["revision_sha256"], row["raw_sha"]
                        )
                    ]
                    calc = evidence.publish(
                        s3,
                        "uncertainty_comparison",
                        METHOD,
                        inputs,
                        result,
                        {
                            "release_id": str(release["release_id"]),
                            "expected_id": str(release["expected_id"]),
                            "reference_id": str(release["reference_id"]),
                            "reference_calculation_id": str(release["calculation_id"]),
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
                        """SELECT 1 FROM profile_revisions r JOIN uncertainty_selection s ON s.release_id=%s JOIN uncertainty_releases u ON u.release_id=s.release_id JOIN expected_state_selection e ON e.release_id=u.expected_id JOIN climatology_selection c ON c.release_id=u.reference_id
WHERE r.profile_id=%s AND r.revision_sha256=%s AND r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL FOR UPDATE OF r""",
                        (
                            release["release_id"],
                            row["profile_id"],
                            row["revision_sha256"],
                        ),
                    ).fetchone()
                    owns = db.execute(
                        "SELECT 1 FROM uncertainty_jobs WHERE job_id=%s AND lease_token=%s AND status='running' AND lease_until>clock_timestamp() FOR UPDATE",
                        (job["job_id"], token),
                    ).fetchone()
                    if not owns:
                        continue
                    if not valid:
                        db.execute(
                            "UPDATE uncertainty_jobs SET status='obsolete',lease_until=NULL,completed_at=now() WHERE job_id=%s",
                            (job["job_id"],),
                        )
                        continue
                    evidence.record(db, calc, inputs)
                    db.execute(
                        "INSERT INTO uncertainty_comparisons(profile_id,revision_sha256,release_id,calculation_id,result) VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                        (
                            row["profile_id"],
                            row["revision_sha256"],
                            release["release_id"],
                            calc["id"],
                            Jsonb(result),
                        ),
                    )
                    db.execute(
                        "UPDATE uncertainty_jobs SET status='complete',lease_until=NULL,completed_at=now(),reason_code=NULL WHERE job_id=%s",
                        (job["job_id"],),
                    )
                    completed += 1
            except Exception as error:
                reason = (
                    "uncertainty_runtime_deferred"
                    if isinstance(error, grpc.RpcError)
                    else "uncertainty_artifact_deferred"
                    if isinstance(error, InvalidProfile)
                    else str(error)
                    if isinstance(error, ValueError)
                    else "uncertainty_comparison_deferred"
                )
                status = (
                    "quarantined"
                    if isinstance(error, ValueError)
                    and not isinstance(error, InvalidProfile)
                    else "pending"
                )
                with connect() as db:
                    db.execute(
                        "UPDATE uncertainty_jobs SET status=%s,lease_until=NULL,next_attempt_at=now()+least(attempts,60)*interval '1 second',reason_code=%s WHERE job_id=%s AND lease_token=%s AND status='running'",
                        (status, reason, job["job_id"], token),
                    )
                raise
    finally:
        if channel:
            channel.close()
    return completed
