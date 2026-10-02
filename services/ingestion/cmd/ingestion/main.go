package main

import (
	"bytes"
	"compress/gzip"
	"container/heap"
	"context"
	"crypto/sha256"
	"encoding/csv"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log/slog"
	"math"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"
	"github.com/nats-io/nats.go"
	"github.com/nats-io/nats.go/jetstream"
)

type Config struct {
	SourceID        string                                     `json:"source_id"`
	IndexURL        string                                     `json:"index_url"`
	BaseURL         string                                     `json:"base_url"`
	Domain          struct{ West, South, East, North float64 } `json:"domain"`
	Workers         int                                        `json:"workers"`
	MaxProfiles     int                                        `json:"max_profiles_per_run"`
	MaxCandidates   int                                        `json:"max_discovery_candidates"`
	MaxBytes        int64                                      `json:"max_object_bytes"`
	MaxExpanded     int64                                      `json:"max_expanded_index_bytes"`
	MaxLine         int                                        `json:"max_index_line_bytes"`
	Deadline        int                                        `json:"request_deadline_seconds"`
	Overlap         int                                        `json:"overlap_hours"`
	InitialDays     int                                        `json:"initial_update_lookback_days"`
	ObservationDays int                                        `json:"observation_lookback_days"`
	Poll            int                                        `json:"poll_seconds"`
	Reconcile       int                                        `json:"reconciliation_seconds"`
}
type App struct {
	cfg           Config
	db            *pgxpool.Pool
	s3            *minio.Client
	http          *http.Client
	gate          <-chan time.Time
	scope         string
	observedSince time.Time
}
type Candidate struct {
	Path    string
	Updated time.Time
}
type Candidates []Candidate

func (c Candidates) Len() int { return len(c) }
func less(a, b Candidate) bool {
	if a.Updated.Equal(b.Updated) {
		return a.Path < b.Path
	}
	return a.Updated.Before(b.Updated)
}
func (c Candidates) Less(i, j int) bool   { return less(c[j], c[i]) }
func (c Candidates) Swap(i, j int)        { c[i], c[j] = c[j], c[i] }
func (c *Candidates) Push(v any)          { *c = append(*c, v.(Candidate)) }
func (c *Candidates) Pop() any            { old := *c; v := old[len(old)-1]; *c = old[:len(old)-1]; return v }
func sha(data []byte) string              { h := sha256.Sum256(data); return hex.EncodeToString(h[:]) }
func key(path string, t time.Time) string { return path + "|" + t.UTC().Format(time.RFC3339) }

var safePath = regexp.MustCompile(`^[a-z]+/[0-9]{5,8}/profiles/[RD][0-9]{5,8}_[0-9]+D?\.nc$`)

