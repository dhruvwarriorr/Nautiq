"""Bounded native-model inference; missing or invalid releases fail closed."""

import json
import os
import threading
import uuid

import grpc

from ..gen.nautiq.platform.v1 import platform_pb2 as pb, platform_pb2_grpc as rpc
from .model import infer


class PinnedRuntime:
    def __init__(self, release_id=None):
        self.release_id = (
            release_id
            if release_id is not None
            else os.environ.get("ML_RELEASE_ID", "")
        )
        self.release = None
        self.bundle = None
        self.lock = threading.RLock()

    def load(self):
        if not self.release_id:
            raise ValueError("expected_release_not_configured")
        uuid.UUID(self.release_id)
        with self.lock:
            if self.bundle is None:
                from .pipeline import load_release

                release, bundle = load_release(self.release_id)
                if release["status"] != "ready" or not bundle["models"]:
                    raise ValueError("expected_release_unsupported")
                self.release, self.bundle = release, bundle
            return self.release, self.bundle

    def capabilities(self):
        try:
            release, bundle = self.load()
            return (
                {
                    "expected_state": True,
                    "ml_residual": any(
                        v["promotion"]["eligible"] for v in bundle["variables"].values()
                    ),
                    "profile_anomaly": False,
                    "field_sampling": False,
                },
                str(release["release_id"]),
                release["bundle_sha256"],
            )
        except Exception:
            return (
                {
                    "expected_state": False,
                    "ml_residual": False,
                    "profile_anomaly": False,
                    "field_sampling": False,
                },
                "",
                "",
            )


class ExpectedService(rpc.ExpectedStateServiceServicer):
    def __init__(self, runtime):
        self.runtime = runtime

    def Infer(self, request, context):
        if not 1 <= len(request.points) <= 32:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "expected_request_budget")
        if request.release_id != self.runtime.release_id:
            context.abort(
                grpc.StatusCode.FAILED_PRECONDITION, "expected_release_mismatch"
            )
        try:
            release, bundle = self.runtime.load()
        except Exception:
            context.abort(grpc.StatusCode.UNAVAILABLE, "expected_release_unavailable")
        rows = [
            {
                "latitude": p.latitude,
                "longitude": p.longitude,
                "depth_m": p.depth_m,
                "observed_at": p.observed_at,
            }
            for p in request.points
        ]
        try:
            if not context.is_active():
                context.abort(grpc.StatusCode.CANCELLED, "request_cancelled")
            result = infer(rows, bundle, request.explain)
            if not context.is_active():
                context.abort(grpc.StatusCode.CANCELLED, "request_cancelled")
        except ValueError:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "invalid_reference_points")
        except Exception:
            context.abort(grpc.StatusCode.INTERNAL, "expected_inference_unavailable")
        response = pb.ExpectedStateResponse(
            release_id=str(release["release_id"]),
            bundle_sha256=release["bundle_sha256"],
            method_version=result["method_version"],
            feature_version=result["feature_version"],
            estimand=result["estimand"],
            release_approved=False,
            interval_status=result["interval_status"],
            explanation_interpretation=result["explanation_interpretation"],
        )
        for row in result["rows"]:
            point = response.rows.add(depth_m=row["depth_m"])
            for variable in ("temperature_c", "practical_salinity"):
                saved = row[variable]
                output = getattr(point, variable)
                for name in (
                    "climatology_mean",
                    "candidate_mean",
                    "candidate_residual",
                    "expected_mean",
                    "ml_residual",
                    "contribution_bias",
                ):
                    if saved[name] is not None:
                        setattr(output, name, saved[name])
                for name in ("active_method", "reason", "candidate_reason"):
                    setattr(output, name, saved[name] or "")
                output.promotion_reasons.extend(saved["promotion_reasons"])
                for contribution in saved["feature_contributions"]:
                    output.feature_contributions.add(**contribution)
                output.baseline_support_json = json.dumps(
                    saved["baseline_support"], allow_nan=False
                ).encode()
        return response
