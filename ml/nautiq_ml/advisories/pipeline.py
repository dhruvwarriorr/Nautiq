"""Bounded conditional acquisition, retained revisions, frozen replay and health projection."""

import argparse
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPRedirectHandler

from psycopg.types.json import Jsonb

from ..argo.storage import digest, put_immutable, read_object, store
from ..fields.core import canonical
from ..fields.pipeline import connection
from .core import POLICY, METHOD, AdvisoryError, feed, parse


def identifier(value):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "nautiq:advisories:" + value))


def code_hash():
    root = Path(__file__).parent
    files = [
        *root.glob("*.py"),
        root.parent / "argo/storage.py",
        root.parent / "fields/core.py",
    ]
    return digest(
        b"".join(
            str(p.relative_to(root.parent)).encode() + p.read_bytes()
            for p in sorted(files)
        )
    )


def runtime():
    import sys
    import importlib.metadata

    lock = next(
        p
        for p in (
            Path("/app/requirements-fields.lock"),
            Path(__file__).parents[2] / "requirements-fields.lock",
        )
        if p.exists()
    )
    return {
        "python": sys.version.split()[0],
        "libraries": {
            n: importlib.metadata.version(n) for n in ("shapely", "psycopg", "minio")
        },
        "requirements_sha256": digest(lock.read_bytes()),
    }


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AdvisoryError("source_redirect_refused")


def download(url, etag, limit):
    headers = {
        "User-Agent": "Nautiq/0.1 official CAP evidence",
        "Accept": "application/xml",
        "Accept-Encoding": "identity",
    }
    if etag:
        headers["If-None-Match"] = etag
    for attempt in range(2):
        try:
            with build_opener(NoRedirect).open(
                Request(url, headers=headers), timeout=12
            ) as response:
                data = response.read(limit + 1)
                if not data or len(data) > limit or response.status != 200:
                    raise AdvisoryError("source_byte_budget_or_status")
                return (
                    200,
                    data,
                    response.headers.get("ETag"),
                    response.headers.get("Last-Modified"),
                )
        except HTTPError as e:
            if e.code == 304:
                return 304, None, etag, None
            if e.code < 500 or attempt:
                raise AdvisoryError("source_http_" + str(e.code)) from e
        except (TimeoutError, OSError) as e:
            if attempt:
                raise AdvisoryError("source_connection_failed") from e
        time.sleep(0.5)
    raise AdvisoryError("source_request_failed")


def fetch(db, s3, url, limit, request=download):
    prior = db.execute(
        "SELECT receipt FROM advisory_requests WHERE url=%s", (url,)
    ).fetchone()
    cached = prior["receipt"] if prior else None
    # Never send an ETag for a cache whose bytes cannot be reconstructed.
    if cached:
        data = read_object(s3, cached["raw_key"], cached["sha256"], cached["bytes"])
    status, current, etag, modified = request(
        url, cached.get("etag") if cached else None, limit
    )
    if status == 304:
        if not cached:
            raise AdvisoryError("304_without_verified_cache")
        receipt = {**cached, "http_status": 304}
    else:
        if status != 200 or current is None or not 0 < len(current) <= limit:
            raise AdvisoryError("source_byte_budget_or_status")
        data = current
        sha = digest(data)
        key = "advisories/raw/" + sha + ".xml"
        put_immutable(s3, key, data)
        receipt = {
            "url": url,
            "raw_key": key,
            "sha256": sha,
            "bytes": len(data),
            "etag": etag,
            "last_modified": modified,
            "http_status": 200,
        }
    # Source caching is independent of a successful parse/publication; malformed bytes stay auditable.
    db.execute(
        "INSERT INTO advisory_requests VALUES(%s,%s) ON CONFLICT(url) DO UPDATE SET receipt=excluded.receipt",
        (url, Jsonb(receipt)),
    )
    return data, receipt


def initialize(db):
    for source in POLICY["sources"]:
        db.execute(
            "INSERT INTO advisory_sources(source_id,policy) VALUES(%s,%s) ON CONFLICT(source_id) DO UPDATE SET policy=excluded.policy",
            (source["id"], Jsonb(source)),
        )