func main() {
	once := flag.Bool("once", false, "discover/download once and dispatch pending events")
	dispatch := flag.Bool("dispatch-only", false, "publish pending outbox events only")
	reconcile := flag.Bool("reconcile", false, "scan all unseen index records in this configured observation scope")
	configFile := flag.String("config", "/argo.json", "source configuration")
	flag.Parse()
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	cfgBytes, err := os.ReadFile(*configFile)
	if err != nil {
		panic("source configuration unavailable")
	}
	var cfg Config
	if json.Unmarshal(cfgBytes, &cfg) != nil || cfg.SourceID != "argo_gdac" || cfg.IndexURL != "https://data-argo.ifremer.fr/ar_index_global_prof.txt.gz" || cfg.BaseURL != "https://data-argo.ifremer.fr/dac/" || cfg.Workers < 1 || cfg.Workers > 4 || cfg.MaxProfiles < 1 || cfg.MaxProfiles > 200 || cfg.MaxCandidates < cfg.MaxProfiles || cfg.MaxCandidates > 10000 || cfg.MaxBytes < 1 || cfg.MaxBytes > 67108864 || cfg.MaxExpanded > 536870912 || cfg.MaxExpanded < 1 || cfg.Deadline < 1 || cfg.Deadline > 120 || cfg.Poll < 60 || cfg.Reconcile < cfg.Poll || cfg.MaxLine < 128 || cfg.MaxLine > 4096 || cfg.Domain.West >= cfg.Domain.East || cfg.Domain.South >= cfg.Domain.North {
		panic("invalid source configuration")
	}
	db, err := pgxpool.New(ctx, os.Getenv("DATABASE_URL"))
	if err != nil {
		panic("database configuration unavailable")
	}
	defer db.Close()
	s3, err := minio.New(os.Getenv("MINIO_ENDPOINT"), &minio.Options{Creds: credentials.NewStaticV4(os.Getenv("MINIO_ROOT_USER"), os.Getenv("MINIO_ROOT_PASSWORD"), ""), Secure: false})
	if err != nil {
		panic("storage configuration unavailable")
	}
	observed := time.Now().UTC().AddDate(0, 0, -cfg.ObservationDays).Truncate(24 * time.Hour)
	// Fixed date (not rolling scope) keeps restart/discovery identity stable.
	observed = time.Date(observed.Year(), observed.Month(), 1, 0, 0, 0, 0, time.UTC)
	if value := os.Getenv("ARGO_OBSERVED_SINCE"); value != "" {
		observed, err = time.Parse(time.RFC3339, value)
		if err != nil {
			panic("invalid ARGO_OBSERVED_SINCE")
		}
	}
	domainBytes, _ := json.Marshal(cfg.Domain)
	scope := sha([]byte(string(domainBytes) + observed.Format(time.RFC3339)))
	limiter := time.NewTicker(300 * time.Millisecond)
	defer limiter.Stop()
	a := App{cfg: cfg, db: db, s3: s3, http: secureClient(), gate: limiter.C, scope: scope, observedSince: observed}
	if *dispatch {
		if err := a.dispatch(ctx); err != nil {
			slog.Error("dispatch failed")
			os.Exit(1)
		}
		return
	}
	if *once {
		if err := a.ingest(ctx, *reconcile); err != nil {
			slog.Error("ingestion run failed", "reason", err.Error())
			os.Exit(1)
		}
		if err := a.dispatch(ctx); err != nil {
			slog.Error("outbox pending; retry dispatch")
			os.Exit(1)
		}
		return
	}
	go func() {
		lastFull := time.Time{}
		for ctx.Err() == nil {
			if err := a.ingest(ctx, false); err != nil {
				slog.Warn("live ingestion incomplete", "reason", err.Error())
			}
			if time.Since(lastFull) > time.Duration(cfg.Reconcile)*time.Second {
				if err := a.ingest(ctx, true); err != nil {
					slog.Warn("backfill reconciliation incomplete", "reason", err.Error())
				} else {
					lastFull = time.Now()
				}
			}
			select {
			case <-ctx.Done():
				return
			case <-time.After(time.Duration(cfg.Poll) * time.Second):
			}
		}
	}()
	for ctx.Err() == nil {
		if err := a.dispatch(ctx); err != nil {
			slog.Warn("broker dispatch unavailable")
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(time.Second):
		}
	}
}

func secureClient() *http.Client {
	transport := &http.Transport{TLSHandshakeTimeout: 10 * time.Second, ResponseHeaderTimeout: 30 * time.Second, MaxIdleConnsPerHost: 4, Proxy: nil,
		DialContext: func(ctx context.Context, network, address string) (net.Conn, error) {
			host, port, err := net.SplitHostPort(address)
			if err != nil || host != "data-argo.ifremer.fr" || port != "443" {
				return nil, errors.New("destination_denied")
			}
			ips, err := net.DefaultResolver.LookupIPAddr(ctx, host)
			if err != nil {
				return nil, errors.New("dns_failed")
			}
			for _, ip := range ips {
				if !ip.IP.IsGlobalUnicast() || ip.IP.IsPrivate() || ip.IP.IsLoopback() || ip.IP.IsLinkLocalUnicast() {
					return nil, errors.New("private_destination_denied")
				}
			}
			for _, ip := range ips {
				conn, err := (&net.Dialer{Timeout: 15 * time.Second}).DialContext(ctx, network, net.JoinHostPort(ip.IP.String(), port))
				if err == nil {
					return conn, nil
				}
			}
			return nil, errors.New("connect_failed")
		}}
	return &http.Client{Transport: transport, CheckRedirect: func(*http.Request, []*http.Request) error { return errors.New("redirect_denied") }}
}

