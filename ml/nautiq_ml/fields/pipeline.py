"""Atomic field catalog publication, replay verification and a bounded refresh worker."""

import argparse
import json
import os
import signal
import tempfile
import threading
import uuid
from urllib.parse import urlsplit, parse_qs

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..argo.storage import digest, put_immutable, read_object, store
from .core import FieldError, POLICY, VERSION, canonical, freshness, utc
from .providers import Acquisition, acquire_product
from .storage import open_grid, stage


def connection():
    return psycopg.connect(
        os.environ["DATABASE_URL"],
        autocommit=True,
        row_factory=dict_row,
        connect_timeout=5,
        options="-c statement_timeout=10000 -c lock_timeout=5000",
    )


def identifier(sha):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "nautiq:fields:" + sha))


def publish(db, s3, grid, receipts, source_version, before_commit=None):
    lat, lon, times, arrays, metadata = grid
    if not 1 <= len(receipts) <= 32:
        raise FieldError("raw_manifest_required")
    for receipt in receipts:
        if (
            receipt["raw_key"] != "fields/raw/" + receipt["sha256"]
            or not 0 < receipt["bytes"] <= POLICY["limits"]["raw_bytes"]
        ):
            raise FieldError("invalid_raw_manifest")
        read_object(s3, receipt["raw_key"], receipt["sha256"], receipt["bytes"])
    manifest, key, manifest_sha = stage(
        s3, lat, lon, times, arrays, metadata, receipts, source_version
    )
    release_id = identifier(manifest["release_sha256"])
    calculation = {
        "schema_version": 1,
        "kind": "field_normalization",
        "method_version": VERSION,
        "input": {
            "raw": receipts,
            "code_sha256": manifest["code_sha256"],
            "policy_sha256": manifest["policy_sha256"],
        },
        "output": {
            "release_id": release_id,
            "manifest_sha256": manifest_sha,
            "metadata": metadata,
            "release_approved": False,
        },
    }
    calc_sha = digest(canonical(calculation))
    calc_id, calc_key = (
        identifier(calc_sha),
        "fields/calculations/" + calc_sha + ".json",
    )
    put_immutable(s3, calc_key, canonical(calculation))
    product = metadata["product_id"]
    with db.transaction():
        db.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("field:" + product,))
        db.execute(
            "UPDATE field_products SET metadata=%s WHERE product_id=%s",
            (Jsonb(POLICY["products"][product]), product),
        )
        db.execute(
            "INSERT INTO calculations(calculation_id,calculation_sha256,kind,method_version,manifest,manifest_key,manifest_sha256,state) VALUES(%s,%s,'field_normalization',%s,%s,%s,%s,'frozen') ON CONFLICT(calculation_sha256) DO NOTHING",
            (calc_id, calc_sha, VERSION, Jsonb(calculation), calc_key, calc_sha),
        )
        db.execute(
            "INSERT INTO field_releases(release_id,release_sha256,product_id,calculation_id,cycle,valid_time_start,valid_time_end,source_version,manifest_key,manifest_sha256,manifest) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(release_sha256) DO NOTHING",
            (
                release_id,
                manifest["release_sha256"],
                product,
                calc_id,
                metadata["cycle"],
                metadata["valid_time_start"],
                metadata["valid_time_end"],
                source_version,
                key,
                manifest_sha,
                Jsonb(manifest),
            ),
        )
        retained = db.execute(
            "SELECT * FROM field_releases WHERE release_id=%s", (release_id,)
        ).fetchone()
        if (
            not retained
            or canonical(retained["manifest"]) != canonical(manifest)
            or retained["manifest_sha256"] != manifest_sha
        ):
            raise FieldError("immutable_catalog_conflict")
        # Latest-cycle selection never moves backward due to late arrival. Final supersedes preliminary for the same SST day.
        prior = db.execute(
            "SELECT r.* FROM field_selection s JOIN field_releases r USING(release_id) WHERE s.product_id=%s FOR UPDATE OF s",
            (product,),
        ).fetchone()
        candidate_rank = (
            utc(metadata["cycle"] or metadata["valid_time_start"]),
            source_version == "final",
        )
        prior_rank = (
            (
                prior["cycle"] or prior["valid_time_start"],
                prior["source_version"] == "final",
            )
            if prior
            else None
        )
        preserves_horizon = (
            prior is None
            or candidate_rank > prior_rank
            or (
                utc(metadata["valid_time_start"]) <= prior["valid_time_start"]
                and utc(metadata["valid_time_end"]) >= prior["valid_time_end"]
            )
        )
        if (prior_rank is None or candidate_rank >= prior_rank) and preserves_horizon:
            db.execute(
                "INSERT INTO field_selection(product_id,release_id) VALUES(%s,%s) ON CONFLICT(product_id) DO UPDATE SET release_id=excluded.release_id,selected_at=now() WHERE field_selection.release_id<>excluded.release_id",
                (product, release_id),
            )
        db.execute(
            "INSERT INTO event_outbox(event_id,event_type,schema_version,aggregate_key,revision_sha256,payload) VALUES(%s,'field.ready',1,%s,%s,%s) ON CONFLICT(event_id) DO NOTHING",
            (
                identifier("event:" + manifest["release_sha256"]),
                "field:" + product,
                manifest["release_sha256"],
                Jsonb(
                    {
                        "release_id": release_id,
                        "product_id": product,
                        "manifest_sha256": manifest_sha,
                    }
                ),
            ),
        )
        if before_commit:
            before_commit()
    return {
        "release_id": release_id,
        "calculation_id": calc_id,
        "manifest_sha256": manifest_sha,
        "metadata": metadata,
    }


