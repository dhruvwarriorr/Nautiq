// Package operations exposes bounded incident controls without a public admin API.
package operations

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

var Scopes = []string{"science", "field_sampling", "model_inference", "events", "advisories", "trips", "notification_evaluation", "email_delivery", "product_writes"}

type State struct {
	Revision  int64           `json:"revision"`
	Paused    map[string]bool `json:"paused"`
	UpdatedAt time.Time       `json:"updated_at"`
}
type Queryer interface {
	QueryRow(context.Context, string, ...any) pgx.Row
}

func Read(ctx context.Context, q Queryer, lock bool) (State, error) {
	var state State
	var raw []byte
	sql := "SELECT revision,paused,updated_at FROM operations_controls WHERE singleton"
	if lock {
		sql += " FOR SHARE"
	}
	err := q.QueryRow(ctx, sql).Scan(&state.Revision, &raw, &state.UpdatedAt)
	if err != nil {
		return state, err
	}
	var values map[string]json.RawMessage
	if json.Unmarshal(raw, &values) != nil || values == nil || state.Revision < 1 {
		return state, errors.New("control_integrity")
	}
	state.Paused = make(map[string]bool, len(values))
	for scope, value := range values {
		if !ValidScope(scope) || (string(value) != "true" && string(value) != "false") {
			return state, errors.New("control_integrity")
		}
		state.Paused[scope] = string(value) == "true"
	}
	return state, nil
}
func ValidScope(scope string) bool {
	for _, s := range Scopes {
		if s == scope {
			return true
		}
	}
	return false
}
func (s State) Allows(scope string) bool {
	return !s.Paused[scope] && !(scope != "product_writes" && scope != "email_delivery" && s.Paused["science"])
}
func Allowed(ctx context.Context, q Queryer, scope string) (bool, error) {
	s, e := Read(ctx, q, false)
	return e == nil && s.Allows(scope), e
}
func Scope(r *http.Request) string {
	p := r.URL.Path
	if r.Method != "GET" && (strings.HasPrefix(p, "/api/v1/auth/") || p == "/api/v1/account" || strings.HasPrefix(p, "/api/v1/routes") || strings.HasPrefix(p, "/api/v1/watchlists") || strings.HasPrefix(p, "/api/v1/alert-rules") || strings.HasPrefix(p, "/api/v1/saved-trips") || strings.HasPrefix(p, "/api/v1/exports") || strings.HasPrefix(p, "/api/v1/reports") || strings.HasPrefix(p, "/api/v1/notification-email") || (strings.HasPrefix(p, "/api/v1/alerts/") && !strings.HasSuffix(p, "/replay"))) {
		return "product_writes"
	}
	if strings.HasPrefix(p, "/api/v1/fields") {
		return "field_sampling"
	}
	if strings.HasPrefix(p, "/api/v1/trips") || p == "/api/v1/trip-policy" {
		return "trips"
	}
	if strings.HasPrefix(p, "/api/v1/advisories") {
		return "advisories"
	}
	if strings.HasPrefix(p, "/api/v1/event") {
		return "events"
	}
	if strings.HasPrefix(p, "/api/v1/conditions") || strings.HasPrefix(p, "/api/v1/map") || p == "/api/v1/research" {
		return "science"
	}
	for _, suffix := range []string{"expected-state", "uncertainty", "anomaly", "climatology"} {
		if strings.HasSuffix(p, "/"+suffix) || strings.Contains(p, suffix+"-releases") {
			return "model_inference"
		}
	}
	return ""
}
func Guard(db *pgxpool.Pool, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		scope := Scope(r)
		if scope != "" {
			ctx, cancel := context.WithTimeout(r.Context(), time.Second)
			defer cancel()
			state, e := Read(ctx, db, false)
			ok := e == nil && state.Allows(scope)
			if ok && (scope == "science" || scope == "trips") {
				for _, dependency := range []string{"field_sampling", "advisories", "model_inference"} {
					ok = state.Allows(dependency)
					if !ok {
						break
					}
				}
				if strings.HasPrefix(r.URL.Path, "/api/v1/map") || r.URL.Path == "/api/v1/research" {
					ok = ok && state.Allows("events")
				}
			}
			if e != nil || !ok {
				w.Header().Set("Cache-Control", "no-store")
				w.Header().Set("Content-Type", "application/problem+json")
				w.Header().Set("Retry-After", "60")
				w.WriteHeader(503)
				json.NewEncoder(w).Encode(map[string]any{"code": "operation_paused_or_unavailable", "status": 503, "scope": scope})
				return
			}
		}
		next.ServeHTTP(w, r)
	})
}
