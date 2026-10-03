package product

import (
	"bytes"
	"crypto/sha256"
	_ "embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"math"
	"nautiq.local/api/internal/trips"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

//go:embed policy.json
var PolicyJSON []byte

type Location struct {
	Slug      string    `json:"slug"`
	Name      string    `json:"name"`
	Latitude  float64   `json:"latitude"`
	Longitude float64   `json:"longitude"`
	BBox      []float64 `json:"bbox"`
}
type Policy struct {
	Version           string          `json:"version"`
	Locations         []Location      `json:"locations"`
	Limitations       []string        `json:"limitations"`
	Unavailable       []string        `json:"unavailable_layers"`
	ExportPermissions map[string]bool `json:"export_permissions"`
}

func Catalog() Policy {
	var p Policy
	if json.Unmarshal(PolicyJSON, &p) != nil {
		panic("product policy invalid")
	}
	return p
}
func Hash(data []byte) string { v := sha256.Sum256(data); return hex.EncodeToString(v[:]) }
func JSON(value any) []byte {
	data, err := json.Marshal(value)
	if err != nil {
		panic("invalid product JSON")
	}
	return data
}
func Strict(data []byte, value any) error {
	if !utf8.Valid(data) {
		return errors.New("invalid_utf8")
	}
	d := json.NewDecoder(bytes.NewReader(data))
	d.DisallowUnknownFields()
	if d.Decode(value) != nil || d.Decode(&struct{}{}) != io.EOF {
		return errors.New("invalid_json")
	}
	walk := json.NewDecoder(bytes.NewReader(data))
	var visit func(int) error
	visit = func(depth int) error {
		if depth > 24 {
			return errors.New("json_depth")
		}
		t, e := walk.Token()
		if e != nil {
			return e
		}
		delim, ok := t.(json.Delim)
		if !ok {
			return nil
		}
		if delim == '{' {
			keys := map[string]bool{}
			for walk.More() {
				k, e := walk.Token()
				if e != nil {
					return e
				}
				name, ok := k.(string)
				if !ok || keys[name] {
					return errors.New("duplicate_key")
				}
				keys[name] = true
				if e = visit(depth + 1); e != nil {
					return e
				}
			}
		} else if delim == '[' {
			for walk.More() {
				if e = visit(depth + 1); e != nil {
					return e
				}
			}
		} else {
			return errors.New("invalid_json")
		}
		_, e = walk.Token()
		return e
	}
	return visit(0)
}
func finite(v float64) bool { return !math.IsNaN(v) && !math.IsInf(v, 0) }
func validName(s string) bool {
	return len(s) > 0 && len(s) <= 80 && strings.TrimSpace(s) == s && strings.IndexFunc(s, unicode.IsControl) < 0
}

type ObjectInput struct {
	Name string          `json:"name"`
	Data json.RawMessage `json:"data"`
}
type Watch struct {
	Type      string      `json:"type"`
	Latitude  *float64    `json:"latitude,omitempty"`
	Longitude *float64    `json:"longitude,omitempty"`
	RadiusKM  *float64    `json:"radius_km,omitempty"`
	Place     string      `json:"place,omitempty"`
	Polygon   [][]float64 `json:"polygon,omitempty"`
	RouteID   string      `json:"route_id,omitempty"`
}
type AlertRule struct {
	WatchlistID string   `json:"watchlist_id"`
	Type        string   `json:"type"`
	Variable    string   `json:"variable,omitempty"`
	Units       string   `json:"units,omitempty"`
	Limit       *float64 `json:"limit,omitempty"`
	Enabled     bool     `json:"enabled"`
	Channel     string   `json:"channel"`
}

func ValidateObject(kind string, body ObjectInput) error {
	if !validName(body.Name) || len(body.Data) == 0 {
		return errors.New("invalid_name_or_data")
	}
	switch kind {
	case "routes":
		var req trips.Request
		if Strict(body.Data, &req) != nil {
			return errors.New("invalid_timed_route")
		}
		if len(req.Waypoints) < 2 {
			return errors.New("timed_waypoints_required")
		}
		var required struct {
			Waypoints []struct {
				Latitude  *float64 `json:"latitude"`
				Longitude *float64 `json:"longitude"`
			} `json:"waypoints"`
		}
		if json.Unmarshal(body.Data, &required) != nil {
			return errors.New("timed_waypoints_required")
		}
		for _, p := range required.Waypoints {
			if p.Latitude == nil || p.Longitude == nil {
				return errors.New("coordinates_required")
			}
		}
		activity := false
		for _, a := range trips.DefaultPolicy().Activities {
			activity = activity || req.Activity == a
		}
		if !activity || len(req.Fields) > 3 {
			return errors.New("invalid_activity_or_binding_budget")
		}
		seen := map[string]bool{}
		for _, b := range req.Fields {
			known := false
			for _, input := range trips.DefaultPolicy().Inputs {
				known = known || input.Variable == b.Variable
			}
			if !known || seen[b.Variable] || !identifier(b.ReleaseID) {
				return errors.New("invalid_or_repeated_field_binding")
			}
			seen[b.Variable] = true
		}
		if req.ThresholdVersion != trips.DefaultPolicy().Version {
			return errors.New("threshold_version")
		}
		if _, e := trips.DefaultPolicy().WithPreferences(req.Preferences); e != nil {
			return e
		}
		_, _, e := trips.Points(req, req.Waypoints[0].Time)
		return e
	case "watchlists":
		var v Watch
		if Strict(body.Data, &v) != nil {
			return errors.New("invalid_watchlist")
		}
		switch v.Type {
		case "point":
			if v.Latitude == nil || v.Longitude == nil || !finite(*v.Latitude) || !finite(*v.Longitude) || math.Abs(*v.Latitude) > 85 || math.Abs(*v.Longitude) > 180 || v.RadiusKM == nil || !finite(*v.RadiusKM) || *v.RadiusKM < 0 || *v.RadiusKM > 100 {
				return errors.New("invalid_watch_point")
			}
			if v.Place != "" || v.RouteID != "" || len(v.Polygon) > 0 {
				return errors.New("mixed_watch_geometry")
			}
		case "place":
			found := false
			for _, p := range Catalog().Locations {
				found = found || p.Slug == v.Place
			}
			if !found || v.Latitude != nil || v.Longitude != nil || v.RadiusKM != nil || v.RouteID != "" || len(v.Polygon) > 0 {
				return errors.New("invalid_watch_place")
			}
		case "route":
			if v.RouteID == "" || v.Latitude != nil || v.Longitude != nil || v.RadiusKM != nil || v.Place != "" || len(v.Polygon) > 0 {
				return errors.New("invalid_watch_route")
			}
		case "polygon":
			if len(v.Polygon) < 4 || len(v.Polygon) > 129 || v.Latitude != nil || v.Longitude != nil || v.RadiusKM != nil || v.Place != "" || v.RouteID != "" {
				return errors.New("polygon_budget")
			}
			for i, p := range v.Polygon {
				if len(p) != 2 || !finite(p[0]) || !finite(p[1]) || math.Abs(p[0]) > 180 || math.Abs(p[1]) > 85 {
					return errors.New("invalid_polygon")
				}
				if i > 0 && math.Abs(p[0]-v.Polygon[i-1][0]) > 180 {
					return errors.New("split_dateline_polygon")
				}
			}
			first, last := v.Polygon[0], v.Polygon[len(v.Polygon)-1]
			if first[0] != last[0] || first[1] != last[1] {
				return errors.New("polygon_not_closed")
			}
		default:
			return errors.New("unknown_watch_type")
		}
	case "alert-rules":
		var v AlertRule
		if Strict(body.Data, &v) != nil || v.WatchlistID == "" || v.Channel != "in_app" {
			return errors.New("invalid_alert_rule")
		}
		switch v.Type {
		case "official_advisory", "source_stale":
			if v.Limit != nil || v.Variable != "" || v.Units != "" {
				return errors.New("unexpected_threshold")
			}
		case "field_threshold":
			units := map[string]string{"wave_height_m": "m", "wind_speed_m_s": "m s-1", "current_speed_m_s": "m s-1"}
			if units[v.Variable] == "" || units[v.Variable] != v.Units || v.Limit == nil || !finite(*v.Limit) || *v.Limit < 0 || *v.Limit > 1000 {
				return errors.New("invalid_preference_alert")
			}
		default:
			return errors.New("unsupported_alert_type")
		}
	default:
		return errors.New("unknown_object_kind")
	}
	return nil
}
func ValidTime(s string) (time.Time, error) { return time.Parse(time.RFC3339Nano, s) }
