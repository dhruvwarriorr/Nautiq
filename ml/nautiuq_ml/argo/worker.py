"""Durable raw.received consumer, immutable lake artifacts, and replay repair."""

import asyncio
import hashlib
import io
import itertools
import json
import logging
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import uuid
import urllib3
from datetime import datetime
from pathlib import Path

import nats
import psycopg
import pyarrow as pa
import pyarrow.parquet as pq
from minio import Minio
from minio.error import S3Error
from nats.js.api import ConsumerConfig, AckPolicy, DeliverPolicy
from nats.js.errors import NotFoundError
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .parser import InvalidProfile, parse, revision_digest

CONSUMER = "argo-normalizer-v1"
MAX_BYTES = 64 * 1024 * 1024
_lake_cursor = None
_raw_cursor = None


def store():
    return Minio(
        os.environ["MINIO_ENDPOINT"],
        access_key=os.environ["MINIO_ROOT_USER"],
        secret_key=os.environ["MINIO_ROOT_PASSWORD"],
        secure=False,
        http_client=urllib3.PoolManager(
            timeout=urllib3.Timeout(connect=5, read=10),
            retries=urllib3.Retry(total=1, backoff_factor=0.5),
        ),
    )


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_object(s3, key, expected, limit=MAX_BYTES):
    response = s3.get_object("nautiuq", key)
    try:
        data = response.read(limit + 1)
    finally:
        response.close()
        response.release_conn()
    if len(data) > limit or digest(data) != expected:
        raise InvalidProfile("artifact_checksum_or_budget")
    return data


def put_immutable(s3, key, data):
    try:
        info = s3.stat_object("nautiuq", key)
        if info.size != len(data) or info.metadata.get("x-amz-meta-sha256") != digest(
            data
        ):
            raise InvalidProfile("immutable_lake_conflict")
        read_object(s3, key, digest(data))
    except S3Error as error:
        if error.code != "NoSuchKey":
            raise
        s3.put_object(
            "nautiuq",
            key,
            io.BytesIO(data),
            len(data),
            metadata={"sha256": digest(data)},
        )
        read_object(s3, key, digest(data))


def decode_envelope(data):
    if len(data) > 262144:
        raise InvalidProfile("event_budget")
    value = json.loads(data)
    if (
        not isinstance(value, dict)
        or not all(
            isinstance(value.get(k), str)
            for k in (
                "event_id",
                "aggregate_key",
                "event_type",
                "revision_sha256",
                "created_at",
            )
        )
        or type(value.get("schema_version")) is not int
        or not isinstance(value.get("payload"), dict)
        or not isinstance(value["payload"].get("artifact_id"), str)
    ):
        raise InvalidProfile("invalid_event_envelope")
    created = datetime.fromisoformat(value["created_at"])
    if created.tzinfo is None or created.utcoffset().total_seconds() != 0:
        raise InvalidProfile("event_time_not_utc")
    uuid.UUID(value["event_id"])
    uuid.UUID(value["aggregate_key"])
    uuid.UUID(value["payload"]["artifact_id"])
    if (
        value["schema_version"] != 1
        or value["event_type"] != "raw.received"
        or not re.fullmatch(r"[a-f0-9]{64}", value["revision_sha256"])
    ):
        raise InvalidProfile("unsupported_event_contract")
    if value["aggregate_key"] != value["payload"]["artifact_id"]:
        raise InvalidProfile("event_artifact_mismatch")
    return value


def isolated_parse(data):
    # Untrusted NetCDF native code runs in a short-lived child, bounded by container quotas.
    with tempfile.TemporaryDirectory() as directory:
        raw, result = Path(directory) / "raw.nc", Path(directory) / "result.json"
        raw.write_bytes(data)
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "nautiuq_ml.argo.worker",
                    "parse",
                    str(raw),
                    str(result),
                ],
                timeout=45,
                capture_output=True,
            )
        except subprocess.TimeoutExpired:
            raise InvalidProfile("parser_deadline") from None
        if (
            completed.returncode
            or not result.exists()
            or result.stat().st_size > 32 * 1024 * 1024
        ):
            raise InvalidProfile("parser_rejected_or_crashed")
        return json.loads(result.read_bytes())


def quarantine(db, event_id, artifact, reason):
    db.execute(
        "INSERT INTO ingestion_quarantine(quarantine_id,event_id,artifact_id,reason_code) VALUES(%s,%s,%s,%s) ON CONFLICT(event_id) DO NOTHING",
        (str(uuid.uuid4()), event_id, artifact, reason),
    )
    db.execute(
        "INSERT INTO consumer_inbox(consumer_name,event_id) VALUES(%s,%s) ON CONFLICT DO NOTHING",
        (CONSUMER, event_id),
    )


