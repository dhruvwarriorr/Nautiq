package science

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"reflect"
	"runtime"
	"runtime/debug"
	"sort"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/minio/minio-go/v7"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/proto"
	pb "nautiq.local/api/gen/nautiq/platform/v1"
	"nautiq.local/api/internal/advisories"
	"nautiq.local/api/internal/trips"
)

//go:embed trips.go advisories.go fields.go science.go events.go
var tripIntegration embed.FS

func tripCodeSHA() string {
	h := sha256.New()
	for _, n := range []string{"advisories.go", "events.go", "fields.go", "science.go", "trips.go"} {
		b, _ := tripIntegration.ReadFile(n)
		h.Write([]byte(n))
		h.Write(b)
	}
	h.Write([]byte(trips.CodeSHA()))
	h.Write([]byte(advisories.CodeSHA()))
	return hex.EncodeToString(h.Sum(nil))
}

func tripRuntime() string {
	dependencies := []string{}
	if info, ok := debug.ReadBuildInfo(); ok {
		for _, dep := range info.Deps {
			dependencies = append(dependencies, dep.Path+"@"+dep.Version+":"+dep.Sum)
		}
	}
	sort.Strings(dependencies)
	return runtime.Version() + "/" + runtime.GOOS + "/" + runtime.GOARCH + ":" + trips.Hash(dependencies)
}

type tripReceipt struct {
	SchemaVersion    int                     `json:"schema_version"`
	Kind             string                  `json:"kind"`
	CodeSHA          string                  `json:"code_sha256"`
	Runtime          string                  `json:"runtime"`
	Input            trips.Input             `json:"input"`
	AdvisorySnapshot advisories.Snapshot     `json:"advisory_snapshot"`
	AdvisoryHits     map[string]map[int]bool `json:"advisory_hits"`
	FieldEvidence    []json.RawMessage       `json:"field_evidence"`
	Output           trips.Verdict           `json:"output"`
}

func (s *Server) tripPolicy(w http.ResponseWriter, r *http.Request) {
	if _, ok := query(w, r); !ok {
		return
	}
	p := trips.DefaultPolicy()
	advisoryJSON(w, map[string]any{"policy": p, "engine_available": p.Available(), "code_sha256": tripCodeSHA(), "as_of": time.Now().UTC(), "limits": map[string]any{"waypoints": 32, "samples": 512, "distance_km": 1000, "hours": 24, "spacing_km": []float64{0.5, 5}, "step_minutes": []float64{1, 30}}, "private_receipts": "A random access token is returned once. It must be supplied as a Bearer header for evidence or replay; tokens and routes are not public calculation records."})
}

// Reject duplicate keys as well as unknown fields; never silently resolve ambiguous user inputs.
func uniqueJSON(data []byte) bool {
	d := json.NewDecoder(bytes.NewReader(data))
	var walk func(int) error
	walk = func(depth int) error {
		if depth > 12 {
			return errors.New("json_depth")
		}
		token, err := d.Token()
		if err != nil {
			return err
		}
		delim, ok := token.(json.Delim)
		if !ok {
			return nil
		}
		switch delim {
		case '{':
			seen := map[string]bool{}
			for d.More() {
				key, e := d.Token()
				if e != nil {
					return e
				}
				k, ok := key.(string)
				if !ok || seen[k] {
					return errors.New("duplicate_key")
				}
				seen[k] = true
				if e = walk(depth + 1); e != nil {
					return e
				}
			}
			end, e := d.Token()
			if e != nil || end != json.Delim('}') {
				return errors.New("invalid_object")
			}
		case '[':
			for d.More() {
				if e := walk(depth + 1); e != nil {
					return e
				}
			}
			end, e := d.Token()
			if e != nil || end != json.Delim(']') {
				return errors.New("invalid_array")
			}
		default:
			return errors.New("invalid_delimiter")
		}
		return nil
	}
	if walk(0) != nil {
		return false
	}
	_, err := d.Token()
	return err == io.EOF
}
func decodeTrip(w http.ResponseWriter, r *http.Request) (trips.Request, bool) {
	var req trips.Request
	if r.Header.Get("Content-Type") != "application/json" {
		problem(w, 415, "json_required")
		return req, false
	}
	data, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 32768))
	if err != nil || !uniqueJSON(data) {
		problem(w, 400, "invalid_or_ambiguous_trip_body")
		return req, false
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&req) != nil {
		problem(w, 400, "invalid_trip_body")
		return req, false
	}
	var shape struct {
		Waypoints []map[string]json.RawMessage `json:"waypoints"`
	}
	json.Unmarshal(data, &shape)
	for _, p := range shape.Waypoints {
		if len(p) != 3 || p["latitude"] == nil || p["longitude"] == nil || p["time"] == nil || bytes.Equal(p["latitude"], []byte("null")) || bytes.Equal(p["longitude"], []byte("null")) {
			problem(w, 400, "timed_waypoints_required")
			return req, false
		}
	}
	if len(req.Fields) > 3 {
		problem(w, 400, "field_binding_budget")
		return req, false
	}
	seen := map[string]bool{}
	policy := trips.DefaultPolicy()
	for _, f := range req.Fields {
		valid := false
		for _, spec := range policy.Inputs {
			valid = valid || f.Variable == spec.Variable
		}
		if !valid || seen[f.Variable] || !fieldID(f.ReleaseID) {
			problem(w, 400, "invalid_or_repeated_field_binding")
			return req, false
		}
		seen[f.Variable] = true
	}
	validActivity := false
	for _, a := range policy.Activities {
		validActivity = validActivity || a == req.Activity
	}
	if !validActivity || req.ThresholdVersion != policy.Version {
		problem(w, 400, "unknown_activity_or_threshold_version")
		return req, false
	}
	if _, err = policy.WithPreferences(req.Preferences); err != nil {
		problem(w, 400, err.Error())
		return req, false
	}
	return req, true
}

