CREATE TABLE product_accounts (
 account_id uuid PRIMARY KEY, handle text NOT NULL UNIQUE CHECK(handle ~ '^[a-z0-9_]{3,32}$'),
 password_salt bytea NOT NULL CHECK(octet_length(password_salt)=16), password_hash bytea NOT NULL CHECK(octet_length(password_hash)=32),
 notifications_enabled boolean NOT NULL DEFAULT true, version bigint NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE product_sessions (
 token_sha256 text PRIMARY KEY CHECK(token_sha256 ~ '^[a-f0-9]{64}$'), account_id uuid NOT NULL REFERENCES product_accounts ON DELETE CASCADE,
 created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL, last_seen_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX product_sessions_owner ON product_sessions(account_id);
CREATE TABLE product_rate_limits (key_sha256 text NOT NULL, window_start timestamptz NOT NULL, attempts integer NOT NULL, PRIMARY KEY(key_sha256,window_start));
CREATE TABLE product_objects (
 object_id uuid PRIMARY KEY, owner_id uuid NOT NULL REFERENCES product_accounts ON DELETE CASCADE,
 kind text NOT NULL CHECK(kind IN ('routes','watchlists','alert-rules')), name text NOT NULL CHECK(length(name) BETWEEN 1 AND 80),
 data jsonb NOT NULL, version bigint NOT NULL DEFAULT 1, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), deleted_at timestamptz,
 UNIQUE(object_id,owner_id)
);
CREATE INDEX product_objects_owner ON product_objects(owner_id,kind,created_at,object_id) WHERE deleted_at IS NULL;
CREATE TABLE product_idempotency (
 owner_id uuid NOT NULL REFERENCES product_accounts ON DELETE CASCADE, key uuid NOT NULL,
 action text NOT NULL, request_sha256 text NOT NULL, status integer NOT NULL, response jsonb NOT NULL,
 expires_at timestamptz NOT NULL DEFAULT now()+interval '24 hours', PRIMARY KEY(owner_id,key)
);
CREATE TABLE product_trip_links (
 calculation_id uuid PRIMARY KEY REFERENCES trip_calculations, owner_id uuid NOT NULL REFERENCES product_accounts ON DELETE CASCADE,
 name text NOT NULL CHECK(length(name) BETWEEN 1 AND 80), created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(calculation_id,owner_id)
);
CREATE TABLE product_alerts (
 alert_id uuid PRIMARY KEY, owner_id uuid NOT NULL REFERENCES product_accounts ON DELETE CASCADE, rule_id uuid NOT NULL,
 rule_version bigint NOT NULL, event_revision text NOT NULL, state text NOT NULL CHECK(state IN ('new','active','updated','escalated','recovered')),
 evidence jsonb NOT NULL, evidence_bytes bytea NOT NULL CHECK(octet_length(evidence_bytes)<=32768), evidence_sha256 text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), acknowledged_at timestamptz,
 FOREIGN KEY(rule_id,owner_id) REFERENCES product_objects(object_id,owner_id), UNIQUE(owner_id,rule_id,rule_version,event_revision)
);
CREATE TABLE product_jobs (
 job_id uuid PRIMARY KEY, owner_id uuid NOT NULL REFERENCES product_accounts ON DELETE CASCADE,
 kind text NOT NULL CHECK(kind IN ('exports','reports')), format text NOT NULL CHECK(format IN ('json','csv','parquet','html','netcdf')),
 state text NOT NULL CHECK(state IN ('queued','running','ready','blocked','failed','cancelled','expired')),
 input jsonb NOT NULL, input_bytes bytea NOT NULL CHECK(octet_length(input_bytes)<=4194304), input_sha256 text NOT NULL, version bigint NOT NULL DEFAULT 1, attempts integer NOT NULL DEFAULT 0,
 lease_id uuid, lease_expires_at timestamptz, reason text, object_key text, artifact_sha256 text, artifact_bytes bigint CHECK(artifact_bytes BETWEEN 0 AND 8388608),
 created_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz, expires_at timestamptz NOT NULL DEFAULT now()+interval '72 hours',
 UNIQUE(job_id,owner_id)
);
CREATE INDEX product_jobs_pending ON product_jobs(state,created_at) WHERE state IN ('queued','running');
CREATE TABLE product_download_grants (
 grant_id uuid PRIMARY KEY, job_id uuid NOT NULL, owner_id uuid NOT NULL REFERENCES product_accounts ON DELETE CASCADE,
 expires_at timestamptz NOT NULL DEFAULT now()+interval '5 minutes', used_at timestamptz,
 FOREIGN KEY(job_id,owner_id) REFERENCES product_jobs(job_id,owner_id) ON DELETE CASCADE
);
CREATE TABLE product_object_gc (object_key text PRIMARY KEY, queued_at timestamptz NOT NULL DEFAULT now());
INSERT INTO platform_schema_version(version) VALUES (14);
