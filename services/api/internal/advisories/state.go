// Package advisories preserves official CAP identities and incomplete coverage.
package advisories

import (
	"encoding/json"
	"math"
	"sort"
	"time"
)

type Identity struct {
	Sender     string    `json:"sender"`
	Identifier string    `json:"identifier"`
	Sent       time.Time `json:"sent"`
}
type Circle struct {
	Center   []float64 `json:"center"`
	RadiusKM float64   `json:"radius_km"`
}
type Geometry struct {
	Type        string        `json:"type"`
	Coordinates [][][]float64 `json:"coordinates"`
}
type Area struct {
	Description string              `json:"description"`
	Polygons    []Geometry          `json:"polygons"`
	Circles     []Circle            `json:"circles"`
	Unresolved  []string            `json:"unresolved"`
	Geocodes    []map[string]string `json:"geocodes"`
}
type Info struct {
	Language    string     `json:"language"`
	Event       string     `json:"event"`
	Severity    string     `json:"severity"`
	Urgency     string     `json:"urgency"`
	Certainty   string     `json:"certainty"`
	Effective   time.Time  `json:"effective"`
	Onset       *time.Time `json:"onset"`
	Expires     *time.Time `json:"expires"`
	Headline    string     `json:"headline"`
	Description string     `json:"description"`
	Instruction string     `json:"instruction"`
	Web         string     `json:"web"`
	Issues      []string   `json:"issues"`
	Areas       []Area     `json:"areas"`
}
type Message struct {
	Identity    Identity   `json:"identity"`
	Sender      string     `json:"sender"`
	Identifier  string     `json:"identifier"`
	Sent        time.Time  `json:"sent"`
	RevisionID  string     `json:"revision_id"`
	SourceID    string     `json:"source_id"`
	Operational bool       `json:"operational"`
	Type        string     `json:"msgType"`
	Status      string     `json:"status"`
	Scope       string     `json:"scope"`
	Issues      []string   `json:"issues"`
	References  []Identity `json:"references"`
	Infos       []Info     `json:"infos"`
}
type Life struct {
	State      string   `json:"state"`
	ReplacedBy []string `json:"replaced_by"`
	Issues     []string `json:"issues"`
}
type Source struct {
	ID         string          `json:"source_id"`
	Policy     json.RawMessage `json:"policy"`
	Transport  string          `json:"transport"`
	CheckedAt  *time.Time      `json:"checked_at"`
	RunID      *string         `json:"run_id"`
	Integrity  string          `json:"integrity"`
	Reasons    json.RawMessage `json:"reasons"`
	AgeSeconds *int64          `json:"age_seconds"`
	Coverage   string          `json:"coverage"`
}
type Bulletin struct {
	Message    Message `json:"message"`
	Lifecycle  Life    `json:"lifecycle"`
	RawSHA     string  `json:"raw_sha256"`
	FirstRunID string  `json:"first_run_id"`
	SourceURL  string  `json:"source_url"`
}
type Snapshot struct {
	AsOf               time.Time  `json:"as_of"`
	Sources            []Source   `json:"sources"`
	Items              []Bulletin `json:"items"`
	ProductionApproved bool       `json:"production_approved"`
	Issues             []string   `json:"issues"`
}
type Warning struct {
	RevisionID string     `json:"revision_id"`
	SourceID   string     `json:"source_id"`
	Event      string     `json:"event"`
	Severity   string     `json:"severity"`
	Effective  time.Time  `json:"effective"`
	Expires    *time.Time `json:"expires"`
	InfoIndex  int        `json:"info_index"`
}
type State struct {
	Status             string    `json:"status"`
	AsOf               time.Time `json:"as_of"`
	Start              time.Time `json:"start"`
	End                time.Time `json:"end"`
	Warnings           []Warning `json:"warnings"`
	Unknown            []string  `json:"unknown_reasons"`
	Sources            []Source  `json:"sources"`
	ProductionApproved bool      `json:"production_approved"`
}

