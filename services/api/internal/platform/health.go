package platform

import (
	"context"
	"encoding/json"
	"net/http"
	"sync"
	"time"
)

type Check func(context.Context) error
type Result struct {
	Status string `json:"status"`
	Detail string `json:"detail,omitempty"`
}
type Report struct {
	Status       string            `json:"status"`
	CheckedAt    time.Time         `json:"checked_at"`
	Dependencies map[string]Result `json:"dependencies"`
}

// Readiness depends only on capabilities required by the current observation API.
// Diagnostics still show failures in optional runtimes without removing API traffic.
func Readiness(checks map[string]Check) http.Handler {
	required := make(map[string]Check)
	for _, name := range []string{"postgresql", "postgis", "timescaledb", "schema"} {
		if check, ok := checks[name]; ok {
			required[name] = check
		} else {
			required[name] = func(context.Context) error { return context.Canceled }
		}
	}
	return Handler(required)
}

func Capabilities(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	json.NewEncoder(w).Encode(map[string]any{
		"schema_version": 1,
		"capabilities": map[string]bool{"platform_runtime": true, "observations": false,
			"expected_state": false, "profile_anomaly": false, "field_sampling": false,
			"official_advisories": false, "trip_assessment": false},
		"limitations": []string{"Phase 0 is offline feasibility tooling; scientific serving is not enabled."},
	})
}

func Handler(checks map[string]Check) http.Handler {
	slots := make(chan struct{}, 8)
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		select {
		case slots <- struct{}{}:
			defer func() { <-slots }()
		default:
			results := make(map[string]Result)
			for name := range checks {
				results[name] = Result{Status: "unavailable", Detail: "Diagnostic capacity exhausted; retry shortly."}
			}
			w.Header().Set("Content-Type", "application/json")
			w.Header().Set("Cache-Control", "no-store")
			w.Header().Set("Retry-After", "1")
			w.WriteHeader(http.StatusServiceUnavailable)
			json.NewEncoder(w).Encode(Report{Status: "degraded", CheckedAt: time.Now().UTC(), Dependencies: results})
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
		defer cancel()
		report := Report{Status: "healthy", CheckedAt: time.Now().UTC(), Dependencies: make(map[string]Result)}
		var wg sync.WaitGroup
		var mu sync.Mutex
		for name, check := range checks {
			wg.Go(func() {
				result := Result{Status: "healthy"}
				if err := check(ctx); err != nil {
					result = Result{Status: "unavailable", Detail: "Dependency check failed; inspect local service logs."}
				}
				mu.Lock()
				defer mu.Unlock()
				report.Dependencies[name] = result
				if result.Status != "healthy" {
					report.Status = "degraded"
				}
			})
		}
		wg.Wait()
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Cache-Control", "no-store")
		if report.Status != "healthy" {
			w.WriteHeader(http.StatusServiceUnavailable)
		}
		json.NewEncoder(w).Encode(report)
	})
}
