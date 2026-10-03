// Independent lifecycle tables and disposable SQL/HTTP/SMTP reliability checks.
package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"
	"google.golang.org/grpc"
	pb "nautiq.local/api/gen/nautiq/platform/v1"
	"nautiq.local/api/internal/advisories"
	"nautiq.local/api/internal/notifications"
	"nautiq.local/api/internal/product"
	"nautiq.local/api/internal/science"
	"nautiq.local/api/internal/trips"
)

func must(e error) {
	if e != nil {
		panic(e)
	}
}
func check(ok bool, label string) {
	if !ok {
		panic("notification verification: " + label)
	}
}
func data(v any) []byte { return notifications.JSON(v) }
func offline() {
	now := time.Now().UTC()
	pin := notifications.Hash([]byte("revision1"))
	obs := notifications.Evidence{Outcome: "triggered", Fingerprint: pin, Severity: 1, Fresh: true, AsOf: now, Warnings: []string{"warning1"}}
	first := notifications.Advance(notifications.State{}, obs, time.Hour)
	check(first.Notice == "new" && first.State.Active, "first alert")
	repeat := notifications.Advance(first.State, obs, time.Hour)
	check(repeat.Notice == "", "same revision dedup")
	obs.Fingerprint = notifications.Hash([]byte("revision2"))
	obs.AsOf = now.Add(time.Minute)
	cooldown := notifications.Advance(first.State, obs, time.Hour)
	check(cooldown.Pending && cooldown.Notice == "" && cooldown.State.Notified == pin, "cooldown retains pending update")
	obs.Severity = 3
	escalation := notifications.Advance(first.State, obs, time.Hour)
	check(escalation.Notice == "escalated", "severity bypasses cooldown")
	obs.Severity = 1
	obs.AsOf = now.Add(time.Hour)
	check(notifications.Advance(first.State, obs, time.Hour).Notice == "updated", "pending update becomes due")
	unknown := notifications.Evidence{Outcome: "unknown", AsOf: now.Add(time.Minute), Fingerprint: pin}
	check(notifications.Advance(first.State, unknown, time.Hour).State.Active, "unknown never recovers")
	clear := notifications.Evidence{Outcome: "clear", Fresh: true, AsOf: now.Add(time.Minute), Fingerprint: notifications.Hash([]byte("clear1"))}
	one := notifications.Advance(first.State, clear, time.Hour)
	check(one.State.ClearCount == 1 && one.Notice == "", "positive recovery confirmation")
	check(notifications.Advance(one.State, clear, time.Hour).State.ClearCount == 1, "duplicate confirmation refused")
	clear.Fingerprint = notifications.Hash([]byte("clear2"))
	clear.AsOf = now.Add(90 * time.Second)
	check(notifications.Advance(one.State, clear, time.Hour).State.ClearCount == 1, "recovery cadence")
	check(notifications.Advance(one.State, unknown, time.Hour).State.ClearCount == 0, "unknown interrupts recovery")
	clear.AsOf = now.Add(2 * time.Minute)
	two := notifications.Advance(one.State, clear, time.Hour)
	check(two.Notice == "recovered" && !two.State.Active, "two distinct fresh confirmations recover")
	clear.Fresh = false
	check(notifications.Advance(one.State, clear, time.Hour).Notice == "", "stale clear refused")
	obs.Fingerprint = pin
	obs.AsOf = now.Add(3 * time.Minute)
	recur := notifications.Advance(two.State, obs, time.Hour)
	check(recur.Notice == "new" && recur.Dedup != first.Dedup, "new episode can recur")
	unknown.Retired = []string{"warning1"}
	correction := notifications.Advance(first.State, unknown, time.Hour)
	check(correction.Notice == "corrected" && correction.State.Active, "retraction corrected without all-clear")
	check(notifications.Advance(correction.State, unknown, time.Hour).Notice == "", "correction dedup")
	unknown.Retired = append(unknown.Retired, "unrelated")
	unknown.Fingerprint = notifications.Hash([]byte("new unrelated source receipt"))
	check(notifications.Advance(correction.State, unknown, time.Hour).Notice == "", "unrelated retraction cannot duplicate correction")
	obs.AsOf = now.Add(time.Minute)
	obs.Fingerprint = notifications.Hash([]byte("replacement warning"))
	obs.Retired = []string{"warning1"}
	check(notifications.Advance(first.State, obs, time.Hour).Notice == "updated", "official replacement bypasses cooldown")
	unknown.Retired = []string{"unrelated"}
	check(notifications.Advance(first.State, unknown, time.Hour).Notice == "", "unrelated correction ignored")
	maximum := 2.0
	out, _ := notifications.Threshold(&maximum, 2, true)
	check(out == "triggered", "threshold equality")
	out, _ = notifications.Threshold(&maximum, 3, false)
	check(out == "unknown", "partial favorable value cannot recover")
	out, _ = notifications.Threshold(&maximum, 1, false)
	check(out == "triggered", "known exceedance dominates missing support")
	_, e := notifications.Address("recipient@example.test\r\nBcc:bad@example.test")
	check(e != nil, "mail header injection")
	_, e = notifications.Address("person+marine@example.test")
	check(e == nil, "email normalization")
	_, e = (&notifications.SMTP{Host: "smtp.example.test", Port: "25", Mode: "loopback", From: "sender@example.test"}).Validate()
	check(e != nil, "plaintext remote SMTP refused")
	check(product.ValidateObject("alert-rules", product.ObjectInput{Name: "invalid", Data: data(map[string]any{"watchlist_id": uuid.NewString(), "type": "field_threshold", "variable": "wave_height_m", "units": "m", "limit": 2, "enabled": true, "channel": "sms"})}) != nil, "unsupported channels refused")
	fmt.Println("Offline lifecycle verification passed: dedup, cooldown, escalation, recovery, corrections, equality, partial evidence and SMTP boundaries.")
}

