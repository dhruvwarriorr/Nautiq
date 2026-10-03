package product

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"github.com/jackc/pgx/v5"
	"net/http"
	"regexp"
	"strings"
	"time"
)

type ResearchFilter struct {
	BBox              []float64   `json:"bbox"`
	Polygon           [][]float64 `json:"polygon,omitempty"`
	Start             string      `json:"start"`
	End               string      `json:"end"`
	MinDepth          float64     `json:"min_depth_m"`
	MaxDepth          float64     `json:"max_depth_m"`
	Variable          string      `json:"variable"`
	Source            string      `json:"source"`
	QC                string      `json:"qc"`
	Mode              string      `json:"data_mode,omitempty"`
	MinimumPercentile *float64    `json:"minimum_anomaly_percentile,omitempty"`
	EventID           string      `json:"event_id,omitempty"`
	Limit             int         `json:"limit"`
	Cursor            string      `json:"cursor,omitempty"`
	Snapshot          time.Time   `json:"-"`
	After             string      `json:"-"`
}

func (f *ResearchFilter) UnmarshalJSON(data []byte) error {
	type wire ResearchFilter
	var value wire
	if Strict(data, &value) != nil {
		return errors.New("invalid_research_contract")
	}
	var properties map[string]json.RawMessage
	if json.Unmarshal(data, &properties) != nil {
		return errors.New("invalid_research_contract")
	}
	for _, key := range []string{"bbox", "start", "end", "min_depth_m", "max_depth_m", "variable", "source", "qc", "limit"} {
		raw, ok := properties[key]
		if !ok || bytes.Equal(bytes.TrimSpace(raw), []byte("null")) {
			return errors.New("explicit_research_bounds_required")
		}
	}
	*f = ResearchFilter(value)
	return nil
}

func (f ResearchFilter) Validate() error {
	if len(f.BBox) != 4 {
		return errors.New("invalid_bbox")
	}
	for _, v := range f.BBox {
		if !finite(v) {
			return errors.New("invalid_bbox")
		}
	}
	b := f.BBox
	if b[0] < -180 || b[2] > 180 || b[1] < -85 || b[3] > 85 || b[0] >= b[2] || b[1] >= b[3] {
		return errors.New("invalid_or_dateline_bbox")
	}
	start, e := ValidTime(f.Start)
	if e != nil {
		return errors.New("explicit_utc_start_required")
	}
	end, e := ValidTime(f.End)
	if e != nil || !end.After(start) || end.Sub(start) > 366*24*time.Hour {
		return errors.New("time_range_budget")
	}
	if !finite(f.MinDepth) || !finite(f.MaxDepth) || f.MinDepth < 0 || f.MaxDepth > 6000 || f.MaxDepth < f.MinDepth || f.Limit < 1 || f.Limit > 100 {
		return errors.New("research_budget")
	}
	if f.Variable != "temperature_c" && f.Variable != "practical_salinity" || f.Source != "argo_gdac" || f.QC != "accepted" && f.QC != "science_ready" || f.Mode != "" && f.Mode != "R" && f.Mode != "A" && f.Mode != "D" {
		return errors.New("unsupported_research_filter")
	}
	if f.EventID != "" && !identifier(f.EventID) {
		return errors.New("invalid_event")
	}
	if f.MinimumPercentile != nil && (!finite(*f.MinimumPercentile) || *f.MinimumPercentile < 0 || *f.MinimumPercentile > 100) {
		return errors.New("invalid_percentile")
	}
	if len(f.Polygon) > 0 {
		raw := JSON(Watch{Type: "polygon", Polygon: f.Polygon})
		if e = ValidateObject("watchlists", ObjectInput{Name: "Research polygon", Data: raw}); e != nil {
			return e
		}
	}
	return nil
}

type ResearchRow struct {
	ID                 string          `json:"id"`
	Revision           string          `json:"revision_sha256"`
	Platform           string          `json:"platform_id"`
	Observed           time.Time       `json:"observed_at"`
	Received           time.Time       `json:"received_at"`
	Latitude           float64         `json:"latitude"`
	Longitude          float64         `json:"longitude"`
	Mode               string          `json:"data_mode"`
	QC                 string          `json:"qc_version"`
	Source             string          `json:"source_id"`
	Calculation        *string         `json:"calculation_id"`
	RawSHA             string          `json:"raw_sha256"`
	SourceURL          string          `json:"source_url"`
	Levels             json.RawMessage `json:"levels"`
	LevelCount         int             `json:"level_count"`
	Minimum            *float64        `json:"minimum"`
	Maximum            *float64        `json:"maximum"`
	Percentile         *float64        `json:"anomaly_percentile"`
	AnomalyCalculation *string         `json:"anomaly_calculation_id"`
	AnomalyState       *string         `json:"anomaly_state"`
}
type Querier interface {
	Query(context.Context, string, ...any) (pgx.Rows, error)
}

