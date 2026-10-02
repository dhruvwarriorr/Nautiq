package science

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"math"
	"net/http"
	"regexp"
	"strconv"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	pb "nautiq.local/api/gen/nautiq/platform/v1"
)

var fieldName = regexp.MustCompile(`^[a-z][a-z0-9_]{0,63}$`)

func (s *Server) fields(w http.ResponseWriter, r *http.Request) {
	q, ok := query(w, r, "product_id", "limit")
	if !ok {
		return
	}
	n, ok := limit(q)
	if !ok {
		problem(w, 400, "invalid_limit")
		return
	}
	var product any
	if q.Has("product_id") {
		if !fieldName.MatchString(q.Get("product_id")) {
			problem(w, 400, "invalid_product_id")
			return
		}
		product = q.Get("product_id")
	}
	s.serve(w, r, `SELECT json_build_object('products',COALESCE((SELECT json_agg(t ORDER BY product_id) FROM (SELECT p.product_id,p.metadata,s.release_id selected_release_id,
 (SELECT json_build_object('status',u.status,'reason_code',u.reason_code,'started_at',u.started_at,'completed_at',u.completed_at,'upstream_checked_at',u.upstream_checked_at) FROM field_ingestion_runs u WHERE u.product_id=p.product_id ORDER BY u.started_at DESC LIMIT 1) latest_run
 FROM field_products p LEFT JOIN field_selection s USING(product_id)) t),'[]'), 'items',COALESCE((SELECT json_agg(t) FROM (
 SELECT r.release_id,r.product_id,r.calculation_id,r.cycle,r.valid_time_start,r.valid_time_end,r.source_version,r.created_at,r.manifest_sha256,r.status,r.release_approved,
 r.manifest->'metadata' metadata,EXISTS(SELECT 1 FROM field_selection s WHERE s.release_id=r.release_id) selected,
 CASE WHEN COALESCE(r.cycle,r.valid_time_end)+make_interval(hours=>(r.manifest->'metadata'->>'max_age_hours')::integer)<now() THEN 'stale' ELSE 'available' END freshness
 FROM field_releases r WHERE ($1::text IS NULL OR r.product_id=$1) ORDER BY r.created_at DESC,r.release_id LIMIT $2) t),'[]'))`, product, n)
}
func (s *Server) fieldDetail(w http.ResponseWriter, r *http.Request) {
	if _, ok := query(w, r); !ok {
		return
	}
	id, ok := identifier(w, r)
	if !ok {
		return
	}
	s.serve(w, r, `SELECT json_build_object('release_id',r.release_id,'product_id',r.product_id,'calculation_id',r.calculation_id,'manifest_sha256',r.manifest_sha256,
 'cycle',r.cycle,'valid_time_start',r.valid_time_start,'valid_time_end',r.valid_time_end,'source_version',r.source_version,'created_at',r.created_at,'status',r.status,'release_approved',r.release_approved,
 'selected',EXISTS(SELECT 1 FROM field_selection s WHERE s.release_id=r.release_id),'manifest',r.manifest,'metadata',r.manifest->'metadata',
 'freshness',CASE WHEN COALESCE(r.cycle,r.valid_time_end)+make_interval(hours=>(r.manifest->'metadata'->>'max_age_hours')::integer)<now() THEN 'stale' ELSE 'available' END) FROM field_releases r WHERE r.release_id=$1`, id)
}

