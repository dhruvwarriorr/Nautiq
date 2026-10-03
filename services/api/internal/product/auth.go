package product

import (
	"context"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/minio/minio-go/v7"
	"golang.org/x/crypto/argon2"
	"io"
	"net"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"
)

type Server struct {
	DB        *pgxpool.Pool
	Storage   *minio.Client
	Origin    string
	slots     chan struct{}
	hashSlots chan struct{}
	cursorKey []byte
}
type Identity struct {
	ID            string    `json:"account_id"`
	Handle        string    `json:"handle"`
	Notifications bool      `json:"notifications_enabled"`
	Version       int64     `json:"version"`
	CSRF          string    `json:"csrf_token"`
	Expires       time.Time `json:"expires_at"`
	token         string
}

var handlePattern = regexp.MustCompile(`^[a-z0-9_]{3,32}$`)
var tokenPattern = regexp.MustCompile(`^[a-f0-9]{64}$`)

func New(db *pgxpool.Pool, storage *minio.Client, origin string) (*Server, error) {
	u, e := url.Parse(origin)
	if e != nil || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || u.Path != "" || u.Scheme != "https" && (u.Scheme != "http" || (u.Hostname() != "localhost" && u.Hostname() != "127.0.0.1" && u.Hostname() != "::1")) {
		return nil, errors.New("product_origin_requires_https_or_loopback")
	}
	key, e := entropy(32)
	if e != nil {
		return nil, e
	}
	return &Server{db, storage, origin, make(chan struct{}, 12), make(chan struct{}, 2), key}, nil
}
func (s *Server) Register(mux *http.ServeMux) {
	mux.Handle("POST /api/v1/research", s.bound(s.research))
	mux.Handle("POST /api/v1/query", s.bound(s.query))
	mux.Handle("GET /api/v1/product-policy", s.bound(func(w http.ResponseWriter, r *http.Request) {
		if len(r.URL.Query()) != 0 {
			fail(w, 400, "unknown_query")
			return
		}
		write(w, 200, map[string]any{"policy": json.RawMessage(PolicyJSON), "accounts_available": true, "notification_delivery_available": false, "as_of": time.Now().UTC()})
	}))
	mux.Handle("POST /api/v1/auth/register", s.bound(s.register))
	mux.Handle("POST /api/v1/auth/login", s.bound(s.login))
	mux.Handle("GET /api/v1/auth/session", s.private(false, s.session))
	mux.Handle("POST /api/v1/auth/logout", s.private(true, s.logout))
	mux.Handle("PATCH /api/v1/account", s.private(true, s.account))
	mux.Handle("DELETE /api/v1/account", s.private(true, s.deleteAccount))
	for _, kind := range []string{"routes", "watchlists", "alert-rules"} {
		mux.Handle("GET /api/v1/"+kind, s.private(false, s.objects))
		mux.Handle("POST /api/v1/"+kind, s.private(true, s.createObject))
		mux.Handle("GET /api/v1/"+kind+"/{id}", s.private(false, s.object))
		mux.Handle("PUT /api/v1/"+kind+"/{id}", s.private(true, s.updateObject))
		mux.Handle("DELETE /api/v1/"+kind+"/{id}", s.private(true, s.deleteObject))
	}
	mux.Handle("GET /api/v1/saved-trips", s.private(false, s.savedTrips))
	mux.Handle("POST /api/v1/saved-trips", s.private(true, s.saveTrip))
	mux.Handle("GET /api/v1/saved-trips/{id}", s.private(false, s.savedTrip))
	mux.Handle("DELETE /api/v1/saved-trips/{id}", s.private(true, s.forgetTrip))
	mux.Handle("GET /api/v1/alerts", s.private(false, s.alerts))
	mux.Handle("POST /api/v1/alerts/{id}/acknowledge", s.private(true, s.acknowledge))
	for _, kind := range []string{"reports", "exports"} {
		mux.Handle("GET /api/v1/"+kind, s.private(false, s.jobs))
		mux.Handle("POST /api/v1/"+kind, s.private(true, s.createJob))
		mux.Handle("GET /api/v1/"+kind+"/{id}", s.private(false, s.job))
		mux.Handle("POST /api/v1/"+kind+"/{id}/cancel", s.private(true, s.cancelJob))
		mux.Handle("POST /api/v1/"+kind+"/{id}/download-grants", s.private(true, s.grant))
		mux.Handle("GET /api/v1/"+kind+"/{id}/download", s.private(false, s.download))
	}
}
func fail(w http.ResponseWriter, status int, code string) {
	write(w, status, map[string]any{"type": "about:blank", "title": http.StatusText(status), "status": status, "code": code})
}
func write(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}
func (s *Server) bound(next http.HandlerFunc) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		q, e := url.ParseQuery(r.URL.RawQuery)
		if e != nil {
			fail(w, 400, "invalid_query")
			return
		}
		for _, v := range q {
			if len(v) != 1 {
				fail(w, 400, "repeated_query")
				return
			}
		}
		select {
		case s.slots <- struct{}{}:
			defer func() { <-s.slots }()
		default:
			fail(w, 429, "product_capacity")
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), 8*time.Second)
		defer cancel()
		next(w, r.WithContext(ctx))
	})
}
func body(w http.ResponseWriter, r *http.Request, v any) bool {
	if r.Header.Get("Content-Type") != "application/json" {
		fail(w, 415, "json_required")
		return false
	}
	data, e := io.ReadAll(http.MaxBytesReader(w, r.Body, 32768))
	if e != nil || Strict(data, v) != nil {
		fail(w, 400, "invalid_or_duplicate_json")
		return false
	}
	return true
}
func entropy(n int) ([]byte, error) { v := make([]byte, n); _, e := rand.Read(v); return v, e }
func csrf(token string) string {
	h := hmac.New(sha256.New, []byte(token))
	h.Write([]byte("nautiq:csrf:v1"))
	return hex.EncodeToString(h.Sum(nil))
}
func password(secret string, salt []byte) []byte {
	return argon2.IDKey([]byte(secret), salt, 3, 64*1024, 1, 32)
}
func validPassword(v string) bool {
	return len(v) >= 12 && len(v) <= 128 && !strings.ContainsRune(v, 0)
}
func (s *Server) rate(ctx context.Context, key string, limit int, window time.Duration) bool {
	var count int
	at := time.Now().UTC().Truncate(window)
	e := s.DB.QueryRow(ctx, `INSERT INTO product_rate_limits(key_sha256,window_start,attempts) VALUES($1,$2,1) ON CONFLICT(key_sha256,window_start) DO UPDATE SET attempts=product_rate_limits.attempts+1 RETURNING attempts`, Hash([]byte(key)), at).Scan(&count)
	return e == nil && count <= limit
}
func (s *Server) authGuard(w http.ResponseWriter, r *http.Request, handle string) bool {
	if len(r.URL.Query()) != 0 || r.Header.Get("Origin") != s.Origin {
		fail(w, 403, "origin_required")
		return false
	}
	ip, _, e := net.SplitHostPort(r.RemoteAddr)
	if e != nil {
		ip = r.RemoteAddr
	}
	if !s.rate(r.Context(), "auth:ip:"+ip, 30, 5*time.Minute) || !s.rate(r.Context(), "auth:handle:"+handle, 10, 5*time.Minute) {
		fail(w, 429, "auth_rate_limit")
		return false
	}
	select {
	case s.hashSlots <- struct{}{}:
		return true
	default:
		fail(w, 429, "password_hash_capacity")
		return false
	}
}