def lake(s3, profile, raw_sha):
    revision = revision_digest(profile, raw_sha)
    rows = [
        {
            "profile_id": str(uuid.uuid5(uuid.NAMESPACE_URL, profile["native_key"])),
            "revision_sha256": revision,
            "raw_sha256": raw_sha,
            "observed_at": profile["observed_at"],
            "latitude": profile["latitude"],
            "longitude": profile["longitude"],
            "data_mode": profile["data_mode"],
            "qc_version": profile["qc_version"],
            "source_level_index": level["qc_flags"]["source_level_index"],
            "pressure_dbar": level["pressure_dbar"],
            "depth_m": level["depth_m"],
            "temperature_c": level["temperature_c"],
            "practical_salinity": level["practical_salinity"],
            "missing_reasons": json.dumps(level["missing_reasons"], sort_keys=True),
            "qc_flags": json.dumps(level["qc_flags"], sort_keys=True),
        }
        for level in profile["levels"]
    ]
    # Explicit nullable doubles: a wholly missing variable never changes the lake schema.
    schema = pa.schema(
        [
            (
                k,
                pa.float64()
                if k
                in {
                    "latitude",
                    "longitude",
                    "pressure_dbar",
                    "depth_m",
                    "temperature_c",
                    "practical_salinity",
                }
                else pa.string(),
            )
            for k in rows[0]
        ]
    )
    output = io.BytesIO()
    pq.write_table(
        pa.Table.from_pylist(rows, schema=schema),
        output,
        compression="zstd",
        version="2.6",
    )
    data = output.getvalue()
    key = f"lake/observations/schema=v1/year={profile['observed_at'][:4]}/month={profile['observed_at'][5:7]}/{revision}.parquet"
    put_immutable(s3, key, data)
    manifest = json.dumps(
        {
            "revision_sha256": revision,
            "raw_sha256": raw_sha,
            "parquet_key": key,
            "parquet_sha256": digest(data),
            "row_count": len(rows),
            "normalizer_version": profile["normalizer_version"],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    put_immutable(s3, f"lake/manifests/{revision}.json", manifest)
    return revision, key, digest(data)


def process(event_data, s3=None):
    event = decode_envelope(event_data)
    s3 = s3 or store()
    with psycopg.connect(
        os.environ["DATABASE_URL"], row_factory=dict_row, connect_timeout=5
    ) as db:
        db.execute("SET statement_timeout='15s'; SET lock_timeout='5s'")
        if db.execute(
            "SELECT 1 FROM consumer_inbox WHERE consumer_name=%s AND event_id=%s",
            (CONSUMER, event["event_id"]),
        ).fetchone():
            return "duplicate"
        raw = db.execute(
            "SELECT * FROM raw_artifacts WHERE artifact_id=%s",
            (event["payload"]["artifact_id"],),
        ).fetchone()
        if not raw:
            raise RuntimeError("artifact_registry_pending")
        if raw["kind"] != "profile" or raw["sha256"] != event["revision_sha256"]:
            quarantine(
                db, event["event_id"], raw["artifact_id"], "event_artifact_mismatch"
            )
            return "quarantined"
        try:
            data = read_object(s3, raw["object_key"], raw["sha256"])
            parsed = isolated_parse(data)
            prepared = [
                (profile, *lake(s3, profile, raw["sha256"]))
                for profile in parsed["profiles"]
            ]
        except (InvalidProfile, ValueError, KeyError) as error:
            reason = (
                str(error)
                if isinstance(error, InvalidProfile)
                else "invalid_parser_output"
            )
            quarantine(db, event["event_id"], raw["artifact_id"], reason)
            return "quarantined"
        # Object/lake publication precedes one atomic canonical+inbox+outbox commit.
        # A DB failure leaves immutable staged objects that replay reuses.
        db.execute("SELECT pg_advisory_xact_lock(78192402)")
        for profile, revision, parquet_key, parquet_sha in prepared:
            profile_id = str(uuid.uuid5(uuid.NAMESPACE_URL, profile["native_key"]))
            revision_id = str(uuid.uuid5(uuid.NAMESPACE_URL, profile_id + revision))
            db.execute(
                "INSERT INTO profiles(profile_id,native_key,platform_id,cycle_number,direction,sampling_scheme,profile_index) VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(native_key) DO NOTHING",
                (
                    profile_id,
                    profile["native_key"],
                    profile["platform_id"],
                    profile["cycle_number"],
                    profile["direction"],
                    profile["sampling_scheme"],
                    profile["profile_index"],
                ),
            )
            # Row lock serializes revisions and duplicate deliveries for each native profile.
            db.execute(
                "SELECT profile_id FROM profiles WHERE profile_id=%s FOR UPDATE",
                (profile_id,),
            )
            current = db.execute(
                "SELECT * FROM profile_revisions WHERE profile_id=%s AND selected_at IS NOT NULL AND superseded_at IS NULL",
                (profile_id,),
            ).fetchone()
            inserted = db.execute(
                """INSERT INTO profile_revisions(revision_id,profile_id,revision_sha256,raw_artifact_id,observed_at,received_at,source_updated_at,latitude,longitude,position,data_mode,qc_version,normalizer_version,depth_conversion_version,parameter_modes,levels,parquet_key,parquet_sha256,science_ready)
VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,ST_SetSRID(ST_MakePoint(%s,%s),4326),%s,%s,%s,%s,%s,%s,%s,%s,true) ON CONFLICT(profile_id,revision_sha256) DO NOTHING RETURNING revision_id""",
                (
                    revision_id,
                    profile_id,
                    revision,
                    raw["artifact_id"],
                    profile["observed_at"],
                    raw["received_at"],
                    profile["source_updated_at"],
                    profile["latitude"],
                    profile["longitude"],
                    profile["longitude"],
                    profile["latitude"],
                    profile["data_mode"],
                    profile["qc_version"],
                    profile["normalizer_version"],
                    profile["depth_conversion_version"],
                    Jsonb(profile["parameter_modes"]),
                    Jsonb(profile["levels"]),
                    parquet_key,
                    parquet_sha,
                ),
            ).fetchone()
            db.execute(
                "INSERT INTO profile_source_links(profile_id,artifact_id) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                (profile_id, raw["artifact_id"]),
            )
            if not inserted:
                continue
            rank = {"R": 0, "A": 1, "D": 2}
            new_rank = (
                rank[profile["data_mode"]],
                datetime.fromisoformat(profile["source_updated_at"]),
            )
            old_rank = (
                (rank[current["data_mode"]], current["source_updated_at"])
                if current
                else None
            )
            if old_rank == new_rank and current["revision_sha256"] != revision:
                quarantine(
                    db,
                    str(uuid.uuid5(uuid.NAMESPACE_URL, event["event_id"] + profile_id)),
                    raw["artifact_id"],
                    "same_version_revision_conflict",
                )
            if old_rank is None or new_rank > old_rank:
                # Clock timestamp avoids transaction-start ordering after waiting on a lock.
                chosen = db.execute("SELECT clock_timestamp() AS chosen").fetchone()[
                    "chosen"
                ]
                if current:
                    db.execute(
                        "UPDATE profile_revisions SET superseded_at=%s WHERE revision_id=%s",
                        (chosen, current["revision_id"]),
                    )
                db.execute(
                    "UPDATE profile_revisions SET selected_at=%s WHERE revision_id=%s",
                    (chosen, revision_id),
                )
                event_type = "profile.revised" if current else "profile.ready"
                ready_id = str(
                    uuid.uuid5(uuid.NAMESPACE_URL, event_type + profile_id + revision)
                )
                db.execute(
                    "INSERT INTO event_outbox(event_id,event_type,schema_version,aggregate_key,revision_sha256,payload) VALUES(%s,%s,1,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (
                        ready_id,
                        event_type,
                        profile_id,
                        revision,
                        Jsonb({"profile_id": profile_id, "revision_sha256": revision}),
                    ),
                )
        for rejection in parsed["rejections"]:
            reject_id = str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    event["event_id"] + str(rejection["profile_index"]),
                )
            )
            quarantine(db, reject_id, raw["artifact_id"], rejection["reason_code"])
        if not prepared and not parsed["rejections"]:
            quarantine(db, event["event_id"], raw["artifact_id"], "no_profiles")
        db.execute(
            "INSERT INTO consumer_inbox(consumer_name,event_id) VALUES(%s,%s) ON CONFLICT DO NOTHING",
            (CONSUMER, event["event_id"]),
        )
        return "normalized"


