// Independent HTTP/privacy and disposable PostgreSQL incident-control verification.
package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"google.golang.org/grpc/metadata"
	"log/slog"
	"nautiq.local/api/internal/operations"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

func must(e error) {
	if e != nil {
		panic("operation verification failed; details suppressed")
	}
}
func check(ok bool, label string) {
	if !ok {
		panic("operation verification: " + label)
	}
}
func httpChecks() {
	var logs bytes.Buffer
	monitor := operations.NewMonitor(slog.New(slog.NewJSONHandler(&logs, nil)))
	mux := http.NewServeMux()
	mux.HandleFunc("GET /profiles/{id}", func(w http.ResponseWriter, r *http.Request) {
		md, _ := metadata.FromOutgoingContext(r.Context())
		check(len(md.Get("traceparent")) == 1, "outgoing trace context")
		w.Write([]byte("ok"))
	})
	mux.HandleFunc("GET /panic", func(w http.ResponseWriter, r *http.Request) { panic("private panic content") })
	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/profiles/private-id?proof=never-log-this", nil)
	req.Header.Set("Authorization", "Bearer never-log-this")
	monitor.Wrap(mux).ServeHTTP(rec, req)
	check(rec.Code == 200 && regexp.MustCompile(`^[a-f0-9]{32}$`).MatchString(rec.Header().Get("X-Request-ID")), "request correlation")
	rec = httptest.NewRecorder()
	monitor.Metrics(rec, req)
	check(!strings.Contains(rec.Body.String(), "private-id") && !strings.Contains(rec.Body.String(), "never-log-this") && strings.Contains(rec.Body.String(), "/profiles/{id}"), "bounded metric labels")
	monitor.Wrap(mux).ServeHTTP(httptest.NewRecorder(), httptest.NewRequest("GET", "/panic", nil))
	check(!strings.Contains(logs.String(), "private panic") && !strings.Contains(logs.String(), "never-log-this"), "sanitized logs")
}
func main() {
	httpChecks()
	if len(os.Args) > 1 && os.Args[1] == "--offline" {
		fmt.Println("HTTP observability passed: route labels, request correlation, propagated trace context and private-data exclusion.")
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()
	root, e := pgxpool.New(ctx, os.Getenv("DATABASE_URL"))
	must(e)
	defer root.Close()
	name := "verify14_" + strings.ReplaceAll(uuid.NewString(), "-", "")
	_, e = root.Exec(ctx, "CREATE DATABASE "+pgx.Identifier{name}.Sanitize())
	must(e)
	defer root.Exec(context.Background(), "DROP DATABASE "+pgx.Identifier{name}.Sanitize()+" WITH (FORCE)")
	config, e := pgxpool.ParseConfig(os.Getenv("DATABASE_URL"))
	must(e)
	config.ConnConfig.Database = name
	db, e := pgxpool.NewWithConfig(ctx, config)
	must(e)
	defer db.Close()
	files, e := filepath.Glob("/migrations/*.sql")
	must(e)
	check(len(files) == 19, "migration chain")
	_, e = db.Exec(ctx, "CREATE TABLE platform_migrations(version integer PRIMARY KEY,sha256 text NOT NULL,applied_at timestamptz DEFAULT now())")
	must(e)
	for i, file := range files {
		raw, e := os.ReadFile(file)
		must(e)
		_, e = db.Exec(ctx, string(raw))
		must(e)
		h := sha256.Sum256(raw)
		_, e = db.Exec(ctx, "INSERT INTO platform_migrations(version,sha256) VALUES($1,$2)", i+1, hex.EncodeToString(h[:]))
		must(e)
	}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /api/v1/fields/sample", func(w http.ResponseWriter, r *http.Request) { w.Write([]byte("available")) })
	for _, pattern := range []string{"POST /api/v1/trips", "GET /api/v1/map/overview", "POST /api/v1/research"} {
		mux.HandleFunc(pattern, func(w http.ResponseWriter, r *http.Request) { w.Write([]byte("available")) })
	}
	handler := operations.Guard(db, mux)
	request := func() int {
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, httptest.NewRequest("GET", "/api/v1/fields/sample", nil))
		return rec.Code
	}
	check(request() == 200, "unpaused serving")
	_, e = db.Exec(ctx, `UPDATE operations_controls SET paused='{"field_sampling":true}',revision=revision+1`)
	must(e)
	check(request() == 503, "field pause")
	for _, input := range [][2]string{{"POST", "/api/v1/trips"}, {"GET", "/api/v1/map/overview"}, {"POST", "/api/v1/research"}} {
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, httptest.NewRequest(input[0], input[1], nil))
		check(rec.Code == 503, "dependent public serving withheld")
	}
	rec := httptest.NewRecorder()
	operations.Capabilities(db, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"capabilities":{"field_sampling":true,"observations":true,"profile_anomaly":false}}`))
	})).ServeHTTP(rec, httptest.NewRequest("GET", "/api/v1/capabilities", nil))
	var body map[string]any
	must(json.Unmarshal(rec.Body.Bytes(), &body))
	check(body["capabilities"].(map[string]any)["field_sampling"] == false, "capability flag reflects pause")
	_, e = db.Exec(ctx, `UPDATE operations_controls SET paused='{"unsupported_scope":true}'`)
	must(e)
	check(request() == 503, "invalid controls fail closed")
	_, e = db.Exec(ctx, `UPDATE operations_controls SET paused='{"science":null}'`)
	must(e)
	check(request() == 503, "null pause fails closed")
	_, e = db.Exec(ctx, `UPDATE operations_controls SET paused='{}'`)
	must(e)
	_, e = db.Exec(ctx, `DELETE FROM operations_controls`)
	must(e)
	check(request() == 503, "missing control row fails closed")
	fmt.Println("Disposable operations verification passed: migrations, serving and capability pauses, and corrupt/missing control refusal.")
}
