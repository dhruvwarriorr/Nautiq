"""Bounded scientific runtime with explicit immutable expected-state loading."""

import os
import signal
from concurrent import futures

import grpc

from nautiuq_ml import __version__
from nautiuq_ml.gen.nautiuq.platform.v1 import platform_pb2, platform_pb2_grpc


class PlatformService(platform_pb2_grpc.PlatformServiceServicer):
    def __init__(self, service: str, runtime=None):
        self.service = service
        self.runtime = runtime

    def Check(self, request, context):
        caps, rid, sha = (
            self.runtime.capabilities()
            if self.runtime
            else (
                {
                    "expected_state": False,
                    "profile_anomaly": False,
                    "field_sampling": False,
                },
                "",
                "",
            )
        )
        return platform_pb2.CheckResponse(
            service=self.service,
            version=__version__,
            ready=True,
            capabilities=caps,
            expected_release_id=rid,
            expected_bundle_sha256=sha,
        )


def main():
    service = os.environ.get("SERVICE_NAME", "ml-inference")
    if service not in {"ml-inference", "field-service"}:
        raise ValueError("Unknown scientific service role")
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=4),
        options=[
            ("grpc.max_receive_message_length", 1024 * 1024),
            ("grpc.max_send_message_length", 1024 * 1024),
        ],
        maximum_concurrent_rpcs=16,
    )
    runtime = None
    if service == "ml-inference":
        from .expected_state.serving import PinnedRuntime, ExpectedService

        runtime = PinnedRuntime()
        platform_pb2_grpc.add_ExpectedStateServiceServicer_to_server(
            ExpectedService(runtime), server
        )
    platform_pb2_grpc.add_PlatformServiceServicer_to_server(
        PlatformService(service, runtime), server
    )
    if not server.add_insecure_port("[::]:50051"):
        raise RuntimeError("Cannot bind gRPC listener")
    server.start()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: server.stop(5))
    server.wait_for_termination()


if __name__ == "__main__":
    main()