func (a *App) fetch(ctx context.Context, uri string, headers map[string]string) ([]byte, http.Header, int, error) {
	parsed, err := url.Parse(uri)
	if err != nil || parsed.Scheme != "https" || parsed.Host != "data-argo.ifremer.fr" || parsed.User != nil || parsed.RawQuery != "" {
		return nil, nil, 0, errors.New("source_url_denied")
	}
	ctx, cancel := context.WithTimeout(ctx, time.Duration(a.cfg.Deadline)*time.Second)
	defer cancel()
	for attempt := 0; attempt < 3; attempt++ {
		select {
		case <-ctx.Done():
			return nil, nil, 0, errors.New("fetch_deadline")
		case <-a.gate:
		}
		req, _ := http.NewRequestWithContext(ctx, http.MethodGet, uri, nil)
		req.Header.Set("User-Agent", "Nautiq-Argo/0.1")
		req.Header.Set("Accept-Encoding", "identity")
		for k, v := range headers {
			req.Header.Set(k, v)
		}
		resp, err := a.http.Do(req)
		delay := time.Duration(1<<attempt) * time.Second
		if err == nil {
			if resp.StatusCode == 304 {
				resp.Body.Close()
				return nil, resp.Header, 304, nil
			}
			if resp.StatusCode == 200 {
				if resp.ContentLength > a.cfg.MaxBytes {
					resp.Body.Close()
					return nil, nil, 0, errors.New("object_too_large")
				}
				data, e := io.ReadAll(io.LimitReader(resp.Body, a.cfg.MaxBytes+1))
				resp.Body.Close()
				if e == nil && len(data) > 0 && int64(len(data)) <= a.cfg.MaxBytes && (resp.ContentLength < 0 || resp.ContentLength == int64(len(data))) {
					return data, resp.Header, 200, nil
				}
				if int64(len(data)) > a.cfg.MaxBytes {
					return nil, nil, 0, errors.New("object_too_large")
				}
			} else {
				resp.Body.Close()
				if resp.StatusCode != 429 && resp.StatusCode < 500 {
					return nil, nil, 0, fmt.Errorf("provider_http_%d", resp.StatusCode)
				}
				if retry := resp.Header.Get("Retry-After"); retry != "" {
					if seconds, e := strconv.Atoi(retry); e == nil {
						delay = time.Duration(seconds) * time.Second
					} else if date, e := http.ParseTime(retry); e == nil {
						delay = time.Until(date)
					} else {
						return nil, nil, 0, errors.New("invalid_retry_after")
					}
					if delay > 30*time.Second {
						return nil, nil, 0, errors.New("provider_retry_window")
					}
					if delay < 0 {
						delay = 0
					}
				}
			}
		}
		if attempt < 2 {
			select {
			case <-ctx.Done():
				return nil, nil, 0, errors.New("fetch_deadline")
			case <-time.After(delay):
			}
		}
	}
	return nil, nil, 0, errors.New("transport_retries_exhausted")
}

func (a *App) object(ctx context.Context, objectKey string, data []byte, meta map[string]string) error {
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	digest := sha(data)
	existing, err := a.s3.StatObject(ctx, "nautiq", objectKey, minio.StatObjectOptions{})
	if err == nil {
		if existing.Size != int64(len(data)) || existing.Metadata.Get("X-Amz-Meta-Sha256") != digest {
			return errors.New("immutable_object_conflict")
		}
	} else if minio.ToErrorResponse(err).Code != "NoSuchKey" {
		return err
	} else {
		meta["sha256"] = digest
		if _, err = a.s3.PutObject(ctx, "nautiq", objectKey, bytes.NewReader(data), int64(len(data)), minio.PutObjectOptions{ContentType: "application/octet-stream", UserMetadata: meta}); err != nil {
			return err
		}
	}
	obj, err := a.s3.GetObject(ctx, "nautiq", objectKey, minio.GetObjectOptions{})
	if err != nil {
		return err
	}
	defer obj.Close()
	stored, err := io.ReadAll(io.LimitReader(obj, int64(len(data))+1))
	if err != nil || len(stored) != len(data) || sha(stored) != digest {
		return errors.New("immutable_object_checksum")
	}
	return nil
}

