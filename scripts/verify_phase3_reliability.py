"""Reproducibility gate using a disposable database and unique scientific fixtures."""

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
POLICY = globals().get("POLICY", {})


def launch():
    import netCDF4
    import numpy as np
    from verify_argo_parser import fixture

    samples = {}
    platform = str(90000000 + int(uuid.uuid4().hex[:6], 16) % 9999999)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "fixture.nc"
        for name, mode, unit in (
            ("R", "R", "decibar"),
            ("D", "D", "decibar"),
            ("D2", "D", "decibar"),
            ("BAD", "D", "metres"),
        ):
            fixture(path, mode, bad_salinity=True, unit=unit)
            with netCDF4.Dataset(path, "a") as ds:
                ds["PLATFORM_NUMBER"][:] = np.frombuffer(
                    np.array([platform, platform], dtype="S8").tobytes(), dtype="S1"
                ).reshape(2, 8)
                # Historical synthetic test observations fall inside the real frozen policy.
                ds["JULD"][:] = [22000, 22000]
                if name == "D2":
                    ds["TEMP_ADJUSTED"][:] = [[22, 21, 20]] * 2
                    ds["DATE_UPDATE"][:] = np.frombuffer(b"20261002000000", dtype="S1")
            samples[name] = base64.b64encode(path.read_bytes()).decode()
    values = {
        "SAMPLES": samples,
        "MIGRATIONS": [
            p.read_text() for p in sorted((ROOT / "migrations").glob("*.sql"))
        ],
        "POLICY": json.loads(
            (ROOT / "packages/source-catalog/argo-training.json").read_text()
        ),
    }
    code = "\n".join(f"{k}={v!r}" for k, v in values.items()) + "\n"
    code += "import sys\nsys.argv=['verify_phase3_reliability.py','--inside']\n"
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
    import pyarrow.parquet as pq
    from psycopg import sql

    from nautiuq_ml.argo import evidence
    from nautiuq_ml.argo.freshness import monitor
    from nautiuq_ml.argo.snapshots import build, selection_database
    from nautiuq_ml.argo.storage import read_object, store
    from nautiuq_ml.argo.worker import process

    name = "science_verify_" + uuid.uuid4().hex[:12]
    original = os.environ["DATABASE_URL"]
    admin = psycopg.connect(original, autocommit=True)
    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    parts = urlsplit(original)
    os.environ["DATABASE_URL"] = urlunsplit(
        (parts.scheme, parts.netloc, "/" + name, parts.query, parts.fragment)
    )
    s3 = store()
    keys = set()
    original_put = s3.put_object

    def track(bucket, key, *args, **kwargs):
        keys.add(key)
        return original_put(bucket, key, *args, **kwargs)

    s3.put_object = track
    # Worker and snapshots receive the same tracked client, including failed staging.
    import nautiuq_ml.argo.worker as worker

    worker.store = lambda: s3
    prefix = "verification/" + name + "/"

    def query(statement, args=()):
        with psycopg.connect(os.environ["DATABASE_URL"]) as db:
            cursor = db.execute(statement, args)
            return cursor.fetchall() if cursor.description else []

    def register(data, ordinal):
        sha = hashlib.sha256(data).hexdigest()
        artifact, event, run = (str(uuid.uuid4()) for _ in range(3))
        key = prefix + str(ordinal) + ".nc"
        s3.put_object("nautiuq", key, io.BytesIO(data), len(data))
        with psycopg.connect(os.environ["DATABASE_URL"]) as db:
            db.execute(
                "INSERT INTO ingestion_runs(run_id,source_id,run_kind,status) VALUES(%s,'argo_gdac','backfill','complete')",
                (run,),
            )
            db.execute(
                "INSERT INTO raw_artifacts(artifact_id,source_id,source_path,source_url,source_updated_at,sha256,object_key,size_bytes,kind,run_id) VALUES(%s,'argo_gdac',%s,%s,now(),%s,%s,%s,'profile',%s)",
                (
                    artifact,
                    f"aoml/9900001/profiles/D9900001_{ordinal:03}.nc",
                    f"https://data-argo.ifremer.fr/dac/aoml/9900001/profiles/D9900001_{ordinal:03}.nc",
                    sha,
                    key,
                    len(data),
                    run,
                ),
            )
        return json.dumps(
            {
                "event_id": event,
                "event_type": "raw.received",
                "schema_version": 1,
                "aggregate_key": artifact,
                "revision_sha256": sha,
                "payload": {"artifact_id": artifact},
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        ).encode()

    try:
        with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as db:
            for migration in MIGRATIONS:
                db.execute(migration)
        events = {}
        events["R"] = register(base64.b64decode(SAMPLES["R"]), 1)
        assert process(events["R"]) == "normalized"
        assert evidence.recompute(20, s3) == 2
        old_calcs = {
            str(row[0])
            for row in query(
                "SELECT calculation_id FROM calculations WHERE state='current'"
            )
        }
        events["D"] = register(base64.b64decode(SAMPLES["D"]), 2)
        assert process(events["D"]) == "normalized"
        assert all(
            row[0] == "stale"
            for row in query(
                "SELECT state FROM calculations WHERE calculation_id=ANY(%s::uuid[])",
                (list(old_calcs),),
            )
        )
        assert evidence.recompute(20, s3) == 2
        assert (
            query(
                "SELECT count(*) FROM profile_statistics s JOIN profile_revisions r USING(profile_id,revision_sha256) WHERE r.data_mode='D' AND r.superseded_at IS NULL"
            )[0][0]
            == 2
        )
        canonical = query(
            "SELECT profile_id,revision_sha256,parquet_sha256,calculation_id FROM profile_revisions WHERE selected_at IS NOT NULL AND superseded_at IS NULL ORDER BY profile_id"
        )
        assert process(events["D"]) == "duplicate"
        assert process(events["D"], replay=True) == "normalized"
        assert (
            query(
                "SELECT profile_id,revision_sha256,parquet_sha256,calculation_id FROM profile_revisions WHERE selected_at IS NOT NULL AND superseded_at IS NULL ORDER BY profile_id"
            )
            == canonical
        )
        duplicate = register(base64.b64decode(SAMPLES["D"]), 3)
        assert process(duplicate) == "normalized"
        assert query("SELECT count(*) FROM profiles")[0][0] == 2
        assert query("SELECT count(*) FROM profile_revisions")[0][0] == 4
        assert query("SELECT count(*) FROM profile_source_links")[0][0] == 6
        assert process(events["R"], replay=True) == "normalized"
        assert (
            query(
                "SELECT count(*) FROM profile_revisions WHERE data_mode='D' AND selected_at IS NOT NULL AND superseded_at IS NULL"
            )[0][0]
            == 2
        )
        policy_path = Path(tempfile.gettempdir()) / (name + ".json")
        policy_path.write_text(json.dumps(POLICY))
        as_of = query("SELECT clock_timestamp()")[0][0].isoformat()
        frozen = build(policy_path, as_of, s3, 100)
        assert (
            frozen["output"]["profile_count"] == 2
            and frozen["output"]["row_count"] == 6
        )
        assert frozen["output"]["split_rows"] == {
            "train": 6,
            "tune": 0,
            "calibration": 0,
            "test": 0,
        }
        assert frozen == build(policy_path, as_of, s3, 100)
        data = read_object(
            s3, frozen["parquet_key"], frozen["output"]["parquet_sha256"]
        )
        from nautiuq_ml.argo import tools
        from nautiuq_ml.argo.parser import InvalidProfile

        tools.store = lambda: s3
        assert tools.verify_snapshot(frozen["snapshot_id"])["verified"]
        s3.put_object(
            "nautiuq",
            frozen["parquet_key"],
            io.BytesIO(b"corrupt"),
            7,
            metadata={"sha256": frozen["output"]["parquet_sha256"]},
        )
        try:
            tools.verify_snapshot(frozen["snapshot_id"])
        except InvalidProfile:
            pass
        else:
            raise AssertionError("Corrupt snapshot verified")
        try:
            build(policy_path, as_of, s3, 100)
        except InvalidProfile:
            pass
        else:
            raise AssertionError("Corrupt immutable snapshot was overwritten")
        s3.put_object(
            "nautiuq",
            frozen["parquet_key"],
            io.BytesIO(data),
            len(data),
            metadata={"sha256": frozen["output"]["parquet_sha256"]},
        )
        rows = pq.read_table(io.BytesIO(data)).to_pylist()
        assert sum(r["practical_salinity"] is None for r in rows) == 1
        assert len({(r["profile_id"], r["source_level_index"]) for r in rows}) == 6
        try:
            build(policy_path, as_of, s3, 1)
        except ValueError as error:
            assert str(error) == "snapshot_selection_exceeds_budget"
        else:
            raise AssertionError("Snapshot silently truncated")
        # Failure after immutable staging publishes no SQL snapshot or calculation.
        with psycopg.connect(os.environ["DATABASE_URL"]) as db:
            db.execute(
                "ALTER TABLE training_snapshots ADD CONSTRAINT forced_failure CHECK (row_count<0) NOT VALID"
            )
        count = query("SELECT count(*) FROM calculations")[0][0]
        try:
            build(
                policy_path,
                query("SELECT clock_timestamp()")[0][0].isoformat(),
                s3,
                100,
            )
        except psycopg.errors.CheckViolation:
            pass
        else:
            raise AssertionError("Failed snapshot published")
        assert query("SELECT count(*) FROM calculations")[0][0] == count
        with psycopg.connect(os.environ["DATABASE_URL"]) as db:
            db.execute("ALTER TABLE training_snapshots DROP CONSTRAINT forced_failure")
        # Inject supersession while a summary is staging; its old revision cannot publish.
        events["D2"] = register(base64.b64decode(SAMPLES["D2"]), 4)
        query(
            "UPDATE recomputation_jobs SET status='pending',lease_until=NULL,next_attempt_at=now() WHERE revision_sha256 IN (SELECT revision_sha256 FROM profile_revisions WHERE data_mode='D' AND superseded_at IS NULL)"
        )
        publish = evidence.publish
        triggered = False

        def interleave(*args, **kwargs):
            nonlocal triggered
            result = publish(*args, **kwargs)
            if not triggered:
                triggered = True
                assert process(events["D2"]) == "normalized"
            return result

        evidence.publish = interleave
        try:
            evidence.recompute(20, s3)
        finally:
            evidence.publish = publish
        assert triggered
        assert (
            query("SELECT count(*) FROM recomputation_jobs WHERE status='obsolete'")[0][
                0
            ]
            >= 1
        )
        assert (
            query(
                "SELECT count(*) FROM profile_statistics s JOIN profile_revisions r USING(profile_id,revision_sha256) WHERE r.selected_at IS NOT NULL AND r.superseded_at IS NULL"
            )[0][0]
            == 2
        )
        assert (
            read_object(s3, frozen["parquet_key"], frozen["output"]["parquet_sha256"])
            == data
        )
        assert (
            query(
                "SELECT state FROM calculations WHERE calculation_id=%s",
                (frozen["calculation_id"],),
            )[0][0]
            == "frozen"
        )
        assert build(policy_path, as_of, s3, 100) == frozen
        changed = build(
            policy_path, query("SELECT clock_timestamp()")[0][0].isoformat(), s3, 100
        )
        assert changed["snapshot_id"] != frozen["snapshot_id"]
        assert changed["output"]["parquet_sha256"] != frozen["output"]["parquet_sha256"]
        # A repaired current revision must recover jobs obsoleted during withholding.
        with psycopg.connect(os.environ["DATABASE_URL"]) as db:
            target, revision = db.execute(
                "SELECT profile_id,revision_sha256 FROM profile_revisions WHERE selected_at IS NOT NULL AND superseded_at IS NULL LIMIT 1"
            ).fetchone()
            db.execute(
                "UPDATE profile_revisions SET science_ready=false WHERE profile_id=%s AND revision_sha256=%s",
                (target, revision),
            )
            db.execute(
                "UPDATE recomputation_jobs SET status='pending',lease_until=NULL,next_attempt_at=now() WHERE profile_id=%s AND revision_sha256=%s",
                (target, revision),
            )
        evidence.recompute(20, s3)
        assert (
            query(
                "SELECT status FROM recomputation_jobs WHERE profile_id=%s AND revision_sha256=%s",
                (target, revision),
            )[0][0]
            == "obsolete"
        )
        worker._lake_cursor = None
        with psycopg.connect(os.environ["DATABASE_URL"]) as db:
            worker.repair_lake(db, s3)
        assert evidence.recompute(20, s3) == 1
        # Candidate bounds and rows see one read snapshot even if readiness changes concurrently.
        with selection_database() as db:
            assert db.execute(
                "SELECT science_ready FROM profile_revisions WHERE profile_id=%s AND revision_sha256=%s",
                (target, revision),
            ).fetchone()["science_ready"]
            query(
                "UPDATE profile_revisions SET science_ready=false WHERE profile_id=%s AND revision_sha256=%s",
                (target, revision),
            )
            assert db.execute(
                "SELECT science_ready FROM profile_revisions WHERE profile_id=%s AND revision_sha256=%s",
                (target, revision),
            ).fetchone()["science_ready"]
            query(
                "UPDATE profile_revisions SET science_ready=true WHERE profile_id=%s AND revision_sha256=%s",
                (target, revision),
            )
        query(
            "UPDATE recomputation_jobs SET status='running',lease_token=%s,lease_until=now()-interval '1 minute',next_attempt_at=now() WHERE profile_id=%s AND revision_sha256=%s",
            (str(uuid.uuid4()), target, revision),
        )
        assert evidence.recompute(20, s3) == 1
        # Frozen labels cannot be built from a SQL projection diverging from pinned lake bytes.
        with psycopg.connect(os.environ["DATABASE_URL"]) as db:
            levels = db.execute(
                "SELECT levels FROM profile_revisions WHERE profile_id=%s AND revision_sha256=%s",
                (target, revision),
            ).fetchone()[0]
            db.execute(
                "UPDATE profile_revisions SET levels=jsonb_set(levels,'{0,temperature_c}','99') WHERE profile_id=%s AND revision_sha256=%s",
                (target, revision),
            )
        try:
            build(
                policy_path,
                query("SELECT clock_timestamp()")[0][0].isoformat(),
                s3,
                100,
            )
        except ValueError as error:
            assert str(error) == "canonical_lake_mismatch"
        else:
            raise AssertionError("Mutable projection was accepted as frozen truth")
        from psycopg.types.json import Jsonb

        with psycopg.connect(os.environ["DATABASE_URL"]) as db:
            db.execute(
                "UPDATE profile_revisions SET levels=%s WHERE profile_id=%s AND revision_sha256=%s",
                (Jsonb(levels), target, revision),
            )

        for ordinal, raw in (
            (5, base64.b64decode(SAMPLES["BAD"])),
            (6, b"malformed NetCDF"),
        ):
            event = register(raw, ordinal)
            assert process(event) == "quarantined"
            assert process(event, replay=True) == "quarantined"
        assert (
            query(
                "SELECT count(*) FROM qc_rejections WHERE artifact_id IS NOT NULL AND rule_id IS NOT NULL AND qc_version IS NOT NULL"
            )[0][0]
            >= 3
        )
        qc = query("SELECT count(*) FROM qc_rejections")[0][0]
        process(events["D"], replay=True)
        assert query("SELECT count(*) FROM qc_rejections")[0][0] == qc
        monitor()
        report = query("SELECT report FROM source_health WHERE source_id='argo_gdac'")[
            0
        ][0]
        assert (
            report["source_freshness"] == "unverified"
            and report["ingestion_state"] == "unknown"
        )
        live = str(uuid.uuid4())
        with psycopg.connect(os.environ["DATABASE_URL"]) as db:
            db.execute(
                "INSERT INTO ingestion_runs(run_id,source_id,run_kind,status,upstream_checked_at) VALUES(%s,'argo_gdac','live','complete',now()-interval '1 hour')",
                (live,),
            )
            db.execute(
                "INSERT INTO ingestion_runs(run_id,source_id,run_kind,status,started_at,upstream_checked_at) VALUES(%s,'argo_gdac','backfill','complete',now()+interval '1 minute',now())",
                (str(uuid.uuid4()),),
            )
        monitor()
        report = query("SELECT report FROM source_health WHERE source_id='argo_gdac'")[
            0
        ][0]
        assert (
            report["ingestion_state"] == "on_schedule"
            and report["last_fetch_age_hours"] > 0.99
        )
        with psycopg.connect(os.environ["DATABASE_URL"]) as db:
            db.execute(
                "INSERT INTO ingestion_runs(run_id,source_id,run_kind,status,started_at,reason_code) VALUES(%s,'argo_gdac','live','failed',now()+interval '1 minute','index_fetch_failed')",
                (str(uuid.uuid4()),),
            )
        monitor()
        report = query("SELECT report FROM source_health WHERE source_id='argo_gdac'")[
            0
        ][0]
        assert (
            report["ingestion_state"] == "degraded"
            and report["source_freshness"] == "unverified"
        )
        with psycopg.connect(os.environ["DATABASE_URL"]) as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM calculations c WHERE NOT EXISTS (SELECT 1 FROM calculation_inputs i WHERE i.calculation_id=c.calculation_id)"
                ).fetchone()[0]
                == 0
            )
        print(
            "Disposable science DB passed: R→D, duplicates, deterministic replay, QC audit, stale calculation invalidation, late recomputation guard, pinned repeatable Parquet, historical rebuild after revision, snapshot rollback/budgets, independent labels, frozen evidence, live/backfill freshness separation"
        )
        policy_path.unlink()
    finally:
        for key in keys:
            s3.remove_object("nautiuq", key)
        os.environ["DATABASE_URL"] = original
        admin.execute(
            sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
        )
        admin.close()


if __name__ == "__main__":
    if "--inside" in sys.argv:
        verify()
    else:
        launch()
