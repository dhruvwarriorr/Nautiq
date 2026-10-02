"""Disposable SQL and real lake tests. No fixture bulletin enters the pilot database."""

import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = globals().get("DATA", {})


def launch():
    data = {
        "OFFLINE": (ROOT / "scripts/verify_phase10.py").read_text(),
        "MIGRATIONS": [
            p.read_text() for p in sorted((ROOT / "migrations").glob("*.sql"))
        ],
    }
    subprocess.run(
        [
            "docker",
            "compose",
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "--entrypoint",
            "python",
            "advisory-worker",
            "-",
        ],
        input="DATA=" + repr(data) + "\n" + Path(__file__).read_text(),
        text=True,
        cwd=ROOT,
        check=True,
    )


def verify():
    import os
    from urllib.parse import urlsplit, urlunsplit
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
    from nautiq_ml.argo.storage import store, read_object, put_immutable
    from nautiq_ml.advisories.core import POLICY, AdvisoryError
    from nautiq_ml.advisories.pipeline import (
        collect,
        publish,
        verify,
        replay,
        maintain,
        fetch,
    )

    def refuses(fn):
        try:
            fn()
        except Exception:
            return
        raise AssertionError("invalid publication accepted")

    ns = {"__name__": "fixtures"}
    exec(DATA["OFFLINE"], ns)
    ns["refuses"] = refuses
    name = "nautiq_advisory_test_" + uuid.uuid4().hex[:12]
    admin = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    dsn = urlunsplit(urlsplit(os.environ["DATABASE_URL"])._replace(path="/" + name))
    db = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
    s3 = store()
    keys = set()
    original = s3.put_object

    def track(bucket, key, *args, **kwargs):
        keys.add(key)
        return original(bucket, key, *args, **kwargs)

    s3.put_object = track
    try:
        for migration in DATA["MIGRATIONS"]:
            db.execute(migration)
        source = POLICY["sources"][0]
        url = "https://sachet.ndma.gov.in/cap_public_website/FetchXMLFile?identifier=1"
        rss = f'<rss version="2.0"><channel><item><link>{url}</link></item></channel></rss>'.encode()
        xml = ns["fixture"](name)
        calls = []

        def request(u, etag, limit):
            calls.append((u, etag))
            return (
                (304, None, etag, None)
                if etag
                else (200, rss if u == source["url"] else xml, '"retained-etag"', None)
            )

        report = collect(db, s3, source, "2026-10-03T02:00:00Z", request)
        assert report["transport"] == "healthy" and len(report["messages"]) == 1
        result = publish(db, s3, report)
        assert publish(db, s3, report) == result
        rid = result["run_id"]
        assert len(verify(db, s3, rid)["messages"]) == 1
        assert replay(db, s3, rid)["freshness_renewed"] is False
        repeated = collect(db, s3, source, "2026-10-03T02:10:00Z", request)
        assert all(r["http_status"] == 304 for r in repeated["receipts"])
        assert all(etag == '"retained-etag"' for _, etag in calls[-2:])
        publish(db, s3, repeated)
        assert (
            db.execute("SELECT count(*) AS n FROM advisory_revisions").fetchone()["n"]
            == 1
        )
        assert (
            db.execute("SELECT count(*) AS n FROM advisory_geometry").fetchone()["n"]
            == 1
        )
        # The original raw object is verified even on a 304; a damaged cache does not hit the source.
        receipt = report["messages"][0]["receipt"]
        raw = read_object(s3, receipt["raw_key"], receipt["sha256"], receipt["bytes"])
        s3.remove_object("nautiq", receipt["raw_key"])
        before = len(calls)
        ns["refuses"](lambda: fetch(db, s3, url, 1048576, request))
        assert len(calls) == before
        assert maintain(db, s3)["unavailable"] == 2
        put_immutable(s3, receipt["raw_key"], raw)
        assert maintain(db, s3)["ready"] == 2
        # Report, membership and geometry mirrors are independently checked.
        db.execute(
            'UPDATE advisory_runs SET report=report || \'{"transport":"wrong"}\'::jsonb WHERE run_id=%s',
            (rid,),
        )
        ns["refuses"](lambda: verify(db, s3, rid))
        db.execute(
            "UPDATE advisory_runs SET report=%s WHERE run_id=%s", (Jsonb(report), rid)
        )
        db.execute("UPDATE advisory_geometry SET geometry=ST_Translate(geometry,1,0)")
        ns["refuses"](lambda: verify(db, s3, rid))
        db.execute("UPDATE advisory_geometry SET geometry=ST_Translate(geometry,-1,0)")
        verify(db, s3, rid)
        db.execute("DELETE FROM advisory_run_members WHERE run_id=%s", (rid,))
        ns["refuses"](lambda: verify(db, s3, rid))
        db.execute(
            "INSERT INTO advisory_run_members VALUES(%s,%s)",
            (rid, report["messages"][0]["revision_id"]),
        )

        def fail():
            raise AdvisoryError("atomic_failure")

        modified = {**report, "as_of": "2026-10-03T02:20:00Z"}
        ns["refuses"](lambda: publish(db, s3, modified, fail))
        assert (
            db.execute("SELECT count(*) AS n FROM advisory_runs").fetchone()["n"] == 2
        )
        assert (
            db.execute(
                "SELECT count(*) AS n FROM event_outbox WHERE event_type='advisory.feed.checked'"
            ).fetchone()["n"]
            == 2
        )
        # An empty successful index retains earlier messages; a failed poll retains them too.
        empty = {**report, "as_of": "2026-10-03T02:30:00Z", "messages": []}
        publish(db, s3, empty)
        failed = {
            **empty,
            "as_of": "2026-10-03T02:40:00Z",
            "transport": "failed",
            "reasons": ["source_http_503"],
        }
        publish(db, s3, failed)
        assert (
            db.execute("SELECT count(*) AS n FROM advisory_revisions").fetchone()["n"]
            == 1
        )
        assert (
            db.execute(
                "SELECT transport FROM advisory_sources WHERE source_id='ndma_cap_rss'"
            ).fetchone()["transport"]
            == "failed"
        )
        print(
            "Official advisory persistence passed: conditional 304, cache damage, immutable replay, mirror corruption, atomic rollback, outbox uniqueness and disappearance retention."
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