// Each CAP info window clips complete timed great-circle legs, including stationary stops.
// Intersections use PostGIS geography, rather than testing only discrete forecast samples.
func (s *Server) tripAdvisoryHits(r *http.Request, snapshot advisories.Snapshot, req trips.Request) (map[string]map[int]bool, error) {
	type pair struct {
		ID       string                `json:"id"`
		Index    int                   `json:"index"`
		Polygons []advisories.Geometry `json:"polygons"`
		Circles  []advisories.Circle   `json:"circles"`
		Routes   []map[string]any      `json:"routes"`
	}
	pairs := []pair{}
	for _, b := range snapshot.Items {
		if b.Lifecycle.State != "active" || !b.Message.Operational {
			continue
		}
		for ii, info := range b.Message.Infos {
			p := pair{ID: b.Message.RevisionID, Index: ii, Polygons: []advisories.Geometry{}, Circles: []advisories.Circle{}, Routes: []map[string]any{}}
			for _, a := range info.Areas {
				p.Polygons = append(p.Polygons, a.Polygons...)
				p.Circles = append(p.Circles, a.Circles...)
			}
			if len(p.Polygons)+len(p.Circles) == 0 {
				continue
			}
			for i := 1; i < len(req.Waypoints); i++ {
				a, z := req.Waypoints[i-1], req.Waypoints[i]
				start, end := a.Time, z.Time
				if info.Effective.After(start) {
					start = info.Effective
				}
				if info.Expires != nil && info.Expires.Before(end) {
					end = *info.Expires
				}
				if end.Before(start) || (info.Expires != nil && !info.Expires.After(start)) {
					continue
				}
				one := trips.Interpolate(a, z, float64(start.Sub(a.Time))/float64(z.Time.Sub(a.Time)))
				two := trips.Interpolate(a, z, float64(end.Sub(a.Time))/float64(z.Time.Sub(a.Time)))
				geo := map[string]any{"type": "LineString", "coordinates": [][]float64{{one.Longitude, one.Latitude}, {two.Longitude, two.Latitude}}}
				if trips.Distance(one, two) < 1e-8 {
					geo = map[string]any{"type": "Point", "coordinates": []float64{one.Longitude, one.Latitude}}
				}
				p.Routes = append(p.Routes, geo)
			}
			if len(p.Routes) > 0 {
				pairs = append(pairs, p)
			}
		}
	}
	data, _ := json.Marshal(pairs)
	if len(pairs) > 1024 || len(data) > 4<<20 {
		return nil, errors.New("advisory_route_intersection_budget")
	}
	rows, err := s.DB.Query(r.Context(), `SELECT DISTINCT p->>'id',(p->>'index')::int FROM jsonb_array_elements($1::jsonb) p WHERE
 EXISTS(SELECT 1 FROM jsonb_array_elements(p->'routes') r WHERE
 EXISTS(SELECT 1 FROM jsonb_array_elements(p->'polygons') g WHERE ST_Intersects(ST_SetSRID(ST_GeomFromGeoJSON(g::text),4326)::geography,ST_SetSRID(ST_GeomFromGeoJSON(r::text),4326)::geography)) OR
 EXISTS(SELECT 1 FROM jsonb_array_elements(p->'circles') c WHERE ST_DWithin(ST_SetSRID(ST_MakePoint((c->'center'->>0)::float8,(c->'center'->>1)::float8),4326)::geography,ST_SetSRID(ST_GeomFromGeoJSON(r::text),4326)::geography,(c->>'radius_km')::float8*1000)))`, data)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	hits := map[string]map[int]bool{}
	for rows.Next() {
		var id string
		var ii int
		if err = rows.Scan(&id, &ii); err != nil {
			return nil, err
		}
		if hits[id] == nil {
			hits[id] = map[int]bool{}
		}
		hits[id][ii] = true
	}
	return hits, rows.Err()
}

