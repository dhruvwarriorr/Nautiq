"""Authenticated encrypted SQL/object backups; restore only to new isolated targets."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import tarfile
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from minio import Minio
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b"NAUTIQB1"
MAX_BYTES = 2 * 1024**3
MAX_OBJECTS = 50000
TABLES = (
    "platform_migrations",
    "profiles",
    "profile_revisions",
    "calculations",
    "training_snapshots",
    "climatology_releases",
    "expected_state_releases",
    "uncertainty_releases",
    "anomaly_releases",
    "field_releases",
    "event_runs",
    "product_accounts",
    "product_objects",
)


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024**2), b""):
            h.update(block)
    return h.hexdigest()


def key():
    raw = Path(os.environ["BACKUP_KEY_FILE"]).read_bytes().strip()
    if not re.fullmatch(b"[a-f0-9]{64}", raw):
        raise ValueError("backup_key_contract")
    return bytes.fromhex(raw.decode())


def crypt(source, target, decrypt=False):
    # GCM authentication is completed before decrypted bytes are used or extracted.
    with source.open("rb") as src, target.open("xb") as out:
        os.chmod(target, 0o600)
        if decrypt:
            if src.read(8) != MAGIC or source.stat().st_size > MAX_BYTES + 64:
                raise ValueError("backup_envelope_contract")
            nonce = src.read(12)
            src.seek(-16, 2)
            tag = src.read(16)
            src.seek(20)
            engine = Cipher(algorithms.AES(key()), modes.GCM(nonce, tag)).decryptor()
            remaining = source.stat().st_size - 36
        else:
            nonce = os.urandom(12)
            out.write(MAGIC + nonce)
            engine = Cipher(algorithms.AES(key()), modes.GCM(nonce)).encryptor()
            remaining = source.stat().st_size
        engine.authenticate_additional_data(MAGIC)
        while remaining > 0:
            block = src.read(min(1024**2, remaining))
            if not block:
                raise ValueError("truncated_backup")
            out.write(engine.update(block))
            remaining -= len(block)
        out.write(engine.finalize())
        if not decrypt:
            out.write(engine.tag)


def storage():
    return Minio(
        os.environ["MINIO_ENDPOINT"],
        access_key=os.environ["MINIO_ROOT_USER"],
        secret_key=os.environ["MINIO_ROOT_PASSWORD"],
        secure=os.getenv("MINIO_SECURE") == "true",
    )


def inventory(s3, bucket):
    result = []
    total = 0
    for obj in s3.list_objects(bucket, recursive=True):
        total += obj.size
        if len(result) >= MAX_OBJECTS or total > MAX_BYTES:
            raise ValueError("backup_object_budget")
        result.append({"key": obj.object_name, "size": obj.size, "etag": obj.etag})
    return sorted(result, key=lambda obj: obj["key"])


def pg(command, database, *args):
    config = conninfo_to_dict(os.environ["DATABASE_URL"])
    env = dict(os.environ)
    for name, option in (
        ("PGHOST", "host"),
        ("PGPORT", "port"),
        ("PGUSER", "user"),
        ("PGPASSWORD", "password"),
        ("PGSSLMODE", "sslmode"),
    ):
        if option in config:
            env[name] = config[option]
    env["PGDATABASE"] = database
    result = subprocess.run(
        [
            command,
            *(["--dbname=" + database] if command == "pg_restore" else []),
            *args,
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=300,
    )
    if result.returncode:
        raise ValueError("database_archive_command_failed")


def metadata(db):
    counts = {}
    for table in TABLES:
        counts[table] = db.execute(
            sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
        ).fetchone()[0]
    migrations = db.execute(
        "SELECT version,sha256 FROM platform_migrations ORDER BY version"
    ).fetchall()
    return {"counts": counts, "migrations": migrations}


def create(destination, quiesced):
    if not quiesced or destination.exists():
        raise ValueError("backup_requires_quiesced_writers_and_new_path")
    s3 = storage()
    bucket = "nautiq"
    with tempfile.TemporaryDirectory(
        prefix="nautiq-backup-", dir=destination.parent
    ) as temporary:
        root = Path(temporary)
        with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as db:
            db.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
            snapshot = db.execute("SELECT pg_export_snapshot()").fetchone()[0]
            database = db.execute("SELECT current_database()").fetchone()[0]
            meta = metadata(db)
            items = inventory(s3, bucket)
            dump = root / "database.dump"
            pg(
                "pg_dump",
                database,
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                "--snapshot=" + snapshot,
                "--file=" + str(dump),
            )
            objects = []
            total = dump.stat().st_size
            (root / "objects").mkdir()
            for index, obj in enumerate(items):
                member = f"objects/{index:08d}"
                path = root / member
                response = s3.get_object(bucket, obj["key"])
                try:
                    with path.open("xb") as file:
                        copied = 0
                        for block in iter(lambda: response.read(1024**2), b""):
                            copied += len(block)
                            total += len(block)
                            if total > MAX_BYTES - 32 * 1024**2 or copied > obj["size"]:
                                raise ValueError("backup_byte_budget")
                            file.write(block)
                finally:
                    response.close()
                    response.release_conn()
                if copied != obj["size"]:
                    raise ValueError("backup_object_changed")
                objects.append(
                    {
                        "member": member,
                        "key": obj["key"],
                        "bytes": copied,
                        "sha256": sha(path),
                    }
                )
            if items != inventory(s3, bucket):
                raise ValueError("backup_inventory_changed")
            manifest = {
                "schema": 1,
                "as_of": datetime.now(timezone.utc).isoformat(),
                "source_database": database,
                "source_bucket": bucket,
                "coordination": "writers quiesced; repeatable-read SQL snapshot and stable verified object inventory",
                "database_sha256": sha(dump),
                "database_bytes": dump.stat().st_size,
                "objects": objects,
                "sql": meta,
            }
            (root / "manifest.json").write_text(json.dumps(manifest, sort_keys=True))
            db.execute("ROLLBACK")
        archive = root / "archive.tar"
        with tarfile.open(archive, "w") as tar:
            for member in ["manifest.json", "database.dump"] + [
                obj["member"] for obj in objects
            ]:
                tar.add(root / member, arcname=member, recursive=False)
        if archive.stat().st_size > MAX_BYTES:
            raise ValueError("backup_archive_budget")
        try:
            crypt(archive, destination)
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
    print(
        json.dumps(
            {
                "backup_created": True,
                "objects": len(objects),
                "encrypted_bytes": destination.stat().st_size,
                "sha256": sha(destination),
                "production_approved": False,
            }
        )
    )


def restore(archive, database, bucket):
    if not re.fullmatch(r"restore_[a-z0-9_]{8,40}", database) or not re.fullmatch(
        r"restore-[a-z0-9-]{8,40}", bucket
    ):
        raise ValueError("isolated_restore_target_required")
    s3 = storage()
    with tempfile.TemporaryDirectory(
        prefix="nautiq-restore-", dir=archive.parent
    ) as temporary:
        root = Path(temporary)
        plain = root / "archive.tar"
        crypt(archive, plain, decrypt=True)
        with tarfile.open(plain) as tar:
            members = []
            member_bytes = 0
            for item in tar:
                members.append(item)
                member_bytes += item.size
                if len(members) > MAX_OBJECTS + 2 or member_bytes > MAX_BYTES:
                    raise ValueError("restore_archive_budget")
            if (
                len(members) > MAX_OBJECTS + 2
                or sum(item.size for item in members) > MAX_BYTES
            ):
                raise ValueError("restore_archive_budget")
            names = [item.name for item in members]
            if len(set(names)) != len(names) or any(
                not item.isfile()
                or not re.fullmatch(
                    r"manifest.json|database.dump|objects/[0-9]{8}", item.name
                )
                for item in members
            ):
                raise ValueError("restore_archive_members")
            # Extract only the already validated regular-file names. Avoid archive
            # permissions/links and Python-version-dependent extraction filters.
            (root / "objects").mkdir()
            for item in members:
                with (
                    tar.extractfile(item) as source,
                    (root / item.name).open("xb") as target,
                ):
                    for block in iter(lambda: source.read(1024**2), b""):
                        target.write(block)
        manifest = json.loads((root / "manifest.json").read_text())
        objects = manifest["objects"]
        if (
            manifest["schema"] != 1
            or database == manifest["source_database"]
            or bucket == manifest["source_bucket"]
            or len(objects) > MAX_OBJECTS
        ):
            raise ValueError("restore_manifest_contract")
        if set(names) != {
            "manifest.json",
            "database.dump",
            *[obj["member"] for obj in objects],
        } or len({obj["key"] for obj in objects}) != len(objects):
            raise ValueError("restore_manifest_members")
        for obj in objects + [
            {
                "member": "database.dump",
                "bytes": manifest["database_bytes"],
                "sha256": manifest["database_sha256"],
            }
        ]:
            path = root / obj["member"]
            if path.stat().st_size != obj["bytes"] or sha(path) != obj["sha256"]:
                raise ValueError("restore_checksum_refused")
        with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as admin:
            if admin.execute(
                "SELECT 1 FROM pg_database WHERE datname=%s", (database,)
            ).fetchone() or s3.bucket_exists(bucket):
                raise ValueError("restore_target_exists")
            admin.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(
                    sql.Identifier(database)
                )
            )
        config = conninfo_to_dict(os.environ["DATABASE_URL"])
        config["dbname"] = database
        with psycopg.connect(**config, autocommit=True) as db:
            db.execute("CREATE EXTENSION timescaledb")
            db.execute("SELECT timescaledb_pre_restore()")
        pg(
            "pg_restore",
            database,
            "--exit-on-error",
            "--no-owner",
            "--no-privileges",
            str(root / "database.dump"),
        )
        with psycopg.connect(**config, autocommit=True) as db:
            db.execute("SELECT timescaledb_post_restore()")
            # --no-privileges intentionally omits ACL restoration. Prevent the
            # restored SECURITY DEFINER helper's default PUBLIC execute grant.
            if db.execute(
                "SELECT to_regprocedure('public.operations_lock_release(text,uuid)') IS NOT NULL"
            ).fetchone()[0]:
                db.execute(
                    "REVOKE ALL ON FUNCTION public.operations_lock_release(text,uuid) FROM PUBLIC"
                )
            restored = metadata(db)
            expected = manifest["sql"]
            if (
                restored["counts"] != expected["counts"]
                or [list(row) for row in restored["migrations"]]
                != expected["migrations"]
            ):
                raise ValueError("restore_sql_contract")
            db.execute(
                "UPDATE operations_controls SET paused=jsonb_build_object('science',true,'product_writes',true),revision=revision+1,updated_at=now() WHERE singleton"
            )
            db.execute(
                "DELETE FROM product_sessions; DELETE FROM product_download_grants"
            )
        s3.make_bucket(bucket)
        for obj in objects:
            s3.fput_object(bucket, obj["key"], str(root / obj["member"]))
            response = s3.get_object(bucket, obj["key"])
            try:
                h = hashlib.sha256()
                for block in iter(lambda: response.read(1024**2), b""):
                    h.update(block)
                if h.hexdigest() != obj["sha256"]:
                    raise ValueError("restore_uploaded_integrity")
            finally:
                response.close()
                response.release_conn()
        with psycopg.connect(**config, autocommit=True) as db:
            db.execute(
                "INSERT INTO operations_audit(audit_id,action,scope,reason,actor,before_state,after_state) VALUES(%s,'restore_completed','science','restore_drill','backup_tool','{}',%s::jsonb)",
                (
                    uuid.uuid4(),
                    json.dumps({"paused": True, "objects_verified": len(objects)}),
                ),
            )
    print(
        json.dumps(
            {
                "isolated_restore": True,
                "sql_counts_and_migrations_matched": True,
                "objects_verified": len(objects),
                "sessions_revoked": True,
                "serving_paused": True,
                "production_approved": False,
            }
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    create_cmd = sub.add_parser("create")
    create_cmd.add_argument("destination", type=Path)
    create_cmd.add_argument("--writers-quiesced", action="store_true")
    restore_cmd = sub.add_parser("restore")
    restore_cmd.add_argument("archive", type=Path)
    restore_cmd.add_argument("--database", required=True)
    restore_cmd.add_argument("--bucket", required=True)
    args = parser.parse_args()
    if args.action == "create":
        create(args.destination, args.writers_quiesced)
    else:
        restore(args.archive, args.database, args.bucket)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Emit only a type and fixed, code-owned failure label; never SQL/DSN/object text.
        label = (
            str(error)
            if isinstance(error, ValueError)
            and re.fullmatch(r"[a-z_]{1,80}", str(error))
            else type(error).__name__
        )
        raise SystemExit(
            "Backup/restore refused: "
            + label
            + "; private details suppressed. Check the isolated target and operator runbook."
        ) from None
