"""Disposable native uncertainty, publication, RPC, lease and revision integration."""

import base64
import json
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = globals().get("SAMPLES", {})
MIGRATIONS = globals().get("MIGRATIONS", [])
TRAINING = globals().get("TRAINING", {})
CLIMATE = globals().get("CLIMATE", {})
POLICY = globals().get("POLICY", {})
UNCERTAINTY = globals().get("UNCERTAINTY", {})


def launch():
    import math
    from datetime import datetime, timezone
    import netCDF4
    import numpy as np
    from verify_argo_parser import fixture

    samples = {}
    platform = 90000000 + int(uuid.uuid4().hex[:6], 16) % 9999000
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "fixture.nc"
        for i in range(73):
            n = i if i < 72 else 0
            fixture(path, "D", bad_salinity=i == 72)
            with netCDF4.Dataset(path, "a") as ds:
                platforms = np.array([str(platform + n % 4)] * 2, dtype="S8")
                ds["PLATFORM_NUMBER"][:] = np.frombuffer(
                    platforms.tobytes(), dtype="S1"
                ).reshape(2, 8)
                ds["CYCLE_NUMBER"][:] = [n + 1] * 2
                year = (
                    2005 + n // 12
                    if n < 24
                    else 2017 + (n - 24) // 12
                    if n < 48
                    else 2020
                    if n < 60
                    else 2023
                )
                t = datetime(year, n % 12 + 1, 15, tzinfo=timezone.utc)
                ds["JULD"][:] = [
                    (t - datetime(1950, 1, 1, tzinfo=timezone.utc)).total_seconds()
                    / 86400
                ] * 2
                ds["PRES_ADJUSTED"][:] = [[0, 100, 200]] * 2
                temp = 25 + math.sin(n % 12 * math.pi / 6) + (1 if i == 72 else 0)
                ds["TEMP_ADJUSTED"][:] = [[temp, temp - 2, temp - 4]] * 2
                if i == 72:
                    ds["DATE_UPDATE"][:] = np.frombuffer(b"20261002000000", dtype="S1")
            samples[str(i)] = base64.b64encode(path.read_bytes()).decode()
    values = {
        "SAMPLES": samples,
        "MIGRATIONS": [
            p.read_text() for p in sorted((ROOT / "migrations").glob("*.sql"))
        ],
        "TRAINING": json.loads(
            (ROOT / "packages/source-catalog/argo-training.json").read_text()
        ),
        "CLIMATE": json.loads(
            (ROOT / "packages/source-catalog/climatology.json").read_text()
        ),
        "UNCERTAINTY": json.loads(
            (ROOT / "packages/source-catalog/uncertainty.json").read_text()
        ),
        "POLICY": json.loads(
            (ROOT / "packages/source-catalog/expected-state.json").read_text()
        ),
    }
    code = "\n".join(f"{k}={v!r}" for k, v in values.items()) + "\n"
    code += (
        "import sys\nsys.argv=['verify_phase6_reliability.py','--inside']\n"
        + Path(__file__).read_text()
    )
    subprocess.run(
        [
            "docker",
            "compose",
            "run",
            "--rm",
            "--no-deps",
            "--entrypoint",
            "python",
            "ml-inference",
            "-",
        ],
        input=code,
        text=True,
        cwd=ROOT,
        check=True,
    )


