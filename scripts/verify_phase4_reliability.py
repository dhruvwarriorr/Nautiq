"""Disposable integration gate for immutable references and comparison races."""

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
        for i in range(25):
            n = i if i < 24 else 0
            fixture(path, "D", bad_salinity=i == 24)
            with netCDF4.Dataset(path, "a") as ds:
                platforms = np.array([str(platform + n % 4)] * 2, dtype="S8")
                ds["PLATFORM_NUMBER"][:] = np.frombuffer(
                    platforms.tobytes(), dtype="S1"
                ).reshape(2, 8)
                ds["CYCLE_NUMBER"][:] = [n + 1] * 2
                t = datetime(2005 + n // 12, n % 12 + 1, 15, tzinfo=timezone.utc)
                ds["JULD"][:] = [
                    (t - datetime(1950, 1, 1, tzinfo=timezone.utc)).total_seconds()
                    / 86400
                ] * 2
                ds["PRES_ADJUSTED"][:] = [[0, 100, 200]] * 2
                temp = 25 + math.sin(n % 12 * math.pi / 6) + (1 if i == 24 else 0)
                ds["TEMP_ADJUSTED"][:] = [[temp, temp - 2, temp - 4]] * 2
                if i == 24:
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
        "POLICY": json.loads(
            (ROOT / "packages/source-catalog/climatology.json").read_text()
        ),
    }
    code = "\n".join(f"{k}={v!r}" for k, v in values.items()) + "\n"
    code += "import sys\nsys.argv=['verify_phase4_reliability.py','--inside']\n"
    code += Path(__file__).read_text()
    subprocess.run(
        ["docker", "compose", "exec", "-T", "normalizer", "python", "-"],
        input=code,
        text=True,
        cwd=ROOT,
        check=True,
    )