func (a *App) register(ctx context.Context, run string, c Candidate, kind string, data []byte, headers http.Header) (string, error) {
	digest := sha(data)
	id := uuid.NewSHA1(uuid.NameSpaceURL, []byte(a.cfg.SourceID+"|"+c.Path+"|"+digest)).String()
	objectKey := "raw/argo_gdac/" + kind + "/" + digest[:2] + "/" + digest + "/" + filepath.Base(c.Path)
	meta := map[string]string{"source_path": c.Path, "source_updated_at": c.Updated.UTC().Format(time.RFC3339)}
	if err := a.object(ctx, objectKey, data, meta); err != nil {
		return "", err
	}
	uri := a.cfg.BaseURL + c.Path
	if kind == "index" {
		uri = a.cfg.IndexURL
	}
	receipt := map[string]any{"artifact_id": id, "source_id": a.cfg.SourceID, "source_path": c.Path, "source_url": uri, "sha256": digest, "object_key": objectKey, "source_updated_at": c.Updated, "run_id": run, "bytes": len(data), "received_at": time.Now().UTC(), "kind": kind, "etag": headers.Get("ETag"), "last_modified": headers.Get("Last-Modified")}
	receiptBytes, _ := json.Marshal(receipt)
	// Receipt is immutable too; retries reconstruct registration using these bytes.
	if _, err := a.s3.StatObject(ctx, "nautiq", "receipts/"+id+".json", minio.StatObjectOptions{}); err != nil {
		if err := a.object(ctx, "receipts/"+id+".json", receiptBytes, map[string]string{}); err != nil {
			return "", err
		}
	} else {
		obj, err := a.s3.GetObject(ctx, "nautiq", "receipts/"+id+".json", minio.GetObjectOptions{})
		if err != nil {
			return "", err
		}
		stored, err := io.ReadAll(io.LimitReader(obj, 65537))
		obj.Close()
		var previous map[string]any
		if err != nil || len(stored) > 65536 || json.Unmarshal(stored, &previous) != nil || previous["artifact_id"] != id || previous["sha256"] != digest || previous["source_path"] != c.Path || previous["object_key"] != objectKey {
			return "", errors.New("receipt_integrity_failed")
		}
	}
	metadata, _ := json.Marshal(map[string]string{"etag": headers.Get("ETag"), "last_modified": headers.Get("Last-Modified")})
	tx, err := a.db.Begin(ctx)
	if err != nil {
		return "", err
	}
	defer tx.Rollback(ctx)
	_, err = tx.Exec(ctx, `INSERT INTO raw_artifacts(artifact_id,source_id,source_path,source_url,source_updated_at,sha256,object_key,size_bytes,kind,run_id,http_metadata) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) ON CONFLICT(source_id,source_path,sha256) DO NOTHING`, id, a.cfg.SourceID, c.Path, uri, c.Updated, digest, objectKey, len(data), kind, run, metadata)
	if err != nil {
		return "", err
	}
	if kind == "profile" {
		payload, _ := json.Marshal(map[string]string{"artifact_id": id})
		eventID := uuid.NewSHA1(uuid.NameSpaceURL, []byte("raw.received|"+id)).String()
		_, err = tx.Exec(ctx, `INSERT INTO event_outbox(event_id,event_type,schema_version,aggregate_key,revision_sha256,payload) VALUES($1,'raw.received',1,$2,$3,$4) ON CONFLICT(event_type,aggregate_key,revision_sha256) DO NOTHING`, eventID, id, digest, payload)
		if err != nil {
			return "", err
		}
		_, err = tx.Exec(ctx, `UPDATE argo_discoveries SET status='received',artifact_id=$4 WHERE scope=$1 AND source_path=$2 AND source_updated_at=$3`, a.scope, c.Path, c.Updated, id)
		if err != nil {
			return "", err
		}
	}
	return id, tx.Commit(ctx)
}

