"""Real coordinated local backup and isolated SQL/object restore; no live replacement."""

import json
import secrets
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix="nautiq-restore-drill-") as directory:
        root = Path(directory)
        root.chmod(0o700)
        key = root / "backup.key"
        key.write_text(secrets.token_hex(32))
        key.chmod(0o600)
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/backup.py"),
                str(root),
                "--key-file",
                str(key),
            ],
            cwd=ROOT,
            check=True,
        )
        archive = next(root.glob("*.backup"))
        suffix = uuid.uuid4().hex[:16]
        database, bucket = "restore_" + suffix, "restore-" + suffix
        command = [
            "docker",
            "compose",
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "-v",
            str(root) + ":/backup",
            "-v",
            str(key) + ":/run/secrets/backup_key:ro",
            "-e",
            "BACKUP_KEY_FILE=/run/secrets/backup_key",
            "operations-tools",
        ]
        try:
            subprocess.run(
                [
                    *command,
                    "restore",
                    "/backup/" + archive.name,
                    "--database",
                    database,
                    "--bucket",
                    bucket,
                ],
                cwd=ROOT,
                check=True,
            )
            subprocess.run(
                [
                    "docker",
                    "compose",
                    "run",
                    "--rm",
                    "--no-deps",
                    "-T",
                    "-e",
                    "RESTORE_DATABASE=" + database,
                    "--entrypoint",
                    "python",
                    "ml-inference",
                    "-m",
                    "nautiq_ml.operations.verify_rollback",
                ],
                cwd=ROOT,
                check=True,
            )
            # Reusing an existing isolated target is refused, never overwritten.
            repeat = subprocess.run(
                [
                    *command,
                    "restore",
                    "/backup/" + archive.name,
                    "--database",
                    database,
                    "--bucket",
                    bucket,
                ],
                cwd=ROOT,
                capture_output=True,
            )
            assert repeat.returncode != 0
            raw = bytearray(archive.read_bytes())
            raw[len(raw) // 2] ^= 1
            damaged = root / "damaged.backup"
            damaged.write_bytes(raw)
            refused = subprocess.run(
                [
                    *command,
                    "restore",
                    "/backup/damaged.backup",
                    "--database",
                    "restore_" + uuid.uuid4().hex[:16],
                    "--bucket",
                    "restore-" + uuid.uuid4().hex[:16],
                ],
                cwd=ROOT,
                capture_output=True,
            )
            assert refused.returncode != 0
            print(
                json.dumps(
                    {
                        "real_sql_object_backup_restore": True,
                        "authenticated_corruption_refusal": True,
                        "existing_target_refusal": True,
                        "live_database_replaced": False,
                        "public_production_approved": False,
                    }
                )
            )
        finally:
            # Delete only the uniquely named targets created by this drill.
            cleanup = "import os,psycopg; from minio import Minio; from minio.deleteobjects import DeleteObject; from psycopg import sql; "
            cleanup += (
                "db=psycopg.connect(os.environ['DATABASE_URL'],autocommit=True); db.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(sql.Identifier("
                + repr(database)
                + "))); db.close(); "
            )
            cleanup += "s=Minio(os.environ['MINIO_ENDPOINT'],access_key=os.environ['MINIO_ROOT_USER'],secret_key=os.environ['MINIO_ROOT_PASSWORD'],secure=False); "
            cleanup += "b=" + repr(bucket) + "; "
            cleanup += "\nif s.bucket_exists(b):\n list(s.remove_objects(b,(DeleteObject(o.object_name) for o in s.list_objects(b,recursive=True)))); s.remove_bucket(b)\n"
            subprocess.run(
                [
                    "docker",
                    "compose",
                    "run",
                    "--rm",
                    "--no-deps",
                    "-T",
                    "--entrypoint",
                    "/opt/ops/bin/python",
                    "operations-tools",
                    "-c",
                    cleanup,
                ],
                cwd=ROOT,
                check=True,
            )


if __name__ == "__main__":
    main()
