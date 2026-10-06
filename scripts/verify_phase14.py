"""Offline hardening contracts and authenticated backup refusal checks."""

import json
import copy
import io
import os
import secrets
import subprocess
import tempfile
import tarfile
from pathlib import Path

from nautiq_ml.operations.backup import crypt, restore
from production_preflight import validate

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        key = root / "key"
        key.write_text(secrets.token_hex(32))
        previous = os.environ.get("BACKUP_KEY_FILE")
        os.environ["BACKUP_KEY_FILE"] = str(key)
        try:
            source = root / "original"
            source.write_bytes(b"Frozen synthetic byte fixture\x00" * 1000)
            crypt(source, root / "encrypted")
            crypt(root / "encrypted", root / "replayed", True)
            assert (root / "replayed").read_bytes() == source.read_bytes()
            for index in (0, 9, 20, (root / "encrypted").stat().st_size - 1):
                raw = bytearray((root / "encrypted").read_bytes())
                raw[index] ^= 1
                damaged = root / f"damaged-{index}"
                damaged.write_bytes(raw)
                try:
                    crypt(damaged, root / f"refused-{index}", True)
                except Exception:
                    pass
                else:
                    raise AssertionError("Modified backup was accepted")
            key.write_text(secrets.token_hex(32))
            try:
                crypt(root / "encrypted", root / "wrong-key", True)
            except Exception:
                pass
            else:
                raise AssertionError("Wrong backup key was accepted")
            original_env = {
                name: os.environ.get(name)
                for name in ("MINIO_ENDPOINT", "MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD")
            }
            os.environ.update(
                MINIO_ENDPOINT="unused.invalid:9000",
                MINIO_ROOT_USER="fixture",
                MINIO_ROOT_PASSWORD="fixture-only",
            )
            try:
                for fixture in ("traversal", "link", "duplicate"):
                    archive = root / (fixture + ".tar")
                    with tarfile.open(archive, "w") as tar:
                        entry = tarfile.TarInfo(
                            "../../outside"
                            if fixture == "traversal"
                            else "manifest.json"
                        )
                        if fixture == "link":
                            entry.type = tarfile.SYMTYPE
                            entry.linkname = "../../outside"
                            tar.addfile(entry)
                        else:
                            entry.size = 7
                            tar.addfile(entry, io.BytesIO(b"fixture"))
                            if fixture == "duplicate":
                                tar.addfile(entry, io.BytesIO(b"fixture"))
                    encrypted = root / (fixture + ".backup")
                    crypt(archive, encrypted)
                    try:
                        restore(
                            encrypted, "restore_fixture_only", "restore-fixture-only"
                        )
                    except ValueError as error:
                        assert str(error) == "restore_archive_members"
                    else:
                        raise AssertionError("Unsafe archive member accepted")
            finally:
                for name, value in original_env.items():
                    if value is None:
                        os.environ.pop(name, None)
                    else:
                        os.environ[name] = value
        finally:
            if previous is None:
                os.environ.pop("BACKUP_KEY_FILE", None)
            else:
                os.environ["BACKUP_KEY_FILE"] = previous
        secret_file = root / "secret"
        secret_file.write_text("synthetic-file-value\n")
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.endswith("_FILE")
            and key
            not in {
                "DATABASE_URL",
                "MINIO_ROOT_USER",
                "MINIO_ROOT_PASSWORD",
                "NAUTIQ_DEPLOYMENT",
                "PRODUCT_WEB_ORIGIN",
            }
        }
        environment["DATABASE_URL_FILE"] = str(secret_file)
        result = subprocess.run(
            [
                str(ROOT / ".venv/bin/python"),
                "-c",
                "import nautiq_ml,os; assert os.environ['DATABASE_URL']=='synthetic-file-value'",
            ],
            env=environment,
            capture_output=True,
        )
        assert result.returncode == 0
        result = subprocess.run(
            [str(ROOT / ".venv/bin/python"), "-c", "import nautiq_ml"],
            env={**environment, "DATABASE_URL": "conflicting-fixture"},
            capture_output=True,
        )
        assert result.returncode != 0
        result = subprocess.run(
            [str(ROOT / ".venv/bin/python"), "-c", "import nautiq_ml"],
            env={
                **environment,
                "NAUTIQ_DEPLOYMENT": "production",
                "PRODUCT_WEB_ORIGIN": "http://localhost:3000",
            },
            capture_output=True,
        )
        assert result.returncode != 0
    env = {
        **os.environ,
        "PUBLIC_HOST": "localhost",
        "PUBLIC_DOMAIN": "localhost:8443",
        "NAUTIQ_SECRETS_DIR": "/tmp/nautiq-placeholder",
    }
    config = json.loads(
        subprocess.check_output(
            [
                "docker",
                "compose",
                "-f",
                str(ROOT / "docker-compose.yml"),
                "-f",
                str(ROOT / "docker-compose.production.yml"),
                "config",
                "--format",
                "json",
            ],
            env=env,
            text=True,
        )
    )
    assert config["networks"]["default"]["internal"] is True
    for name, service in config["services"].items():
        assert not service.get("ports") or name == "gateway"
    for name in ("api", "web"):
        assert config["services"][name]["read_only"]
    assert config["services"]["api"]["environment"]["DATABASE_URL"] == ""
    assert config["services"]["api"]["environment"]["DATABASE_URL_FILE"]
    with tempfile.TemporaryDirectory() as directory:
        private = Path(directory)
        private.chmod(0o700)
        for name, secret in config["secrets"].items():
            secret["file"] = str(private / name)
            (private / name).write_text(secrets.token_hex(32))
        for scope in ("app", "worker"):
            (private / (scope + "_database_url")).write_text(
                "host=postgres dbname=nautiq user=nautiq_"
                + scope
                + " password="
                + secrets.token_hex(32)
            )
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "14",
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost",
                "-keyout",
                str(private / "tls_key"),
                "-out",
                str(private / "tls_cert"),
            ],
            check=True,
            capture_output=True,
        )
        images = {
            name: "registry.invalid/fixture@sha256:" + "a" * 64
            for name, service in config["services"].items()
            if not service.get("profiles")
        }
        validate(config, private, "localhost", "localhost:8443", images)
        original_key = (private / "tls_key").read_bytes()
        refusals = {
            "port": "backend_host_port_forbidden",
            "mutable": "registry_digest_required",
            "hostname": "certificate_hostname_or_expiry_refused",
            "role": "restricted_database_identity_required",
            "key": "certificate_key_mismatch",
            "directory": "private_secret_directory_required",
        }
        for failure in ("port", "mutable", "hostname", "role", "key", "directory"):
            (private / "tls_key").write_bytes(original_key)
            changed = copy.deepcopy(config)
            pins = dict(images)
            hostname = "wrong.invalid" if failure == "hostname" else "localhost"
            if failure == "port":
                changed["services"]["api"]["ports"] = [
                    {"target": 8080, "published": "8080"}
                ]
            elif failure == "mutable":
                pins["api"] = "registry.invalid/fixture:latest"
            elif failure == "role":
                (private / "app_database_url").write_text(
                    "host=postgres dbname=nautiq user=administrator password="
                    + secrets.token_hex(32)
                )
            elif failure == "key":
                (private / "tls_key").write_text("invalid fixture")
            elif failure == "directory":
                private.chmod(0o755)
            try:
                validate(changed, private, hostname, hostname + ":8443", pins)
            except ValueError as error:
                assert str(error) == refusals[failure]
            else:
                raise AssertionError("Unsafe deployment input accepted")
            private.chmod(0o700)
            (private / "app_database_url").write_text(
                "host=postgres dbname=nautiq user=nautiq_app password="
                + secrets.token_hex(32)
            )
    policy = json.loads((ROOT / "packages/source-catalog/production.json").read_text())
    assert (
        policy["production_approved"] is False
        and policy["scientific_approved"] is False
    )
    assert (
        subprocess.run(
            [str(ROOT / ".venv/bin/python"), str(ROOT / "scripts/production_gate.py")],
            capture_output=True,
        ).returncode
        == 2
    )
    assert (
        "backups" in (ROOT / ".dockerignore").read_text()
        and "secrets" in (ROOT / ".dockerignore").read_text()
    )
    print(
        "Hardening contracts passed: encrypted replay/tamper/wrong-key refusal, secret-file conflict/HTTPS guards, private service ports, read-only apps and fail-closed production gates."
    )


if __name__ == "__main__":
    main()
