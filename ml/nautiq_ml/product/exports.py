"""Fenced durable export leases, immutable artifacts and private-object cleanup."""

import csv
import hashlib
import html
import io
from importlib.metadata import version
import json
import os
import re
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from ..argo.storage import store, put_immutable, read_object

MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 10000
POLICY_PATH = next(
    p
    for p in (
        Path("/product.json"),
        Path(__file__).parents[3] / "packages/source-catalog/product.json",
        Path.cwd() / "packages/source-catalog/product.json",
    )
    if p.exists()
)
POLICY_BYTES = POLICY_PATH.read_bytes()
POLICY = json.loads(POLICY_BYTES)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def cell(value):
    if isinstance(value, str) and re.match(r"^[\s\x00-\x1f]*[=+@-]", value):
        return "'" + value
    return value


def flat_rows(snapshot):
    scope = snapshot["scope"]
    if scope == "research":
        variable = snapshot["query"]["variable"]
        if variable not in ("temperature_c", "practical_salinity"):
            raise ValueError("research_variable")
        rows = []
        for profile in snapshot["observations"]:
            metadata = {k: v for k, v in profile.items() if k != "levels"}
            for level in profile["levels"]:
                rows.append(
                    {
                        **metadata,
                        "depth_m": level["depth_m"],
                        "pressure_dbar": level["pressure_dbar"],
                        variable: level[variable],
                        "qc_flags": json.dumps(
                            level.get("qc_flags", {}), sort_keys=True
                        ),
                        "units": "degree_Celsius"
                        if variable == "temperature_c"
                        else "PSS-78 dimensionless",
                    }
                )
                if len(rows) > MAX_ROWS:
                    raise ValueError("row_budget")
        if len(rows) != snapshot["row_count"]:
            raise ValueError("row_count_integrity")
        return rows
    obj = snapshot["owned_object"]
    base = {
        "object_id": obj["id"],
        "name": obj["name"],
        "object_version": obj["version"],
    }
    if scope == "route":
        return [
            {**base, "order": i + 1, **point, "assessment": "not_assessed"}
            for i, point in enumerate(obj["data"]["waypoints"])
        ]
    if scope == "watchlist":
        return [
            {
                **base,
                "type": obj["data"]["type"],
                "geometry": json.dumps(obj["data"], sort_keys=True),
            }
        ]
    raise ValueError("source_redistribution_unreviewed")


