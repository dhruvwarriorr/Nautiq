package science

import (
	"bytes"
	"encoding/json"
	"errors"
	"github.com/minio/minio-go/v7"
	"io"
	"nautiq.local/api/internal/product"
	"net/http"
	"net/url"
	"reflect"
	"strconv"
	"strings"
	"sync"
	"time"
)

// Product composition retains typed API boundaries and per-layer unknown states.
func (s *Server) RegisterSurfaces(mux *http.ServeMux) {
	mux.Handle("GET /api/v1/conditions/point", s.bound(s.conditions))
	mux.Handle("GET /api/v1/conditions/region/{slug}", s.bound(s.regionConditions))
	mux.Handle("GET /api/v1/map/overview", s.bound(s.mapOverview))
	mux.Handle("POST /api/v1/answer", s.bound(s.answer))
}

type collected struct {
	header   http.Header
	code     int
	data     bytes.Buffer
	overflow bool
}

func (w *collected) Header() http.Header { return w.header }
func (w *collected) WriteHeader(code int) {
	if w.code == 0 {
		w.code = code
	}
}
func (w *collected) Write(data []byte) (int, error) {
	if w.code == 0 {
		w.code = 200
	}
	if w.data.Len()+len(data) > 4194304 {
		w.overflow = true
		return 0, errors.New("composition_byte_budget")
	}
	return w.data.Write(data)
}
func compose(r *http.Request, next http.HandlerFunc, q url.Values) (json.RawMessage, int) {
	copy := r.Clone(r.Context())
	u := *r.URL
	u.RawQuery = q.Encode()
	copy.URL = &u
	w := &collected{header: make(http.Header)}
	next(w, copy)
	if w.overflow || !json.Valid(w.data.Bytes()) {
		return json.RawMessage(`{"status":"unavailable","reason":"composition_contract"}`), 503
	}
	return append(json.RawMessage{}, w.data.Bytes()...), w.code
}
func fstr(v float64) string { return strconv.FormatFloat(v, 'g', -1, 64) }
func (s *Server) regionConditions(w http.ResponseWriter, r *http.Request) {
	q, ok := query(w, r, "time")
	if !ok {
		return
	}
	var place *product.Location
	for _, p := range product.Catalog().Locations {
		if p.Slug == r.PathValue("slug") {
			copy := p
			place = &copy
		}
	}
	if place == nil {
		problem(w, 404, "region_not_found")
		return
	}
	copy := r.Clone(r.Context())
	u := *r.URL
	values := url.Values{"latitude": {fstr(place.Latitude)}, "longitude": {fstr(place.Longitude)}}
	if q.Has("time") {
		values.Set("time", q.Get("time"))
	}
	u.RawQuery = values.Encode()
	copy.URL = &u
	s.conditions(w, copy)
}
func (s *Server) conditions(w http.ResponseWriter, r *http.Request) {
	q, ok := query(w, r, "latitude", "longitude", "time")
	if !ok {
		return
	}
	lat, la := coordinate(q.Get("latitude"), -85, 85)
	lon, lo := coordinate(q.Get("longitude"), -180, 180)
	at := time.Now().UTC()
	var e error
	if q.Has("time") {
		at, e = time.Parse(time.RFC3339Nano, q.Get("time"))
	}
	if !la || !lo || e != nil {
		problem(w, 400, "invalid_location_or_utc_time")
		return
	}
	at = at.UTC()
	asOf := time.Now().UTC()
	var nearby []byte
	e = s.DB.QueryRow(r.Context(), `SELECT COALESCE(json_agg(v),'[]') FROM (SELECT r.profile_id,r.revision_sha256,r.latitude,r.longitude,r.observed_at,r.received_at,p.platform_id,r.data_mode,r.qc_version,r.calculation_id,ST_Distance(r.position::geography,ST_SetSRID(ST_MakePoint($1,$2),4326)::geography)/1000 AS distance_km FROM profile_revisions r JOIN profiles p USING(profile_id) WHERE r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL AND r.observed_at<=$3 AND ST_DWithin(r.position::geography,ST_SetSRID(ST_MakePoint($1,$2),4326)::geography,100000) ORDER BY r.observed_at DESC,r.profile_id LIMIT 20) v`, lon, lat, at).Scan(&nearby)
	if e != nil {
		problem(w, 503, "nearby_profiles_unavailable")
		return
	}
	type field struct {
		Product  string            `json:"product_id"`
		Variable string            `json:"variable"`
		ID       string            `json:"release_id"`
		SHA      string            `json:"manifest_sha256"`
		Cycle    *time.Time        `json:"cycle"`
		State    string            `json:"state"`
		Timeline []json.RawMessage `json:"timeline"`
	}
	specifications := [][2]string{{"noaa_oisst", "sst_c"}, {"noaa_gfs_wave", "wave_height_m"}, {"noaa_gfs_weather", "wind_speed_m_s"}, {"hycom_espc", "current_speed_m_s"}}
	results := make([]field, len(specifications))
	var wg sync.WaitGroup
	for i, spec := range specifications {
		wg.Add(1)
		go func(i int, spec [2]string) {
			defer wg.Done()
			item := field{Product: spec[0], Variable: spec[1], State: "unavailable", Timeline: []json.RawMessage{}}
			e := s.DB.QueryRow(r.Context(), `SELECT f.release_id::text,f.manifest_sha256,f.cycle,CASE WHEN COALESCE(f.cycle,f.valid_time_end)+make_interval(hours=>(f.manifest->'metadata'->>'max_age_hours')::integer)<now() THEN 'stale' ELSE 'available' END FROM field_selection s JOIN field_releases f USING(release_id) WHERE s.product_id=$1 AND f.status='ready'`, spec[0]).Scan(&item.ID, &item.SHA, &item.Cycle, &item.State)
			if e == nil {
				for j := 0; j < 4; j++ {
					timeValue := at.Add(time.Duration(j) * 6 * time.Hour).Format(time.RFC3339Nano)
					raw, status := compose(r, s.fieldSample, url.Values{"release_id": {item.ID}, "variable": {spec[1]}, "latitude": {fstr(lat)}, "longitude": {fstr(lon)}, "time": {timeValue}})
					if status != 200 {
						item.Timeline = append(item.Timeline, product.JSON(map[string]any{"status": "unavailable", "requested_time": timeValue, "reason": "field_dependency_or_contract"}))
						item.State = "partial"
					} else {
						item.Timeline = append(item.Timeline, raw)
					}
				}
			}
			results[i] = item
		}(i, spec)
	}
	advisory, advisoryStatus := compose(r, s.advisoryState, url.Values{"latitude": {fstr(lat)}, "longitude": {fstr(lon)}, "start": {at.Format(time.RFC3339Nano)}, "end": {at.Add(24 * time.Hour).Format(time.RFC3339Nano)}})
	wg.Wait()
	if advisoryStatus != 200 {
		advisory = product.JSON(map[string]any{"status": "unknown", "as_of": asOf, "unknown_reasons": []string{"advisory_evidence_unavailable"}})
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	json.NewEncoder(w).Encode(map[string]any{"requested_point": map[string]float64{"latitude": lat, "longitude": lon}, "requested_time": at, "as_of": asOf, "nearby_profiles": json.RawMessage(nearby), "fields": results, "advisory": advisory, "expected_at_point": map[string]any{"state": "unavailable", "reason": "no_validated_profile_collocation"}, "confidence": map[string]any{"state": "unavailable", "reason": "confidence_policy_unvalidated"}, "limitations": []string{"Nearby observations are shown at their actual positions, times and depths; none is a surface value or observation at the requested point.", "Four retained forecast samples are a timeline preview, not a best-window or trip assessment.", "Field support, stale cycles, masks and horizons remain explicit; no numeric value is substituted for missing data.", "Official marine completeness and operational science/trip approvals remain unproven."}})
}
func (s *Server) mapOverview(w http.ResponseWriter, r *http.Request) {
	q, ok := query(w, r, "bbox", "start", "end")
	if !ok {
		return
	}
	bbox := q.Get("bbox")
	if bbox == "" {
		bbox = "45,0,100,30"
	}
	parts := strings.Split(bbox, ",")
	if len(parts) != 4 {
		problem(w, 400, "invalid_map_bbox")
		return
	}
	bounds := []float64{}
	for i, p := range parts {
		low, high := -180.0, 180.0
		if i%2 == 1 {
			low, high = -85, 85
		}
		v, ok := coordinate(p, low, high)
		if !ok {
			problem(w, 400, "invalid_map_bbox")
			return
		}
		bounds = append(bounds, v)
	}
	if bounds[0] >= bounds[2] || bounds[1] >= bounds[3] {
		problem(w, 400, "split_dateline_bbox")
		return
	}
	end := time.Now().UTC()
	start := end.Add(-30 * 24 * time.Hour)
	var e error
	if q.Has("start") || q.Has("end") {
		start, e = time.Parse(time.RFC3339Nano, q.Get("start"))
		if e == nil {
			end, e = time.Parse(time.RFC3339Nano, q.Get("end"))
		}
		if e != nil || !start.Before(end) || end.Sub(start) > 366*24*time.Hour {
			problem(w, 400, "invalid_map_window")
			return
		}
	}
	var profiles, fields []byte
	e = s.DB.QueryRow(r.Context(), `SELECT COALESCE(json_agg(v),'[]') FROM (SELECT r.profile_id AS id,r.revision_sha256,r.latitude,r.longitude,r.observed_at,r.received_at,p.platform_id,r.qc_version,r.data_mode,r.calculation_id FROM profile_revisions r JOIN profiles p USING(profile_id) WHERE r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL AND r.observed_at>=$1 AND r.observed_at<$2 AND r.position && ST_MakeEnvelope($3,$4,$5,$6,4326) ORDER BY r.observed_at DESC,r.profile_id LIMIT 200) v`, start, end, bounds[0], bounds[1], bounds[2], bounds[3]).Scan(&profiles)
	if e != nil {
		problem(w, 503, "map_observations_unavailable")
		return
	}
	e = s.DB.QueryRow(r.Context(), `SELECT COALESCE(json_agg(v),'[]') FROM (SELECT f.release_id,f.product_id,f.calculation_id,f.manifest_sha256,f.cycle,f.valid_time_start,f.valid_time_end,f.manifest->'metadata' AS metadata,f.status,false AS release_approved,true AS selected,CASE WHEN COALESCE(f.cycle,f.valid_time_end)+make_interval(hours=>(f.manifest->'metadata'->>'max_age_hours')::integer)<now() THEN 'stale' ELSE 'available' END AS freshness FROM field_selection s JOIN field_releases f USING(release_id) ORDER BY f.product_id LIMIT 8) v`).Scan(&fields)
	if e != nil {
		problem(w, 503, "map_fields_unavailable")
		return
	}
	// Only frozen report geometries are plotted. Index geometry is not evidence.
	rows, e := s.DB.Query(r.Context(), `SELECT DISTINCT ON (kind) kind,run_id::text,report_key,report_sha256,report,calculation_id::text FROM event_runs WHERE status='ready' ORDER BY kind,created_at DESC,run_id LIMIT 2`)
	events := []map[string]any{}
	geometryBytes := 0
	eventState := "historical_diagnostics"
	if e == nil {
		type pin struct {
			kind, id, key, sha, cid string
			mirror                  []byte
		}
		pins := []pin{}
		for rows.Next() {
			var p pin
			if rows.Scan(&p.kind, &p.id, &p.key, &p.sha, &p.mirror, &p.cid) != nil {
				e = errors.New("map_event_projection")
				break
			}
			pins = append(pins, p)
		}
		if rows.Err() != nil {
			e = rows.Err()
		}
		rows.Close()
		for _, p := range pins {
			if e != nil {
				break
			}
			obj, err := s.Storage.GetObject(r.Context(), "nautiq", p.key, minio.GetObjectOptions{})
			if err != nil {
				e = err
				break
			}
			data, err := io.ReadAll(io.LimitReader(obj, 16*1024*1024+1))
			obj.Close()
			var lake, mirror map[string]any
			if err != nil || len(data) > 16*1024*1024 || product.Hash(data) != p.sha || json.Unmarshal(data, &lake) != nil || json.Unmarshal(p.mirror, &mirror) != nil || !reflect.DeepEqual(lake, mirror) {
				e = errors.New("map_event_integrity")
				break
			}
			list, _ := lake["events"].([]any)
			for _, v := range list {
				item, ok := v.(map[string]any)
				if !ok {
					e = errors.New("map_event_contract")
					break
				}
				aText, aOK := item["start"].(string)
				bText, bOK := item["end"].(string)
				a, aErr := time.Parse("2006-01-02", aText)
				b, bErr := time.Parse("2006-01-02", bText)
				if !aOK || !bOK || aErr != nil || bErr != nil {
					e = errors.New("map_event_contract")
					break
				}
				if b.Add(24*time.Hour).Before(start) || !a.Before(end) {
					continue
				}
				if len(events) >= 100 {
					break
				}
				copy := map[string]any{}
				for k, value := range item {
					if k == "event_id" || k == "kind" || k == "start" || k == "end" || k == "geometry" {
						copy[k] = value
					}
				}
				encodedSize := len(product.JSON(copy))
				if encodedSize > 65536 || geometryBytes+encodedSize > 1048576 {
					continue
				}
				geometryBytes += encodedSize
				copy["kind"] = p.kind
				copy["run_id"] = p.id
				copy["report_sha256"] = p.sha
				copy["calculation_id"] = p.cid
				events = append(events, copy)
			}
		}
	}
	if e != nil {
		eventState = "unavailable"
		events = []map[string]any{}
	}
	snapshot, e := s.advisorySnapshot(r)
	advisoryState := "unknown"
	polygons := []map[string]any{}
	circles := []map[string]any{}
	if e == nil {
		for _, bulletin := range snapshot.Items {
			if !bulletin.Message.Operational || bulletin.Lifecycle.State == "superseded" || bulletin.Lifecycle.State == "cancelled" {
				continue
			}
			for _, info := range bulletin.Message.Infos {
				if info.Effective.After(end) || info.Expires != nil && !info.Expires.After(start) {
					continue
				}
				for _, area := range info.Areas {
					for _, circle := range area.Circles {
						if len(circles) >= 100 {
							break
						}
						circles = append(circles, map[string]any{"revision_id": bulletin.Message.RevisionID, "event": info.Event, "severity": info.Severity, "effective": info.Effective, "expires": info.Expires, "circle": circle})
					}
					for _, geometry := range area.Polygons {
						if len(polygons) >= 100 {
							break
						}
						polygons = append(polygons, map[string]any{"revision_id": bulletin.Message.RevisionID, "event": info.Event, "severity": info.Severity, "effective": info.Effective, "expires": info.Expires, "geometry": geometry})
					}
				}
			}
		}
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	json.NewEncoder(w).Encode(map[string]any{"as_of": time.Now().UTC(), "bbox": bounds, "start": start, "end": end, "profiles": json.RawMessage(profiles), "fields": json.RawMessage(fields), "events": events, "event_state": eventState, "advisory_polygons": polygons, "advisory_circles": circles, "advisory_sources": snapshot.Sources, "advisory_state": advisoryState, "unavailable_layers": product.Catalog().Unavailable, "limitations": []string{"At most 200 profiles, 100 retained event components and 100 advisory polygons/circles are plotted. Tables and exact evidence links remain available.", "Events are frozen diagnostic report candidates. No live event absence or operational warning completeness is inferred.", "Unknown/missing/text-only advisory areas remain in the authority explorer; polygons alone never establish an all-clear.", "Raster controls use original native cells and field release masks. No unsupported map confidence or interpolated profile surface is drawn."}})
}
