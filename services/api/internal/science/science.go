// Package science serves durable audit evidence, not model or trip predictions.
package science

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/minio/minio-go/v7"
	pb "nautiq.local/api/gen/nautiq/platform/v1"
)

type Server struct {
	DB           *pgxpool.Pool
	Storage      *minio.Client
	Runtime      pb.PlatformServiceClient
	Fields       pb.FieldServiceClient
	FieldRuntime pb.PlatformServiceClient
	slots        chan struct{}
	downloads    chan struct{}
}

func New(db *pgxpool.Pool, storage *minio.Client) *Server {
	return &Server{DB: db, Storage: storage, slots: make(chan struct{}, 8), downloads: make(chan struct{}, 2)}
}
func (s *Server) Register(mux *http.ServeMux) {
	mux.Handle("GET /api/v1/fields", s.bound(s.fields))
	mux.Handle("GET /api/v1/fields/sample", s.bound(s.fieldSample))
	mux.Handle("POST /api/v1/fields/route", s.bound(s.fieldRoute))
	mux.Handle("POST /api/v1/fields/polygon", s.bound(s.fieldPolygon))
	mux.Handle("GET /api/v1/fields/{id}", s.bound(s.fieldDetail))
	mux.Handle("GET /api/v1/fields/{id}/tiles/{variable}/{z}/{x}/{y}", s.bound(s.fieldTile))
	mux.Handle("GET /api/v1/anomaly-releases", s.bound(s.anomalyReleases))
	mux.Handle("GET /api/v1/anomaly-releases/selected", s.bound(s.selectedAnomaly))
	mux.Handle("GET /api/v1/anomaly-releases/{id}", s.bound(s.anomalyRelease))
	mux.Handle("GET /api/v1/profiles/{id}/anomaly", s.bound(s.profileAnomaly))
	mux.Handle("GET /api/v1/uncertainty-releases", s.bound(s.uncertaintyReleases))
	mux.Handle("GET /api/v1/uncertainty-releases/selected", s.bound(s.selectedUncertainty))
	mux.Handle("GET /api/v1/uncertainty-releases/{id}", s.bound(s.uncertaintyRelease))
	mux.Handle("GET /api/v1/uncertainty-releases/{id}/coverage", s.bound(s.intervalCoverage))
	mux.Handle("GET /api/v1/profiles/{id}/uncertainty", s.bound(s.profileUncertainty))
	mux.Handle("GET /api/v1/expected-state-releases", s.bound(s.expectedReleases))
	mux.Handle("GET /api/v1/expected-state-releases/selected", s.bound(s.selectedExpected))
	mux.Handle("GET /api/v1/expected-state-releases/{id}", s.bound(s.expectedRelease))
	mux.Handle("GET /api/v1/profiles/{id}/expected-state", s.bound(s.profileExpected))
	mux.Handle("GET /api/v1/climatology-releases", s.bound(s.climatologyReleases))
	mux.Handle("GET /api/v1/climatology-releases/selected", s.bound(s.selectedClimatology))
	mux.Handle("GET /api/v1/climatology-releases/{id}", s.bound(s.climatologyRelease))
	mux.Handle("GET /api/v1/profiles/{id}/climatology", s.bound(s.profileClimatology))
	mux.Handle("GET /api/v1/capabilities", s.bound(s.capabilities))
	mux.Handle("GET /api/v1/sources", s.bound(s.sources))
	mux.Handle("GET /api/v1/qc-rejections", s.bound(s.rejections))
	mux.Handle("GET /api/v1/profiles/{id}/revisions", s.bound(s.revisions))
	mux.Handle("GET /api/v1/profiles/{id}/statistics", s.bound(s.statistics))
	mux.Handle("GET /api/v1/calculations/{id}", s.bound(s.calculation))
	mux.Handle("GET /api/v1/training-snapshots", s.bound(s.snapshots))
	mux.Handle("GET /api/v1/training-snapshots/{id}", s.bound(s.snapshot))
	mux.Handle("GET /api/v1/training-snapshots/{id}/parquet", s.bound(s.download))
}
func problem(w http.ResponseWriter, status int, code string) {
	w.Header().Set("Content-Type", "application/problem+json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(map[string]any{"type": "about:blank", "title": http.StatusText(status), "status": status, "code": code, "request_id": uuid.NewString()})
}
func (s *Server) bound(next http.HandlerFunc) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if len(r.URL.RawQuery) > 4096 {
			problem(w, 400, "query_budget")
			return
		}
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
func query(w http.ResponseWriter, r *http.Request, allowed ...string) (url.Values, bool) {
	q := r.URL.Query()
	names := map[string]bool{}
	for _, n := range allowed {
		names[n] = true
	}
	for k, v := range q {
		if !names[k] || len(v) != 1 {
			problem(w, 400, "unknown_or_repeated_parameter")
			return nil, false
		}
	}
	return q, true
}
func limit(q url.Values) (int, bool) {
	if !q.Has("limit") {
		return 50, true
	}
	n, e := strconv.Atoi(q.Get("limit"))
	return n, e == nil && n >= 1 && n <= 200
}
func identifier(w http.ResponseWriter, r *http.Request) (string, bool) {
	id, e := uuid.Parse(r.PathValue("id"))
	if e != nil {
		problem(w, 404, "evidence_not_found")
		return "", false
	}
	return id.String(), true
}
func (s *Server) serve(w http.ResponseWriter, r *http.Request, statement string, args ...any) {
	var data json.RawMessage
	err := s.DB.QueryRow(r.Context(), statement, args...).Scan(&data)
	if errors.Is(err, pgx.ErrNoRows) {
		problem(w, 404, "evidence_not_found")
		return
	}
	if err != nil {
		problem(w, 503, "evidence_unavailable")
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.Write(data)
}
func (s *Server) sources(w http.ResponseWriter, r *http.Request) {
	if _, ok := query(w, r); !ok {
		return
	}
	s.serve(w, r, `SELECT json_build_object('items',COALESCE(json_agg(t ORDER BY source_id),'[]')) FROM (
 SELECT s.source_id,s.metadata,h.checked_at AS monitor_checked_at,
 CASE WHEN h.checked_at IS NULL OR h.checked_at<now()-interval '3 minutes' THEN 'unavailable' ELSE 'current' END AS monitor_state,
 CASE WHEN h.checked_at IS NULL OR h.checked_at<now()-interval '3 minutes' THEN NULL ELSE h.report END AS health
 FROM sources s LEFT JOIN source_health h USING(source_id)) t`)
}

var sourcePattern = regexp.MustCompile(`^[a-z][a-z0-9_]{0,39}$`)

func (s *Server) rejections(w http.ResponseWriter, r *http.Request) {
	q, ok := query(w, r, "source_id", "artifact_id", "limit")
	if !ok {
		return
	}
	n, ok := limit(q)
	if !ok {
		problem(w, 400, "invalid_limit")
		return
	}
	var sid, aid any
	if q.Has("source_id") {
		if !sourcePattern.MatchString(q.Get("source_id")) {
			problem(w, 400, "invalid_source_id")
			return
		}
		sid = q.Get("source_id")
	}
	if q.Has("artifact_id") {
		id, e := uuid.Parse(q.Get("artifact_id"))
		if e != nil {
			problem(w, 400, "invalid_artifact_id")
			return
		}
		aid = id.String()
	}
	s.serve(w, r, `SELECT json_build_object('items',COALESCE(json_agg(t),'[]')) FROM (
 SELECT rejection_id,artifact_id,source_id,profile_index,variable,rule_id,reason_code,qc_version,normalizer_version,rejected_count,context,created_at
 FROM qc_rejections WHERE ($1::text IS NULL OR source_id=$1) AND ($2::uuid IS NULL OR artifact_id=$2) ORDER BY created_at DESC,rejection_id LIMIT $3) t`, sid, aid, n)
}
func (s *Server) revisions(w http.ResponseWriter, r *http.Request) {
	q, ok := query(w, r, "limit")
	if !ok {
		return
	}
	n, ok := limit(q)
	if !ok {
		problem(w, 400, "invalid_limit")
		return
	}
	id, ok := identifier(w, r)
	if !ok {
		return
	}
	s.serve(w, r, `SELECT json_build_object('profile_id',p.profile_id,'items',COALESCE((SELECT json_agg(t) FROM (
 SELECT r.revision_sha256,r.data_mode,r.source_updated_at,r.received_at,r.selected_at,r.superseded_at,r.science_ready,r.calculation_id,a.artifact_id,a.sha256 raw_sha256,a.source_url,
 CASE WHEN r.selected_at IS NOT NULL AND r.superseded_at IS NULL THEN 'current' WHEN r.superseded_at IS NOT NULL THEN 'superseded' ELSE 'unselected' END AS selection_state
 FROM profile_revisions r JOIN raw_artifacts a ON a.artifact_id=r.raw_artifact_id WHERE r.profile_id=p.profile_id ORDER BY r.source_updated_at DESC,r.revision_sha256 LIMIT $2) t),'[]')) FROM profiles p WHERE p.profile_id=$1`, id, n)
}
func (s *Server) statistics(w http.ResponseWriter, r *http.Request) {
	if _, ok := query(w, r); !ok {
		return
	}
	id, ok := identifier(w, r)
	if !ok {
		return
	}
	s.serve(w, r, `SELECT json_build_object('profile_id',p.profile_id,'revision_sha256',r.revision_sha256,'status',CASE WHEN ps.calculation_id IS NULL THEN 'pending' ELSE 'ready' END,'calculation_id',ps.calculation_id,'statistics',ps.statistics)
 FROM profiles p JOIN profile_revisions r USING(profile_id) LEFT JOIN profile_statistics ps ON ps.profile_id=p.profile_id AND ps.revision_sha256=r.revision_sha256
 WHERE p.profile_id=$1 AND r.science_ready AND r.selected_at IS NOT NULL AND r.superseded_at IS NULL`, id)
}
func (s *Server) calculation(w http.ResponseWriter, r *http.Request) {
	if _, ok := query(w, r); !ok {
		return
	}
	id, ok := identifier(w, r)
	if !ok {
		return
	}
	s.serve(w, r, `SELECT json_build_object('calculation_id',calculation_id,'kind',kind,'state',state,'created_at',created_at,'manifest_sha256',manifest_sha256,'superseded_by',superseded_by,'manifest',manifest) FROM calculations WHERE calculation_id=$1`, id)
}
func (s *Server) snapshots(w http.ResponseWriter, r *http.Request) {
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
 SELECT snapshot_id,snapshot_sha256,calculation_id,profile_count,row_count,created_at,parquet_sha256,manifest->'output'->>'status' AS status
 FROM training_snapshots ORDER BY created_at DESC,snapshot_id LIMIT $1) t`, n)
}
func (s *Server) snapshot(w http.ResponseWriter, r *http.Request) {
	if _, ok := query(w, r); !ok {
		return
	}
	id, ok := identifier(w, r)
	if !ok {
		return
	}
	s.serve(w, r, `SELECT json_build_object('snapshot_id',snapshot_id,'snapshot_sha256',snapshot_sha256,'calculation_id',calculation_id,'created_at',created_at,'manifest_sha256',manifest_sha256,'parquet_sha256',parquet_sha256,'profile_count',profile_count,'row_count',row_count,'manifest',manifest) FROM training_snapshots WHERE snapshot_id=$1`, id)
}
func (s *Server) download(w http.ResponseWriter, r *http.Request) {
	if _, ok := query(w, r); !ok {
		return
	}
	id, ok := identifier(w, r)
	if !ok {
		return
	}
	select {
	case s.downloads <- struct{}{}:
		defer func() { <-s.downloads }()
	default:
		w.Header().Set("Retry-After", "1")
		problem(w, 429, "download_capacity_exceeded")
		return
	}
	var key, digest string
	var size int64
	err := s.DB.QueryRow(r.Context(), "SELECT parquet_key,parquet_sha256,size_bytes FROM training_snapshots WHERE snapshot_id=$1", id).Scan(&key, &digest, &size)
	if errors.Is(err, pgx.ErrNoRows) {
		problem(w, 404, "evidence_not_found")
		return
	}
	if err != nil {
		problem(w, 503, "evidence_unavailable")
		return
	}
	obj, err := s.Storage.GetObject(r.Context(), "nautiq", key, minio.GetObjectOptions{})
	if err != nil {
		problem(w, 503, "snapshot_unavailable")
		return
	}
	defer obj.Close()
	data, err := io.ReadAll(io.LimitReader(obj, 134217729))
	sha := sha256.Sum256(data)
	if err != nil || int64(len(data)) != size || hex.EncodeToString(sha[:]) != digest {
		problem(w, 503, "snapshot_integrity_failed")
		return
	}
	w.Header().Set("Content-Type", "application/vnd.apache.parquet")
	w.Header().Set("Content-Length", strconv.Itoa(len(data)))
	w.Header().Set("Content-Disposition", `attachment; filename="`+id+`.parquet"`)
	w.Header().Set("X-Parquet-SHA256", digest)
	w.Header().Set("Cache-Control", "private, max-age=3600")
	w.Write(data)
}