def collect(db, s3, source, checked_at, request=download):
    report = {
        "source_id": source["id"],
        "as_of": checked_at,
        "policy": POLICY,
        "code_sha256": code_hash(),
        "method_version": METHOD,
        "runtime": runtime(),
        "transport": "healthy",
        "reasons": [],
        "receipts": [],
        "messages": [],
    }
    total = 0
    try:
        data, receipt = fetch(
            db, s3, source["url"], POLICY["limits"]["feed_bytes"], request
        )
        report["receipts"].append(receipt)
        total += len(data)
        urls = feed(data)
    except Exception as e:
        report["transport"] = "failed"
        report["reasons"].append(
            str(e) if isinstance(e, AdvisoryError) else "source_or_cache_unavailable"
        )
        return report
    deadline = time.monotonic() + 300
    for url in urls:
        try:
            if time.monotonic() >= deadline:
                raise AdvisoryError("run_deadline")
            data, receipt = fetch(db, s3, url, POLICY["limits"]["xml_bytes"], request)
            report["receipts"].append(receipt)
            total += len(data)
            if total > POLICY["limits"]["run_bytes"]:
                raise AdvisoryError("run_byte_budget")
            message = parse(data, checked_at)
            message["revision_id"] = identifier(source["id"] + digest(data))
            message["source_id"] = source["id"]
            message["receipt"] = receipt
            report["messages"].append(message)
        except Exception as e:
            report["transport"] = "partial"
            report["reasons"].append(
                {
                    "url": url,
                    "reason": str(e)
                    if isinstance(e, AdvisoryError)
                    else "source_or_cache_unavailable",
                }
            )
        if time.monotonic() >= deadline or total > POLICY["limits"]["run_bytes"]:
            report["reasons"].append("remaining_items_not_fetched_budget")
            report["transport"] = "partial"
            break
        time.sleep(0.2)
    report["listed_items"] = len(urls)
    report["parsed_items"] = len(report["messages"])
    return report


def publish(db, s3, report, before_commit=None):
    data = canonical(report)
    if len(data) > POLICY["limits"]["run_bytes"]:
        raise AdvisoryError("report_budget")
    sha = digest(data)
    rid = identifier(sha)
    key = "advisories/runs/" + sha + ".json"
    put_immutable(s3, key, data)
    manifest = {
        "schema_version": 1,
        "kind": "advisory_ingestion",
        "method_version": METHOD,
        "as_of": report["as_of"],
        "input": {"receipts": report["receipts"]},
        "output": {"run_id": rid, "report_key": key, "report_sha256": sha},
        "code_sha256": report["code_sha256"],
        "runtime": report.get("runtime"),
        "policy": report["policy"],
    }
    cdata = canonical(manifest)
    csha = digest(cdata)
    cid = identifier(csha)
    ckey = "advisories/calculations/" + csha + ".json"
    put_immutable(s3, ckey, cdata)
    with db.transaction():
        db.execute("SELECT pg_advisory_xact_lock(78192403)")
        initialize(db)
        count = db.execute(
            "SELECT count(*) AS n FROM advisory_revisions WHERE source_id=%s",
            (report["source_id"],),
        ).fetchone()["n"]
        existing = {
            str(r["revision_id"])
            for r in db.execute(
                "SELECT revision_id FROM advisory_revisions WHERE source_id=%s",
                (report["source_id"],),
            ).fetchall()
        }
        if (
            count + len({m["revision_id"] for m in report["messages"]} - existing)
            > POLICY["limits"]["messages"]
        ):
            raise AdvisoryError("revision_budget_requires_archival_policy")
        db.execute(
            "INSERT INTO calculations(calculation_id,calculation_sha256,kind,method_version,manifest,manifest_key,manifest_sha256,state) VALUES(%s,%s,'advisory_ingestion',%s,%s,%s,%s,'frozen') ON CONFLICT DO NOTHING",
            (cid, csha, METHOD, Jsonb(manifest), ckey, csha),
        )
        db.execute(
            "INSERT INTO advisory_runs(run_id,source_id,checked_at,report,report_key,report_sha256,calculation_id) VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(run_id) DO NOTHING",
            (rid, report["source_id"], report["as_of"], Jsonb(report), key, sha, cid),
        )
        prior = db.execute(
            "SELECT report_sha256 FROM advisory_runs WHERE run_id=%s", (rid,)
        ).fetchone()
        if not prior or prior["report_sha256"] != sha:
            raise AdvisoryError("immutable_run_conflict")
        for m in report["messages"]:
            r = m["receipt"]
            # http status is a fetch receipt, not part of the immutable parsed revision.
            document = {k: v for k, v in m.items() if k != "receipt"}
            inserted = db.execute(
                "INSERT INTO advisory_revisions(revision_id,source_id,sender,identifier,sent,raw_sha256,raw_key,raw_bytes,document,first_run_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING revision_id",
                (
                    m["revision_id"],
                    m["source_id"],
                    m["sender"],
                    m["identifier"],
                    m["sent"],
                    r["sha256"],
                    r["raw_key"],
                    r["bytes"],
                    Jsonb(document),
                    rid,
                ),
            ).fetchone()
            mirror = db.execute(
                "SELECT document FROM advisory_revisions WHERE revision_id=%s",
                (m["revision_id"],),
            ).fetchone()
            if canonical(mirror["document"]) != canonical(document):
                # A changed parser creates a new run but must not reinterpret an archived revision.
                raise AdvisoryError("revision_projection_conflict")
            db.execute(
                "INSERT INTO advisory_run_members VALUES(%s,%s) ON CONFLICT DO NOTHING",
                (rid, m["revision_id"]),
            )
            if inserted:
                for ii, info in enumerate(m["infos"]):
                    for ai, area in enumerate(info["areas"]):
                        for polygon in area["polygons"]:
                            db.execute(
                                "INSERT INTO advisory_geometry(revision_id,info_index,area_index,effective,expires,geometry) VALUES(%s,%s,%s,%s,%s,ST_SetSRID(ST_GeomFromGeoJSON(%s),4326))",
                                (
                                    m["revision_id"],
                                    ii,
                                    ai,
                                    info["effective"],
                                    info["expires"],
                                    json.dumps(polygon),
                                ),
                            )
                        for circle in area["circles"]:
                            lon, lat = circle["center"]
                            db.execute(
                                "INSERT INTO advisory_geometry(revision_id,info_index,area_index,effective,expires,center,radius_m) VALUES(%s,%s,%s,%s,%s,ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography,%s)",
                                (
                                    m["revision_id"],
                                    ii,
                                    ai,
                                    info["effective"],
                                    info["expires"],
                                    lon,
                                    lat,
                                    circle["radius_km"] * 1000,
                                ),
                            )
        db.execute(
            "UPDATE advisory_sources SET latest_run_id=%s,checked_at=%s,transport=%s,reasons=%s,updated_at=now() WHERE source_id=%s AND (checked_at IS NULL OR checked_at<=%s::timestamptz)",
            (
                rid,
                report["as_of"],
                report["transport"],
                Jsonb(report["reasons"]),
                report["source_id"],
                report["as_of"],
            ),
        )
        payload = {
            "event_id": rid,
            "schema_version": 1,
            "run_id": rid,
            "source_id": report["source_id"],
            "report_sha256": sha,
            "calculation_id": cid,
        }
        db.execute(
            "INSERT INTO event_outbox(event_id,event_type,schema_version,aggregate_key,revision_sha256,payload) VALUES(%s,'advisory.feed.checked',1,%s,%s,%s) ON CONFLICT DO NOTHING",
            (rid, report["source_id"] + ":" + report["as_of"], sha, Jsonb(payload)),
        )
        if before_commit:
            before_commit()
    return {
        "run_id": rid,
        "calculation_id": cid,
        "transport": report["transport"],
        "messages": len(report["messages"]),
        "report_sha256": sha,
    }