func ResearchRows(ctx context.Context, db Querier, f ResearchFilter) ([]ResearchRow, error) {
	if e := f.Validate(); e != nil {
		return nil, e
	}
	if f.Snapshot.IsZero() {
		f.Snapshot = time.Now().UTC()
	}
	polygon := ""
	if len(f.Polygon) > 0 {
		polygon = string(JSON(map[string]any{"type": "Polygon", "coordinates": [][][]float64{f.Polygon}}))
	}
	rows, e := db.Query(ctx, `WITH selected AS (
 SELECT r.*,p.platform_id,a.sha256 AS raw_sha,a.source_url,a.source_id,cmp.result AS anomaly_result,cmp.calculation_id AS anomaly_calculation,c.state AS anomaly_state
 FROM profile_revisions r JOIN profiles p USING(profile_id) JOIN raw_artifacts a ON a.artifact_id=r.raw_artifact_id
 LEFT JOIN anomaly_selection sel ON sel.singleton LEFT JOIN anomaly_comparisons cmp ON cmp.profile_id=r.profile_id AND cmp.revision_sha256=r.revision_sha256 AND cmp.release_id=sel.release_id LEFT JOIN calculations c ON c.calculation_id=cmp.calculation_id
 WHERE r.selected_at IS NOT NULL AND r.selected_at<=$15 AND (r.superseded_at IS NULL OR r.superseded_at>$15)
 AND r.observed_at>=$1 AND r.observed_at<$2 AND r.position && ST_MakeEnvelope($3,$4,$5,$6,4326)
 AND ($7='' OR r.data_mode=$7) AND ($8='accepted' OR r.science_ready) AND a.source_id='argo_gdac'
 AND ($9='' OR ST_IsValid(ST_GeomFromGeoJSON($9)) AND ST_Covers(ST_GeomFromGeoJSON($9),r.position))
 AND ($10::float8 IS NULL OR c.state='current' AND (cmp.result#>>ARRAY['variables',$11,'percentiles','values','weighted_squared_residual'])::float8 >= $10)
 AND ($12='' OR EXISTS(SELECT 1 FROM regional_events ev,jsonb_array_elements(ev.evidence->'members') member WHERE ev.event_id::text=$12 AND member->>'profile_id'=r.profile_id::text AND member->>'revision_sha256'=r.revision_sha256))
 AND EXISTS(SELECT 1 FROM jsonb_array_elements(r.levels) level WHERE (level->>'depth_m')::float8 BETWEEN $16 AND $17 AND level->>$11 IS NOT NULL)
 AND ($14='' OR r.profile_id::text>$14) ORDER BY r.profile_id LIMIT $13
 ) SELECT r.profile_id::text,r.revision_sha256,r.platform_id,r.observed_at,r.received_at,r.latitude,r.longitude,r.data_mode,r.qc_version,r.source_id,r.calculation_id::text,r.raw_sha,r.source_url,
 COALESCE((SELECT jsonb_agg(v.level ORDER BY (v.level->>'depth_m')::float8) FROM (SELECT level FROM jsonb_array_elements(r.levels) level WHERE (level->>'depth_m')::float8 BETWEEN $16 AND $17 AND level->>$11 IS NOT NULL ORDER BY (level->>'depth_m')::float8 LIMIT 200) v),'[]'),
 (SELECT count(*) FROM jsonb_array_elements(r.levels) level WHERE (level->>'depth_m')::float8 BETWEEN $16 AND $17 AND level->>$11 IS NOT NULL),
 (SELECT min((level->>$11)::float8) FROM jsonb_array_elements(r.levels) level WHERE (level->>'depth_m')::float8 BETWEEN $16 AND $17),
 (SELECT max((level->>$11)::float8) FROM jsonb_array_elements(r.levels) level WHERE (level->>'depth_m')::float8 BETWEEN $16 AND $17),
 (r.anomaly_result#>>ARRAY['variables',$11,'percentiles','values','weighted_squared_residual'])::float8,r.anomaly_calculation::text,r.anomaly_state FROM selected r
 WHERE EXISTS(SELECT 1 FROM jsonb_array_elements(r.levels) level WHERE (level->>'depth_m')::float8 BETWEEN $16 AND $17 AND level->>$11 IS NOT NULL) ORDER BY r.profile_id`, f.Start, f.End, f.BBox[0], f.BBox[1], f.BBox[2], f.BBox[3], f.Mode, f.QC, polygon, f.MinimumPercentile, f.Variable, f.EventID, f.Limit+1, f.After, f.Snapshot, f.MinDepth, f.MaxDepth)
	if e != nil {
		return nil, e
	}
	defer rows.Close()
	out := []ResearchRow{}
	for rows.Next() {
		var v ResearchRow
		if e = rows.Scan(&v.ID, &v.Revision, &v.Platform, &v.Observed, &v.Received, &v.Latitude, &v.Longitude, &v.Mode, &v.QC, &v.Source, &v.Calculation, &v.RawSHA, &v.SourceURL, &v.Levels, &v.LevelCount, &v.Minimum, &v.Maximum, &v.Percentile, &v.AnomalyCalculation, &v.AnomalyState); e != nil {
			return nil, e
		}
		out = append(out, v)
	}
	return out, rows.Err()
}

