"""Disposable SQL and real object-store checks; fixtures never enter the retained pilot."""

import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = globals().get("DATA", {})


def launch():
    data = {
        "OFFLINE": (ROOT / "scripts/verify_phase9.py").read_text(),
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
            "event-worker",
            "-",
        ],
        input=code,
        text=True,
        cwd=ROOT,
        check=True,
    )


def verify():
    import os
    from urllib.parse import urlsplit, urlunsplit
    import numpy as np
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
    from nautiq_ml.argo.storage import digest, put_immutable, read_object, store
    from nautiq_ml.events.core import POLICY, EventError, days
    from nautiq_ml.events.storage import (
        publish_dataset,
        load_dataset,
        identifier,
        calculation,
    )
    from nautiq_ml.events.pipeline import (
        baseline,
        thermal,
        verify_run,
        replay,
        maintain,
        profiles,
        publish_run,
    )
    from nautiq_ml.fields.core import canonical

    name = "nautiq_events_test_" + uuid.uuid4().hex[:12]
    admin = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    dsn = urlunsplit(urlsplit(os.environ["DATABASE_URL"])._replace(path="/" + name))
    db = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
    s3, keys = store(), set()
    original = s3.put_object

    def track(bucket, key, *args, **kwargs):
        keys.add(key)
        return original(bucket, key, *args, **kwargs)

    s3.put_object = track
    fixtures = {"__name__": "event_fixtures"}
    exec(DATA["OFFLINE"], fixtures)

    def refuses(fn):
        try:
            fn()
        except Exception:
            return
        raise AssertionError("unsafe event publication accepted")

    def insert(table, record):
        db.execute(
            sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                sql.Identifier(table),
                sql.SQL(",").join(map(sql.Identifier, record)),
                sql.SQL(",").join(sql.Placeholder() for _ in record),
            ),
            list(record.values()),
        )

    def crash():
        raise EventError("injected_atomic_rollback")

    try:
        for migration in DATA["MIGRATIONS"]:
            db.execute(migration)
        raw = uuid.uuid4().bytes
        sha = digest(raw)
        key = "verification/" + name + "/source"
        put_immutable(s3, key, raw)
        receipts = [
            dict(
                url="https://example.invalid/" + name,
                raw_key=key,
                sha256=sha,
                bytes=len(raw),
            )
        ]
        dates = days("1982-01-01", "2011-12-31", 11323)
        lat, lon = np.array([11.125, 11.375]), np.array([71.125, 71.375])
        values = np.array(
            [20 + 0.05 * (int(d[:4]) - 1982) for d in dates], dtype="float32"
        )[:, None, None] * np.ones((1, 2, 2), dtype="float32")
        meta = dict(
            dates=dates,
            bbox=[71, 11, 72, 12],
            shape=list(values.shape),
            missing_cells=0,
            raw=receipts,
            source=POLICY["source"],
            fixture=name,
        )
        arrays = dict(lat=lat, lon=lon, sst=values)
        h = publish_dataset(db, s3, "history", arrays, meta)
        assert (
            publish_dataset(db, s3, "history", arrays, meta)["dataset_id"]
            == h["dataset_id"]
        )
        refuses(
            lambda: publish_dataset(
                db,
                s3,
                "history",
                arrays,
                {**meta, "fixture": name + "-rollback"},
                before_commit=crash,
            )
        )
        assert db.execute("SELECT count(*) n FROM event_datasets").fetchone()["n"] == 1
        base = baseline(db, s3, h["dataset_id"])
        load_dataset(db, s3, base["dataset_id"], raw=True)
        a, d, y, x, _ = fixtures["thermal_fixture"]()
        recent = publish_dataset(
            db,
            s3,
            "history",
            dict(lat=y, lon=x, sst=a),
            dict(
                dates=d,
                bbox=[71, 11, 72, 12],
                shape=list(a.shape),
                missing_cells=0,
                raw=receipts,
                source=POLICY["source"],
                fixture=name,
            ),
        )
        run = thermal(db, s3, base["dataset_id"], recent["dataset_id"])
        assert run["event_count"] == 1 and not run["release_approved"]
        assert (
            thermal(db, s3, base["dataset_id"], recent["dataset_id"])["run_id"]
            == run["run_id"]
        )
        row, report = verify_run(db, s3, run["run_id"])
        assert replay(db, s3, run["run_id"])["run_id"] == run["run_id"]
        assert db.execute("SELECT count(*) n FROM event_outbox").fetchone()["n"] == 1
        modified = {**report, "fixture": "rollback"}
        modified["events"] = [
            {k: v for k, v in e.items() if k != "event_id"} for e in report["events"]
        ]
        refuses(
            lambda: publish_run(
                db,
                s3,
                modified,
                row["manifest"]["inputs"],
                base["dataset_id"],
                recent["dataset_id"],
                before_commit=crash,
            )
        )
        assert db.execute("SELECT count(*) n FROM event_runs").fetchone()["n"] == 1
        # Missing report and restored report; missing raw input and restored input.
        data = read_object(s3, row["report_key"], row["report_sha256"])
        s3.remove_object("nautiq", row["report_key"])
        refuses(lambda: verify_run(db, s3, run["run_id"]))
        assert any(
            r.get("run_id") == run["run_id"] and r["status"] == "unavailable"
            for r in maintain(db, s3)
        )
        put_immutable(s3, row["report_key"], data)
        maintain(db, s3)
        assert (
            db.execute("SELECT status FROM event_runs").fetchone()["status"] == "ready"
        )
        s3.remove_object("nautiq", key)
        refuses(lambda: verify_run(db, s3, run["run_id"]))
        maintain(db, s3)
        assert (
            db.execute(
                "SELECT count(*) n FROM event_datasets WHERE status='unavailable'"
            ).fetchone()["n"]
            == 3
        )
        put_immutable(s3, key, raw)
        maintain(db, s3)
        verify_run(db, s3, run["run_id"])
        event = report["events"][0]
        db.execute(
            "UPDATE regional_events SET variable='wrong' WHERE event_id=%s",
            (event["event_id"],),
        )
        refuses(lambda: verify_run(db, s3, run["run_id"]))
        db.execute(
            "UPDATE regional_events SET variable=%s WHERE event_id=%s",
            (event["variable"], event["event_id"]),
        )
        db.execute(
            "UPDATE event_runs SET manifest=jsonb_set(manifest,'{policy_sha256}','\"invalid\"') WHERE run_id=%s",
            (run["run_id"],),
        )
        refuses(lambda: verify_run(db, s3, run["run_id"]))
        db.execute(
            "UPDATE event_runs SET manifest=%s WHERE run_id=%s",
            (Jsonb(row["manifest"]), run["run_id"]),
        )
        verify_run(db, s3, run["run_id"])
        # Minimal explicitly synthetic parent records exercise lineage without retraining models.
        parent_key = "verification/" + name + "/anomaly-bundle"
        parent_data = canonical({"fixture": name})
        put_immutable(s3, parent_key, parent_data)
        parent_sha = digest(parent_data)
        cid = calculation(
            db, s3, "training_snapshot", {"fixture": name}, {"fixture": name}
        )
        snap = str(uuid.uuid4())
        insert(
            "training_snapshots",
            dict(
                snapshot_id=snap,
                snapshot_sha256=parent_sha,
                calculation_id=cid,
                manifest=Jsonb({}),
                manifest_key=parent_key,
                manifest_sha256=parent_sha,
                parquet_key=parent_key,
                parquet_sha256=parent_sha,
                size_bytes=len(parent_data),
                profile_count=3,
                row_count=3,
            ),
        )
        ids = {
            n: str(uuid.uuid4())
            for n in ["climatology", "expected_state", "uncertainty", "anomaly"]
        }
        for n in ids:
            rec = dict(
                release_id=ids[n],
                release_sha256=digest(n.encode() + raw),
                snapshot_id=snap,
                calculation_id=cid,
                manifest=Jsonb({}),
                bundle_key=parent_key,
                bundle_sha256=parent_sha,
                status="ready",
            )
            if n == "climatology":
                rec.update(
                    grid_key=parent_key,
                    grid_sha256=parent_sha,
                    evaluation_key=parent_key,
                    evaluation_sha256=parent_sha,
                    evaluation=Jsonb({}),
                )
            else:
                rec.update(
                    reference_id=ids["climatology"],
                    report_key=parent_key,
                    report_sha256=parent_sha,
                    report=Jsonb({}),
                )
            if n in ("uncertainty", "anomaly"):
                rec["expected_id"] = ids["expected_state"]
            if n == "anomaly":
                rec["uncertainty_id"] = ids["uncertainty"]
            insert(n + "_releases", rec)
            insert(n + "_selection", dict(release_id=ids[n]))
        ingest = str(uuid.uuid4())
        insert(
            "ingestion_runs",
            dict(
                run_id=ingest,
                source_id="argo_gdac",
                run_kind="backfill",
                status="complete",
            ),
        )
        artifact = str(uuid.uuid4())
        insert(
            "raw_artifacts",
            dict(
                artifact_id=artifact,
                source_id="argo_gdac",
                source_path=name,
                source_url="https://example.invalid/" + name,
                source_updated_at="2026-09-01T00:00:00Z",
                sha256=sha,
                object_key=key,
                size_bytes=len(raw),
                kind="profile",
                run_id=ingest,
            ),
        )
        pids = []
        for i in range(3):
            pid = str(uuid.uuid4())
            pids.append(pid)
            revision = digest((name + str(i)).encode())
            insert(
                "profiles",
                dict(
                    profile_id=pid,
                    native_key=name + str(i),
                    platform_id=str(i),
                    cycle_number=1,
                    direction="A",
                    sampling_scheme="fixture",
                    profile_index=0,
                ),
            )
            db.execute(
                "INSERT INTO profile_revisions(revision_id,profile_id,revision_sha256,raw_artifact_id,observed_at,received_at,source_updated_at,latitude,longitude,position,data_mode,qc_version,normalizer_version,depth_conversion_version,parameter_modes,levels,parquet_key,parquet_sha256,science_ready,selected_at) VALUES(%s,%s,%s,%s,%s,now(),now(),11,71,ST_SetSRID(ST_MakePoint(71,11),4326),'D','fixture','fixture','fixture','{}','[{}]',%s,%s,true,now())",
                (
                    str(uuid.uuid4()),
                    pid,
                    revision,
                    artifact,
                    f"2026-09-{i + 1:02d}T12:00:00Z",
                    key,
                    sha,
                ),
            )
            result = {
                "variables": {
                    "temperature_c": {
                        "percentiles": {
                            "values": {POLICY["profile_lens"]: 96},
                            "profiles": 28,
                        },
                        "max_signed_standardized_residual": 2,
                        "score_evidence": {"scores": {POLICY["profile_lens"]: 4}},
                    }
                }
            }
            manifest = {
                "inputs": [{"profile_id": pid, "revision_sha256": revision}],
                "policy": {"release_id": ids["anomaly"], "bundle_sha256": parent_sha},
                "output": result,
            }
            mdata = canonical(manifest)
            msha = digest(mdata)
            mkey = "verification/" + name + "/comparison-" + str(i)
            put_immutable(s3, mkey, mdata)
            calc_id = identifier(msha)
            insert(
                "calculations",
                dict(
                    calculation_id=calc_id,
                    calculation_sha256=msha,
                    kind="anomaly_comparison",
                    method_version="fixture",
                    manifest=Jsonb(manifest),
                    manifest_key=mkey,
                    manifest_sha256=msha,
                    state="current",
                ),
            )
            insert(
                "anomaly_comparisons",
                dict(
                    profile_id=pid,
                    revision_sha256=revision,
                    release_id=ids["anomaly"],
                    calculation_id=calc_id,
                    result=Jsonb(result),
                ),
            )
        prof = profiles(
            db, s3, ids["anomaly"], "2026-09-01", "2026-09-15", [70, 10, 72, 12]
        )
        pr, pp = verify_run(db, s3, prof["run_id"])
        assert (
            pp["regional_groups"] == 1
            and pp["isolated_groups"] == 0
            and pp["events"][0]["geometry"]["type"] == "MultiPoint"
        )
        assert replay(db, s3, prof["run_id"])["run_id"] == prof["run_id"]
        isolated = profiles(
            db, s3, ids["anomaly"], "2026-09-01", "2026-09-01", [70, 10, 72, 12]
        )
        _, ip = verify_run(db, s3, isolated["run_id"])
        assert ip["regional_groups"] == 0 and ip["isolated_groups"] == 1
        # Parent/revision changes during final publication must roll back, not silently publish.
        clean = {**pp, "fixture": "race"}
        clean["events"] = [
            {k: v for k, v in e.items() if k != "event_id"} for e in pp["events"]
        ]

        def stale():
            db.execute(
                "UPDATE profile_revisions SET superseded_at=now() WHERE profile_id=%s",
                (pids[0],),
            )

        refuses(
            lambda: publish_run(
                db,
                s3,
                clean,
                pr["manifest"]["inputs"],
                anomaly_id=ids["anomaly"],
                strict=True,
                before_commit=stale,
            )
        )
        assert (
            db.execute(
                "SELECT superseded_at FROM profile_revisions WHERE profile_id=%s",
                (pids[0],),
            ).fetchone()["superseded_at"]
            is None
        )
        db.execute(
            "UPDATE profile_revisions SET superseded_at=now() WHERE profile_id=%s",
            (pids[0],),
        )
        verify_run(
            db, s3, prof["run_id"]
        )  # Historical integrity remains valid after inputs become stale.
        assert replay(db, s3, prof["run_id"])["run_id"] == prof["run_id"]
        s3.remove_object("nautiq", parent_key)
        refuses(lambda: verify_run(db, s3, prof["run_id"]))
        put_immutable(s3, parent_key, parent_data)
        print(
            "Disposable event reliability checks passed: dataset/run idempotency, atomic rollback, outbox deduplication, exact replay, report/raw/parent withholding and restoration, SQL projection/fingerprint refusal, distinct isolated/regional profile support, and publication races with historical snapshot retention."
        )
    finally:
        db.close()
        admin.execute(
            sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
        )
        admin.close()
        for key in keys:
            s3.remove_object("nautiq", key)


if __name__ == "__main__":
    verify() if DATA else launch()