func (original *App) ingest(ctx context.Context, full bool) (runErr error) {
	ctx, cancel := context.WithTimeout(ctx, 10*time.Minute)
	defer cancel()
	copy := *original
	a := &copy
	if full {
		a.scope += ":backfill"
	} else {
		a.scope += ":live"
	}
	run := uuid.NewString()
	if _, err := a.db.Exec(ctx, "INSERT INTO ingestion_runs(run_id,source_id,scope,run_kind) VALUES($1,$2,$3,$4)", run, a.cfg.SourceID, a.scope, map[bool]string{false: "live", true: "backfill"}[full]); err != nil {
		return errors.New("database_unavailable")
	}
	defer func() {
		cleanup, cancel := context.WithTimeout(context.WithoutCancel(ctx), 5*time.Second)
		defer cancel()
		status := "complete"
		if runErr != nil {
			status = "failed"
		}
		reason := ""
		if runErr != nil {
			reason = runErr.Error()
		}
		a.db.Exec(cleanup, "UPDATE ingestion_runs SET completed_at=now(),status=$2,reason_code=NULLIF($3,'') WHERE run_id=$1", run, status, reason)
	}()
	// Source-scope lock prevents concurrent scheduled/manual runs from racing the cursor.
	conn, err := a.db.Acquire(ctx)
	if err != nil {
		return errors.New("database_unavailable")
	}
	defer conn.Release()
	var locked bool
	if err := conn.QueryRow(ctx, "SELECT pg_try_advisory_lock(hashtext($1))", a.cfg.SourceID).Scan(&locked); err != nil || !locked {
		return errors.New("ingestion_scope_busy")
	}
	defer func() {
		cleanup, cancel := context.WithTimeout(context.WithoutCancel(ctx), 5*time.Second)
		defer cancel()
		if _, err := conn.Exec(cleanup, "SELECT pg_advisory_unlock(hashtext($1))", a.cfg.SourceID); err != nil {
			conn.Conn().Close(cleanup) // Never return a session holding the provider lock to the pool.
		}
	}()
	cutoff := time.Now().UTC().AddDate(0, 0, -a.cfg.InitialDays)
	var cursorPath string
	var cursorTime time.Time
	if e := a.db.QueryRow(ctx, "SELECT updated_at,source_path FROM ingestion_cursors WHERE scope=$1", a.scope).Scan(&cursorTime, &cursorPath); e == nil {
		cutoff = cursorTime.Add(-time.Duration(a.cfg.Overlap) * time.Hour)
	}
	if full {
		cutoff = time.Time{}
	}
	known := map[string]bool{}
	rows, err := a.db.Query(ctx, "SELECT source_path,source_updated_at FROM argo_discoveries WHERE scope=$1 AND status <> 'pending'", a.scope)
	if err != nil {
		return errors.New("database_unavailable")
	}
	for rows.Next() {
		var path string
		var updated time.Time
		if rows.Scan(&path, &updated) != nil {
			rows.Close()
			return errors.New("discovery_state_invalid")
		}
		known[key(path, updated)] = true
		if len(known) > 200000 {
			rows.Close()
			return errors.New("discovery_state_budget")
		}
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return errors.New("database_unavailable")
	}
	headers := map[string]string{}
	var cachedKey, etag, modified, cachedSHA string
	if a.db.QueryRow(ctx, "SELECT r.object_key,c.etag,c.modified,r.sha256 FROM argo_index_cache c JOIN raw_artifacts r ON r.artifact_id=c.artifact_id WHERE c.scope=$1", a.cfg.SourceID).Scan(&cachedKey, &etag, &modified, &cachedSHA) != nil {
		headers = map[string]string{}
	} else {
		headers["If-None-Match"] = etag
		headers["If-Modified-Since"] = modified
	}
	data, h, status, err := a.fetch(ctx, a.cfg.IndexURL, headers)
	if err != nil {
		return err
	}
	if status == 304 {
		obj, e := a.s3.GetObject(ctx, "nautiq", cachedKey, minio.GetObjectOptions{})
		if e != nil {
			return errors.New("index_cache_unavailable")
		}
		data, err = io.ReadAll(io.LimitReader(obj, a.cfg.MaxBytes+1))
		obj.Close()
		if err != nil || int64(len(data)) > a.cfg.MaxBytes || sha(data) != cachedSHA {
			return errors.New("index_cache_invalid")
		}
	}
	if _, err := a.db.Exec(ctx, "UPDATE ingestion_runs SET upstream_checked_at=now() WHERE run_id=$1", run); err != nil {
		return errors.New("fetch_registration_failed")
	}
	indexSHA := sha(data)
	if status == 200 {
		id, e := a.register(ctx, run, Candidate{Path: "ar_index_global_prof.txt.gz", Updated: time.Now().UTC()}, "index", data, h)
		if e != nil {
			return errors.New("index_registration_failed")
		}
		_, e = a.db.Exec(ctx, "INSERT INTO argo_index_cache(scope,artifact_id,etag,modified) VALUES($1,$2,$3,$4) ON CONFLICT(scope) DO UPDATE SET artifact_id=excluded.artifact_id,etag=excluded.etag,modified=excluded.modified", a.cfg.SourceID, id, h.Get("ETag"), h.Get("Last-Modified"))
		if e != nil {
			return errors.New("index_registration_failed")
		}
	}
	candidates, invalid, err := a.discover(data, known, cutoff)
	if err != nil {
		return err
	}
	if len(candidates) > a.cfg.MaxProfiles {
		candidates = candidates[:a.cfg.MaxProfiles]
	}
	for _, c := range candidates {
		if _, err := a.db.Exec(ctx, `INSERT INTO argo_discoveries(scope,source_path,source_updated_at) VALUES($1,$2,$3) ON CONFLICT DO NOTHING`, a.scope, c.Path, c.Updated); err != nil {
			return errors.New("discovery_registration_failed")
		}
	}
	var wg sync.WaitGroup
	var downloaded, quarantined atomic.Int32
	slots := make(chan struct{}, a.cfg.Workers)
	errs := make(chan error, len(candidates))
	for _, c := range candidates {
		wg.Go(func() {
			select {
			case slots <- struct{}{}:
			case <-ctx.Done():
				errs <- ctx.Err()
				return
			}
			defer func() { <-slots }()
			bytes, h, _, e := a.fetch(ctx, a.cfg.BaseURL+c.Path, nil)
			if e != nil {
				if e.Error() == "provider_http_404" || e.Error() == "provider_http_410" {
					_, err := a.db.Exec(ctx, `UPDATE argo_discoveries SET status='quarantined',reason_code=$4 WHERE scope=$1 AND source_path=$2 AND source_updated_at=$3`, a.scope, c.Path, c.Updated, e.Error())
					if err != nil {
						errs <- errors.New("discovery_quarantine_failed")
					} else {
						quarantined.Add(1)
					}
					return
				}
				errs <- e
				return
			} // Transport failures stay pending; cursor cannot pass them.
			if _, e = a.register(ctx, run, c, "profile", bytes, h); e != nil {
				errs <- errors.New("raw_registration_failed")
			} else {
				downloaded.Add(1)
			}
		})
	}
	wg.Wait()
	close(errs)
	if len(errs) > 0 {
		return errors.New("downloads_pending_retry")
	}
	if len(candidates) > 0 {
		last := candidates[len(candidates)-1]
		_, err = a.db.Exec(ctx, `INSERT INTO ingestion_cursors(scope,updated_at,source_path,index_sha256) VALUES($1,$2,$3,$4) ON CONFLICT(scope) DO UPDATE SET updated_at=CASE WHEN (excluded.updated_at,excluded.source_path)>(ingestion_cursors.updated_at,ingestion_cursors.source_path) THEN excluded.updated_at ELSE ingestion_cursors.updated_at END,source_path=CASE WHEN (excluded.updated_at,excluded.source_path)>(ingestion_cursors.updated_at,ingestion_cursors.source_path) THEN excluded.source_path ELSE ingestion_cursors.source_path END,index_sha256=excluded.index_sha256,checked_at=now()`, a.scope, last.Updated, last.Path, indexSHA)
		if err != nil {
			return errors.New("cursor_commit_failed")
		}
	}
	counts, _ := json.Marshal(map[string]any{"downloaded": downloaded.Load(), "quarantined": quarantined.Load(), "invalid_index_rows": invalid, "index_sha256": indexSHA, "reconciliation": full})
	a.db.Exec(ctx, "UPDATE ingestion_runs SET counters=$2 WHERE run_id=$1", run, counts)
	slog.Info("Argo ingestion complete", "downloaded", len(candidates), "invalid_index_rows", invalid)
	return nil
}

