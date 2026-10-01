package platform

import (
	"context"
	"encoding/json"
	"errors"
	"net/http/httptest"
	"sync"
	"testing"
)

func TestHealthReportsFailuresWithoutLeakingDetails(t *testing.T) {
	for _, fail := range []bool{false, true} {
		t.Run(map[bool]string{false: "healthy", true: "degraded"}[fail], func(t *testing.T) {
			checks := map[string]Check{"dependency": func(ctx context.Context) error {
				if fail {
					return errors.New("password=secret")
				}
				return nil
			}}
			recorder := httptest.NewRecorder()
			Handler(checks).ServeHTTP(recorder, httptest.NewRequest("GET", "/api/v1/health", nil))
			expected := 200
			if fail {
				expected = 503
			}
			if recorder.Code != expected {
				t.Fatalf("status = %d", recorder.Code)
			}
			var report Report
			if err := json.Unmarshal(recorder.Body.Bytes(), &report); err != nil {
				t.Fatal(err)
			}
			if fail && report.Dependencies["dependency"].Detail != "Dependency check failed; inspect local service logs." {
				t.Fatal("error detail leaked")
			}
			if report.CheckedAt.IsZero() {
				t.Fatal("missing check time")
			}
		})
	}
}

func TestHealthChecksReceiveDeadline(t *testing.T) {
	Handler(map[string]Check{"deadline": func(ctx context.Context) error {
		if _, ok := ctx.Deadline(); !ok {
			t.Error("missing deadline")
		}
		return nil
	}}).ServeHTTP(httptest.NewRecorder(), httptest.NewRequest("GET", "/", nil))
}

func TestOptionalFailureDoesNotRemoveReadiness(t *testing.T) {
	checks := map[string]Check{}
	for _, name := range []string{"postgresql", "postgis", "timescaledb", "schema"} {
		checks[name] = func(context.Context) error { return nil }
	}
	checks["redis"] = func(context.Context) error { return errors.New("offline") }
	r := httptest.NewRecorder()
	Readiness(checks).ServeHTTP(r, httptest.NewRequest("GET", "/health/ready", nil))
	if r.Code != 200 {
		t.Fatal("optional dependency removed readiness")
	}
	checks["schema"] = func(context.Context) error { return errors.New("mismatch") }
	r = httptest.NewRecorder()
	Readiness(checks).ServeHTTP(r, httptest.NewRequest("GET", "/health/ready", nil))
	if r.Code != 503 {
		t.Fatal("schema mismatch did not remove readiness")
	}
}

func TestMissingRequiredCheckFailsClosed(t *testing.T) {
	r := httptest.NewRecorder()
	Readiness(map[string]Check{}).ServeHTTP(r, httptest.NewRequest("GET", "/health/ready", nil))
	if r.Code != 503 {
		t.Fatal("missing required checks accepted")
	}
}

func TestDiagnosticConcurrencyIsBounded(t *testing.T) {
	started := make(chan struct{}, 8)
	release := make(chan struct{})
	handler := Handler(map[string]Check{"dependency": func(ctx context.Context) error {
		started <- struct{}{}
		select {
		case <-release:
			return nil
		case <-ctx.Done():
			return ctx.Err()
		}
	}})
	var wg sync.WaitGroup
	for range 8 {
		wg.Go(func() { handler.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest("GET", "/", nil)) })
	}
	for range 8 {
		<-started
	}
	r := httptest.NewRecorder()
	handler.ServeHTTP(r, httptest.NewRequest("GET", "/", nil))
	close(release)
	wg.Wait()
	if r.Code != 503 || r.Header().Get("Retry-After") != "1" {
		t.Fatal("diagnostic limit not enforced")
	}
}
