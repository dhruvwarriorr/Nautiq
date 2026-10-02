ALTER TABLE calculations DROP CONSTRAINT calculations_kind_check;
ALTER TABLE calculations ADD CONSTRAINT calculations_kind_check CHECK(kind IN ('normalization','profile_summary','training_snapshot','climatology_fit','climatology_comparison','expected_state_fit','expected_state_comparison'));
CREATE TABLE expected_state_releases (
 release_id uuid PRIMARY KEY,
 release_sha256 text NOT NULL UNIQUE CHECK(release_sha256 ~ '^[a-f0-9]{64}$'),
 reference_id uuid NOT NULL REFERENCES climatology_releases(release_id),
 snapshot_id uuid NOT NULL REFERENCES training_snapshots,
 calculation_id uuid NOT NULL REFERENCES calculations,
 manifest jsonb NOT NULL,
 bundle_key text NOT NULL, bundle_sha256 text NOT NULL CHECK(bundle_sha256 ~ '^[a-f0-9]{64}$'),
 report_key text NOT NULL, report_sha256 text NOT NULL CHECK(report_sha256 ~ '^[a-f0-9]{64}$'),
 report jsonb NOT NULL,
 status text NOT NULL CHECK(status IN ('ready','unsupported')),
 release_approved boolean NOT NULL DEFAULT false CHECK(NOT release_approved),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE expected_state_tracking (
 release_id uuid PRIMARY KEY REFERENCES expected_state_releases,
 run_id text NOT NULL, registered_model text NOT NULL, model_version text NOT NULL,
 logged_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE expected_state_selection (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 release_id uuid NOT NULL REFERENCES expected_state_releases,
 selected_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE expected_state_jobs (
 job_id uuid PRIMARY KEY, profile_id uuid NOT NULL REFERENCES profiles,
 revision_sha256 text NOT NULL, release_id uuid NOT NULL REFERENCES expected_state_releases,
 status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','running','complete','obsolete','quarantined')),
 lease_until timestamptz, lease_token uuid, attempts integer NOT NULL DEFAULT 0,
 next_attempt_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz,
 reason_code text, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(profile_id,revision_sha256,release_id),
 FOREIGN KEY(profile_id,revision_sha256) REFERENCES profile_revisions(profile_id,revision_sha256)
);
CREATE INDEX expected_state_jobs_pending ON expected_state_jobs(next_attempt_at) WHERE status IN ('pending','running');
CREATE TABLE expected_state_comparisons (
 profile_id uuid NOT NULL, revision_sha256 text NOT NULL,
 release_id uuid NOT NULL REFERENCES expected_state_releases,
 calculation_id uuid NOT NULL REFERENCES calculations,
 result jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(profile_id,revision_sha256,release_id),
 FOREIGN KEY(profile_id,revision_sha256) REFERENCES profile_revisions(profile_id,revision_sha256)
);
INSERT INTO platform_schema_version(version) VALUES (6);
