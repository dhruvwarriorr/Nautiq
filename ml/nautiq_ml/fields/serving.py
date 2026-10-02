"""Read-only, bounded field RPCs; catalog and object failures stay explicit."""

import json
import signal
import time
from concurrent import futures

import grpc

from .. import __version__
from ..argo.storage import store, digest
from ..gen.nautiq.platform.v1 import platform_pb2 as pb, platform_pb2_grpc as rpc
from .core import FieldError, canonical, freshness
from .pipeline import connection, release
from .sampling import FieldGrid, polygon, route, tile
from .storage import open_grid, code_hash


class FieldService(rpc.FieldServiceServicer):
    def __init__(self, connect=connection, storage=store):
        self.connect, self.storage = connect, storage

    def load(self, rid):
        with self.connect() as db:
            row = release(db, rid)
        if row["status"] != "ready":
            raise FieldError("field_integrity_unavailable")
        group, metadata = open_grid(self.storage(), row)
        return row, FieldGrid(group, metadata)

    def execute(self, request, context, function, raster=False):
        started = time.monotonic()

        def check():
            if time.monotonic() - started > 5 or not context.is_active():
                raise FieldError("field_query_deadline")

        try:
            check()
            row, grid = self.load(request.release_id)
            grid.variable(request.variable)
            result = function(grid, check)
            evidence = {
                "release_id": str(row["release_id"]),
                "calculation_id": str(row["calculation_id"]),
                "manifest_sha256": row["manifest_sha256"],
                "created_at": row["created_at"].isoformat(),
                "source_version": row["source_version"],
                "metadata": grid.metadata,
                "freshness": freshness(grid.metadata, grid.as_of),
                "variable": request.variable,
                "release_approved": False,
                "calculation": {
                    "as_of": grid.as_of.isoformat(),
                    "method_version": grid.metadata["sampling_version"],
                    "code_sha256": code_hash(),
                    "request_sha256": digest(
                        request.SerializeToString(deterministic=True)
                    ),
                    "output_sha256": digest(result if raster else canonical(result)),
                },
            }
            check()
            if raster:
                return pb.FieldTileResponse(
                    release_id=request.release_id,
                    manifest_sha256=row["manifest_sha256"],
                    png=result,
                    metadata_json=canonical(evidence),
                )
            data = canonical({**evidence, "result": result})
            if len(data) > 900000:
                raise FieldError("field_response_budget")
            return pb.FieldEvidence(
                release_id=request.release_id,
                manifest_sha256=row["manifest_sha256"],
                result_json=data,
            )
        except FieldError as error:
            code = str(error)
            input_codes = {
                "invalid_release_id",
                "invalid_coordinate",
                "invalid_utc_time",
                "timezone_required",
                "variable_not_in_product",
                "timed_waypoints_required",
                "bounded_geojson_polygon_required",
                "invalid_polygon",
                "invalid_polygon_or_split_dateline_required",
                "invalid_tile_coordinate",
                "outside_horizon",
            }
            status = (
                grpc.StatusCode.NOT_FOUND
                if code == "field_not_found"
                else grpc.StatusCode.INVALID_ARGUMENT
                if code in input_codes
                or code.startswith("route_")
                or code == "polygon_cell_budget"
                else grpc.StatusCode.UNAVAILABLE
            )
            context.abort(status, code)
        except Exception:
            context.abort(
                grpc.StatusCode.UNAVAILABLE, "field_integrity_or_dependency_unavailable"
            )

    def Sample(self, request, context):
        if not request.HasField("point"):
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "timed_point_required")
        return self.execute(
            request,
            context,
            lambda g, c: g.sample(
                request.variable,
                request.point.latitude,
                request.point.longitude,
                request.point.time,
            ),
        )

    def Route(self, request, context):
        points = [
            {"latitude": p.latitude, "longitude": p.longitude, "time": p.time}
            for p in request.waypoints
        ]
        return self.execute(
            request,
            context,
            lambda g, c: route(
                g, request.variable, points, request.spacing_km, request.step_minutes, c
            ),
        )

    def Polygon(self, request, context):
        if not 0 < len(request.geometry_json) <= 16000:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "polygon_budget")
        try:
            geometry = json.loads(request.geometry_json)
        except (ValueError, UnicodeError):
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "invalid_polygon")
        return self.execute(
            request,
            context,
            lambda g, c: polygon(g, request.variable, geometry, request.time, c),
        )

    def Tile(self, request, context):
        return self.execute(
            request,
            context,
            lambda g, c: tile(
                g, request.variable, request.time, request.z, request.x, request.y, c
            ),
            raster=True,
        )


class Platform(rpc.PlatformServiceServicer):
    def __init__(self, fields):
        self.fields = fields

    def Check(self, request, context):
        sampling = False
        try:
            with self.fields.connect() as db:
                ids = db.execute(
                    "SELECT r.release_id FROM field_selection s JOIN field_releases r USING(release_id) WHERE r.status='ready' LIMIT 4"
                ).fetchall()
            for row in ids:
                _, grid = self.fields.load(str(row["release_id"]))
                if freshness(grid.metadata) == "available" and any(
                    count
                    < grid.metadata["shape"][0]
                    * grid.metadata["shape"][1]
                    * grid.metadata["shape"][2]
                    for count in grid.metadata["mask_counts"].values()
                ):
                    sampling = True
        except Exception:
            sampling = False
        return pb.CheckResponse(
            service="field-service",
            version=__version__,
            ready=True,
            capabilities={"field_sampling": sampling, "field_release_approved": False},
        )


def main():
    service = FieldService()
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=4),
        maximum_concurrent_rpcs=8,
        options=[
            ("grpc.max_receive_message_length", 1024 * 1024),
            ("grpc.max_send_message_length", 1024 * 1024),
        ],
    )
    rpc.add_FieldServiceServicer_to_server(service, server)
    rpc.add_PlatformServiceServicer_to_server(Platform(service), server)
    if not server.add_insecure_port("[::]:50051"):
        raise RuntimeError("Cannot bind field service")
    server.start()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: server.stop(5))
    server.wait_for_termination()


if __name__ == "__main__":
    main()
