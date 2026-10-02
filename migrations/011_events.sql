ALTER TABLE calculations DROP CONSTRAINT calculations_kind_check;
ALTER TABLE calculations ADD CONSTRAINT calculations_kind_check CHECK(kind IN ('normalization','profile_summary','training_snapshot','climatology_fit','climatology_comparison','expected_state_fit','expected_state_comparison','uncertainty_fit','uncertainty_comparison','uncertainty_monitor','anomaly_fit','anomaly_comparison','field_normalization','event_history','event_baseline','event_detection'));
CREATE TABLE event_source_requests (
 url text PRIMARY KEY CHECK(length(url)<2048), receipt jsonb NOT NULL, checked_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE event_datasets (
 dataset_id uuid PRIMARY KEY, dataset_sha256 text UNIQUE NOT NULL CHECK(dataset_sha256 ~ '^[a-f0-9]{64}$'),
 kind text NOT NULL CHECK(kind IN ('history','baseline')), parent_id uuid REFERENCES event_datasets,
 calculation_id uuid NOT NULL REFERENCES calculations,
 manifest jsonb NOT NULL, manifest_key text NOT NULL, manifest_sha256 text NOT NULL CHECK(manifest_sha256 ~ '^[a-f0-9]{64}$'),
 status text NOT NULL DEFAULT 'ready' CHECK(status IN ('ready','unavailable')), created_at timestamptz NOT NULL DEFAULT now(),
 CHECK((kind='history' AND parent_id IS NULL) OR (kind='baseline' AND parent_id IS NOT NULL))
);
CREATE TABLE event_runs (
 run_id uuid PRIMARY KEY, run_sha256 text UNIQUE NOT NULL CHECK(run_sha256 ~ '^[a-f0-9]{64}$'),
 kind text NOT NULL CHECK(kind IN ('surface_thermal','profile_groups')),
 baseline_id uuid REFERENCES event_datasets, history_id uuid REFERENCES event_datasets,
 anomaly_id uuid REFERENCES anomaly_releases(release_id),
 calculation_id uuid NOT NULL REFERENCES calculations, manifest jsonb NOT NULL,
 report jsonb NOT NULL, report_key text NOT NULL, report_sha256 text NOT NULL CHECK(report_sha256 ~ '^[a-f0-9]{64}$'),
 status text NOT NULL DEFAULT 'ready' CHECK(status IN ('ready','unavailable')),
 release_approved boolean NOT NULL DEFAULT false CHECK(NOT release_approved), created_at timestamptz NOT NULL DEFAULT now(),
 CHECK((kind='surface_thermal' AND baseline_id IS NOT NULL AND history_id IS NOT NULL AND anomaly_id IS NULL) OR
       (kind='profile_groups' AND baseline_id IS NULL AND history_id IS NULL AND anomaly_id IS NOT NULL))
);
CREATE TABLE regional_events (
 event_id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES event_runs,
 kind text NOT NULL CHECK(kind IN ('surface_thermal_candidate','regional_profile_candidate','isolated_profile_anomalies')),
 variable text NOT NULL, start_day date NOT NULL, end_day date NOT NULL CHECK(end_day>=start_day),
 geometry geometry(Geometry,4326) NOT NULL, evidence jsonb NOT NULL
);
CREATE INDEX regional_events_geometry ON regional_events USING gist(geometry);
CREATE INDEX regional_events_window ON regional_events(start_day,end_day);
CREATE TABLE event_profile_inputs (
 run_id uuid NOT NULL REFERENCES event_runs, profile_id uuid NOT NULL, revision_sha256 text NOT NULL,
 calculation_id uuid REFERENCES calculations,
 PRIMARY KEY(run_id,profile_id), FOREIGN KEY(profile_id,revision_sha256) REFERENCES profile_revisions(profile_id,revision_sha256)
);
INSERT INTO platform_schema_version(version) VALUES (11);