def release(db, rid):
    try:
        rid = str(uuid.UUID(rid))
    except (ValueError, TypeError):
        raise FieldError("invalid_release_id") from None
    row = db.execute(
        "SELECT * FROM field_releases WHERE release_id=%s", (rid,)
    ).fetchone()
    if not row:
        raise FieldError("field_not_found")
    return row


def verify(db, s3, rid):
    row = release(db, rid)
    group, metadata = open_grid(s3, row, full=True)
    for receipt in row["manifest"]["raw"]:
        read_object(s3, receipt["raw_key"], receipt["sha256"], receipt["bytes"])
    # Verify all decoded values as well as compressed bytes; coordinates and masks remain native.
    import numpy as np
    from .core import validate_grid

    lat, lon, times, arrays, reproduced = validate_grid(
        group["latitude"][:],
        group["longitude"][:],
        group["time"][:],
        {name: group[name][:] for name in metadata["variables"]},
        metadata["product_id"],
        metadata["cycle"],
        metadata["valid_time_start"],
        metadata["valid_time_end"],
    )
    if canonical(reproduced) != canonical(metadata):
        raise FieldError("normalized_metadata_mismatch")
    return {
        "release_id": str(row["release_id"]),
        "manifest_sha256": row["manifest_sha256"],
        "status": "verified",
        "freshness": freshness(metadata),
        "shape": list(arrays[next(iter(arrays))].shape),
        "cells": int(np.prod((len(times), len(lat), len(lon)))),
        "release_approved": False,
    }


def ingest(db, s3, product, cycle=None, day=None, hours=24, bbox=None):
    if product not in POLICY["products"]:
        raise FieldError("unknown_product")
    if not db.execute(
        "SELECT pg_try_advisory_lock(hashtext(%s)) AS acquired", ("field:" + product,)
    ).fetchone()["acquired"]:
        raise FieldError("product_refresh_already_running")
    run_id = str(uuid.uuid4())
    try:
        db.execute(
            "INSERT INTO field_ingestion_runs(run_id,product_id,status) VALUES(%s,%s,'running')",
            (run_id, product),
        )
        with tempfile.TemporaryDirectory() as directory:
            acquisition = Acquisition(directory, s3)
            grid, version = acquire_product(
                acquisition, product, cycle, day, hours, bbox
            )
            result = publish(db, s3, grid, acquisition.receipts, version)
        db.execute(
            "UPDATE field_ingestion_runs SET status='complete',completed_at=now(),upstream_checked_at=now(),release_id=%s WHERE run_id=%s",
            (result["release_id"], run_id),
        )
        return result
    except Exception as error:
        code = (
            str(error)
            if isinstance(error, FieldError)
            else "field_ingestion_dependency_failure"
        )
        db.execute(
            "UPDATE field_ingestion_runs SET status='failed',completed_at=now(),reason_code=%s WHERE run_id=%s",
            (code, run_id),
        )
        raise FieldError(code) from None
    finally:
        db.execute("SELECT pg_advisory_unlock(hashtext(%s))", ("field:" + product,))


