ALTER TABLE calculations DROP CONSTRAINT calculations_kind_check;
ALTER TABLE calculations ADD CONSTRAINT calculations_kind_check CHECK(kind IN ('normalization','profile_summary','training_snapshot','climatology_fit','climatology_comparison','expected_state_fit','expected_state_comparison','uncertainty_fit','uncertainty_comparison','uncertainty_monitor','anomaly_fit','anomaly_comparison','field_normalization','event_history','event_baseline','event_detection','advisory_ingestion','trip_assessment'));
CREATE TABLE trip_calculations (
 calculation_id uuid PRIMARY KEY REFERENCES calculations,
 access_sha256 text NOT NULL CHECK(access_sha256 ~ '^[a-f0-9]{64}$'),
 verdict jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 production_approved boolean NOT NULL DEFAULT false CHECK(NOT production_approved)
);
INSERT INTO platform_schema_version(version) VALUES (13);
