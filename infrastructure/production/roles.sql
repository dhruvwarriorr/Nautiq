-- Run as the migration administrator after migrations, with separately generated
-- credentials. Never use the migration/superuser role in API secret files.
CREATE ROLE nautiq_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
CREATE ROLE nautiq_worker LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
CREATE ROLE nautiq_operator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
GRANT USAGE ON SCHEMA public TO nautiq_app,nautiq_worker,nautiq_operator;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO nautiq_app,nautiq_worker,nautiq_operator;
GRANT INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO nautiq_worker;
REVOKE INSERT,UPDATE,DELETE ON operations_controls,operations_audit FROM nautiq_worker;
GRANT UPDATE ON operations_controls TO nautiq_operator;
GRANT INSERT ON operations_audit TO nautiq_operator;
GRANT INSERT,UPDATE,DELETE ON climatology_selection,expected_state_selection,uncertainty_selection,anomaly_selection TO nautiq_operator;
GRANT INSERT,UPDATE ON climatology_jobs,expected_state_jobs,uncertainty_jobs,anomaly_jobs TO nautiq_operator;
GRANT UPDATE ON calculations TO nautiq_operator;
GRANT INSERT,UPDATE,DELETE ON product_accounts,product_sessions,product_objects,product_idempotency,product_rate_limits,product_alerts,product_jobs,product_download_grants,product_object_gc,product_trip_links,notification_email_challenges,notification_rule_state,notification_evaluations,notification_evidence_blobs,notification_deliveries,notification_worker_health TO nautiq_app;
GRANT INSERT ON calculations,trip_calculations TO nautiq_app;
GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO nautiq_app,nautiq_worker;
-- Passwords are supplied out of band. Reapply explicit grants after migrations.
GRANT DELETE ON calculations,trip_calculations TO nautiq_app;
ALTER TABLE calculations ENABLE ROW LEVEL SECURITY;
CREATE POLICY app_calculation_read ON calculations FOR SELECT TO nautiq_app USING(true);
CREATE POLICY app_calculation_insert ON calculations FOR INSERT TO nautiq_app WITH CHECK(kind='trip_assessment');
CREATE POLICY app_calculation_delete ON calculations FOR DELETE TO nautiq_app USING(kind='trip_assessment');
CREATE POLICY worker_calculation_access ON calculations TO nautiq_worker USING(true) WITH CHECK(true);
CREATE POLICY operator_calculation_access ON calculations TO nautiq_operator USING(true) WITH CHECK(true);
-- SELECT FOR SHARE needs UPDATE privilege. Grant a narrowly scoped row-lock
-- function instead of allowing the operator to edit immutable release rows.
CREATE FUNCTION operations_lock_release(kind text, id uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog,public AS $$
BEGIN
 IF kind NOT IN ('climatology','expected_state','uncertainty','anomaly') THEN
  RAISE EXCEPTION 'unsupported_model_kind';
 END IF;
 EXECUTE format('SELECT 1 FROM public.%I WHERE release_id=$1 FOR SHARE',kind || '_releases') USING id;
END;
$$;
REVOKE ALL ON FUNCTION operations_lock_release(text,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations_lock_release(text,uuid) TO nautiq_operator;
