package science

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"github.com/jackc/pgx/v5"
	"github.com/minio/minio-go/v7"
	"io"
	"net/http"
	"reflect"
	"strings"
	"time"
)

type eventArtifact struct {
	Key   string `json:"raw_key"`
	SHA   string `json:"sha256"`
	Bytes int64  `json:"bytes"`
}

func (s *Server) checkEventObject(r *http.Request, key, sha string, size int64) error {
	if s.Storage == nil || key == "" || len(sha) != 64 || size <= 0 || size > 64*1024*1024 {
		return errors.New("event artifact contract")
	}
	object, err := s.Storage.GetObject(r.Context(), "nautiq", key, minio.GetObjectOptions{})
	if err != nil {
		return err
	}
	defer object.Close()
	hash := sha256.New()
	n, err := io.Copy(hash, io.LimitReader(object, size+1))
	if err != nil || n > size || hex.EncodeToString(hash.Sum(nil)) != sha {
		return errors.New("event artifact unavailable")
	}
	return nil
}

// Inspect exact parent manifests, arrays, raw receipts and calculation objects on each detail read.
// The worker performs numerical contract validation; this read verifies retained byte identities.
func (s *Server) checkEventInputs(r *http.Request, manifest map[string]any, cid string, kind string) error {
	data, _ := json.Marshal(manifest)
	var pin struct {
		Inputs struct {
			BaselineID  string `json:"baseline_id"`
			BaselineSHA string `json:"baseline_sha256"`
			HistoryID   string `json:"history_id"`
			HistorySHA  string `json:"history_sha256"`
			AnomalyID   string `json:"anomaly_id"`
			BundleSHA   string `json:"bundle_sha256"`
			Profiles    []struct {
				CalculationID *string `json:"calculation_id"`
				SHA           *string `json:"manifest_sha256"`
			} `json:"profiles"`
		} `json:"inputs"`
	}
	if json.Unmarshal(data, &pin) != nil {
		return errors.New("event pins")
	}
	var calcKey, calcSHA string
	if err := s.DB.QueryRow(r.Context(), "SELECT manifest_key,manifest_sha256 FROM calculations WHERE calculation_id=$1 AND kind='event_detection'", cid).Scan(&calcKey, &calcSHA); err != nil {
		return err
	}
	if err := s.checkEventObject(r, calcKey, calcSHA, 16*1024*1024); err != nil {
		return err
	}
	if kind == "profile_groups" {
		var key, sha string
		if err := s.DB.QueryRow(r.Context(), "SELECT bundle_key,bundle_sha256 FROM anomaly_releases WHERE release_id=$1", pin.Inputs.AnomalyID).Scan(&key, &sha); err != nil {
			return err
		}
		if sha != pin.Inputs.BundleSHA {
			return errors.New("event parent pin")
		}
		if err := s.checkEventObject(r, key, sha, 64*1024*1024); err != nil {
			return err
		}
		for _, p := range pin.Inputs.Profiles {
			if p.CalculationID != nil {
				if err := s.DB.QueryRow(r.Context(), "SELECT manifest_key,manifest_sha256 FROM calculations WHERE calculation_id=$1", *p.CalculationID).Scan(&key, &sha); err != nil {
					return err
				}
				if p.SHA == nil || sha != *p.SHA {
					return errors.New("event profile pin")
				}
				if err := s.checkEventObject(r, key, sha, 16*1024*1024); err != nil {
					return err
				}
			}
		}
		return nil
	}
	rows, err := s.DB.Query(r.Context(), `WITH RECURSIVE d AS (SELECT * FROM event_datasets WHERE dataset_id=$1::uuid OR dataset_id=$2::uuid UNION SELECT p.* FROM event_datasets p JOIN d ON p.dataset_id=d.parent_id) SELECT d.dataset_id::text,d.status,d.manifest_key,d.manifest_sha256,d.manifest,c.manifest_key,c.manifest_sha256 FROM d JOIN calculations c USING(calculation_id)`, pin.Inputs.BaselineID, pin.Inputs.HistoryID)
	if err != nil {
		return err
	}
	defer rows.Close()
	type retained struct {
		id, state, key, sha, calcKey, calcSHA string
		raw                                   []byte
	}
	items := []retained{}
	for rows.Next() {
		var p retained
		if err := rows.Scan(&p.id, &p.state, &p.key, &p.sha, &p.raw, &p.calcKey, &p.calcSHA); err != nil {
			return err
		}
		items = append(items, p)
	}
	if rows.Err() != nil {
		return rows.Err()
	}
	rows.Close()
	if len(items) != 3 {
		return errors.New("event dataset ancestry")
	}
	var total int64
	for _, p := range items {
		if p.state != "ready" || (p.id == pin.Inputs.BaselineID && p.sha != pin.Inputs.BaselineSHA) || (p.id == pin.Inputs.HistoryID && p.sha != pin.Inputs.HistorySHA) {
			return errors.New("event dataset pin")
		}
		var m struct {
			ArraysKey   string `json:"arrays_key"`
			ArraysSHA   string `json:"arrays_sha256"`
			ArraysBytes int64  `json:"arrays_bytes"`
			Metadata    struct {
				Raw []eventArtifact `json:"raw"`
			} `json:"metadata"`
		}
		if json.Unmarshal(p.raw, &m) != nil {
			return errors.New("event dataset manifest")
		}
		object, err := s.Storage.GetObject(r.Context(), "nautiq", p.key, minio.GetObjectOptions{})
		if err != nil {
			return err
		}
		raw, err := io.ReadAll(io.LimitReader(object, 1024*1024+1))
		object.Close()
		hash := sha256.Sum256(raw)
		var lake, sql any
		if err != nil || len(raw) > 1024*1024 || hex.EncodeToString(hash[:]) != p.sha || json.Unmarshal(raw, &lake) != nil || json.Unmarshal(p.raw, &sql) != nil || !reflect.DeepEqual(lake, sql) {
			return errors.New("event dataset mirror")
		}
		if err := s.checkEventObject(r, p.calcKey, p.calcSHA, 16*1024*1024); err != nil {
			return err
		}
		if m.ArraysBytes > 16*1024*1024 {
			return errors.New("event array budget")
		}
		if err := s.checkEventObject(r, m.ArraysKey, m.ArraysSHA, m.ArraysBytes); err != nil {
			return err
		}
		total += m.ArraysBytes
		for _, a := range m.Metadata.Raw {
			total += a.Bytes
			if total > 192*1024*1024 || a.Bytes > 16*1024*1024 {
				return errors.New("event raw budget")
			}
			if err := s.checkEventObject(r, a.Key, a.SHA, a.Bytes); err != nil {
				return err
			}
		}
	}
	return nil
}

