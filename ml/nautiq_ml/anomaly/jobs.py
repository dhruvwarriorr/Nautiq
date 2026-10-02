"""Revision, parent-selection and lease-safe predictive interval publication."""

import os
import json
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
from . import METHOD


def queue(db, profile_id, revision, release_id=None):
    if release_id is None:
        row = db.execute(
            "SELECT release_id FROM anomaly_selection WHERE singleton"
        ).fetchone()
        if not row:
            return
        release_id = row["release_id"] if isinstance(row, dict) else row[0]
    jid = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL, f"anomaly-job|{profile_id}|{revision}|{release_id}"
        )
    )
    db.execute(
        """INSERT INTO anomaly_jobs(job_id,profile_id,revision_sha256,release_id) VALUES(%s,%s,%s,%s)
ON CONFLICT(profile_id,revision_sha256,release_id) DO UPDATE SET status='pending',lease_until=NULL,lease_token=NULL,next_attempt_at=clock_timestamp(),completed_at=NULL,reason_code=NULL
WHERE anomaly_jobs.status='obsolete' AND EXISTS(SELECT 1 FROM profile_revisions r JOIN anomaly_selection s ON s.release_id=excluded.release_id WHERE r.profile_id=excluded.profile_id AND r.revision_sha256=excluded.revision_sha256 AND r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL)""",
        (jid, profile_id, revision, release_id),
    )


def decode(response, grid):
    try:
        return _decode(response, grid)
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("anomaly_rpc_malformed_result") from error


def _decode(response, grid):
    if (
        response.release_approved
        or response.method_version != METHOD
        or len(response.result_json) > 262144
    ):
        raise ValueError("anomaly_rpc_contract_mismatch")
    result = json.loads(response.result_json)

    def finite(value):
        if isinstance(value, dict):
            for item in value.values():
                finite(item)
        elif isinstance(value, list):
            for item in value:
                finite(item)
        elif isinstance(value, float) and not math.isfinite(value):
            raise ValueError("anomaly_rpc_nonfinite")

    finite(result)
    if (
        result["release_approved"] is not False
        or result["method_version"] != METHOD
        or result["depths_m"] != [r["depth_m"] for r in grid]
        or result["coverage_policy"] != "complete_10_500m_per_variable"
        or result["scale_estimator"]
        != "train_fitted_rearranged_quantile_half_interdecile_width"
    ):
        raise ValueError("anomaly_rpc_grid_mismatch")
    supported = 0
    for v in VARIABLES:
        value = result["variables"][v]
        points = value["points"]
        if value["qualified"] is not False or len(points) != len(grid):
            raise ValueError("anomaly_rpc_variable_mismatch")
        for point, row in zip(points, grid, strict=True):
            if point["observed"] != row[v] or point["depth_m"] != row["depth_m"]:
                raise ValueError("anomaly_rpc_observation_mismatch")
            if point["scale"] is not None and point["scale"] <= 0:
                raise ValueError("anomaly_rpc_invalid_scale")
        scored = value["score_evidence"]
        if value["complete"] != all(point["covered"] for point in points):
            raise ValueError("anomaly_rpc_coverage_mismatch")
        if scored is not None:
            supported += 1
            if not value["complete"] or any(not point["covered"] for point in points):
                raise ValueError("anomaly_rpc_incomplete_vector")
            for name in (
                "weighted_squared_residual",
                "mahalanobis_squared",
                "fpca_distance_squared",
                "fpca_reconstruction_error",
                "climatology_z_squared",
                "isolation_forest",
            ):
                if scored["scores"][name] < -1e-8:
                    raise ValueError("anomaly_rpc_negative_score")
            for name, total in (
                ("weighted_contribution", "weighted_squared_residual"),
                ("mahalanobis_contribution", "mahalanobis_squared"),
            ):
                if (
                    abs(sum(point[name] for point in points) - scored["scores"][total])
                    > 1e-7
                ):
                    raise ValueError("anomaly_rpc_contribution_mismatch")
            for percentile in value["percentiles"]["values"].values():
                if percentile is not None and not 0 <= percentile <= 100:
                    raise ValueError("anomaly_rpc_invalid_percentile")
                if percentile is not None and value["percentiles"]["profiles"] < 20:
                    raise ValueError("anomaly_rpc_sparse_percentile")
            if (
                len(scored["component_scores"]) != 3
                or len(scored["component_distance_contributions"]) != 3
                or not 1 <= scored["dominant_component"] <= 3
                or not math.isclose(
                    sum(scored["component_distance_contributions"]),
                    scored["scores"]["fpca_distance_squared"],
                    rel_tol=1e-10,
                    abs_tol=1e-8,
                )
            ):
                raise ValueError("anomaly_rpc_component_mismatch")
    if result["supported_variables"] != supported:
        raise ValueError("anomaly_rpc_support_mismatch")
    return result


