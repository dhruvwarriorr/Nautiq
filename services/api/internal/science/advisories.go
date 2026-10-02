package science

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"github.com/minio/minio-go/v7"
	"io"
	"net/http"
	"reflect"
	"strconv"
	"time"

	"nautiq.local/api/internal/advisories"
)

// Load a bounded, repeatable snapshot and verify lake bytes before interpreting official messages.
// No source or parser failure is represented as an empty, healthy feed.
func (s *Server) advisorySnapshot(r *http.Request) (advisories.Snapshot, error) {
	out := advisories.Snapshot{AsOf: time.Now().UTC(), Sources: []advisories.Source{}, Items: []advisories.Bulletin{}, Issues: []string{}}
	select {
	case s.downloads <- struct{}{}:
		defer func() { <-s.downloads }()
	default:
		return out, errors.New("advisory_integrity_capacity")
	}
	tx, err := s.DB.Begin(r.Context())
	if err != nil {
		return out, err
	}
	defer tx.Rollback(r.Context())
	if _, err = tx.Exec(r.Context(), "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"); err != nil {
		return out, err
	}
	rows, err := tx.Query(r.Context(), `SELECT s.source_id,s.policy,s.transport,s.checked_at,s.latest_run_id::text,COALESCE(u.integrity,'unavailable'),s.reasons FROM advisory_sources s LEFT JOIN advisory_runs u ON u.run_id=s.latest_run_id ORDER BY s.source_id`)
	if err != nil {
		return out, err
	}
	for rows.Next() {
		var src advisories.Source
		if err = rows.Scan(&src.ID, &src.Policy, &src.Transport, &src.CheckedAt, &src.RunID, &src.Integrity, &src.Reasons); err != nil {
			rows.Close()
			return out, err
		}
		src.Coverage = "unverified"
		var p struct {
			Required bool  `json:"required"`
			Marine   bool  `json:"marine_coverage_verified"`
			Cadence  bool  `json:"cadence_verified"`
			Rights   bool  `json:"redistribution_reviewed"`
			MaxAge   int64 `json:"transport_max_age_seconds"`
		}
		if json.Unmarshal(src.Policy, &p) != nil {
			return out, errors.New("source_policy")
		}
		if src.CheckedAt != nil {
			age := int64(out.AsOf.Sub(*src.CheckedAt).Seconds())
			src.AgeSeconds = &age
			if age < 0 || age > p.MaxAge {
				src.Transport = "stale"
			}
		}
		if src.RunID == nil {
			src.Coverage = "unconfigured"
		} else if src.Transport != "healthy" || src.Integrity != "ready" {
			src.Coverage = "stale_or_incomplete"
		} else if p.Marine && p.Cadence && p.Rights {
			src.Coverage = "verified_complete"
		}
		out.Sources = append(out.Sources, src)
	}
	if rows.Err() != nil {
		return out, rows.Err()
	}
	rows.Close()
	if len(out.Sources) == 0 {
		out.Issues = append(out.Issues, "source_catalog_uninitialized")
	}
	rows, err = tx.Query(r.Context(), `SELECT document,raw_sha256,first_run_id::text,raw_key,raw_bytes FROM advisory_revisions ORDER BY sent,revision_id LIMIT 4001`)
	if err != nil {
		return out, err
	}
	type pin struct {
		b    advisories.Bulletin
		key  string
		size int64
	}
	pins := []pin{}
	for rows.Next() {
		var p pin
		var data []byte
		if err = rows.Scan(&data, &p.b.RawSHA, &p.b.FirstRunID, &p.key, &p.size); err != nil {
			rows.Close()
			return out, err
		}
		if json.Unmarshal(data, &p.b.Message) != nil {
			return out, errors.New("advisory_document")
		}
		pins = append(pins, p)
	}
	if rows.Err() != nil {
		return out, rows.Err()
	}
	rows.Close()
	if len(pins) > 4000 {
		return out, errors.New("advisory_snapshot_budget")
	}
	runIDs := map[string]bool{}
	for _, src := range out.Sources {
		if src.RunID != nil {
			runIDs[*src.RunID] = true
		}
	}
	for _, p := range pins {
		runIDs[p.b.FirstRunID] = true
	}
	if len(runIDs) > 64 {
		return out, errors.New("advisory_ancestry_budget")
	}
	documents := map[string]json.RawMessage{}
	urls := map[string]string{}
	var total int64
	verifiedRaw := map[string]bool{}
	for id := range runIDs {
		var data []byte
		var key, sha, calcKey, calcSHA string
		if err = tx.QueryRow(r.Context(), `SELECT u.report,u.report_key,u.report_sha256,c.manifest_key,c.manifest_sha256 FROM advisory_runs u JOIN calculations c USING(calculation_id) WHERE run_id=$1`, id).Scan(&data, &key, &sha, &calcKey, &calcSHA); err != nil {
			return out, err
		}
		if err = s.checkEventObject(r, key, sha, 32<<20); err != nil {
			return out, err
		}
		if err = s.checkEventObject(r, calcKey, calcSHA, 4<<20); err != nil {
			return out, err
		}
		// Compare the SQL mirror with the checksum-pinned object, not only the stored digest.
		lake, err := s.readAdvisoryJSON(r, key, sha)
		if err != nil {
			return out, err
		}
		var a, b any
		if json.Unmarshal(lake, &a) != nil || json.Unmarshal(data, &b) != nil || !reflect.DeepEqual(a, b) {
			return out, errors.New("advisory_report_mirror")
		}
		var report struct {
			Receipts []struct {
				Key   string `json:"raw_key"`
				SHA   string `json:"sha256"`
				Bytes int64  `json:"bytes"`
			} `json:"receipts"`
			Messages []json.RawMessage `json:"messages"`
		}
		if json.Unmarshal(data, &report) != nil {
			return out, errors.New("advisory_report")
		}
		for _, receipt := range report.Receipts {
			if verifiedRaw[receipt.SHA] {
				continue
			}
			verifiedRaw[receipt.SHA] = true
			total += receipt.Bytes
			if total > 32<<20 {
				return out, errors.New("advisory_integrity_byte_budget")
			}
			if err = s.checkEventObject(r, receipt.Key, receipt.SHA, receipt.Bytes); err != nil {
				return out, err
			}
		}
		for _, raw := range report.Messages {
			var m map[string]json.RawMessage
			if json.Unmarshal(raw, &m) != nil {
				return out, errors.New("advisory_message")
			}
			var revision string
			json.Unmarshal(m["revision_id"], &revision)
			var receipt struct {
				URL string `json:"url"`
			}
			json.Unmarshal(m["receipt"], &receipt)
			delete(m, "receipt")
			clean, _ := json.Marshal(m)
			documents[revision] = clean
			urls[revision] = receipt.URL
		}
	}
	messages := []advisories.Message{}
	for _, p := range pins {
		raw, ok := documents[p.b.Message.RevisionID]
		var frozen advisories.Message
		if !ok || json.Unmarshal(raw, &frozen) != nil || !reflect.DeepEqual(frozen, p.b.Message) {
			return out, errors.New("advisory_revision_mirror")
		}
		p.b.SourceURL = urls[p.b.Message.RevisionID]
		out.Items = append(out.Items, p.b)
		messages = append(messages, p.b.Message)
	}
	life := advisories.Lifecycle(messages)
	for i := range out.Items {
		out.Items[i].Lifecycle = life[out.Items[i].Message.RevisionID]
	}
	return out, tx.Commit(r.Context())
}