const eventCurrent = `CASE WHEN u.kind='surface_thermal' THEN 'frozen_history'
 WHEN NOT EXISTS(SELECT 1 FROM anomaly_selection s JOIN anomaly_releases a USING(release_id)
 JOIN uncertainty_selection q ON q.release_id=a.uncertainty_id JOIN expected_state_selection e ON e.release_id=a.expected_id JOIN climatology_selection c ON c.release_id=a.reference_id WHERE s.release_id=u.anomaly_id)
 OR EXISTS(SELECT 1 FROM event_profile_inputs p JOIN profile_revisions r USING(profile_id,revision_sha256) WHERE p.run_id=u.run_id AND (r.superseded_at IS NOT NULL OR r.selected_at IS NULL OR NOT r.science_ready
 OR COALESCE(p.calculation_id::text,'')<>COALESCE((SELECT a.calculation_id::text FROM anomaly_comparisons a JOIN calculations c USING(calculation_id) WHERE a.profile_id=p.profile_id AND a.revision_sha256=p.revision_sha256 AND a.release_id=u.anomaly_id AND c.state='current'),'')))
 OR (SELECT count(*) FROM profile_revisions r WHERE r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL
 AND r.observed_at>=(u.report->>'start')::date AND r.observed_at<(u.report->>'end')::date+interval '1 day'
 AND r.longitude BETWEEN (u.report->'extent'->>0)::float8 AND (u.report->'extent'->>2)::float8 AND r.latitude BETWEEN (u.report->'extent'->>1)::float8 AND (u.report->'extent'->>3)::float8)<>(u.report->'coverage'->>'queried_profiles')::int THEN 'stale_snapshot' ELSE 'current_snapshot' END`

