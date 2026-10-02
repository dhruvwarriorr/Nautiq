package science

import (
	"context"
	pb "nautiuq.local/api/gen/nautiuq/platform/v1"
	"net/http"
	"time"
)

func (s *Server) climatologyReleases(w http.ResponseWriter, r *http.Request) {
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
 SELECT c.release_id,c.snapshot_id,c.calculation_id,c.created_at,c.status,c.release_approved,
 EXISTS(SELECT 1 FROM climatology_selection a WHERE a.release_id=c.release_id) AS selected,
 c.manifest->'output'->'fitting_period' AS fitting_period,c.manifest->'output'->'model_count' AS model_count
 FROM climatology_releases c ORDER BY c.created_at DESC,c.release_id LIMIT $1) t`, n)
}
func (s *Server) climatologyRelease(w http.ResponseWriter, r *http.Request) {
	if _, ok := query(w, r); !ok {
		return
	}
	id, ok := identifier(w, r)
	if !ok {
		return
	}
	s.serve(w, r, `SELECT json_build_object('release_id',c.release_id,'snapshot_id',c.snapshot_id,'calculation_id',c.calculation_id,'status',c.status,
 'release_approved',c.release_approved,'created_at',c.created_at,'selected',EXISTS(SELECT 1 FROM climatology_selection a WHERE a.release_id=c.release_id),
 'manifest',c.manifest,'evaluation',c.evaluation) FROM climatology_releases c WHERE c.release_id=$1`, id)
}
func (s *Server) selectedClimatology(w http.ResponseWriter, r *http.Request) {
	if _, ok := query(w, r); !ok {
		return
	}
	s.serve(w, r, `SELECT json_build_object('release_id',a.release_id,'selected_at',a.selected_at,'status',c.status,'release_approved',c.release_approved,
 'calculation_id',c.calculation_id,'fitting_period',c.manifest->'output'->'fitting_period','model_count',c.manifest->'output'->'model_count')
 FROM climatology_selection a JOIN climatology_releases c USING(release_id) WHERE a.singleton`)
}
func (s *Server) profileClimatology(w http.ResponseWriter, r *http.Request) {
	if _, ok := query(w, r); !ok {
		return
	}
	id, ok := identifier(w, r)
	if !ok {
		return
	}
	s.serve(w, r, `SELECT json_build_object('profile_id',p.profile_id,'revision_sha256',r.revision_sha256,
 'status',CASE WHEN c.release_id IS NULL OR c.status<>'ready' THEN 'reference_unavailable' WHEN v.calculation_id IS NULL THEN 'pending' ELSE v.result->>'status' END,
 'release_id',c.release_id,'calculation_id',v.calculation_id,'reference_calculation_id',c.calculation_id,
 'fitting_period',c.manifest->'output'->'fitting_period','dataset_baseline',c.manifest->'output'->'dataset_baseline',
 'release_approved',false,'result',v.result)
 FROM profiles p JOIN profile_revisions r USING(profile_id) LEFT JOIN climatology_selection a ON a.singleton
 LEFT JOIN climatology_releases c ON c.release_id=a.release_id AND c.status='ready'
 LEFT JOIN climatology_comparisons v ON v.profile_id=r.profile_id AND v.revision_sha256=r.revision_sha256 AND v.release_id=c.release_id
 WHERE p.profile_id=$1 AND r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL`, id)
}
func (s *Server) capabilities(w http.ResponseWriter, r *http.Request) {
	if _, ok := query(w, r); !ok {
		return
	}
	rid, sha := "", ""
	if s.Runtime != nil {
		ctx, cancel := context.WithTimeout(r.Context(), time.Second)
		response, err := s.Runtime.Check(ctx, &pb.CheckRequest{})
		cancel()
		if err == nil && response.Service == "ml-inference" && response.Capabilities["expected_state"] {
			rid, sha = response.ExpectedReleaseId, response.ExpectedBundleSha256
		}
	}
	s.serve(w, r, `SELECT json_build_object('schema_version',1,'capabilities',json_build_object('platform_runtime',true,'observations',true,
 'climatology',EXISTS(SELECT 1 FROM climatology_selection a JOIN climatology_releases c USING(release_id)
 JOIN climatology_comparisons v USING(release_id) JOIN profile_revisions r USING(profile_id,revision_sha256)
 WHERE c.status='ready' AND r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL AND (v.result->>'supported_pairs')::integer>0),
 'expected_state',EXISTS(SELECT 1 FROM expected_state_selection s JOIN expected_state_releases m USING(release_id) JOIN climatology_selection c ON c.release_id=m.reference_id
 JOIN expected_state_comparisons v ON v.release_id=m.release_id JOIN profile_revisions r USING(profile_id,revision_sha256)
 WHERE m.release_id::text=$1 AND m.bundle_sha256=$2 AND m.status='ready' AND r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL AND (v.result->>'supported_pairs')::integer>0),
 'ml_residual',EXISTS(SELECT 1 FROM expected_state_selection s JOIN expected_state_releases m USING(release_id) JOIN climatology_selection c ON c.release_id=m.reference_id
 WHERE m.release_id::text=$1 AND m.bundle_sha256=$2 AND (m.manifest->'output'->'active_methods'->>'temperature_c'='lightgbm_residual' OR m.manifest->'output'->'active_methods'->>'practical_salinity'='lightgbm_residual')),
 'profile_anomaly',false,'field_sampling',false,'official_advisories',false,'trip_assessment',false),
 'limitations',json_build_array('Local train-only climatology is a prototype; source coverage and scientific production approval remain unverified. Point means may use fixed climatology fallback; production approval, calibrated intervals, field, advisory and trip verdicts remain unavailable.'))`, rid, sha)
}
