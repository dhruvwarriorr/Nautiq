"""Bounded single-profile inference with explicit anomaly and parent release pins."""

import os
import threading
import uuid

import grpc

from ..argo.evidence import canonical
from ..climatology.grid import VARIABLES
from ..gen.nautiq.platform.v1 import platform_pb2 as pb, platform_pb2_grpc as rpc
from . import METHOD
from .model import infer, loaded_parent


class PinnedRuntime:
    def __init__(self, release_id=None, uncertainty_id=None, expected_id=None):
        self.release_id = (
            os.environ.get("ANOMALY_RELEASE_ID", "")
            if release_id is None
            else release_id
        )
        self.uncertainty_id = (
            os.environ.get("UNCERTAINTY_RELEASE_ID", "")
            if uncertainty_id is None
            else uncertainty_id
        )
        self.expected_id = (
            os.environ.get("ML_RELEASE_ID", "") if expected_id is None else expected_id
        )
        self.release = self.bundle = None
        self.loaded = {}
        self.lock = threading.RLock()

    def load(self):
        if not self.release_id:
            raise ValueError("anomaly_release_not_configured")
        uuid.UUID(self.release_id)
        with self.lock:
            if self.bundle is None:
                from .pipeline import load_release

                release, bundle = load_release(self.release_id)
                if (
                    str(release["uncertainty_id"]) != self.uncertainty_id
                    or str(release["expected_id"]) != self.expected_id
                    or release["status"] != "ready"
                ):
                    raise ValueError("anomaly_runtime_parent_mismatch")
                self.loaded = loaded_parent(bundle["uncertainty"])
                self.release, self.bundle = release, bundle
            return self.release, self.bundle

    def capabilities(self):
        try:
            release, _ = self.load()
            return (
                {"profile_anomaly_diagnostics": True, "profile_anomaly": False},
                str(release["release_id"]),
                release["bundle_sha256"],
            )
        except Exception:
            return (
                {"profile_anomaly_diagnostics": False, "profile_anomaly": False},
                "",
                "",
            )


class AnomalyService(rpc.AnomalyServiceServicer):
    def __init__(self, runtime):
        self.runtime = runtime

    def Infer(self, request, context):
        if len(request.points) != 11:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "anomaly_profile_budget")
        if request.release_id != self.runtime.release_id:
            context.abort(
                grpc.StatusCode.FAILED_PRECONDITION, "anomaly_release_mismatch"
            )
        try:
            release, bundle = self.runtime.load()
        except Exception:
            context.abort(grpc.StatusCode.UNAVAILABLE, "anomaly_release_unavailable")
        rows = [
            {
                "latitude": p.location.latitude,
                "longitude": p.location.longitude,
                "depth_m": p.location.depth_m,
                "observed_at": p.location.observed_at,
                **{v: getattr(p, v) if p.HasField(v) else None for v in VARIABLES},
            }
            for p in request.points
        ]
        try:
            if not context.is_active():
                context.abort(grpc.StatusCode.CANCELLED, "request_cancelled")
            result = infer(rows, bundle, self.runtime.loaded)
            data = canonical(result)
            if len(data) > 262144:
                raise ValueError("anomaly_result_budget")
        except ValueError:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "invalid_anomaly_profile")
        except Exception:
            context.abort(grpc.StatusCode.INTERNAL, "anomaly_inference_unavailable")
        if not context.is_active():
            context.abort(grpc.StatusCode.CANCELLED, "request_cancelled")
        return pb.AnomalyResponse(
            release_id=str(release["release_id"]),
            bundle_sha256=release["bundle_sha256"],
            uncertainty_id=str(release["uncertainty_id"]),
            expected_id=str(release["expected_id"]),
            reference_id=str(release["reference_id"]),
            method_version=METHOD,
            result_json=data,
            release_approved=False,
        )
