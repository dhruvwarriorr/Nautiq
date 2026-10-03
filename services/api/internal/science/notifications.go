package science

import (
	"context"
	"encoding/json"
	"errors"
	"math"
	"net/http"
	"sort"
	"time"

	pb "nautiq.local/api/gen/nautiq/platform/v1"
	"nautiq.local/api/internal/advisories"
	"nautiq.local/api/internal/notifications"
	"nautiq.local/api/internal/product"
	"nautiq.local/api/internal/trips"
)

type notificationShape struct {
	geometry   []byte
	lat, lon   float64
	route      *trips.Request
	start, end time.Time
	polygon    bool
}

func (s *Server) notificationShape(ctx context.Context, in notifications.Input, now time.Time) (notificationShape, error) {
	shape := notificationShape{start: now, end: now.Add(time.Hour)}
	var watch product.Watch
	if product.Strict(in.Watch, &watch) != nil {
		return shape, errors.New("invalid_watch")
	}
	var geometry any
	switch watch.Type {
	case "point":
		if watch.Latitude == nil || watch.Longitude == nil || watch.RadiusKM == nil {
			return shape, errors.New("invalid_point")
		}
		shape.lat, shape.lon = *watch.Latitude, *watch.Longitude
		if *watch.RadiusKM > 0 {
			shape.polygon = true
			err := s.DB.QueryRow(ctx, `SELECT ST_AsGeoJSON(ST_Buffer(ST_SetSRID(ST_MakePoint($1,$2),4326)::geography,$3,'quad_segs=12')::geometry)`, shape.lon, shape.lat, *watch.RadiusKM*1000).Scan(&shape.geometry)
			if err != nil {
				return shape, err
			}
		} else {
			geometry = map[string]any{"type": "Point", "coordinates": []float64{shape.lon, shape.lat}}
		}
	case "place":
		found := false
		for _, p := range product.Catalog().Locations {
			if p.Slug == watch.Place {
				shape.lat, shape.lon = p.Latitude, p.Longitude
				found = true
			}
		}
		if !found {
			return shape, errors.New("unknown_place")
		}
		geometry = map[string]any{"type": "Point", "coordinates": []float64{shape.lon, shape.lat}}
	case "polygon":
		shape.polygon = true
		geometry = map[string]any{"type": "Polygon", "coordinates": [][][]float64{watch.Polygon}}
	case "route":
		var route trips.Request
		if product.Strict(in.Route, &route) != nil || len(route.Waypoints) < 2 {
			return shape, errors.New("route_missing")
		}
		if !route.Waypoints[len(route.Waypoints)-1].Time.After(now) {
			return shape, errors.New("saved_route_expired")
		}
		// Keep the saved schedule, but evaluate only the untraversed portion.
		for i := 1; i < len(route.Waypoints); i++ {
			if route.Waypoints[i-1].Time.Before(now) && route.Waypoints[i].Time.After(now) {
				a, b := route.Waypoints[i-1], route.Waypoints[i]
				first := trips.Interpolate(a, b, float64(now.Sub(a.Time))/float64(b.Time.Sub(a.Time)))
				first.Time = now
				route.Waypoints = append([]trips.Point{first}, route.Waypoints[i:]...)
				break
			}
			if route.Waypoints[i].Time.Equal(now) {
				route.Waypoints = route.Waypoints[i:]
				break
			}
		}
		shape.route = &route
		shape.start = route.Waypoints[0].Time
		shape.end = route.Waypoints[len(route.Waypoints)-1].Time
		if shape.start.Before(now) {
			shape.start = now
		}
		coords := [][]float64{}
		for _, p := range route.Waypoints {
			coords = append(coords, []float64{p.Longitude, p.Latitude})
		}
		geometry = map[string]any{"type": "LineString", "coordinates": coords}
		stationary := true
		for _, p := range route.Waypoints[1:] {
			stationary = stationary && trips.Distance(route.Waypoints[0], p) < 1e-8
		}
		if stationary {
			geometry = map[string]any{"type": "Point", "coordinates": coords[0]}
		}
	default:
		return shape, errors.New("unknown_watch_geometry")
	}
	if geometry != nil {
		shape.geometry = notifications.JSON(geometry)
	}
	var valid bool
	err := s.DB.QueryRow(ctx, `SELECT ST_IsValid(g) AND NOT ST_IsEmpty(g) AND ST_XMax(Box3D(g))-ST_XMin(Box3D(g))<=180 FROM (SELECT ST_SetSRID(ST_GeomFromGeoJSON($1),4326) g) t`, string(shape.geometry)).Scan(&valid)
	if err != nil {
		return shape, err
	}
	if !valid {
		return shape, errors.New("invalid_or_dateline_watch_geometry")
	}
	return shape, nil
}

