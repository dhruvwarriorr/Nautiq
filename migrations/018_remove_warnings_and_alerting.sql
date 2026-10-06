-- Official warnings and alerting (rules, inbox, email delivery) are no longer part of Nautiq.
DROP TABLE notification_deliveries, notification_evidence_blobs, notification_evaluations,
 notification_rule_state, notification_worker_health, notification_email_challenges, product_alerts;
DELETE FROM product_objects WHERE kind='alert-rules';
ALTER TABLE product_objects DROP CONSTRAINT product_objects_kind_check;
ALTER TABLE product_objects ADD CONSTRAINT product_objects_kind_check CHECK(kind IN ('routes','watchlists'));
ALTER TABLE product_accounts DROP COLUMN notifications_enabled, DROP COLUMN notification_email,
 DROP COLUMN email_verified_at, DROP COLUMN email_version;
DROP TABLE advisory_geometry, advisory_run_members, advisory_sources, advisory_revisions, advisory_runs, advisory_requests;
DELETE FROM calculations WHERE kind='advisory_ingestion';
-- Trip receipts embedded a warning snapshot and can no longer be replayed.
DELETE FROM product_trip_links;
DELETE FROM trip_calculations;
DELETE FROM calculations WHERE kind='trip_assessment';
ALTER TABLE calculations DROP CONSTRAINT calculations_kind_check;
ALTER TABLE calculations ADD CONSTRAINT calculations_kind_check CHECK(kind IN ('normalization','profile_summary','training_snapshot','climatology_fit','climatology_comparison','expected_state_fit','expected_state_comparison','uncertainty_fit','uncertainty_comparison','uncertainty_monitor','anomaly_fit','anomaly_comparison','field_normalization','event_history','event_baseline','event_detection','trip_assessment','model_monitor'));
UPDATE operations_controls SET paused=paused-'advisories'-'notification_evaluation'-'email_delivery', revision=revision+1, updated_at=now();
INSERT INTO platform_schema_version(version) VALUES (18);