func (a *App) discover(data []byte, known map[string]bool, cutoff time.Time) ([]Candidate, int, error) {
	gz, err := gzip.NewReader(bytes.NewReader(data))
	if err != nil {
		return nil, 0, errors.New("invalid_index_gzip")
	}
	defer gz.Close()
	// Read bounded individual lines before CSV parsing to prevent giant-line allocation.
	reader := &boundedLines{r: gz, max: a.cfg.MaxLine, total: a.cfg.MaxExpanded}
	csvReader := csv.NewReader(reader)
	csvReader.Comment = '#'
	csvReader.FieldsPerRecord = -1
	header, err := csvReader.Read()
	if err != nil || strings.Join(header, ",") != "file,date,latitude,longitude,ocean,profiler_type,institution,date_update" {
		return nil, 0, errors.New("index_schema_changed")
	}
	selected := &Candidates{}
	heap.Init(selected)
	invalid := 0
	for {
		row, e := csvReader.Read()
		if e == io.EOF {
			break
		}
		if e != nil {
			return nil, invalid, errors.New("index_read_budget_or_corruption")
		}
		if len(row) != 8 {
			invalid++
			continue
		}
		lat, e1 := strconv.ParseFloat(row[2], 64)
		lon, e2 := strconv.ParseFloat(row[3], 64)
		observed, e3 := time.Parse("20060102150405", row[1])
		updated, e4 := time.Parse("20060102150405", row[7])
		if e1 != nil || e2 != nil || e3 != nil || e4 != nil || !safePath.MatchString(row[0]) || math.IsNaN(lat) || math.IsNaN(lon) || math.IsInf(lat, 0) || math.IsInf(lon, 0) || lat < -90 || lat > 90 || lon < -180 || lon > 180 {
			invalid++
			continue
		}
		if lat < a.cfg.Domain.South || lat > a.cfg.Domain.North || lon < a.cfg.Domain.West || lon > a.cfg.Domain.East || observed.Before(a.observedSince) || updated.Before(cutoff) || known[key(row[0], updated)] {
			continue
		}
		c := Candidate{row[0], updated}
		if selected.Len() < a.cfg.MaxCandidates {
			heap.Push(selected, c)
		} else if less(c, (*selected)[0]) {
			heap.Pop(selected)
			heap.Push(selected, c)
		}
	}
	result := []Candidate(*selected)
	sort.Slice(result, func(i, j int) bool { return less(result[i], result[j]) })
	return result, invalid, nil
}

