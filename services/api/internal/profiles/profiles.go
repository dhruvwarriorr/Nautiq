package profiles

import (
	"context"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/minio/minio-go/v7"
)

type Server struct {
	DB      *pgxpool.Pool
	Storage *minio.Client
	secret  []byte
	slots   chan struct{}
}
type Summary struct {
	ID        string    `json:"id"`
	Revision  string    `json:"revision_sha256"`
	Platform  string    `json:"platform_id"`
	Observed  time.Time `json:"observed_at"`
	Received  time.Time `json:"received_at"`
	Latitude  float64   `json:"latitude"`
	Longitude float64   `json:"longitude"`
	Mode      string    `json:"data_mode"`
	QC        string    `json:"qc_version"`
	Source    string    `json:"source_id"`
}
type Provenance struct {
	CalculationID     *string         `json:"calculation_id"`
	RawSHA            string          `json:"raw_sha256"`
	SourceURL         string          `json:"source_url"`
	DepthVersion      string          `json:"depth_conversion_version"`
	NormalizerVersion string          `json:"normalizer_version"`
	ParquetSHA        string          `json:"parquet_sha256"`
	ParquetKey        string          `json:"parquet_key"`
	SourceUpdated     time.Time       `json:"source_updated_at"`
	Attribution       string          `json:"attribution"`
	Cycle             int             `json:"cycle_number"`
	Direction         string          `json:"direction"`
	Sampling          string          `json:"sampling_scheme"`
	ParameterModes    json.RawMessage `json:"parameter_modes"`
}
type Profile struct {
	Summary
	Levels     json.RawMessage `json:"levels"`
	Provenance Provenance      `json:"provenance"`
}
type Page struct {
	Items    []Summary `json:"items"`
	Next     *string   `json:"next_cursor"`
	Snapshot time.Time `json:"snapshot_at"`
}
type cursor struct {
	Filter   string    `json:"filter"`
	Snapshot time.Time `json:"snapshot"`
	LastTime time.Time `json:"last_time"`
	LastID   string    `json:"last_id"`
	Expires  time.Time `json:"expires"`
	Schema   int       `json:"schema"`
}
type filters struct {
	West, South, East, North float64
	Start, End               time.Time
	Limit                    int
}

var digestPattern = regexp.MustCompile(`^[a-f0-9]{64}$`)

func New(db *pgxpool.Pool, storage *minio.Client) *Server {
	secret := make([]byte, 32)
	if _, err := rand.Read(secret); err != nil {
		panic("cursor entropy unavailable")
	}
	return &Server{DB: db, Storage: storage, secret: secret, slots: make(chan struct{}, 16)}
}
func (s *Server) Register(mux *http.ServeMux) {
	mux.Handle("GET /api/v1/profiles", s.bounded(s.list))
	mux.Handle("GET /api/v1/profiles/{id}", s.bounded(s.detail))
	mux.Handle("GET /api/v1/profiles/{id}/raw", s.bounded(s.raw))
}
func problem(w http.ResponseWriter, status int, code string) {
	w.Header().Set("Content-Type", "application/problem+json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(map[string]any{"type": "about:blank", "title": http.StatusText(status), "status": status, "code": code, "request_id": uuid.NewString()})
}
func (s *Server) bounded(next http.HandlerFunc) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if _, err := url.ParseQuery(r.URL.RawQuery); err != nil {
			problem(w, 400, "invalid_query")
			return
		}
		select {
		case s.slots <- struct{}{}:
			defer func() { <-s.slots }()
		default:
			w.Header().Set("Retry-After", "1")
			problem(w, 429, "query_capacity_exceeded")
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), 8*time.Second)
		defer cancel()
		next(w, r.WithContext(ctx))
	})
}
func known(q url.Values, names ...string) bool {
	allowed := map[string]bool{}
	for _, name := range names {
		allowed[name] = true
	}
	for name, values := range q {
		if !allowed[name] || len(values) != 1 {
			return false
		}
	}
	return true
}
func parseFilters(q url.Values) (filters, int, string) {
	f := filters{Limit: 50}
	if !known(q, "bbox", "start", "end", "limit", "cursor") {
		return f, 400, "unknown_or_repeated_parameter"
	}
	parts := strings.Split(q.Get("bbox"), ",")
	if len(parts) != 4 {
		return f, 400, "invalid_bbox"
	}
	values := []float64{}
	for _, p := range parts {
		v, e := strconv.ParseFloat(p, 64)
		if e != nil || math.IsNaN(v) || math.IsInf(v, 0) {
			return f, 400, "invalid_bbox"
		}
		values = append(values, v)
	}
	f.West, f.South, f.East, f.North = values[0], values[1], values[2], values[3]
	if f.West < -180 || f.East > 180 || f.South < -90 || f.North > 90 || f.West >= f.East || f.South >= f.North {
		return f, 400, "invalid_bbox"
	}
	var e error
	f.Start, e = time.Parse(time.RFC3339Nano, q.Get("start"))
	if e != nil {
		return f, 400, "invalid_start"
	}
	f.End, e = time.Parse(time.RFC3339Nano, q.Get("end"))
	if e != nil || !f.Start.Before(f.End) {
		return f, 400, "invalid_time_range"
	}
	f.Start = f.Start.UTC()
	f.End = f.End.UTC()
	if f.End.Sub(f.Start) > 366*24*time.Hour {
		return f, 422, "time_range_budget"
	}
	if q.Has("limit") {
		f.Limit, e = strconv.Atoi(q.Get("limit"))
		if e != nil || f.Limit < 1 || f.Limit > 200 {
			return f, 400, "invalid_limit"
		}
	}
	return f, 0, ""
}
func filterHash(f filters) string {
	b, _ := json.Marshal(f)
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:])
}
func (s *Server) encode(c cursor) string {
	b, _ := json.Marshal(c)
	mac := hmac.New(sha256.New, s.secret)
	mac.Write(b)
	return base64.RawURLEncoding.EncodeToString(b) + "." + base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
}
func (s *Server) decode(value string, f filters) (cursor, error) {
	var c cursor
	if len(value) > 2048 {
		return c, errors.New("invalid_cursor")
	}
	parts := strings.Split(value, ".")
	if len(parts) != 2 {
		return c, errors.New("invalid_cursor")
	}
	b, e := base64.RawURLEncoding.DecodeString(parts[0])
	if e != nil {
		return c, e
	}
	signature, e := base64.RawURLEncoding.DecodeString(parts[1])
	if e != nil {
		return c, e
	}
	mac := hmac.New(sha256.New, s.secret)
	mac.Write(b)
	if !hmac.Equal(signature, mac.Sum(nil)) {
		return c, errors.New("invalid_cursor")
	}
	if json.Unmarshal(b, &c) != nil || c.Filter != filterHash(f) || c.Schema != 3 || !c.Expires.After(time.Now()) || c.Snapshot.After(time.Now()) || c.Snapshot.IsZero() {
		return c, errors.New("expired_or_filter_mismatched_cursor")
	}
	if _, e := uuid.Parse(c.LastID); e != nil {
		return c, e
	}
	return c, nil
}

