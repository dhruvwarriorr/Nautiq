ALTER TABLE calculations DROP CONSTRAINT calculations_kind_check;
ALTER TABLE calculations ADD CONSTRAINT calculations_kind_check CHECK(kind IN ('normalization','profile_summary','training_snapshot','climatology_fit','climatology_comparison','expected_state_fit','expected_state_comparison','uncertainty_fit','uncertainty_comparison','uncertainty_monitor'));
CREATE TABLE uncertainty_releases (
 release_id uuid PRIMARY KEY, release_sha256 text NOT NULL UNIQUE CHECK(release_sha256 ~ '^[a-f0-9]{64}$'),
 expected_id uuid NOT NULL REFERENCES expected_state_releases(release_id), reference_id uuid NOT NULL REFERENCES climatology_releases(release_id),
 snapshot_id uuid NOT NULL REFERENCES training_snapshots, calculation_id uuid NOT NULL REFERENCES calculations,
 manifest jsonb NOT NULL, bundle_key text NOT NULL, bundle_sha256 text NOT NULL CHECK(bundle_sha256 ~ '^[a-f0-9]{64}$'),
 report_key text NOT NULL, report_sha256 text NOT NULL CHECK(report_sha256 ~ '^[a-f0-9]{64}$'), report jsonb NOT NULL,
 status text NOT NULL CHECK(status IN ('ready','unsupported')), release_approved boolean NOT NULL DEFAULT false CHECK(NOT release_approved),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE uncertainty_tracking (
 release_id uuid PRIMARY KEY REFERENCES uncertainty_releases, run_id text NOT NULL, registered_model text NOT NULL, model_version text NOT NULL, performance jsonb NOT NULL DEFAULT '{}', logged_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE uncertainty_selection (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton), release_id uuid NOT NULL REFERENCES uncertainty_releases, selected_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE uncertainty_jobs (
 job_id uuid PRIMARY KEY, profile_id uuid NOT NULL REFERENCES profiles, revision_sha256 text NOT NULL,
 release_id uuid NOT NULL REFERENCES uncertainty_releases, status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','running','complete','obsolete','quarantined')),
 lease_until timestamptz, lease_token uuid, attempts integer NOT NULL DEFAULT 0, next_attempt_at timestamptz NOT NULL DEFAULT now(),
 completed_at timestamptz, reason_code text, created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(profile_id,revision_sha256,release_id),
 FOREIGN KEY(profile_id,revision_sha256) REFERENCES profile_revisions(profile_id,revision_sha256)
);
CREATE INDEX uncertainty_jobs_pending ON uncertainty_jobs(next_attempt_at) WHERE status IN ('pending','running');
CREATE TABLE uncertainty_comparisons (
 profile_id uuid NOT NULL, revision_sha256 text NOT NULL, release_id uuid NOT NULL REFERENCES uncertainty_releases,
 calculation_id uuid NOT NULL REFERENCES calculations, result jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(profile_id,revision_sha256,release_id), FOREIGN KEY(profile_id,revision_sha256) REFERENCES profile_revisions(profile_id,revision_sha256)
);
CREATE TABLE uncertainty_health (
 release_id uuid PRIMARY KEY REFERENCES uncertainty_releases, checked_at timestamptz NOT NULL,
 calculation_id uuid NOT NULL REFERENCES calculations, report jsonb NOT NULL
);
CREATE FUNCTION invalidate_uncertainty_reference() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 UPDATE calculations SET state='stale' WHERE kind IN ('uncertainty_comparison','uncertainty_monitor') AND state='current';
 UPDATE calculations c SET state='current' FROM uncertainty_comparisons p
 JOIN profile_revisions r USING(profile_id,revision_sha256) JOIN uncertainty_selection s ON s.release_id=p.release_id
 JOIN uncertainty_releases u ON u.release_id=s.release_id JOIN expected_state_selection e ON e.release_id=u.expected_id
 JOIN climatology_selection b ON b.release_id=u.reference_id
 WHERE c.calculation_id=p.calculation_id AND r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL;
 RETURN NEW;
END $$;
CREATE TRIGGER uncertainty_expected_changed AFTER INSERT OR UPDATE ON expected_state_selection FOR EACH ROW EXECUTE FUNCTION invalidate_uncertainty_reference();
CREATE TRIGGER uncertainty_climatology_changed AFTER INSERT OR UPDATE ON climatology_selection FOR EACH ROW EXECUTE FUNCTION invalidate_uncertainty_reference();
INSERT INTO platform_schema_version(version) VALUES (8);