type researchCursor struct {
	Filter   string    `json:"filter"`
	After    string    `json:"after"`
	Snapshot time.Time `json:"snapshot"`
	Expires  time.Time `json:"expires"`
}

func filterHash(f ResearchFilter) string {
	f.Cursor = ""
	f.After = ""
	f.Snapshot = time.Time{}
	return Hash(JSON(f))
}
func (s *Server) signCursor(c researchCursor) string {
	raw := JSON(c)
	mac := hmac.New(sha256.New, s.cursorKey)
	mac.Write(raw)
	return base64.RawURLEncoding.EncodeToString(raw) + "." + base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
}
func (s *Server) research(w http.ResponseWriter, r *http.Request) {
	if !noQuery(w, r) {
		return
	}
	var f ResearchFilter
	if !body(w, r, &f) {
		return
	}
	if e := f.Validate(); e != nil {
		fail(w, 400, e.Error())
		return
	}
	now := time.Now().UTC()
	f.Snapshot = now
	if f.Cursor != "" {
		parts := strings.Split(f.Cursor, ".")
		if len(parts) != 2 || len(f.Cursor) > 2048 {
			fail(w, 400, "invalid_cursor")
			return
		}
		raw, e := base64.RawURLEncoding.DecodeString(parts[0])
		sig, es := base64.RawURLEncoding.DecodeString(parts[1])
		mac := hmac.New(sha256.New, s.cursorKey)
		mac.Write(raw)
		var cursor researchCursor
		if e != nil || es != nil || !hmac.Equal(sig, mac.Sum(nil)) || Strict(raw, &cursor) != nil || cursor.Filter != filterHash(f) || !identifier(cursor.After) || !cursor.Expires.After(now) || cursor.Snapshot.After(now) {
			fail(w, 400, "invalid_or_expired_cursor")
			return
		}
		f.Snapshot = cursor.Snapshot
		f.After = cursor.After
	}
	tx, e := s.DB.Begin(r.Context())
	if e != nil {
		fail(w, 503, "research_unavailable")
		return
	}
	defer tx.Rollback(r.Context())
	_, e = tx.Exec(r.Context(), "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
	if e != nil {
		fail(w, 503, "research_unavailable")
		return
	}
	if len(f.Polygon) > 0 {
		var valid bool
		e = tx.QueryRow(r.Context(), `SELECT ST_IsValid(ST_GeomFromGeoJSON($1)) AND ST_Area(ST_GeomFromGeoJSON($1)::geography)<1000000000000`, string(JSON(map[string]any{"type": "Polygon", "coordinates": [][][]float64{f.Polygon}}))).Scan(&valid)
		if e != nil || !valid {
			fail(w, 400, "invalid_or_over_budget_polygon")
			return
		}
	}
	items, e := ResearchRows(r.Context(), tx, f)
	if e != nil {
		fail(w, 503, "research_unavailable")
		return
	}
	var next *string
	if len(items) > f.Limit {
		items = items[:f.Limit]
		v := s.signCursor(researchCursor{filterHash(f), items[len(items)-1].ID, f.Snapshot, f.Snapshot.Add(15 * time.Minute)})
		next = &v
	}
	if tx.Commit(r.Context()) != nil {
		fail(w, 503, "research_unavailable")
		return
	}
	units := "°C"
	if f.Variable == "practical_salinity" {
		units = "PSS-78 (dimensionless)"
	}
	write(w, 200, map[string]any{"items": items, "query": f, "snapshot_at": f.Snapshot, "next_cursor": next, "units": units, "method_version": "bounded-original-levels-v1", "limitations": []string{"Each profile retains its actual instrument position, time and depth; no surface or point extrapolation.", "Preview shows at most 200 levels per profile; extrema cover all matching levels. Exact original levels remain in profile detail.", "Anomaly percentiles are diagnostic ranks, not probabilities or alert approvals.", "Temporal coverage and observation age must be compared before interpreting differences."}})
}

type QueryPlan struct {
	Version        string          `json:"version"`
	Intent         string          `json:"intent"`
	State          string          `json:"state"`
	Clarifications []string        `json:"clarifications"`
	Research       *ResearchFilter `json:"research,omitempty"`
	Place          *Location       `json:"place,omitempty"`
	Explanation    string          `json:"explanation"`
}

var dates = regexp.MustCompile(`\b\d{4}-\d{2}-\d{2}\b`)

func ParseQuery(text, zone string) QueryPlan {
	out := QueryPlan{Version: "bounded-intent-grammar-v1", State: "clarification_required", Clarifications: []string{}}
	text = strings.ToLower(strings.TrimSpace(text))
	if len(text) == 0 || len(text) > 512 {
		out.Clarifications = append(out.Clarifications, "Enter a question of 1–512 characters.")
		return out
	}
	if zone != "" {
		if _, e := time.LoadLocation(zone); e != nil {
			out.Clarifications = append(out.Clarifications, "Choose a valid IANA time zone.")
			return out
		}
	}
	relative := strings.Contains(text, "tomorrow") || strings.Contains(text, "today") || strings.Contains(text, "this week") || strings.Contains(text, "morning")
	if relative {
		out.Clarifications = append(out.Clarifications, "Resolve relative wording into explicit UTC dates/times before execution.")
	}
	for _, p := range Catalog().Locations {
		if strings.Contains(text, strings.ToLower(p.Name)) || strings.Contains(text, strings.ReplaceAll(p.Slug, "-", " ")) || strings.Contains(text, strings.Split(p.Slug, "-")[0]) {
			copy := p
			out.Place = &copy
			break
		}
	}
	if out.Place == nil {
		out.Clarifications = append(out.Clarifications, "Choose Mumbai Offshore, Goa Offshore, Kerala Offshore, Arabian Sea or Bay of Bengal.")
	}
	switch {
	case strings.Contains(text, "profile") || strings.Contains(text, "salinity") || strings.Contains(text, "temperature"):
		out.Intent = "research"
		d := dates.FindAllString(text, -1)
		if len(d) != 2 {
			out.Clarifications = append(out.Clarifications, "Provide a start and exclusive end date as YYYY-MM-DD.")
		} else if out.Place != nil {
			variable := "temperature_c"
			if strings.Contains(text, "salinity") {
				variable = "practical_salinity"
			}
			filter := ResearchFilter{BBox: out.Place.BBox, Start: d[0] + "T00:00:00Z", End: d[1] + "T00:00:00Z", MinDepth: 0, MaxDepth: 2000, Variable: variable, Source: "argo_gdac", QC: "accepted", Limit: 50}
			if strings.Contains(text, "unusual") {
				out.Clarifications = append(out.Clarifications, "Choose a diagnostic anomaly percentile explicitly in the research filters.")
			}
			if filter.Validate() != nil {
				out.Clarifications = append(out.Clarifications, "Use a valid interval of at most 366 days.")
			} else {
				out.Research = &filter
			}
		}
		out.Explanation = "The plan queries accepted Argo profiles at their recorded positions and depths. Values are returned only after the typed research API executes."
	case strings.Contains(text, "warning") || strings.Contains(text, "advisory") || strings.Contains(text, "conditions"):
		out.Intent = "conditions"
		out.Explanation = "Open the named location and choose an explicit observation/forecast time. Official state stays unknown unless retained authority evidence supports it."
	case strings.Contains(text, "event"):
		out.Intent = "events"
		out.Explanation = "Open retained diagnostic event runs; historical results do not establish live event absence."
	case strings.Contains(text, "fish") || strings.Contains(text, "trip") || strings.Contains(text, "route") || strings.Contains(text, "waves"):
		out.Intent = "trip"
		out.Clarifications = append(out.Clarifications, "Supply timed outward/return waypoints and review the trip policy. This text cannot choose a safety verdict.")
		out.Explanation = "Use the typed timed-route form and pinned forecasts. No best window is inferred from a single calm sample."
	default:
		out.Intent = "unsupported"
		out.Clarifications = append(out.Clarifications, "Use a profile, location conditions, official warning, event or timed-trip question.")
	}
	if len(out.Clarifications) == 0 {
		out.State = "ready"
	}
	return out
}
func (s *Server) query(w http.ResponseWriter, r *http.Request) {
	if !noQuery(w, r) {
		return
	}
	var v struct {
		Text string `json:"text"`
		Zone string `json:"time_zone"`
	}
	if !body(w, r, &v) {
		return
	}
	plan := ParseQuery(v.Text, v.Zone)
	write(w, 200, map[string]any{"plan": plan, "executed": false, "limitations": []string{"A bounded parser builds a typed preview. It does not issue SQL, call an arbitrary endpoint or invent measurements or verdicts."}})
}
