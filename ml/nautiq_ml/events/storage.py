"""Content-pinned daily history and seasonal arrays; safe, bounded NPZ artifacts."""

import io
import json
import sys
import uuid
import zipfile
from pathlib import Path

import numpy as np
from psycopg.types.json import Jsonb

from ..argo.storage import digest, put_immutable, read_object
from ..fields.core import canonical
from .core import POLICY, METHOD, EventError, axes, daily


def identifier(value):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "nautiq:events:" + value))


def code_hash():
    root = Path(__file__).parent
    shared = [
        root.parent / p
        for p in (
            "fields/core.py",
            "fields/providers.py",
            "argo/storage.py",
            "phase0/acquire.py",
        )
    ]
    return digest(
        b"".join(
            str(p.relative_to(root.parent)).encode() + p.read_bytes()
            for p in sorted([*root.glob("*.py"), *shared])
        )
    )


def runtime():
    import importlib.metadata

    return {
        "python": sys.version.split()[0],
        "libraries": {
            n: importlib.metadata.version(n)
            for n in ("numpy", "netCDF4", "shapely", "psycopg", "minio")
        },
        "requirements_sha256": digest(
            next(
                p
                for p in (
                    Path("/app/requirements-fields.lock"),
                    Path(__file__).parents[2] / "requirements-fields.lock",
                )
                if p.exists()
            ).read_bytes()
        ),
    }


def pack(arrays):
    buffer = io.BytesIO()
    np.savez_compressed(buffer, **{k: arrays[k] for k in sorted(arrays)})
    data = buffer.getvalue()
    if not 0 < len(data) <= POLICY["limits"]["report_bytes"]:
        raise EventError("compressed_array_budget")
    return data


def unpack(data, expected):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        files = archive.infolist()
        if (
            set(f.filename for f in files) != {k + ".npy" for k in expected}
            or len(files) != len(expected)
            or sum(f.file_size for f in files) > POLICY["limits"]["array_bytes"]
        ):
            raise EventError("expanded_array_budget_or_keys")
    with np.load(io.BytesIO(data), allow_pickle=False) as source:
        arrays = {k: source[k] for k in expected}
    if any(v.dtype.kind not in "fi" or np.isinf(v).any() for v in arrays.values()):
        raise EventError("unsafe_event_arrays")
    return arrays


def calculation(db, s3, kind, inputs, output):
    manifest = {
        "schema_version": 1,
        "kind": kind,
        "method_version": METHOD,
        "input": inputs,
        "output": output,
        "policy": POLICY,
        "code_sha256": code_hash(),
        "runtime": runtime(),
    }
    sha = digest(canonical(manifest))
    cid = identifier(sha)
    key = "events/calculations/" + sha + ".json"
    put_immutable(s3, key, canonical(manifest))
    db.execute(
        "INSERT INTO calculations(calculation_id,calculation_sha256,kind,method_version,manifest,manifest_key,manifest_sha256,state) VALUES(%s,%s,%s,%s,%s,%s,%s,'frozen') ON CONFLICT(calculation_sha256) DO NOTHING",
        (cid, sha, kind, METHOD, Jsonb(manifest), key, sha),
    )
    return cid


def verify_calculation(db, s3, cid, kind, output):
    row = db.execute(
        "SELECT * FROM calculations WHERE calculation_id=%s", (cid,)
    ).fetchone()
    if not row or row["kind"] != kind:
        raise EventError("event_calculation_missing")
    data = read_object(
        s3,
        row["manifest_key"],
        row["manifest_sha256"],
        POLICY["limits"]["report_bytes"],
    )
    manifest = json.loads(data)
    if (
        canonical(manifest) != canonical(row["manifest"])
        or digest(data) != row["calculation_sha256"]
        or canonical(manifest["output"]) != canonical(output)
    ):
        raise EventError("event_calculation_mismatch")
    return manifest


def validate_arrays(kind, arrays, metadata):
    axes(arrays["lat"], arrays["lon"])
    if kind == "history":
        a = daily(
            arrays["sst"],
            metadata["dates"],
            arrays["lat"],
            arrays["lon"],
            POLICY["limits"]["history_days"],
        )
        if metadata["shape"] != list(a.shape) or metadata["missing_cells"] != int(
            np.isnan(a).sum()
        ):
            raise EventError("history_metadata_mismatch")
    elif kind == "baseline":
        shape = (366, len(arrays["lat"]), len(arrays["lon"]))
        if (
            any(
                arrays[n].shape != shape
                for n in ("mean", "threshold", "count", "years")
            )
            or metadata["shape"] != list(shape)
            or metadata["baseline_years"] != POLICY["baseline_years"]
        ):
            raise EventError("invalid_seasonal_bundle")
        valid = np.isfinite(arrays["threshold"])
        if not np.array_equal(valid, np.isfinite(arrays["mean"])) or metadata[
            "supported_seasonal_cells"
        ] != int(valid.sum()):
            raise EventError("invalid_baseline_mask")
        for n in ("count", "years"):
            if arrays[n].dtype.kind not in "iu" or (arrays[n] < 0).any():
                raise EventError("invalid_baseline_support")
        if (
            (arrays["years"] > 30).any()
            or (arrays["count"] > 330).any()
            or (arrays["years"][valid] < POLICY["min_baseline_years"]).any()
        ):
            raise EventError("invalid_baseline_support")
        for n in ("mean", "threshold"):
            if (
                np.isinf(arrays[n]).any()
                or ((arrays[n][valid] < -3) | (arrays[n][valid] > 45)).any()
            ):
                raise EventError("invalid_baseline_temperature")
    else:
        raise EventError("invalid_event_dataset_kind")