func (s *Server) eventDatasets(w http.ResponseWriter, r *http.Request) {
	q, ok := query(w, r, "kind", "limit")
	if !ok {
		return
	}
	n, ok := limit(q)
	if !ok {
		problem(w, 400, "invalid_limit")
		return
	}
	var kind any
	if q.Has("kind") {
		if q.Get("kind") != "history" && q.Get("kind") != "baseline" {
			problem(w, 400, "invalid_event_dataset_kind")
			return
		}
		kind = q.Get("kind")
	}
	s.serve(w, r, `SELECT json_build_object('items',COALESCE(json_agg(t),'[]')) FROM (SELECT dataset_id,kind,parent_id,calculation_id,manifest_sha256,status,created_at,manifest->'metadata' metadata FROM event_datasets WHERE ($1::text IS NULL OR kind=$1) ORDER BY created_at DESC,dataset_id LIMIT $2) t`, kind, n)
}
func (s *Server) eventDataset(w http.ResponseWriter, r *http.Request) {
	if _, ok := query(w, r); !ok {
		return
	}
	id, ok := identifier(w, r)
	if !ok {
		return
	}
	s.serve(w, r, `SELECT json_build_object('dataset_id',dataset_id,'kind',kind,'parent_id',parent_id,'calculation_id',calculation_id,'manifest_sha256',manifest_sha256,'status',status,'created_at',created_at,'manifest',manifest) FROM event_datasets WHERE dataset_id=$1`, id)
}
func (s *Server) eventRuns(w http.ResponseWriter, r *http.Request) {
	q, ok := query(w, r, "kind", "limit")
	if !ok {
		return
	}
	n, ok := limit(q)
	if !ok {
		problem(w, 400, "invalid_limit")
		return
	}
	var kind any
	if q.Has("kind") {
		if q.Get("kind") != "surface_thermal" && q.Get("kind") != "profile_groups" {
			problem(w, 400, "invalid_event_kind")
			return
		}
		kind = q.Get("kind")
	}
	s.serve(w, r, `SELECT json_build_object('items',COALESCE(json_agg(t),'[]')) FROM (SELECT u.run_id,u.kind,u.calculation_id,u.baseline_id,u.history_id,u.anomaly_id,u.report_sha256,u.status,u.release_approved,u.created_at,u.report->>'start' start,u.report->>'end' "end",jsonb_array_length(u.report->'events') event_count,u.report->'coverage' coverage,`+eventCurrent+` input_state FROM event_runs u WHERE ($1::text IS NULL OR u.kind=$1) ORDER BY u.created_at DESC,u.run_id LIMIT $2) t`, kind, n)
}

