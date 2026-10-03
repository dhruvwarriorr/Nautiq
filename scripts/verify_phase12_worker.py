"""Disposable SQL and actual MinIO worker lease, integrity and cleanup contracts."""

import uuid
import os
from pathlib import Path

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb
from nautiq_ml.product import exports as worker


def main():
    admin = worker.connection()
    name = "nautiq_exports_test_" + uuid.uuid4().hex[:12]
    admin.execute("CREATE DATABASE " + name)
    conn = psycopg.connect(
        make_conninfo(os.environ["DATABASE_URL"], dbname=name),
        autocommit=True,
        row_factory=psycopg.rows.dict_row,
    )
    s3 = worker.store()
    job_ids = []
    try:
        for path in sorted(Path("/migrations").glob("*.sql")):
            conn.execute(path.read_text())
        owner = uuid.uuid4()
        conn.execute(
            "INSERT INTO product_accounts(account_id,handle,password_salt,password_hash) VALUES(%s,%s,%s,%s)",
            (owner, name, b"a" * 16, b"b" * 32),
        )
        snapshot = {
            "schema_version": 1,
            "scope": "route",
            "method_version": "private-provenance-report-v1",
            "generated_at": "2026-10-03T00:00:00Z",
            "product_policy_sha256": worker.digest(worker.POLICY_BYTES),
            "limitations": ["Frozen user-owned route; not assessed."],
            "owned_object": {
                "id": str(uuid.uuid4()),
                "name": "=unsafe-formula",
                "version": 1,
                "data": {
                    "waypoints": [
                        {
                            "latitude": 12,
                            "longitude": 72,
                            "time": "2026-10-03T12:00:00Z",
                        },
                        {
                            "latitude": 12.01,
                            "longitude": 72.01,
                            "time": "2026-10-03T13:00:00Z",
                        },
                    ]
                },
            },
        }

        def job():
            identifier = uuid.uuid4()
            raw = worker.canonical(snapshot)
            conn.execute(
                "INSERT INTO product_jobs(job_id,owner_id,kind,format,state,input,input_bytes,input_sha256) VALUES(%s,%s,'exports','csv','queued',%s,%s,%s)",
                (identifier, owner, Jsonb(snapshot), raw, worker.digest(raw)),
            )
            job_ids.append(identifier)
            return identifier

        def state(identifier):
            return conn.execute(
                "SELECT * FROM product_jobs WHERE job_id=%s", (identifier,)
            ).fetchone()

        ready = job()
        assert worker.run_one(conn, s3)
        row = state(ready)
        assert row["state"] == "ready" and row["attempts"] == 1
        data = worker.read_object(
            s3, row["object_key"], row["artifact_sha256"], limit=worker.MAX_BYTES
        )
        assert b"'=unsafe-formula" in data and data.count(b"not_assessed") == 2
        recovery = job()
        conn.execute(
            "UPDATE product_jobs SET state='running',attempts=1,lease_id=%s,lease_expires_at=now()-interval '1 second' WHERE job_id=%s",
            (uuid.uuid4(), recovery),
        )
        assert (
            worker.run_one(conn, s3)
            and state(recovery)["state"] == "ready"
            and state(recovery)["attempts"] == 2
        )
        corrupted = job()
        conn.execute(
            "UPDATE product_jobs SET input_bytes=%s WHERE job_id=%s", (b"{}", corrupted)
        )
        worker.run_one(conn, s3)
        assert state(corrupted)["reason"] == "input_hash_integrity"
        projected = job()
        conn.execute("UPDATE product_jobs SET input='{}' WHERE job_id=%s", (projected,))
        worker.run_one(conn, s3)
        assert state(projected)["reason"] == "input_projection_integrity"
        cancelled = job()
        original = worker.put_immutable
        keys = []

        def cancel_during_upload(store, key, data):
            keys.append(key)
            conn.execute(
                "UPDATE product_jobs SET state='cancelled',lease_id=NULL WHERE job_id=%s",
                (cancelled,),
            )
            original(store, key, data)

        worker.put_immutable = cancel_during_upload
        worker.run_one(conn, s3)
        worker.put_immutable = original
        assert (
            state(cancelled)["state"] == "cancelled"
            and state(cancelled)["object_key"] is None
        )
        assert not list(
            s3.list_objects(
                "nautiq", prefix=f"product/private/{cancelled}/", recursive=True
            )
        )
        exhausted = job()
        conn.execute(
            "UPDATE product_jobs SET state='running',attempts=3,lease_id=%s,lease_expires_at=now()-interval '1 second' WHERE job_id=%s",
            (uuid.uuid4(), exhausted),
        )
        conn.execute(
            "UPDATE product_jobs SET expires_at=now()-interval '1 second' WHERE job_id=%s",
            (ready,),
        )
        worker.maintain(conn, s3)
        assert (
            state(ready)["state"] == "expired"
            and state(exhausted)["reason"] == "lease_retry_budget"
        )
        assert not list(
            s3.list_objects(
                "nautiq", prefix=f"product/private/{ready}/", recursive=True
            )
        )
        conn.execute(
            "UPDATE product_jobs SET expires_at=now()-interval '25 hours' WHERE job_id=%s",
            (ready,),
        )
        worker.maintain(conn, s3)
        assert state(ready) is None
        print(
            "Private worker contracts passed: actual immutable MinIO bytes, durable jobs, abandoned lease recovery, input hash/mirror refusal, cancellation fence and orphan cleanup, retry budget, expiry cleanup."
        )
    finally:
        for identifier in job_ids:
            for obj in s3.list_objects(
                "nautiq", prefix=f"product/private/{identifier}/", recursive=True
            ):
                s3.remove_object("nautiq", obj.object_name)
        conn.close()
        admin.execute("DROP DATABASE " + name + " WITH (FORCE)")
        admin.close()


if __name__ == "__main__":
    main()
