"""Disposable SQL, real object storage, publication ordering and typed field gRPC checks."""

import json
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = globals().get("DATA", {})


def launch():
    data = {
        "OFFLINE": (ROOT / "scripts/verify_phase8.py").read_text(),
        "MIGRATIONS": [
            p.read_text() for p in sorted((ROOT / "migrations").glob("*.sql"))
        ],
    }
    code = "DATA=" + repr(data) + "\n" + Path(__file__).read_text()
    subprocess.run(
        [
            "docker",
            "compose",
            "run",
            "--rm",
            "--no-deps",
            "--entrypoint",
            "python",
            "field-service",
            "-",
        ],
        input=code,
        text=True,
        cwd=ROOT,
        check=True,
    )


def verify():
    import os
    from concurrent import futures
    from urllib.parse import urlsplit, urlunsplit
    import grpc
    import psycopg
    from psycopg.rows import dict_row
    from nautiq_ml.argo.storage import digest, put_immutable, store
    from nautiq_ml.fields.core import FieldError
    from nautiq_ml.fields.pipeline import publish, verify as verify_release, maintain
    from nautiq_ml.fields.serving import FieldService
    from nautiq_ml.gen.nautiq.platform.v1 import (
        platform_pb2 as pb,
        platform_pb2_grpc as rpc,
    )

    namespace = {"__name__": "field_fixtures"}
    exec(DATA["OFFLINE"], namespace)
    fixture = namespace["grid_fixture"]
    parsed = urlsplit(os.environ["DATABASE_URL"])
    database = "nautiq_fields_test_" + uuid.uuid4().hex[:12]
    admin = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    admin.execute("CREATE DATABASE " + database)
    dsn = urlunsplit(parsed._replace(path="/" + database))
    db = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
    s3, keys, server = store(), set(), None

    def connect():
        return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)

    def remember():
        for row in db.execute("SELECT manifest FROM field_releases").fetchall():
            manifest = row["manifest"]
            keys.update(manifest["zarr_prefix"] + key for key in manifest["files"])
            keys.add(
                manifest["zarr_prefix"].removesuffix("data.zarr/") + "manifest.json"
            )
        keys.update(
            row["manifest_key"]
            for row in db.execute(
                "SELECT manifest_key FROM calculations WHERE kind='field_normalization'"
            ).fetchall()
        )

    try:
        for migration in DATA["MIGRATIONS"]:
            db.execute(migration)
        raw = uuid.uuid4().bytes
        sha = digest(raw)
        raw_key = "fields/raw/" + sha
        keys.add(raw_key)
        put_immutable(s3, raw_key, raw)
        receipts = [
            {
                "url": "https://example.invalid/synthetic-field/" + database,
                "sha256": sha,
                "bytes": len(raw),
                "raw_key": raw_key,
            }
        ]
        grid = fixture()
        first = publish(db, s3, grid, receipts, "forecast")
        remember()
        assert (
            publish(db, s3, grid, receipts, "forecast")["release_id"]
            == first["release_id"]
        )
        assert db.execute("SELECT count(*) n FROM field_releases").fetchone()["n"] == 1
        assert db.execute("SELECT count(*) n FROM event_outbox").fetchone()["n"] == 1
        verify_release(db, s3, first["release_id"])

        # A transaction crash must not publish a SQL release or switch selection.
        def crash():
            raise FieldError("injected_atomic_rollback")

        failed_grid = fixture(offset=0.1)
        try:
            publish(db, s3, failed_grid, receipts, "forecast", before_commit=crash)
        except FieldError:
            pass
        else:
            raise AssertionError("publication rollback did not occur")
        assert db.execute("SELECT count(*) n FROM field_releases").fetchone()["n"] == 1
        # Retry recovers staged orphan bytes idempotently.
        publish(db, s3, failed_grid, receipts, "forecast")
        remember()
        newer = publish(
            db, s3, fixture(cycle="2026-10-02T06:00:00Z"), receipts, "forecast"
        )
        remember()
        publish(db, s3, grid, receipts, "forecast")
        selected = db.execute(
            "SELECT release_id FROM field_selection WHERE product_id='noaa_gfs_weather'"
        ).fetchone()["release_id"]
        assert str(selected) == newer["release_id"]
        # Final analysis replaces preliminary; late preliminary cannot reverse it.
        preliminary = publish(db, s3, fixture("noaa_oisst"), receipts, "preliminary")
        final = publish(db, s3, fixture("noaa_oisst"), receipts, "final")
        remember()
        publish(db, s3, fixture("noaa_oisst"), receipts, "preliminary")
        assert (
            str(
                db.execute(
                    "SELECT release_id FROM field_selection WHERE product_id='noaa_oisst'"
                ).fetchone()["release_id"]
            )
            == final["release_id"]
        )
        assert final["release_id"] != preliminary["release_id"]
        # Real typed gRPC endpoints pin exact requested releases and refuse malformed payloads.
        server = grpc.server(
            futures.ThreadPoolExecutor(max_workers=2),
            options=[
                ("grpc.max_receive_message_length", 1048576),
                ("grpc.max_send_message_length", 1048576),
            ],
        )
        rpc.add_FieldServiceServicer_to_server(
            FieldService(connect, lambda: s3), server
        )
        port = server.add_insecure_port("127.0.0.1:0")
        server.start()
        with grpc.insecure_channel("127.0.0.1:" + str(port)) as channel:
            client = rpc.FieldServiceStub(channel)
            point = pb.TimedFieldPoint(
                latitude=10.5, longitude=70.125, time="2026-10-02T01:30:00Z"
            )
            response = client.Sample(
                pb.FieldSampleRequest(
                    release_id=first["release_id"],
                    variable="wind_east_m_s",
                    point=point,
                ),
                timeout=6,
            )
            result = json.loads(response.result_json)
            assert (
                response.release_id == first["release_id"]
                and result["result"]["value"] == 12.5
                and result["release_approved"] is False
            )
            points = [
                pb.TimedFieldPoint(
                    latitude=10, longitude=70, time="2026-10-02T00:00:00Z"
                ),
                pb.TimedFieldPoint(
                    latitude=10, longitude=70.2, time="2026-10-02T01:00:00Z"
                ),
            ]
            response = client.Route(
                pb.FieldRouteRequest(
                    release_id=first["release_id"],
                    variable="wind_speed_m_s",
                    waypoints=points,
                    spacing_km=5,
                    step_minutes=30,
                ),
                timeout=6,
            )
            assert (
                json.loads(response.result_json)["result"]["sampling"]["sample_count"]
                > 2
            )
            png = client.Tile(
                pb.FieldTileRequest(
                    release_id=first["release_id"],
                    variable="wind_speed_m_s",
                    time=point.time,
                    z=3,
                    x=5,
                    y=3,
                ),
                timeout=6,
            )
            assert png.png.startswith(b"\x89PNG")
            geo = {
                "type": "Polygon",
                "coordinates": [[[70, 10], [70.5, 10], [70.5, 12], [70, 12], [70, 10]]],
            }
            response = client.Polygon(
                pb.FieldPolygonRequest(
                    release_id=first["release_id"],
                    variable="wind_speed_m_s",
                    time=point.time,
                    geometry_json=json.dumps(geo).encode(),
                ),
                timeout=6,
            )
            assert "native_cells" in json.loads(response.result_json)["result"]
            for request in [
                pb.FieldSampleRequest(
                    release_id=first["release_id"], variable="sst_c", point=point
                ),
                pb.FieldSampleRequest(
                    release_id=first["release_id"], variable="wind_speed_m_s"
                ),
                pb.FieldSampleRequest(
                    release_id=first["release_id"],
                    variable="wind_speed_m_s",
                    point=pb.TimedFieldPoint(
                        latitude=float("nan"), longitude=70, time=point.time
                    ),
                ),
            ]:
                try:
                    client.Sample(request, timeout=6)
                except grpc.RpcError as error:
                    assert error.code() == grpc.StatusCode.INVALID_ARGUMENT
                else:
                    raise AssertionError("invalid RPC accepted")
            row = db.execute(
                "SELECT * FROM field_releases WHERE release_id=%s",
                (newer["release_id"],),
            ).fetchone()
            chunk = row["manifest"]["zarr_prefix"] + "wind_east_m_s/0.0.0"
            response = s3.get_object("nautiq", chunk)
            data = response.read()
            response.close()
            response.release_conn()
            s3.remove_object("nautiq", chunk)
            reports = maintain(db, s3)
            assert any(r["status"] == "unavailable" for r in reports)
            try:
                client.Sample(
                    pb.FieldSampleRequest(
                        release_id=newer["release_id"],
                        variable="wind_east_m_s",
                        point=points[0],
                    ),
                    timeout=6,
                )
            except grpc.RpcError as error:
                assert error.code() == grpc.StatusCode.UNAVAILABLE
            else:
                raise AssertionError("unavailable release served")
            put_immutable(s3, chunk, data)
            maintain(db, s3)
            assert (
                db.execute(
                    "SELECT status FROM field_releases WHERE release_id=%s",
                    (newer["release_id"],),
                ).fetchone()["status"]
                == "ready"
            )
        print(
            "Disposable field reliability checks passed: atomic rollback/retry, idempotency/outbox, late-cycle refusal, preliminary/final supersession, typed point/route/polygon/tile RPCs, malformed payloads, missing-chunk withholding and restored integrity."
        )
    finally:
        if server:
            server.stop(0).wait()
        db.close()
        admin.execute("DROP DATABASE " + database + " WITH (FORCE)")
        admin.close()
        for key in keys:
            s3.remove_object("nautiq", key)


if __name__ == "__main__":
    if DATA:
        verify()
    else:
        launch()