func fieldTime(value string) bool {
	_, err := time.Parse(time.RFC3339, value)
	return err == nil && len(value) <= 40
}
func fieldID(value string) bool { _, err := uuid.Parse(value); return err == nil }
func coordinate(value string, low, high float64) (float64, bool) {
	n, err := strconv.ParseFloat(value, 64)
	return n, err == nil && !math.IsNaN(n) && !math.IsInf(n, 0) && n >= low && n <= high
}
func fieldRPCError(w http.ResponseWriter, err error) {
	switch status.Code(err) {
	case codes.InvalidArgument:
		problem(w, 400, "invalid_field_request")
	case codes.NotFound:
		problem(w, 404, "field_not_found")
	case codes.ResourceExhausted:
		w.Header().Set("Retry-After", "1")
		problem(w, 429, "field_capacity_exceeded")
	default:
		problem(w, 503, "field_runtime_or_integrity_unavailable")
	}
}
func (s *Server) fieldPin(w http.ResponseWriter, r *http.Request, id string) (string, bool) {
	if !fieldID(id) {
		problem(w, 400, "invalid_field_release_id")
		return "", false
	}
	var sha, state string
	err := s.DB.QueryRow(r.Context(), "SELECT manifest_sha256,status FROM field_releases WHERE release_id=$1", id).Scan(&sha, &state)
	if errors.Is(err, pgx.ErrNoRows) {
		problem(w, 404, "field_not_found")
		return "", false
	}
	if err != nil || state != "ready" || s.Fields == nil {
		problem(w, 503, "field_unavailable")
		return "", false
	}
	return sha, true
}
func sendField(w http.ResponseWriter, id, sha string, response *pb.FieldEvidence) {
	var evidence struct {
		ReleaseID       string          `json:"release_id"`
		ManifestSHA256  string          `json:"manifest_sha256"`
		ReleaseApproved bool            `json:"release_approved"`
		Result          json.RawMessage `json:"result"`
	}
	if response == nil || response.ReleaseId != id || response.ManifestSha256 != sha || len(response.ResultJson) > 900000 || json.Unmarshal(response.ResultJson, &evidence) != nil || evidence.ReleaseID != id || evidence.ManifestSHA256 != sha || evidence.ReleaseApproved || len(evidence.Result) == 0 {
		problem(w, 503, "field_response_contract_failed")
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Field-Manifest-SHA256", sha)
	w.Write(response.ResultJson)
}
func (s *Server) fieldSample(w http.ResponseWriter, r *http.Request) {
	q, ok := query(w, r, "release_id", "variable", "latitude", "longitude", "time")
	if !ok {
		return
	}
	lat, la := coordinate(q.Get("latitude"), -90, 90)
	lon, lo := coordinate(q.Get("longitude"), -180, 180)
	if !la || !lo || !fieldTime(q.Get("time")) || !fieldName.MatchString(q.Get("variable")) {
		problem(w, 400, "invalid_timed_field_point")
		return
	}
	id := q.Get("release_id")
	sha, ok := s.fieldPin(w, r, id)
	if !ok {
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 6*time.Second)
	defer cancel()
	response, err := s.Fields.Sample(ctx, &pb.FieldSampleRequest{ReleaseId: id, Variable: q.Get("variable"), Point: &pb.TimedFieldPoint{Latitude: lat, Longitude: lon, Time: q.Get("time")}})
	if err != nil {
		fieldRPCError(w, err)
		return
	}
	sendField(w, id, sha, response)
}

type fieldPoint struct {
	Latitude  *float64 `json:"latitude"`
	Longitude *float64 `json:"longitude"`
	Time      string   `json:"time"`
}
type fieldBody struct {
	ReleaseID   string       `json:"release_id"`
	Variable    string       `json:"variable"`
	Waypoints   []fieldPoint `json:"waypoints"`
	SpacingKM   *float64     `json:"spacing_km"`
	StepMinutes *float64     `json:"step_minutes"`
}

func decodeField(w http.ResponseWriter, r *http.Request, value any) bool {
	if r.Header.Get("Content-Type") != "application/json" {
		problem(w, 415, "json_required")
		return false
	}
	r.Body = http.MaxBytesReader(w, r.Body, 32768)
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	if decoder.Decode(value) != nil || decoder.Decode(&struct{}{}) != io.EOF {
		problem(w, 400, "invalid_field_body")
		return false
	}
	return true
}
func (s *Server) fieldRoute(w http.ResponseWriter, r *http.Request) {
	if _, ok := query(w, r); !ok {
		return
	}
	var body fieldBody
	if !decodeField(w, r, &body) {
		return
	}
	if !fieldName.MatchString(body.Variable) || len(body.Waypoints) < 2 || len(body.Waypoints) > 32 {
		problem(w, 400, "invalid_route")
		return
	}
	request := &pb.FieldRouteRequest{ReleaseId: body.ReleaseID, Variable: body.Variable, SpacingKm: 5, StepMinutes: 30}
	if body.SpacingKM != nil {
		request.SpacingKm = *body.SpacingKM
	}
	if body.StepMinutes != nil {
		request.StepMinutes = *body.StepMinutes
	}
	for _, p := range body.Waypoints {
		if p.Latitude == nil || p.Longitude == nil || !fieldTime(p.Time) || *p.Latitude < -85 || *p.Latitude > 85 || *p.Longitude < -180 || *p.Longitude > 180 {
			problem(w, 400, "timed_waypoints_required")
			return
		}
		request.Waypoints = append(request.Waypoints, &pb.TimedFieldPoint{Latitude: *p.Latitude, Longitude: *p.Longitude, Time: p.Time})
	}
	sha, ok := s.fieldPin(w, r, body.ReleaseID)
	if !ok {
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 6*time.Second)
	defer cancel()
	response, err := s.Fields.Route(ctx, request)
	if err != nil {
		fieldRPCError(w, err)
		return
	}
	sendField(w, body.ReleaseID, sha, response)
}
func (s *Server) fieldPolygon(w http.ResponseWriter, r *http.Request) {
	if _, ok := query(w, r); !ok {
		return
	}
	var body struct {
		ReleaseID string          `json:"release_id"`
		Variable  string          `json:"variable"`
		Time      string          `json:"time"`
		Geometry  json.RawMessage `json:"geometry"`
	}
	if !decodeField(w, r, &body) {
		return
	}
	if !fieldName.MatchString(body.Variable) || !fieldTime(body.Time) || len(body.Geometry) > 16000 || len(body.Geometry) == 0 {
		problem(w, 400, "invalid_polygon_request")
		return
	}
	sha, ok := s.fieldPin(w, r, body.ReleaseID)
	if !ok {
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 6*time.Second)
	defer cancel()
	response, err := s.Fields.Polygon(ctx, &pb.FieldPolygonRequest{ReleaseId: body.ReleaseID, Variable: body.Variable, Time: body.Time, GeometryJson: body.Geometry})
	if err != nil {
		fieldRPCError(w, err)
		return
	}
	sendField(w, body.ReleaseID, sha, response)
}
func (s *Server) fieldTile(w http.ResponseWriter, r *http.Request) {
	q, ok := query(w, r, "time")
	if !ok {
		return
	}
	z, ze := strconv.Atoi(r.PathValue("z"))
	x, xe := strconv.Atoi(r.PathValue("x"))
	y, ye := strconv.Atoi(r.PathValue("y"))
	if ze != nil || xe != nil || ye != nil || z < 0 || z > 12 || x < 0 || x >= 1<<z || y < 0 || y >= 1<<z || !fieldTime(q.Get("time")) || !fieldName.MatchString(r.PathValue("variable")) {
		problem(w, 400, "invalid_tile_request")
		return
	}
	id := r.PathValue("id")
	sha, ok := s.fieldPin(w, r, id)
	if !ok {
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 6*time.Second)
	defer cancel()
	response, err := s.Fields.Tile(ctx, &pb.FieldTileRequest{ReleaseId: id, Variable: r.PathValue("variable"), Time: q.Get("time"), Z: int32(z), X: int32(x), Y: int32(y)})
	if err != nil {
		fieldRPCError(w, err)
		return
	}
	var metadata struct {
		Freshness string `json:"freshness"`
		Metadata  struct {
			Cycle       *string `json:"cycle"`
			Attribution string  `json:"attribution"`
		} `json:"metadata"`
	}
	if response == nil || response.ReleaseId != id || response.ManifestSha256 != sha || len(response.Png) > 300000 || len(response.Png) < 8 || string(response.Png[:8]) != "\x89PNG\r\n\x1a\n" || json.Unmarshal(response.MetadataJson, &metadata) != nil {
		problem(w, 503, "field_tile_contract_failed")
		return
	}
	w.Header().Set("Content-Type", "image/png")
	w.Header().Set("Cache-Control", "private, max-age=60")
	w.Header().Set("X-Field-Release-ID", id)
	w.Header().Set("X-Field-Manifest-SHA256", sha)
	w.Header().Set("X-Field-Valid-Time", q.Get("time"))
	w.Header().Set("X-Field-Freshness", metadata.Freshness)
	if metadata.Metadata.Cycle != nil {
		w.Header().Set("X-Field-Cycle", *metadata.Metadata.Cycle)
	}
	w.Write(response.Png)
}
