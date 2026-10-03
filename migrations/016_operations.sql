CREATE TABLE operations_controls (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 revision bigint NOT NULL DEFAULT 1,
 paused jsonb NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(paused)='object'),
 updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO operations_controls(singleton) VALUES(true);
CREATE TABLE operations_audit (
 audit_id uuid PRIMARY KEY,
 action text NOT NULL CHECK(action IN ('pause','resume','rollback_started','rollback_completed','rollback_failed','restore_completed')),
 scope text NOT NULL, reason text NOT NULL CHECK(reason ~ '^[a-z][a-z0-9_]{2,63}$'),
 actor text NOT NULL CHECK(actor ~ '^[a-zA-Z0-9_.-]{1,64}$'),
 before_state jsonb NOT NULL, after_state jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX operations_audit_time ON operations_audit(created_at);
INSERT INTO platform_schema_version(version) VALUES(16);