def recompute(limit=5, s3=None, client=None):
    if not 1 <= limit <= 2000:
        raise ValueError("anomaly_job_budget")
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
        client = rpc.AnomalyServiceStub(channel)
    completed = 0
    try:
        for _ in range(limit):
            token = str(uuid.uuid4())
            with connect() as db:
                job = db.execute(
                    """WITH picked AS (SELECT job_id FROM anomaly_jobs WHERE status IN ('pending','running') AND next_attempt_at<=now() AND (lease_until IS NULL OR lease_until<now()) ORDER BY created_at,job_id FOR UPDATE SKIP LOCKED LIMIT 1)
UPDATE anomaly_jobs j SET status='running',lease_token=%s,lease_until=now()+interval '60 seconds',attempts=attempts+1 FROM picked p WHERE j.job_id=p.job_id RETURNING j.*""",
                    (token,),
                ).fetchone()
            if not job:
                break
            try:
                with connect() as db:
                    row = db.execute(
                        """SELECT p.platform_id,r.*,a.sha256 raw_sha,a.object_key FROM profile_revisions r JOIN profiles p USING(profile_id) JOIN raw_artifacts a ON a.artifact_id=r.raw_artifact_id
JOIN anomaly_selection s ON s.release_id=%s JOIN anomaly_releases u ON u.release_id=s.release_id JOIN uncertainty_selection i ON i.release_id=u.uncertainty_id JOIN expected_state_selection e ON e.release_id=u.expected_id JOIN climatology_selection c ON c.release_id=u.reference_id
WHERE r.profile_id=%s AND r.revision_sha256=%s AND r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL""",
                        (job["release_id"], job["profile_id"], job["revision_sha256"]),
                    ).fetchone()
                    if not row:
                        db.execute(
                            "UPDATE anomaly_jobs SET status='obsolete',lease_until=NULL,completed_at=now() WHERE job_id=%s AND lease_token=%s",
                            (job["job_id"], token),
                        )
                        continue
                    release = db.execute(
                        "SELECT u.*,c.manifest->'policy'->'climatology_policy' AS grid_policy FROM anomaly_releases u JOIN climatology_releases c ON c.release_id=u.reference_id WHERE u.release_id=%s",
                        (job["release_id"],),
                    ).fetchone()
                    canonical_profile(row, s3)
                    grid = [
                        p
                        for p in profile_grid(row, release["grid_policy"])
                        if p["depth_m"] <= 500
                    ]
                    request = pb.AnomalyRequest(
                        release_id=str(release["release_id"]),
                        points=[
                            pb.AnomalyPoint(
                                location=pb.ReferencePoint(
                                    latitude=r["latitude"],
                                    longitude=r["longitude"],
                                    depth_m=r["depth_m"],
                                    observed_at=r["observed_at"],
                                ),
                                **{v: r[v] for v in VARIABLES if r[v] is not None},
                            )
                            for r in grid
                        ],
                    )
                    response = client.Infer(request, timeout=3)
                    if (
                        response.release_id != str(release["release_id"])
                        or response.bundle_sha256 != release["bundle_sha256"]
                        or response.uncertainty_id != str(release["uncertainty_id"])
                        or response.expected_id != str(release["expected_id"])
                        or response.reference_id != str(release["reference_id"])
                    ):
                        raise ValueError("anomaly_rpc_release_mismatch")
                    result = decode(response, grid)
                    inputs = [
                        evidence.input_ref(
                            row["profile_id"], row["revision_sha256"], row["raw_sha"]
                        )
                    ]
                    calc = evidence.publish(
                        s3,
                        "anomaly_comparison",
                        METHOD,
                        inputs,
                        result,
                        {
                            "release_id": str(release["release_id"]),
                            "expected_id": str(release["expected_id"]),
                            "reference_id": str(release["reference_id"]),
                            "reference_calculation_id": str(release["calculation_id"]),
                            "bundle_sha256": release["bundle_sha256"],
                            "uncertainty_id": str(release["uncertainty_id"]),
                            "grid_version": release["grid_policy"]["grid_version"],
                            "display_qc_version": row["qc_version"],
                        },
                        row["observed_at"].isoformat(),
                        release["manifest"]["code_sha256"],
                    )
                    db.execute("SELECT pg_advisory_xact_lock(78192402)")
                    valid = db.execute(
                        """SELECT 1 FROM profile_revisions r JOIN anomaly_selection s ON s.release_id=%s JOIN anomaly_releases u ON u.release_id=s.release_id JOIN uncertainty_selection i ON i.release_id=u.uncertainty_id JOIN expected_state_selection e ON e.release_id=u.expected_id JOIN climatology_selection c ON c.release_id=u.reference_id
WHERE r.profile_id=%s AND r.revision_sha256=%s AND r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL FOR UPDATE OF r""",
                        (
                            release["release_id"],
                            row["profile_id"],
                            row["revision_sha256"],
                        ),
                    ).fetchone()
                    owns = db.execute(
                        "SELECT 1 FROM anomaly_jobs WHERE job_id=%s AND lease_token=%s AND status='running' AND lease_until>clock_timestamp() FOR UPDATE",
                        (job["job_id"], token),
                    ).fetchone()
                    if not owns:
                        continue
                    if not valid:
                        db.execute(
                            "UPDATE anomaly_jobs SET status='obsolete',lease_until=NULL,completed_at=now() WHERE job_id=%s",
                            (job["job_id"],),
                        )
                        continue
                    evidence.record(db, calc, inputs)
                    db.execute(
                        "INSERT INTO anomaly_comparisons(profile_id,revision_sha256,release_id,calculation_id,result) VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                        (
                            row["profile_id"],
                            row["revision_sha256"],
                            release["release_id"],
                            calc["id"],
                            Jsonb(result),
                        ),
                    )
                    db.execute(
                        "UPDATE anomaly_jobs SET status='complete',lease_until=NULL,completed_at=now(),reason_code=NULL WHERE job_id=%s",
                        (job["job_id"],),
                    )
                    completed += 1
            except Exception as error:
                reason = (
                    "anomaly_runtime_deferred"
                    if isinstance(error, grpc.RpcError)
                    else "anomaly_artifact_deferred"
                    if isinstance(error, InvalidProfile)
                    else str(error)
                    if isinstance(error, ValueError)
                    else "anomaly_comparison_deferred"
                )
                status = (
                    "quarantined"
                    if isinstance(error, ValueError)
                    and not isinstance(error, InvalidProfile)
                    else "pending"
                )
                with connect() as db:
                    db.execute(
                        "UPDATE anomaly_jobs SET status=%s,lease_until=NULL,next_attempt_at=now()+least(attempts,60)*interval '1 second',reason_code=%s WHERE job_id=%s AND lease_token=%s AND status='running'",
                        (status, reason, job["job_id"], token),
                    )
                raise
    finally:
        if channel:
            channel.close()
    return completed
