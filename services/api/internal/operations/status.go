package operations

import (
	"context"
	"encoding/json"
	"github.com/jackc/pgx/v5/pgxpool"
	"net/http"
	"net/http/httptest"
	"time"
)

func Status(db *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
		defer cancel()
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Cache-Control", "no-store")
		state, e := Read(ctx, db, false)
		if e != nil {
			w.WriteHeader(503)
			json.NewEncoder(w).Encode(map[string]any{"status": "unavailable"})
			return
		}
		var sources, queues []byte
		e = db.QueryRow(ctx, `SELECT json_build_object('fields',COALESCE((SELECT json_agg(json_build_object('product_id',p.product_id,'release_id',r.release_id,'status',COALESCE(r.status,'unavailable'),'cycle',r.cycle,'valid_time_end',r.valid_time_end,'fresh',COALESCE(COALESCE(r.cycle,r.valid_time_end)+make_interval(hours=>(r.manifest->'metadata'->>'max_age_hours')::integer)>=now(),false))) FROM field_products p LEFT JOIN field_selection s USING(product_id) LEFT JOIN field_releases r USING(release_id)),'[]'),'advisories',COALESCE((SELECT json_agg(json_build_object('source_id',source_id,'transport',transport,'checked_at',checked_at,'integrity',COALESCE((SELECT integrity FROM advisory_runs WHERE run_id=latest_run_id),'unavailable'))) FROM advisory_sources),'[]'))`).Scan(&sources)
		if e == nil {
			e = db.QueryRow(ctx, `SELECT json_build_object('notifications',EXISTS(SELECT 1 FROM notification_worker_health WHERE success_at>now()-interval '90 seconds' AND heartbeat_at>now()-interval '90 seconds'),'email_configured',COALESCE((SELECT smtp_configured FROM notification_worker_health ORDER BY heartbeat_at DESC LIMIT 1),false))`).Scan(&queues)
		}
		if e != nil {
			w.WriteHeader(503)
			json.NewEncoder(w).Encode(map[string]any{"status": "unavailable"})
			return
		}
		json.NewEncoder(w).Encode(map[string]any{"status": "available", "as_of": time.Now().UTC(), "controls": state, "sources": json.RawMessage(sources), "workers": json.RawMessage(queues), "production_approved": false, "scientific_approved": false})
	}
}
func Capabilities(db *pgxpool.Pool, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), time.Second)
		defer cancel()
		state, e := Read(ctx, db, false)
		if e != nil {
			http.Error(w, "controls_unavailable", 503)
			return
		}
		rec := httptest.NewRecorder()
		next.ServeHTTP(rec, r)
		var result map[string]any
		if rec.Code == 200 && json.Unmarshal(rec.Body.Bytes(), &result) == nil {
			if caps, ok := result["capabilities"].(map[string]any); ok {
				for key := range caps {
					scope := "model_inference"
					switch key {
					case "platform_runtime", "observations":
						continue
					case "field_sampling":
						scope = "field_sampling"
					case "regional_events", "event_detection_diagnostics":
						scope = "events"
					case "official_advisories", "advisory_diagnostics":
						scope = "advisories"
					case "trip_assessment", "trip_diagnostics":
						scope = "trips"
					}
					if !state.Allows(scope) {
						caps[key] = false
					}
				}
			}
			result["operations"] = state
			rec.Body.Reset()
			json.NewEncoder(rec.Body).Encode(result)
		}
		for k, v := range rec.Header() {
			w.Header()[k] = v
		}
		w.WriteHeader(rec.Code)
		w.Write(rec.Body.Bytes())
	})
}
