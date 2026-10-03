"""Exercise retained model rollback only inside an isolated restore database."""

import json
import os
import uuid

from psycopg.conninfo import conninfo_to_dict, make_conninfo
from .rollback import rollback, selections, KINDS
from ..climatology import pipeline as climate


def main():
    database = os.environ["RESTORE_DATABASE"]
    if not database.startswith("restore_"):
        raise ValueError("isolated_rollback_required")
    config = conninfo_to_dict(os.environ["DATABASE_URL"])
    config["dbname"] = database
    os.environ["DATABASE_URL"] = make_conninfo(**config)
    with climate.connect() as db:
        before = selections(db)
        revision = db.execute(
            "SELECT revision FROM operations_controls WHERE singleton"
        ).fetchone()["revision"]
    try:
        rollback(
            "climatology",
            uuid.uuid4(),
            "verification",
            "missing_release_fixture",
            revision,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Missing model accepted")
    with climate.connect() as db:
        assert selections(db) == before
        control = db.execute(
            "SELECT revision,paused FROM operations_controls WHERE singleton"
        ).fetchone()
        assert control["paused"]["science"] is True
        available = [(kind, before[kind]) for kind in KINDS if before[kind]]
    if not available:
        raise ValueError("no_retained_model_for_rollback_acceptance")
    kind, release = available[-1]
    rollback(
        kind, release, "verification", "retained_lineage_fixture", control["revision"]
    )
    with climate.connect() as db:
        assert selections(db) == before
        assert (
            db.execute(
                "SELECT paused->>'science' AS science_paused FROM operations_controls WHERE singleton"
            ).fetchone()["science_paused"]
            == "true"
        )
        actions = [
            row["action"]
            for row in db.execute(
                "SELECT action FROM operations_audit WHERE scope='model_inference' ORDER BY created_at"
            ).fetchall()
        ]
        assert "rollback_failed" in actions and "rollback_completed" in actions
    print(
        json.dumps(
            {
                "verified_retained_model_lineage": True,
                "atomic_selection_rollback": True,
                "missing_release_refused_without_selection_change": True,
                "serving_stays_paused": True,
                "live_selection_changed": False,
            }
        )
    )


if __name__ == "__main__":
    main()