type notificationField struct {
	Release     string          `json:"release_id"`
	SHA         string          `json:"manifest_sha256"`
	Freshness   string          `json:"freshness"`
	Variable    string          `json:"variable"`
	Approved    bool            `json:"release_approved"`
	Calculation json.RawMessage `json:"calculation"`
	Metadata    json.RawMessage `json:"metadata"`
	Result      json.RawMessage `json:"result"`
}
type notificationSample struct {
	Value     *float64        `json:"value"`
	Status    string          `json:"status"`
	Units     string          `json:"units"`
	Latitude  float64         `json:"latitude"`
	Longitude float64         `json:"longitude"`
	Time      string          `json:"requested_time"`
	Temporal  json.RawMessage `json:"temporal_support"`
	Spatial   json.RawMessage `json:"spatial_support"`
}

func (s *Server) notificationField(ctx context.Context, shape notificationShape, variable string, now time.Time) (notificationField, notifications.Pin, []byte, error) {
	var out notificationField
	pin := notifications.Pin{Kind: "field", Product: map[string]string{"wave_height_m": "noaa_gfs_wave", "wind_speed_m_s": "noaa_gfs_weather", "current_speed_m_s": "hycom_espc"}[variable]}
	err := s.DB.QueryRow(ctx, `SELECT r.release_id::text,r.manifest_sha256 FROM field_selection s JOIN field_releases r USING(release_id) WHERE s.product_id=$1 AND r.status='ready'`, pin.Product).Scan(&pin.ID, &pin.SHA)
	if err != nil || s.Fields == nil {
		return out, pin, nil, errors.New("selected_field_unavailable")
	}
	rpcCtx, cancel := context.WithTimeout(ctx, 6*time.Second)
	defer cancel()
	var response *pb.FieldEvidence
	switch {
	case shape.route != nil:
		req := &pb.FieldRouteRequest{ReleaseId: pin.ID, Variable: variable, SpacingKm: shape.route.SpacingKM, StepMinutes: shape.route.StepMinutes}
		for _, p := range shape.route.Waypoints {
			req.Waypoints = append(req.Waypoints, &pb.TimedFieldPoint{Latitude: p.Latitude, Longitude: p.Longitude, Time: p.Time.UTC().Format(time.RFC3339)})
		}
		response, err = s.Fields.Route(rpcCtx, req)
	case shape.polygon:
		response, err = s.Fields.Polygon(rpcCtx, &pb.FieldPolygonRequest{ReleaseId: pin.ID, Variable: variable, Time: now.Format(time.RFC3339), GeometryJson: shape.geometry})
	default:
		response, err = s.Fields.Sample(rpcCtx, &pb.FieldSampleRequest{ReleaseId: pin.ID, Variable: variable, Point: &pb.TimedFieldPoint{Latitude: shape.lat, Longitude: shape.lon, Time: now.Format(time.RFC3339)}})
	}
	if err != nil || response == nil || response.ReleaseId != pin.ID || response.ManifestSha256 != pin.SHA || len(response.ResultJson) > 900000 || json.Unmarshal(response.ResultJson, &out) != nil || out.Release != pin.ID || out.SHA != pin.SHA || out.Variable != variable || out.Approved || len(out.Calculation) == 0 || len(out.Metadata) == 0 {
		return out, pin, nil, errors.New("field_evidence_contract")
	}
	return out, pin, response.ResultJson, nil
}