def build(snapshot, kind, fmt, input_sha):
    if kind not in ("reports", "exports") or snapshot.get("schema_version") != 1:
        raise ValueError("export_schema")
    if snapshot.get("product_policy_sha256") != digest(POLICY_BYTES):
        raise ValueError("pinned_policy_unavailable")
    metadata = {
        "libraries": {
            name: version(name) for name in ("psycopg", "pyarrow", "netCDF4", "minio")
        },
        "input_sha256": input_sha,
        "policy_sha256": digest(POLICY_BYTES),
        "code_sha256": digest(Path(__file__).read_bytes()),
        "python": sys.version.split()[0],
        "snapshot": snapshot,
    }
    if fmt == "json":
        data = canonical(metadata) + b"\n"
    elif kind == "reports" and fmt == "html":
        text = html.escape(json.dumps(metadata, indent=2, ensure_ascii=False))
        data = (
            '<!doctype html><html lang="en"><meta charset="utf-8"><title>Nautiq private evidence report</title><style>body{font:16px system-ui;max-width:1000px;margin:40px auto;padding:20px;color:#163c40}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><h1>Nautiq private evidence report</h1><p>Frozen evidence; generated time does not renew freshness. This report carries the recorded limitations.</p><pre>'
            + text
            + "</pre></html>"
        ).encode()
    elif kind == "exports" and fmt in ("csv", "parquet", "netcdf"):
        rows = flat_rows(snapshot)
        if len(rows) > MAX_ROWS:
            raise ValueError("row_budget")
        common = {
            "input_sha256": input_sha,
            "generated_at": snapshot["generated_at"],
            "method_version": snapshot["method_version"],
            "attribution": snapshot.get("attribution", "User-owned Nautiq saved state"),
            "terms_url": snapshot.get("terms_url", ""),
            "limitations": "; ".join(snapshot["limitations"]),
        }
        rows = [{**common, **row} for row in rows]
        headers = list(dict.fromkeys([*common, *(k for row in rows for k in row)]))
        if fmt == "csv":
            output = io.StringIO(newline="")
            writer = csv.DictWriter(output, fieldnames=headers, lineterminator="\n")
            writer.writeheader()
            writer.writerows({k: cell(v) for k, v in row.items()} for row in rows)
            data = output.getvalue().encode("utf-8")
        elif fmt == "parquet":
            import pyarrow as pa
            import pyarrow.parquet as pq

            table = (
                pa.Table.from_pylist(rows)
                if rows
                else pa.table({k: pa.array([], type=pa.string()) for k in headers})
            )
            table = table.replace_schema_metadata(
                {
                    b"nautiq:evidence": canonical(
                        {k: v for k, v in metadata.items() if k != "snapshot"}
                    ),
                    b"nautiq:attribution": common["attribution"].encode(),
                }
            )
            buffer = io.BytesIO()
            pq.write_table(table, buffer, compression="zstd")
            data = buffer.getvalue()
        else:
            if snapshot["scope"] != "research":
                raise ValueError("netcdf_requires_research_observations")
            from netCDF4 import Dataset

            with tempfile.TemporaryDirectory(prefix="nautiq-export-") as folder:
                target = Path(folder) / "observations.nc"
                with Dataset(target, "w", format="NETCDF4") as dataset:
                    dataset.createDimension("obs", len(rows))
                    dataset.title = "Nautiq bounded original-level Argo research export"
                    dataset.source = "International Argo Program / Argo GDAC"
                    dataset.history = (
                        snapshot["generated_at"]
                        + ": frozen QC-accepted original levels; no location extrapolation"
                    )
                    dataset.nautiq_input_sha256 = input_sha
                    dataset.nautiq_evidence = canonical(
                        {k: v for k, v in metadata.items() if k != "snapshot"}
                    ).decode()
                    dataset.attribution = common["attribution"]
                    dataset.references = (
                        common["terms_url"] + " https://doi.org/10.17882/42182"
                    )
                    dataset.limitations = common["limitations"]
                    numeric = {
                        "latitude": "degrees_north",
                        "longitude": "degrees_east",
                        "depth_m": "m",
                        "pressure_dbar": "dbar",
                        snapshot["query"]["variable"]: "degree_Celsius"
                        if snapshot["query"]["variable"] == "temperature_c"
                        else "1",
                    }
                    for key, units in numeric.items():
                        var = dataset.createVariable(key, "f8", ("obs",), zlib=True)
                        var.units = units
                        if key == "depth_m":
                            var.positive = "down"
                        var[:] = [row[key] for row in rows]
                    time_var = dataset.createVariable(
                        "observed_at", "f8", ("obs",), zlib=True
                    )
                    time_var.units = "seconds since 1970-01-01 00:00:00 UTC"
                    time_var.calendar = "gregorian"
                    time_var[:] = [
                        datetime.fromisoformat(
                            row["observed_at"].replace("Z", "+00:00")
                        ).timestamp()
                        for row in rows
                    ]
                    for key in (
                        "profile_id",
                        "revision_sha256",
                        "raw_sha256",
                        "source_url",
                        "platform_id",
                        "qc_version",
                        "data_mode",
                        "source_id",
                        "qc_flags",
                    ):
                        var = dataset.createVariable(key, str, ("obs",))
                        for i, row in enumerate(rows):
                            var[i] = row[key]
                data = target.read_bytes()
    else:
        raise ValueError("format_not_appropriate")
    if not 0 < len(data) <= MAX_BYTES:
        raise ValueError("artifact_byte_budget")
    return data


def connection():
    return psycopg.connect(
        os.environ["DATABASE_URL"],
        autocommit=True,
        row_factory=dict_row,
        connect_timeout=5,
        options="-c statement_timeout=10000 -c lock_timeout=3000",
    )


