"""Bounded offline import, deterministic replay, snapshot build and verification commands."""

import argparse
import io
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
import pyarrow.parquet as pq
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import evidence
from .freshness import monitor
from .snapshots import build
from .storage import digest, put_immutable, read_object, store

PATH = re.compile(r"[a-z]+/[0-9]{5,8}/profiles/[RD][0-9]{5,8}_[0-9]+D?\.nc")


def replay(limit=1000, after=None):
    from .worker import process

    if not 1 <= limit <= 5000:
        raise ValueError("replay_budget")
    with psycopg.connect(
        os.environ["DATABASE_URL"], row_factory=dict_row, connect_timeout=5
    ) as db:
        rows = db.execute(
            "SELECT artifact_id,sha256 FROM raw_artifacts WHERE kind='profile' AND (%s::uuid IS NULL OR artifact_id>%s::uuid) ORDER BY artifact_id LIMIT %s",
            (after, after, limit + 1),
        ).fetchall()
    results = {}
    for row in rows[:limit]:
        aid = str(row["artifact_id"])
        event = {
            "schema_version": 1,
            "event_type": "raw.received",
            "event_id": str(uuid.uuid5(uuid.NAMESPACE_URL, "raw.received|" + aid)),
            "aggregate_key": aid,
            "revision_sha256": row["sha256"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "payload": {"artifact_id": aid},
        }
        result = process(evidence.canonical(event), replay=True)
        results[result] = results.get(result, 0) + 1
    return {
        "processed": sum(results.values()),
        "results": results,
        "next_after": str(rows[limit - 1]["artifact_id"])
        if len(rows) > limit
        else None,
    }


def import_cache(directory, limit=20):
    if not 1 <= limit <= 1000:
        raise ValueError("import_budget")
    root = Path(directory).resolve()
    s3 = store()
    registered = 0
    for path in sorted((root / "receipts").glob("*.json")):
        receipt = json.loads(path.read_bytes())
        uri = urlsplit(receipt["url"])
        source_path = uri.path.removeprefix("/dac/")
        if (
            uri.scheme != "https"
            or uri.hostname != "data-argo.ifremer.fr"
            or uri.query
            or uri.username
            or not PATH.fullmatch(source_path)
        ):
            continue
        sha = receipt["sha256"]
        if not re.fullmatch(r"[a-f0-9]{64}", sha):
            raise ValueError("invalid_cache_digest")
        aid = str(
            uuid.uuid5(uuid.NAMESPACE_URL, "argo_gdac|" + source_path + "|" + sha)
        )
        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=5) as db:
            if db.execute(
                "SELECT 1 FROM raw_artifacts WHERE artifact_id=%s", (aid,)
            ).fetchone():
                continue
        file = root / "raw" / sha
        if (
            file.is_symlink()
            or not file.is_file()
            or not 0 < file.stat().st_size <= 67108864
        ):
            raise ValueError("cache_artifact_budget")
        data = file.read_bytes()
        if digest(data) != sha or len(data) != receipt["bytes"]:
            raise ValueError("cache_artifact_integrity")
        updated = (
            parsedate_to_datetime(receipt["last_modified"]).astimezone(timezone.utc)
            if receipt.get("last_modified")
            else datetime.fromisoformat(receipt["received_at"])
        )
        run = str(uuid.uuid4())
        key = f"raw/argo_gdac/profile/{sha[:2]}/{sha}/{Path(source_path).name}"
        # Native recovery metadata matches scheduled ingestion; no provider call occurs.
        try:
            info = s3.stat_object("nautiq", key)
        except Exception as error:
            from minio.error import S3Error

            if not isinstance(error, S3Error) or error.code != "NoSuchKey":
                raise
            s3.put_object(
                "nautiq",
                key,
                io.BytesIO(data),
                len(data),
                metadata={
                    "sha256": sha,
                    "source_path": source_path,
                    "source_updated_at": updated.isoformat(),
                },
            )
        else:
            if info.size != len(data):
                raise ValueError("immutable_cache_conflict")
        read_object(s3, key, sha)
        permanent = {
            "artifact_id": aid,
            "source_id": "argo_gdac",
            "source_path": source_path,
            "source_url": receipt["url"],
            "sha256": sha,
            "object_key": key,
            "source_updated_at": updated.isoformat(),
            "bytes": len(data),
            "kind": "profile",
            "received_at": receipt["received_at"],
            "import_policy": "verified-offline-receipt-v1",
        }
        put_immutable(s3, f"receipts/{aid}.json", evidence.canonical(permanent))
        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=5) as db:
            db.execute(
                "INSERT INTO ingestion_runs(run_id,source_id,status,run_kind,completed_at) VALUES(%s,'argo_gdac','complete','reconciled',now())",
                (run,),
            )
            db.execute(
                """INSERT INTO raw_artifacts(artifact_id,source_id,source_path,source_url,source_updated_at,sha256,object_key,size_bytes,kind,run_id,http_metadata)
VALUES(%s,'argo_gdac',%s,%s,%s,%s,%s,%s,'profile',%s,%s) ON CONFLICT DO NOTHING""",
                (
                    aid,
                    source_path,
                    receipt["url"],
                    updated,
                    sha,
                    key,
                    len(data),
                    run,
                    Jsonb({"cached": True, "etag": receipt.get("etag")}),
                ),
            )
            db.execute(
                """INSERT INTO event_outbox(event_id,event_type,schema_version,aggregate_key,revision_sha256,payload)
VALUES(%s,'raw.received',1,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (
                    str(uuid.uuid5(uuid.NAMESPACE_URL, "raw.received|" + aid)),
                    aid,
                    sha,
                    Jsonb({"artifact_id": aid}),
                ),
            )
        registered += 1
        if registered >= limit:
            break
    return {"registered": registered, "provider_requests": 0}


def verify_snapshot(snapshot_id):
    with psycopg.connect(
        os.environ["DATABASE_URL"], row_factory=dict_row, connect_timeout=5
    ) as db:
        row = db.execute(
            "SELECT * FROM training_snapshots WHERE snapshot_id=%s", (snapshot_id,)
        ).fetchone()
    if not row:
        raise ValueError("snapshot_not_found")
    s3 = store()
    manifest = json.loads(
        read_object(
            s3, row["manifest_key"], row["manifest_sha256"], limit=16 * 1024 * 1024
        )
    )
    if manifest != row["manifest"]:
        raise ValueError("snapshot_manifest_mismatch")
    data = read_object(s3, row["parquet_key"], row["parquet_sha256"], limit=134217728)
    table = pq.read_table(io.BytesIO(data))
    if len(table) != row["row_count"]:
        raise ValueError("snapshot_row_count")
    splits = {}
    for item in table.to_pylist():
        if item["profile_id"] in splits and splits[item["profile_id"]] != item["split"]:
            raise ValueError("snapshot_profile_split_leakage")
        splits[item["profile_id"]] = item["split"]
    if len(splits) != row["profile_count"]:
        raise ValueError("snapshot_profile_count")
    return {
        "snapshot_id": snapshot_id,
        "verified": True,
        "profiles": len(splits),
        "rows": len(table),
        "parquet_sha256": row["parquet_sha256"],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    replay_args = sub.add_parser("replay")
    replay_args.add_argument("--limit", type=int, default=1000)
    replay_args.add_argument("--after")
    importer = sub.add_parser("import-cache")
    importer.add_argument("directory")
    importer.add_argument("--limit", type=int, default=20)
    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("--policy", default="/argo-training.json")
    snapshot.add_argument("--as-of", required=True)
    snapshot.add_argument("--max-profiles", type=int, default=500)
    verify = sub.add_parser("verify-snapshot")
    verify.add_argument("snapshot_id")
    sub.add_parser("maintain")
    args = p.parse_args()
    try:
        if args.command == "replay":
            result = replay(args.limit, args.after)
        elif args.command == "import-cache":
            result = import_cache(args.directory, args.limit)
        elif args.command == "snapshot":
            result = build(args.policy, args.as_of, max_profiles=args.max_profiles)
        elif args.command == "verify-snapshot":
            result = verify_snapshot(args.snapshot_id)
        else:
            result = {
                "summaries_completed": evidence.recompute(limit=500),
                "monitor_checked_at": monitor(),
            }
    except ValueError as error:
        p.exit(2, str(error) + "\n")
    except Exception:
        logging.error("Scientific task deferred; inspect database/artifact readiness")
        p.exit(1)
    print(json.dumps(result, sort_keys=True, indent=2, default=str))


if __name__ == "__main__":
    main()
