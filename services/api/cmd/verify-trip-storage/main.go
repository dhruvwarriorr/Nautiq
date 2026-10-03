// Isolated trip API/persistence verification. All synthetic data lives in a disposable database.
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"
	"google.golang.org/grpc"
	"google.golang.org/protobuf/proto"
	pb "nautiq.local/api/gen/nautiq/platform/v1"
	"nautiq.local/api/internal/advisories"
	"nautiq.local/api/internal/science"
	"nautiq.local/api/internal/trips"
)

func check(ok bool, label string) {
	if !ok {
		panic("trip storage contract: " + label)
	}
}
func must(err error) {
	if err != nil {
		panic("trip verification operation failed")
	}
}
func data(value any) []byte { b, err := json.Marshal(value); must(err); return b }
func put(s3 *minio.Client, key string, raw []byte) {
	_, err := s3.PutObject(context.Background(), "nautiq", key, bytes.NewReader(raw), int64(len(raw)), minio.PutObjectOptions{})
	must(err)
}

type fixtureRelease struct {
	ID      string
	SHA     string
	Product string
	Cycle   time.Time
	Start   time.Time
	End     time.Time
}
type fakeFields struct {
	pb.FieldServiceClient
	Releases map[string]fixtureRelease
	Change   func()
	once     sync.Once
}

func (f *fakeFields) Route(ctx context.Context, r *pb.FieldRouteRequest, options ...grpc.CallOption) (*pb.FieldEvidence, error) {
	if f.Change != nil {
		f.once.Do(f.Change)
	}
	release := f.Releases[r.ReleaseId]
	req := trips.Request{SpacingKM: r.SpacingKm, StepMinutes: r.StepMinutes}
	for _, p := range r.Waypoints {
		t, e := time.Parse(time.RFC3339Nano, p.Time)
		must(e)
		req.Waypoints = append(req.Waypoints, trips.Point{Latitude: p.Latitude, Longitude: p.Longitude, Time: t})
	}
	points, _, err := trips.Points(req, time.Now().UTC())
	must(err)
	units, value := "m", 1.25
	if r.Variable == "wind_speed_m_s" {
		units = "m s-1"
		value = 3.5
	}
	samples := []map[string]any{}
	for _, p := range points {
		samples = append(samples, map[string]any{"latitude": p.Latitude, "longitude": p.Longitude, "requested_time": p.Time, "value": value, "units": units, "status": "available", "reason": nil})
	}
	wire, e := proto.MarshalOptions{Deterministic: true}.Marshal(r)
	must(e)
	raw := data(map[string]any{"release_id": release.ID, "manifest_sha256": release.SHA, "variable": r.Variable, "calculation_id": uuid.NewString(), "release_approved": false, "metadata": map[string]any{"product_id": release.Product, "cycle": release.Cycle, "valid_time_start": release.Start, "valid_time_end": release.End}, "calculation": map[string]any{"request_sha256": trips.HashRaw(wire)}, "result": map[string]any{"samples": samples}})
	return &pb.FieldEvidence{ReleaseId: release.ID, ManifestSha256: release.SHA, ResultJson: raw}, nil
}

type created struct {
	ID      string        `json:"calculation_id"`
	Token   string        `json:"access_token"`
	SHA     string        `json:"manifest_sha256"`
	Verdict trips.Verdict `json:"verdict"`
}

