ALTER TABLE calculations DROP CONSTRAINT calculations_kind_check;
ALTER TABLE calculations ADD CONSTRAINT calculations_kind_check CHECK(kind IN ('normalization','profile_summary','training_snapshot','climatology_fit','climatology_comparison','expected_state_fit','expected_state_comparison','uncertainty_fit','uncertainty_comparison','uncertainty_monitor','anomaly_fit','anomaly_comparison','field_normalization'));
CREATE TABLE field_products (
 product_id text PRIMARY KEY CHECK(product_id IN ('noaa_oisst','noaa_gfs_wave','noaa_gfs_weather','hycom_espc')),
 metadata jsonb NOT NULL
);
INSERT INTO field_products VALUES ('noaa_oisst','{}'),('noaa_gfs_wave','{}'),('noaa_gfs_weather','{}'),('hycom_espc','{}');
CREATE TABLE field_releases (
 release_id uuid PRIMARY KEY, release_sha256 text UNIQUE NOT NULL CHECK(release_sha256 ~ '^[a-f0-9]{64}$'),
 product_id text NOT NULL REFERENCES field_products, calculation_id uuid NOT NULL REFERENCES calculations,
 cycle timestamptz, valid_time_start timestamptz NOT NULL, valid_time_end timestamptz NOT NULL,
 source_version text NOT NULL CHECK(source_version IN ('preliminary','final','forecast')),
 manifest_key text NOT NULL, manifest_sha256 text NOT NULL CHECK(manifest_sha256 ~ '^[a-f0-9]{64}$'), manifest jsonb NOT NULL,
 status text NOT NULL DEFAULT 'ready' CHECK(status IN ('ready','unavailable')),
 release_approved boolean NOT NULL DEFAULT false CHECK(NOT release_approved), created_at timestamptz NOT NULL DEFAULT now(),
 CHECK(valid_time_end>=valid_time_start),
 CHECK((product_id='noaa_oisst' AND cycle IS NULL AND source_version IN ('preliminary','final')) OR (product_id<>'noaa_oisst' AND cycle IS NOT NULL AND source_version='forecast')),
 UNIQUE(product_id,release_id)
);
CREATE INDEX field_catalog_time ON field_releases(product_id,valid_time_start DESC,created_at DESC);
CREATE TABLE field_selection (
 product_id text PRIMARY KEY REFERENCES field_products, release_id uuid NOT NULL,
 selected_at timestamptz NOT NULL DEFAULT now(), FOREIGN KEY(product_id,release_id) REFERENCES field_releases(product_id,release_id)
);
CREATE TABLE field_ingestion_runs (
 run_id uuid PRIMARY KEY, product_id text NOT NULL REFERENCES field_products, started_at timestamptz NOT NULL DEFAULT now(),
 completed_at timestamptz, status text NOT NULL CHECK(status IN ('running','complete','failed')), reason_code text,
 release_id uuid REFERENCES field_releases, upstream_checked_at timestamptz
);
CREATE INDEX field_run_recent ON field_ingestion_runs(product_id,started_at DESC);
INSERT INTO platform_schema_version(version) VALUES (10);