def verify():
    import hashlib
    import io
    import os
    from concurrent import futures
    from datetime import datetime, timezone
    from urllib.parse import urlsplit, urlunsplit
    import grpc
    import psycopg
    from psycopg import sql
    from nautiq_ml.argo import evidence, snapshots, worker
    from nautiq_ml.argo.storage import read_object, store
    from nautiq_ml.climatology import pipeline as climate
    from nautiq_ml.expected_state import pipeline as expected
    from nautiq_ml.expected_state.serving import PinnedRuntime as MeanRuntime
    from nautiq_ml.uncertainty import jobs, pipeline
    from nautiq_ml.uncertainty.serving import UncertaintyService, PinnedRuntime
    from nautiq_ml.uncertainty.tracking import log_release
    from nautiq_ml.uncertainty.monitoring import monitor
    from nautiq_ml.gen.nautiq.platform.v1 import (
        platform_pb2 as pb,
        platform_pb2_grpc as rpc,
    )
    from nautiq_ml.server import PlatformService

    name = "interval_verify_" + uuid.uuid4().hex[:12]
    original = os.environ["DATABASE_URL"]
    admin = psycopg.connect(original, autocommit=True)
    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    parts = urlsplit(original)
    os.environ["DATABASE_URL"] = urlunsplit(
        (parts.scheme, parts.netloc, "/" + name, parts.query, parts.fragment)
    )
    s3, keys = store(), set()
    original_put = s3.put_object

    def track(bucket, key, *args, **kwargs):
        keys.add(key)
        return original_put(bucket, key, *args, **kwargs)

    s3.put_object = track
    worker.store = lambda: s3

    def query(statement, args=()):
        with psycopg.connect(os.environ["DATABASE_URL"]) as db:
            cur = db.execute(statement, args)
            return cur.fetchall() if cur.description else []

    def register(index):
        data = base64.b64decode(SAMPLES[str(index)])
        artifact, run = str(uuid.uuid4()), str(uuid.uuid4())
        sha = hashlib.sha256(data).hexdigest()
        key = f"verification/{name}/{index}.nc"
        s3.put_object("nautiq", key, io.BytesIO(data), len(data))
        query(
            "INSERT INTO ingestion_runs(run_id,source_id,run_kind,status) VALUES(%s,'argo_gdac','backfill','complete')",
            (run,),
        )
        query(
            "INSERT INTO raw_artifacts(artifact_id,source_id,source_path,source_url,source_updated_at,sha256,object_key,size_bytes,kind,run_id) VALUES(%s,'argo_gdac',%s,%s,now(),%s,%s,%s,'profile',%s)",
            (
                artifact,
                f"aoml/test/profiles/D{index}.nc",
                f"https://data-argo.ifremer.fr/dac/aoml/test/profiles/D{index}.nc",
                sha,
                key,
                len(data),
                run,
            ),
        )
        return json.dumps(
            {
                "event_id": str(uuid.uuid4()),
                "event_type": "raw.received",
                "schema_version": 1,
                "aggregate_key": artifact,
                "revision_sha256": sha,
                "payload": {"artifact_id": artifact},
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        ).encode()

    server = channel = None
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        policies = [
            path / (n + ".json")
            for n in ("training", "climate", "mean", "interval", "changed")
        ]
        tracking_uri = os.environ.get("MLFLOW_TRACKING_URI")
        os.environ["MLFLOW_TRACKING_URI"] = "sqlite:///" + str(path / "mlflow.db")
        os.environ["MLFLOW_ARTIFACT_ROOT"] = (path / "tracking-artifacts").as_uri()
        try:
            for migration in MIGRATIONS:
                query(migration)
            for i in range(72):
                assert worker.process(register(i)) == "normalized"
            p = {
                **UNCERTAINTY,
                "max_rounds": 8,
                "early_stopping_rounds": 3,
                "min_calibration_profiles": 10,
            }
            for file, value in zip(
                policies,
                (
                    TRAINING,
                    CLIMATE,
                    {**POLICY, "max_rounds": 8, "bootstrap_replicates": 10},
                    p,
                    {**p, "max_rounds": 9},
                ),
                strict=True,
            ):
                file.write_text(json.dumps(value))
            snap = snapshots.build(
                policies[0],
                query("SELECT clock_timestamp()")[0][0].isoformat(),
                s3,
                200,
            )
            reference = climate.build(snap["snapshot_id"], policies[1], s3)
            climate.select(reference["release_id"], s3)
            mean = expected.build(reference["release_id"], policies[2], s3, track=False)
            expected.select(mean["release_id"], s3)
            first = pipeline.build(mean["release_id"], policies[3], s3, track=False)
            assert first == pipeline.build(
                mean["release_id"], policies[3], s3, track=False
            )
            assert first["status"] == "ready" and not any(first["qualified"].values())
            assert pipeline.verify(first["release_id"], s3)["verified"]
            release, bundle = pipeline.load_release(first["release_id"], s3)
            logged = log_release(release, bundle)
            assert logged == log_release(release, bundle)
            assert query("SELECT count(*) FROM uncertainty_tracking")[0][0] == 1
            assert query("SELECT performance <> '{}'::jsonb FROM uncertainty_tracking")[
                0
            ][0]
            # Atomic release publication failure must roll back its calculation.
            query(
                "ALTER TABLE uncertainty_releases ADD CONSTRAINT forced_failure CHECK(status='invalid') NOT VALID"
            )
            count = query("SELECT count(*) FROM calculations")[0][0]
            try:
                pipeline.build(mean["release_id"], policies[4], s3, track=False)
            except psycopg.errors.CheckViolation:
                pass
            else:
                raise AssertionError("Failed publication survived")
            assert query("SELECT count(*) FROM calculations")[0][0] == count
            query("ALTER TABLE uncertainty_releases DROP CONSTRAINT forced_failure")
            second = pipeline.build(mean["release_id"], policies[4], s3, track=False)
            data = read_object(s3, first["bundle_key"], first["bundle_sha256"])
            s3.put_object("nautiq", first["bundle_key"], io.BytesIO(b"corrupt"), 7)
            try:
                pipeline.select(first["release_id"], s3)
            except ValueError:
                pass
            else:
                raise AssertionError("Corrupt model selected")
            s3.put_object(
                "nautiq",
                first["bundle_key"],
                io.BytesIO(data),
                len(data),
                metadata={"sha256": first["bundle_sha256"]},
            )
            assert pipeline.select(first["release_id"], s3)["profiles_queued"] == 144
            try:
                PinnedRuntime(first["release_id"], str(uuid.uuid4())).load()
            except ValueError as error:
                assert str(error) == "uncertainty_runtime_parent_mismatch"
            else:
                raise AssertionError("Wrong parent accepted")
            runtime = PinnedRuntime(first["release_id"], mean["release_id"])
            service = UncertaintyService(runtime)
            server = grpc.server(
                futures.ThreadPoolExecutor(max_workers=2),
                options=[("grpc.max_receive_message_length", 1048576)],
            )
            rpc.add_UncertaintyServiceServicer_to_server(service, server)
            rpc.add_PlatformServiceServicer_to_server(
                PlatformService(
                    "ml-inference", MeanRuntime(mean["release_id"]), runtime
                ),
                server,
            )
            port = server.add_insecure_port("127.0.0.1:0")
            server.start()
            channel = grpc.insecure_channel(f"127.0.0.1:{port}")
            client = rpc.UncertaintyServiceStub(channel)
            status = rpc.PlatformServiceStub(channel).Check(
                pb.CheckRequest(), timeout=3
            )
            assert (
                status.uncertainty_release_id == first["release_id"]
                and status.capabilities["predictive_intervals"]
                and not status.capabilities["calibrated_uncertainty"]
            )
            point = pb.ReferencePoint(
                latitude=15,
                longitude=70,
                depth_m=10,
                observed_at="2023-06-15T00:00:00Z",
            )
            for request, code in (
                (
                    pb.UncertaintyRequest(
                        release_id=second["release_id"], points=[point]
                    ),
                    grpc.StatusCode.FAILED_PRECONDITION,
                ),
                (
                    pb.UncertaintyRequest(
                        release_id=first["release_id"], points=[point] * 33
                    ),
                    grpc.StatusCode.INVALID_ARGUMENT,
                ),
                (
                    pb.UncertaintyRequest(
                        release_id=first["release_id"],
                        points=[
                            pb.ReferencePoint(
                                latitude=float("nan"),
                                longitude=70,
                                depth_m=10,
                                observed_at=point.observed_at,
                            )
                        ],
                    ),
                    grpc.StatusCode.INVALID_ARGUMENT,
                ),
            ):
                try:
                    client.Infer(request, timeout=3)
                except grpc.RpcError as error:
                    assert error.code() == code
                else:
                    raise AssertionError("Invalid RPC accepted")
            reply = client.Infer(
                pb.UncertaintyRequest(release_id=first["release_id"], points=[point]),
                timeout=3,
            )
            assert reply.rows[0].temperature_c.HasField("lower") and reply.rows[
                0
            ].temperature_c.HasField("expected_mean")
            assert jobs.recompute(200, s3, client) == 144
            assert query("SELECT count(*) FROM uncertainty_comparisons")[0][0] == 144
            event = register(72)
            target = query(
                "SELECT r.profile_id,r.revision_sha256 FROM profile_revisions r JOIN profiles p USING(profile_id) WHERE p.cycle_number=1 AND r.superseded_at IS NULL ORDER BY r.profile_id LIMIT 1"
            )[0]
            query(
                "UPDATE uncertainty_jobs SET status='pending',lease_until=NULL,next_attempt_at=now(),created_at=now()-interval '1 day' WHERE profile_id=%s",
                (target[0],),
            )
            publish, triggered = evidence.publish, False

            def revise(*args, **kwargs):
                nonlocal triggered
                result = publish(*args, **kwargs)
                if not triggered:
                    triggered = True
                    assert worker.process(event) == "normalized"
                return result

            evidence.publish = revise
            try:
                assert jobs.recompute(1, s3, client) == 0
            finally:
                evidence.publish = publish
            assert (
                query(
                    "SELECT status FROM uncertainty_jobs WHERE profile_id=%s AND revision_sha256=%s",
                    target,
                )[0][0]
                == "obsolete"
            )
            jobs.recompute(200, s3, client)
            assert (
                query(
                    "SELECT count(*) FROM calculations WHERE kind='uncertainty_comparison' AND state='stale'"
                )[0][0]
                == 2
            )
            # Changing the selected interval during publication invalidates late work.
            query(
                "UPDATE uncertainty_jobs SET status='pending',lease_until=NULL,next_attempt_at=now() WHERE status='complete'"
            )
            triggered = False

            def switch(*args, **kwargs):
                nonlocal triggered
                result = publish(*args, **kwargs)
                if not triggered:
                    triggered = True
                    pipeline.select(second["release_id"], s3)
                return result

            evidence.publish = switch
            try:
                assert jobs.recompute(1, s3, client) == 0
            finally:
                evidence.publish = publish
            service.runtime = PinnedRuntime(second["release_id"], mean["release_id"])
            jobs.recompute(200, s3, client)
            current = "SELECT count(*) FROM calculations WHERE kind='uncertainty_comparison' AND state='current'"
            assert query(current)[0][0] == 144, (
                query(current),
                query("SELECT status,count(*) FROM uncertainty_jobs GROUP BY status"),
            )
            # Parent selection mismatch stales evidence and blocks interval activation.
            policies[2].write_text(
                json.dumps({**POLICY, "max_rounds": 9, "bootstrap_replicates": 10})
            )
            other_mean = expected.build(
                reference["release_id"], policies[2], s3, track=False
            )
            expected.select(other_mean["release_id"], s3)
            assert query(current)[0][0] == 0
            try:
                pipeline.select(second["release_id"], s3)
            except ValueError:
                pass
            else:
                raise AssertionError("Mismatched mean selected")
            expected.select(mean["release_id"], s3)
            assert query(current)[0][0] == 144, (
                query(current),
                query("SELECT status,count(*) FROM uncertainty_jobs GROUP BY status"),
            )
            policies[1].write_text(json.dumps({**CLIMATE, "ridge_alpha": 2.0}))
            other_reference = climate.build(snap["snapshot_id"], policies[1], s3)
            climate.select(other_reference["release_id"], s3)
            assert query(current)[0][0] == 0
            climate.select(reference["release_id"], s3)
            assert query(current)[0][0] == 144, (
                query(current),
                query("SELECT status,count(*) FROM uncertainty_jobs GROUP BY status"),
            )
            watched = monitor()
            assert (
                watched["status"] == "monitored" and not watched["calibration_updated"]
            )
            assert (
                query(
                    "SELECT (report->>'trusted_profiles')::integer FROM uncertainty_health"
                )[0][0]
                == 0
            )
            # Lost lease cannot publish, and an outage is deferred for retry.
            query(
                "UPDATE uncertainty_jobs SET status='pending',lease_until=NULL,next_attempt_at=now() WHERE status='complete'"
            )

            def expire(*args, **kwargs):
                result = publish(*args, **kwargs)
                query(
                    "UPDATE uncertainty_jobs SET lease_until=now()-interval '1 second' WHERE status='running'"
                )
                return result

            evidence.publish = expire
            try:
                assert jobs.recompute(1, s3, client) == 0
            finally:
                evidence.publish = publish
            server.stop(0).wait()
            server = None
            query(
                "UPDATE uncertainty_jobs SET status='pending',lease_until=NULL,next_attempt_at=now() WHERE status='running'"
            )
            try:
                jobs.recompute(1, s3, client)
            except grpc.RpcError:
                pass
            else:
                raise AssertionError("RPC outage not deferred")
            assert (
                query(
                    "SELECT count(*) FROM uncertainty_jobs WHERE status='pending' AND reason_code='uncertainty_runtime_deferred'"
                )[0][0]
                >= 1
            )
            print(
                "Uncertainty integration passed: deterministic native releases, registry idempotency, atomic publication, corruption refusal, explicit parent pins, typed RPC budgets, revision and selection races, staleness restoration, lease loss, outage deferral and immutable monitoring."
            )
        finally:
            if server:
                server.stop(0).wait()
            if channel:
                channel.close()
            if tracking_uri:
                os.environ["MLFLOW_TRACKING_URI"] = tracking_uri
            else:
                os.environ.pop("MLFLOW_TRACKING_URI", None)
            os.environ["DATABASE_URL"] = original
            admin.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )
            admin.close()
            for key in keys:
                s3.remove_object("nautiq", key)


if __name__ == "__main__":
    verify() if "--inside" in sys.argv else launch()
