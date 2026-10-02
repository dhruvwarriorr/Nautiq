"""Disposable expected-state release/registry/RPC and revision-race integration."""

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
        for i in range(49):
            n = i if i < 48 else 0
            fixture(path, "D", bad_salinity=i == 48)
            with netCDF4.Dataset(path, "a") as ds:
                platforms = np.array([str(platform + n % 4)] * 2, dtype="S8")
                ds["PLATFORM_NUMBER"][:] = np.frombuffer(
                    platforms.tobytes(), dtype="S1"
                ).reshape(2, 8)
                ds["CYCLE_NUMBER"][:] = [n + 1] * 2
                year = 2005 + n // 12 if n < 24 else 2017 + (n - 24) // 12
                t = datetime(year, n % 12 + 1, 15, tzinfo=timezone.utc)
                ds["JULD"][:] = [
                    (t - datetime(1950, 1, 1, tzinfo=timezone.utc)).total_seconds()
                    / 86400
                ] * 2
                ds["PRES_ADJUSTED"][:] = [[0, 100, 200]] * 2
                temp = 25 + math.sin(n % 12 * math.pi / 6) + (1 if i == 48 else 0)
                ds["TEMP_ADJUSTED"][:] = [[temp, temp - 2, temp - 4]] * 2
                if i == 48:
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
        "POLICY": json.loads(
            (ROOT / "packages/source-catalog/expected-state.json").read_text()
        ),
    }
    code = "\n".join(f"{k}={v!r}" for k, v in values.items()) + "\n"
    code += (
        "import sys\nsys.argv=['verify_phase5_reliability.py','--inside']\n"
        + Path(__file__).read_text()
    )
    subprocess.run(
        ["docker", "compose", "exec", "-T", "ml-inference", "python", "-"],
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
    from nautiuq_ml.argo import evidence, snapshots, worker
    from nautiuq_ml.argo.storage import read_object, store
    from nautiuq_ml.climatology import pipeline as climate
    from nautiuq_ml.expected_state import jobs, pipeline
    from nautiuq_ml.expected_state.serving import ExpectedService, PinnedRuntime
    from nautiuq_ml.gen.nautiuq.platform.v1 import (
        platform_pb2 as pb,
        platform_pb2_grpc as rpc,
    )
    from nautiuq_ml.server import PlatformService

    name = "expected_verify_" + uuid.uuid4().hex[:12]
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
        s3.put_object("nautiuq", key, io.BytesIO(data), len(data))
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

    server = None
    channel = None
    with tempfile.TemporaryDirectory() as directory:
        paths = [
            Path(directory) / (n + ".json")
            for n in ("training", "climate", "expected", "changed")
        ]
        tracking_uri = os.environ.get("MLFLOW_TRACKING_URI")
        os.environ["MLFLOW_TRACKING_URI"] = "sqlite:///" + str(
            Path(directory) / "mlflow.db"
        )
        os.environ["MLFLOW_ARTIFACT_ROOT"] = (
            Path(directory) / "tracking-artifacts"
        ).as_uri()
        try:
            for migration in MIGRATIONS:
                query(migration)
            for i in range(48):
                assert worker.process(register(i)) == "normalized"
            paths[0].write_text(json.dumps(TRAINING))
            paths[1].write_text(json.dumps(CLIMATE))
            p = {**POLICY, "max_rounds": 20, "bootstrap_replicates": 10}
            paths[2].write_text(json.dumps(p))
            paths[3].write_text(json.dumps({**p, "max_rounds": 21}))
            snap = snapshots.build(
                paths[0], query("SELECT clock_timestamp()")[0][0].isoformat(), s3, 100
            )
            reference = climate.build(snap["snapshot_id"], paths[1], s3)
            climate.select(reference["release_id"], s3)
            first = pipeline.build(reference["release_id"], paths[2], s3, track=False)
            assert first == pipeline.build(
                reference["release_id"], paths[2], s3, track=False
            )
            assert first["model_count"] == 2 and first["active_methods"] == {
                "temperature_c": "climatology",
                "practical_salinity": "climatology",
            }
            assert pipeline.verify(first["release_id"], s3)["verified"]
            release, bundle = pipeline.load_release(first["release_id"], s3)
            climate_hash = climate.code_hash
            climate.code_hash = lambda: "0" * 64
            try:
                pipeline.load_release(first["release_id"], s3)
            except ValueError as error:
                assert str(error) == "expected_bundle_version_mismatch"
            else:
                raise AssertionError("Changed climatology implementation was accepted")
            finally:
                climate.code_hash = climate_hash
            from nautiuq_ml.expected_state.tracking import log_release

            logged = log_release(release, bundle)
            assert logged == log_release(release, bundle)
            assert query("SELECT count(*) FROM expected_state_tracking")[0][0] == 1
            query(
                "ALTER TABLE expected_state_releases ADD CONSTRAINT forced_failure CHECK(status='invalid') NOT VALID"
            )
            count = query("SELECT count(*) FROM calculations")[0][0]
            try:
                pipeline.build(reference["release_id"], paths[3], s3, track=False)
            except psycopg.errors.CheckViolation:
                pass
            else:
                raise AssertionError("Failed model publication survived")
            assert query("SELECT count(*) FROM calculations")[0][0] == count
            query("ALTER TABLE expected_state_releases DROP CONSTRAINT forced_failure")
            second = pipeline.build(reference["release_id"], paths[3], s3, track=False)
            data = read_object(s3, first["bundle_key"], first["bundle_sha256"])
            s3.put_object("nautiuq", first["bundle_key"], io.BytesIO(b"corrupt"), 7)
            try:
                pipeline.select(first["release_id"], s3)
            except ValueError:
                pass
            else:
                raise AssertionError("Corrupt model selected")
            s3.put_object(
                "nautiuq",
                first["bundle_key"],
                io.BytesIO(data),
                len(data),
                metadata={"sha256": first["bundle_sha256"]},
            )
            assert pipeline.select(first["release_id"], s3)["profiles_queued"] == 96
            runtime = PinnedRuntime(first["release_id"])
            service = ExpectedService(runtime)
            server = grpc.server(
                futures.ThreadPoolExecutor(max_workers=2),
                options=[
                    ("grpc.max_receive_message_length", 1024 * 1024),
                    ("grpc.max_send_message_length", 1024 * 1024),
                ],
            )
            rpc.add_ExpectedStateServiceServicer_to_server(service, server)
            rpc.add_PlatformServiceServicer_to_server(
                PlatformService("ml-inference", runtime), server
            )
            port = server.add_insecure_port("127.0.0.1:0")
            server.start()
            channel = grpc.insecure_channel(f"127.0.0.1:{port}")
            client = rpc.ExpectedStateServiceStub(channel)
            status = rpc.PlatformServiceStub(channel).Check(
                pb.CheckRequest(), timeout=3
            )
            assert (
                status.expected_release_id == first["release_id"]
                and status.capabilities["expected_state"]
                and not status.capabilities["ml_residual"]
            )
            point = pb.ReferencePoint(
                latitude=15,
                longitude=70,
                depth_m=10,
                observed_at="2023-06-15T00:00:00Z",
            )
            for request, code in (
                (
                    pb.ExpectedStateRequest(
                        release_id=second["release_id"], points=[point]
                    ),
                    grpc.StatusCode.FAILED_PRECONDITION,
                ),
                (
                    pb.ExpectedStateRequest(
                        release_id=first["release_id"], points=[point] * 33
                    ),
                    grpc.StatusCode.INVALID_ARGUMENT,
                ),
                (
                    pb.ExpectedStateRequest(
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
                pb.ExpectedStateRequest(
                    release_id=first["release_id"], points=[point], explain=True
                ),
                timeout=3,
            )
            assert reply.rows[0].temperature_c.HasField("expected_mean")
            assert reply.rows[0].temperature_c.active_method == "climatology"
            assert jobs.recompute(100, s3, client) == 96
            assert query("SELECT count(*) FROM expected_state_comparisons")[0][0] == 96
            # Upstream revision arrives after RPC but before SQL publication.
            event = register(48)
            target = query(
                "SELECT r.profile_id,r.revision_sha256 FROM profile_revisions r JOIN profiles p USING(profile_id) WHERE p.cycle_number=1 AND r.superseded_at IS NULL ORDER BY r.profile_id LIMIT 1"
            )[0]
            query(
                "UPDATE expected_state_jobs SET status='pending',lease_until=NULL,next_attempt_at=now(),created_at=now()-interval '1 day' WHERE profile_id=%s",
                (target[0],),
            )
            publish = evidence.publish
            triggered = False

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
                    "SELECT status FROM expected_state_jobs WHERE profile_id=%s AND revision_sha256=%s",
                    target,
                )[0][0]
                == "obsolete"
            )
            jobs.recompute(100, s3, client)
            assert (
                query(
                    "SELECT count(*) FROM calculations WHERE kind='expected_state_comparison' AND state='stale'"
                )[0][0]
                == 2
            )
            # Explicit model change during publication prevents obsolete work from publishing.
            query(
                "UPDATE expected_state_jobs SET status='pending',lease_until=NULL,next_attempt_at=now() WHERE status='complete'"
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
            service.runtime = PinnedRuntime(second["release_id"])
            jobs.recompute(200, s3, client)
            assert (
                query(
                    "SELECT count(*) FROM expected_state_comparisons v JOIN profile_revisions r USING(profile_id,revision_sha256) WHERE v.release_id=%s AND r.superseded_at IS NULL",
                    (second["release_id"],),
                )[0][0]
                == 96
            )
            # Full source-reference changes stale/restore matching cached evidence atomically.
            paths[1].write_text(json.dumps({**CLIMATE, "ridge_alpha": 2.0}))
            other_reference = climate.build(snap["snapshot_id"], paths[1], s3)
            climate.select(other_reference["release_id"], s3)
            assert (
                query(
                    "SELECT count(*) FROM calculations WHERE kind='expected_state_comparison' AND state='current'"
                )[0][0]
                == 0
            )
            try:
                pipeline.select(second["release_id"], s3)
            except ValueError as error:
                assert str(error) == "expected_climatology_selection_mismatch"
            else:
                raise AssertionError("Model/reference mismatch selected")
            climate.select(reference["release_id"], s3)
            assert (
                query(
                    "SELECT count(*) FROM calculations WHERE kind='expected_state_comparison' AND state='current'"
                )[0][0]
                == 96
            )
            jid = query(
                "SELECT job_id FROM expected_state_jobs WHERE release_id=%s AND status='complete' LIMIT 1",
                (second["release_id"],),
            )[0][0]
            query(
                "UPDATE expected_state_jobs SET status='running',lease_until=now()-interval '1 minute',lease_token=%s WHERE job_id=%s",
                (str(uuid.uuid4()), jid),
            )
            assert jobs.recompute(1, s3, client) == 1
            query(
                "UPDATE expected_state_jobs SET status='pending',lease_until=NULL WHERE job_id=%s",
                (jid,),
            )

            def lose_lease(*args, **kwargs):
                result = publish(*args, **kwargs)
                query(
                    "UPDATE expected_state_jobs SET lease_token=%s,lease_until=now()-interval '1 minute' WHERE job_id=%s",
                    (str(uuid.uuid4()), jid),
                )
                return result

            evidence.publish = lose_lease
            try:
                assert jobs.recompute(1, s3, client) == 0
            finally:
                evidence.publish = publish
            assert jobs.recompute(1, s3, client) == 1
            # Runtime failure defers jobs without destroying valid observations or cached evidence.
            query(
                "UPDATE expected_state_jobs SET status='pending',lease_until=NULL WHERE job_id=%s",
                (jid,),
            )
            server.stop(0).wait()
            server = None
            try:
                jobs.recompute(1, s3, client)
            except grpc.RpcError:
                pass
            else:
                raise AssertionError("Unavailable runtime did not defer work")
            assert query(
                "SELECT status,reason_code FROM expected_state_jobs WHERE job_id=%s",
                (jid,),
            )[0] == ("pending", "expected_runtime_deferred")
            assert (
                query(
                    "SELECT count(*) FROM profile_revisions WHERE science_ready AND superseded_at IS NULL"
                )[0][0]
                == 96
            )
            assert read_object(s3, first["bundle_key"], first["bundle_sha256"]) == data
            assert (
                query(
                    "SELECT state FROM calculations WHERE calculation_id=%s",
                    (first["calculation_id"],),
                )[0][0]
                == "frozen"
            )
            print(
                "Disposable expected-state gate passed: repeatable native fits, MLflow registry idempotence, checksums, rollback, typed RPC refusal/additivity/fallback, revision/model/reference races, lease ownership/recovery, runtime deferral and frozen evidence"
            )
        finally:
            if server:
                server.stop(0).wait()
            if channel:
                channel.close()
            for key in keys:
                s3.remove_object("nautiuq", key)
            os.environ["DATABASE_URL"] = original
            if tracking_uri:
                os.environ["MLFLOW_TRACKING_URI"] = tracking_uri
            os.environ.pop("MLFLOW_ARTIFACT_ROOT", None)
            admin.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )
            admin.close()


if __name__ == "__main__":
    verify() if "--inside" in sys.argv else launch()