def repair_lake(db, s3):
    """Bounded rolling integrity sweep; reconstruct missing outputs from retained raw."""
    global _lake_cursor
    with db.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            """SELECT r.*,a.sha256 AS raw_sha,a.object_key FROM profile_revisions r
JOIN raw_artifacts a ON a.artifact_id=r.raw_artifact_id
WHERE (%s::uuid IS NULL OR r.revision_id>%s::uuid) ORDER BY r.revision_id LIMIT 20""",
            (_lake_cursor, _lake_cursor),
        ).fetchall()
    for row in rows:
        revision = row["revision_sha256"]
        manifest_key = f"lake/manifests/{revision}.json"
        expected = json.dumps(
            {
                "revision_sha256": revision,
                "raw_sha256": row["raw_sha"],
                "parquet_key": row["parquet_key"],
                "parquet_sha256": row["parquet_sha256"],
                "row_count": len(row["levels"]),
                "normalizer_version": row["normalizer_version"],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        try:
            try:
                read_object(s3, row["object_key"], row["raw_sha"])
                read_object(s3, manifest_key, digest(expected), limit=1048576)
                read_object(s3, row["parquet_key"], row["parquet_sha256"])
            except S3Error as error:
                if error.code != "NoSuchKey":
                    raise
                db.execute(
                    "UPDATE profile_revisions SET science_ready=false WHERE revision_id=%s",
                    (row["revision_id"],),
                )
                parsed = isolated_parse(
                    read_object(s3, row["object_key"], row["raw_sha"])
                )
                profile = next(
                    (
                        p
                        for p in parsed["profiles"]
                        if revision_digest(p, row["raw_sha"]) == revision
                    ),
                    None,
                )
                if profile is None:
                    raise InvalidProfile("lake_reconstruction_version_mismatch")
                restored = lake(s3, profile, row["raw_sha"])
                if restored != (revision, row["parquet_key"], row["parquet_sha256"]):
                    raise InvalidProfile("lake_reconstruction_checksum_mismatch")
            db.execute(
                "UPDATE profile_revisions SET science_ready=true WHERE revision_id=%s",
                (row["revision_id"],),
            )
            db.execute(
                "UPDATE ingestion_quarantine SET resolved_at=now() WHERE event_id=%s AND resolved_at IS NULL",
                (str(uuid.uuid5(uuid.NAMESPACE_URL, "lake-integrity|" + revision)),),
            )
        except (InvalidProfile, S3Error) as error:
            if isinstance(error, S3Error) and error.code != "NoSuchKey":
                raise
            db.execute(
                "UPDATE profile_revisions SET science_ready=false WHERE revision_id=%s",
                (row["revision_id"],),
            )
            quarantine(
                db,
                str(uuid.uuid5(uuid.NAMESPACE_URL, "lake-integrity|" + revision)),
                row["raw_artifact_id"],
                "lake_integrity_failed",
            )
        _lake_cursor = str(row["revision_id"])
    if len(rows) < 20:
        _lake_cursor = None


def repair(raw_prefix="raw/argo_gdac/profile/"):
    """Repair raw registry/events and lake manifests; requeue unconsumed work."""
    global _raw_cursor
    s3 = store()
    with psycopg.connect(
        os.environ["DATABASE_URL"], row_factory=dict_row, connect_timeout=5
    ) as db:
        db.execute("SET statement_timeout='15s'; SET lock_timeout='5s'")
        # Recover a durable object written before SQL registration. Objects retain native path/version.
        checked = 0
        for obj in itertools.islice(
            s3.list_objects(
                "nautiuq", prefix=raw_prefix, recursive=True, start_after=_raw_cursor
            ),
            200,
        ):
            checked += 1
            _raw_cursor = obj.object_name
            info = s3.stat_object("nautiuq", obj.object_name)
            path = info.metadata.get("x-amz-meta-source_path", "")
            sha = info.metadata.get("x-amz-meta-sha256", "")
            updated = info.metadata.get("x-amz-meta-source_updated_at", "")
            if not re.fullmatch(
                r"[a-z]+/[0-9]{5,8}/profiles/[RD][0-9]{5,8}_[0-9]+D?\.nc", path
            ) or not re.fullmatch(r"[a-f0-9]{64}", sha):
                continue
            artifact = str(
                uuid.uuid5(uuid.NAMESPACE_URL, "argo_gdac|" + path + "|" + sha)
            )
            row = db.execute(
                "SELECT artifact_id FROM raw_artifacts WHERE source_id='argo_gdac' AND source_path=%s AND sha256=%s",
                (path, sha),
            ).fetchone()
            if not row:
                read_object(s3, obj.object_name, sha)
                run = str(uuid.uuid4())
                db.execute(
                    "INSERT INTO ingestion_runs(run_id,source_id,status,completed_at) VALUES(%s,'argo_gdac','reconciled',now())",
                    (run,),
                )
                db.execute(
                    "INSERT INTO raw_artifacts(artifact_id,source_id,source_path,source_url,source_updated_at,sha256,object_key,size_bytes,kind,run_id) VALUES(%s,'argo_gdac',%s,%s,%s,%s,%s,%s,'profile',%s) ON CONFLICT DO NOTHING",
                    (
                        artifact,
                        path,
                        "https://data-argo.ifremer.fr/dac/" + path,
                        updated,
                        sha,
                        obj.object_name,
                        obj.size,
                        run,
                    ),
                )
        if checked < 200:
            _raw_cursor = None
        # Retention/ack loss: use the original stable event ID. Broker dedup is temporary.
        db.execute(
            """UPDATE event_outbox e SET published_at=NULL,next_attempt_at=now(),lease_until=NULL
WHERE e.event_type='raw.received' AND e.published_at < now()-interval '5 minutes'
AND NOT EXISTS(SELECT 1 FROM consumer_inbox i WHERE i.consumer_name=%s AND i.event_id=e.event_id)""",
            (CONSUMER,),
        )
        for raw in db.execute(
            "SELECT r.* FROM raw_artifacts r WHERE kind='profile' AND NOT EXISTS(SELECT 1 FROM event_outbox e WHERE e.event_type='raw.received' AND e.aggregate_key=r.artifact_id::text)"
        ).fetchall():
            eid = str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL, "raw.received|" + str(raw["artifact_id"])
                )
            )
            db.execute(
                "INSERT INTO event_outbox(event_id,event_type,schema_version,aggregate_key,revision_sha256,payload) VALUES(%s,'raw.received',1,%s,%s,%s) ON CONFLICT DO NOTHING",
                (
                    eid,
                    str(raw["artifact_id"]),
                    raw["sha256"],
                    Jsonb({"artifact_id": str(raw["artifact_id"])}),
                ),
            )
        repair_lake(db, s3)


