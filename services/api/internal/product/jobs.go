package product

import (
	"context"
	"encoding/json"
	"errors"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/minio/minio-go/v7"
	"io"
	"net/http"
	"reflect"
	"strconv"
	"strings"
	"time"
)

type JobInput struct {
	Scope    string          `json:"scope"`
	TargetID string          `json:"target_id,omitempty"`
	Format   string          `json:"format"`
	Query    *ResearchFilter `json:"query,omitempty"`
	Place    string          `json:"place,omitempty"`
}
type Job struct {
	ID       string          `json:"id"`
	Kind     string          `json:"kind"`
	Format   string          `json:"format"`
	State    string          `json:"state"`
	Reason   *string         `json:"reason"`
	Version  int64           `json:"version"`
	Input    json.RawMessage `json:"input"`
	InputSHA string          `json:"input_sha256"`
	SHA      *string         `json:"artifact_sha256"`
	Bytes    *int64          `json:"artifact_bytes"`
	Created  time.Time       `json:"created_at"`
	Finished *time.Time      `json:"finished_at"`
	Expires  time.Time       `json:"expires_at"`
}

const jobColumns = `job_id::text,kind,format,CASE WHEN expires_at<=now() AND state NOT IN ('blocked','cancelled','failed') THEN 'expired' ELSE state END,reason,version,input,input_sha256,artifact_sha256,artifact_bytes,created_at,finished_at,expires_at`