type tripFieldResponse struct {
	ReleaseID     string `json:"release_id"`
	SHA           string `json:"manifest_sha256"`
	Variable      string `json:"variable"`
	CalculationID string `json:"calculation_id"`
	Approved      bool   `json:"release_approved"`
	Metadata      struct {
		ProductID string     `json:"product_id"`
		Cycle     *time.Time `json:"cycle"`
		Start     time.Time  `json:"valid_time_start"`
		End       time.Time  `json:"valid_time_end"`
	} `json:"metadata"`
	Calculation struct {
		RequestSHA string `json:"request_sha256"`
	} `json:"calculation"`
	Result struct {
		Samples []struct {
			Latitude  float64   `json:"latitude"`
			Longitude float64   `json:"longitude"`
			Time      time.Time `json:"requested_time"`
			Value     *float64  `json:"value"`
			Units     string    `json:"units"`
			Status    string    `json:"status"`
			Reason    string    `json:"reason"`
		} `json:"samples"`
	} `json:"result"`
}

func (s *Server) tripField(r *http.Request, req trips.Request, binding trips.Binding) (trips.Field, json.RawMessage) {
	out := trips.Field{Variable: binding.Variable, ReleaseID: binding.ReleaseID, Samples: []trips.Sample{}}
	var sha, state string
	var metadata []byte
	err := s.DB.QueryRow(r.Context(), "SELECT manifest_sha256,status,manifest->'metadata' FROM field_releases WHERE release_id=$1", binding.ReleaseID).Scan(&sha, &state, &metadata)
	if err != nil || state != "ready" || s.Fields == nil {
		out.Error = "field_release_or_runtime_unavailable"
		return out, nil
	}
	out.ManifestSHA = sha
	request := &pb.FieldRouteRequest{ReleaseId: binding.ReleaseID, Variable: binding.Variable, SpacingKm: req.SpacingKM, StepMinutes: req.StepMinutes}
	for _, p := range req.Waypoints {
		request.Waypoints = append(request.Waypoints, &pb.TimedFieldPoint{Latitude: p.Latitude, Longitude: p.Longitude, Time: p.Time.Format(time.RFC3339Nano)})
	}
	ctx, cancel := context.WithTimeout(r.Context(), 6*time.Second)
	defer cancel()
	response, err := s.Fields.Route(ctx, request)
	if err != nil {
		out.Error = "field_sampling_" + strings.ToLower(status.Code(err).String())
		return out, nil
	}
	var frozen tripFieldResponse
	wire, _ := proto.MarshalOptions{Deterministic: true}.Marshal(request)
	hash := sha256.Sum256(wire)
	if response == nil || response.ReleaseId != binding.ReleaseID || response.ManifestSha256 != sha || len(response.ResultJson) > 900000 || json.Unmarshal(response.ResultJson, &frozen) != nil || frozen.ReleaseID != binding.ReleaseID || frozen.SHA != sha || frozen.Variable != binding.Variable || frozen.Calculation.RequestSHA != hex.EncodeToString(hash[:]) || len(frozen.Result.Samples) > 512 {
		out.Error = "field_response_contract_failed"
		return out, nil
	}
	normalized, err := normalizeTripField(response.ResultJson, binding, sha)
	if err != nil {
		out.Error = "field_response_contract_failed"
		return out, nil
	}
	return normalized, json.RawMessage(response.ResultJson)
}
func normalizeTripField(raw []byte, binding trips.Binding, sha string) (trips.Field, error) {
	out := trips.Field{Variable: binding.Variable, ReleaseID: binding.ReleaseID, ManifestSHA: sha, Samples: []trips.Sample{}}
	var frozen tripFieldResponse
	if len(raw) > 900000 || json.Unmarshal(raw, &frozen) != nil || frozen.ReleaseID != binding.ReleaseID || frozen.SHA != sha || frozen.Variable != binding.Variable || len(frozen.Result.Samples) > 512 {
		return out, errors.New("field_response_contract_failed")
	}
	out.ProductID = frozen.Metadata.ProductID
	out.CalculationID = frozen.CalculationID
	out.Cycle = frozen.Metadata.Cycle
	out.ValidStart = frozen.Metadata.Start
	out.ValidEnd = frozen.Metadata.End
	out.OperationalApproved = frozen.Approved
	out.EvidenceSHA = hexSHA(raw)
	for _, sample := range frozen.Result.Samples {
		out.Samples = append(out.Samples, trips.Sample{Point: trips.Point{Latitude: sample.Latitude, Longitude: sample.Longitude, Time: sample.Time}, Value: sample.Value, Units: sample.Units, Status: sample.Status, Reason: sample.Reason})
	}
	return out, nil
}