func invoke(server *httptest.Server, method, path string, body []byte, token string, expected int) []byte {
	request, err := http.NewRequest(method, server.URL+path, bytes.NewReader(body))
	must(err)
	if body != nil {
		request.Header.Set("Content-Type", "application/json")
	}
	if token != "" {
		request.Header.Set("Authorization", "Bearer "+token)
	}
	response, err := server.Client().Do(request)
	must(err)
	defer response.Body.Close()
	raw, e := io.ReadAll(response.Body)
	must(e)
	var failure struct {
		Code string `json:"code"`
	}
	if response.StatusCode != expected {
		_ = json.Unmarshal(raw, &failure)
	}
	check(response.StatusCode == expected, fmt.Sprintf("HTTP %d expected %d on %s (%s)", response.StatusCode, expected, path, failure.Code))
	if expected == 201 {
		check(strings.HasPrefix(response.Header.Get("Content-Type"), "application/json"), "JSON create response")
	}
	return raw
}
func create(server *httptest.Server, req trips.Request) created {
	raw := invoke(server, "POST", "/api/v1/trips", data(req), "", 201)
	var out created
	must(json.Unmarshal(raw, &out))
	check(len(out.Token) == 64 && out.ID != "", "private receipt identity")
	return out
}
func main() {
	ctx := context.Background()
	admin, err := pgxpool.New(ctx, os.Getenv("DATABASE_URL"))
	must(err)
	defer admin.Close()
	name := "nautiq_trip_test_" + strings.ReplaceAll(uuid.NewString(), "-", "")[:12]
	_, err = admin.Exec(ctx, "CREATE DATABASE "+name)
	must(err)
	dsn, err := url.Parse(os.Getenv("DATABASE_URL"))
	must(err)
	dsn.Path = "/" + name
	db, err := pgxpool.New(ctx, dsn.String())
	must(err)
	s3, err := minio.New(os.Getenv("MINIO_ENDPOINT"), &minio.Options{Creds: credentials.NewStaticV4(os.Getenv("MINIO_ROOT_USER"), os.Getenv("MINIO_ROOT_PASSWORD"), ""), Secure: false})
	must(err)
	prefix := "verification/trips/" + name + "/"
	ownedFields := map[string]bool{}
	defer func() {
		// Clean only receipts bound to this test's unique field IDs, including staged rollback objects.
		for object := range s3.ListObjects(ctx, "nautiq", minio.ListObjectsOptions{Prefix: "trips/private/", Recursive: true}) {
			if object.Err != nil {
				continue
			}
			o, e := s3.GetObject(ctx, "nautiq", object.Key, minio.GetObjectOptions{})
			if e != nil {
				continue
			}
			raw, e := io.ReadAll(io.LimitReader(o, 8<<20))
			o.Close()
			if e != nil {
				continue
			}
			var receipt struct {
				Input struct {
					Request trips.Request `json:"request"`
				} `json:"input"`
			}
			if json.Unmarshal(raw, &receipt) != nil {
				continue
			}
			owned := false
			for _, binding := range receipt.Input.Request.Fields {
				owned = owned || ownedFields[binding.ReleaseID]
			}
			if owned {
				_ = s3.RemoveObject(ctx, "nautiq", object.Key, minio.RemoveObjectOptions{})
			}
		}
		for object := range s3.ListObjects(ctx, "nautiq", minio.ListObjectsOptions{Prefix: prefix, Recursive: true}) {
			if object.Err == nil {
				_ = s3.RemoveObject(ctx, "nautiq", object.Key, minio.RemoveObjectOptions{})
			}
		}
		db.Close()
		_, _ = admin.Exec(ctx, "DROP DATABASE "+name+" WITH (FORCE)")
	}()
	files, err := filepath.Glob("/migrations/*.sql")
	must(err)
	check(len(files) == 13, "all migrations present")
	for _, file := range files {
		raw, e := os.ReadFile(file)
		must(e)
		_, err = db.Exec(ctx, string(raw))
		must(err)
	}
	now := time.Now().UTC().Truncate(time.Second)
	policy := map[string]any{"required": true, "marine_coverage_verified": false, "cadence_verified": false, "redistribution_reviewed": false, "transport_max_age_seconds": 1800}
	for _, id := range []string{"ndma_cap_rss", "incois_advisories"} {
		_, err = db.Exec(ctx, "INSERT INTO advisory_sources(source_id,policy) VALUES($1,$2)", id, data(policy))
		must(err)
	}
	fake := &fakeFields{Releases: map[string]fixtureRelease{}}
	req := trips.Request{Activity: "fishing", ThresholdVersion: trips.DefaultPolicy().Version, Waypoints: []trips.Point{{Latitude: 12, Longitude: 72, Time: now.Add(10 * time.Minute)}, {Latitude: 12.05, Longitude: 72.05, Time: now.Add(70 * time.Minute)}, {Latitude: 12, Longitude: 72, Time: now.Add(130 * time.Minute)}}, SpacingKM: 5, StepMinutes: 30, Fields: []trips.Binding{}, Preferences: map[string]trips.Preference{}}
	for i, spec := range trips.DefaultPolicy().Inputs {
		if !spec.Required {
			continue
		}
		id, calc := uuid.NewString(), uuid.NewString()
		sha := strings.Repeat(fmt.Sprint(i+1), 64)
		ownedFields[id] = true
		_, err = db.Exec(ctx, "INSERT INTO calculations(calculation_id,calculation_sha256,kind,method_version,manifest,manifest_key,manifest_sha256,state) VALUES($1,$2,'field_normalization','isolated-fixture','{}',$3,$2,'frozen')", calc, sha, prefix+"field-unused")
		must(err)
		_, err = db.Exec(ctx, "INSERT INTO field_releases(release_id,release_sha256,product_id,calculation_id,cycle,valid_time_start,valid_time_end,source_version,manifest_key,manifest_sha256,manifest) VALUES($1,$2,$3,$4,$5,$6,$7,'forecast',$8,$2,'{}')", id, sha, spec.ProductID, calc, now.Add(-time.Hour), now, now.Add(24*time.Hour), prefix+"field-unused")
		must(err)
		fake.Releases[id] = fixtureRelease{id, sha, spec.ProductID, now.Add(-time.Hour), now, now.Add(24 * time.Hour)}
		req.Fields = append(req.Fields, trips.Binding{Variable: spec.Variable, ReleaseID: id})
	}
	api := science.New(db, s3)
	api.Fields = fake
	mux := http.NewServeMux()
	api.Register(mux)
	server := httptest.NewServer(mux)
	defer server.Close()
	first := create(server, req)
	check(first.Verdict.Status == "insufficient_data" && len(first.Verdict.Worst) == 2 && first.Verdict.Worst[0].Point.Time.Year() > 2020, "unapproved policy retains real-shaped samples")
	invoke(server, "GET", "/api/v1/calculations/"+first.ID, nil, "", 404)
	invoke(server, "GET", "/api/v1/trips/"+first.ID, nil, "", 404)
	invoke(server, "GET", "/api/v1/trips/"+first.ID, nil, strings.Repeat("0", 64), 404)
	invoke(server, "GET", "/api/v1/trips/"+first.ID, nil, first.Token, 200)
	raw := invoke(server, "POST", "/api/v1/trips/"+first.ID+"/replay", nil, first.Token, 200)
	check(bytes.Contains(raw, []byte(`"freshness_renewed":false`)), "frozen replay")
	_, err = db.Exec(ctx, "UPDATE trip_calculations SET verdict=verdict || '{\"status\":\"favorable\"}' WHERE calculation_id=$1", first.ID)
	must(err)
	invoke(server, "GET", "/api/v1/trips/"+first.ID, nil, first.Token, 503)
	_, err = db.Exec(ctx, "UPDATE trip_calculations SET verdict=$2 WHERE calculation_id=$1", first.ID, data(first.Verdict))
	must(err)
	var key string
	must(db.QueryRow(ctx, "SELECT manifest_key FROM calculations WHERE calculation_id=$1", first.ID).Scan(&key))
	object, e := s3.GetObject(ctx, "nautiq", key, minio.GetObjectOptions{})
	must(e)
	original, e := io.ReadAll(object)
	object.Close()
	must(e)
	must(s3.RemoveObject(ctx, "nautiq", key, minio.RemoveObjectOptions{}))
	invoke(server, "GET", "/api/v1/trips/"+first.ID, nil, first.Token, 503)
	put(s3, key, original)
	invoke(server, "GET", "/api/v1/trips/"+first.ID, nil, first.Token, 200)
	// A thin warning polygon lies between forecast samples, but intersects the whole timed route.
	sent := now.Add(-time.Hour)
	expires := now.Add(4 * time.Hour)
	revision, run, calc := uuid.NewString(), uuid.NewString(), uuid.NewString()
	polygon := advisories.Geometry{Type: "Polygon", Coordinates: [][][]float64{{{72.0119, 12.0119}, {72.0131, 12.0119}, {72.0131, 12.0131}, {72.0119, 12.0131}, {72.0119, 12.0119}}}}
	message := advisories.Message{Identity: advisories.Identity{Sender: "IMD", Identifier: name, Sent: sent}, Sender: "IMD", Identifier: name, Sent: sent, RevisionID: revision, SourceID: "ndma_cap_rss", Operational: true, Type: "Alert", Status: "Actual", Scope: "Public", Issues: []string{}, References: []advisories.Identity{}, Infos: []advisories.Info{{Language: "en-IN", Event: "High waves fixture", Severity: "Severe", Urgency: "Expected", Certainty: "Likely", Effective: sent, Expires: &expires, Issues: []string{}, Areas: []advisories.Area{{Description: "Isolated test warning", Polygons: []advisories.Geometry{polygon}, Circles: []advisories.Circle{}, Unresolved: []string{}}}}}}
	capXML := []byte(fmt.Sprintf(`<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2"><identifier>%s</identifier><sender>IMD</sender><sent>%s</sent><status>Actual</status><msgType>Alert</msgType><scope>Public</scope><info><category>Met</category><event>High waves fixture</event><urgency>Expected</urgency><severity>Severe</severity><certainty>Likely</certainty><expires>%s</expires><area><areaDesc>Isolated test warning</areaDesc><polygon>12.0119,72.0119 12.0119,72.0131 12.0131,72.0131 12.0131,72.0119 12.0119,72.0119</polygon></area></info></alert>`, name, sent.Format(time.RFC3339), expires.Format(time.RFC3339)))
	rawKey := prefix + "cap.xml"
	put(s3, rawKey, capXML)
	receipt := map[string]any{"raw_key": rawKey, "sha256": trips.HashRaw(capXML), "bytes": len(capXML), "url": "https://sachet.ndma.gov.in/cap_public_website/FetchXMLFile?identifier=1"}
	var m map[string]any
	must(json.Unmarshal(data(message), &m))
	m["receipt"] = receipt
	report := data(map[string]any{"messages": []any{m}, "receipts": []any{receipt}})
	reportKey := prefix + "report.json"
	put(s3, reportKey, report)
	calcData := data(map[string]any{"kind": "advisory_ingestion", "source": "isolated-verification"})
	calcKey := prefix + "calc.json"
	put(s3, calcKey, calcData)
	_, err = db.Exec(ctx, "INSERT INTO calculations(calculation_id,calculation_sha256,kind,method_version,manifest,manifest_key,manifest_sha256,state) VALUES($1,$2,'advisory_ingestion','isolated-fixture',$3,$4,$2,'frozen')", calc, trips.HashRaw(calcData), calcData, calcKey)
	must(err)
	_, err = db.Exec(ctx, "INSERT INTO advisory_runs(run_id,source_id,checked_at,report,report_key,report_sha256,calculation_id) VALUES($1,'ndma_cap_rss',$2,$3,$4,$5,$6)", run, now, report, reportKey, trips.HashRaw(report), calc)
	must(err)
	_, err = db.Exec(ctx, "INSERT INTO advisory_revisions(revision_id,source_id,sender,identifier,sent,raw_sha256,raw_key,raw_bytes,document,first_run_id) VALUES($1,'ndma_cap_rss','IMD',$2,$3,$4,$5,$6,$7,$8)", revision, name, sent, trips.HashRaw(capXML), rawKey, len(capXML), data(message), run)
	must(err)
	_, err = db.Exec(ctx, "UPDATE advisory_sources SET latest_run_id=$1,checked_at=$2,transport='healthy' WHERE source_id='ndma_cap_rss'", run, now)
	must(err)
	warning := create(server, req)
	check(warning.Verdict.Status == "official_warning" && len(warning.Verdict.Missing) > 0, "complete timed geometry warning dominates unknown inputs")
	invoke(server, "POST", "/api/v1/trips/"+warning.ID+"/replay", nil, warning.Token, 200)
	// Immutable warning expires before departure: it must not be counted in a later route.
	later := req
	later.Waypoints = append([]trips.Point{}, req.Waypoints...)
	for i := range later.Waypoints {
		later.Waypoints[i].Time = later.Waypoints[i].Time.Add(5 * time.Hour)
	}
	check(create(server, later).Verdict.Status == "insufficient_data", "validity clipped before intersections")
	// Inject a source change during field sampling; staged work cannot publish obsolete advisory state.
	var count int
	must(db.QueryRow(ctx, "SELECT count(*) FROM trip_calculations").Scan(&count))
	fake.Change = func() {
		_, e := db.Exec(ctx, "UPDATE advisory_sources SET latest_run_id=NULL WHERE source_id='ndma_cap_rss'")
		must(e)
	}
	invoke(server, "POST", "/api/v1/trips", data(req), "", 409)
	fake.Change = nil
	var after int
	must(db.QueryRow(ctx, "SELECT count(*) FROM trip_calculations").Scan(&after))
	check(after == count, "source publication race rollback")
	_, err = db.Exec(ctx, "UPDATE advisory_sources SET latest_run_id=$1 WHERE source_id='ndma_cap_rss'", run)
	must(err)
	_, err = db.Exec(ctx, `CREATE FUNCTION refuse_trip() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN RAISE EXCEPTION 'isolated failure'; END$$; CREATE TRIGGER refuse_trip BEFORE INSERT ON trip_calculations FOR EACH ROW EXECUTE FUNCTION refuse_trip()`)
	must(err)
	var calculations int
	must(db.QueryRow(ctx, "SELECT count(*) FROM calculations").Scan(&calculations))
	invoke(server, "POST", "/api/v1/trips", data(req), "", 503)
	var final int
	must(db.QueryRow(ctx, "SELECT count(*) FROM calculations").Scan(&final))
	check(final == calculations, "calculation and verdict roll back together")
	invoke(server, "POST", "/api/v1/trips", []byte(`{"activity":"fishing","activity":"boating"}`), "", 400)
	bad := req
	bad.Waypoints = append([]trips.Point{}, req.Waypoints...)
	bad.Waypoints[0].Time = now.Add(-time.Hour)
	invoke(server, "POST", "/api/v1/trips", data(bad), "", 400)
	fmt.Println("Trip persistence passed: private token access, public-record exclusion, captured field/advisory replay, corruption refusal/recovery, whole-leg warning intersection, temporal clipping, source race and atomic rollback.")
}
