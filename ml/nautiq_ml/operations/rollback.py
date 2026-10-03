"""Verified atomic selection rollback; scientific serving remains paused afterwards."""

import argparse
import json
import re
import uuid

from psycopg import sql
from psycopg.types.json import Jsonb
from ..argo.storage import store
from ..climatology import pipeline as climate

KINDS = ("climatology", "expected_state", "uncertainty", "anomaly")


def selections(db):
    result = {}
    for kind in KINDS:
        row = db.execute(
            sql.SQL("SELECT release_id FROM {} WHERE singleton").format(
                sql.Identifier(kind + "_selection")
            )
        ).fetchone()
        result[kind] = str(row["release_id"]) if row else None
    return result


def audit(db, action, actor, reason, before, after):
    db.execute(
        "INSERT INTO operations_audit(audit_id,action,scope,reason,actor,before_state,after_state) VALUES(%s,%s,'model_inference',%s,%s,%s,%s)",
        (uuid.uuid4(), action, reason, actor, Jsonb(before), Jsonb(after)),
    )


def prepare(kind, release_id, s3=None):
    """Verify complete current-compatible lineage before changing any selection."""
    s3 = s3 or store()
    chain = {}
    if kind == "anomaly":
        from ..anomaly import pipeline

        row, _ = pipeline.load_release(release_id, s3)
        chain["anomaly"] = row
        kind, release_id = "uncertainty", row["uncertainty_id"]
    if kind == "uncertainty":
        from ..uncertainty import pipeline

        row, _ = pipeline.load_release(release_id, s3)
        chain["uncertainty"] = row
        kind, release_id = "expected_state", row["expected_id"]
    if kind == "expected_state":
        from ..expected_state import pipeline

        row, _ = pipeline.load_release(release_id, s3)
        chain["expected_state"] = row
        release_id = row["reference_id"]
    with climate.connect() as db:
        row = db.execute(
            "SELECT * FROM climatology_releases WHERE release_id=%s", (release_id,)
        ).fetchone()
    if row is None:
        raise ValueError("rollback_reference_missing")
    climate.verify(release_id, s3)
    climate.release_bundle(row, s3)
    chain["climatology"] = row
    if any(
        row["status"] != "ready" or row["release_approved"] is not False
        for row in chain.values()
    ):
        raise ValueError("rollback_not_ready")
    return chain


def apply_chain(db, chain):
    """Caller holds the canonical selection lock and incident-control row lock."""
    from ..expected_state.jobs import queue as expected_queue
    from ..uncertainty.jobs import queue as uncertainty_queue
    from ..anomaly.jobs import queue as anomaly_queue

    queues = {
        "climatology": climate.queue,
        "expected_state": expected_queue,
        "uncertainty": uncertainty_queue,
        "anomaly": anomaly_queue,
    }
    rows = db.execute(
        "SELECT profile_id,revision_sha256 FROM profile_revisions WHERE science_ready AND selected_at IS NOT NULL AND superseded_at IS NULL ORDER BY profile_id LIMIT 2001"
    ).fetchall()
    if len(rows) > 2000:
        raise ValueError("rollback_profile_budget")
    for kind in KINDS:
        if kind not in chain:
            db.execute(
                sql.SQL("DELETE FROM {}").format(sql.Identifier(kind + "_selection"))
            )
            db.execute(
                "UPDATE calculations SET state='stale' WHERE kind=%s AND state='current'",
                (kind + "_comparison",),
            )
            continue
        release = chain[kind]
        operator = (
            db.execute("SELECT current_user AS role").fetchone()["role"]
            == "nautiq_operator"
        )
        if operator:
            db.execute(
                "SELECT operations_lock_release(%s,%s)", (kind, release["release_id"])
            )
        current = db.execute(
            sql.SQL(
                "SELECT * FROM {} WHERE release_id=%s"
                + ("" if operator else " FOR SHARE")
            ).format(sql.Identifier(kind + "_releases")),
            (release["release_id"],),
        ).fetchone()
        if current != release:
            raise ValueError("rollback_release_superseded")
        db.execute(
            sql.SQL(
                "INSERT INTO {}(singleton,release_id) VALUES(true,%s) ON CONFLICT(singleton) DO UPDATE SET release_id=excluded.release_id,selected_at=clock_timestamp()"
            ).format(sql.Identifier(kind + "_selection")),
            (release["release_id"],),
        )
        db.execute(
            "UPDATE calculations SET state='stale' WHERE kind=%s AND state='current'",
            (kind + "_comparison",),
        )
        for profile in rows:
            queues[kind](
                db,
                profile["profile_id"],
                profile["revision_sha256"],
                release["release_id"],
            )
        db.execute(
            sql.SQL(
                "UPDATE calculations c SET state='current' FROM {} p JOIN profile_revisions r USING(profile_id,revision_sha256) WHERE p.calculation_id=c.calculation_id AND p.release_id=%s AND r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL"
            ).format(sql.Identifier(kind + "_comparisons")),
            (release["release_id"],),
        )


def rollback(kind, release_id, actor, reason, revision):
    uuid.UUID(str(release_id))
    if (
        kind not in KINDS
        or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", actor)
        or not re.fullmatch(r"[a-z][a-z0-9_]{2,63}", reason)
    ):
        raise ValueError("invalid_operator_request")
    with climate.connect() as db:
        control = db.execute(
            "SELECT * FROM operations_controls WHERE singleton FOR UPDATE"
        ).fetchone()
        if control["revision"] != revision:
            raise ValueError("control_revision_conflict")
        before = selections(db)
        paused = {**control["paused"], "science": True}
        db.execute(
            "UPDATE operations_controls SET paused=%s,revision=revision+1,updated_at=now() WHERE singleton",
            (Jsonb(paused),),
        )
        audit(db, "rollback_started", actor, reason, before, {"science_paused": True})
    try:
        chain = prepare(kind, release_id)
        with climate.connect() as db:
            db.execute("SET LOCAL statement_timeout='60s'")
            db.execute("SELECT pg_advisory_xact_lock(78192402)")
            control = db.execute(
                "SELECT * FROM operations_controls WHERE singleton FOR UPDATE"
            ).fetchone()
            if control["revision"] != revision + 1 or not control["paused"].get(
                "science"
            ):
                raise ValueError("rollback_control_superseded")
            apply_chain(db, chain)
            after = selections(db)
            audit(db, "rollback_completed", actor, reason, before, after)
        print(
            json.dumps(
                {
                    "rollback_completed": True,
                    "serving_paused": True,
                    "runtime_pins": after,
                    "release_approved": False,
                },
                sort_keys=True,
            )
        )
    except Exception:
        with climate.connect() as db:
            audit(
                db,
                "rollback_failed",
                actor,
                reason,
                before,
                {
                    "selection_transaction_unchanged": True,
                    "serving_requires_operator_check": True,
                },
            )
        raise ValueError("rollback_failed_check_incident_controls") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=KINDS)
    parser.add_argument("release_id")
    parser.add_argument("--actor", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--revision", type=int, required=True)
    args = parser.parse_args()
    rollback(args.kind, args.release_id, args.actor, args.reason, args.revision)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "Rollback refused; inspect incident controls and original runtime pins. Private details suppressed."
        ) from None