func scanJob(row pgx.Row) (Job, error) {
	var v Job
	e := row.Scan(&v.ID, &v.Kind, &v.Format, &v.State, &v.Reason, &v.Version, &v.Input, &v.InputSHA, &v.SHA, &v.Bytes, &v.Created, &v.Finished, &v.Expires)
	return v, e
}
func (s *Server) jobs(w http.ResponseWriter, r *http.Request, u Identity) {
	limit, after, ok := page(w, r)
	if !ok {
		return
	}
	rows, e := s.DB.Query(r.Context(), `SELECT `+strings.Replace(jobColumns, ",input,", ",(input-'observations'-'owned_object'-'owned_route'-'references'),", 1)+` FROM product_jobs WHERE owner_id=$1 AND kind=$2 AND ($3='' OR job_id::text>$3) ORDER BY job_id LIMIT $4`, u.ID, routeKind(r), after, limit+1)
	if e != nil {
		fail(w, 503, "job_catalog_unavailable")
		return
	}
	defer rows.Close()
	items := []Job{}
	for rows.Next() {
		v, e := scanJob(rows)
		if e != nil {
			fail(w, 503, "job_catalog_unavailable")
			return
		}
		items = append(items, v)
		var summary map[string]any
		if json.Unmarshal(v.Input, &summary) != nil {
			fail(w, 503, "job_input_integrity")
			return
		}
		delete(summary, "observations")
		delete(summary, "owned_object")
		delete(summary, "owned_route")
		delete(summary, "references")
		items[len(items)-1].Input = JSON(summary)
	}
	if rows.Err() != nil {
		fail(w, 503, "job_catalog_unavailable")
		return
	}
	var next *string
	if len(items) > limit {
		items = items[:limit]
		next = &items[len(items)-1].ID
	}
	write(w, 200, map[string]any{"items": items, "next_cursor": next})
}
func (s *Server) job(w http.ResponseWriter, r *http.Request, u Identity) {
	if !noQuery(w, r) {
		return
	}
	if !identifier(r.PathValue("id")) {
		fail(w, 404, "not_found")
		return
	}
	v, e := scanJob(s.DB.QueryRow(r.Context(), `SELECT `+jobColumns+` FROM product_jobs WHERE job_id=$1 AND owner_id=$2 AND kind=$3`, r.PathValue("id"), u.ID, routeKind(r)))
	if missing(e) {
		fail(w, 404, "not_found")
		return
	}
	if e != nil {
		fail(w, 503, "job_unavailable")
		return
	}
	var raw []byte
	if s.DB.QueryRow(r.Context(), `SELECT input_bytes FROM product_jobs WHERE job_id=$1 AND owner_id=$2`, v.ID, u.ID).Scan(&raw) != nil {
		fail(w, 503, "job_input_integrity")
		return
	}
	var frozen, projection any
	if Hash(raw) != v.InputSHA || json.Unmarshal(raw, &frozen) != nil || json.Unmarshal(v.Input, &projection) != nil || !reflect.DeepEqual(frozen, projection) {
		fail(w, 503, "job_input_integrity")
		return
	}
	write(w, 200, v)
}
func (s *Server) snapshot(r *http.Request, tx pgx.Tx, u Identity, v JobInput, rawResearch bool) (map[string]any, error) {
	out := map[string]any{"schema_version": 1, "method_version": "private-provenance-report-v1", "generated_at": time.Now().UTC(), "scope": v.Scope, "target_id": v.TargetID, "source_list": []any{}, "calculation_ids": []string{}, "valid_data_times": []string{}, "limitations": []string{"Frozen historical snapshot; generated time does not renew source freshness.", "Source measurements and original advisory content are withheld pending redistribution review."}}
	switch v.Scope {
	case "route", "watchlist":
		kind := "routes"
		if v.Scope == "watchlist" {
			kind = "watchlists"
		}
		if !identifier(v.TargetID) {
			return nil, refusal{404, "not_found"}
		}
		obj, e := scanObject(tx.QueryRow(r.Context(), `SELECT `+objectColumns+` FROM product_objects WHERE object_id=$1 AND owner_id=$2 AND kind=$3 AND deleted_at IS NULL`, v.TargetID, u.ID, kind))
		if missing(e) {
			return nil, refusal{404, "not_found"}
		}
		if e != nil {
			return nil, e
		}
		out["owned_object"] = obj
		if kind == "routes" {
			var req struct {
				Waypoints []struct {
					Time string `json:"time"`
				} `json:"waypoints"`
				Threshold string `json:"threshold_version"`
			}
			if json.Unmarshal(obj.Data, &req) != nil {
				return nil, errors.New("route_snapshot_integrity")
			}
			times := []string{}
			for _, p := range req.Waypoints {
				times = append(times, p.Time)
			}
			out["valid_data_times"] = times
			out["threshold_version"] = req.Threshold
			out["assessment"] = "not_assessed"
		}
	case "trip":
		if !identifier(v.TargetID) {
			return nil, refusal{404, "not_found"}
		}
		var found string
		e := tx.QueryRow(r.Context(), `SELECT calculation_id::text FROM product_trip_links WHERE calculation_id=$1 AND owner_id=$2`, v.TargetID, u.ID).Scan(&found)
		if missing(e) {
			return nil, refusal{404, "not_found"}
		}
		if e != nil {
			return nil, e
		}
		data, e := s.receipt(r, v.TargetID)
		if e != nil {
			return nil, e
		}
		var receipt struct {
			Input struct {
				Request json.RawMessage `json:"request"`
			} `json:"input"`
			Output struct {
				Status      string            `json:"status"`
				AsOf        string            `json:"as_of"`
				Method      string            `json:"method_version"`
				Threshold   string            `json:"threshold_version"`
				Cycles      []json.RawMessage `json:"source_cycles"`
				Limitations []string          `json:"limitations"`
				Wording     string            `json:"wording"`
			} `json:"output"`
		}
		if json.Unmarshal(data, &receipt) != nil {
			return nil, errors.New("trip_report_integrity")
		}
		out["owned_route"] = receipt.Input.Request
		out["status"] = receipt.Output.Status
		out["wording"] = receipt.Output.Wording
		out["source_list"] = receipt.Output.Cycles
		out["calculation_ids"] = []string{v.TargetID}
		out["valid_data_times"] = []string{receipt.Output.AsOf}
		out["trip_method_version"] = receipt.Output.Method
		out["threshold_version"] = receipt.Output.Threshold
		out["trip_limitations"] = receipt.Output.Limitations
		out["receipt_sha256"] = Hash(data)
	case "research":
		if rawResearch && !Catalog().ExportPermissions["source_profile_rows"] {
			return nil, refusal{422, "source_redistribution_unreviewed"}
		}
		if v.Query == nil || v.Query.Validate() != nil || v.Query.Cursor != "" {
			return nil, refusal{400, "valid_research_query_required"}
		}
		if len(v.Query.Polygon) > 0 {
			var valid bool
			geo := JSON(map[string]any{"type": "Polygon", "coordinates": [][][]float64{v.Query.Polygon}})
			if e := tx.QueryRow(r.Context(), `SELECT ST_IsValid(g) AND ST_Area(g::geography)<=1e12 FROM (SELECT ST_SetSRID(ST_GeomFromGeoJSON($1),4326) g) v`, string(geo)).Scan(&valid); e != nil || !valid {
				return nil, refusal{400, "invalid_research_polygon"}
			}
		}
		rows, e := ResearchRows(r.Context(), tx, *v.Query)
		if e != nil {
			return nil, e
		}
		if len(rows) > v.Query.Limit {
			return nil, refusal{422, "refine_research_before_export"}
		}
		refs := []map[string]any{}
		for _, row := range rows {
			refs = append(refs, map[string]any{"profile_id": row.ID, "revision_sha256": row.Revision, "calculation_id": row.Calculation, "source_id": row.Source, "observed_at": row.Observed})
		}
		out["query"] = v.Query
		out["references"] = refs
		out["valid_data_times"] = []string{v.Query.Start, v.Query.End}
		out["source_list"] = []string{"argo_gdac"}
		out["provenance_only"] = true
		out["attribution"] = "International Argo Program and contributing national programmes; part of the Global Ocean Observing System. Argo GDAC DOI: 10.17882/42182."
		out["terms_url"] = "https://argo.ucsd.edu/data/acknowledging-argo/"
		if rawResearch {
			out["limitations"] = []string{"Original QC-accepted Argo levels at recorded instrument positions, times and depths; no spatial interpolation.", "Scientific promotion and operational anomaly alerts remain unapproved.", "Frozen selection; generation time does not renew observation freshness."}
			observations := []map[string]any{}
			count := 0
			for _, row := range rows {
				var levels []byte
				e = tx.QueryRow(r.Context(), `SELECT COALESCE(jsonb_agg(level ORDER BY (level->>'depth_m')::float8),'[]') FROM profile_revisions r,jsonb_array_elements(r.levels) level WHERE r.profile_id=$1 AND r.revision_sha256=$2 AND (level->>'depth_m')::float8 BETWEEN $3 AND $4 AND level->>$5 IS NOT NULL`, row.ID, row.Revision, v.Query.MinDepth, v.Query.MaxDepth, v.Query.Variable).Scan(&levels)
				if e != nil {
					return nil, e
				}
				var parsed []map[string]any
				if json.Unmarshal(levels, &parsed) != nil {
					return nil, errors.New("research_level_integrity")
				}
				count += len(parsed)
				if count > 10000 {
					return nil, refusal{422, "research_export_row_budget"}
				}
				observations = append(observations, map[string]any{"profile_id": row.ID, "revision_sha256": row.Revision, "raw_sha256": row.RawSHA, "source_url": row.SourceURL, "platform_id": row.Platform, "observed_at": row.Observed, "received_at": row.Received, "latitude": row.Latitude, "longitude": row.Longitude, "data_mode": row.Mode, "qc_version": row.QC, "source_id": row.Source, "levels": parsed})
			}
			out["observations"] = observations
			out["row_count"] = count
			out["provenance_only"] = false
			out["method_version"] = "bounded-original-levels-export-v1"
		}
	case "location":
		var found *Location
		for _, p := range Catalog().Locations {
			if p.Slug == v.Place {
				copy := p
				found = &copy
			}
		}
		if found == nil {
			return nil, refusal{400, "unknown_place"}
		}
		out["place"] = found
		out["provenance_only"] = true
		rows, e := tx.Query(r.Context(), `SELECT json_build_object('release_id',f.release_id,'product_id',f.product_id,'cycle',f.cycle,'valid_time_start',f.valid_time_start,'valid_time_end',f.valid_time_end,'manifest_sha256',f.manifest_sha256,'calculation_id',f.calculation_id),f.manifest_key,f.manifest_sha256,f.manifest FROM field_selection s JOIN field_releases f USING(release_id) ORDER BY f.product_id LIMIT 8`)
		if e != nil {
			return nil, e
		}
		type pin struct {
			ref      json.RawMessage
			key, sha string
			mirror   []byte
		}
		pins := []pin{}
		for rows.Next() {
			var p pin
			if e = rows.Scan(&p.ref, &p.key, &p.sha, &p.mirror); e != nil {
				rows.Close()
				return nil, e
			}
			pins = append(pins, p)
		}
		e = rows.Err()
		rows.Close()
		if e != nil {
			return nil, e
		}
		refs := []json.RawMessage{}
		for _, p := range pins {
			if _, e = s.frozen(r.Context(), p.key, p.sha, p.mirror, 4194304); e != nil {
				return nil, e
			}
			refs = append(refs, p.ref)
		}
		out["source_list"] = refs
	case "event":
		if !identifier(v.TargetID) {
			return nil, refusal{404, "not_found"}
		}
		var refs, mirror []byte
		var key, sha string
		e := tx.QueryRow(r.Context(), `SELECT json_build_object('event_id',e.event_id,'run_id',e.run_id,'start',e.start_day,'end',e.end_day,'report_sha256',r.report_sha256,'calculation_id',r.calculation_id),r.report_key,r.report_sha256,r.report FROM regional_events e JOIN event_runs r USING(run_id) WHERE event_id=$1`, v.TargetID).Scan(&refs, &key, &sha, &mirror)
		if missing(e) {
			return nil, refusal{404, "not_found"}
		}
		if e != nil {
			return nil, e
		}
		frozen, e := s.frozen(r.Context(), key, sha, mirror, 16*1024*1024)
		if e != nil {
			return nil, e
		}
		var index map[string]any
		if json.Unmarshal(refs, &index) != nil {
			return nil, errors.New("event_report_integrity")
		}
		found := false
		if list, ok := frozen["events"].([]any); ok {
			for _, v := range list {
				item, ok := v.(map[string]any)
				if ok && item["event_id"] == index["event_id"] {
					found = item["start"] == index["start"] && item["end"] == index["end"]
					break
				}
			}
		}
		if !found {
			return nil, errors.New("event_report_projection_integrity")
		}
		out["references"] = json.RawMessage(refs)
		out["provenance_only"] = true
	default:
		return nil, refusal{400, "unsupported_report_scope"}
	}
	return out, nil
}
func (s *Server) frozen(ctx context.Context, key, sha string, mirror []byte, limit int64) (map[string]any, error) {
	if s.Storage == nil {
		return nil, errors.New("source_store_unavailable")
	}
	obj, e := s.Storage.GetObject(ctx, "nautiq", key, minio.GetObjectOptions{})
	if e != nil {
		return nil, e
	}
	defer obj.Close()
	raw, e := io.ReadAll(io.LimitReader(obj, limit+1))
	var value, sql map[string]any
	if e != nil || int64(len(raw)) > limit || Hash(raw) != sha || json.Unmarshal(raw, &value) != nil || json.Unmarshal(mirror, &sql) != nil || !reflect.DeepEqual(value, sql) {
		return nil, errors.New("report_source_integrity")
	}
	return value, nil
}
func (s *Server) createJob(w http.ResponseWriter, r *http.Request, u Identity) {
	var v JobInput
	if !body(w, r, &v) {
		return
	}
	kind := routeKind(r)
	validFormat := v.Format == "json" || kind == "reports" && v.Format == "html" || kind == "exports" && (v.Format == "csv" || v.Format == "parquet" || v.Format == "netcdf")
	if !validFormat {
		fail(w, 400, "unsupported_format")
		return
	}
	s.mutation(w, r, u, v, func(tx pgx.Tx) (int, any, error) {
		var count int
		e := tx.QueryRow(r.Context(), `SELECT count(*) FROM product_jobs WHERE owner_id=$1 AND created_at>now()-interval '24 hours'`, u.ID).Scan(&count)
		if e != nil {
			return 0, nil, e
		}
		if count >= 20 {
			return 0, nil, refusal{422, "job_quota"}
		}
		snapshot, e := s.snapshot(r, tx, u, v, kind == "exports" && v.Scope == "research")
		if e != nil {
			return 0, nil, e
		}
		state := "queued"
		var reason *string
		if v.Format == "netcdf" && v.Scope != "research" {
			state = "blocked"
			code := "netcdf_requires_scientifically_appropriate_licensed_source"
			reason = &code
		} else if kind == "exports" && v.Scope != "route" && v.Scope != "watchlist" && v.Scope != "research" {
			state = "blocked"
			code := "source_redistribution_unreviewed"
			reason = &code
		}
		snapshot["product_policy_sha256"] = Hash(PolicyJSON)
		raw := JSON(snapshot)
		if len(raw) > 4194304 {
			return 0, nil, refusal{422, "snapshot_byte_budget"}
		}
		job, e := scanJob(tx.QueryRow(r.Context(), `INSERT INTO product_jobs(job_id,owner_id,kind,format,state,input,input_bytes,input_sha256,reason) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING `+jobColumns, uuid.NewString(), u.ID, kind, v.Format, state, raw, raw, Hash(raw), reason))
		return 202, job, e
	})
}
func (s *Server) cancelJob(w http.ResponseWriter, r *http.Request, u Identity) {
	if r.ContentLength > 0 || !identifier(r.PathValue("id")) {
		fail(w, 400, "invalid_cancel")
		return
	}
	s.mutation(w, r, u, nil, func(tx pgx.Tx) (int, any, error) {
		old, e := scanJob(tx.QueryRow(r.Context(), `SELECT `+jobColumns+` FROM product_jobs WHERE job_id=$1 AND owner_id=$2 AND kind=$3`, r.PathValue("id"), u.ID, routeKind(r)))
		if missing(e) {
			return 0, nil, refusal{404, "not_found"}
		}
		if e != nil {
			return 0, nil, e
		}
		if r.Header.Get("If-Match") == "" {
			return 0, nil, refusal{428, "version_required"}
		}
		if r.Header.Get("If-Match") != strconv.Quote(strconv.FormatInt(old.Version, 10)) {
			return 0, nil, refusal{409, "version_conflict"}
		}
		if old.State != "queued" && old.State != "running" {
			return 0, nil, refusal{409, "job_not_cancellable"}
		}
		job, e := scanJob(tx.QueryRow(r.Context(), `UPDATE product_jobs SET state='cancelled',version=version+1,lease_id=NULL,lease_expires_at=NULL,finished_at=now() WHERE job_id=$1 AND owner_id=$2 RETURNING `+jobColumns, old.ID, u.ID))
		return 200, job, e
	})
}
func (s *Server) grant(w http.ResponseWriter, r *http.Request, u Identity) {
	if r.ContentLength > 0 || !identifier(r.PathValue("id")) {
		fail(w, 400, "invalid_download_request")
		return
	}
	s.mutation(w, r, u, nil, func(tx pgx.Tx) (int, any, error) {
		var id string
		e := tx.QueryRow(r.Context(), `SELECT job_id::text FROM product_jobs WHERE job_id=$1 AND owner_id=$2 AND kind=$3 AND state='ready' AND expires_at>now()`, r.PathValue("id"), u.ID, routeKind(r)).Scan(&id)
		if missing(e) {
			return 0, nil, refusal{404, "download_unavailable"}
		}
		if e != nil {
			return 0, nil, e
		}
		var count int
		e = tx.QueryRow(r.Context(), `SELECT count(*) FROM product_download_grants WHERE owner_id=$1 AND expires_at>now()`, u.ID).Scan(&count)
		if e != nil {
			return 0, nil, e
		}
		if count >= 20 {
			return 0, nil, refusal{422, "download_grant_quota"}
		}
		gid := uuid.NewString()
		expiry := time.Now().UTC().Add(5 * time.Minute)
		_, e = tx.Exec(r.Context(), `INSERT INTO product_download_grants(grant_id,job_id,owner_id,expires_at) VALUES($1,$2,$3,$4)`, gid, id, u.ID, expiry)
		return 201, map[string]any{"grant_id": gid, "expires_at": expiry, "path": "/" + routeKind(r) + "/" + id + "/download?grant=" + gid, "single_use": true, "session_required": true}, e
	})
}
func (s *Server) download(w http.ResponseWriter, r *http.Request, u Identity) {
	q := r.URL.Query()
	if len(q) != 1 || !identifier(q.Get("grant")) || !identifier(r.PathValue("id")) {
		fail(w, 404, "download_unavailable")
		return
	}
	var key, sha, format string
	var size int64
	e := s.DB.QueryRow(r.Context(), `SELECT j.object_key,j.artifact_sha256,j.artifact_bytes,j.format FROM product_jobs j JOIN product_download_grants g USING(job_id,owner_id) WHERE j.job_id=$1 AND j.owner_id=$2 AND j.kind=$3 AND j.state='ready' AND j.expires_at>now() AND g.grant_id=$4 AND g.expires_at>now() AND g.used_at IS NULL`, r.PathValue("id"), u.ID, routeKind(r), q.Get("grant")).Scan(&key, &sha, &size, &format)
	if e != nil {
		fail(w, 404, "download_unavailable")
		return
	}
	if size < 1 || size > 8388608 {
		fail(w, 503, "artifact_integrity")
		return
	}
	obj, e := s.Storage.GetObject(r.Context(), "nautiq", key, minio.GetObjectOptions{})
	if e != nil {
		fail(w, 503, "artifact_unavailable")
		return
	}
	defer obj.Close()
	data, e := io.ReadAll(io.LimitReader(obj, size+1))
	if e != nil || int64(len(data)) != size || Hash(data) != sha {
		fail(w, 503, "artifact_integrity")
		return
	}
	tag, e := s.DB.Exec(r.Context(), `UPDATE product_download_grants g SET used_at=now() WHERE grant_id=$1 AND owner_id=$2 AND used_at IS NULL AND expires_at>now() AND EXISTS(SELECT 1 FROM product_jobs j WHERE j.job_id=g.job_id AND j.owner_id=g.owner_id AND j.state='ready' AND j.expires_at>now())`, q.Get("grant"), u.ID)
	if e != nil {
		fail(w, 503, "download_unavailable")
		return
	}
	if tag.RowsAffected() != 1 {
		fail(w, 404, "download_unavailable")
		return
	}
	types := map[string]string{"json": "application/json", "html": "text/html; charset=utf-8", "csv": "text/csv; charset=utf-8", "parquet": "application/vnd.apache.parquet", "netcdf": "application/x-netcdf"}
	w.Header().Set("Content-Type", types[format])
	w.Header().Set("Cache-Control", "private, no-store")
	w.Header().Set("Referrer-Policy", "no-referrer")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.Header().Set("Content-Security-Policy", "sandbox; default-src 'none'; style-src 'unsafe-inline'")
	w.Header().Set("Content-Disposition", "attachment; filename=\"nautiq-"+r.PathValue("id")+"."+format+"\"")
	w.Header().Set("X-Artifact-SHA256", sha)
	w.Header().Set("Content-Length", strconv.Itoa(len(data)))
	w.Write(data)
}
