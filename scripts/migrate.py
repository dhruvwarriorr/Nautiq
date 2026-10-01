"""Checksum-verified local migrations, one lock and transaction across all files."""

import hashlib
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def migration_sql(directory):
    files = sorted(directory.glob("*.sql"))
    if not files or any(
        not re.fullmatch(r"\d{3}_[a-z0-9_]+\.sql", f.name) for f in files
    ):
        raise ValueError("invalid_migration_names")
    versions = [int(f.name[:3]) for f in files]
    if versions != list(range(1, len(versions) + 1)):
        raise ValueError("noncontiguous_migrations")
    # Existing Phase 1 schema is adopted only after checking its capabilities.
    sql = [
        "BEGIN; SET LOCAL lock_timeout = '15s'; SET LOCAL statement_timeout = '60s';",
        "SELECT pg_advisory_xact_lock(78192401);",
        "CREATE TABLE IF NOT EXISTS platform_migrations (version integer PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now());",
    ]
    for version, path in zip(versions, files, strict=True):
        raw = path.read_bytes()
        content = raw.decode("utf-8")
        sha = hashlib.sha256(raw).hexdigest()
        if "$migration$" in content or re.search(
            r"\b(BEGIN|COMMIT|ROLLBACK)\s*;", content, re.I
        ):
            raise ValueError("migration_contains_transaction_or_reserved_delimiter")
        if version == 1:
            # Legacy initialization lacked checksums. Never rerun a destructive bootstrap.
            sql.append(f"""DO $migration$ BEGIN
IF to_regclass('public.platform_schema_version') IS NOT NULL AND NOT EXISTS (SELECT 1 FROM platform_migrations WHERE version=1) THEN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname='postgis') OR NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname='timescaledb') OR NOT EXISTS (SELECT 1 FROM platform_schema_version WHERE version=1) THEN
    RAISE EXCEPTION 'Legacy platform schema cannot be adopted';
  END IF;
  INSERT INTO platform_migrations(version,sha256) VALUES (1,'{sha}');
END IF;
END $migration$;""")
        sql.append(f"""DO $migration$ BEGIN
IF EXISTS (SELECT 1 FROM platform_migrations WHERE version={version} AND sha256 <> '{sha}') THEN
  RAISE EXCEPTION 'Applied migration checksum changed: {version}';
END IF;
IF NOT EXISTS (SELECT 1 FROM platform_migrations WHERE version={version}) THEN
{content}
INSERT INTO platform_migrations(version,sha256) VALUES ({version},'{sha}');
END IF;
END $migration$;""")
    sql.append(
        f"DO $migration$ BEGIN IF (SELECT max(version) FROM platform_schema_version) <> {len(files)} THEN RAISE EXCEPTION 'Platform schema version differs from migration set'; END IF; END $migration$;"
    )
    sql.extend(
        [
            f"DO $migration$ BEGIN IF EXISTS (SELECT 1 FROM platform_migrations WHERE version > {len(files)}) THEN RAISE EXCEPTION 'Database is newer than this checkout'; END IF; END $migration$;",
            "COMMIT;",
        ]
    )
    return "\n".join(sql)


def main():
    # PostgreSQL startup wait does not reveal credentials.
    subprocess.run(
        ["docker", "compose", "up", "-d", "--wait", "postgres"], cwd=ROOT, check=True
    )
    command = [
        "docker",
        "compose",
        "exec",
        "-T",
        "postgres",
        "sh",
        "-ec",
        'psql -X -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1',
    ]
    result = subprocess.run(
        command,
        cwd=ROOT,
        input=migration_sql(ROOT / "migrations"),
        text=True,
        capture_output=True,
    )
    if result.returncode:
        # Log only the failure class, never SQL bodies or connection strings.
        raise SystemExit(
            "Migration failed; check schema/checksum compatibility and database availability. No transaction was committed."
        )
    print("Migrations applied and checksums verified; existing data preserved.")


if __name__ == "__main__":
    main()