def verify(db, s3, rid):
    row = db.execute("SELECT * FROM advisory_runs WHERE run_id=%s", (rid,)).fetchone()
    if not row:
        raise AdvisoryError("run_not_found")
    data = read_object(
        s3, row["report_key"], row["report_sha256"], POLICY["limits"]["run_bytes"]
    )
    report = json.loads(data)
    if canonical(report) != canonical(row["report"]) or identifier(digest(data)) != str(
        row["run_id"]
    ):
        raise AdvisoryError("report_projection_mismatch")
    for r in report["receipts"]:
        read_object(s3, r["raw_key"], r["sha256"], r["bytes"])
    c = db.execute(
        "SELECT * FROM calculations WHERE calculation_id=%s", (row["calculation_id"],)
    ).fetchone()
    cdata = read_object(
        s3, c["manifest_key"], c["manifest_sha256"], POLICY["limits"]["run_bytes"]
    )
    if (
        digest(cdata) != c["calculation_sha256"]
        or canonical(json.loads(cdata)) != canonical(c["manifest"])
        or c["manifest"]["output"]["report_sha256"] != row["report_sha256"]
    ):
        raise AdvisoryError("calculation_projection_mismatch")
    members = {
        str(r["revision_id"])
        for r in db.execute(
            "SELECT revision_id FROM advisory_run_members WHERE run_id=%s", (rid,)
        ).fetchall()
    }
    if members != {m["revision_id"] for m in report["messages"]}:
        raise AdvisoryError("run_members_mismatch")
    for m in report["messages"]:
        projection = db.execute(
            "SELECT * FROM advisory_revisions WHERE revision_id=%s", (m["revision_id"],)
        ).fetchone()
        document = {k: v for k, v in m.items() if k != "receipt"}
        if (
            not projection
            or canonical(projection["document"]) != canonical(document)
            or projection["raw_sha256"] != m["receipt"]["sha256"]
        ):
            raise AdvisoryError("revision_projection_mismatch")
        # Validate geometry SQL mirrors using binary WKB; rounded GeoJSON can lose exact precision.
        from shapely import from_wkb

        projected = db.execute(
            "SELECT info_index,area_index,ST_AsBinary(geometry) AS geom,ST_X(center::geometry) AS lon,ST_Y(center::geometry) AS lat,radius_m,effective,expires FROM advisory_geometry WHERE revision_id=%s",
            (m["revision_id"],),
        ).fetchall()
        expected = []
        for ii, info in enumerate(m["infos"]):
            for ai, a in enumerate(info["areas"]):
                for g in a["polygons"]:
                    expected.append(
                        (ii, ai, canonical(g), None, info["effective"], info["expires"])
                    )
                for circle in a["circles"]:
                    expected.append(
                        (
                            ii,
                            ai,
                            None,
                            canonical(circle),
                            info["effective"],
                            info["expires"],
                        )
                    )
        from shapely.geometry import mapping

        actual = [
            (
                p["info_index"],
                p["area_index"],
                canonical(mapping(from_wkb(bytes(p["geom"])))) if p["geom"] else None,
                canonical(
                    {"center": [p["lon"], p["lat"]], "radius_km": p["radius_m"] / 1000}
                )
                if p["lon"] is not None
                else None,
                p["effective"].isoformat().replace("+00:00", "Z"),
                p["expires"].isoformat().replace("+00:00", "Z")
                if p["expires"]
                else None,
            )
            for p in projected
        ]
        if sorted(map(str, actual)) != sorted(map(str, expected)):
            raise AdvisoryError("geometry_projection_mismatch")
    return report