func usable(m Message) bool {
	if !m.Operational || len(m.Issues) > 0 {
		return false
	}
	if m.Type == "Cancel" {
		return len(m.References) > 0
	}
	if m.Type != "Update" || len(m.Infos) == 0 {
		return false
	}
	for _, i := range m.Infos {
		if len(i.Issues) > 0 || len(i.Areas) == 0 || i.Expires == nil || !i.Expires.After(i.Effective) {
			return false
		}
		for _, a := range i.Areas {
			if len(a.Unresolved) > 0 {
				return false
			}
		}
	}
	return true
}
func Lifecycle(messages []Message) map[string]Life {
	groups := map[Identity][]Message{}
	result := map[string]Life{}
	for _, m := range messages {
		groups[m.Identity] = append(groups[m.Identity], m)
		state := "non_warning"
		if m.Operational && (m.Type == "Alert" || m.Type == "Update") {
			state = "active"
		}
		result[m.RevisionID] = Life{state, []string{}, append([]string{}, m.Issues...)}
	}
	for _, g := range groups {
		if len(g) > 1 {
			for _, m := range g {
				l := result[m.RevisionID]
				l.Issues = append(l.Issues, "identity_conflict")
				result[m.RevisionID] = l
			}
		}
	}
	ordered := append([]Message{}, messages...)
	sort.Slice(ordered, func(i, j int) bool {
		if ordered[i].Sent.Equal(ordered[j].Sent) {
			return ordered[i].RevisionID < ordered[j].RevisionID
		}
		return ordered[i].Sent.Before(ordered[j].Sent)
	})
	for _, m := range ordered {
		if !m.Operational || (m.Type != "Update" && m.Type != "Cancel") {
			continue
		}
		for _, ref := range m.References {
			targets := groups[ref]
			if ref.Sender != m.Sender || !ref.Sent.Before(m.Sent) || len(targets) != 1 || len(groups[m.Identity]) != 1 || !usable(m) || !targets[0].Operational {
				l := result[m.RevisionID]
				l.Issues = append(l.Issues, "unresolved_revision_reference")
				result[m.RevisionID] = l
				continue
			}
			l := result[targets[0].RevisionID]
			l.State = "superseded"
			if m.Type == "Cancel" {
				l.State = "cancelled"
			}
			l.ReplacedBy = append(l.ReplacedBy, m.RevisionID)
			result[targets[0].RevisionID] = l
		}
	}
	return result
}

// Evaluate accepts exact geometry intersections supplied by PostGIS (point or timed route).
// Missing geometry remains potential relevance; warnings win over incomplete other sources.
func Evaluate(s Snapshot, start, end time.Time, intersects map[string]map[int]bool) State {
	out := State{Status: "unknown", AsOf: s.AsOf, Start: start, End: end, Warnings: []Warning{}, Unknown: append([]string{}, s.Issues...), Sources: s.Sources}
	complete := len(s.Sources) > 0
	for _, src := range s.Sources {
		if src.Coverage != "verified_complete" {
			complete = false
			out.Unknown = append(out.Unknown, src.ID+":"+src.Coverage)
		}
	}
	for _, b := range s.Items {
		m := b.Message
		l := b.Lifecycle
		if !m.Operational {
			continue
		}
		if len(l.Issues) > 0 {
			out.Unknown = append(out.Unknown, m.RevisionID+":revision_ambiguity")
		}
		if l.State != "active" {
			continue
		}
		if m.Sent.After(s.AsOf.Add(5 * time.Minute)) {
			out.Unknown = append(out.Unknown, m.RevisionID+":future_issued")
			continue
		}
		if len(m.Infos) == 0 {
			out.Unknown = append(out.Unknown, m.RevisionID+":missing_info")
		}
		for ii, info := range m.Infos {
			if info.Effective.After(end) || (info.Expires != nil && !info.Expires.After(start)) {
				continue
			}
			if info.Expires == nil || !info.Expires.After(info.Effective) || len(info.Issues) > 0 {
				out.Unknown = append(out.Unknown, m.RevisionID+":unknown_validity_or_classification")
				continue
			}
			unknown := len(info.Areas) == 0
			for _, a := range info.Areas {
				unknown = unknown || len(a.Unresolved) > 0
			}
			if unknown {
				out.Unknown = append(out.Unknown, m.RevisionID+":unresolved_geometry")
			}
			if intersects[m.RevisionID][ii] {
				out.Warnings = append(out.Warnings, Warning{m.RevisionID, m.SourceID, info.Event, info.Severity, info.Effective, info.Expires, ii})
			}
		}
	}
	sort.Strings(out.Unknown)
	unique := out.Unknown[:0]
	for _, v := range out.Unknown {
		if len(unique) == 0 || unique[len(unique)-1] != v {
			unique = append(unique, v)
		}
	}
	out.Unknown = unique
	if len(out.Warnings) > 0 {
		out.Status = "official_warning"
	} else if complete && len(out.Unknown) == 0 && s.ProductionApproved {
		out.Status = "known_none_intersecting"
		out.ProductionApproved = true
	}
	return out
}
func FiniteCoordinate(lon, lat float64) bool {
	return !math.IsNaN(lon+lat) && !math.IsInf(lon+lat, 0) && lon >= -180 && lon <= 180 && lat >= -90 && lat <= 90
}