def publish_dataset(db, s3, kind, arrays, metadata, parent_id=None, before_commit=None):
    validate_arrays(kind, arrays, metadata)
    data = pack(arrays)
    identity = {
        "kind": kind,
        "parent_id": parent_id,
        "metadata": metadata,
        "arrays_sha256": digest(data),
        "policy_sha256": digest(canonical(POLICY)),
        "code_sha256": code_hash(),
        "runtime": runtime(),
    }
    sha = digest(canonical(identity))
    did = identifier(sha)
    key = "events/datasets/" + sha + "/arrays.npz"
    manifest = {
        **identity,
        "dataset_id": did,
        "dataset_sha256": sha,
        "arrays_key": key,
        "arrays_bytes": len(data),
    }
    mdata = canonical(manifest)
    mkey = "events/datasets/" + sha + "/manifest.json"
    put_immutable(s3, key, data)
    put_immutable(s3, mkey, mdata)
    with db.transaction():
        cid = calculation(
            db,
            s3,
            "event_" + kind,
            {"parent_id": parent_id, "raw": metadata.get("raw", [])},
            {"dataset_id": did, "manifest_sha256": digest(mdata)},
        )
        db.execute(
            "INSERT INTO event_datasets(dataset_id,dataset_sha256,kind,parent_id,calculation_id,manifest,manifest_key,manifest_sha256) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(dataset_sha256) DO NOTHING",
            (did, sha, kind, parent_id, cid, Jsonb(manifest), mkey, digest(mdata)),
        )
        prior = db.execute(
            "SELECT manifest FROM event_datasets WHERE dataset_id=%s", (did,)
        ).fetchone()
        if canonical(prior["manifest"]) != mdata:
            raise EventError("immutable_dataset_conflict")
        if before_commit:
            before_commit()
    return {
        "dataset_id": did,
        "kind": kind,
        "calculation_id": cid,
        "manifest": manifest,
    }


def load_dataset(db, s3, did, raw=False):
    row = db.execute(
        "SELECT * FROM event_datasets WHERE dataset_id=%s", (did,)
    ).fetchone()
    if not row:
        raise EventError("event_dataset_not_found")
    manifest = json.loads(
        read_object(s3, row["manifest_key"], row["manifest_sha256"], 1024 * 1024)
    )
    identity = {
        k: v
        for k, v in manifest.items()
        if k not in ("dataset_id", "dataset_sha256", "arrays_key", "arrays_bytes")
    }
    sha = digest(canonical(identity))
    if (
        canonical(manifest) != canonical(row["manifest"])
        or sha != row["dataset_sha256"]
        or manifest["dataset_sha256"] != sha
        or manifest["kind"] != row["kind"]
        or manifest["parent_id"]
        != (str(row["parent_id"]) if row["parent_id"] else None)
        or manifest["dataset_id"] != str(row["dataset_id"])
        or manifest["arrays_key"] != "events/datasets/" + sha + "/arrays.npz"
    ):
        raise EventError("dataset_manifest_mismatch")
    data = read_object(
        s3, manifest["arrays_key"], manifest["arrays_sha256"], manifest["arrays_bytes"]
    )
    names = (
        ("lat", "lon", "sst")
        if row["kind"] == "history"
        else ("lat", "lon", "mean", "threshold", "count", "years")
    )
    arrays = unpack(data, names)
    meta = manifest["metadata"]
    validate_arrays(row["kind"], arrays, meta)
    verify_calculation(
        db,
        s3,
        row["calculation_id"],
        "event_" + row["kind"],
        {
            "dataset_id": str(row["dataset_id"]),
            "manifest_sha256": row["manifest_sha256"],
        },
    )
    if raw:
        for r in meta.get("raw", []):
            read_object(s3, r["raw_key"], r["sha256"], r["bytes"])
        if row["parent_id"]:
            parent, source = load_dataset(db, s3, row["parent_id"], raw=True)
            if (
                parent["kind"] != "history"
                or parent["manifest"]["metadata"]["dates"][0] != "1982-01-01"
                or parent["manifest"]["metadata"]["dates"][-1] != "2011-12-31"
                or not np.array_equal(source["lat"], arrays["lat"])
                or not np.array_equal(source["lon"], arrays["lon"])
            ):
                raise EventError("baseline_parent_mismatch")
    return row, arrays
