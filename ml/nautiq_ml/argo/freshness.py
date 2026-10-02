"""Source cadence and ingestion freshness are separate, explicit states."""

import os
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


def age_hours(value, now):
    return (now - value).total_seconds() / 3600 if value else None


def evaluate(
    metadata, latest, successful, newest, pending, oldest_pending, qc_count, now
):
    fetch = successful.get("upstream_checked_at") if successful else None
    observed_age = age_hours(newest, now)
    fetch_age = age_hours(fetch, now)
    failed = bool(
        latest
        and latest["status"] == "failed"
        and (not successful or latest["started_at"] > successful["started_at"])
    )
    budget = metadata.get("ingestion_budget_hours")
    ingestion = "unknown"
    if fetch_age is not None and budget is not None:
        ingestion = (
            "invalid_clock"
            if fetch_age < -5 / 60
            else (
                "stale"
                if fetch_age > budget
                else ("degraded" if failed else "on_schedule")
            )
        )
    cadence_verified = bool(metadata.get("cadence_verified"))
    freshness_budget = metadata.get("freshness_budget_hours")
    source_state = "unverified"
    if cadence_verified and freshness_budget is not None:
        source_state = (
            "unknown"
            if observed_age is None
            else (
                "invalid_clock"
                if observed_age < -5 / 60
                else ("stale" if observed_age > freshness_budget else "fresh")
            )
        )
    return {
        "schema_version": 1,
        "source_freshness": source_state,
        "ingestion_state": ingestion,
        "coverage_state": metadata.get("coverage_state", "unverified"),
        "expected_update_hours": metadata.get("expected_update_hours"),
        "cadence_verified": cadence_verified,
        "freshness_budget_hours": freshness_budget,
        "ingestion_budget_hours": budget,
        "last_successful_fetch": fetch.isoformat() if fetch else None,
        "last_fetch_age_hours": fetch_age,
        "newest_observed_at": newest.isoformat() if newest else None,
        "observation_age_hours": observed_age,
        "latest_run_status": latest["status"] if latest else None,
        "last_failure_code": latest.get("reason_code") if failed else None,
        "pending_event_count": pending,
        "oldest_pending_age_hours": age_hours(oldest_pending, now),
        "qc_rejection_count": qc_count,
        "checked_at": now.isoformat(),
    }


def monitor():
    with psycopg.connect(
        os.environ["DATABASE_URL"], row_factory=dict_row, connect_timeout=5
    ) as db:
        db.execute("SET statement_timeout='15s'; SET lock_timeout='5s'")
        now = db.execute("SELECT clock_timestamp() AS instant").fetchone()["instant"]
        for source in db.execute("SELECT * FROM sources ORDER BY source_id").fetchall():
            sid = source["source_id"]
            latest = db.execute(
                "SELECT * FROM ingestion_runs WHERE source_id=%s AND run_kind='live' ORDER BY started_at DESC LIMIT 1",
                (sid,),
            ).fetchone()
            successful = db.execute(
                "SELECT * FROM ingestion_runs WHERE source_id=%s AND run_kind='live' AND status='complete' AND upstream_checked_at IS NOT NULL ORDER BY upstream_checked_at DESC LIMIT 1",
                (sid,),
            ).fetchone()
            newest = db.execute(
                "SELECT max(r.observed_at) AS instant FROM profile_revisions r JOIN raw_artifacts a ON a.artifact_id=r.raw_artifact_id WHERE a.source_id=%s AND r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL",
                (sid,),
            ).fetchone()["instant"]
            queue = db.execute(
                "SELECT count(*) AS n,min(e.created_at) AS oldest FROM event_outbox e JOIN raw_artifacts a ON a.artifact_id::text=e.aggregate_key WHERE e.event_type='raw.received' AND a.source_id=%s AND NOT EXISTS(SELECT 1 FROM consumer_inbox i WHERE i.consumer_name='argo-normalizer-v1' AND i.event_id=e.event_id)",
                (sid,),
            ).fetchone()
            qc = db.execute(
                "SELECT count(*) AS n FROM qc_rejections WHERE source_id=%s", (sid,)
            ).fetchone()["n"]
            report = evaluate(
                source["metadata"],
                latest,
                successful,
                newest,
                queue["n"],
                queue["oldest"],
                qc,
                now,
            )
            db.execute(
                "INSERT INTO source_health VALUES(%s,%s,%s) ON CONFLICT(source_id) DO UPDATE SET checked_at=excluded.checked_at,report=excluded.report",
                (sid, now, Jsonb(report)),
            )
    return datetime.now(timezone.utc).isoformat()