type credentials struct {
	Handle   string `json:"handle"`
	Password string `json:"password"`
}

func (s *Server) issue(w http.ResponseWriter, r *http.Request, id string) {
	raw, e := entropy(32)
	if e != nil {
		fail(w, 503, "session_unavailable")
		return
	}
	token := hex.EncodeToString(raw)
	expiry := time.Now().UTC().Add(24 * time.Hour)
	tx, e := s.DB.Begin(r.Context())
	if e != nil {
		fail(w, 503, "session_unavailable")
		return
	}
	defer tx.Rollback(r.Context())
	_, e = tx.Exec(r.Context(), `DELETE FROM product_sessions WHERE account_id=$1 AND (expires_at<now() OR last_seen_at<now()-interval '30 minutes')`, id)
	if e == nil {
		_, e = tx.Exec(r.Context(), `DELETE FROM product_sessions WHERE token_sha256 IN (SELECT token_sha256 FROM product_sessions WHERE account_id=$1 ORDER BY created_at DESC OFFSET 4)`, id)
	}
	if e == nil {
		_, e = tx.Exec(r.Context(), `INSERT INTO product_sessions(token_sha256,account_id,expires_at) VALUES($1,$2,$3)`, Hash([]byte(token)), id, expiry)
	}
	if e == nil {
		e = tx.Commit(r.Context())
	}
	if e != nil {
		fail(w, 503, "session_unavailable")
		return
	}
	write(w, 200, map[string]any{"session_token": token, "csrf_token": csrf(token), "expires_at": expiry})
}
func (s *Server) register(w http.ResponseWriter, r *http.Request) {
	var v credentials
	if !body(w, r, &v) {
		return
	}
	if !handlePattern.MatchString(v.Handle) || !validPassword(v.Password) {
		fail(w, 400, "handle_or_password_policy")
		return
	}
	if !s.authGuard(w, r, v.Handle) {
		return
	}
	defer func() { <-s.hashSlots }()
	salt, e := entropy(16)
	if e != nil {
		fail(w, 503, "account_unavailable")
		return
	}
	hash := password(v.Password, salt)
	id := uuid.NewString()
	tag, e := s.DB.Exec(r.Context(), `INSERT INTO product_accounts(account_id,handle,password_salt,password_hash) SELECT $1,$2,$3,$4 WHERE (SELECT count(*) FROM product_accounts)<10000 ON CONFLICT(handle) DO NOTHING`, id, v.Handle, salt, hash)
	if e != nil {
		fail(w, 503, "account_unavailable")
		return
	}
	if tag.RowsAffected() != 1 {
		fail(w, 409, "account_unavailable")
		return
	}
	s.issue(w, r, id)
}
func (s *Server) login(w http.ResponseWriter, r *http.Request) {
	var v credentials
	if !body(w, r, &v) {
		return
	}
	if !handlePattern.MatchString(v.Handle) || !validPassword(v.Password) {
		fail(w, 401, "invalid_credentials")
		return
	}
	if !s.authGuard(w, r, v.Handle) {
		return
	}
	defer func() { <-s.hashSlots }()
	var id string
	var salt, hash []byte
	e := s.DB.QueryRow(r.Context(), `SELECT account_id::text,password_salt,password_hash FROM product_accounts WHERE handle=$1`, v.Handle).Scan(&id, &salt, &hash)
	if e != nil {
		salt = make([]byte, 16)
		hash = make([]byte, 32)
	}
	candidate := password(v.Password, salt)
	if e != nil || subtle.ConstantTimeCompare(hash, candidate) != 1 {
		fail(w, 401, "invalid_credentials")
		return
	}
	s.issue(w, r, id)
}
func (s *Server) identity(r *http.Request) (Identity, error) {
	out := Identity{}
	h := r.Header.Get("Authorization")
	if !strings.HasPrefix(h, "Bearer ") || !tokenPattern.MatchString(strings.TrimPrefix(h, "Bearer ")) {
		return out, errors.New("session_required")
	}
	out.token = strings.TrimPrefix(h, "Bearer ")
	e := s.DB.QueryRow(r.Context(), `SELECT a.account_id::text,a.handle,a.notifications_enabled,a.version,s.expires_at FROM product_sessions s JOIN product_accounts a USING(account_id) WHERE s.token_sha256=$1 AND s.expires_at>now() AND s.last_seen_at>now()-interval '30 minutes'`, Hash([]byte(out.token))).Scan(&out.ID, &out.Handle, &out.Notifications, &out.Version, &out.Expires)
	if e != nil {
		return out, e
	}
	out.CSRF = csrf(out.token)
	_, e = s.DB.Exec(r.Context(), `UPDATE product_sessions SET last_seen_at=now() WHERE token_sha256=$1 AND last_seen_at<now()-interval '1 minute'`, Hash([]byte(out.token)))
	return out, e
}