type collector struct {
	listener       net.Listener
	mu             sync.Mutex
	messages       []string
	fail           int
	acceptThenDrop bool
}

func newCollector() *collector {
	l, e := net.Listen("tcp", "127.0.0.1:0")
	must(e)
	c := &collector{listener: l}
	go func() {
		for {
			conn, e := l.Accept()
			if e != nil {
				return
			}
			go c.serve(conn)
		}
	}()
	return c
}
func (c *collector) serve(conn net.Conn) {
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(10 * time.Second))
	reader := bufio.NewReader(conn)
	fmt.Fprint(conn, "220 local collector\r\n")
	for {
		line, e := reader.ReadString('\n')
		if e != nil {
			return
		}
		line = strings.TrimSpace(line)
		switch {
		case strings.HasPrefix(line, "EHLO"):
			fmt.Fprint(conn, "250-localhost\r\n250 SIZE 8192\r\n")
		case strings.HasPrefix(line, "MAIL FROM") || strings.HasPrefix(line, "RCPT TO"):
			fmt.Fprint(conn, "250 ok\r\n")
		case line == "DATA":
			c.mu.Lock()
			fail := c.fail > 0
			if fail {
				c.fail--
			}
			c.mu.Unlock()
			if fail {
				fmt.Fprint(conn, "451 transient fixture\r\n")
				continue
			}
			fmt.Fprint(conn, "354 send\r\n")
			var message strings.Builder
			for {
				v, e := reader.ReadString('\n')
				if e != nil {
					return
				}
				if v == ".\r\n" {
					break
				}
				message.WriteString(v)
			}
			c.mu.Lock()
			c.messages = append(c.messages, message.String())
			drop := c.acceptThenDrop
			c.mu.Unlock()
			fmt.Fprint(conn, "250 accepted\r\n")
			if drop {
				return
			}
		case line == "QUIT":
			fmt.Fprint(conn, "221 bye\r\n")
			return
		default:
			fmt.Fprint(conn, "250 ok\r\n")
		}
	}
}
func (c *collector) all() []string {
	c.mu.Lock()
	defer c.mu.Unlock()
	return append([]string{}, c.messages...)
}
func (c *collector) failure() { c.mu.Lock(); c.fail++; c.mu.Unlock() }

type client struct {
	server          *httptest.Server
	token, csrf, id string
}

func (c client) call(method, path string, body any, want int, key string) []byte {
	var raw []byte
	if body != nil {
		raw = data(body)
	}
	r, e := http.NewRequest(method, c.server.URL+"/api/v1/"+path, bytes.NewReader(raw))
	must(e)
	if body != nil {
		r.Header.Set("Content-Type", "application/json")
	}
	r.Header.Set("Origin", "http://localhost:3000")
	if c.token != "" {
		r.Header.Set("Authorization", "Bearer "+c.token)
		r.Header.Set("X-CSRF-Token", c.csrf)
	}
	if key == "" {
		key = uuid.NewString()
	}
	r.Header.Set("Idempotency-Key", key)
	response, e := c.server.Client().Do(r)
	must(e)
	defer response.Body.Close()
	b, e := io.ReadAll(response.Body)
	must(e)
	check(response.StatusCode == want, fmt.Sprintf("%s %s wanted %d got %d", method, path, want, response.StatusCode))
	return b
}
func register(server *httptest.Server, handle string) client {
	c := client{server: server}
	var auth struct {
		Token string `json:"session_token"`
		CSRF  string `json:"csrf_token"`
	}
	must(json.Unmarshal(c.call("POST", "auth/register", map[string]any{"handle": handle, "password": "Synthetic-fixture-password-13"}, 200, ""), &auth))
	c.token, c.csrf = auth.Token, auth.CSRF
	var session struct {
		ID string `json:"account_id"`
	}
	must(json.Unmarshal(c.call("GET", "auth/session", nil, 200, ""), &session))
	c.id = session.ID
	return c
}
func (c client) object(kind string, body any) product.Object {
	var out product.Object
	must(json.Unmarshal(c.call("POST", kind, body, 201, ""), &out))
	return out
}