def maintain(db, s3):
    reports = []
    for row in db.execute(
        "SELECT r.* FROM field_selection s JOIN field_releases r USING(release_id)"
    ).fetchall():
        try:
            report = verify(db, s3, str(row["release_id"]))
            state = "ready"
        except Exception:
            report = {
                "release_id": str(row["release_id"]),
                "status": "unavailable",
                "reason": "field_integrity_unavailable",
            }
            state = "unavailable"
        db.execute(
            "UPDATE field_releases SET status=%s WHERE release_id=%s",
            (state, row["release_id"]),
        )
        reports.append(report)
    return reports


def replay(db, s3, rid):
    """Reparse exact retained requests without network access or manufactured data."""
    row = release(db, rid)
    metadata, receipts = row["manifest"]["metadata"], row["manifest"]["raw"]

    def request_key(url):
        parsed = urlsplit(url)
        params = parse_qs(parsed.query, keep_blank_values=True)
        for key in (
            "north",
            "south",
            "west",
            "east",
            "leftlon",
            "rightlon",
            "toplat",
            "bottomlat",
            "subregion",
        ):
            params.pop(key, None)
        return parsed.scheme, parsed.netloc, parsed.path, canonical(params)

    class Retained:
        def fetch(self, url):
            matches = [r for r in receipts if request_key(r["url"]) == request_key(url)]
            if not matches:
                # The analysis adapter tries final before preliminary; a retained
                # preliminary receipt cannot manufacture the absent final file.
                raise FieldError("http_404")
            if len(matches) != 1:
                raise FieldError("ambiguous_retained_source_request")
            raw = matches[0]
            return read_object(s3, raw["raw_key"], raw["sha256"], raw["bytes"])

    hours = int(
        (utc(metadata["times"][-1]) - utc(metadata["times"][0])).total_seconds() / 3600
    )
    grid, source_version = acquire_product(
        Retained(),
        metadata["product_id"],
        cycle=metadata["cycle"],
        day=metadata["valid_time_start"][:10]
        if metadata["kind"] == "analysis"
        else None,
        hours=hours,
        bbox=metadata["extent"],
    )
    if source_version != row["source_version"]:
        raise FieldError("retained_source_version_mismatch")
    return publish(db, s3, grid, receipts, source_version)


def main():
    parser = argparse.ArgumentParser(description="Nautiq immutable gridded field tools")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest_parser = commands.add_parser("ingest")
    ingest_parser.add_argument("product", choices=list(POLICY["products"]))
    ingest_parser.add_argument("--cycle")
    ingest_parser.add_argument("--day")
    ingest_parser.add_argument("--hours", type=int, default=24)
    ingest_parser.add_argument("--bbox", nargs=4, type=float)
    commands.add_parser("maintain")
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("release_id")
    replay_parser = commands.add_parser("replay")
    replay_parser.add_argument("release_id")
    refresh_parser = commands.add_parser("refresh")
    refresh_parser.add_argument("--watch", action="store_true")
    args = parser.parse_args()
    if args.command == "refresh":
        stopped = threading.Event()
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: stopped.set())
        while not stopped.is_set():
            for product in POLICY["products"]:
                if stopped.is_set():
                    break
                try:
                    with connection() as db:
                        # HYCOM runs arrive about a day late, so currents need 72 h to cover
                        # tomorrow; 48 h does the same for the six-hourly GFS cycles.
                        hours = 72 if product == "hycom_espc" else 48
                        result = ingest(db, store(), product, hours=hours)
                    print(
                        json.dumps(
                            {
                                "product_id": product,
                                "release_id": result["release_id"],
                                "status": "complete",
                            }
                        ),
                        flush=True,
                    )
                except Exception as error:
                    print(
                        json.dumps(
                            {
                                "product_id": product,
                                "status": "failed",
                                "reason": str(error)
                                if isinstance(error, FieldError)
                                else "dependency_failure",
                            }
                        ),
                        flush=True,
                    )
            if not args.watch:
                break
            stopped.wait(3600)
        return
    with connection() as db:
        s3 = store()
        if args.command == "ingest":
            result = ingest(
                db, s3, args.product, args.cycle, args.day, args.hours, args.bbox
            )
        elif args.command == "verify":
            result = verify(db, s3, args.release_id)
        elif args.command == "replay":
            result = replay(db, s3, args.release_id)
        else:
            result = maintain(db, s3)
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
