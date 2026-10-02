"""Exercise fresh/legacy/checksum/rollback paths in a disposable local database."""

import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from migrate import ROOT, migration_sql


def sql(database, text, expected_success=True):
    # Database is generated locally or read from the container's configured name.
    name = database if database else '"$POSTGRES_DB"'
    command = [
        "docker",
        "compose",
        "exec",
        "-T",
        "postgres",
        "sh",
        "-ec",
        f'psql -X -qAt -U "$POSTGRES_USER" -d {name} -v ON_ERROR_STOP=1',
    ]
    result = subprocess.run(
        command, cwd=ROOT, input=text, text=True, capture_output=True
    )
    if (result.returncode == 0) != expected_success:
        raise AssertionError(
            "Unexpected migration database result (details suppressed)"
        )
    return result.stdout.strip()


def main():
    version = len(list((ROOT / "migrations").glob("*.sql")))
    failure_name = f"{version + 1:03}_failure.sql"
    database = "nautiuq_migration_test_" + uuid.uuid4().hex[:12]
    sql(None, f"CREATE DATABASE {database};")
    try:
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            for path in (ROOT / "migrations").glob("*.sql"):
                shutil.copyfile(path, directory / path.name)
            sql(database, migration_sql(directory))
            assert sql(
                database, "SELECT max(version) FROM platform_schema_version;"
            ) == str(version)
            sql(
                database,
                "CREATE TABLE sentinel(value text); INSERT INTO sentinel VALUES ('preserved');",
            )
            sql(database, migration_sql(directory))
            assert sql(database, "SELECT value FROM sentinel;") == "preserved"
            original = (directory / "002_reliability.sql").read_text()
            (directory / "002_reliability.sql").write_text(
                original + "\n-- changed checksum\n"
            )
            sql(database, migration_sql(directory), expected_success=False)
            (directory / "002_reliability.sql").write_text(original)
            (directory / failure_name).write_text(
                "CREATE TABLE must_rollback(value integer); SELECT 1/0;"
            )
            sql(database, migration_sql(directory), expected_success=False)
            assert (
                sql(database, "SELECT to_regclass('public.must_rollback') IS NULL;")
                == "t"
            )
            assert sql(database, "SELECT count(*) FROM platform_migrations;") == str(
                version
            )
            (directory / failure_name).unlink()
            # Reset only the disposable DB to the original legacy v1 bootstrap.
            sql(database, "DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
            sql(database, (ROOT / "migrations/001_platform.sql").read_text())
            sql(database, migration_sql(directory))
            assert sql(database, "SELECT count(*) FROM platform_migrations;") == str(
                version
            )
            # Unique events and inbox delivery identities are actual DB constraints.
            event = str(uuid.uuid4())
            digest = "a" * 64
            insert = f"INSERT INTO event_outbox(event_id,event_type,schema_version,aggregate_key,revision_sha256,payload) VALUES ('{event}','profile.ready',1,'argo:fixture','{digest}','{{}}');"
            sql(database, insert)
            sql(database, insert, expected_success=False)
            sql(
                database,
                f"INSERT INTO consumer_inbox VALUES ('normalizer','{event}',now());",
            )
            sql(
                database,
                f"INSERT INTO consumer_inbox VALUES ('normalizer','{event}',now());",
                expected_success=False,
            )
        print(
            "Migration integration checks passed: fresh, repeat, legacy upgrade, checksum refusal, rollback, outbox/inbox uniqueness."
        )
    finally:
        sql(None, f"DROP DATABASE {database};")


if __name__ == "__main__":
    main()
