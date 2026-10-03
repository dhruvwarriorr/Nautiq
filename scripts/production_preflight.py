"""Validate operator-supplied deployment inputs without starting or publishing services."""

import argparse
import json
import os
import re
import stat
import subprocess
from pathlib import Path
from urllib.parse import urlsplit
from psycopg.conninfo import conninfo_to_dict

ROOT = Path(__file__).resolve().parents[1]


def validate(config, directory, host, domain, images):
    if not re.fullmatch(r"[a-zA-Z0-9.-]{1,253}", host):
        raise ValueError("certificate_hostname_required")
    origin = urlsplit("https://" + domain)
    if (
        origin.hostname != host
        or origin.username
        or origin.path
        or origin.query
        or origin.fragment
    ):
        raise ValueError("origin_hostname_mismatch")
    # Multi-UID containers may read a mounted file; protect its host parent instead.
    info = directory.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077:
        raise ValueError("private_secret_directory_required")
    for secret in config["secrets"].values():
        path = Path(secret["file"])
        if path.parent.resolve() != directory.resolve() or path.is_symlink():
            raise ValueError("secret_path_contract")
        if not path.is_file() or not 0 < path.stat().st_size <= 16384:
            raise ValueError("secret_file_contract")
        if path.name not in {"tls_cert", "tls_key"}:
            raw = path.read_text().removesuffix("\n").removesuffix("\r")
            if not raw or any(c in raw for c in "\r\n\0") or "nautiq_local" in raw:
                raise ValueError("secret_value_contract")
            if "password" in path.name and len(raw) < 24:
                raise ValueError("strong_secret_required")
    if not config["networks"]["default"].get("internal"):
        raise ValueError("private_backend_required")
    for name, role in (
        ("app_database_url", "nautiq_app"),
        ("worker_database_url", "nautiq_worker"),
    ):
        connection = conninfo_to_dict((directory / name).read_text().strip())
        if (
            connection.get("user") != role
            or connection.get("host") != "postgres"
            or not connection.get("dbname")
            or len(connection.get("password", "")) < 24
        ):
            raise ValueError("restricted_database_identity_required")
    enabled = {
        name: service
        for name, service in config["services"].items()
        if not service.get("profiles")
    }
    if not set(enabled).issubset(images) or not set(images).issubset(
        config["services"]
    ):
        raise ValueError("complete_image_lock_required")
    for image in images.values():
        if not re.fullmatch(r"[a-zA-Z0-9._:/-]+@sha256:[a-f0-9]{64}", image):
            raise ValueError("registry_digest_required")
    for name, service in enabled.items():
        if name != "gateway" and service.get("ports"):
            raise ValueError("backend_host_port_forbidden")
        if not re.fullmatch(r"[a-zA-Z0-9._:/-]+@sha256:[a-f0-9]{64}", images[name]):
            raise ValueError("registry_digest_required")
    for name in ("api", "notifications", "web"):
        if not enabled[name].get("read_only") or "ALL" not in enabled[name].get(
            "cap_drop", []
        ):
            raise ValueError("application_hardening_required")
    for name, service in enabled.items():
        for key, value in service.get("environment", {}).items():
            if (
                key
                in {
                    "DATABASE_URL",
                    "MINIO_ROOT_PASSWORD",
                    "SMTP_PASSWORD",
                    "POSTGRES_PASSWORD",
                }
                and value
            ):
                raise ValueError("plaintext_secret_environment_forbidden")
    for args in (
        [
            "openssl",
            "x509",
            "-in",
            str(directory / "tls_cert"),
            "-noout",
            "-checkhost",
            host,
        ],
        [
            "openssl",
            "x509",
            "-in",
            str(directory / "tls_cert"),
            "-noout",
            "-checkend",
            "604800",
        ],
    ):
        result = subprocess.run(
            args, capture_output=True, stdin=subprocess.DEVNULL, timeout=10
        )
        if result.returncode or b"does NOT match certificate" in result.stdout:
            raise ValueError("certificate_hostname_or_expiry_refused")
    public = subprocess.run(
        ["openssl", "x509", "-in", str(directory / "tls_cert"), "-pubkey", "-noout"],
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=10,
    )
    private = subprocess.run(
        ["openssl", "pkey", "-in", str(directory / "tls_key"), "-pubout"],
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=10,
    )
    if public.returncode or private.returncode or public.stdout != private.stdout:
        raise ValueError("certificate_key_mismatch")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--images",
        required=True,
        type=Path,
        help="JSON map of every enabled service to registry image@sha256 digest",
    )
    parser.add_argument(
        "--output", required=True, type=Path, help="new immutable-image Compose overlay"
    )
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("new_lock_path_required")
    command = [
        "docker",
        "compose",
        "-f",
        str(ROOT / "docker-compose.yml"),
        "-f",
        str(ROOT / "docker-compose.production.yml"),
    ]
    if os.getenv("SMTP_HOST"):
        command.extend(["-f", str(ROOT / "docker-compose.mail.yml")])
    result = subprocess.run(
        [*command, "config", "--format", "json"], capture_output=True, text=True
    )
    if result.returncode:
        raise ValueError("production_manifest_refused")
    images = json.loads(args.images.read_text())
    validate(
        json.loads(result.stdout),
        Path(os.environ["NAUTIQ_SECRETS_DIR"]),
        os.environ["PUBLIC_HOST"],
        os.environ["PUBLIC_DOMAIN"],
        images,
    )
    with args.output.open("x") as file:
        json.dump(
            {"services": {name: {"image": image} for name, image in images.items()}},
            file,
            indent=2,
        )
        file.write("\n")
    print(
        json.dumps(
            {
                "deployment_inputs_validated": True,
                "immutable_image_overlay_created": True,
                "services_started": False,
                "production_approved": False,
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        label = (
            str(error)
            if isinstance(error, ValueError)
            and re.fullmatch(r"[a-z_]{1,80}", str(error))
            else type(error).__name__
        )
        raise SystemExit(
            "Deployment preflight refused: " + label + "; private details suppressed"
        ) from None
