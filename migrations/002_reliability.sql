-- Foundation only: publishers/consumers are introduced with the data slice.
CREATE TABLE IF NOT EXISTS event_outbox (
    event_id uuid PRIMARY KEY,
    event_type text NOT NULL CHECK (length(event_type) BETWEEN 1 AND 100),
    schema_version integer NOT NULL CHECK (schema_version > 0),
    aggregate_key text NOT NULL CHECK (length(aggregate_key) BETWEEN 1 AND 256),
    revision_sha256 text NOT NULL CHECK (revision_sha256 ~ '^[a-f0-9]{64}$'),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object' AND octet_length(payload::text) <= 262144),
    created_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    next_attempt_at timestamptz NOT NULL DEFAULT now(),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    lease_until timestamptz,
    UNIQUE (event_type, aggregate_key, revision_sha256)
);
CREATE INDEX IF NOT EXISTS event_outbox_pending ON event_outbox(next_attempt_at, created_at)
    WHERE published_at IS NULL;
CREATE TABLE IF NOT EXISTS consumer_inbox (
    consumer_name text NOT NULL CHECK (length(consumer_name) BETWEEN 1 AND 100),
    event_id uuid NOT NULL,
    processed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (consumer_name, event_id)
);
INSERT INTO platform_schema_version(version) VALUES (2) ON CONFLICT DO NOTHING;
