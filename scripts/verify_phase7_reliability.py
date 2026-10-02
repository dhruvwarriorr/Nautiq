"""Disposable profile scoring, publication, ancestor, RPC, lease and revision integration."""

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
ANOMALY = globals().get("ANOMALY", {})


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
        for i in range(121):
            n = i if i < 120 else 0
            fixture(path, "D", bad_salinity=i == 120, levels=13)
            with netCDF4.Dataset(path, "a") as ds:
                platforms = np.array([str(platform + n % 4)] * 2, dtype="S8")
                ds["PLATFORM_NUMBER"][:] = np.frombuffer(
                    platforms.tobytes(), dtype="S1"
                ).reshape(2, 8)
                ds["CYCLE_NUMBER"][:] = [n + 1] * 2
                year = (
                    2005 + n // 12
                    if n < 48
                    else 2017 + (n - 48) // 12
                    if n < 72
                    else 2020 + (n - 72) // 12
                    if n < 96
                    else 2023
                )
                t = datetime(year, n % 12 + 1, 15, tzinfo=timezone.utc)
                ds["JULD"][:] = [
                    (t - datetime(1950, 1, 1, tzinfo=timezone.utc)).total_seconds()
                    / 86400
                ] * 2
                depths = np.array(
                    [0, 10, 20, 30, 50, 75, 100, 150, 200, 300, 400, 500, 600]
                )
                ds["PRES_ADJUSTED"][:] = [depths] * 2
                seasonal = math.sin(n % 12 * math.pi / 6)
                noise = (
                    sum(
                        np.sin(n * (k + 1) * 1.73) * np.cos(depths / (20 + 50 * k))
                        for k in range(5)
                    )
                    * 0.3
                )
                temp = 25 - 0.015 * depths + seasonal + noise + (1 if i == 120 else 0)
                salt = 35 + 0.001 * depths + 0.1 * seasonal + 0.1 * noise
                ds["TEMP_ADJUSTED"][:] = [temp] * 2
                ds["PSAL_ADJUSTED"][:] = [salt] * 2
                if i == 120:
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
        "ANOMALY": json.loads(
            (ROOT / "packages/source-catalog/anomaly.json").read_text()
        ),
        "POLICY": json.loads(
            (ROOT / "packages/source-catalog/expected-state.json").read_text()
        ),
    }
    code = "\n".join(f"{k}={v!r}" for k, v in values.items()) + "\n"
    code += (
        "import sys\nsys.argv=['verify_phase7_reliability.py','--inside']\n"
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
    from nautiq_ml.argo.storage import store
    from nautiq_ml.climatology import pipeline as climate
    from nautiq_ml.expected_state import pipeline as expected
    from nautiq_ml.expected_state.serving import PinnedRuntime as MeanRuntime
    from nautiq_ml.uncertainty import pipeline as interval
    from nautiq_ml.anomaly import jobs, pipeline
    from nautiq_ml.anomaly.serving import AnomalyService, PinnedRuntime
    from nautiq_ml.anomaly.tracking import log_release
    from nautiq_ml.gen.nautiq.platform.v1 import (
        platform_pb2 as pb,
        platform_pb2_grpc as rpc,
    )
    from nautiq_ml.server import PlatformService

    name = "anomaly_verify_" + uuid.uuid4().hex[:12]
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
            for n in ("training", "climate", "mean", "interval", "anomaly", "changed")
        ]
        tracking_uri = os.environ.get("MLFLOW_TRACKING_URI")
        os.environ["MLFLOW_TRACKING_URI"] = "sqlite:///" + str(path / "mlflow.db")
        os.environ["MLFLOW_ARTIFACT_ROOT"] = (path / "tracking-artifacts").as_uri()
        try:
            for migration in MIGRATIONS:
                query(migration)
            for i in range(120):
                assert worker.process(register(i)) == "normalized"
            values = (
                TRAINING,
                CLIMATE,
                {**POLICY, "max_rounds": 8, "bootstrap_replicates": 10},
                {**UNCERTAINTY, "max_rounds": 8, "early_stopping_rounds": 3},
                ANOMALY,
                {**ANOMALY, "seed": 43},
            )
            for file, value in zip(policies, values, strict=True):
                file.write_text(json.dumps(value))
            snap = snapshots.build(
                policies[0],
                query("SELECT clock_timestamp()")[0][0].isoformat(),
                s3,
                500,
            )
            reference = climate.build(snap["snapshot_id"], policies[1], s3)
            climate.select(reference["release_id"], s3)
            mean = expected.build(reference["release_id"], policies[2], s3, track=False)
            expected.select(mean["release_id"], s3)
            parent = interval.build(mean["release_id"], policies[3], s3, track=False)
            interval.select(parent["release_id"], s3)
            first = pipeline.build(parent["release_id"], policies[4], s3, track=False)
            assert first == pipeline.build(
                parent["release_id"], policies[4], s3, track=False
            )
            assert first["status"] == "ready"
            assert pipeline.verify(first["release_id"], s3)["current_code_compatible"]
            release, bundle = pipeline.load_release(first["release_id"], s3)
            logged = log_release(release, bundle)
            assert logged == log_release(release, bundle)
            assert query("SELECT count(*) FROM anomaly_tracking")[0][0] == 1
            count = query("SELECT count(*) FROM calculations")[0][0]
            query(
                "ALTER TABLE anomaly_releases ADD CONSTRAINT forced_failure CHECK(status='invalid') NOT VALID"
            )
            try:
                pipeline.build(parent["release_id"], policies[5], s3, track=False)
            except psycopg.errors.CheckViolation:
                pass
            else:
                raise AssertionError("Publication did not roll back")
            assert query("SELECT count(*) FROM calculations")[0][0] == count
            query("ALTER TABLE anomaly_releases DROP CONSTRAINT forced_failure")
            second = pipeline.build(parent["release_id"], policies[5], s3, track=False)
            original_read = pipeline.read_object

            def corrupt(*args, **kwargs):
                return (
                    b"corrupt"
                    if args[1] == release["bundle_key"]
                    else original_read(*args, **kwargs)
                )

            pipeline.read_object = corrupt
            try:
                try:
                    pipeline.load_release(first["release_id"], s3)
                except (ValueError, json.JSONDecodeError):
                    pass
                else:
                    raise AssertionError("Corrupt bundle accepted")
            finally:
                pipeline.read_object = original_read
            query(
                "UPDATE anomaly_releases SET bundle_sha256=%s WHERE release_id=%s",
                ("a" * 64, first["release_id"]),
            )
            try:
                try:
                    pipeline.load_release(first["release_id"], s3)
                except ValueError:
                    pass
                else:
                    raise AssertionError("Artifact checksum mismatch accepted")
            finally:
                query(
                    "UPDATE anomaly_releases SET bundle_sha256=%s WHERE release_id=%s",
                    (release["bundle_sha256"], first["release_id"]),
                )
            pipeline.select(first["release_id"], s3)
            runtime = PinnedRuntime(
                first["release_id"], parent["release_id"], mean["release_id"]
            )
            service = AnomalyService(runtime)
            server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
            rpc.add_AnomalyServiceServicer_to_server(service, server)
            rpc.add_PlatformServiceServicer_to_server(
                PlatformService(
                    "ml-inference", MeanRuntime(mean["release_id"]), anomaly=runtime
                ),
                server,
            )
            port = server.add_insecure_port("127.0.0.1:0")
            server.start()
            channel = grpc.insecure_channel(f"127.0.0.1:{port}")
            client = rpc.AnomalyServiceStub(channel)
            caps = rpc.PlatformServiceStub(channel).Check(pb.CheckRequest(), timeout=10)
            assert (
                caps.capabilities["profile_anomaly_diagnostics"]
                and not caps.capabilities["profile_anomaly"]
            )
            points = [
                pb.AnomalyPoint(
                    location=pb.ReferencePoint(
                        latitude=15,
                        longitude=70,
                        depth_m=z,
                        observed_at="2023-06-15T00:00:00Z",
                    ),
                    temperature_c=25 - 0.015 * z,
                    practical_salinity=35 + 0.001 * z,
                )
                for z in ANOMALY["depths_m"]
            ]
            bad = pb.AnomalyPoint(
                location=pb.ReferencePoint(
                    latitude=float("nan"),
                    longitude=70,
                    depth_m=10,
                    observed_at="2023-06-15T00:00:00Z",
                ),
                temperature_c=25,
            )
            for request, code in (
                (
                    pb.AnomalyRequest(release_id=second["release_id"], points=points),
                    grpc.StatusCode.FAILED_PRECONDITION,
                ),
                (
                    pb.AnomalyRequest(
                        release_id=first["release_id"], points=points * 3
                    ),
                    grpc.StatusCode.INVALID_ARGUMENT,
                ),
                (
                    pb.AnomalyRequest(
                        release_id=first["release_id"], points=[bad] + points[1:]
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
                pb.AnomalyRequest(release_id=first["release_id"], points=points),
                timeout=3,
            )
            assert (
                reply.uncertainty_id == parent["release_id"]
                and json.loads(reply.result_json)["supported_variables"] == 2
            )
            assert jobs.recompute(500, s3, client) == 240
            assert query("SELECT count(*) FROM anomaly_comparisons")[0][0] == 240
            picked = query(
                "SELECT job_id FROM anomaly_jobs ORDER BY created_at,job_id LIMIT 1"
            )[0][0]
            query(
                "UPDATE anomaly_jobs SET status='pending',lease_until=NULL,next_attempt_at=now() WHERE job_id=%s",
                (picked,),
            )

            class MalformedClient:
                def Infer(self, *args, **kwargs):
                    response = client.Infer(*args, **kwargs)
                    response.result_json = b"{}"
                    return response

            try:
                jobs.recompute(1, s3, MalformedClient())
            except ValueError:
                pass
            else:
                raise AssertionError("Malformed RPC result published")
            assert query(
                "SELECT status,reason_code FROM anomaly_jobs WHERE job_id=%s", (picked,)
            )[0] == ("quarantined", "anomaly_rpc_malformed_result")
            query(
                "UPDATE anomaly_jobs SET status='pending',lease_until=NULL,next_attempt_at=now() WHERE job_id=%s",
                (picked,),
            )
            assert jobs.recompute(1, s3, client) == 1
            event = register(120)
            target = query(
                "SELECT r.profile_id,r.revision_sha256 FROM profile_revisions r JOIN profiles p USING(profile_id) WHERE p.cycle_number=1 AND r.superseded_at IS NULL ORDER BY r.profile_id LIMIT 1"
            )[0]
            query(
                "UPDATE anomaly_jobs SET status='pending',lease_until=NULL,next_attempt_at=now(),created_at=now()-interval '1 day' WHERE profile_id=%s",
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
                    "SELECT status FROM anomaly_jobs WHERE profile_id=%s AND revision_sha256=%s",
                    target,
                )[0][0]
                == "obsolete"
            )
            jobs.recompute(500, s3, client)
            current = "SELECT count(*) FROM calculations WHERE kind='anomaly_comparison' AND state='current'"
            assert query(current)[0][0] == 240
            query(
                "UPDATE anomaly_jobs SET status='pending',lease_until=NULL,next_attempt_at=now() WHERE status='complete'"
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
            service.runtime = PinnedRuntime(
                second["release_id"], parent["release_id"], mean["release_id"]
            )
            jobs.recompute(500, s3, client)
            assert query(current)[0][0] == 240
            # Each ancestor selection independently invalidates comparisons and blocks selection.
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
            assert query(current)[0][0] == 240
            policies[1].write_text(json.dumps({**CLIMATE, "ridge_alpha": 2.0}))
            other_ref = climate.build(snap["snapshot_id"], policies[1], s3)
            climate.select(other_ref["release_id"], s3)
            assert query(current)[0][0] == 0
            climate.select(reference["release_id"], s3)
            assert query(current)[0][0] == 240
            policies[3].write_text(
                json.dumps({**UNCERTAINTY, "max_rounds": 9, "early_stopping_rounds": 3})
            )
            other_interval = interval.build(
                mean["release_id"], policies[3], s3, track=False
            )
            interval.select(other_interval["release_id"], s3)
            assert query(current)[0][0] == 0
            try:
                pipeline.select(second["release_id"], s3)
            except ValueError:
                pass
            else:
                raise AssertionError("Mismatched interval selected")
            interval.select(parent["release_id"], s3)
            assert query(current)[0][0] == 240
            query(
                "UPDATE anomaly_jobs SET status='pending',lease_until=NULL,next_attempt_at=now() WHERE status='complete'"
            )

            def expire(*args, **kwargs):
                result = publish(*args, **kwargs)
                query(
                    "UPDATE anomaly_jobs SET lease_until=now()-interval '1 second' WHERE status='running'"
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
                "UPDATE anomaly_jobs SET status='pending',lease_until=NULL,next_attempt_at=now() WHERE status='running'"
            )
            try:
                jobs.recompute(1, s3, client)
            except grpc.RpcError:
                pass
            else:
                raise AssertionError("RPC outage not deferred")
            assert (
                query(
                    "SELECT count(*) FROM anomaly_jobs WHERE status='pending' AND reason_code='anomaly_runtime_deferred'"
                )[0][0]
                >= 1
            )
            print(
                "Profile integration passed: immutable deterministic fit/registry, atomic rollback, corrupt-artifact refusal, explicit ancestor pins, RPC validation, revision and release-selection races, all ancestor invalidation/restoration, lease expiry and outage deferral."
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
