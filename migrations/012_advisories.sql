ALTER TABLE calculations DROP CONSTRAINT calculations_kind_check;
ALTER TABLE calculations ADD CONSTRAINT calculations_kind_check CHECK(kind IN ('normalization','profile_summary','training_snapshot','climatology_fit','climatology_comparison','expected_state_fit','expected_state_comparison','uncertainty_fit','uncertainty_comparison','uncertainty_monitor','anomaly_fit','anomaly_comparison','field_normalization','event_history','event_baseline','event_detection','advisory_ingestion'));
CREATE TABLE advisory_requests (url text PRIMARY KEY, receipt jsonb NOT NULL);
CREATE TABLE advisory_runs (
 run_id uuid PRIMARY KEY, source_id text NOT NULL, checked_at timestamptz NOT NULL,
 report jsonb NOT NULL, report_key text NOT NULL, report_sha256 text NOT NULL CHECK(report_sha256 ~ '^[a-f0-9]{64}$'),
 calculation_id uuid NOT NULL REFERENCES calculations, integrity text NOT NULL DEFAULT 'ready' CHECK(integrity IN ('ready','unavailable')),
 UNIQUE(source_id,checked_at)
);
CREATE TABLE advisory_revisions (
 revision_id uuid PRIMARY KEY, source_id text NOT NULL, sender text NOT NULL, identifier text NOT NULL, sent timestamptz NOT NULL,
 raw_sha256 text NOT NULL CHECK(raw_sha256 ~ '^[a-f0-9]{64}$'), raw_key text NOT NULL, raw_bytes integer NOT NULL CHECK(raw_bytes BETWEEN 1 AND 1048576),
 document jsonb NOT NULL, first_run_id uuid NOT NULL REFERENCES advisory_runs,
 UNIQUE(source_id,sender,identifier,sent,raw_sha256)
);
CREATE INDEX advisory_identity ON advisory_revisions(source_id,sender,identifier,sent);
CREATE TABLE advisory_run_members (run_id uuid NOT NULL REFERENCES advisory_runs, revision_id uuid NOT NULL REFERENCES advisory_revisions, PRIMARY KEY(run_id,revision_id));
CREATE TABLE advisory_sources (
 source_id text PRIMARY KEY, policy jsonb NOT NULL, latest_run_id uuid REFERENCES advisory_runs, checked_at timestamptz,
 transport text NOT NULL DEFAULT 'unconfigured' CHECK(transport IN ('unconfigured','healthy','partial','failed')),
 reasons jsonb NOT NULL DEFAULT '[]', updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE advisory_geometry (
 revision_id uuid NOT NULL REFERENCES advisory_revisions, info_index integer NOT NULL, area_index integer NOT NULL,
 effective timestamptz NOT NULL, expires timestamptz, geometry geometry(Geometry,4326), center geography(Point,4326), radius_m double precision,
 CHECK((geometry IS NOT NULL AND center IS NULL AND radius_m IS NULL) OR (geometry IS NULL AND center IS NOT NULL AND radius_m BETWEEN 0 AND 20000000))
);
CREATE INDEX advisory_geometry_spatial ON advisory_geometry USING gist(geometry);
CREATE INDEX advisory_circle_spatial ON advisory_geometry USING gist(center);
INSERT INTO platform_schema_version(version) VALUES (12);