type fields struct {
	pb.FieldServiceClient
	db      *pgxpool.Pool
	mu      sync.Mutex
	value   float64
	fresh   string
	serial  int
	partial bool
}

func (f *fields) evidence(id, variable string, result any) *pb.FieldEvidence {
	var sha string
	must(f.db.QueryRow(context.Background(), `SELECT manifest_sha256 FROM field_releases WHERE release_id=$1`, id).Scan(&sha))
	f.serial++
	raw := data(map[string]any{"release_id": id, "manifest_sha256": sha, "variable": variable, "release_approved": false, "freshness": f.fresh, "metadata": map[string]any{"variable_metadata": map[string]any{variable: map[string]any{"units": map[string]string{"wave_height_m": "m", "wind_speed_m_s": "m s-1", "current_speed_m_s": "m s-1"}[variable]}}}, "calculation": map[string]any{"fixture_sequence": f.serial, "output_sha256": notifications.Hash(data(result))}, "result": result})
	return &pb.FieldEvidence{ReleaseId: id, ManifestSha256: sha, ResultJson: raw}
}
func (f *fields) Sample(_ context.Context, r *pb.FieldSampleRequest, _ ...grpc.CallOption) (*pb.FieldEvidence, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	units := "m s-1"
	if r.Variable == "wave_height_m" {
		units = "m"
	}
	return f.evidence(r.ReleaseId, r.Variable, map[string]any{"status": f.fresh, "units": units, "value": f.value, "requested_time": r.Point.Time, "latitude": r.Point.Latitude, "longitude": r.Point.Longitude, "temporal_support": []any{}, "spatial_support": []any{}}), nil
}
func (f *fields) Polygon(_ context.Context, r *pb.FieldPolygonRequest, _ ...grpc.CallOption) (*pb.FieldEvidence, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.evidence(r.ReleaseId, r.Variable, map[string]any{"status": f.fresh, "maximum": f.value, "native_cells": 2, "available_cells": 2}), nil
}
func (f *fields) Route(_ context.Context, r *pb.FieldRouteRequest, _ ...grpc.CallOption) (*pb.FieldEvidence, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	status := "available"
	missing := "available"
	if f.partial {
		status = "partial"
		missing = "unavailable"
	}
	units := "m s-1"
	if r.Variable == "wave_height_m" {
		units = "m"
	}
	return f.evidence(r.ReleaseId, r.Variable, map[string]any{"status": status, "samples": []any{map[string]any{"status": "available", "value": f.value, "units": units}, map[string]any{"status": missing, "value": f.value, "units": units}}}), nil
}
func (f *fields) set(value float64, fresh string) {
	f.mu.Lock()
	f.value, f.fresh = value, fresh
	f.mu.Unlock()
}
func isolated() {
	ctx := context.Background()
	admin, e := pgxpool.New(ctx, os.Getenv("DATABASE_URL"))
	must(e)
	defer admin.Close()
	name := "nautiq_notifications_test_" + strings.ReplaceAll(uuid.NewString(), "-", "")[:12]
	_, e = admin.Exec(ctx, "CREATE DATABASE "+name)
	must(e)
	dsn, e := url.Parse(os.Getenv("DATABASE_URL"))
	must(e)
	dsn.Path = "/" + name
	db, e := pgxpool.New(ctx, dsn.String())
	must(e)
	s3, e := minio.New(os.Getenv("MINIO_ENDPOINT"), &minio.Options{Creds: credentials.NewStaticV4(os.Getenv("MINIO_ROOT_USER"), os.Getenv("MINIO_ROOT_PASSWORD"), ""), Secure: false})
	must(e)
	prefix := "notifications/verification/" + name + "/"
	defer func() {
		for o := range s3.ListObjects(ctx, "nautiq", minio.ListObjectsOptions{Prefix: prefix, Recursive: true}) {
			if o.Err == nil {
				_ = s3.RemoveObject(ctx, "nautiq", o.Key, minio.RemoveObjectOptions{})
			}
		}
		db.Close()
		_, _ = admin.Exec(ctx, "DROP DATABASE "+name+" WITH (FORCE)")
	}()
	files, e := filepath.Glob("/migrations/*.sql")
	must(e)
	check(len(files) == 16, "complete migration chain")
	for _, path := range files {
		b, e := os.ReadFile(path)
		must(e)
		_, e = db.Exec(ctx, string(b))
		must(e)
	}
	collector := newCollector()
	defer collector.listener.Close()
	_, port, e := net.SplitHostPort(collector.listener.Addr().String())
	must(e)
	smtp := &notifications.SMTP{Host: "127.0.0.1", Port: port, Mode: "loopback", From: "sender@example.test"}
	api, e := product.New(db, s3, "http://localhost:3000")
	must(e)
	api.Mailer = smtp
	mux := http.NewServeMux()
	api.Register(mux)
	server := httptest.NewServer(mux)
	defer server.Close()
	a, b := register(server, "fixture_owner"), register(server, "fixture_other")
	a.call("POST", "notification-email", map[string]any{"email": "recipient@example.test"}, 202, "")
	messages := collector.all()
	check(len(messages) == 1, "real local SMTP verification mail")
	proof := regexp.MustCompile(`[a-f0-9]{64}`).FindString(messages[0])
	check(proof != "", "verification proof in email only")
	b.call("POST", "notification-email/verify", map[string]any{"proof": proof}, 400, "")
	a.call("POST", "notification-email/verify", map[string]any{"proof": strings.Repeat("0", 64)}, 400, "")
	a.call("POST", "notification-email/verify", map[string]any{"proof": proof}, 200, "")
	a.call("POST", "notification-email/verify", map[string]any{"proof": proof}, 400, "")
	watch := a.object("watchlists", map[string]any{"name": "Point fixture", "data": map[string]any{"type": "point", "latitude": 12, "longitude": 72, "radius_km": 0}})
	rule := a.object("alert-rules", map[string]any{"name": "Personal fixture", "data": map[string]any{"watchlist_id": watch.ID, "type": "field_threshold", "variable": "wave_height_m", "units": "m", "limit": 2, "channel": "both", "enabled": true, "cooldown_minutes": 60}})
	b.call("GET", "alert-rules/"+rule.ID, nil, 404, "")
	for _, productID := range []string{"noaa_gfs_wave", "noaa_gfs_weather", "hycom_espc"} {
		id, calc := uuid.NewString(), uuid.NewString()
		sha := notifications.Hash([]byte(productID))
		_, e = db.Exec(ctx, `INSERT INTO calculations(calculation_id,calculation_sha256,kind,method_version,manifest,manifest_key,manifest_sha256,state) VALUES($1,$2,'field_normalization','synthetic-fixture','{}','fixture',$2,'frozen')`, calc, sha)
		must(e)
		_, e = db.Exec(ctx, `INSERT INTO field_releases(release_id,release_sha256,product_id,calculation_id,cycle,valid_time_start,valid_time_end,source_version,manifest_key,manifest_sha256,manifest) VALUES($1,$2,$3,$4,now(),now()-interval '1 hour',now()+interval '4 hours','forecast','fixture',$2,'{}')`, id, sha, productID, calc)
		must(e)
		_, e = db.Exec(ctx, `INSERT INTO field_selection(product_id,release_id) VALUES($1,$2)`, productID, id)
		must(e)
	}
	fake := &fields{db: db, value: 2, fresh: "available"}
	source := science.New(db, s3)
	source.Fields = fake
	worker := &notifications.Worker{DB: db, Provider: source, Mail: smtp, Origin: "http://localhost:3000", ID: uuid.NewString()}
	evaluate := func() string {
		_, e = db.Exec(ctx, `UPDATE notification_rule_state SET next_evaluation_at=now() WHERE rule_id=$1`, rule.ID)
		must(e)
		in, e := worker.Claim(ctx)
		must(e)
		check(in != nil, "due rule claim")
		out, e := source.NotificationEvidence(ctx, *in, time.Now().UTC())
		must(e)
		ok, e := worker.Publish(ctx, *in, out)
		must(e)
		check(ok, "atomic publish")
		return out.Outcome
	}
	check(evaluate() == "triggered", "native field threshold equality")
	var firstID, blob string
	must(db.QueryRow(ctx, `SELECT alert_id::text,evidence#>>'{observation,field_evidence_sha256,0}' FROM product_alerts WHERE rule_id=$1`, rule.ID).Scan(&firstID, &blob))
	a.call("POST", "alerts/"+firstID+"/replay", nil, 200, "")
	noCSRF := a
	noCSRF.csrf = ""
	noCSRF.call("POST", "alerts/"+firstID+"/replay", nil, 403, "")
	b.call("POST", "alerts/"+firstID+"/replay", nil, 404, "")
	a.call("GET", "notification-evidence/"+blob, nil, 200, "")
	b.call("GET", "notification-evidence/"+blob, nil, 404, "")
	collector.failure()
	ok, e := worker.DeliverOne(ctx)
	must(e)
	check(ok && len(collector.all()) == 1, "transient SMTP failure queued retry")
	_, e = db.Exec(ctx, `UPDATE notification_deliveries SET next_attempt_at=now() WHERE state='pending'`)
	must(e)
	ok, e = worker.DeliverOne(ctx)
	must(e)
	check(ok && len(collector.all()) == 2, "SMTP retry delivered")
	body := strings.SplitN(collector.all()[1], "\r\n\r\n", 2)
	check(len(body) == 2 && strings.HasPrefix(body[1], "A retained alert has a new lifecycle record.") && !strings.Contains(body[1], "wave_height_m") && !strings.Contains(body[1], "72"), "generic mail body omits source and coordinate content")
	var attempts int
	must(db.QueryRow(ctx, `SELECT attempts FROM notification_deliveries WHERE alert_id=$1 AND channel='email'`, firstID).Scan(&attempts))
	check(attempts == 2, "retry count")
	check(evaluate() == "triggered", "repeat evaluation")
	var count int
	must(db.QueryRow(ctx, `SELECT count(*) FROM product_alerts WHERE rule_id=$1`, rule.ID).Scan(&count))
	check(count == 1, "cooldown suppresses changed fresh receipt")
	fake.set(5, "available")
	evaluate()
	must(db.QueryRow(ctx, `SELECT count(*) FROM product_alerts WHERE rule_id=$1 AND state='escalated'`, rule.ID).Scan(&count))
	check(count == 1, "escalation publication")
	_, e = db.Exec(ctx, `UPDATE product_accounts SET notifications_enabled=false WHERE account_id=$1`, a.id)
	must(e)
	ok, e = worker.DeliverOne(ctx)
	must(e)
	check(ok && len(collector.all()) == 2, "opt-out rechecked before attempt")
	_, e = db.Exec(ctx, `UPDATE product_accounts SET notifications_enabled=true WHERE account_id=$1`, a.id)
	must(e)
	fake.set(0, "stale")
	check(evaluate() == "unknown", "stale favorable field cannot recover")
	fake.set(0, "available")
	check(evaluate() == "clear", "fresh below threshold")
	_, e = db.Exec(ctx, `UPDATE notification_rule_state SET state=jsonb_set(state,'{last_clear}',to_jsonb($2::text)) WHERE rule_id=$1`, rule.ID, time.Now().Add(-2*time.Minute).UTC().Format(time.RFC3339Nano))
	must(e)
	check(evaluate() == "clear", "second fresh confirmation")
	must(db.QueryRow(ctx, `SELECT count(*) FROM product_alerts WHERE rule_id=$1 AND state='recovered'`, rule.ID).Scan(&count))
	check(count == 1, "recovery record")
	ok, e = worker.DeliverOne(ctx)
	must(e)
	check(ok, "recovery email")
	// Expired claims and concurrent workers cannot publish twice or retain superseded input.
	_, e = db.Exec(ctx, `UPDATE notification_rule_state SET next_evaluation_at=now() WHERE rule_id=$1`, rule.ID)
	must(e)
	in, e := worker.Claim(ctx)
	must(e)
	check(in != nil, "lease claimed")
	other, e := worker.Claim(ctx)
	must(e)
	check(other == nil, "competing worker excluded")
	out, e := source.NotificationEvidence(ctx, *in, time.Now().UTC())
	must(e)
	_, e = db.Exec(ctx, `UPDATE product_objects SET version=version+1 WHERE object_id=$1`, watch.ID)
	must(e)
	ok, e = worker.Publish(ctx, *in, out)
	must(e)
	check(!ok, "watch version fences publication")
	in, e = worker.Claim(ctx)
	must(e)
	out, e = source.NotificationEvidence(ctx, *in, time.Now().UTC())
	must(e)
	_, e = db.Exec(ctx, `UPDATE notification_rule_state SET lease_expires_at=now()-interval '1 second' WHERE rule_id=$1`, rule.ID)
	must(e)
	ok, e = worker.Publish(ctx, *in, out)
	must(e)
	check(!ok, "expired lease refused")
	// A later worker recovers the abandoned claim; the old lease remains fenced.
	replacement, e := worker.Claim(ctx)
	must(e)
	check(replacement != nil && replacement.Lease != in.Lease, "abandoned evaluation recovered")
	ok, e = worker.Publish(ctx, *in, out)
	must(e)
	check(!ok, "abandoned owner fenced after replacement")
	out, e = source.NotificationEvidence(ctx, *replacement, time.Now().UTC())
	must(e)
	ok, e = worker.Publish(ctx, *replacement, out)
	must(e)
	check(ok, "replacement owner publishes")
	// Evidence corruption blocks reads, replay and mail; immutable originals can restore service.
	var original []byte
	must(db.QueryRow(ctx, `SELECT raw_bytes FROM notification_evidence_blobs WHERE owner_id=$1 AND sha256=$2`, a.id, blob).Scan(&original))
	_, e = db.Exec(ctx, `UPDATE notification_evidence_blobs SET raw_bytes='{}'::bytea WHERE owner_id=$1 AND sha256=$2`, a.id, blob)
	must(e)
	a.call("GET", "notification-evidence/"+blob, nil, 503, "")
	a.call("POST", "alerts/"+firstID+"/replay", nil, 503, "")
	_, e = db.Exec(ctx, `UPDATE notification_evidence_blobs SET raw_bytes=$3 WHERE owner_id=$1 AND sha256=$2`, a.id, blob, original)
	must(e)
	// Pin changes during collection withhold publication without inventing recovery.
	_, e = db.Exec(ctx, `UPDATE notification_rule_state SET next_evaluation_at=now() WHERE rule_id=$1`, rule.ID)
	must(e)
	in, e = worker.Claim(ctx)
	must(e)
	out, e = source.NotificationEvidence(ctx, *in, time.Now().UTC())
	must(e)
	_, e = db.Exec(ctx, `UPDATE field_releases SET status='unavailable' WHERE release_id=$1`, out.Pins[0].ID)
	must(e)
	ok, e = worker.Publish(ctx, *in, out)
	must(e)
	check(!ok, "source status change fences publication")
	_, e = db.Exec(ctx, `UPDATE field_releases SET status='ready' WHERE release_id=$1`, out.Pins[0].ID)
	must(e)
	// Recipient changes block queued delivery; retry requires a current verified opt-in.
	fake.set(5, "available")
	evaluate()
	var latest string
	must(db.QueryRow(ctx, `SELECT last_alert_id::text FROM notification_rule_state WHERE rule_id=$1`, rule.ID).Scan(&latest))
	beforeMail := len(collector.all())
	_, e = db.Exec(ctx, `UPDATE product_accounts SET notification_email='changed@example.test',email_version=email_version+1 WHERE account_id=$1`, a.id)
	must(e)
	ok, e = worker.DeliverOne(ctx)
	must(e)
	check(ok && len(collector.all()) == beforeMail, "recipient version checked on queued delivery")
	a.call("POST", "alerts/"+latest+"/retry-email", nil, 202, "")
	for i := 0; i < 5; i++ {
		collector.failure()
	}
	for i := 0; i < 5; i++ {
		_, e = db.Exec(ctx, `UPDATE notification_deliveries SET next_attempt_at=now() WHERE alert_id=$1 AND channel='email'`, latest)
		must(e)
		ok, e = worker.DeliverOne(ctx)
		must(e)
		check(ok, "bounded delivery attempt")
	}
	var deliveryState string
	must(db.QueryRow(ctx, `SELECT state,attempts FROM notification_deliveries WHERE alert_id=$1 AND channel='email'`, latest).Scan(&deliveryState, &attempts))
	check(deliveryState == "failed" && attempts == 5, "retry exhaustion is terminal")
	retryKey := uuid.NewString()
	a.call("POST", "alerts/"+latest+"/retry-email", nil, 202, retryKey)
	a.call("POST", "alerts/"+latest+"/retry-email", nil, 202, retryKey)
	ok, e = worker.DeliverOne(ctx)
	must(e)
	check(ok && len(collector.all()) == beforeMail+1, "explicit retry idempotence and delivery")
	a.call("POST", "alerts/"+latest+"/retry-email", nil, 409, "")
	// All publication rows roll back together when the delivery insert fails.
	_, e = db.Exec(ctx, `UPDATE product_objects SET version=version+1 WHERE object_id=$1`, rule.ID)
	must(e)
	_, e = db.Exec(ctx, `UPDATE notification_rule_state SET next_evaluation_at=now() WHERE rule_id=$1`, rule.ID)
	must(e)
	in, e = worker.Claim(ctx)
	must(e)
	out, e = source.NotificationEvidence(ctx, *in, time.Now().UTC())
	must(e)
	must(db.QueryRow(ctx, `SELECT count(*) FROM product_alerts`).Scan(&count))
	baseline := count
	_, e = db.Exec(ctx, `CREATE FUNCTION reject_notification_fixture() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic rollback'; END $$; CREATE TRIGGER reject_notification_fixture BEFORE INSERT ON notification_deliveries FOR EACH ROW EXECUTE FUNCTION reject_notification_fixture()`)
	must(e)
	_, e = worker.Publish(ctx, *in, out)
	check(e != nil, "forced delivery failure")
	must(db.QueryRow(ctx, `SELECT count(*) FROM product_alerts`).Scan(&count))
	check(count == baseline, "alert publication rolled back atomically")
	_, e = db.Exec(ctx, `DROP TRIGGER reject_notification_fixture ON notification_deliveries; DROP FUNCTION reject_notification_fixture()`)
	must(e)
	ok, e = worker.Publish(ctx, *in, out)
	must(e)
	check(ok, "same frozen claim recovers after rollback")
	must(db.QueryRow(ctx, `SELECT last_alert_id::text FROM notification_rule_state WHERE rule_id=$1`, rule.ID).Scan(&latest))
	var latestBlob string
	must(db.QueryRow(ctx, `SELECT evidence#>>'{observation,field_evidence_sha256,0}' FROM product_alerts WHERE alert_id=$1`, latest).Scan(&latestBlob))
	_, e = db.Exec(ctx, `UPDATE notification_evidence_blobs SET raw_bytes='{}'::bytea WHERE owner_id=$1 AND sha256=$2`, a.id, latestBlob)
	must(e)
	beforeMail = len(collector.all())
	ok, e = worker.DeliverOne(ctx)
	must(e)
	check(ok && len(collector.all()) == beforeMail, "source corruption blocks mail")
	// A pinned snapshot orders history newest-first and excludes intervening publication.
	var page struct {
		Items []struct {
			ID string `json:"alert_id"`
		}
		Next string `json:"next_cursor"`
	}
	must(json.Unmarshal(a.call("GET", "alerts?limit=1", nil, 200, ""), &page))
	check(page.Next != "" && page.Items[0].ID == latest, "newest-first inbox")
	b.call("GET", "alerts?limit=1&after="+page.Next, nil, 400, "")
	a.call("GET", "alerts?limit=1&after="+page.Next+"broken", nil, 400, "")
	var second struct {
		Items []struct {
			ID string `json:"alert_id"`
		}
	}
	must(json.Unmarshal(a.call("GET", "alerts?limit=1&after="+page.Next, nil, 200, ""), &second))
	check(len(second.Items) == 1 && second.Items[0].ID != latest, "snapshot page does not duplicate")
	// SMTP DATA acceptance is success even if QUIT fails; opportunistic plaintext is forbidden.
	collector.mu.Lock()
	collector.acceptThenDrop = true
	collector.mu.Unlock()
	must(smtp.Send(ctx, "test@example.test", uuid.NewString(), "Synthetic accepted message", "Local verification only"))
	collector.mu.Lock()
	collector.acceptThenDrop = false
	collector.mu.Unlock()
	tlsRequired := *smtp
	tlsRequired.Mode = "starttls"
	check(tlsRequired.Send(ctx, "test@example.test", uuid.NewString(), "TLS check", "Local verification only") != nil, "missing STARTTLS refused")
	// Native polygon/radius matching, route support and real immutable CAP byte checks.
	geometryChecks(ctx, db, s3, source, a, prefix)
	a.call("GET", "notification-status", nil, 200, "")
	a.call("GET", "alerts", nil, 200, "")
	a.call("POST", "alerts/"+firstID+"/acknowledge", nil, 200, "")
	a.call("DELETE", "notification-email", nil, 200, "")
	a.call("GET", "notification-settings", nil, 200, "")
	// Account deletion cascades recipients, evidence, evaluations and pending deliveries.
	_, e = db.Exec(ctx, `DELETE FROM product_accounts WHERE account_id=$1`, a.id)
	must(e)
	must(db.QueryRow(ctx, `SELECT count(*) FROM notification_evidence_blobs WHERE owner_id=$1`, a.id).Scan(&count))
	check(count == 0, "private evidence deletion")
	fmt.Println("Disposable notification verification passed: actual PostgreSQL/PostGIS, HTTP ownership/CSRF, native sampling, SMTP proof/retry/opt-out, frozen replay, lease/version fences, positive recovery, source geometry, corruption and deletion.")
}

