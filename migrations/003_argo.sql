CREATE TABLE sources (
 source_id text PRIMARY KEY, metadata jsonb NOT NULL
);
INSERT INTO sources VALUES ('argo_gdac', '{"provider":"Argo GDAC / Ifremer","dataset":"core profiles","authority_class":"A","attribution":"International Argo Program and contributing national programs; doi:10.17882/42182","terms_url":"https://argo.ucsd.edu/data/acknowledging-argo/","source_mode":"historical_or_near_real_time","production_approved":false}'::jsonb);
CREATE TABLE ingestion_runs (
 run_id uuid PRIMARY KEY, source_id text NOT NULL REFERENCES sources,
 started_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz,
 status text NOT NULL DEFAULT 'running', counters jsonb NOT NULL DEFAULT '{}'
);
CREATE TABLE ingestion_cursors (
 scope text PRIMARY KEY, updated_at timestamptz NOT NULL, source_path text NOT NULL,
 index_sha256 text NOT NULL, checked_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE raw_artifacts (
 artifact_id uuid PRIMARY KEY, source_id text NOT NULL REFERENCES sources,
 source_path text NOT NULL, source_url text NOT NULL, source_updated_at timestamptz NOT NULL,
 received_at timestamptz NOT NULL DEFAULT now(), sha256 text NOT NULL CHECK (sha256 ~ '^[a-f0-9]{64}$'),
 object_key text NOT NULL, size_bytes bigint NOT NULL CHECK (size_bytes > 0 AND size_bytes <= 67108864),
 kind text NOT NULL CHECK (kind IN ('index','profile')), run_id uuid NOT NULL REFERENCES ingestion_runs,
 http_metadata jsonb NOT NULL DEFAULT '{}', UNIQUE(source_id, source_path, sha256)
);
CREATE TABLE argo_discoveries (
 scope text NOT NULL, source_path text NOT NULL, source_updated_at timestamptz NOT NULL,
 status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','received','quarantined')),
 artifact_id uuid REFERENCES raw_artifacts, reason_code text,
 PRIMARY KEY(scope,source_path,source_updated_at)
);
CREATE TABLE ingestion_quarantine (
 quarantine_id uuid PRIMARY KEY, event_id uuid UNIQUE, artifact_id uuid REFERENCES raw_artifacts,
 reason_code text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 resolved_at timestamptz
);
CREATE TABLE profiles (
 profile_id uuid PRIMARY KEY, native_key text UNIQUE NOT NULL,
 platform_id text NOT NULL, cycle_number integer NOT NULL CHECK(cycle_number >= 0),
 direction text NOT NULL CHECK(direction IN ('A','D')), sampling_scheme text NOT NULL,
 profile_index integer NOT NULL CHECK(profile_index >= 0)
);
CREATE TABLE profile_revisions (
 revision_id uuid PRIMARY KEY, profile_id uuid NOT NULL REFERENCES profiles,
 revision_sha256 text NOT NULL CHECK(revision_sha256 ~ '^[a-f0-9]{64}$'),
 raw_artifact_id uuid NOT NULL REFERENCES raw_artifacts,
 observed_at timestamptz NOT NULL, received_at timestamptz NOT NULL, source_updated_at timestamptz NOT NULL,
 latitude double precision NOT NULL CHECK(latitude BETWEEN -90 AND 90),
 longitude double precision NOT NULL CHECK(longitude >= -180 AND longitude < 180),
 position geometry(Point,4326) NOT NULL, data_mode text NOT NULL CHECK(data_mode IN ('R','A','D')),
 qc_version text NOT NULL, normalizer_version text NOT NULL, depth_conversion_version text NOT NULL,
 parameter_modes jsonb NOT NULL, levels jsonb NOT NULL CHECK(jsonb_typeof(levels)='array' AND jsonb_array_length(levels) BETWEEN 1 AND 10000),
 parquet_key text NOT NULL, parquet_sha256 text NOT NULL CHECK(parquet_sha256 ~ '^[a-f0-9]{64}$'),
 science_ready boolean NOT NULL DEFAULT false,
 selected_at timestamptz, superseded_at timestamptz,
 UNIQUE(profile_id, revision_sha256)
);
CREATE UNIQUE INDEX profile_current_revision ON profile_revisions(profile_id) WHERE selected_at IS NOT NULL AND superseded_at IS NULL;
CREATE INDEX profile_revision_space ON profile_revisions USING gist(position);
CREATE INDEX profile_revision_time ON profile_revisions(observed_at,profile_id);
CREATE TABLE profile_source_links (
 profile_id uuid NOT NULL REFERENCES profiles, artifact_id uuid NOT NULL REFERENCES raw_artifacts,
 PRIMARY KEY(profile_id,artifact_id)
);
ALTER TABLE event_outbox ADD COLUMN lease_token uuid;
CREATE TABLE argo_index_cache (
 scope text PRIMARY KEY, artifact_id uuid NOT NULL REFERENCES raw_artifacts, etag text, modified text
);
INSERT INTO platform_schema_version(version) VALUES (3);
