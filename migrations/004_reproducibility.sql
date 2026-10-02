ALTER TABLE ingestion_runs ADD COLUMN scope text;
ALTER TABLE ingestion_runs ADD COLUMN run_kind text NOT NULL DEFAULT 'legacy' CHECK(run_kind IN ('legacy','live','backfill','reconciled'));
ALTER TABLE ingestion_runs ADD COLUMN upstream_checked_at timestamptz;
ALTER TABLE ingestion_runs ADD COLUMN reason_code text;
UPDATE sources SET metadata=metadata || '{"catalog_version":"argo-source-v1","expected_update_hours":24,"cadence_verified":false,"freshness_budget_hours":null,"ingestion_budget_hours":14,"coverage_state":"unverified","license_state":"public_unrestricted_with_acknowledgement"}'::jsonb WHERE source_id='argo_gdac';
CREATE TABLE qc_rejections (
 rejection_id uuid PRIMARY KEY, artifact_id uuid REFERENCES raw_artifacts, source_id text NOT NULL REFERENCES sources,
 profile_index integer, variable text, rule_id text NOT NULL, reason_code text NOT NULL,
 qc_version text NOT NULL, normalizer_version text NOT NULL, rejected_count integer NOT NULL CHECK(rejected_count>0),
 context jsonb NOT NULL DEFAULT '{}', created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX qc_rejection_source_time ON qc_rejections(source_id,created_at DESC,rejection_id);
INSERT INTO qc_rejections(rejection_id,artifact_id,source_id,rule_id,reason_code,qc_version,normalizer_version,rejected_count,context)
SELECT q.quarantine_id,q.artifact_id,'argo_gdac','legacy.quarantine',q.reason_code,'argo-display-1-v1','argo-original-levels-v1',1,'{"legacy_context":true}'::jsonb
FROM ingestion_quarantine q;
CREATE TABLE calculations (
 calculation_id uuid PRIMARY KEY, calculation_sha256 text UNIQUE NOT NULL CHECK(calculation_sha256 ~ '^[a-f0-9]{64}$'),
 kind text NOT NULL CHECK(kind IN ('normalization','profile_summary','training_snapshot')),
 method_version text NOT NULL, manifest jsonb NOT NULL,
 manifest_key text NOT NULL, manifest_sha256 text NOT NULL CHECK(manifest_sha256 ~ '^[a-f0-9]{64}$'),
 state text NOT NULL CHECK(state IN ('current','stale','frozen')), created_at timestamptz NOT NULL DEFAULT now(),
 superseded_by uuid REFERENCES calculations
);
CREATE TABLE calculation_inputs (
 calculation_id uuid NOT NULL REFERENCES calculations, profile_id uuid NOT NULL,
 revision_sha256 text NOT NULL, PRIMARY KEY(calculation_id,profile_id,revision_sha256),
 FOREIGN KEY(profile_id,revision_sha256) REFERENCES profile_revisions(profile_id,revision_sha256)
);
CREATE INDEX calculation_input_revision ON calculation_inputs(profile_id,revision_sha256);
ALTER TABLE profile_revisions ADD COLUMN calculation_id uuid REFERENCES calculations;
CREATE TABLE recomputation_jobs (
 job_id uuid PRIMARY KEY, profile_id uuid NOT NULL REFERENCES profiles, revision_sha256 text NOT NULL,
 method_version text NOT NULL, status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','running','complete','obsolete','quarantined')),
 lease_until timestamptz, lease_token uuid, attempts integer NOT NULL DEFAULT 0,
 next_attempt_at timestamptz NOT NULL DEFAULT now(), created_at timestamptz NOT NULL DEFAULT now(),
 completed_at timestamptz, reason_code text, calculation_id uuid REFERENCES calculations,
 UNIQUE(profile_id,revision_sha256,method_version),
 FOREIGN KEY(profile_id,revision_sha256) REFERENCES profile_revisions(profile_id,revision_sha256)
);
CREATE INDEX recomputation_pending ON recomputation_jobs(next_attempt_at) WHERE status IN ('pending','running');
CREATE TABLE profile_statistics (
 profile_id uuid PRIMARY KEY REFERENCES profiles, revision_sha256 text NOT NULL,
 calculation_id uuid NOT NULL REFERENCES calculations, statistics jsonb NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(profile_id,revision_sha256) REFERENCES profile_revisions(profile_id,revision_sha256)
);
CREATE TABLE source_health (
 source_id text PRIMARY KEY REFERENCES sources, checked_at timestamptz NOT NULL, report jsonb NOT NULL
);
CREATE TABLE training_snapshots (
 snapshot_id uuid PRIMARY KEY, snapshot_sha256 text UNIQUE NOT NULL CHECK(snapshot_sha256 ~ '^[a-f0-9]{64}$'),
 calculation_id uuid NOT NULL REFERENCES calculations, manifest jsonb NOT NULL,
 manifest_key text NOT NULL, manifest_sha256 text NOT NULL CHECK(manifest_sha256 ~ '^[a-f0-9]{64}$'),
 parquet_key text NOT NULL, parquet_sha256 text NOT NULL CHECK(parquet_sha256 ~ '^[a-f0-9]{64}$'),
 size_bytes bigint NOT NULL CHECK(size_bytes BETWEEN 1 AND 134217728),
 profile_count integer NOT NULL CHECK(profile_count>=0), row_count integer NOT NULL CHECK(row_count>=0),
 created_at timestamptz NOT NULL DEFAULT now()
);
-- Frozen snapshots never become live mutable datasets. Jobs are seeded for retained current revisions.
INSERT INTO recomputation_jobs(job_id,profile_id,revision_sha256,method_version)
SELECT revision_id,profile_id,revision_sha256,'original-level-summary-v1'
FROM profile_revisions WHERE selected_at IS NOT NULL AND superseded_at IS NULL;
INSERT INTO platform_schema_version(version) VALUES (4);