def maintain(conn, s3):
    with conn.transaction():
        expired = conn.execute(
            "UPDATE product_jobs SET state='expired',version=version+1,lease_id=NULL,lease_expires_at=NULL WHERE expires_at<=now() AND state NOT IN ('expired','cancelled','failed','blocked') RETURNING object_key"
        ).fetchall()
        for row in expired:
            if row["object_key"]:
                conn.execute(
                    "INSERT INTO product_object_gc(object_key) VALUES(%s) ON CONFLICT DO NOTHING",
                    (row["object_key"],),
                )
        conn.execute(
            "UPDATE product_jobs SET state='failed',reason='lease_retry_budget',version=version+1,finished_at=now(),lease_id=NULL WHERE state='running' AND lease_expires_at<=now() AND attempts>=3"
        )
        conn.execute("DELETE FROM product_download_grants WHERE expires_at<=now()")
        conn.execute(
            "DELETE FROM product_sessions WHERE expires_at<=now() OR last_seen_at<=now()-interval '30 minutes'"
        )
        conn.execute("DELETE FROM product_idempotency WHERE expires_at<=now()")
        conn.execute(
            "DELETE FROM product_rate_limits WHERE window_start<now()-interval '24 hours'"
        )
        # Retain expired metadata for a bounded 24-hour grace period, then remove private snapshots.
        conn.execute(
            "DELETE FROM product_jobs WHERE expires_at<=now()-interval '24 hours'"
        )
    for row in conn.execute(
        "SELECT object_key FROM product_object_gc ORDER BY queued_at LIMIT 20"
    ).fetchall():
        key = row["object_key"]
        if not key.startswith(("product/private/", "trips/private/")):
            continue
        try:
            s3.remove_object("nautiq", key)
            conn.execute("DELETE FROM product_object_gc WHERE object_key=%s", (key,))
        except Exception:
            pass


def run_one(conn, s3):
    lease = str(uuid.uuid4())
    with conn.transaction():
        job = conn.execute(
            "SELECT * FROM product_jobs WHERE expires_at>now() AND attempts<3 AND (state='queued' OR state='running' AND lease_expires_at<=now()) ORDER BY created_at,job_id FOR UPDATE SKIP LOCKED LIMIT 1"
        ).fetchone()
        if not job:
            return False
        conn.execute(
            "UPDATE product_jobs SET state='running',lease_id=%s,lease_expires_at=now()+interval '90 seconds',attempts=attempts+1,version=version+1 WHERE job_id=%s",
            (lease, job["job_id"]),
        )
    key = None
    try:
        raw = bytes(job["input_bytes"])
        if len(raw) > 4 * 1024 * 1024 or digest(raw) != job["input_sha256"]:
            raise ValueError("input_hash_integrity")
        snapshot = json.loads(raw)
        if snapshot != job["input"]:
            raise ValueError("input_projection_integrity")
        if (
            snapshot["scope"] == "research"
            and not POLICY["export_permissions"]["source_profile_rows"]
        ):
            raise ValueError("source_redistribution_unreviewed")
        data = build(snapshot, job["kind"], job["format"], job["input_sha256"])
        sha = digest(data)
        key = f"product/private/{job['job_id']}/{lease}/{sha}.{job['format']}"
        put_immutable(s3, key, data)
        read_object(s3, key, sha, limit=MAX_BYTES)
        tag = conn.execute(
            "UPDATE product_jobs SET state='ready',object_key=%s,artifact_sha256=%s,artifact_bytes=%s,version=version+1,finished_at=now(),lease_id=NULL,lease_expires_at=NULL WHERE job_id=%s AND owner_id=%s AND state='running' AND lease_id=%s AND lease_expires_at>now() AND expires_at>now()",
            (key, sha, len(data), job["job_id"], job["owner_id"], lease),
        )
        if tag.rowcount != 1:
            s3.remove_object("nautiq", key)
    except Exception as error:
        if key:
            try:
                s3.remove_object("nautiq", key)
            except Exception:
                conn.execute(
                    "INSERT INTO product_object_gc(object_key) VALUES(%s) ON CONFLICT DO NOTHING",
                    (key,),
                )
        reason = (
            str(error)
            if isinstance(error, ValueError)
            else "artifact_or_storage_failure"
        )
        if not re.fullmatch("[a-z_]{1,80}", reason):
            reason = "artifact_contract_failure"
        conn.execute(
            "UPDATE product_jobs SET state='failed',reason=%s,version=version+1,finished_at=now(),lease_id=NULL,lease_expires_at=NULL WHERE job_id=%s AND state='running' AND lease_id=%s",
            (reason, job["job_id"], lease),
        )
    return True


def main():
    s3 = store()
    if "--once" in sys.argv:
        with connection() as conn:
            maintain(conn, s3)
            run_one(conn, s3)
        return
    while True:
        try:
            with connection() as conn:
                while True:
                    maintain(conn, s3)
                    busy = run_one(conn, s3)
                    time.sleep(0.2 if busy else 2)
        except Exception:
            print(
                "Private export dependency unavailable; reconnecting with durable jobs retained.",
                flush=True,
            )
            time.sleep(2)


if __name__ == "__main__":
    main()