func geometryChecks(ctx context.Context, db *pgxpool.Pool, s3 *minio.Client, source *science.Server, a client, prefix string) {
	now := time.Now().UTC()
	expires := now.Add(2 * time.Hour)
	sent := now.Add(-time.Hour)
	revision, run, calc := uuid.NewString(), uuid.NewString(), uuid.NewString()
	poly := advisories.Geometry{Type: "Polygon", Coordinates: [][][]float64{{{71.99, 11.99}, {72.01, 11.99}, {72.01, 12.01}, {71.99, 12.01}, {71.99, 11.99}}}}
	msg := advisories.Message{Identity: advisories.Identity{Sender: "IMD", Identifier: run, Sent: sent}, Sender: "IMD", Identifier: run, Sent: sent, RevisionID: revision, SourceID: "ndma_cap_rss", Operational: true, Type: "Alert", Status: "Actual", Scope: "Public", Issues: []string{}, References: []advisories.Identity{}, Infos: []advisories.Info{{Language: "en", Event: "Synthetic warning", Severity: "Severe", Urgency: "Expected", Certainty: "Likely", Effective: sent, Expires: &expires, Issues: []string{}, Areas: []advisories.Area{{Description: "fixture", Polygons: []advisories.Geometry{poly}, Circles: []advisories.Circle{}, Unresolved: []string{}}}}}}
	raw := []byte("<synthetic-byte-integrity-fixture/>")
	put := func(key string, b []byte) {
		_, e := s3.PutObject(ctx, "nautiq", key, bytes.NewReader(b), int64(len(b)), minio.PutObjectOptions{})
		must(e)
	}
	put(prefix+"cap.xml", raw)
	receipt := map[string]any{"raw_key": prefix + "cap.xml", "sha256": notifications.Hash(raw), "bytes": len(raw), "url": "https://sachet.ndma.gov.in/cap_public_website/FetchXMLFile?identifier=fixture"}
	var mirror map[string]any
	must(json.Unmarshal(data(msg), &mirror))
	mirror["receipt"] = receipt
	report := data(map[string]any{"messages": []any{mirror}, "receipts": []any{receipt}})
	put(prefix+"report.json", report)
	calcRaw := data(map[string]any{"kind": "advisory_ingestion", "synthetic": true})
	put(prefix+"calc.json", calcRaw)
	_, e := db.Exec(ctx, `INSERT INTO calculations(calculation_id,calculation_sha256,kind,method_version,manifest,manifest_key,manifest_sha256,state) VALUES($1,$2,'advisory_ingestion','synthetic-fixture',$3,$4,$2,'frozen')`, calc, notifications.Hash(calcRaw), calcRaw, prefix+"calc.json")
	must(e)
	_, e = db.Exec(ctx, `INSERT INTO advisory_runs(run_id,source_id,checked_at,report,report_key,report_sha256,calculation_id) VALUES($1,'ndma_cap_rss',$2,$3,$4,$5,$6)`, run, now, report, prefix+"report.json", notifications.Hash(report), calc)
	must(e)
	_, e = db.Exec(ctx, `INSERT INTO advisory_revisions(revision_id,source_id,sender,identifier,sent,raw_sha256,raw_key,raw_bytes,document,first_run_id) VALUES($1,'ndma_cap_rss','IMD',$2,$3,$4,$5,$6,$7,$8)`, revision, run, sent, notifications.Hash(raw), prefix+"cap.xml", len(raw), data(msg), run)
	must(e)
	_, e = db.Exec(ctx, `UPDATE advisory_sources SET latest_run_id=$1,checked_at=$2,transport='healthy' WHERE source_id='ndma_cap_rss'`, run, now)
	must(e)
	for _, watchData := range []any{map[string]any{"type": "point", "latitude": 12, "longitude": 72, "radius_km": 0}, map[string]any{"type": "point", "latitude": 12, "longitude": 72, "radius_km": 5}, map[string]any{"type": "polygon", "polygon": poly.Coordinates[0]}} {
		watch := a.object("watchlists", map[string]any{"name": "Geometry fixture", "data": watchData})
		rule := a.object("alert-rules", map[string]any{"name": "Authority fixture", "data": map[string]any{"watchlist_id": watch.ID, "type": "official_advisory", "channel": "in_app", "enabled": true}})
		in, e := notifications.Load(ctx, db, rule.ID)
		must(e)
		out, e := source.NotificationEvidence(ctx, in, now)
		must(e)
		check(out.Outcome == "triggered" && len(out.Warnings) == 1 && out.Severity == 2, "exact geometry official warning despite unknown other feeds")
	}
	watch := a.object("watchlists", map[string]any{"name": "Timed fixture", "data": map[string]any{"type": "point", "latitude": 12, "longitude": 72, "radius_km": 0}})
	rule := a.object("alert-rules", map[string]any{"name": "Timed authority fixture", "data": map[string]any{"watchlist_id": watch.ID, "type": "official_advisory", "channel": "in_app", "enabled": true}})
	in, e := notifications.Load(ctx, db, rule.ID)
	must(e)
	in.Watch = data(map[string]any{"type": "route", "route_id": uuid.NewString()})
	for _, tc := range []struct {
		name    string
		points  []trips.Point
		trigger bool
	}{
		{"warning before arrival", []trips.Point{{Latitude: 12, Longitude: 71.9, Time: now}, {Latitude: 12, Longitude: 72, Time: now.Add(4 * time.Hour)}}, false},
		{"warning at arrival", []trips.Point{{Latitude: 12, Longitude: 71.9, Time: now}, {Latitude: 12, Longitude: 72, Time: now.Add(time.Hour)}}, true},
		{"stationary stop", []trips.Point{{Latitude: 12, Longitude: 72, Time: now}, {Latitude: 12, Longitude: 72, Time: now.Add(time.Hour)}}, true},
		{"already traversed warning", []trips.Point{{Latitude: 12, Longitude: 72, Time: now.Add(-time.Hour)}, {Latitude: 12, Longitude: 72.1, Time: now.Add(time.Hour)}}, false},
	} {
		in.Route = data(trips.Request{Waypoints: tc.points, SpacingKM: 5, StepMinutes: 30})
		out, err := source.NotificationEvidence(ctx, in, now)
		must(err)
		check((out.Outcome == "triggered") == tc.trigger, tc.name)
	}
	in.Route = data(trips.Request{Waypoints: []trips.Point{{Latitude: 12, Longitude: 72, Time: now.Add(-2 * time.Hour)}, {Latitude: 12, Longitude: 72, Time: now.Add(-time.Hour)}}, SpacingKM: 5, StepMinutes: 30})
	_, e = source.NotificationEvidence(ctx, in, now)
	check(e != nil, "expired saved route is refused rather than rescheduled")
}
func main() {
	offline()
	if len(os.Args) > 1 && os.Args[1] == "--offline" {
		return
	}
	isolated()
}
