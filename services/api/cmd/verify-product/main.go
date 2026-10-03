// Disposable database and real object-store contracts for private product surfaces.
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"
	"io"
	"nautiq.local/api/internal/product"
	"nautiq.local/api/internal/trips"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

func must(e error) {
	if e != nil {
		panic(e)
	}
}
func check(ok bool, label string) {
	if !ok {
		panic("product verification: " + label)
	}
}
func raw(v any) []byte { return product.JSON(v) }

type user struct {
	Token string `json:"session_token"`
	CSRF  string `json:"csrf_token"`
	ID    string
}
type client struct {
	server *httptest.Server
	u      user
}

func (c client) call(method, path string, body any, status int, key string, version int64) []byte {
	var data []byte
	if body != nil {
		data = raw(body)
	}
	r, e := http.NewRequest(method, c.server.URL+"/api/v1/"+path, bytes.NewReader(data))
	must(e)
	if body != nil {
		r.Header.Set("Content-Type", "application/json")
	}
	if c.u.Token != "" {
		r.Header.Set("Authorization", "Bearer "+c.u.Token)
		r.Header.Set("X-CSRF-Token", c.u.CSRF)
	}
	r.Header.Set("Origin", "http://localhost:3000")
	if method != "GET" {
		if key == "" {
			key = uuid.NewString()
		}
		r.Header.Set("Idempotency-Key", key)
	}
	if version > 0 {
		r.Header.Set("If-Match", fmt.Sprintf("\"%d\"", version))
	}
	response, e := c.server.Client().Do(r)
	must(e)
	defer response.Body.Close()
	b, e := io.ReadAll(response.Body)
	must(e)
	check(response.StatusCode == status, fmt.Sprintf("%s %s wanted %d got %d", method, path, status, response.StatusCode))
	return b
}
func (c client) object(method, path string, body any, status int, key string, version int64) product.Object {
	var o product.Object
	must(json.Unmarshal(c.call(method, path, body, status, key, version), &o))
	return o
}
func main() {
	var input product.ObjectInput
	check(product.Strict([]byte(`{"name":"a","name":"b","data":{}}`), &input) != nil, "duplicate JSON")
	check(product.Strict([]byte(`{"name":"a","owner_id":"spoof","data":{}}`), &input) != nil, "owner spoof")
	var missingDepth product.ResearchFilter
	check(product.Strict([]byte(`{"bbox":[45,0,77,25],"start":"2026-09-01T00:00:00Z","end":"2026-10-01T00:00:00Z","min_depth_m":0,"max_depth_m":null,"variable":"temperature_c","source":"argo_gdac","qc":"accepted","limit":10}`), &missingDepth) != nil, "unknown depth cannot become zero")
	check(product.ParseQuery("is fishing safe tomorrow near Goa?", "UTC").State == "clarification_required", "relative time clarification")
	check(product.ParseQuery("temperature profiles in Arabian Sea from 2026-09-01 to 2026-10-01", "UTC").State == "ready", "typed research grammar")
	now := time.Now().UTC()
	route := trips.Request{Activity: "fishing", ThresholdVersion: trips.DefaultPolicy().Version, Waypoints: []trips.Point{{Latitude: 12, Longitude: 72, Time: now.Add(time.Hour)}, {Latitude: 12.02, Longitude: 72.02, Time: now.Add(2 * time.Hour)}}, Fields: []trips.Binding{}, SpacingKM: 5, StepMinutes: 30, Preferences: map[string]trips.Preference{}}
	check(product.ValidateObject("routes", product.ObjectInput{Name: "valid", Data: raw(route)}) == nil, "valid timed route")
	malformed := map[string]any{}
	must(json.Unmarshal(raw(route), &malformed))
	points := malformed["waypoints"].([]any)
	delete(points[0].(map[string]any), "latitude")
	check(product.ValidateObject("routes", product.ObjectInput{Name: "missing", Data: raw(malformed)}) != nil, "missing coordinate cannot become zero")
	ctx := context.Background()
	admin, e := pgxpool.New(ctx, os.Getenv("DATABASE_URL"))
	must(e)
	defer admin.Close()
	name := "nautiq_product_test_" + strings.ReplaceAll(uuid.NewString(), "-", "")[:12]
	_, e = admin.Exec(ctx, "CREATE DATABASE "+name)
	must(e)
	dsn, e := url.Parse(os.Getenv("DATABASE_URL"))
	must(e)
	dsn.Path = "/" + name
	db, e := pgxpool.New(ctx, dsn.String())
	must(e)
	s3, e := minio.New(os.Getenv("MINIO_ENDPOINT"), &minio.Options{Creds: credentials.NewStaticV4(os.Getenv("MINIO_ROOT_USER"), os.Getenv("MINIO_ROOT_PASSWORD"), ""), Secure: false})
	must(e)
	prefix := "product/private/verification/" + name + "/"
	receiptKeys := []string{}
	defer func() {
		for _, key := range receiptKeys {
			_ = s3.RemoveObject(ctx, "nautiq", key, minio.RemoveObjectOptions{})
		}
		for obj := range s3.ListObjects(ctx, "nautiq", minio.ListObjectsOptions{Prefix: prefix, Recursive: true}) {
			if obj.Err == nil {
				_ = s3.RemoveObject(ctx, "nautiq", obj.Key, minio.RemoveObjectOptions{})
			}
		}
		db.Close()
		_, _ = admin.Exec(ctx, "DROP DATABASE "+name+" WITH (FORCE)")
	}()
	files, e := filepath.Glob("/migrations/*.sql")
	must(e)
	check(len(files) == 14, "complete migration chain")
	for _, f := range files {
		b, e := os.ReadFile(f)
		must(e)
		_, e = db.Exec(ctx, string(b))
		must(e)
	}
	api, e := product.New(db, s3, "http://localhost:3000")
	must(e)
	mux := http.NewServeMux()
	api.Register(mux)
	server := httptest.NewServer(mux)
	defer server.Close()
	anonymous := client{server: server}
	anonymous.call("GET", "routes", nil, 401, "", 0)
	password := "verification-password-2026"
	signup := func(handle string) client {
		var u user
		must(json.Unmarshal(anonymous.call("POST", "auth/register", map[string]string{"handle": handle, "password": password}, 200, "", 0), &u))
		c := client{server, u}
		var identity product.Identity
		must(json.Unmarshal(c.call("GET", "auth/session", nil, 200, "", 0), &identity))
		c.u.ID = identity.ID
		return c
	}
	a, b := signup("verifier_a"), signup("verifier_b")
	var count int
	must(db.QueryRow(ctx, `SELECT count(*) FROM product_sessions WHERE token_sha256=$1`, a.u.Token).Scan(&count))
	check(count == 0, "only session hashes persisted")
	noCSRF := a
	noCSRF.u.CSRF = ""
	noCSRF.call("POST", "routes", product.ObjectInput{Name: "route", Data: raw(route)}, 403, "", 0)
	key := uuid.NewString()
	body := product.ObjectInput{Name: "owned route", Data: raw(route)}
	one := a.object("POST", "routes", body, 201, key, 0)
	two := a.object("POST", "routes", body, 201, key, 0)
	check(one.ID == two.ID, "idempotent retry same resource")
	body.Name = "different"
	a.call("POST", "routes", body, 409, key, 0)
	body.Name = "owned route"
	b.call("GET", "routes/"+one.ID, nil, 404, "", 0)
	b.call("PUT", "routes/"+one.ID, body, 404, "", 1)
	b.call("DELETE", "routes/"+one.ID, nil, 404, "", 1)
	a.call("PUT", "routes/"+one.ID, body, 428, "", 0)
	updated := a.object("PUT", "routes/"+one.ID, body, 200, "", 1)
	check(updated.Version == 2, "optimistic edit increments")
	a.call("PUT", "routes/"+one.ID, body, 409, "", 1)
	concurrentKey := uuid.NewString()
	var wg sync.WaitGroup
	ids := make(chan string, 4)
	for i := 0; i < 4; i++ {
		wg.Add(1)
		go func() { defer wg.Done(); ids <- a.object("POST", "routes", body, 201, concurrentKey, 0).ID }()
	}
	wg.Wait()
	close(ids)
	same := ""
	for id := range ids {
		if same == "" {
			same = id
		}
		check(id == same, "concurrent retries deduplicate")
	}
	// A real immutable synthetic receipt exercises owner claims separately from scientific verdict tests.
	receiptID := uuid.NewString()
	proof := strings.Repeat("f", 64)
	verdict := map[string]any{"status": "insufficient_data", "as_of": now, "method_version": "private-fixture", "threshold_version": trips.DefaultPolicy().Version, "source_cycles": []any{}, "limitations": []string{"Synthetic ownership fixture"}, "wording": "Insufficient data"}
	receipt := raw(map[string]any{"input": map[string]any{"request": route}, "output": verdict})
	sha := product.Hash(receipt)
	receiptKey := "trips/private/" + sha + ".json"
	receiptKeys = append(receiptKeys, receiptKey)
	_, e = s3.PutObject(ctx, "nautiq", receiptKey, bytes.NewReader(receipt), int64(len(receipt)), minio.PutObjectOptions{})
	must(e)
	_, e = db.Exec(ctx, `INSERT INTO calculations(calculation_id,calculation_sha256,kind,method_version,manifest,manifest_key,manifest_sha256,state) VALUES($1,$2,'trip_assessment','private-fixture',$3,$4,$2,'frozen')`, receiptID, sha, receipt, receiptKey)
	must(e)
	_, e = db.Exec(ctx, `INSERT INTO trip_calculations(calculation_id,access_sha256,verdict) VALUES($1,$2,$3)`, receiptID, product.Hash([]byte(proof)), raw(verdict))
	must(e)
	claim := map[string]string{"name": "owned receipt", "calculation_id": receiptID, "access_token": proof}
	a.call("POST", "saved-trips", claim, 201, "", 0)
	b.call("POST", "saved-trips", claim, 404, "", 0)
	b.call("GET", "saved-trips/"+receiptID, nil, 404, "", 0)
	a.call("GET", "saved-trips/"+receiptID, nil, 200, "", 0)
	var receiptJob product.Job
	must(json.Unmarshal(a.call("POST", "reports", product.JobInput{Scope: "trip", TargetID: receiptID, Format: "json"}, 202, "", 0), &receiptJob))
	b.call("POST", "reports", product.JobInput{Scope: "trip", TargetID: receiptID, Format: "json"}, 404, "", 0)
	watch := a.object("POST", "watchlists", map[string]any{"name": "route watch", "data": map[string]any{"type": "route", "route_id": one.ID}}, 201, "", 0)
	a.call("DELETE", "routes/"+one.ID, nil, 409, "", 2)
	b.call("POST", "watchlists", map[string]any{"name": "foreign route", "data": map[string]any{"type": "route", "route_id": one.ID}}, 404, "", 0)
	a.call("POST", "watchlists", map[string]any{"name": "crossing polygon", "data": map[string]any{"type": "polygon", "polygon": [][]float64{{65, 10}, {66, 11}, {65, 11}, {66, 10}, {65, 10}}}}, 400, "", 0)
	rule := a.object("POST", "alert-rules", map[string]any{"name": "own rule", "data": map[string]any{"type": "official_advisory", "watchlist_id": watch.ID, "enabled": true, "channel": "in_app"}}, 201, "", 0)
	alertID := uuid.NewString()
	evidence := raw(map[string]any{"source_revision": "fixture", "state": "unknown"})
	_, e = db.Exec(ctx, `INSERT INTO product_alerts(alert_id,owner_id,rule_id,rule_version,event_revision,state,evidence,evidence_bytes,evidence_sha256) VALUES($1,$2,$3,1,'fixture','new',$4,$5,$6)`, alertID, a.u.ID, rule.ID, evidence, evidence, product.Hash(evidence))
	must(e)
	a.call("GET", "alerts", nil, 200, "", 0)
	b.call("POST", "alerts/"+alertID+"/acknowledge", nil, 404, "", 0)
	a.call("POST", "alerts/"+alertID+"/acknowledge", nil, 200, "", 0)
	_, e = db.Exec(ctx, `UPDATE product_alerts SET evidence='{}' WHERE alert_id=$1`, alertID)
	must(e)
	a.call("GET", "alerts", nil, 503, "", 0)
	var job product.Job
	must(json.Unmarshal(a.call("POST", "exports", product.JobInput{Scope: "route", TargetID: one.ID, Format: "csv"}, 202, "", 0), &job))
	check(job.State == "queued", "durable export queued")
	b.call("GET", "exports/"+job.ID, nil, 404, "", 0)
	a.call("POST", "exports/"+job.ID+"/cancel", nil, 409, "", 2)
	a.call("POST", "exports/"+job.ID+"/cancel", nil, 200, "", 1)
	a.call("POST", "exports/"+job.ID+"/download-grants", nil, 404, "", 0)
	must(json.Unmarshal(a.call("POST", "exports", product.JobInput{Scope: "route", TargetID: one.ID, Format: "netcdf"}, 202, "", 0), &job))
	check(job.State == "blocked", "inappropriate NetCDF fails closed")
	must(json.Unmarshal(a.call("POST", "reports", product.JobInput{Scope: "route", TargetID: one.ID, Format: "json"}, 202, "", 0), &job))
	artifact := []byte("{\"private\":true}\n")
	objectKey := prefix + uuid.NewString() + ".json"
	_, e = s3.PutObject(ctx, "nautiq", objectKey, bytes.NewReader(artifact), int64(len(artifact)), minio.PutObjectOptions{})
	must(e)
	_, e = db.Exec(ctx, `UPDATE product_jobs SET state='ready',object_key=$2,artifact_sha256=$3,artifact_bytes=$4 WHERE job_id=$1`, job.ID, objectKey, product.Hash(artifact), len(artifact))
	must(e)
	var grant struct {
		Path string `json:"path"`
	}
	must(json.Unmarshal(a.call("POST", "reports/"+job.ID+"/download-grants", nil, 201, "", 0), &grant))
	b.call("GET", strings.TrimPrefix(grant.Path, "/"), nil, 404, "", 0)
	download := a.call("GET", strings.TrimPrefix(grant.Path, "/"), nil, 200, "", 0)
	check(bytes.Equal(download, artifact), "verified private artifact bytes")
	a.call("GET", strings.TrimPrefix(grant.Path, "/"), nil, 404, "", 0)
	must(json.Unmarshal(a.call("POST", "reports/"+job.ID+"/download-grants", nil, 201, "", 0), &grant))
	_, e = s3.PutObject(ctx, "nautiq", objectKey, bytes.NewReader([]byte("corrupt")), 7, minio.PutObjectOptions{})
	must(e)
	a.call("GET", strings.TrimPrefix(grant.Path, "/"), nil, 503, "", 0)
	a.call("PATCH", "account?owner=bad", map[string]bool{"notifications_enabled": false}, 400, "", 1)
	a.call("PATCH", "account", map[string]string{"old_password": password, "new_password": "verification-password-rotated"}, 200, "", 1)
	a.call("GET", "auth/session", nil, 401, "", 0)
	_, e = db.Exec(ctx, `UPDATE product_sessions SET last_seen_at=now()-interval '31 minutes' WHERE account_id=$1`, b.u.ID)
	must(e)
	b.call("GET", "routes", nil, 401, "", 0)
	var u user
	must(json.Unmarshal(anonymous.call("POST", "auth/login", map[string]string{"handle": "verifier_a", "password": "verification-password-rotated"}, 200, "", 0), &u))
	a.u = u
	a.call("DELETE", "account", map[string]string{"password": "verification-password-rotated"}, 200, "", 2)
	must(db.QueryRow(ctx, `SELECT count(*) FROM product_object_gc WHERE object_key=$1`, objectKey).Scan(&count))
	check(count == 1, "deletion schedules durable private cleanup")
	must(db.QueryRow(ctx, `SELECT count(*) FROM product_object_gc WHERE object_key=$1`, receiptKey).Scan(&count))
	check(count == 1, "claimed receipt cleanup queued")
	must(db.QueryRow(ctx, `SELECT count(*) FROM calculations WHERE calculation_id=$1`, receiptID).Scan(&count))
	check(count == 0, "deleted account removes private receipt metadata")
	a.call("GET", "auth/session", nil, 401, "", 0)
	fmt.Println("Product contracts passed: typed validation, isolated migrations, Argon2 sessions, CSRF, owner isolation, concurrent idempotency, optimistic edits, dependencies, alert integrity, job fencing, verified single-use downloads, expiry and account deletion.")
}