def replay(db, s3, rid):
    report = verify(db, s3, rid)
    if (
        report["code_sha256"] != code_hash()
        or report["policy"] != POLICY
        or report.get("runtime") != runtime()
    ):
        raise AdvisoryError("replay_requires_pinned_code_policy")
    for m in report["messages"]:
        document = parse(
            read_object(
                s3,
                m["receipt"]["raw_key"],
                m["receipt"]["sha256"],
                m["receipt"]["bytes"],
            ),
            report["as_of"],
        )
        if canonical(document) != canonical(
            {
                k: v
                for k, v in m.items()
                if k not in ("revision_id", "source_id", "receipt")
            }
        ):
            raise AdvisoryError("replay_mismatch")
    return {
        "run_id": str(rid),
        "replayed_messages": len(report["messages"]),
        "freshness_renewed": False,
    }


def maintain(db, s3):
    result = {"ready": 0, "unavailable": 0}
    rows = db.execute(
        "SELECT DISTINCT run_id AS latest_run_id FROM advisory_runs WHERE run_id IN (SELECT latest_run_id FROM advisory_sources UNION SELECT first_run_id FROM advisory_revisions) LIMIT 65"
    ).fetchall()
    if len(rows) > 64:
        raise AdvisoryError("maintenance_ancestry_budget")
    for r in rows:
        state = "ready"
        try:
            verify(db, s3, r["latest_run_id"])
        except Exception:
            state = "unavailable"
        db.execute(
            "UPDATE advisory_runs SET integrity=%s WHERE run_id=%s",
            (state, r["latest_run_id"]),
        )
        result[state] += 1
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("refresh", "verify", "replay", "maintain"))
    p.add_argument("run_id", nargs="?")
    p.add_argument("--watch", action="store_true")
    args = p.parse_args()
    if args.watch and args.command != "refresh":
        p.error("--watch requires refresh")
    with connection() as db:
        s3 = store()
        initialize(db)
        if args.command in ("verify", "replay"):
            if not args.run_id:
                p.error("run_id required")
            output = (
                replay(db, s3, args.run_id)
                if args.command == "replay"
                else {
                    "run_id": args.run_id,
                    "verified_messages": len(verify(db, s3, args.run_id)["messages"]),
                }
            )
            print(json.dumps(output, sort_keys=True))
        elif args.command == "maintain":
            print(json.dumps(maintain(db, s3)))
        else:
            while True:
                # One cooperative writer per source; avoid overlapping poll cycles and cache races.
                locked = db.execute(
                    "SELECT pg_try_advisory_lock(78192404) AS locked"
                ).fetchone()["locked"]
                if locked:
                    try:
                        for source in POLICY["sources"]:
                            if source["enabled"]:
                                checked = (
                                    datetime.now(timezone.utc)
                                    .isoformat()
                                    .replace("+00:00", "Z")
                                )
                                print(
                                    json.dumps(
                                        publish(
                                            db, s3, collect(db, s3, source, checked)
                                        )
                                    ),
                                    flush=True,
                                )
                        print(json.dumps(maintain(db, s3)), flush=True)
                    finally:
                        db.execute("SELECT pg_advisory_unlock(78192404)")
                if not args.watch:
                    break
                time.sleep(POLICY["poll_seconds"])


if __name__ == "__main__":
    main()