// Maximum uses fresh values only; stale retained extrema cannot fire or recover a threshold.
func fieldMaximum(field notificationField, units string) (*float64, bool, any, error) {
	var shape struct {
		Samples   []notificationSample `json:"samples"`
		Status    string               `json:"status"`
		Maximum   *float64             `json:"maximum"`
		Cells     *int                 `json:"native_cells"`
		Available int                  `json:"available_cells"`
	}
	if json.Unmarshal(field.Result, &shape) != nil {
		return nil, false, nil, errors.New("invalid_field_result")
	}
	complete := field.Freshness == "available" && shape.Status == "available"
	if shape.Cells != nil {
		var metadata struct {
			Variables map[string]struct {
				Units string `json:"units"`
			} `json:"variable_metadata"`
		}
		if json.Unmarshal(field.Metadata, &metadata) != nil || metadata.Variables[field.Variable].Units != units {
			return nil, false, nil, errors.New("field_units")
		}
		if field.Freshness != "available" {
			return nil, false, map[string]any{"status": field.Freshness}, nil
		}
		if shape.Maximum != nil && (math.IsNaN(*shape.Maximum) || math.IsInf(*shape.Maximum, 0) || *shape.Maximum < 0) {
			return nil, false, nil, errors.New("invalid_field_value")
		}
		return shape.Maximum, complete && *shape.Cells > 0 && shape.Available == *shape.Cells, map[string]any{"native_cells": shape.Cells, "available_cells": shape.Available, "maximum": shape.Maximum, "scope": "native cell centers; unsampled extremes are not guaranteed"}, nil
	}
	samples := shape.Samples
	if samples == nil {
		var sample notificationSample
		if json.Unmarshal(field.Result, &sample) != nil {
			return nil, false, nil, errors.New("invalid_field_sample")
		}
		samples = []notificationSample{sample}
	}
	if len(samples) == 0 || len(samples) > 512 {
		return nil, false, nil, errors.New("sample_budget")
	}
	var max *float64
	var worst any
	count := 0
	for _, p := range samples {
		if p.Units != units {
			return nil, false, nil, errors.New("field_units")
		}
		if p.Status != "available" || field.Freshness != "available" || p.Value == nil {
			complete = false
			continue
		}
		if math.IsNaN(*p.Value) || math.IsInf(*p.Value, 0) || *p.Value < 0 {
			return nil, false, nil, errors.New("invalid_field_value")
		}
		count++
		if max == nil || *p.Value > *max {
			v := *p.Value
			max = &v
			worst = p
		}
	}
	return max, complete && count == len(samples), map[string]any{"maximum": max, "worst_sample": worst, "sample_count": len(samples), "fresh_samples": count, "scope": "retained sampled support; conditions between samples remain unresolved"}, nil
}

