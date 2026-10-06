package product

import (
	"crypto/hmac"
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

type Object struct {
	ID      string          `json:"id"`
	Kind    string          `json:"kind"`
	Name    string          `json:"name"`
	Data    json.RawMessage `json:"data"`
	Version int64           `json:"version"`
	Created time.Time       `json:"created_at"`
	Updated time.Time       `json:"updated_at"`
}

func routeKind(r *http.Request) string {
	p := strings.Split(strings.TrimPrefix(r.URL.Path, "/api/v1/"), "/")
	return p[0]
}
func identifier(v string) bool { u, e := uuid.Parse(v); return e == nil && u.String() == v }
func noQuery(w http.ResponseWriter, r *http.Request) bool {
	if len(r.URL.Query()) != 0 {
		fail(w, 400, "unknown_query")
		return false
	}
	return true
}
func page(w http.ResponseWriter, r *http.Request) (int, string, bool) {
	q := r.URL.Query()
	for k := range q {
		if k != "limit" && k != "after" {
			fail(w, 400, "unknown_query")
			return 0, "", false
		}
	}
	n := 50
	if q.Has("limit") {
		v, e := strconv.Atoi(q.Get("limit"))
		if e != nil || v < 1 || v > 100 {
			fail(w, 400, "invalid_limit")
			return 0, "", false
		}
		n = v
	}
	after := q.Get("after")
	if after != "" && !identifier(after) {
		fail(w, 400, "invalid_cursor")
		return 0, "", false
	}
	return n, after, true
}
func scanObject(row pgx.Row) (Object, error) {
	var v Object
	e := row.Scan(&v.ID, &v.Kind, &v.Name, &v.Data, &v.Version, &v.Created, &v.Updated)
	return v, e
}

const objectColumns = "object_id::text,kind,name,data,version,created_at,updated_at"

func (s *Server) objects(w http.ResponseWriter, r *http.Request, u Identity) {
	limit, after, ok := page(w, r)
	if !ok {
		return
	}
	rows, e := s.DB.Query(r.Context(), `SELECT `+objectColumns+` FROM product_objects WHERE owner_id=$1 AND kind=$2 AND deleted_at IS NULL AND ($3='' OR object_id::text>$3) ORDER BY object_id LIMIT $4`, u.ID, routeKind(r), after, limit+1)
	if e != nil {
		fail(w, 503, "saved_state_unavailable")
		return
	}
	defer rows.Close()
	items := []Object{}
	for rows.Next() {
		v, e := scanObject(rows)
		if e != nil {
			fail(w, 503, "saved_state_unavailable")
			return
		}
		items = append(items, v)
	}
	if rows.Err() != nil {
		fail(w, 503, "saved_state_unavailable")
		return
	}
	var next *string
	if len(items) > limit {
		items = items[:limit]
		next = &items[len(items)-1].ID
	}
	write(w, 200, map[string]any{"items": items, "next_cursor": next, "snapshot_at": time.Now().UTC()})
}
func (s *Server) object(w http.ResponseWriter, r *http.Request, u Identity) {
	if !noQuery(w, r) {
		return
	}
	if !identifier(r.PathValue("id")) {
		fail(w, 404, "not_found")
		return
	}
	v, e := scanObject(s.DB.QueryRow(r.Context(), `SELECT `+objectColumns+` FROM product_objects WHERE object_id=$1 AND owner_id=$2 AND kind=$3 AND deleted_at IS NULL`, r.PathValue("id"), u.ID, routeKind(r)))
	if e != nil {
		if missing(e) {
			fail(w, 404, "not_found")
		} else {
			fail(w, 503, "saved_state_unavailable")
		}
		return
	}
	w.Header().Set("ETag", strconv.Quote(strconv.FormatInt(v.Version, 10)))
	write(w, 200, v)
}

type action func(pgx.Tx) (int, any, error)
type refusal struct {
	status int
	code   string
}

func (e refusal) Error() string { return e.code }
func (s *Server) mutation(w http.ResponseWriter, r *http.Request, u Identity, payload any, next action) {
	if !noQuery(w, r) {
		return
	}
	key := r.Header.Get("Idempotency-Key")
	if !identifier(key) {
		fail(w, 400, "idempotency_key_required")
		return
	}
	requestSHA := Hash(JSON(map[string]any{"body": payload, "version": r.Header.Get("If-Match")}))
	actionName := r.Method + ":" + r.URL.Path
	tx, e := s.DB.Begin(r.Context())
	if e != nil {
		fail(w, 503, "saved_state_unavailable")
		return
	}
	defer tx.Rollback(r.Context())
	var exists string
	e = tx.QueryRow(r.Context(), `SELECT account_id::text FROM product_accounts WHERE account_id=$1 FOR UPDATE`, u.ID).Scan(&exists)
	if e == nil {
		e = tx.QueryRow(r.Context(), `SELECT account_id::text FROM product_sessions WHERE token_sha256=$1 AND expires_at>now() AND last_seen_at>now()-interval '30 minutes' FOR SHARE`, Hash([]byte(u.token))).Scan(&exists)
	}
	if e != nil {
		fail(w, 401, "session_expired_or_missing")
		return
	}
	_, e = tx.Exec(r.Context(), `DELETE FROM product_idempotency WHERE owner_id=$1 AND expires_at<=now()`, u.ID)
	if e != nil {
		fail(w, 503, "idempotency_unavailable")
		return
	}
	var previousAction, previousSHA string
	var previousStatus int
	var response []byte
	e = tx.QueryRow(r.Context(), `SELECT action,request_sha256,status,response FROM product_idempotency WHERE owner_id=$1 AND key=$2`, u.ID, key).Scan(&previousAction, &previousSHA, &previousStatus, &response)
	if e == nil {
		if previousAction != actionName || previousSHA != requestSHA {
			fail(w, 409, "idempotency_conflict")
			return
		}
		write(w, previousStatus, json.RawMessage(response))
		return
	}
	if !missing(e) {
		fail(w, 503, "idempotency_unavailable")
		return
	}
	status, result, e := next(tx)
	if e != nil {
		var refusal refusal
		if errors.As(e, &refusal) {
			fail(w, refusal.status, refusal.code)
		} else {
			fail(w, 503, "saved_state_unavailable")
		}
		return
	}
	_, e = tx.Exec(r.Context(), `INSERT INTO product_idempotency(owner_id,key,action,request_sha256,status,response) VALUES($1,$2,$3,$4,$5,$6)`, u.ID, key, actionName, requestSHA, status, JSON(result))
	if e == nil {
		e = tx.Commit(r.Context())
	}
	if e != nil {
		fail(w, 503, "saved_state_unavailable")
		return
	}
	write(w, status, result)
}
func (s *Server) references(r *http.Request, tx pgx.Tx, u Identity, kind string, data []byte) error {
	var id, expected string
	if kind == "watchlists" {
		var v Watch
		json.Unmarshal(data, &v)
		if v.Type == "route" {
			id, expected = v.RouteID, "routes"
		}
		if v.Type == "polygon" {
			var valid bool
			e := tx.QueryRow(r.Context(), `SELECT ST_IsValid(ST_GeomFromGeoJSON($1)) AND ST_Area(ST_GeomFromGeoJSON($1)::geography)<1000000000000`, string(JSON(map[string]any{"type": "Polygon", "coordinates": [][][]float64{v.Polygon}}))).Scan(&valid)
			if e != nil || !valid {
				return refusal{400, "invalid_or_over_budget_polygon"}
			}
		}
	}
	if id != "" {
		if !identifier(id) {
			return refusal{404, "referenced_object_not_found"}
		}
		var found string
		e := tx.QueryRow(r.Context(), `SELECT object_id::text FROM product_objects WHERE object_id=$1 AND owner_id=$2 AND kind=$3 AND deleted_at IS NULL`, id, u.ID, expected).Scan(&found)
		if missing(e) {
			return refusal{404, "referenced_object_not_found"}
		}
		return e
	}
	return nil
}
func (s *Server) createObject(w http.ResponseWriter, r *http.Request, u Identity) {
	var v ObjectInput
	if !body(w, r, &v) {
		return
	}
	kind := routeKind(r)
	if e := ValidateObject(kind, v); e != nil {
		fail(w, 400, e.Error())
		return
	}
	s.mutation(w, r, u, v, func(tx pgx.Tx) (int, any, error) {
		if e := s.references(r, tx, u, kind, v.Data); e != nil {
			return 0, nil, e
		}
		var count int
		e := tx.QueryRow(r.Context(), `SELECT count(*) FROM product_objects WHERE owner_id=$1 AND kind=$2 AND deleted_at IS NULL`, u.ID, kind).Scan(&count)
		if e != nil {
			return 0, nil, e
		}
		if count >= 100 {
			return 0, nil, refusal{422, "saved_object_quota"}
		}
		item, e := scanObject(tx.QueryRow(r.Context(), `INSERT INTO product_objects(object_id,owner_id,kind,name,data) VALUES($1,$2,$3,$4,$5) RETURNING `+objectColumns, uuid.NewString(), u.ID, kind, v.Name, []byte(v.Data)))
		return 201, item, e
	})
}
func (s *Server) updateObject(w http.ResponseWriter, r *http.Request, u Identity) {
	var v ObjectInput
	if !body(w, r, &v) {
		return
	}
	kind := routeKind(r)
	if !identifier(r.PathValue("id")) {
		fail(w, 404, "not_found")
		return
	}
	if e := ValidateObject(kind, v); e != nil {
		fail(w, 400, e.Error())
		return
	}
	s.mutation(w, r, u, v, func(tx pgx.Tx) (int, any, error) {
		old, e := scanObject(tx.QueryRow(r.Context(), `SELECT `+objectColumns+` FROM product_objects WHERE object_id=$1 AND owner_id=$2 AND kind=$3 AND deleted_at IS NULL`, r.PathValue("id"), u.ID, kind))
		if e != nil {
			if missing(e) {
				return 0, nil, refusal{404, "not_found"}
			}
			return 0, nil, e
		}
		if r.Header.Get("If-Match") == "" {
			return 0, nil, refusal{428, "version_required"}
		}
		if r.Header.Get("If-Match") != strconv.Quote(strconv.FormatInt(old.Version, 10)) {
			return 0, nil, refusal{409, "version_conflict"}
		}
		if e = s.references(r, tx, u, kind, v.Data); e != nil {
			return 0, nil, e
		}
		item, e := scanObject(tx.QueryRow(r.Context(), `UPDATE product_objects SET name=$4,data=$5,version=version+1,updated_at=now() WHERE object_id=$1 AND owner_id=$2 AND kind=$3 AND version=$6 AND deleted_at IS NULL RETURNING `+objectColumns, old.ID, u.ID, kind, v.Name, []byte(v.Data), old.Version))
		return 200, item, e
	})
}
func (s *Server) deleteObject(w http.ResponseWriter, r *http.Request, u Identity) {
	if r.ContentLength > 0 {
		fail(w, 400, "unexpected_body")
		return
	}
	id := r.PathValue("id")
	if !identifier(id) {
		fail(w, 404, "not_found")
		return
	}
	s.mutation(w, r, u, nil, func(tx pgx.Tx) (int, any, error) {
		var version int64
		e := tx.QueryRow(r.Context(), `SELECT version FROM product_objects WHERE object_id=$1 AND owner_id=$2 AND kind=$3 AND deleted_at IS NULL`, id, u.ID, routeKind(r)).Scan(&version)
		if missing(e) {
			return 0, nil, refusal{404, "not_found"}
		}
		if e != nil {
			return 0, nil, e
		}
		if r.Header.Get("If-Match") == "" {
			return 0, nil, refusal{428, "version_required"}
		}
		if r.Header.Get("If-Match") != strconv.Quote(strconv.FormatInt(version, 10)) {
			return 0, nil, refusal{409, "version_conflict"}
		}
		var inUse bool
		e = tx.QueryRow(r.Context(), `SELECT EXISTS(SELECT 1 FROM product_objects WHERE owner_id=$1 AND deleted_at IS NULL AND (data->>'route_id'=$2 OR data->>'watchlist_id'=$2))`, u.ID, id).Scan(&inUse)
		if e != nil {
			return 0, nil, e
		}
		if inUse {
			return 0, nil, refusal{409, "object_has_dependents"}
		}
		_, e = tx.Exec(r.Context(), `UPDATE product_objects SET deleted_at=now(),version=version+1,updated_at=now() WHERE object_id=$1 AND owner_id=$2`, id, u.ID)
		return 200, map[string]any{"id": id, "deleted": true, "version": version + 1}, e
	})
}
func (s *Server) receipt(r *http.Request, id string) (json.RawMessage, error) {
	var sha string
	var mirror, verdict []byte
	e := s.DB.QueryRow(r.Context(), `SELECT c.manifest_sha256,c.manifest,t.verdict FROM calculations c JOIN trip_calculations t USING(calculation_id) WHERE calculation_id=$1 AND c.kind='trip_assessment'`, id).Scan(&sha, &mirror, &verdict)
	if e != nil {
		return nil, e
	}
	obj, e := s.Storage.GetObject(r.Context(), "nautiq", "trips/private/"+sha+".json", minio.GetObjectOptions{})
	if e != nil {
		return nil, e
	}
	defer obj.Close()
	data, e := io.ReadAll(io.LimitReader(obj, 8388609))
	if e != nil || len(data) > 8388608 || Hash(data) != sha {
		return nil, errors.New("trip_object_integrity")
	}
	var stored, sql any
	var decoded struct {
		Output json.RawMessage `json:"output"`
	}
	if json.Unmarshal(data, &stored) != nil || json.Unmarshal(mirror, &sql) != nil || !reflect.DeepEqual(stored, sql) || json.Unmarshal(data, &decoded) != nil {
		return nil, errors.New("trip_mirror_integrity")
	}
	var output, sqlOutput any
	if json.Unmarshal(decoded.Output, &output) != nil || json.Unmarshal(verdict, &sqlOutput) != nil || !reflect.DeepEqual(output, sqlOutput) {
		return nil, errors.New("trip_verdict_integrity")
	}
	return data, nil
}
func (s *Server) saveTrip(w http.ResponseWriter, r *http.Request, u Identity) {
	var v struct {
		Name  string `json:"name"`
		ID    string `json:"calculation_id"`
		Token string `json:"access_token"`
	}
	if !body(w, r, &v) {
		return
	}
	if !validName(v.Name) || !identifier(v.ID) || !tokenPattern.MatchString(v.Token) {
		fail(w, 400, "invalid_trip_claim")
		return
	}
	var access string
	e := s.DB.QueryRow(r.Context(), `SELECT access_sha256 FROM trip_calculations WHERE calculation_id=$1`, v.ID).Scan(&access)
	if e != nil || !hmac.Equal([]byte(access), []byte(Hash([]byte(v.Token)))) {
		fail(w, 404, "not_found")
		return
	}
	if _, e = s.receipt(r, v.ID); e != nil {
		fail(w, 503, "trip_integrity_unavailable")
		return
	}
	s.mutation(w, r, u, v, func(tx pgx.Tx) (int, any, error) {
		var owner string
		e := tx.QueryRow(r.Context(), `SELECT owner_id::text FROM product_trip_links WHERE calculation_id=$1`, v.ID).Scan(&owner)
		if e == nil && owner != u.ID {
			return 0, nil, refusal{404, "not_found"}
		}
		if e == nil {
			return 200, map[string]any{"calculation_id": v.ID, "name": v.Name, "already_saved": true}, nil
		}
		if !missing(e) {
			return 0, nil, e
		}
		var count int
		if e = tx.QueryRow(r.Context(), `SELECT count(*) FROM product_trip_links WHERE owner_id=$1`, u.ID).Scan(&count); e != nil {
			return 0, nil, e
		}
		if count >= 100 {
			return 0, nil, refusal{422, "saved_trip_quota"}
		}
		_, e = tx.Exec(r.Context(), `INSERT INTO product_trip_links(calculation_id,owner_id,name) VALUES($1,$2,$3)`, v.ID, u.ID, v.Name)
		return 201, map[string]any{"calculation_id": v.ID, "name": v.Name}, e
	})
}
func (s *Server) savedTrips(w http.ResponseWriter, r *http.Request, u Identity) {
	limit, after, ok := page(w, r)
	if !ok {
		return
	}
	var data []byte
	e := s.DB.QueryRow(r.Context(), `SELECT json_build_object('items',COALESCE(json_agg(v),'[]')) FROM (SELECT l.calculation_id,l.name,l.created_at,t.verdict->>'status' AS status,t.verdict->>'as_of' AS as_of FROM product_trip_links l JOIN trip_calculations t USING(calculation_id) WHERE owner_id=$1 AND ($2='' OR l.calculation_id::text>$2) ORDER BY l.calculation_id LIMIT $3) v`, u.ID, after, limit+1).Scan(&data)
	if e != nil {
		fail(w, 503, "saved_trip_unavailable")
		return
	}
	var out struct {
		Items []map[string]any `json:"items"`
	}
	if json.Unmarshal(data, &out) != nil {
		fail(w, 503, "saved_trip_unavailable")
		return
	}
	var next any
	if len(out.Items) > limit {
		out.Items = out.Items[:limit]
		next = out.Items[len(out.Items)-1]["calculation_id"]
	}
	write(w, 200, map[string]any{"items": out.Items, "next_cursor": next})
}
func (s *Server) savedTrip(w http.ResponseWriter, r *http.Request, u Identity) {
	if !noQuery(w, r) {
		return
	}
	id := r.PathValue("id")
	if !identifier(id) {
		fail(w, 404, "not_found")
		return
	}
	var found string
	e := s.DB.QueryRow(r.Context(), `SELECT calculation_id::text FROM product_trip_links WHERE calculation_id=$1 AND owner_id=$2`, id, u.ID).Scan(&found)
	if e != nil {
		fail(w, 404, "not_found")
		return
	}
	data, e := s.receipt(r, id)
	if e != nil {
		fail(w, 503, "trip_integrity_unavailable")
		return
	}
	write(w, 200, json.RawMessage(data))
}
func (s *Server) forgetTrip(w http.ResponseWriter, r *http.Request, u Identity) {
	if r.ContentLength > 0 || !identifier(r.PathValue("id")) {
		fail(w, 400, "invalid_trip_unlink")
		return
	}
	s.mutation(w, r, u, nil, func(tx pgx.Tx) (int, any, error) {
		tag, e := tx.Exec(r.Context(), `DELETE FROM product_trip_links WHERE calculation_id=$1 AND owner_id=$2`, r.PathValue("id"), u.ID)
		if e == nil && tag.RowsAffected() != 1 {
			return 0, nil, refusal{404, "not_found"}
		}
		return 200, map[string]bool{"unlinked": true}, e
	})
}
