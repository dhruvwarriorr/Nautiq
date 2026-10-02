"""Frozen, pinned original-level D/QC1 label snapshots; no live training API loop."""

import io
import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import pyarrow as pa
import pyarrow.parquet as pq
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import evidence
from .storage import digest, put_immutable, read_object, store

METHOD = "argo-training-original-levels-v1"


def utc(value):
    instant = datetime.fromisoformat(value)
    if instant.tzinfo is None:
        raise ValueError("explicit_timezone_required")
    return instant.astimezone(timezone.utc)


def load_policy(path):
    value = json.loads(Path(path).read_bytes())
    if (
        value.get("schema_version") != 1
        or value.get("required_profile_mode") != "D"
        or value.get("required_parameter_mode") != "D"
        or value.get("required_qc") != "1"
        or value.get("representation") != "original_levels_no_interpolation"
        or value.get("release_approved") is not False
    ):
        raise ValueError("unsupported_training_policy")
    start, end = value["baseline"]["start_year"], value["baseline"]["end_year"]
    splits = value["splits"]
    if (
        not 1900
        <= start
        <= splits["train_end"]
        < splits["tune_end"]
        < splits["calibration_end"]
        < end
        <= 2100
    ):
        raise ValueError("invalid_training_splits")
    box = value["domain"]
    if (
        not -180 <= box["west"] < box["east"] <= 180
        or not -90 <= box["south"] < box["north"] <= 90
    ):
        raise ValueError("invalid_training_domain")
    return value


def split(observed, policy):
    year = utc(observed).year
    if not policy["baseline"]["start_year"] <= year <= policy["baseline"]["end_year"]:
        return None
    s = policy["splits"]
    return (
        "train"
        if year <= s["train_end"]
        else "tune"
        if year <= s["tune_end"]
        else "calibration"
        if year <= s["calibration_end"]
        else "test"
    )


def training_rows(profile, policy):
    assignment = split(profile["observed_at"], policy)
    if profile["data_mode"] != "D" or assignment is None:
        return [], "profile_not_delayed" if profile[
            "data_mode"
        ] != "D" else "outside_baseline"
    rows = []
    for level in profile["levels"]:
        if (
            profile["parameter_modes"].get("PRES") != "D"
            or level["qc_flags"].get("PRES") != "1"
            or level["qc_flags"].get("PRES_selected_field") != "PRES_ADJUSTED"
        ):
            continue
        labels = {}
        for param, key in (("TEMP", "temperature_c"), ("PSAL", "practical_salinity")):
            labels[key] = (
                level[key]
                if (
                    profile["parameter_modes"].get(param) == "D"
                    and level["qc_flags"].get(param) == "1"
                    and level["qc_flags"].get(param + "_selected_field")
                    == param + "_ADJUSTED"
                )
                else None
            )
        if all(v is None for v in labels.values()):
            continue
        rows.append(
            {
                "profile_id": profile["profile_id"],
                "revision_sha256": profile["revision_sha256"],
                "raw_sha256": profile["raw_sha256"],
                "platform_id": profile["platform_id"],
                "observed_at": profile["observed_at"],
                "latitude": profile["latitude"],
                "longitude": profile["longitude"],
                "split": assignment,
                "source_level_index": int(level["qc_flags"]["source_level_index"]),
                "pressure_dbar": level["pressure_dbar"],
                "depth_m": level["depth_m"],
                **labels,
                "training_qc_version": policy["qc_version"],
                "missing_reasons": json.dumps(
                    {
                        k: "training_label_unavailable"
                        for k, v in labels.items()
                        if v is None
                    },
                    sort_keys=True,
                ),
            }
        )
    return rows, None if rows else "no_eligible_labels"


SCHEMA = pa.schema(
    [
        ("profile_id", pa.string()),
        ("revision_sha256", pa.string()),
        ("raw_sha256", pa.string()),
        ("platform_id", pa.string()),
        ("observed_at", pa.string()),
        ("latitude", pa.float64()),
        ("longitude", pa.float64()),
        ("split", pa.string()),
        ("source_level_index", pa.int32()),
        ("pressure_dbar", pa.float64()),
        ("depth_m", pa.float64()),
        ("temperature_c", pa.float64()),
        ("practical_salinity", pa.float64()),
        ("training_qc_version", pa.string()),
        ("missing_reasons", pa.string()),
    ]
)