func (s *Server) readAdvisoryJSON(r *http.Request, key, sha string) ([]byte, error) {
	if s.Storage == nil {
		return nil, errors.New("storage_unavailable")
	}
	object, err := s.Storage.GetObject(r.Context(), "nautiq", key, minio.GetObjectOptions{})
	if err != nil {
		return nil, err
	}
	defer object.Close()
	data, err := io.ReadAll(io.LimitReader(object, (32<<20)+1))
	hash := sha256.Sum256(data)
	if err != nil || len(data) > 32<<20 || hex.EncodeToString(hash[:]) != sha {
		return nil, errors.New("advisory_checksum")
	}
	return data, nil
}
func advisoryJSON(w http.ResponseWriter, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	json.NewEncoder(w).Encode(value)
}
func (s *Server) advisoryCatalog(w http.ResponseWriter, r *http.Request) {
	if _, ok := query(w, r); !ok {
		return
	}
	snapshot, err := s.advisorySnapshot(r)
	if err != nil {
		problem(w, 503, "advisory_evidence_unavailable")
		return
	}
	advisoryJSON(w, snapshot)
}
func (s *Server) advisoryDetail(w http.ResponseWriter, r *http.Request) {
	if _, ok := query(w, r); !ok {
		return
	}
	id, ok := identifier(w, r)
	if !ok {
		return
	}
	snapshot, err := s.advisorySnapshot(r)
	if err != nil {
		problem(w, 503, "advisory_evidence_unavailable")
		return
	}
	for _, b := range snapshot.Items {
		if b.Message.RevisionID == id {
			advisoryJSON(w, map[string]any{"bulletin": b, "sources": snapshot.Sources, "as_of": snapshot.AsOf})
			return
		}
	}
	problem(w, 404, "evidence_not_found")
}
func (s *Server) advisoryState(w http.ResponseWriter, r *http.Request) {
	q, ok := query(w, r, "longitude", "latitude", "start", "end")
	if !ok {
		return
	}
	lon, e := strconv.ParseFloat(q.Get("longitude"), 64)
	lat, e2 := strconv.ParseFloat(q.Get("latitude"), 64)
	start, e3 := time.Parse(time.RFC3339, q.Get("start"))
	end, e4 := time.Parse(time.RFC3339, q.Get("end"))
	if e != nil || e2 != nil || e3 != nil || e4 != nil || !advisories.FiniteCoordinate(lon, lat) || !end.After(start) || end.Sub(start) > 96*time.Hour {
		problem(w, 400, "invalid_advisory_window_or_coordinate")
		return
	}
	snapshot, err := s.advisorySnapshot(r)
	if err != nil {
		problem(w, 503, "advisory_evidence_unavailable")
		return
	}
	messages := []advisories.Message{}
	for _, b := range snapshot.Items {
		messages = append(messages, b.Message)
	}
	frozen, _ := json.Marshal(messages)
	rows, err := s.DB.Query(r.Context(), `WITH infos AS (
 SELECT m->>'revision_id' AS id,i,ii::int-1 AS idx FROM jsonb_array_elements($1::jsonb) m CROSS JOIN LATERAL jsonb_array_elements(m->'infos') WITH ORDINALITY AS v(i,ii)), areas AS (
 SELECT id,i,idx,a FROM infos CROSS JOIN LATERAL jsonb_array_elements(i->'areas') a)
 SELECT DISTINCT id,idx FROM areas WHERE (i->>'effective')::timestamptz<=$5 AND (i->>'expires' IS NULL OR (i->>'expires')::timestamptz>$4) AND (
 EXISTS(SELECT 1 FROM jsonb_array_elements(a->'polygons') p WHERE ST_Intersects(ST_SetSRID(ST_GeomFromGeoJSON(p::text),4326),ST_SetSRID(ST_MakePoint($2,$3),4326))) OR
 EXISTS(SELECT 1 FROM jsonb_array_elements(a->'circles') c WHERE ST_DWithin(ST_SetSRID(ST_MakePoint((c->'center'->>0)::float8,(c->'center'->>1)::float8),4326)::geography,ST_SetSRID(ST_MakePoint($2,$3),4326)::geography,(c->>'radius_km')::float8*1000)))`, frozen, lon, lat, start, end)
	if err != nil {
		problem(w, 503, "advisory_geometry_unavailable")
		return
	}
	defer rows.Close()
	hits := map[string]map[int]bool{}
	for rows.Next() {
		var id string
		var ii int
		if rows.Scan(&id, &ii) != nil {
			problem(w, 503, "advisory_geometry_unavailable")
			return
		}
		if hits[id] == nil {
			hits[id] = map[int]bool{}
		}
		hits[id][ii] = true
	}
	if rows.Err() != nil {
		problem(w, 503, "advisory_geometry_unavailable")
		return
	}
	advisoryJSON(w, advisories.Evaluate(snapshot, start, end, hits))
}
