ALTER TABLE calculations DROP CONSTRAINT calculations_kind_check;
ALTER TABLE calculations ADD CONSTRAINT calculations_kind_check CHECK(kind IN ('normalization','profile_summary','training_snapshot','climatology_fit','climatology_comparison','expected_state_fit','expected_state_comparison','uncertainty_fit','uncertainty_comparison','uncertainty_monitor','anomaly_fit','anomaly_comparison','field_normalization','event_history','event_baseline','event_detection','advisory_ingestion','trip_assessment','model_monitor'));
-- Monitoring starts investigation; it never selects, retrains, recalibrates or promotes a model.
CREATE TABLE model_monitoring_reports (
 report_id uuid PRIMARY KEY, checked_at timestamptz NOT NULL, calculation_id uuid NOT NULL REFERENCES calculations,
 expected_id uuid REFERENCES expected_state_releases, uncertainty_id uuid REFERENCES uncertainty_releases, anomaly_id uuid REFERENCES anomaly_releases,
 status text NOT NULL CHECK(status IN ('reference_unavailable','insufficient_evidence','within_expectation','investigate')),
 report jsonb NOT NULL, report_sha256 text NOT NULL CHECK(report_sha256 ~ '^[a-f0-9]{64}$'),
 release_approved boolean NOT NULL DEFAULT false CHECK(NOT release_approved), created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX model_monitoring_reports_time ON model_monitoring_reports(checked_at DESC);
INSERT INTO platform_schema_version(version) VALUES(17);