type privateHandler func(http.ResponseWriter, *http.Request, Identity)

func (s *Server) private(mutation bool, next privateHandler) http.Handler {
	return s.bound(func(w http.ResponseWriter, r *http.Request) {
		u, e := s.identity(r)
		if e != nil {
			fail(w, 401, "session_expired_or_missing")
			return
		}
		if scope := r.Header.Get("X-Account-Scope"); scope != "" && scope != u.ID {
			fail(w, 401, "account_scope_changed")
			return
		}
		if mutation && (r.Header.Get("Origin") != s.Origin || !hmac.Equal([]byte(r.Header.Get("X-CSRF-Token")), []byte(u.CSRF))) {
			fail(w, 403, "csrf_required")
			return
		}
		if mutation && !s.rate(r.Context(), "writes:"+u.ID, 60, time.Minute) {
			fail(w, 429, "account_write_quota")
			return
		}
		next(w, r, u)
	})
}
func (s *Server) session(w http.ResponseWriter, r *http.Request, u Identity) {
	if len(r.URL.Query()) != 0 {
		fail(w, 400, "unknown_query")
		return
	}
	write(w, 200, u)
}
func (s *Server) logout(w http.ResponseWriter, r *http.Request, u Identity) {
	if len(r.URL.Query()) != 0 || r.ContentLength > 0 {
		fail(w, 400, "unexpected_body_or_query")
		return
	}
	if _, e := s.DB.Exec(r.Context(), `DELETE FROM product_sessions WHERE token_sha256=$1`, Hash([]byte(u.token))); e != nil {
		fail(w, 503, "logout_unavailable")
		return
	}
	write(w, 200, map[string]bool{"signed_out": true})
}
func match(w http.ResponseWriter, r *http.Request, version int64) bool {
	if r.Header.Get("If-Match") == "" {
		fail(w, 428, "version_required")
		return false
	}
	if r.Header.Get("If-Match") != strconv.Quote(strconv.FormatInt(version, 10)) {
		fail(w, 409, "version_conflict")
		return false
	}
	return true
}
func (s *Server) account(w http.ResponseWriter, r *http.Request, u Identity) {
	var v struct {
		Notifications *bool  `json:"notifications_enabled"`
		OldPassword   string `json:"old_password"`
		NewPassword   string `json:"new_password"`
	}
	if !noQuery(w, r) || !body(w, r, &v) {
		return
	}
	if !match(w, r, u.Version) {
		return
	}
	if v.Notifications == nil && v.NewPassword == "" {
		fail(w, 400, "account_change_required")
		return
	}
	if v.NewPassword != "" && !validPassword(v.NewPassword) {
		fail(w, 400, "password_policy")
		return
	}
	tx, e := s.DB.Begin(r.Context())
	if e != nil {
		fail(w, 503, "account_unavailable")
		return
	}
	defer tx.Rollback(r.Context())
	var salt, hash []byte
	var version int64
	e = tx.QueryRow(r.Context(), `SELECT password_salt,password_hash,version FROM product_accounts WHERE account_id=$1 FOR UPDATE`, u.ID).Scan(&salt, &hash, &version)
	if e != nil {
		fail(w, 503, "account_unavailable")
		return
	}
	if version != u.Version {
		fail(w, 409, "version_conflict")
		return
	}
	var active string
	if e = tx.QueryRow(r.Context(), `SELECT account_id::text FROM product_sessions WHERE token_sha256=$1 AND account_id=$2 AND expires_at>now() AND last_seen_at>now()-interval '30 minutes' FOR SHARE`, Hash([]byte(u.token)), u.ID).Scan(&active); e != nil {
		fail(w, 401, "session_expired")
		return
	}
	if v.NewPassword != "" {
		select {
		case s.hashSlots <- struct{}{}:
			defer func() { <-s.hashSlots }()
		default:
			fail(w, 429, "password_hash_capacity")
			return
		}
		if !validPassword(v.OldPassword) || subtle.ConstantTimeCompare(hash, password(v.OldPassword, salt)) != 1 {
			fail(w, 401, "invalid_credentials")
			return
		}
		salt, e = entropy(16)
		if e == nil {
			hash = password(v.NewPassword, salt)
		}
		if e == nil {
			_, e = tx.Exec(r.Context(), `DELETE FROM product_sessions WHERE account_id=$1`, u.ID)
		}
	}
	notify := u.Notifications
	if v.Notifications != nil {
		notify = *v.Notifications
	}
	if e == nil {
		_, e = tx.Exec(r.Context(), `UPDATE product_accounts SET password_salt=$2,password_hash=$3,notifications_enabled=$4,version=version+1 WHERE account_id=$1`, u.ID, salt, hash, notify)
	}
	if e == nil {
		e = tx.Commit(r.Context())
	}
	if e != nil {
		fail(w, 503, "account_unavailable")
		return
	}
	write(w, 200, map[string]any{"notifications_enabled": notify, "version": version + 1, "sign_in_again": v.NewPassword != ""})
}
func (s *Server) deleteAccount(w http.ResponseWriter, r *http.Request, u Identity) {
	var v struct {
		Password string `json:"password"`
	}
	if !noQuery(w, r) || !body(w, r, &v) || !match(w, r, u.Version) {
		return
	}
	select {
	case s.hashSlots <- struct{}{}:
		defer func() { <-s.hashSlots }()
	default:
		fail(w, 429, "password_hash_capacity")
		return
	}
	var salt, hash []byte
	e := s.DB.QueryRow(r.Context(), `SELECT password_salt,password_hash FROM product_accounts WHERE account_id=$1`, u.ID).Scan(&salt, &hash)
	if e != nil || !validPassword(v.Password) || subtle.ConstantTimeCompare(hash, password(v.Password, salt)) != 1 {
		fail(w, 401, "invalid_credentials")
		return
	}
	tx, e := s.DB.Begin(r.Context())
	if e != nil {
		fail(w, 503, "delete_unavailable")
		return
	}
	defer tx.Rollback(r.Context())
	var version int64
	if e = tx.QueryRow(r.Context(), `SELECT version FROM product_accounts WHERE account_id=$1 FOR UPDATE`, u.ID).Scan(&version); e != nil {
		fail(w, 401, "session_expired")
		return
	}
	if version != u.Version {
		fail(w, 409, "version_conflict")
		return
	}
	var active string
	if e = tx.QueryRow(r.Context(), `SELECT account_id::text FROM product_sessions WHERE token_sha256=$1 AND account_id=$2 AND expires_at>now() AND last_seen_at>now()-interval '30 minutes' FOR SHARE`, Hash([]byte(u.token)), u.ID).Scan(&active); e != nil {
		fail(w, 401, "session_expired")
		return
	}
	// Holding the account lock fences concurrent mutations; durable cleanup survives storage outages.
	_, e = tx.Exec(r.Context(), `INSERT INTO product_object_gc(object_key) SELECT object_key FROM product_jobs WHERE owner_id=$1 AND object_key IS NOT NULL ON CONFLICT DO NOTHING`, u.ID)
	if e == nil {
		_, e = tx.Exec(r.Context(), `INSERT INTO product_object_gc(object_key) SELECT 'trips/private/'||c.manifest_sha256||'.json' FROM product_trip_links l JOIN calculations c USING(calculation_id) WHERE l.owner_id=$1 ON CONFLICT DO NOTHING`, u.ID)
	}
	if e == nil {
		_, e = tx.Exec(r.Context(), `WITH owned AS (DELETE FROM product_trip_links WHERE owner_id=$1 RETURNING calculation_id), receipts AS (DELETE FROM trip_calculations t USING owned o WHERE t.calculation_id=o.calculation_id RETURNING t.calculation_id) DELETE FROM calculations c USING receipts r WHERE c.calculation_id=r.calculation_id`, u.ID)
	}
	// Remove ownership links first to satisfy the receipt foreign key.
	if e != nil {
		fail(w, 503, "delete_unavailable")
		return
	}
	tag, e := tx.Exec(r.Context(), `DELETE FROM product_accounts WHERE account_id=$1 AND version=$2`, u.ID, u.Version)
	if e != nil {
		fail(w, 503, "delete_unavailable")
		return
	}
	if tag.RowsAffected() != 1 {
		fail(w, 409, "version_conflict")
		return
	}
	if e = tx.Commit(r.Context()); e != nil {
		fail(w, 503, "delete_unavailable")
		return
	}
	write(w, 200, map[string]bool{"deleted": true})
}
func missing(e error) bool { return errors.Is(e, pgx.ErrNoRows) }