func (s *Server) notificationAdvisories(ctx context.Context, shape notificationShape, now time.Time) (advisories.State, []notifications.Pin, []string, error) {
	req, _ := http.NewRequestWithContext(ctx, "GET", "http://localhost/internal", nil)
	snapshot, err := s.advisorySnapshot(req)
	if err != nil {
		return advisories.State{}, nil, nil, err
	}
	pins := []notifications.Pin{}
	retired := []string{}
	for _, src := range snapshot.Sources {
		var policy []byte
		var run, revision string
		var checked *time.Time
		err = s.DB.QueryRow(ctx, `SELECT policy,COALESCE(latest_run_id::text,''),checked_at,md5(policy::text||transport||COALESCE(checked_at::text,'')) FROM advisory_sources WHERE source_id=$1`, src.ID).Scan(&policy, &run, &checked, &revision)
		expected := ""
		if src.RunID != nil {
			expected = *src.RunID
		}
		if err != nil || run != expected || !equalSourcePolicy(policy, src.Policy) || !equalSourceTime(checked, src.CheckedAt) {
			return advisories.State{}, nil, nil, errors.New("advisory_source_superseded")
		}
		pins = append(pins, notifications.Pin{Kind: "advisory_source", ID: run, Product: src.ID, Revision: revision})
	}
	messages := []advisories.Message{}
	for _, b := range snapshot.Items {
		messages = append(messages, b.Message)
		if b.Lifecycle.State == "cancelled" || b.Lifecycle.State == "superseded" {
			retired = append(retired, b.Message.RevisionID)
		}
	}
	hits := map[string]map[int]bool{}
	if shape.route != nil {
		hits, err = s.tripAdvisoryHits(req, snapshot, *shape.route)
		if err != nil {
			return advisories.State{}, nil, nil, err
		}
	} else {
		rows, err := s.DB.Query(ctx, `WITH infos AS (SELECT m->>'revision_id' id,i,ii::int-1 idx FROM jsonb_array_elements($1::jsonb) m CROSS JOIN LATERAL jsonb_array_elements(m->'infos') WITH ORDINALITY AS v(i,ii)), areas AS (SELECT id,i,idx,a FROM infos CROSS JOIN LATERAL jsonb_array_elements(i->'areas') a), watch AS (SELECT ST_SetSRID(ST_GeomFromGeoJSON($2),4326) g)
	 SELECT DISTINCT id,idx FROM areas,watch WHERE (i->>'effective')::timestamptz<=$4 AND (i->>'expires' IS NULL OR (i->>'expires')::timestamptz>$3) AND (
	 EXISTS(SELECT 1 FROM jsonb_array_elements(a->'polygons') p WHERE ST_Intersects(ST_SetSRID(ST_GeomFromGeoJSON(p::text),4326)::geography,g::geography)) OR
	 EXISTS(SELECT 1 FROM jsonb_array_elements(a->'circles') c WHERE ST_DWithin(ST_SetSRID(ST_MakePoint((c->'center'->>0)::float8,(c->'center'->>1)::float8),4326)::geography,g::geography,(c->>'radius_km')::float8*1000)))`, notifications.JSON(messages), string(shape.geometry), shape.start, shape.end)
		if err != nil {
			return advisories.State{}, nil, nil, err
		}
		defer rows.Close()
		for rows.Next() {
			var id string
			var idx int
			if rows.Scan(&id, &idx) != nil {
				return advisories.State{}, nil, nil, errors.New("advisory_geometry")
			}
			if hits[id] == nil {
				hits[id] = map[int]bool{}
			}
			hits[id][idx] = true
		}
		if err = rows.Err(); err != nil {
			return advisories.State{}, nil, nil, err
		}
	}
	result := advisories.Evaluate(snapshot, shape.start, shape.end, hits)
	for _, warning := range result.Warnings {
		for _, b := range snapshot.Items {
			if b.Message.RevisionID == warning.RevisionID {
				pins = append(pins, notifications.Pin{Kind: "advisory_revision", ID: warning.RevisionID, SHA: b.RawSHA})
			}
		}
	}
	sort.Strings(retired)
	return result, pins, retired, nil
}
func equalSourcePolicy(a, b []byte) bool {
	var x, y any
	return json.Unmarshal(a, &x) == nil && json.Unmarshal(b, &y) == nil && product.Hash(product.JSON(x)) == product.Hash(product.JSON(y))
}
func equalSourceTime(a, b *time.Time) bool {
	if a == nil || b == nil {
		return a == nil && b == nil
	}
	return a.Equal(*b)
}