def verify():
    import hashlib
    import io
    import os
    from datetime import datetime, timezone
    from urllib.parse import urlsplit, urlunsplit

    import psycopg
    from psycopg import sql
    from psycopg.types.json import Jsonb

    from nautiq_ml.argo import evidence, snapshots, worker
    from nautiq_ml.argo.storage import read_object, store
    from nautiq_ml.climatology import pipeline as climate

    name = "climate_verify_" + uuid.uuid4().hex[:12]
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

    paths = [
        Path(tempfile.gettempdir()) / (name + suffix)
        for suffix in ("-training.json", "-climate.json", "-changed.json")
    ]
    try:
        for migration in MIGRATIONS:
            query(migration)
        for i in range(24):
            assert worker.process(register(i)) == "normalized"
        paths[0].write_text(json.dumps(TRAINING))
        paths[1].write_text(json.dumps(POLICY))
        changed_policy = {**POLICY, "ridge_alpha": 2.0}
        paths[2].write_text(json.dumps(changed_policy))
        as_of = query("SELECT clock_timestamp()")[0][0].isoformat()
        snapshot = snapshots.build(paths[0], as_of, s3, 100)
        assert snapshot["output"]["profile_count"] == 48
        first = climate.build(snapshot["snapshot_id"], paths[1], s3)
        assert first["model_count"] > 0
        assert first == climate.build(snapshot["snapshot_id"], paths[1], s3)
        assert climate.verify(first["release_id"], s3)["verified"]
        assert climate.select(first["release_id"], s3)["profiles_queued"] == 48
        assert climate.recompute(100, s3) == 48
        assert (
            query(
                "SELECT count(*) FROM climatology_comparisons WHERE (result->>'supported_pairs')::integer>0"
            )[0][0]
            == 48
        )
        # Immutable staging followed by SQL failure must publish no fit calculation.
        query(
            "ALTER TABLE climatology_releases ADD CONSTRAINT forced_failure CHECK(status='invalid') NOT VALID"
        )
        before = query("SELECT count(*) FROM calculations")[0][0]
        try:
            climate.build(snapshot["snapshot_id"], paths[2], s3)
        except psycopg.errors.CheckViolation:
            pass
        else:
            raise AssertionError("Failed reference was published")
        assert query("SELECT count(*) FROM calculations")[0][0] == before
        query("ALTER TABLE climatology_releases DROP CONSTRAINT forced_failure")
        second = climate.build(snapshot["snapshot_id"], paths[2], s3)
        assert second["release_id"] != first["release_id"]
        paths[2].write_text(json.dumps({**POLICY, "max_profiles": 1}))
        try:
            climate.build(snapshot["snapshot_id"], paths[2], s3)
        except ValueError as error:
            assert str(error) == "climatology_input_budget"
        else:
            raise AssertionError("Input budget silently truncated")
        paths[2].write_text(json.dumps({**POLICY, "min_profiles": 2000}))
        unsupported = climate.build(snapshot["snapshot_id"], paths[2], s3)
        assert (
            unsupported["status"] == "unsupported" and unsupported["model_count"] == 0
        )
        try:
            climate.select(unsupported["release_id"], s3)
        except ValueError as error:
            assert str(error) == "climatology_reference_unsupported"
        else:
            raise AssertionError("Unsupported reference was selected")
        assert (
            str(query("SELECT release_id FROM climatology_selection")[0][0])
            == first["release_id"]
        )
        data = read_object(s3, first["bundle_key"], first["bundle_sha256"])
        s3.put_object("nautiq", first["bundle_key"], io.BytesIO(b"corrupt"), 7)
        try:
            climate.select(first["release_id"], s3)
        except ValueError:
            pass
        else:
            raise AssertionError("Corrupt reference selected")
        s3.put_object(
            "nautiq",
            first["bundle_key"],
            io.BytesIO(data),
            len(data),
            metadata={"sha256": first["bundle_sha256"]},
        )
        # A revision arriving after staging cannot publish the old comparison.
        event = register(24)
        query(
            "UPDATE climatology_jobs SET status='pending',lease_until=NULL,next_attempt_at=now()"
        )
        publish, triggered = evidence.publish, False

        def revision_race(*args, **kwargs):
            nonlocal triggered
            result = publish(*args, **kwargs)
            if not triggered:
                triggered = True
                assert worker.process(event) == "normalized"
            return result

        # Choose the changed native cycle first, so the race actually invalidates the leased job.
        target = query(
            "SELECT r.profile_id,r.revision_sha256 FROM profile_revisions r JOIN profiles p USING(profile_id) WHERE p.cycle_number=1 AND r.superseded_at IS NULL ORDER BY r.profile_id LIMIT 1"
        )[0]
        query(
            "UPDATE climatology_jobs SET created_at=now()-interval '1 day' WHERE profile_id=%s",
            (target[0],),
        )
        evidence.publish = revision_race
        try:
            climate.recompute(1, s3)
        finally:
            evidence.publish = publish
        assert triggered
        assert (
            query(
                "SELECT status FROM climatology_jobs WHERE profile_id=%s AND revision_sha256=%s",
                target,
            )[0][0]
            == "obsolete"
        )
        climate.recompute(100, s3)
        assert (
            query(
                "SELECT count(*) FROM calculations WHERE kind='climatology_comparison' AND state='stale'"
            )[0][0]
            == 2
        )
        # Independent bad salinity does not suppress valid temperature comparisons.
        result = query(
            "SELECT result FROM climatology_comparisons v JOIN profile_revisions r USING(profile_id,revision_sha256) JOIN profiles p USING(profile_id) WHERE p.cycle_number=1 AND r.superseded_at IS NULL AND v.profile_id=%s",
            (target[0],),
        )[0][0]
        assert any(r["temperature_c"]["difference"] is not None for r in result["rows"])
        changed_results = query(
            "SELECT result FROM climatology_comparisons v JOIN profile_revisions r USING(profile_id,revision_sha256) JOIN profiles p USING(profile_id) WHERE p.cycle_number=1 AND r.superseded_at IS NULL"
        )
        assert any(
            r["practical_salinity"]["observed_reason"] == "missing_bracket"
            for (comparison,) in changed_results
            for r in comparison["rows"]
        )
        # A reference switch during staging invalidates work from the old selection.
        query(
            "UPDATE climatology_jobs SET status='pending',lease_until=NULL,next_attempt_at=now() WHERE status='complete'"
        )
        triggered = False

        def selection_race(*args, **kwargs):
            nonlocal triggered
            result = publish(*args, **kwargs)
            if not triggered:
                triggered = True
                climate.select(second["release_id"], s3)
            return result

        evidence.publish = selection_race
        try:
            climate.recompute(1, s3)
        finally:
            evidence.publish = publish
        assert triggered
        climate.recompute(150, s3)
        assert (
            query(
                "SELECT count(*) FROM climatology_comparisons v JOIN profile_revisions r USING(profile_id,revision_sha256) WHERE v.release_id=%s AND r.superseded_at IS NULL",
                (second["release_id"],),
            )[0][0]
            == 48
        )
        # Expired leases are recovered; stolen leases cannot publish a calculation.
        jid = query(
            "SELECT job_id FROM climatology_jobs WHERE release_id=%s AND status='complete' LIMIT 1",
            (second["release_id"],),
        )[0][0]
        query(
            "UPDATE climatology_jobs SET status='running',lease_until=now()-interval '1 minute',lease_token=%s WHERE job_id=%s",
            (str(uuid.uuid4()), jid),
        )
        assert climate.recompute(1, s3) == 1
        query(
            "UPDATE climatology_jobs SET status='pending',lease_until=NULL WHERE job_id=%s",
            (jid,),
        )

        def lease_race(*args, **kwargs):
            result = publish(*args, **kwargs)
            query(
                "UPDATE climatology_jobs SET lease_token=%s,lease_until=now()-interval '1 minute' WHERE job_id=%s",
                (str(uuid.uuid4()), jid),
            )
            return result

        evidence.publish = lease_race
        try:
            assert climate.recompute(1, s3) == 0
        finally:
            evidence.publish = publish
        assert climate.recompute(1, s3) == 1
        # A SQL projection diverging from immutable canonical Parquet is rejected.
        # Temporary corruption stays retryable so restoring verified bytes recovers work.
        lake_key, lake_sha = query(
            "SELECT r.parquet_key,r.parquet_sha256 FROM climatology_jobs j JOIN profile_revisions r USING(profile_id,revision_sha256) WHERE j.job_id=%s",
            (jid,),
        )[0]
        lake_data = read_object(s3, lake_key, lake_sha)
        s3.put_object("nautiq", lake_key, io.BytesIO(b"corrupt"), 7)
        query(
            "UPDATE climatology_jobs SET status='pending',lease_until=NULL WHERE job_id=%s",
            (jid,),
        )
        try:
            climate.recompute(1, s3)
        except ValueError as error:
            assert str(error) == "artifact_checksum_or_budget"
        else:
            raise AssertionError("Corrupt observation was accepted")
        assert (
            query("SELECT status FROM climatology_jobs WHERE job_id=%s", (jid,))[0][0]
            == "pending"
        )
        s3.put_object(
            "nautiq",
            lake_key,
            io.BytesIO(lake_data),
            len(lake_data),
            metadata={"sha256": lake_sha},
        )
        query(
            "UPDATE climatology_jobs SET next_attempt_at=now() WHERE job_id=%s", (jid,)
        )
        assert climate.recompute(1, s3) == 1
        pid, rev, levels = query(
            "SELECT r.profile_id,r.revision_sha256,r.levels FROM climatology_jobs j JOIN profile_revisions r USING(profile_id,revision_sha256) WHERE j.job_id=%s",
            (jid,),
        )[0]
        query(
            "UPDATE profile_revisions SET levels=jsonb_set(levels,'{0,temperature_c}','39') WHERE profile_id=%s AND revision_sha256=%s",
            (pid, rev),
        )
        query(
            "UPDATE climatology_jobs SET status='pending',lease_until=NULL WHERE job_id=%s",
            (jid,),
        )
        try:
            climate.recompute(1, s3)
        except ValueError as error:
            assert str(error) == "canonical_lake_mismatch"
        else:
            raise AssertionError("Mutable observation accepted")
        assert (
            query("SELECT status FROM climatology_jobs WHERE job_id=%s", (jid,))[0][0]
            == "quarantined"
        )
        query(
            "UPDATE profile_revisions SET levels=%s WHERE profile_id=%s AND revision_sha256=%s",
            (Jsonb(levels), pid, rev),
        )
        assert read_object(s3, first["bundle_key"], first["bundle_sha256"]) == data
        assert (
            query(
                "SELECT state FROM calculations WHERE calculation_id=%s",
                (first["calculation_id"],),
            )[0][0]
            == "frozen"
        )
        assert climate.verify(first["release_id"], s3)["verified"]
        print(
            "Disposable climatology gate passed: repeatable fit, immutable checksums, rollback, independent QC, revision/reference races, lease recovery/ownership, canonical projection refusal, frozen reference retention"
        )
    finally:
        for path in paths:
            path.unlink(missing_ok=True)
        for key in keys:
            s3.remove_object("nautiq", key)
        os.environ["DATABASE_URL"] = original
        admin.execute(
            sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
        )
        admin.close()


if __name__ == "__main__":
    verify() if "--inside" in sys.argv else launch()