type boundedLines struct {
	r     io.Reader
	max   int
	total int64
	line  int
}

func (b *boundedLines) Read(p []byte) (int, error) {
	n, e := b.r.Read(p)
	b.total -= int64(n)
	if b.total < 0 {
		return 0, errors.New("index_expansion_budget")
	}
	for _, v := range p[:n] {
		if v == '\n' {
			b.line = 0
		} else {
			b.line++
			if b.line > b.max {
				return 0, errors.New("index_line_budget")
			}
		}
	}
	return n, e
}

func (a *App) dispatch(ctx context.Context) error {
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	nc, err := nats.Connect(os.Getenv("NATS_URL"), nats.Timeout(3*time.Second), nats.NoReconnect())
	if err != nil {
		return err
	}
	defer nc.Close()
	js, err := jetstream.New(nc)
	if err != nil {
		return err
	}
	_, err = js.CreateOrUpdateStream(ctx, jetstream.StreamConfig{Name: "ARGO", Subjects: []string{"raw.received", "profile.ready", "profile.revised"}, Storage: jetstream.FileStorage, MaxAge: 7 * 24 * time.Hour, MaxBytes: 256 << 20, Discard: jetstream.DiscardNew})
	if err != nil {
		return err
	}
	_, err = js.CreateOrUpdateStream(ctx, jetstream.StreamConfig{Name: "FIELDS", Subjects: []string{"field.ready"}, Storage: jetstream.FileStorage, MaxAge: 7 * 24 * time.Hour, MaxBytes: 32 << 20, Discard: jetstream.DiscardNew})
	if err != nil {
		return err
	}
	_, err = js.CreateOrUpdateStream(ctx, jetstream.StreamConfig{Name: "REGIONAL_EVENTS", Subjects: []string{"regional.event.ready"}, Storage: jetstream.FileStorage, MaxAge: 7 * 24 * time.Hour, MaxBytes: 32 << 20, Discard: jetstream.DiscardNew})
	if err != nil {
		return err
	}
	_, err = js.CreateOrUpdateStream(ctx, jetstream.StreamConfig{Name: "OFFICIAL_ADVISORIES", Subjects: []string{"advisory.feed.checked"}, Storage: jetstream.FileStorage, MaxAge: 7 * 24 * time.Hour, MaxBytes: 32 << 20, Discard: jetstream.DiscardNew})
	if err != nil {
		return err
	}

	leaseToken := uuid.NewString()
	rows, err := a.db.Query(ctx, `WITH claimed AS (SELECT event_id FROM event_outbox WHERE published_at IS NULL AND next_attempt_at<=now() AND (lease_until IS NULL OR lease_until<now()) ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 5) UPDATE event_outbox e SET lease_until=now()+interval '30 seconds',lease_token=$1,attempts=attempts+1 FROM claimed c WHERE e.event_id=c.event_id RETURNING e.event_id::text,e.event_type,e.schema_version,e.aggregate_key,e.revision_sha256,e.payload,e.created_at`, leaseToken)
	if err != nil {
		return err
	}
	type event struct {
		EventID  string          `json:"event_id"`
		Type     string          `json:"event_type"`
		Schema   int             `json:"schema_version"`
		Key      string          `json:"aggregate_key"`
		Revision string          `json:"revision_sha256"`
		Payload  json.RawMessage `json:"payload"`
		Created  time.Time       `json:"created_at"`
	}
	var events []event
	for rows.Next() {
		var e event
		if err := rows.Scan(&e.EventID, &e.Type, &e.Schema, &e.Key, &e.Revision, &e.Payload, &e.Created); err != nil {
			rows.Close()
			return err
		}
		events = append(events, e)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return err
	}
	for _, e := range events {
		body, _ := json.Marshal(e)
		pub, cancel := context.WithTimeout(ctx, 5*time.Second)
		_, err := js.Publish(pub, e.Type, body, jetstream.WithMsgID(e.EventID))
		cancel()
		if err != nil {
			a.db.Exec(ctx, "UPDATE event_outbox SET lease_until=NULL,next_attempt_at=now()+least(attempts,60)*interval '1 second' WHERE event_id=$1 AND lease_token=$2 AND published_at IS NULL", e.EventID, leaseToken)
			return err
		}
		if _, err := a.db.Exec(ctx, "UPDATE event_outbox SET published_at=now(),lease_until=NULL WHERE event_id=$1 AND lease_token=$2", e.EventID, leaseToken); err != nil {
			return err
		}
	}
	return nil
}
