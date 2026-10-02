"""Bounded immutable object operations shared by ingestion science tools."""

import hashlib
import io
import os

import urllib3
from minio import Minio
from minio.error import S3Error

from .parser import InvalidProfile

MAX_BYTES = 64 * 1024 * 1024


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
    if not 0 < len(data) <= 128 * 1024 * 1024:
        raise InvalidProfile("immutable_object_budget")
    try:
        info = s3.stat_object("nautiuq", key)
        if info.size != len(data) or info.metadata.get("x-amz-meta-sha256") != digest(
            data
        ):
            raise InvalidProfile("immutable_lake_conflict")
        read_object(s3, key, digest(data), limit=len(data))
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
        read_object(s3, key, digest(data), limit=len(data))