@contextmanager
def selection_database():
    # Acquire the selection barrier before establishing a consistent read snapshot.
    # Closing this dedicated connection releases its session advisory lock even on error.
    with psycopg.connect(
        os.environ["DATABASE_URL"],
        row_factory=dict_row,
        connect_timeout=5,
        autocommit=True,
    ) as db:
        db.execute("SET statement_timeout='30s'; SET lock_timeout='5s'")
        db.execute("SELECT pg_advisory_lock_shared(78192402)")
        with db.transaction():
            db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            yield db


def build(policy_path, as_of, s3=None, max_profiles=500):
    policy = load_policy(policy_path)
    as_of = utc(as_of)
    if as_of > datetime.now(timezone.utc):
        raise ValueError("snapshot_as_of_in_future")
    if not 1 <= max_profiles <= min(2000, policy["limits"]["max_profiles"]):
        raise ValueError("snapshot_profile_budget")
    s3 = s3 or store()
    box = policy["domain"]
    start = datetime(policy["baseline"]["start_year"], 1, 1, tzinfo=timezone.utc)
    end = datetime(policy["baseline"]["end_year"] + 1, 1, 1, tzinfo=timezone.utc)
    with selection_database() as db:
        bounds = db.execute(
            """SELECT count(*) AS n,coalesce(sum(jsonb_array_length(r.levels)),0) AS levels FROM profile_revisions r
WHERE r.science_ready AND r.selected_at<=%s AND (r.superseded_at IS NULL OR r.superseded_at>%s)
AND r.observed_at>=%s AND r.observed_at<%s AND r.position && ST_MakeEnvelope(%s,%s,%s,%s,4326)""",
            (
                as_of,
                as_of,
                start,
                end,
                box["west"],
                box["south"],
                box["east"],
                box["north"],
            ),
        ).fetchone()
        if bounds["n"] > max_profiles or bounds["levels"] > min(
            100000, policy["limits"]["max_levels"]
        ):
            raise ValueError("snapshot_selection_exceeds_budget")
        selected = db.execute(
            """SELECT p.platform_id,r.*,a.sha256 raw_sha,a.object_key,a.source_id,s.metadata source_metadata
FROM profiles p JOIN profile_revisions r USING(profile_id) JOIN raw_artifacts a ON a.artifact_id=r.raw_artifact_id JOIN sources s USING(source_id)
WHERE r.science_ready AND r.selected_at<=%s AND (r.superseded_at IS NULL OR r.superseded_at>%s)
AND r.observed_at>=%s AND r.observed_at<%s AND r.position && ST_MakeEnvelope(%s,%s,%s,%s,4326)
ORDER BY p.profile_id LIMIT %s""",
            (
                as_of,
                as_of,
                start,
                end,
                box["west"],
                box["south"],
                box["east"],
                box["north"],
                max_profiles + 1,
            ),
        ).fetchall()
    if len(selected) > max_profiles:
        raise ValueError("snapshot_selection_exceeds_budget")
    rows, inputs, excluded = [], [], {}
    for p in selected:
        if policy.get("source_production_approval_required") and not p[
            "source_metadata"
        ].get("production_approved"):
            raise ValueError("source_not_production_approved")
        profile = {
            **p,
            "profile_id": str(p["profile_id"]),
            "observed_at": p["observed_at"].isoformat(),
            "raw_sha256": p["raw_sha"],
        }
        eligible, reason = training_rows(profile, policy)
        if reason:
            excluded[reason] = excluded.get(reason, 0) + 1
            continue
        # Validate original immutable input artifacts, not just the live SQL projection.
        read_object(s3, p["object_key"], p["raw_sha"])
        pinned = pq.read_table(
            io.BytesIO(read_object(s3, p["parquet_key"], p["parquet_sha256"]))
        ).to_pylist()
        if len(pinned) != len(profile["levels"]):
            raise ValueError("canonical_lake_mismatch")
        for saved, level in zip(pinned, profile["levels"], strict=True):
            original = {
                key: saved[key]
                for key in (
                    "pressure_dbar",
                    "depth_m",
                    "temperature_c",
                    "practical_salinity",
                )
            }
            original.update(
                qc_flags=json.loads(saved["qc_flags"]),
                missing_reasons=json.loads(saved["missing_reasons"]),
            )
            if original != level or any(
                saved[key] != profile[key]
                for key in (
                    "profile_id",
                    "revision_sha256",
                    "raw_sha256",
                    "observed_at",
                    "latitude",
                    "longitude",
                    "data_mode",
                    "qc_version",
                )
            ):
                raise ValueError("canonical_lake_mismatch")
        rows.extend(eligible)
        if len(rows) > min(100000, policy["limits"]["max_levels"]):
            raise ValueError("snapshot_level_budget")
        inputs.append(
            {
                **evidence.input_ref(
                    p["profile_id"], p["revision_sha256"], p["raw_sha"]
                ),
                "source_id": p["source_id"],
                "parquet_key": p["parquet_key"],
                "parquet_sha256": p["parquet_sha256"],
                "normalizer_version": p["normalizer_version"],
                "depth_conversion_version": p["depth_conversion_version"],
                "display_qc_version": p["qc_version"],
                "source_metadata": p["source_metadata"],
            }
        )
    stream = io.BytesIO()
    pq.write_table(
        pa.Table.from_pylist(rows, schema=SCHEMA),
        stream,
        compression="zstd",
        version="2.6",
    )
    data = stream.getvalue()
    if len(data) > min(134217728, policy["limits"]["max_parquet_bytes"]):
        raise ValueError("snapshot_parquet_budget")
    counts = {
        name: sum(r["split"] == name for r in rows)
        for name in ("train", "tune", "calibration", "test")
    }
    output = {
        "parquet_sha256": digest(data),
        "profile_count": len(inputs),
        "row_count": len(rows),
        "split_rows": counts,
        "excluded_profiles": excluded,
        "selected_profile_count": len(selected),
        "representation": policy["representation"],
        "spatial_coverage": {
            "latitude_range": [
                min(r["latitude"] for r in rows),
                max(r["latitude"] for r in rows),
            ],
            "longitude_range": [
                min(r["longitude"] for r in rows),
                max(r["longitude"] for r in rows),
            ],
        }
        if rows
        else None,
        "observed_range": [
            min(r["observed_at"] for r in rows),
            max(r["observed_at"] for r in rows),
        ]
        if rows
        else None,
        "release_approved": False,
        "status": "ready" if rows else "empty",
    }
    calc = evidence.publish(
        s3,
        "training_snapshot",
        METHOD,
        inputs,
        output,
        {
            "training_policy": policy,
            "training_policy_sha256": digest(evidence.canonical(policy)),
            "max_profiles": max_profiles,
        },
        as_of.isoformat(),
        evidence.code_digest("snapshots.py", "evidence.py"),
    )
    sha = calc["sha"]
    sid = str(uuid.uuid5(uuid.NAMESPACE_URL, "training-snapshot|" + sha))
    parquet_key = f"lake/training/schema=v1/{sid}/observations.parquet"
    put_immutable(s3, parquet_key, data)
    manifest = {
        **calc["manifest"],
        "snapshot_id": sid,
        "snapshot_sha256": sha,
        "parquet_key": parquet_key,
    }
    encoded = evidence.canonical(manifest)
    manifest_key = f"lake/training/schema=v1/{sid}/manifest.json"
    put_immutable(s3, manifest_key, encoded)
    with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=5) as db:
        db.execute("SET statement_timeout='30s'; SET lock_timeout='5s'")
        evidence.record(db, calc, inputs, "frozen")
        db.execute(
            """INSERT INTO training_snapshots(snapshot_id,snapshot_sha256,calculation_id,manifest,manifest_key,manifest_sha256,parquet_key,parquet_sha256,size_bytes,profile_count,row_count)
VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(snapshot_sha256) DO NOTHING""",
            (
                sid,
                sha,
                calc["id"],
                Jsonb(manifest),
                manifest_key,
                digest(encoded),
                parquet_key,
                digest(data),
                len(data),
                len(inputs),
                len(rows),
            ),
        )
    return manifest
