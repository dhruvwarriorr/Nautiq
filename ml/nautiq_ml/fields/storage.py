"""Stage a real chunked Zarr store; publish SQL only after verified immutable bytes."""

import hashlib
import importlib.metadata
import os
import re
import sys
from collections.abc import MutableMapping
from pathlib import Path

import numcodecs
import zarr

from ..argo.storage import digest, put_immutable, read_object
from .core import FieldError, POLICY, canonical


def code_hash():
    h = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        h.update(path.name.encode())
        h.update(path.read_bytes())
    h.update(canonical(POLICY))
    return h.hexdigest()


def stage(s3, lat, lon, times, arrays, metadata, receipts, source_version):
    memory = zarr.storage.MemoryStore()
    group = zarr.group(store=memory)
    for name, data in (("latitude", lat), ("longitude", lon), ("time", times)):
        group.create_dataset(name, data=data, chunks=(len(data),), compressor=None)
    for name, data in sorted(arrays.items()):
        group.create_dataset(
            name,
            data=data,
            chunks=(1, 64, 64),
            fill_value=float("nan"),
            compressor=numcodecs.Zstd(level=3),
        )
    group.attrs.update({"metadata": metadata})
    zarr.consolidate_metadata(memory)
    files = {
        key: {"sha256": digest(bytes(memory[key])), "bytes": len(memory[key])}
        for key in sorted(memory)
    }
    if (
        len(files) > POLICY["limits"]["objects"]
        or sum(f["bytes"] for f in files.values())
        > POLICY["limits"]["normalized_bytes"]
    ):
        raise FieldError("normalized_object_budget")
    fingerprint = {
        "metadata": metadata,
        "files": files,
        "raw": receipts,
        "source_version": source_version,
        "policy_sha256": digest(canonical(POLICY)),
        "code_sha256": code_hash(),
        "runtime": {
            "python": sys.version.split()[0],
            "libraries": {
                name: importlib.metadata.version(name)
                for name in (
                    "numpy",
                    "netCDF4",
                    "eccodes",
                    "eccodeslib",
                    "zarr",
                    "numcodecs",
                    "pillow",
                    "shapely",
                    "minio",
                    "psycopg",
                    "grpcio",
                    "protobuf",
                )
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
        },
        "source_git_commit": os.environ.get("SOURCE_GIT_COMMIT", "unavailable"),
    }
    sha = digest(canonical(fingerprint))
    prefix = f"fields/{metadata['product_id']}/{sha}/data.zarr/"
    for key in files:
        put_immutable(s3, prefix + key, bytes(memory[key]))
    manifest = {**fingerprint, "release_sha256": sha, "zarr_prefix": prefix}
    data = canonical(manifest)
    key = f"fields/{metadata['product_id']}/{sha}/manifest.json"
    put_immutable(s3, key, data)
    return manifest, key, digest(data)


class VerifiedStore(MutableMapping):
    def __init__(self, s3, manifest, full=False):
        self.s3, self.prefix, self.files = (
            s3,
            manifest["zarr_prefix"],
            manifest["files"],
        )
        self.cache, self.bytes = {}, 0
        self.byte_limit = (
            POLICY["limits"]["normalized_bytes"] if full else 32 * 1024 * 1024
        )
        if (
            len(self.files) > POLICY["limits"]["objects"]
            or sum(f["bytes"] for f in self.files.values())
            > POLICY["limits"]["normalized_bytes"]
        ):
            raise FieldError("normalized_object_budget")
        for key, item in self.files.items():
            if (
                not re.fullmatch(
                    r"(?:\.z(?:group|attrs|metadata)|[a-z_]+/(?:\.zarray|\.zattrs|[0-9.]+))",
                    key,
                )
                or not 0 < item["bytes"] <= 1048576
                or not re.fullmatch("[a-f0-9]{64}", item["sha256"])
            ):
                raise FieldError("invalid_zarr_manifest")

    def __getitem__(self, key):
        if key not in self.files:
            raise KeyError(key)
        if key not in self.cache:
            item = self.files[key]
            data = read_object(
                self.s3, self.prefix + key, item["sha256"], limit=item["bytes"]
            )
            if len(data) != item["bytes"]:
                raise FieldError("chunk_size_mismatch")
            self.bytes += len(data)
            if self.bytes > self.byte_limit:
                raise FieldError("query_chunk_budget")
            self.cache[key] = data
        return self.cache[key]

    def __setitem__(self, key, value):
        raise FieldError("read_only_store")

    def __delitem__(self, key):
        raise FieldError("read_only_store")

    def __iter__(self):
        return iter(self.files)

    def __len__(self):
        return len(self.files)


def open_grid(s3, row, full=False):
    import json

    manifest = json.loads(
        read_object(s3, row["manifest_key"], row["manifest_sha256"], limit=1024 * 1024)
    )
    if (
        canonical(manifest) != canonical(row["manifest"])
        or manifest["release_sha256"] != row["release_sha256"]
    ):
        raise FieldError("catalog_manifest_mismatch")
    fingerprint = {
        k: v for k, v in manifest.items() if k not in ("release_sha256", "zarr_prefix")
    }
    expected_prefix = (
        f"fields/{row['product_id']}/{digest(canonical(fingerprint))}/data.zarr/"
    )
    if (
        manifest["zarr_prefix"] != expected_prefix
        or digest(canonical(fingerprint)) != row["release_sha256"]
    ):
        raise FieldError("release_fingerprint_mismatch")
    metadata = manifest["metadata"]
    if (
        metadata["product_id"] != row["product_id"]
        or metadata["normalizer_version"] != POLICY["normalizer"]
        or manifest["policy_sha256"] != digest(canonical(POLICY))
    ):
        raise FieldError("incompatible_field_policy")
    store = VerifiedStore(s3, manifest, full=full)
    group = zarr.open_consolidated(store=store, mode="r")
    if canonical(dict(group.attrs)["metadata"]) != canonical(metadata):
        raise FieldError("zarr_metadata_mismatch")
    if set(group.array_keys()) != set(metadata["variables"]) | {
        "latitude",
        "longitude",
        "time",
    }:
        raise FieldError("zarr_variable_mismatch")
    shape = tuple(metadata["shape"])
    if (
        len(shape) != 3
        or any(not isinstance(n, int) or n < 1 for n in shape)
        or shape[0] > 25
        or shape[1] > 2000
        or shape[2] > 2000
        or shape[0] * shape[1] * shape[2] * len(metadata["variables"])
        > POLICY["limits"]["cells"]
    ):
        raise FieldError("zarr_shape_budget")
    for name in metadata["variables"]:
        a = group[name]
        if (
            a.shape != shape
            or a.chunks != (1, 64, 64)
            or str(a.dtype) != "float32"
            or a.compressor != numcodecs.Zstd(level=3)
        ):
            raise FieldError("zarr_array_contract")
    for i, name in enumerate(("time", "latitude", "longitude")):
        if (
            group[name].shape != (shape[i],)
            or group[name].chunks != (shape[i],)
            or str(group[name].dtype) != "float64"
            or group[name].compressor is not None
        ):
            raise FieldError("zarr_coordinate_contract")
    if full:
        # Full verification is separately bounded and streams objects; it does not retain every chunk.
        for key, item in manifest["files"].items():
            if (
                len(
                    read_object(
                        s3, manifest["zarr_prefix"] + key, item["sha256"], item["bytes"]
                    )
                )
                != item["bytes"]
            ):
                raise FieldError("chunk_size_mismatch")
    return group, metadata
