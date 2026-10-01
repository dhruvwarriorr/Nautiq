"""Local broker outage and expired-lease check using one already committed event.

Briefly stops only local NATS/ingestion; finally restores services and leaves all
raw/canonical data untouched. Requires a drained, running Phase 2 stack.
"""

import json
import subprocess
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def compose(*args, check=True):
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=ROOT,
        check=check,
        capture_output=True,
        text=True,
    )


def sql(query):
    result = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "postgres",
            "sh",
            "-ec",
            'psql -X -qAt -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1',
        ],
        cwd=ROOT,
        input=query,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def counts():
    return sql(
        "SELECT json_build_array((SELECT count(*) FROM profiles),(SELECT count(*) FROM profile_revisions),(SELECT count(*) FROM consumer_inbox));"
    )


def main():
    saved = None
    event = None
    try:
        for attempt in range(60):
            if (
                sql("SELECT count(*) FROM event_outbox WHERE published_at IS NULL;")
                == "0"
            ):
                break
            time.sleep(1)
        else:
            raise AssertionError("Drain existing outbox before outage verification")
        compose("stop", "ingestion")
        before = counts()
        saved = json.loads(
            sql(
                "SELECT row_to_json(e) FROM event_outbox e JOIN consumer_inbox i ON i.event_id=e.event_id AND i.consumer_name='argo-normalizer-v1' WHERE e.event_type='raw.received' AND e.published_at IS NOT NULL ORDER BY e.created_at LIMIT 1;"
            )
        )
        event = str(uuid.UUID(saved["event_id"]))
        compose("stop", "nats")
        sql(
            f"UPDATE event_outbox SET published_at=NULL,next_attempt_at=now(),lease_until=now()+interval '30 minutes' WHERE event_id='{event}';"
        )
        failed = compose(
            "run", "--rm", "--no-deps", "ingestion", "--dispatch-only", check=False
        )
        assert failed.returncode != 0, "Broker failure reported successful publication"
        assert (
            sql(
                f"SELECT published_at IS NULL FROM event_outbox WHERE event_id='{event}';"
            )
            == "t"
        )
        compose("start", "nats")
        # A live lease must remain unclaimed even after the broker recovers.
        for attempt in range(15):
            healthy = compose(
                "run", "--rm", "--no-deps", "ingestion", "--dispatch-only", check=False
            )
            if healthy.returncode == 0:
                break
            time.sleep(1)
        else:
            raise AssertionError("Broker did not recover")
        assert (
            sql(
                f"SELECT published_at IS NULL FROM event_outbox WHERE event_id='{event}';"
            )
            == "t"
        )
        sql(
            f"UPDATE event_outbox SET lease_until=now()-interval '1 second' WHERE event_id='{event}';"
        )
        compose("run", "--rm", "--no-deps", "ingestion", "--dispatch-only")
        assert (
            sql(
                f"SELECT published_at IS NOT NULL AND lease_until IS NULL FROM event_outbox WHERE event_id='{event}';"
            )
            == "t"
        )
        assert counts() == before, "Committed replay changed canonical identities"
        print(
            "Local broker passed: outage leaves outbox unpublished, active lease respected, expired lease reclaimed, broker ack precedes published marker, committed replay creates no canonical duplicates"
        )
    finally:
        if saved is not None and event is not None:
            # Keep the verified new ack timestamp; restore the original ack if verification failed.
            stamp = saved["published_at"]
            sql(
                f"UPDATE event_outbox SET published_at=coalesce(published_at,'{stamp}'::timestamptz),lease_until=NULL,next_attempt_at=now() WHERE event_id='{event}';"
            )
        compose("up", "-d", "nats", "normalizer", "ingestion")


if __name__ == "__main__":
    main()
