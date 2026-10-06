"""Disposable HTTPS deployment/role/IAM acceptance; never switch the live project."""

import json
import os
import secrets
import socket
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    project = "nautiqverify14" + uuid.uuid4().hex[:10]
    with tempfile.TemporaryDirectory(prefix="nautiq-production-") as directory:
        root = Path(directory)
        root.chmod(0o700)
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            port = server.getsockname()[1]
        env = {
            **os.environ,
            "PUBLIC_HOST": "localhost",
            "PUBLIC_DOMAIN": "localhost:" + str(port),
            "HTTPS_PORT": str(port),
            "NAUTIQ_SECRETS_DIR": str(root),
            "POSTGRES_USER": "nautiqadmin",
            "POSTGRES_DB": "nautiq",
        }
        image_override = root / "images.json"
        image_override.write_text(
            json.dumps(
                {
                    "services": {
                        name: {"image": "nautiq-" + name + ":latest"}
                        for name in (
                            "api",
                            "web",
                            "ml-inference",
                            "field-service",
                            "minio",
                            "storage-init",
                            "operations-tools",
                        )
                    }
                }
            )
        )
        command = [
            "docker",
            "compose",
            "-p",
            project,
            "-f",
            str(ROOT / "docker-compose.yml"),
            "-f",
            str(ROOT / "docker-compose.production.yml"),
            "-f",
            str(image_override),
        ]

        def compose(*args, check=True, input=None):
            result = subprocess.run(
                [*command, *args],
                env=env,
                cwd=ROOT,
                text=True,
                input=input,
                capture_output=True,
            )
            if check and result.returncode:
                raise AssertionError(
                    "Disposable deployment command refused: "
                    + args[0]
                    + "; details suppressed; "
                    + " ".join(
                        line
                        for line in result.stdout.splitlines()
                        if line.startswith("privilege_fixture_")
                    )
                )
            return result

        def write(name, value):
            path = root / name
            path.write_text(value)
            path.chmod(0o644)

        write("database_password", secrets.token_hex(32))
        write("storage_root_user", "root_" + uuid.uuid4().hex[:16])
        write("storage_root_password", secrets.token_hex(32))
        root_dsn = (
            "postgresql://nautiqadmin:"
            + (root / "database_password").read_text()
            + "@postgres:5432/nautiq?sslmode=disable"
        )
        for name in ("app_database_url", "worker_database_url", "backup_database_url"):
            write(name, root_dsn)
        for name in ("storage_app_user", "storage_worker_user"):
            write(name, "placeholder")
        for name in ("storage_app_password", "storage_worker_password"):
            write(name, secrets.token_hex(32))
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost",
                "-keyout",
                str(root / "tls_key"),
                "-out",
                str(root / "tls_cert"),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        (root / "tls_key").chmod(0o644)
        try:
            compose(
                "up",
                "-d",
                "--wait",
                "postgres",
                "redis",
                "nats",
                "minio",
                "storage-init",
            )
            from migrate import migration_sql

            compose(
                "exec",
                "-T",
                "postgres",
                "sh",
                "-ec",
                'psql -X -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1',
                input=migration_sql(ROOT / "migrations"),
            )
            # Provision in this project's fresh DB/bucket. No live roles or objects are modified.
            output = root / "generated"
            compose(
                "run",
                "--rm",
                "--no-deps",
                "-T",
                "-v",
                str(root) + ":/secure",
                "--entrypoint",
                "/opt/ops/bin/python",
                "operations-tools",
                "-m",
                "nautiq_ml.operations.provision",
                "/secure/generated",
            )
            for item in output.iterdir():
                write(item.name, item.read_text())
            # Exercise actual SQL and object-store privileges in this isolated project.
            privileges = """
import io, os, uuid, psycopg
import nautiq_ml
from pathlib import Path
from minio import Minio
from minio.error import S3Error
from psycopg.errors import InsufficientPrivilege
with psycopg.connect(os.environ['DATABASE_URL'], autocommit=True) as db:
 db.execute('SET ROLE nautiq_app')
 assert not db.execute("SELECT has_table_privilege(current_user,'calculations','UPDATE')").fetchone()[0]
 assert not db.execute("SELECT has_table_privilege(current_user,'operations_audit','UPDATE')").fetchone()[0]
 db.execute('RESET ROLE')
 db.execute('SET ROLE nautiq_operator')
 db.execute('SELECT operations_lock_release(%s,%s)', ('climatology',uuid.uuid4()))
 try:
  db.execute("UPDATE climatology_releases SET status='ready'")
 except InsufficientPrivilege:
  pass
 else:
  raise AssertionError('Operator could edit immutable releases')
 db.execute('RESET ROLE')
for scope in ('app','worker'):
 stage='storage_'+scope
 user=Path('/secure/storage_'+scope+'_user').read_text().strip()
 password=Path('/secure/storage_'+scope+'_password').read_text().strip()
 client=Minio('minio:9000',access_key=user,secret_key=password,secure=False)
 client.put_object('nautiq','trips/private/privilege_fixture',io.BytesIO(b'fixture'),7)
 if scope=='app':
  try:
   client.put_object('nautiq','fields/privilege_fixture',io.BytesIO(b'fixture'),7)
  except S3Error as error:
   assert error.code=='AccessDenied'
  else:
   raise AssertionError('App could publish scientific objects')
 else:
  client.put_object('nautiq','fields/privilege_fixture',io.BytesIO(b'fixture'),7)
  try:
   client.remove_object('nautiq','fields/privilege_fixture')
  except S3Error as error:
   assert error.code=='AccessDenied'
  else:
   raise AssertionError('Worker could erase retained scientific objects')
print('Restricted SQL, operator row lock and object-store IAM checks passed.')
"""
            privileges = (
                'stage="sql"\ntry:\n'
                + "\n".join(" " + line for line in privileges.splitlines())
                + '\nexcept Exception as error:\n print("privilege_fixture_refused",stage,type(error).__name__)\n raise SystemExit(1)\n'
            )
            compose(
                "run",
                "--rm",
                "--no-deps",
                "-T",
                "-v",
                str(root) + ":/secure:ro",
                "--entrypoint",
                "/opt/ops/bin/python",
                "operations-tools",
                "-c",
                privileges,
            )
            compose(
                "up",
                "-d",
                "--no-build",
                "api",
                "web",
                "ml-inference",
                "field-service",
                "gateway",
            )
            context = ssl.create_default_context(cafile=str(root / "tls_cert"))
            origin = "https://localhost:" + str(port)

            def call(path, method="GET", body=None, headers=None):
                values = {"Origin": origin, **(headers or {})}
                raw = json.dumps(body).encode() if body is not None else None
                if raw is not None:
                    values["Content-Type"] = "application/json"
                request = urllib.request.Request(
                    origin + path, data=raw, method=method, headers=values
                )
                return urllib.request.urlopen(request, context=context, timeout=12)

            deadline = time.monotonic() + 90
            while True:
                try:
                    with call("/health/live") as response:
                        assert response.status == 200
                    break
                except (OSError, urllib.error.URLError) as error:
                    if time.monotonic() > deadline:
                        raise AssertionError(
                            "Disposable HTTPS gateway did not become ready; last error type="
                            + type(error).__name__
                        ) from None
                    time.sleep(2)
            for path in ("/internal/metrics", "/api/v1/health"):
                try:
                    call(path)
                    raise AssertionError(
                        "Private backend endpoint routed through gateway"
                    )
                except urllib.error.HTTPError as error:
                    assert error.code == 404
            password = "Synthetic-HTTPS-fixture-" + uuid.uuid4().hex
            with call(
                "/api/product/auth/register",
                "POST",
                {"handle": "verify14_https", "password": password},
            ) as response:
                data = json.load(response)
                cookie = response.headers.get("Set-Cookie", "")
                assert (
                    "__Host-nautiq_session=" in cookie
                    and "Secure" in cookie
                    and "HttpOnly" in cookie
                    and "SameSite=lax" in cookie
                )
                assert "session_token" not in data
            with call(
                "/api/product/auth/session", headers={"Cookie": cookie.split(";", 1)[0]}
            ) as response:
                session = json.load(response)
            with call(
                "/api/product/account",
                "DELETE",
                {"password": password},
                {
                    "Cookie": cookie.split(";", 1)[0],
                    "X-CSRF-Token": session["csrf_token"],
                    "If-Match": '"' + str(session["version"]) + '"',
                    "Idempotency-Key": str(uuid.uuid4()),
                },
            ) as response:
                assert response.status == 200
            with call("/status") as response:
                assert (
                    response.headers.get("Strict-Transport-Security")
                    == "max-age=31536000"
                )
                assert response.headers.get("X-Frame-Options") == "DENY"
                assert response.headers.get("Content-Security-Policy")
                page = response.read().decode()
                assert (
                    "Source health" in page
                    and "Public production and scientific approval remain unavailable"
                    in page
                )
            # Restricted role cannot mutate controls; operator uses separate credentials.
            operator_file = root / "operator_database_url"
            result = compose(
                "exec",
                "-T",
                "api",
                "/operations",
                "--action",
                "pause",
                "--scope",
                "science",
                "--reason",
                "permission_fixture",
                "--actor",
                "verifier",
                "--revision",
                "1",
                check=False,
            )
            assert result.returncode != 0
            compose(
                "run",
                "--rm",
                "--no-deps",
                "-T",
                "-v",
                str(operator_file) + ":/run/secrets/operator_database_url:ro",
                "-e",
                "DATABASE_URL_FILE=/run/secrets/operator_database_url",
                "--entrypoint",
                "/operations",
                "api",
                "--action",
                "pause",
                "--scope",
                "science",
                "--reason",
                "permission_fixture",
                "--actor",
                "verifier",
                "--revision",
                "1",
            )
            # Backup the provisioned schema too: RLS role references and restricted
            # SECURITY DEFINER ACLs must survive a paused isolated restore.
            compose("stop", "--timeout", "15", "api", "ml-inference")
            write("restore_key", secrets.token_hex(32))
            backup_command = (
                "run",
                "--rm",
                "--no-deps",
                "-T",
                "-v",
                str(root) + ":/backup",
                "-e",
                "BACKUP_KEY_FILE=/backup/restore_key",
                "operations-tools",
            )
            compose(
                *backup_command,
                "create",
                "/backup/fixture.backup",
                "--writers-quiesced",
            )
            compose(
                *backup_command,
                "restore",
                "/backup/fixture.backup",
                "--database",
                "restore_https_fixture",
                "--bucket",
                "restore-https-fixture",
            )
            restored_acl = """
import os, psycopg, nautiq_ml
from psycopg.conninfo import conninfo_to_dict
config=conninfo_to_dict(os.environ['DATABASE_URL']); config['dbname']='restore_https_fixture'
with psycopg.connect(**config) as db:
 assert db.execute("SELECT paused->>'science' FROM operations_controls WHERE singleton").fetchone()[0]=='true'
 assert not db.execute("SELECT has_function_privilege('nautiq_app','public.operations_lock_release(text,uuid)','EXECUTE')").fetchone()[0]
 assert not db.execute("SELECT has_table_privilege('nautiq_app','operations_controls','UPDATE')").fetchone()[0]
print('Provisioned-schema isolated restore and restricted function ACL passed.')
"""
            compose(
                "run",
                "--rm",
                "--no-deps",
                "-T",
                "--entrypoint",
                "/opt/ops/bin/python",
                "operations-tools",
                "-c",
                restored_acl,
            )
            # Manifest exposes only the HTTPS edge and keeps the backend network private.
            config = json.loads(compose("config", "--format", "json").stdout)
            for name, service in config["services"].items():
                if name != "gateway":
                    assert not service.get("ports"), (
                        "Backend host port remained exposed"
                    )
            assert config["networks"]["default"]["internal"] is True
            print(
                json.dumps(
                    {
                        "disposable_https": True,
                        "certificate_verified": True,
                        "private_backend_routes": True,
                        "host_secure_session_cookie": True,
                        "same_origin_csrf_account_deletion": True,
                        "security_headers": True,
                        "separate_restricted_roles": True,
                        "restricted_storage_iam": True,
                        "operator_release_lock_without_edit_privilege": True,
                        "production_schema_backup_restore_and_restricted_function_acl": True,
                        "private_network": True,
                        "public_production_approved": False,
                    },
                    sort_keys=True,
                )
            )
        except BaseException:
            # Only synthetic gateway process logs; never environment/config/private responses.
            print(compose("logs", "--tail", "15", "gateway", check=False).stdout)
            raise
        finally:
            compose("down", "--volumes", "--remove-orphans", check=False)


if __name__ == "__main__":
    main()