const summaryColumns = `p.profile_id::text,r.revision_sha256,p.platform_id,r.observed_at,r.received_at,r.latitude,r.longitude,r.data_mode,r.qc_version,a.source_id`

func scanSummary(row pgx.Row) (Summary, error) {
	var item Summary
	e := row.Scan(&item.ID, &item.Revision, &item.Platform, &item.Observed, &item.Received, &item.Latitude, &item.Longitude, &item.Mode, &item.QC, &item.Source)
	return item, e
}
func (s *Server) list(w http.ResponseWriter, r *http.Request) {
	f, status, code := parseFilters(r.URL.Query())
	if status != 0 {
		problem(w, status, code)
		return
	}
	c := cursor{Filter: filterHash(f), Snapshot: time.Now().UTC(), Expires: time.Now().Add(30 * time.Minute).UTC(), Schema: 3}
	if value := r.URL.Query().Get("cursor"); value != "" {
		var err error
		c, err = s.decode(value, f)
		if err != nil {
			problem(w, 400, "invalid_or_expired_cursor")
			return
		}
	}
	var after any
	if c.LastID != "" {
		after = c.LastID
	}
	tx, err := s.DB.Begin(r.Context())
	if err != nil {
		problem(w, 503, "observations_unavailable")
		return
	}
	defer tx.Rollback(r.Context())
	if _, err = tx.Exec(r.Context(), "SELECT pg_advisory_xact_lock_shared(78192402)"); err != nil {
		problem(w, 503, "observations_unavailable")
		return
	}
	if r.URL.Query().Get("cursor") == "" {
		if err = tx.QueryRow(r.Context(), "SELECT clock_timestamp()").Scan(&c.Snapshot); err != nil {
			problem(w, 503, "observations_unavailable")
			return
		}
	}
	rows, err := tx.Query(r.Context(), `SELECT `+summaryColumns+` FROM profiles p JOIN profile_revisions r USING(profile_id) JOIN raw_artifacts a ON a.artifact_id=r.raw_artifact_id WHERE r.science_ready AND r.selected_at <= $1 AND (r.superseded_at IS NULL OR r.superseded_at>$1) AND r.observed_at >= $2 AND r.observed_at < $3 AND r.position && ST_MakeEnvelope($4,$5,$6,$7,4326) AND ($8::uuid IS NULL OR (r.observed_at,p.profile_id)>($9,$8::uuid)) ORDER BY r.observed_at,p.profile_id LIMIT $10`, c.Snapshot, f.Start, f.End, f.West, f.South, f.East, f.North, after, c.LastTime, f.Limit+1)
	if err != nil {
		problem(w, 503, "observations_unavailable")
		return
	}
	defer rows.Close()
	page := Page{Items: []Summary{}, Snapshot: c.Snapshot}
	for rows.Next() {
		item, err := scanSummary(rows)
		if err != nil {
			problem(w, 503, "observations_unavailable")
			return
		}
		page.Items = append(page.Items, item)
	}
	if rows.Err() != nil {
		problem(w, 503, "observations_unavailable")
		return
	}
	if len(page.Items) > f.Limit {
		page.Items = page.Items[:f.Limit]
		last := page.Items[len(page.Items)-1]
		c.LastTime = last.Observed
		c.LastID = last.ID
		token := s.encode(c)
		page.Next = &token
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	json.NewEncoder(w).Encode(page)
}
func (s *Server) detail(w http.ResponseWriter, r *http.Request) {
	if !known(r.URL.Query()) {
		problem(w, 400, "unknown_parameter")
		return
	}
	id, e := uuid.Parse(r.PathValue("id"))
	if e != nil {
		problem(w, 404, "profile_not_found")
		return
	}
	var p Profile
	err := s.DB.QueryRow(r.Context(), `SELECT `+summaryColumns+`,r.levels,a.sha256,a.source_url,r.depth_conversion_version,r.normalizer_version,r.parquet_sha256,r.parquet_key,r.source_updated_at,src.metadata->>'attribution',p.cycle_number,p.direction,p.sampling_scheme,r.parameter_modes,r.calculation_id::text FROM profiles p JOIN profile_revisions r USING(profile_id) JOIN raw_artifacts a ON a.artifact_id=r.raw_artifact_id JOIN sources src USING(source_id) WHERE p.profile_id=$1 AND r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL`, id.String()).Scan(&p.ID, &p.Revision, &p.Platform, &p.Observed, &p.Received, &p.Latitude, &p.Longitude, &p.Mode, &p.QC, &p.Source, &p.Levels, &p.Provenance.RawSHA, &p.Provenance.SourceURL, &p.Provenance.DepthVersion, &p.Provenance.NormalizerVersion, &p.Provenance.ParquetSHA, &p.Provenance.ParquetKey, &p.Provenance.SourceUpdated, &p.Provenance.Attribution, &p.Provenance.Cycle, &p.Provenance.Direction, &p.Provenance.Sampling, &p.Provenance.ParameterModes, &p.Provenance.CalculationID)
	if errors.Is(err, pgx.ErrNoRows) {
		problem(w, 404, "profile_not_found")
		return
	}
	if err != nil {
		problem(w, 503, "observations_unavailable")
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	json.NewEncoder(w).Encode(p)
}
func (s *Server) raw(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	if !known(q, "revision_sha256") || !digestPattern.MatchString(q.Get("revision_sha256")) {
		problem(w, 400, "revision_required")
		return
	}
	id, e := uuid.Parse(r.PathValue("id"))
	if e != nil {
		problem(w, 404, "profile_not_found")
		return
	}
	var key, digest, path string
	var size int64
	err := s.DB.QueryRow(r.Context(), `SELECT a.object_key,a.sha256,a.source_path,a.size_bytes FROM profile_revisions r JOIN raw_artifacts a ON a.artifact_id=r.raw_artifact_id WHERE r.profile_id=$1 AND r.revision_sha256=$2`, id.String(), q.Get("revision_sha256")).Scan(&key, &digest, &path, &size)
	if errors.Is(err, pgx.ErrNoRows) {
		problem(w, 404, "profile_revision_not_found")
		return
	}
	if err != nil {
		problem(w, 503, "observations_unavailable")
		return
	}
	obj, err := s.Storage.GetObject(r.Context(), "nautiuq", key, minio.GetObjectOptions{})
	if err != nil {
		problem(w, 503, "raw_artifact_unavailable")
		return
	}
	defer obj.Close()
	// Verify exact immutable bytes before sending headers; no corrupt partial artifact publication.
	data, err := io.ReadAll(io.LimitReader(obj, 67108865))
	h := sha256.Sum256(data)
	if err != nil || int64(len(data)) != size || hex.EncodeToString(h[:]) != digest {
		problem(w, 503, "raw_artifact_integrity_failed")
		return
	}
	filename := path[strings.LastIndex(path, "/")+1:]
	w.Header().Set("Content-Type", "application/x-netcdf")
	w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="%s"`, filename))
	w.Header().Set("X-Raw-SHA256", digest)
	w.Header().Set("ETag", `"`+digest+`"`)
	w.Header().Set("Content-Length", strconv.Itoa(len(data)))
	w.Header().Set("Cache-Control", "private, max-age=3600")
	w.Write(data)
}
