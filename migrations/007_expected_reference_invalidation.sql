-- A climatology switch changes the reference used by expected-state comparisons.
-- Keep archived fits frozen and restore only matching current observation evidence.
CREATE FUNCTION invalidate_expected_reference() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 UPDATE calculations SET state='stale'
 WHERE kind='expected_state_comparison' AND state='current'
 AND manifest->'policy'->>'reference_id'<>NEW.release_id::text;
 UPDATE calculations c SET state='current'
 FROM expected_state_comparisons p
 JOIN profile_revisions r USING(profile_id,revision_sha256)
 JOIN expected_state_selection s ON s.release_id=p.release_id
 JOIN expected_state_releases m ON m.release_id=s.release_id
 WHERE p.calculation_id=c.calculation_id AND m.reference_id=NEW.release_id
 AND r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL;
 RETURN NEW;
END $$;
CREATE TRIGGER expected_reference_changed AFTER INSERT OR UPDATE ON climatology_selection
FOR EACH ROW EXECUTE FUNCTION invalidate_expected_reference();
INSERT INTO platform_schema_version(version) VALUES (7);
