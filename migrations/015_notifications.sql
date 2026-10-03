ALTER TABLE product_accounts ADD COLUMN notification_email text;
ALTER TABLE product_accounts ADD COLUMN email_verified_at timestamptz;
ALTER TABLE product_accounts ADD COLUMN email_version bigint NOT NULL DEFAULT 1;
CREATE TABLE notification_email_challenges (
 owner_id uuid PRIMARY KEY REFERENCES product_accounts ON DELETE CASCADE,
 email text NOT NULL, proof_sha256 text NOT NULL CHECK(proof_sha256 ~ '^[a-f0-9]{64}$'),
 expires_at timestamptz NOT NULL, attempts integer NOT NULL DEFAULT 0,
 created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE product_alerts DROP CONSTRAINT product_alerts_state_check;
ALTER TABLE product_alerts ADD CONSTRAINT product_alerts_state_check CHECK(state IN ('new','active','updated','escalated','recovered','corrected'));
ALTER TABLE product_alerts ADD COLUMN supersedes uuid REFERENCES product_alerts ON DELETE SET NULL;
CREATE TABLE notification_rule_state (
 rule_id uuid PRIMARY KEY REFERENCES product_objects ON DELETE CASCADE,
 state jsonb NOT NULL DEFAULT '{}', rule_version bigint NOT NULL DEFAULT 0,
 watch_version bigint NOT NULL DEFAULT 0, route_version bigint NOT NULL DEFAULT 0,
 next_evaluation_at timestamptz NOT NULL DEFAULT now(),
 lease_id uuid, lease_expires_at timestamptz,
 last_evaluated_at timestamptz, last_outcome text, last_reason text,
 last_alert_id uuid REFERENCES product_alerts ON DELETE SET NULL
);
CREATE INDEX notification_rules_due ON notification_rule_state(next_evaluation_at);
CREATE TABLE notification_evaluations (
 evaluation_id uuid PRIMARY KEY, owner_id uuid NOT NULL REFERENCES product_accounts ON DELETE CASCADE,
 rule_id uuid NOT NULL REFERENCES product_objects ON DELETE CASCADE, rule_version bigint NOT NULL,
 outcome text NOT NULL CHECK(outcome IN ('triggered','clear','unknown','corrected')),
 evidence jsonb NOT NULL, evidence_bytes bytea NOT NULL CHECK(octet_length(evidence_bytes)<=32768),
 evidence_sha256 text NOT NULL CHECK(evidence_sha256 ~ '^[a-f0-9]{64}$'),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX notification_evaluations_owner ON notification_evaluations(owner_id,created_at);
CREATE TABLE notification_evidence_blobs (
 owner_id uuid NOT NULL REFERENCES product_accounts ON DELETE CASCADE,
 sha256 text NOT NULL CHECK(sha256 ~ '^[a-f0-9]{64}$'),
 raw_bytes bytea NOT NULL CHECK(octet_length(raw_bytes)<=900000),
 created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(owner_id,sha256)
);
CREATE TABLE notification_deliveries (
 delivery_id uuid PRIMARY KEY, alert_id uuid NOT NULL REFERENCES product_alerts ON DELETE CASCADE,
 owner_id uuid NOT NULL REFERENCES product_accounts ON DELETE CASCADE,
 channel text NOT NULL CHECK(channel IN ('in_app','email')),
 state text NOT NULL CHECK(state IN ('pending','sending','sent','failed','blocked','cancelled')),
 attempts integer NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 5),
 next_attempt_at timestamptz NOT NULL DEFAULT now(), lease_id uuid, lease_expires_at timestamptz,
 email_version bigint, destination text, reason text, sent_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(alert_id,channel)
);
CREATE INDEX notification_deliveries_due ON notification_deliveries(next_attempt_at) WHERE state IN ('pending','sending');
CREATE TABLE notification_worker_health (
 worker_id uuid PRIMARY KEY, started_at timestamptz NOT NULL DEFAULT now(),
 heartbeat_at timestamptz NOT NULL DEFAULT now(), success_at timestamptz,
 last_error text, smtp_configured boolean NOT NULL DEFAULT false
);
INSERT INTO platform_schema_version(version) VALUES (15);
