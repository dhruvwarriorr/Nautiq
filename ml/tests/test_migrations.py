import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("migrate", ROOT / "scripts/migrate.py")
migrate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migrate)


def test_migration_batch_has_lock_checksum_guard_and_single_transaction():
    sql = migrate.migration_sql(ROOT / "migrations")
    assert sql.startswith("BEGIN;") and sql.endswith("COMMIT;")
    assert "pg_advisory_xact_lock" in sql and "checksum changed" in sql
    assert "Database is newer" in sql and "event_outbox" in sql


def test_migration_gaps_fail_before_database_access(tmp_path):
    (tmp_path / "001_first.sql").write_text("SELECT 1;")
    (tmp_path / "003_third.sql").write_text("SELECT 3;")
    with pytest.raises(ValueError, match="noncontiguous"):
        migrate.migration_sql(tmp_path)
