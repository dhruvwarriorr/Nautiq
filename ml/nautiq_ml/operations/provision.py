"""Provision separate application/worker/operator credentials; never print secrets."""

import argparse
import json
import os
import secrets
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from minio.credentials import StaticProvider
from minio.minioadmin import MinioAdmin


def provision(directory, sql_file, policy_directory):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.stat().st_mode & 0o077:
        raise ValueError("private_secret_directory_required")
    names = (
        "app_database_url",
        "worker_database_url",
        "operator_database_url",
        "backup_database_url",
        "storage_app_user",
        "storage_app_password",
        "storage_worker_user",
        "storage_worker_password",
        "storage_root_user",
        "storage_root_password",
    )
    if any((directory / name).exists() for name in names):
        raise ValueError("existing_credentials_are_never_overwritten")
    config = conninfo_to_dict(os.environ["DATABASE_URL"])
    values = {
        "backup_database_url": os.environ["DATABASE_URL"],
        "storage_root_user": os.environ["MINIO_ROOT_USER"],
        "storage_root_password": os.environ["MINIO_ROOT_PASSWORD"],
    }
    roles = {
        name: secrets.token_hex(32)
        for name in ("nautiq_app", "nautiq_worker", "nautiq_operator")
    }
    with psycopg.connect(os.environ["DATABASE_URL"]) as db:
        if db.execute(
            "SELECT 1 FROM pg_roles WHERE rolname=ANY(%s)", (list(roles),)
        ).fetchone():
            raise ValueError("existing_roles_require_explicit_rotation")
        db.execute(sql_file.read_text())
        for role, password in roles.items():
            db.execute(
                sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                    sql.Identifier(role), sql.Literal(password)
                )
            )
            values[role.removeprefix("nautiq_") + "_database_url"] = make_conninfo(
                **{**config, "user": role, "password": password}
            )
    admin = MinioAdmin(
        endpoint=os.environ["MINIO_ENDPOINT"],
        credentials=StaticProvider(
            values["storage_root_user"], values["storage_root_password"]
        ),
        secure=False,
    )
    for scope in ("app", "worker"):
        user, password = (
            "nautiq_" + scope + "_" + secrets.token_hex(8),
            secrets.token_hex(32),
        )
        policy = json.loads(
            (policy_directory / ("storage-" + scope + "-policy.json")).read_text()
        )
        policy_name = "nautiq_" + scope
        admin.policy_add(policy_name, policy=policy)
        admin.user_add(user, password)
        admin.attach_policy([policy_name], user=user)
        values["storage_" + scope + "_user"] = user
        values["storage_" + scope + "_password"] = password
    for name, value in values.items():
        path = directory / name
        with path.open("x") as file:
            file.write(value + "\n")
        # Parent 0700 protects files on the host; selected read-only Compose mounts
        # remain readable by distinct non-root application UIDs.
        path.chmod(0o644)
    print(
        "Distinct application, worker and operator credentials provisioned. Values are only in the private directory; certificate and backup key are supplied separately."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--sql-file", type=Path, default=Path("/production/roles.sql"))
    parser.add_argument("--policy-directory", type=Path, default=Path("/production"))
    args = parser.parse_args()
    provision(args.directory, args.sql_file, args.policy_directory)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "Provisioning refused. Inspect named roles/policies before explicit retry or rotation; secret values suppressed."
        ) from None