async def consume():
    stopped = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(sig, stopped.set)
    nc = await nats.connect(
        os.environ["NATS_URL"], max_reconnect_attempts=-1, reconnect_time_wait=2
    )
    js = nc.jetstream()
    # Stream is owned by ingestion; wait without creating a conflicting stream definition.
    while not stopped.is_set():
        try:
            await js.stream_info("ARGO")
            break
        except NotFoundError:
            await asyncio.sleep(1)
    await js.add_consumer(
        "ARGO",
        ConsumerConfig(
            durable_name=CONSUMER,
            filter_subject="raw.received",
            ack_policy=AckPolicy.EXPLICIT,
            deliver_policy=DeliverPolicy.ALL,
            ack_wait=120,
            max_ack_pending=4,
            max_deliver=-1,
        ),
    )
    sub = await js.pull_subscribe("raw.received", durable=CONSUMER, stream="ARGO")
    last_repair = 0
    while not stopped.is_set():
        if time.monotonic() - last_repair > 60:
            try:
                await asyncio.to_thread(repair)
                last_repair = time.monotonic()
            except Exception:
                logging.warning("Reconciliation deferred; storage/database unavailable")
        try:
            messages = await sub.fetch(1, timeout=2)
        except (TimeoutError, nats.errors.TimeoutError):
            continue
        for message in messages:
            try:
                result = await asyncio.to_thread(process, message.data)
                await message.ack_sync(timeout=5)
                logging.info("Argo delivery committed: %s", result)
            except (InvalidProfile, ValueError, KeyError, TypeError):
                # Even an invalid envelope receives a durable dead-letter identity.
                eid = str(uuid.uuid5(uuid.NAMESPACE_URL, digest(message.data)))
                with psycopg.connect(
                    os.environ["DATABASE_URL"], connect_timeout=5
                ) as db:
                    quarantine(db, eid, None, "invalid_event_envelope")
                await message.ack_sync(timeout=5)
            except Exception:
                # Transient retries cap their delay, not attempts: outage must not discard data.
                await message.nak(
                    delay=min(60, 2 ** min(message.metadata.num_delivered, 5))
                )
                logging.warning("Argo delivery deferred; retry pending")
    await nc.drain()


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if len(sys.argv) > 1 and sys.argv[1] == "parse":
        result = parse(sys.argv[2])
        Path(sys.argv[3]).write_text(
            json.dumps(result, sort_keys=True, allow_nan=False)
        )
    elif len(sys.argv) > 1 and sys.argv[1] == "repair":
        repair()
    else:
        asyncio.run(consume())


if __name__ == "__main__":
    main()
