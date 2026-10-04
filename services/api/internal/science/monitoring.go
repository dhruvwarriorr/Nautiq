package science

import (
	"net/http"
	"strconv"
)

// modelMonitoring returns the newest unified monitoring report with a short history. It reports
// whether the report still describes the currently selected releases; it never triggers a run.
func (s *Server) modelMonitoring(w http.ResponseWriter, r *http.Request) {
	q, ok := query(w, r, "history")
	if !ok {
		return
	}
	n := 10
	if q.Has("history") {
		v, err := strconv.Atoi(q.Get("history"))
		if err != nil || v < 1 || v > 50 {
			problem(w, 400, "invalid_history")
			return
		}
		n = v
	}
	s.serve(w, r, `SELECT json_build_object(
 'latest',(SELECT row_to_json(t) FROM (SELECT m.report_id,m.checked_at,m.status,m.calculation_id,m.expected_id,m.uncertainty_id,m.anomaly_id,m.report,m.report_sha256,m.release_approved,
   EXTRACT(EPOCH FROM now()-m.checked_at)::bigint AS age_seconds,
   (m.anomaly_id IS NOT DISTINCT FROM (SELECT release_id FROM anomaly_selection) AND m.uncertainty_id IS NOT DISTINCT FROM (SELECT release_id FROM uncertainty_selection) AND m.expected_id IS NOT DISTINCT FROM (SELECT release_id FROM expected_state_selection)) AS pins_current
   FROM model_monitoring_reports m ORDER BY m.checked_at DESC LIMIT 1) t),
 'history',COALESCE((SELECT json_agg(h) FROM (SELECT report_id,checked_at,status FROM model_monitoring_reports ORDER BY checked_at DESC LIMIT $1) h),'[]'::json),
 'method','unified-model-monitoring-v1',
 'actions','A flag starts an investigation. Nautiq never retrains, recalibrates, selects or promotes a model automatically.')`, n)
}
