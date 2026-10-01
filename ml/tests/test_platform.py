from concurrent import futures

import grpc
import pytest

from nautiuq_ml.gen.nautiuq.platform.v1 import platform_pb2, platform_pb2_grpc
from nautiuq_ml.server import PlatformService


@pytest.mark.parametrize("service", ["ml-inference", "field-service"])
def test_generated_contract_round_trip(service):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=1))
    platform_pb2_grpc.add_PlatformServiceServicer_to_server(
        PlatformService(service), server
    )
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    try:
        with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
            response = platform_pb2_grpc.PlatformServiceStub(channel).Check(
                platform_pb2.CheckRequest(), timeout=2
            )
        assert response.ready
        assert response.service == service
        assert response.version == "0.1.0"
        assert response.capabilities == {"expected_state": False, "profile_anomaly": False, "field_sampling": False}
    finally:
        server.stop(0).wait()