func hexSHA(data []byte) string { h := sha256.Sum256(data); return hex.EncodeToString(h[:]) }
func (s *Server) putTrip(r *http.Request, key string, data []byte) error {
	if len(data) == 0 || len(data) > 8<<20 {
		return errors.New("trip_receipt_budget")
	}
	sha := hexSHA(data)
	stat, err := s.Storage.StatObject(r.Context(), "nautiq", key, minio.StatObjectOptions{})
	if err == nil {
		if stat.Size != int64(len(data)) {
			return errors.New("immutable_trip_conflict")
		}
		return s.checkEventObject(r, key, sha, int64(len(data)))
	}
	if minio.ToErrorResponse(err).Code != "NoSuchKey" {
		return err
	}
	_, err = s.Storage.PutObject(r.Context(), "nautiq", key, bytes.NewReader(data), int64(len(data)), minio.PutObjectOptions{ContentType: "application/json", UserMetadata: map[string]string{"sha256": sha}})
	if err != nil {
		return err
	}
	return s.checkEventObject(r, key, sha, int64(len(data)))
}
func (s *Server) assessTrip(w http.ResponseWriter, r *http.Request) {
	if _, ok := query(w, r); !ok {
		return
	}
	req, ok := decodeTrip(w, r)
	if !ok {
		return
	}
	asOf := time.Now().UTC()
	points, sampling, err := trips.Points(req, asOf)
	if err != nil {
		problem(w, 400, err.Error())
		return
	}
	input := trips.Input{AsOf: asOf, Request: req, Policy: trips.DefaultPolicy(), Expected: points, Sampling: sampling, Fields: []trips.Field{}, AcquisitionIssues: []string{}}
	snapshot, err := s.advisorySnapshot(r)
	hits := map[string]map[int]bool{}
	if err != nil {
		snapshot = advisories.Snapshot{AsOf: asOf, Sources: []advisories.Source{}, Items: []advisories.Bulletin{}, Issues: []string{"advisory_evidence_unavailable"}}
		input.AcquisitionIssues = append(input.AcquisitionIssues, "advisory_evidence_unavailable")
	} else {
		asOf = snapshot.AsOf
		input.AsOf = asOf
		points, sampling, err = trips.Points(req, asOf)
		if err != nil {
			problem(w, 400, err.Error())
			return
		}
		input.Expected = points
		input.Sampling = sampling
		hits, err = s.tripAdvisoryHits(r, snapshot, req)
		if err != nil {
			input.AcquisitionIssues = append(input.AcquisitionIssues, "advisory_route_geometry_unavailable")
			snapshot.Issues = append(snapshot.Issues, "advisory_route_geometry_unavailable")
			hits = map[string]map[int]bool{}
		}
	}
	input.Advisory = advisories.Evaluate(snapshot, req.Waypoints[0].Time, req.Waypoints[len(req.Waypoints)-1].Time, hits)
	// Independent pinned field requests share the overall deadline and retain individual failures.
	type result struct {
		field trips.Field
		raw   json.RawMessage
	}
	results := make(chan result, len(req.Fields))
	for _, binding := range req.Fields {
		go func(b trips.Binding) { f, raw := s.tripField(r, req, b); results <- result{f, raw} }(binding)
	}
	collected := map[string]result{}
	for range req.Fields {
		value := <-results
		collected[value.field.Variable] = value
	}
	raw := []json.RawMessage{}
	for _, spec := range input.Policy.Inputs {
		if value, ok := collected[spec.Variable]; ok {
			input.Fields = append(input.Fields, value.field)
			if value.raw != nil {
				raw = append(raw, value.raw)
			}
		}
	}
	receipt := tripReceipt{SchemaVersion: 1, Kind: "trip_assessment", CodeSHA: tripCodeSHA(), Runtime: tripRuntime(), Input: input, AdvisorySnapshot: snapshot, AdvisoryHits: hits, FieldEvidence: raw}
	receipt.Output = trips.Evaluate(input)
	data, err := json.Marshal(receipt)
	if err != nil || len(data) > 8<<20 {
		problem(w, 503, "trip_receipt_budget")
		return
	}
	sha := hexSHA(data)
	id := uuid.NewSHA1(uuid.NameSpaceURL, []byte("nautiq:trip:"+sha)).String()
	key := "trips/private/" + sha + ".json"
	if err = s.putTrip(r, key, data); err != nil {
		problem(w, 503, "trip_evidence_storage_unavailable")
		return
	}
	tokenBytes := make([]byte, 32)
	if _, err = rand.Read(tokenBytes); err != nil {
		problem(w, 503, "trip_access_unavailable")
		return
	}
	token := hex.EncodeToString(tokenBytes)
	accessSHA := hexSHA([]byte(token))
	tx, err := s.DB.Begin(r.Context())
	if err != nil {
		problem(w, 503, "trip_publication_unavailable")
		return
	}
	defer tx.Rollback(r.Context())
	if _, err = tx.Exec(r.Context(), "SELECT pg_advisory_xact_lock(78192403)"); err != nil {
		problem(w, 503, "trip_publication_unavailable")
		return
	}
	// A source revision arriving while fields were sampled invalidates this request before publication.
	for _, src := range snapshot.Sources {
		var current *string
		var currentPolicy []byte
		err = tx.QueryRow(r.Context(), "SELECT latest_run_id::text,policy FROM advisory_sources WHERE source_id=$1", src.ID).Scan(&current, &currentPolicy)
		var frozenPolicy, livePolicy any
		policyChanged := json.Unmarshal(src.Policy, &frozenPolicy) != nil || json.Unmarshal(currentPolicy, &livePolicy) != nil || !reflect.DeepEqual(frozenPolicy, livePolicy)
		if err != nil || policyChanged || (current == nil) != (src.RunID == nil) || current != nil && *current != *src.RunID {
			problem(w, 409, "advisory_snapshot_changed_retry")
			return
		}
	}
	if _, err = tx.Exec(r.Context(), `INSERT INTO calculations(calculation_id,calculation_sha256,kind,method_version,manifest,manifest_key,manifest_sha256,state) VALUES($1,$2,'trip_assessment',$3,$4,$5,$2,'frozen')`, id, sha, input.Policy.Method, data, key); err != nil {
		problem(w, 503, "trip_publication_unavailable")
		return
	}
	verdict, _ := json.Marshal(receipt.Output)
	if _, err = tx.Exec(r.Context(), "INSERT INTO trip_calculations(calculation_id,access_sha256,verdict) VALUES($1,$2,$3)", id, accessSHA, verdict); err != nil {
		problem(w, 503, "trip_publication_unavailable")
		return
	}
	if err = tx.Commit(r.Context()); err != nil {
		problem(w, 503, "trip_publication_unavailable")
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(http.StatusCreated)
	advisoryJSON(w, map[string]any{"calculation_id": id, "access_token": token, "manifest_sha256": sha, "verdict": receipt.Output})
}
func (s *Server) privateTrip(w http.ResponseWriter, r *http.Request) (string, tripReceipt, bool) {
	var receipt tripReceipt
	id, ok := identifier(w, r)
	if !ok {
		return "", receipt, false
	}
	header := r.Header.Get("Authorization")
	if len(header) != 71 || !strings.HasPrefix(header, "Bearer ") {
		problem(w, 404, "evidence_not_found")
		return "", receipt, false
	}
	token := header[7:]
	if _, err := hex.DecodeString(token); err != nil {
		problem(w, 404, "evidence_not_found")
		return "", receipt, false
	}
	var access, sha, key string
	var mirror, verdict []byte
	err := s.DB.QueryRow(r.Context(), `SELECT t.access_sha256,c.manifest_sha256,c.manifest_key,c.manifest,t.verdict FROM trip_calculations t JOIN calculations c USING(calculation_id) WHERE calculation_id=$1 AND c.kind='trip_assessment'`, id).Scan(&access, &sha, &key, &mirror, &verdict)
	if err != nil || subtle.ConstantTimeCompare([]byte(access), []byte(hexSHA([]byte(token)))) != 1 {
		problem(w, 404, "evidence_not_found")
		return "", receipt, false
	}
	data, err := s.readAdvisoryJSON(r, key, sha)
	if err != nil || len(data) > 8<<20 || json.Unmarshal(data, &receipt) != nil || trips.Hash(receipt) != hexSHA(data) {
		problem(w, 503, "trip_evidence_unavailable")
		return "", receipt, false
	}
	var frozen, lake any
	var v trips.Verdict
	if json.Unmarshal(mirror, &frozen) != nil || json.Unmarshal(data, &lake) != nil || !reflect.DeepEqual(frozen, lake) || json.Unmarshal(verdict, &v) != nil || trips.Hash(v) != trips.Hash(receipt.Output) {
		problem(w, 503, "trip_projection_mismatch")
		return "", receipt, false
	}

	return id, receipt, true
}
func (s *Server) tripEvidence(w http.ResponseWriter, r *http.Request) {
	if _, ok := query(w, r); !ok {
		return
	}
	id, receipt, ok := s.privateTrip(w, r)
	if !ok {
		return
	}
	advisoryJSON(w, map[string]any{"calculation_id": id, "manifest_sha256": trips.Hash(receipt), "receipt": receipt, "freshness": "frozen_as_of; request a new calculation for current conditions"})
}
func (s *Server) replayTrip(w http.ResponseWriter, r *http.Request) {
	if _, ok := query(w, r); !ok {
		return
	}
	if r.ContentLength != 0 {
		problem(w, 400, "replay_has_no_body")
		return
	}
	id, receipt, ok := s.privateTrip(w, r)
	if !ok {
		return
	}
	if receipt.CodeSHA != tripCodeSHA() || receipt.Runtime != tripRuntime() {
		problem(w, 409, "replay_requires_pinned_release")
		return
	}
	frozenFields := map[string]json.RawMessage{}
	for _, raw := range receipt.FieldEvidence {
		var p tripFieldResponse
		if json.Unmarshal(raw, &p) != nil {
			problem(w, 503, "trip_field_replay_mismatch")
			return
		}
		frozenFields[p.Variable] = raw
	}
	for _, field := range receipt.Input.Fields {
		if field.Error != "" {
			continue
		}
		raw, ok := frozenFields[field.Variable]
		if !ok {
			problem(w, 503, "trip_field_replay_mismatch")
			return
		}
		normalized, err := normalizeTripField(raw, trips.Binding{Variable: field.Variable, ReleaseID: field.ReleaseID}, field.ManifestSHA)
		if err != nil || trips.Hash(normalized) != trips.Hash(field) {
			problem(w, 503, "trip_field_replay_mismatch")
			return
		}
	}

	state := advisories.Evaluate(receipt.AdvisorySnapshot, receipt.Input.Request.Waypoints[0].Time, receipt.Input.Request.Waypoints[len(receipt.Input.Request.Waypoints)-1].Time, receipt.AdvisoryHits)
	if trips.Hash(state) != trips.Hash(receipt.Input.Advisory) || trips.Hash(trips.Evaluate(receipt.Input)) != trips.Hash(receipt.Output) {
		problem(w, 503, "trip_replay_mismatch")
		return
	}
	advisoryJSON(w, map[string]any{"calculation_id": id, "replayed": true, "freshness_renewed": false, "verdict": receipt.Output})
}

// Keep imports and runtime checks explicit: JSON cannot carry NaN/Inf and stored samples are bounded.
