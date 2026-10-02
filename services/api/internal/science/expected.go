package science

import "net/http"

func (s *Server) expectedReleases(w http.ResponseWriter, r *http.Request) {
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
 SELECT m.release_id,m.reference_id,m.snapshot_id,m.calculation_id,m.created_at,m.status,m.release_approved,
 EXISTS(SELECT 1 FROM expected_state_selection s WHERE s.release_id=m.release_id) AS selected,
 m.manifest->'output'->'active_methods' AS active_methods,m.manifest->'output'->'model_count' AS model_count,
 m.manifest->'output'->'fitting_period' AS fitting_period
 FROM expected_state_releases m ORDER BY m.created_at DESC,m.release_id LIMIT $1) t`, n)
}
func (s *Server) expectedRelease(w http.ResponseWriter, r *http.Request) {
	if _, ok := query(w, r); !ok {
		return
	}
	id, ok := identifier(w, r)
	if !ok {
		return
	}
	s.serve(w, r, `SELECT json_build_object('release_id',m.release_id,'reference_id',m.reference_id,'snapshot_id',m.snapshot_id,'calculation_id',m.calculation_id,
 'status',m.status,'release_approved',m.release_approved,'created_at',m.created_at,'selected',EXISTS(SELECT 1 FROM expected_state_selection s WHERE s.release_id=m.release_id),
 'manifest',m.manifest,'report',m.report,'tracking',CASE WHEN t.run_id IS NULL THEN NULL ELSE json_build_object('run_id',t.run_id,'registered_model',t.registered_model,'model_version',t.model_version,'logged_at',t.logged_at) END)
 FROM expected_state_releases m LEFT JOIN expected_state_tracking t USING(release_id) WHERE m.release_id=$1`, id)
}
func (s *Server) selectedExpected(w http.ResponseWriter, r *http.Request) {
	if _, ok := query(w, r); !ok {
		return
	}
	s.serve(w, r, `SELECT json_build_object('release_id',s.release_id,'selected_at',s.selected_at,'reference_id',m.reference_id,'status',m.status,
 'release_approved',m.release_approved,'calculation_id',m.calculation_id,'active_methods',m.manifest->'output'->'active_methods',
 'fitting_period',m.manifest->'output'->'fitting_period','model_count',m.manifest->'output'->'model_count')
 FROM expected_state_selection s JOIN expected_state_releases m USING(release_id) WHERE s.singleton`)
}
func (s *Server) profileExpected(w http.ResponseWriter, r *http.Request) {
	if _, ok := query(w, r); !ok {
		return
	}
	id, ok := identifier(w, r)
	if !ok {
		return
	}
	s.serve(w, r, `SELECT json_build_object('profile_id',p.profile_id,'revision_sha256',r.revision_sha256,'release_id',m.release_id,
 'reference_id',m.reference_id,'calculation_id',CASE WHEN c.release_id IS NOT NULL THEN v.calculation_id ELSE NULL END,'reference_calculation_id',m.calculation_id,
 'status',CASE WHEN m.release_id IS NULL THEN 'reference_unavailable' WHEN c.release_id IS NULL THEN 'reference_mismatch' WHEN v.calculation_id IS NULL THEN 'pending' ELSE v.result->>'status' END,
 'pending_reason',CASE WHEN v.calculation_id IS NULL THEN j.reason_code ELSE NULL END,'active_methods',m.manifest->'output'->'active_methods',
 'fitting_period',m.manifest->'output'->'fitting_period','release_approved',false,'result',CASE WHEN c.release_id IS NOT NULL THEN v.result ELSE NULL END)
 FROM profiles p JOIN profile_revisions r USING(profile_id) LEFT JOIN expected_state_selection s ON s.singleton
 LEFT JOIN expected_state_releases m ON m.release_id=s.release_id AND m.status='ready' LEFT JOIN climatology_selection c ON c.release_id=m.reference_id
 LEFT JOIN expected_state_comparisons v ON v.profile_id=r.profile_id AND v.revision_sha256=r.revision_sha256 AND v.release_id=m.release_id
 LEFT JOIN expected_state_jobs j ON j.profile_id=r.profile_id AND j.revision_sha256=r.revision_sha256 AND j.release_id=m.release_id
 WHERE p.profile_id=$1 AND r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL`, id)
}
