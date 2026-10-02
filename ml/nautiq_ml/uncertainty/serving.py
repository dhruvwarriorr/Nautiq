"""Explicit uncertainty/mean pins; nullable diagnostic predictive intervals."""

import os
import threading
import uuid

import grpc
import numpy as np

from ..climatology.grid import VARIABLES
from ..expected_state.features import VERSION, vector
from ..expected_state.model import infer as mean_infer
from ..gen.nautiq.platform.v1 import platform_pb2 as pb, platform_pb2_grpc as rpc
from .calibration import choose
from .quantiles import METHOD, envelope, native, predict


def infer(rows, bundle, loaded=None):
    if not 1 <= len(rows) <= 32:
        raise ValueError("uncertainty_request_budget")
    x = np.array([vector(r, bundle["climatology"]["policy"]) for r in rows])
    means = mean_infer(rows, bundle["expected_state"])["rows"]
    output = [{"depth_m": r["depth_m"]} for r in rows]
    for v in VARIABLES:
        info = bundle["variables"][v]
        family = info.get("selected_family")
        artifact = bundle["models"].get(v, {}).get(family)
        residual = (
            predict(artifact, x, loaded.get(v) if loaded else None)
            if artifact
            else None
        )
        for i, row in enumerate(rows):
            point = {
                "expected_mean": means[i][v]["expected_mean"],
                "q10": None,
                "q50": None,
                "q90": None,
                "lower": None,
                "upper": None,
                "correction": None,
                "status": "unavailable",
                "reason": "unsupported_quantile_coverage",
                "family": family or "unavailable",
                "calibration_group": None,
                "requested_group": None,
                "calibration_profiles": 0,
                "calibration_rank": None,
                "fallback": False,
                "fallback_reasons": [],
                "quantile_crossing": False,
                "coverage_qualified": False,
            }
            base = means[i][v]["climatology_mean"]
            if artifact and base is not None and envelope(row, artifact):
                raw = base + residual[i]
                if not np.isfinite(raw).all():
                    raise ValueError("nonfinite_quantile_output")
                q = np.sort(raw)
                selected = choose(
                    row, bundle["climatology"]["policy"], artifact["calibration"]
                )
                point.update(
                    q10=float(q[0]),
                    q50=float(q[1]),
                    q90=float(q[2]),
                    quantile_crossing=bool(np.any(np.diff(raw) < 0)),
                    calibration_group=selected["group"],
                    requested_group=selected["requested_group"],
                    calibration_profiles=selected["profiles"],
                    calibration_rank=selected["rank"],
                    fallback=selected["fallback"],
                    fallback_reasons=selected["fallback_reasons"],
                    reason=selected["reason"],
                )
                if selected["correction"] is not None:
                    correction = selected["correction"]
                    point.update(
                        lower=float(q[0] - correction),
                        upper=float(q[2] + correction),
                        correction=correction,
                        status="qualified_calibrated"
                        if info["coverage_gate"]["qualified"]
                        else "diagnostic_calibrated",
                        coverage_qualified=info["coverage_gate"]["qualified"],
                    )
            output[i][v] = point
    return {
        "rows": output,
        "method_version": METHOD,
        "feature_version": VERSION,
        "nominal_coverage": bundle["nominal_coverage"],
        "coverage_unit": bundle["coverage_unit"],
        "interval_interpretation": bundle["interval_interpretation"],
        "release_approved": False,
    }


class PinnedRuntime:
    def __init__(self, release_id=None, expected_id=None):
        self.release_id = (
            os.environ.get("UNCERTAINTY_RELEASE_ID", "")
            if release_id is None
            else release_id
        )
        self.expected_id = (
            os.environ.get("ML_RELEASE_ID", "") if expected_id is None else expected_id
        )
        self.release = self.bundle = None
        self.loaded = {}
        self.lock = threading.RLock()

    def load(self):
        if not self.release_id:
            raise ValueError("uncertainty_release_not_configured")
        uuid.UUID(self.release_id)
        with self.lock:
            if self.bundle is None:
                from .pipeline import load_release

                release, bundle = load_release(self.release_id)
                if (
                    str(release["expected_id"]) != self.expected_id
                    or release["status"] != "ready"
                ):
                    raise ValueError("uncertainty_runtime_parent_mismatch")
                self.loaded = {
                    v: native(families[bundle["variables"][v]["selected_family"]])
                    for v, families in bundle["models"].items()
                }
                self.release, self.bundle = release, bundle
            return self.release, self.bundle

    def capabilities(self):
        try:
            release, bundle = self.load()
            return (
                {
                    "predictive_intervals": True,
                    "calibrated_uncertainty": any(
                        v["coverage_gate"]["qualified"]
                        for v in bundle["variables"].values()
                    ),
                },
                str(release["release_id"]),
                release["bundle_sha256"],
            )
        except Exception:
            return (
                {"predictive_intervals": False, "calibrated_uncertainty": False},
                "",
                "",
            )


class UncertaintyService(rpc.UncertaintyServiceServicer):
    def __init__(self, runtime):
        self.runtime = runtime

    def Infer(self, request, context):
        if not 1 <= len(request.points) <= 32:
            context.abort(
                grpc.StatusCode.INVALID_ARGUMENT, "uncertainty_request_budget"
            )
        if request.release_id != self.runtime.release_id:
            context.abort(
                grpc.StatusCode.FAILED_PRECONDITION, "uncertainty_release_mismatch"
            )
        try:
            release, bundle = self.runtime.load()
        except Exception:
            context.abort(
                grpc.StatusCode.UNAVAILABLE, "uncertainty_release_unavailable"
            )
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
            result = infer(rows, bundle, self.runtime.loaded)
        except ValueError:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "invalid_reference_points")
        except Exception:
            context.abort(grpc.StatusCode.INTERNAL, "uncertainty_inference_unavailable")
        if not context.is_active():
            context.abort(grpc.StatusCode.CANCELLED, "request_cancelled")
        response = pb.UncertaintyResponse(
            release_id=str(release["release_id"]),
            bundle_sha256=release["bundle_sha256"],
            expected_id=str(release["expected_id"]),
            reference_id=str(release["reference_id"]),
            **{
                k: result[k]
                for k in (
                    "method_version",
                    "feature_version",
                    "nominal_coverage",
                    "coverage_unit",
                    "interval_interpretation",
                    "release_approved",
                )
            },
        )
        for row in result["rows"]:
            depth = response.rows.add(depth_m=row["depth_m"])
            for v in VARIABLES:
                saved, point = row[v], getattr(depth, v)
                for key in (
                    "expected_mean",
                    "q10",
                    "q50",
                    "q90",
                    "lower",
                    "upper",
                    "correction",
                ):
                    if saved[key] is not None:
                        setattr(point, key, saved[key])
                for key in (
                    "status",
                    "reason",
                    "family",
                    "calibration_group",
                    "requested_group",
                ):
                    setattr(point, key, saved[key] or "")
                for key in (
                    "calibration_profiles",
                    "calibration_rank",
                    "fallback",
                    "quantile_crossing",
                    "coverage_qualified",
                ):
                    setattr(point, key, saved[key] or 0)
                point.fallback_reasons.extend(saved["fallback_reasons"])
        return response
