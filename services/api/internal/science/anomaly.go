package science

import "net/http"

func (s *Server) anomalyReleases(w http.ResponseWriter, r *http.Request) {
	q, ok := query(w, r, "limit")
	if !ok {
		return
	}
	n, ok := limit(q)
	if !ok {
		problem(w, 400, "invalid_limit")
		return
	}
	s.serve(w, r, `SELECT json_build_object('items',COALESCE(json_agg(t),'[]')) FROM (
 SELECT u.release_id,u.uncertainty_id,u.expected_id,u.reference_id,u.snapshot_id,u.calculation_id,u.created_at,u.status,u.release_approved,
 EXISTS(SELECT 1 FROM anomaly_selection s WHERE s.release_id=u.release_id) AS selected,
 u.manifest->'output'->'supported_variables' AS supported_variables,
 u.manifest->'output'->'depths_m' AS depths_m,u.manifest->'output'->'coverage_policy' AS coverage_policy,
 u.manifest->'output'->'scale_estimator' AS scale_estimator
 FROM anomaly_releases u ORDER BY u.created_at DESC,u.release_id LIMIT $1) t`, n)
}
func (s *Server) anomalyRelease(w http.ResponseWriter, r *http.Request) {
	if _, ok := query(w, r); !ok {
		return
	}
	id, ok := identifier(w, r)
	if !ok {
		return
	}
	s.serve(w, r, `SELECT json_build_object('release_id',u.release_id,'uncertainty_id',u.uncertainty_id,'expected_id',u.expected_id,'reference_id',u.reference_id,'snapshot_id',u.snapshot_id,'calculation_id',u.calculation_id,
 'status',u.status,'release_approved',u.release_approved,'created_at',u.created_at,'selected',EXISTS(SELECT 1 FROM anomaly_selection s WHERE s.release_id=u.release_id),
 'manifest',u.manifest,'report',u.report,'tracking',CASE WHEN t.run_id IS NULL THEN NULL ELSE json_build_object('run_id',t.run_id,'registered_model',t.registered_model,'model_version',t.model_version,'logged_at',t.logged_at,'performance',t.performance) END)
 FROM anomaly_releases u LEFT JOIN anomaly_tracking t USING(release_id) WHERE u.release_id=$1`, id)
}
func (s *Server) selectedAnomaly(w http.ResponseWriter, r *http.Request) {
	if _, ok := query(w, r); !ok {
		return
	}
	s.serve(w, r, `SELECT json_build_object('release_id',u.release_id,'selected_at',s.selected_at,'uncertainty_id',u.uncertainty_id,'expected_id',u.expected_id,'reference_id',u.reference_id,'status',u.status,'release_approved',false,'calculation_id',u.calculation_id,'depths_m',u.report->'depths_m','coverage_policy',u.report->'coverage_policy','scale_estimator',u.report->'scale_estimator') FROM anomaly_selection s JOIN anomaly_releases u USING(release_id) WHERE s.singleton`)
}
func (s *Server) profileAnomaly(w http.ResponseWriter, r *http.Request) {
	if _, ok := query(w, r); !ok {
		return
	}
	id, ok := identifier(w, r)
	if !ok {
		return
	}
	s.serve(w, r, `SELECT json_build_object('profile_id',p.profile_id,'revision_sha256',r.revision_sha256,'release_id',u.release_id,'uncertainty_id',u.uncertainty_id,'expected_id',u.expected_id,'reference_id',u.reference_id,
 'calculation_id',CASE WHEN e.release_id IS NOT NULL AND b.release_id IS NOT NULL AND i.release_id IS NOT NULL THEN v.calculation_id ELSE NULL END,'reference_calculation_id',u.calculation_id,
 'status',CASE WHEN u.release_id IS NULL THEN 'reference_unavailable' WHEN e.release_id IS NULL OR b.release_id IS NULL OR i.release_id IS NULL THEN 'reference_mismatch' WHEN v.calculation_id IS NULL THEN 'pending' ELSE v.result->>'status' END,
 'pending_reason',CASE WHEN v.calculation_id IS NULL THEN j.reason_code ELSE NULL END,'coverage_policy',u.report->'coverage_policy',
 'release_approved',false,'result',CASE WHEN e.release_id IS NOT NULL AND b.release_id IS NOT NULL AND i.release_id IS NOT NULL THEN v.result ELSE NULL END)
 FROM profiles p JOIN profile_revisions r USING(profile_id) LEFT JOIN anomaly_selection s ON s.singleton LEFT JOIN anomaly_releases u ON u.release_id=s.release_id AND u.status='ready'
 LEFT JOIN uncertainty_selection i ON i.release_id=u.uncertainty_id LEFT JOIN expected_state_selection e ON e.release_id=u.expected_id LEFT JOIN climatology_selection b ON b.release_id=u.reference_id
 LEFT JOIN anomaly_comparisons v ON v.profile_id=r.profile_id AND v.revision_sha256=r.revision_sha256 AND v.release_id=u.release_id
 LEFT JOIN anomaly_jobs j ON j.profile_id=r.profile_id AND j.revision_sha256=r.revision_sha256 AND j.release_id=u.release_id
 WHERE p.profile_id=$1 AND r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL`, id)
}