func (s *Server) NotificationEvidence(ctx context.Context, in notifications.Input, now time.Time) (notifications.Evidence, error) {
	out := notifications.Evidence{Outcome: "unknown", AsOf: now, Reasons: []string{}, Pins: []notifications.Pin{}}
	shape, err := s.notificationShape(ctx, in, now)
	if err != nil {
		return out, err
	}
	if in.Rule.Type == "field_threshold" {
		field, pin, raw, err := s.notificationField(ctx, shape, in.Rule.Variable, now)
		if err != nil {
			return out, err
		}
		maximum, complete, facts, err := fieldMaximum(field, in.Rule.Units)
		if err != nil || in.Rule.Limit == nil {
			return out, errors.New("threshold_evidence")
		}
		out.Pins = []notifications.Pin{pin}
		out.Blobs = [][]byte{raw}
		out.BlobHashes = []string{notifications.Hash(raw)}
		out.Outcome, out.Severity = notifications.Threshold(maximum, *in.Rule.Limit, complete)
		out.Fresh = complete
		out.Facts = notifications.JSON(map[string]any{"field": facts, "variable": in.Rule.Variable, "units": in.Rule.Units, "limit": in.Rule.Limit, "inequality": "value >= personal limit", "freshness": field.Freshness, "calculation": field.Calculation})
		if out.Outcome == "unknown" {
			out.Reasons = []string{"incomplete_or_stale_field_support"}
		}
		// Request/output hashes distinguish positive fresh evidence; repeated snapshots do not confirm recovery.
		out.Fingerprint = notifications.Hash(notifications.JSON([]any{out.Pins, out.Facts}))
		return out, nil
	}
	state, pins, retired, err := s.notificationAdvisories(ctx, shape, now)
	if err != nil && in.Rule.Type == "official_advisory" {
		return out, err
	}
	if err != nil {
		out.Reasons = append(out.Reasons, "advisory_evidence_unavailable")
	}
	out.Pins = pins
	if in.Rule.Type == "official_advisory" {
		warnings := []any{}
		for _, w := range state.Warnings {
			out.Warnings = append(out.Warnings, w.RevisionID)
			severity := map[string]int{"Minor": 1, "Moderate": 1, "Severe": 2, "Extreme": 3}[w.Severity]
			if severity == 0 {
				severity = 1
			}
			if severity > out.Severity {
				out.Severity = severity
			}
			warnings = append(warnings, map[string]any{"revision_id": w.RevisionID, "source_id": w.SourceID, "severity": w.Severity, "effective": w.Effective, "expires": w.Expires, "info_index": w.InfoIndex})
		}
		if state.Status == "official_warning" {
			out.Outcome = "triggered"
		} else if state.Status == "known_none_intersecting" && state.ProductionApproved {
			out.Outcome = "clear"
			out.Fresh = true
		}
		out.Retired = retired
		out.Reasons = state.Unknown
		sources := []any{}
		for _, s := range state.Sources {
			sources = append(sources, map[string]any{"source_id": s.ID, "transport": s.Transport, "coverage": s.Coverage, "run_id": s.RunID, "checked_at": s.CheckedAt})
		}
		out.Facts = notifications.JSON(map[string]any{"status": state.Status, "warnings": warnings, "sources": sources, "window_start": shape.start, "window_end": shape.end, "meaning": "Relevant official authority references; no bulletin content is redistributed."})
		out.Fingerprint = notifications.Hash(notifications.JSON([]any{warnings, retired, out.Outcome}))
		return out, nil
	}
	if in.Rule.Type != "source_stale" {
		return out, errors.New("unsupported_alert_type")
	}
	complete := len(state.Sources) > 0
	stale := []string{}
	sources := []any{}
	for _, src := range state.Sources {
		sources = append(sources, map[string]any{"source_id": src.ID, "transport": src.Transport, "checked_at": src.CheckedAt, "integrity": src.Integrity})
		if src.Transport == "stale" && src.Integrity == "ready" {
			stale = append(stale, src.ID)
		}
		if src.Transport != "healthy" || src.Integrity != "ready" {
			complete = false
		}
	}
	for _, variable := range []string{"wave_height_m", "wind_speed_m_s", "current_speed_m_s"} {
		field, pin, raw, err := s.notificationField(ctx, shape, variable, now)
		if err != nil {
			complete = false
			out.Reasons = append(out.Reasons, variable+":unavailable")
			continue
		}
		out.Pins = append(out.Pins, pin)
		out.Blobs = append(out.Blobs, raw)
		out.BlobHashes = append(out.BlobHashes, notifications.Hash(raw))
		sources = append(sources, map[string]any{"variable": variable, "release_id": pin.ID, "freshness": field.Freshness})
		if field.Freshness == "stale" {
			stale = append(stale, variable)
		}
		if field.Freshness != "available" {
			complete = false
		}
	}
	sort.Strings(stale)
	if len(stale) > 0 {
		out.Outcome = "triggered"
		out.Severity = 1
	} else if complete {
		out.Outcome = "clear"
		out.Fresh = true
	}
	out.Facts = notifications.JSON(map[string]any{"sources": sources, "stale_sources": stale, "meaning": "Source transport/cycle freshness only; recovery does not establish complete warning coverage or safe conditions."})
	if out.Outcome == "unknown" {
		out.Reasons = append(out.Reasons, "fresh_source_evidence_incomplete")
	}
	// Stale age alone does not create a revision. Positive clear evidence includes new transport/field receipts.
	if out.Outcome == "triggered" {
		out.Fingerprint = notifications.Hash(notifications.JSON([]any{stale, out.Pins}))
	} else {
		out.Fingerprint = notifications.Hash(notifications.JSON([]any{out.Pins, out.BlobHashes, out.Facts}))
	}
	return out, nil
}
