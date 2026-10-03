package operations

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"google.golang.org/grpc/metadata"
	"log/slog"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"
)

// Labels use registered route templates, never user paths, queries, proofs or IDs.
type measurement struct {
	Count   int64
	Seconds float64
}
type Monitor struct {
	mu     sync.Mutex
	rows   map[string]measurement
	slots  chan struct{}
	Logger *slog.Logger
}

func NewMonitor(logger *slog.Logger) *Monitor {
	return &Monitor{rows: map[string]measurement{}, slots: make(chan struct{}, 64), Logger: logger}
}

type recorder struct {
	http.ResponseWriter
	status int
}

func (w *recorder) WriteHeader(status int) {
	if w.status == 0 {
		w.status = status
		w.ResponseWriter.WriteHeader(status)
	}
}
func (w *recorder) Write(b []byte) (int, error) {
	if w.status == 0 {
		w.WriteHeader(200)
	}
	return w.ResponseWriter.Write(b)
}
func (w *recorder) Unwrap() http.ResponseWriter { return w.ResponseWriter }
func RequestID(r *http.Request) string          { return r.Header.Get("X-Nautiq-Request-ID") }
func (m *Monitor) Wrap(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		idBytes := make([]byte, 16)
		if _, e := rand.Read(idBytes); e != nil {
			http.Error(w, "unavailable", 503)
			return
		}
		id := hex.EncodeToString(idBytes)
		r.Header.Set("X-Nautiq-Request-ID", id)
		trace := "00-" + id + "-" + id[:16] + "-01"
		r = r.WithContext(metadata.NewOutgoingContext(r.Context(), metadata.Pairs("traceparent", trace)))
		w.Header().Set("traceparent", trace)
		w.Header().Set("X-Request-ID", id)
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("Referrer-Policy", "no-referrer")
		w.Header().Set("X-Frame-Options", "DENY")
		start := time.Now()
		out := &recorder{ResponseWriter: w}
		defer func() {
			if recover() != nil {
				if out.status == 0 {
					out.Header().Set("Content-Type", "application/problem+json")
					out.WriteHeader(500)
					json.NewEncoder(out).Encode(map[string]any{"code": "internal_error", "request_id": id})
				}
				m.Logger.Error("http_panic", "request_id", id)
			}
			route := r.Pattern
			if route == "" {
				route = "unmatched"
			}
			status := out.status
			if status == 0 {
				status = 200
			}
			seconds := time.Since(start).Seconds()
			key := route + "\x00" + strconv.Itoa(status)
			m.mu.Lock()
			v := m.rows[key]
			v.Count++
			v.Seconds += seconds
			m.rows[key] = v
			m.mu.Unlock()
			m.Logger.Info("http_request", "request_id", id, "route", route, "status", status, "duration_ms", time.Since(start).Milliseconds())
		}()
		select {
		case m.slots <- struct{}{}:
			defer func() { <-m.slots }()
		default:
			out.Header().Set("Retry-After", "1")
			out.WriteHeader(503)
			return
		}
		next.ServeHTTP(out, r)
	})
}
func (m *Monitor) Metrics(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/plain; version=0.0.4")
	w.Header().Set("Cache-Control", "no-store")
	m.mu.Lock()
	defer m.mu.Unlock()
	fmt.Fprintln(w, "# TYPE nautiq_http_requests_total counter\n# TYPE nautiq_http_duration_seconds_total counter")
	for key, value := range m.rows {
		parts := strings.Split(key, "\x00")
		fmt.Fprintf(w, "nautiq_http_requests_total{route=%q,status=%q} %d\nnautiq_http_duration_seconds_total{route=%q,status=%q} %f\n", parts[0], parts[1], value.Count, parts[0], parts[1], value.Seconds)
	}
}