func (s *Server) loadEventRun(w http.ResponseWriter, r *http.Request, id string) (map[string]any, bool) {
	var key, sha, state string
	var stored, header []byte
	err := s.DB.QueryRow(r.Context(), `SELECT report_key,report_sha256,status,report,json_build_object('run_id',u.run_id,'kind',u.kind,'calculation_id',u.calculation_id,'report_sha256',u.report_sha256,'status',u.status,'created_at',u.created_at,'manifest',u.manifest,'input_state',`+eventCurrent+`) FROM event_runs u WHERE run_id=$1`, id).Scan(&key, &sha, &state, &stored, &header)
	if errors.Is(err, pgx.ErrNoRows) {
		problem(w, 404, "event_run_not_found")
		return nil, false
	}
	if err != nil || state != "ready" || s.Storage == nil {
		problem(w, 503, "event_integrity_unavailable")
		return nil, false
	}
	object, err := s.Storage.GetObject(r.Context(), "nautiq", key, minio.GetObjectOptions{})
	if err != nil {
		problem(w, 503, "event_integrity_unavailable")
		return nil, false
	}
	defer object.Close()
	data, err := io.ReadAll(io.LimitReader(object, 16*1024*1024+1))
	hash := sha256.Sum256(data)
	if err != nil || len(data) > 16*1024*1024 || hex.EncodeToString(hash[:]) != sha {
		problem(w, 503, "event_integrity_unavailable")
		return nil, false
	}
	var report, mirror map[string]any
	if json.Unmarshal(data, &report) != nil || json.Unmarshal(stored, &mirror) != nil || !reflect.DeepEqual(report, mirror) || report["release_approved"] != false {
		problem(w, 503, "event_report_contract_failed")
		return nil, false
	}
	result := map[string]any{}
	if json.Unmarshal(header, &result) != nil {
		problem(w, 503, "event_report_contract_failed")
		return nil, false
	}
	select {
	case s.downloads <- struct{}{}:
		defer func() { <-s.downloads }()
	default:
		problem(w, 429, "event_integrity_capacity")
		return nil, false
	}
	m, ok := result["manifest"].(map[string]any)
	if !ok || s.checkEventInputs(r, m, result["calculation_id"].(string), result["kind"].(string)) != nil {
		problem(w, 503, "event_input_integrity_unavailable")
		return nil, false
	}
	result["report"] = report
	return result, true
}
func (s *Server) eventRun(w http.ResponseWriter, r *http.Request) {
	if _, ok := query(w, r); !ok {
		return
	}
	id, ok := identifier(w, r)
	if !ok {
		return
	}
	result, ok := s.loadEventRun(w, r, id)
	if !ok {
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	json.NewEncoder(w).Encode(result)
}
func (s *Server) regionalEvents(w http.ResponseWriter, r *http.Request) {
	q, ok := query(w, r, "kind", "run_id", "start", "end", "bbox", "limit")
	if !ok {
		return
	}
	n, ok := limit(q)
	if !ok {
		problem(w, 400, "invalid_limit")
		return
	}
	var kind, rid, start, end any
	if q.Has("kind") {
		if q.Get("kind") != "surface_thermal_candidate" && q.Get("kind") != "regional_profile_candidate" && q.Get("kind") != "isolated_profile_anomalies" {
			problem(w, 400, "invalid_regional_event_kind")
			return
		}
		kind = q.Get("kind")
	}
	if q.Has("run_id") {
		if !fieldID(q.Get("run_id")) {
			problem(w, 400, "invalid_run_id")
			return
		}
		rid = q.Get("run_id")
	}
	if q.Has("start") || q.Has("end") {
		a, ae := time.Parse("2006-01-02", q.Get("start"))
		b, be := time.Parse("2006-01-02", q.Get("end"))
		if ae != nil || be != nil || b.Before(a) || b.Sub(a) > 365*24*time.Hour {
			problem(w, 400, "invalid_event_window")
			return
		}
		start = q.Get("start")
		end = q.Get("end")
	}
	var west, south, east, north any
	if q.Has("bbox") {
		parts := strings.Split(q.Get("bbox"), ",")
		if len(parts) != 4 {
			problem(w, 400, "invalid_event_bbox")
			return
		}
		a, aa := coordinate(parts[0], -180, 180)
		b, bb := coordinate(parts[1], -90, 90)
		c, cc := coordinate(parts[2], -180, 180)
		d, dd := coordinate(parts[3], -90, 90)
		if !aa || !bb || !cc || !dd || a >= c || b >= d {
			problem(w, 400, "invalid_event_bbox")
			return
		}
		west, south, east, north = a, b, c, d
	}
	s.serve(w, r, `SELECT json_build_object('items',COALESCE(json_agg(t),'[]')) FROM (SELECT e.event_id,e.run_id,e.kind,e.variable,e.start_day,e.end_day,e.evidence-'members' evidence,u.status,u.release_approved,`+eventCurrent+` input_state FROM regional_events e JOIN event_runs u USING(run_id) WHERE ($1::text IS NULL OR e.kind=$1) AND ($2::uuid IS NULL OR e.run_id=$2) AND ($3::date IS NULL OR e.end_day>=$3) AND ($4::date IS NULL OR e.start_day<=$4) AND ($5::float8 IS NULL OR ST_Intersects(e.geometry,ST_MakeEnvelope($5,$6,$7,$8,4326))) ORDER BY e.start_day DESC,e.event_id LIMIT $9) t`, kind, rid, start, end, west, south, east, north, n)
}
func (s *Server) regionalEvent(w http.ResponseWriter, r *http.Request) {
	if _, ok := query(w, r); !ok {
		return
	}
	id, ok := identifier(w, r)
	if !ok {
		return
	}
	var rid string
	var stored []byte
	if s.DB.QueryRow(r.Context(), "SELECT run_id,evidence FROM regional_events WHERE event_id=$1", id).Scan(&rid, &stored) != nil {
		problem(w, 404, "regional_event_not_found")
		return
	}
	run, ok := s.loadEventRun(w, r, rid)
	if !ok {
		return
	}
	report := run["report"].(map[string]any)
	events, ok := report["events"].([]any)
	if !ok {
		problem(w, 503, "event_report_contract_failed")
		return
	}
	var mirror map[string]any
	json.Unmarshal(stored, &mirror)
	for _, value := range events {
		event, ok := value.(map[string]any)
		if ok && event["event_id"] == id {
			if !reflect.DeepEqual(event, mirror) {
				problem(w, 503, "event_projection_mismatch")
				return
			}
			delete(run, "report")
			run["event"] = event
			w.Header().Set("Content-Type", "application/json")
			w.Header().Set("Cache-Control", "no-store")
			json.NewEncoder(w).Encode(run)
			return
		}
	}
	problem(w, 503, "event_projection_mismatch")
}
