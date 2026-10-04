package science

import (
	"bytes"
	"encoding/json"
	"math"
	"net/http"
	"net/url"
)

// CategoryPolicyVersion identifies the display-category policy. The category is a readable summary of
// stored empirical ranks. It is not a probability, an event, an alert or a scientific approval.
const CategoryPolicyVersion = "profile-evidence-category-v1"

// Fixed engineering bands, not validated alert thresholds. The strongest band needs a reference large
// enough to resolve the 99.5th percentile.
const (
	elevatedFrom  = 90.0
	unusualFrom   = 97.5
	strongFrom    = 99.5
	minReference  = 20
	strongMinRefs = 200
	coarseResolve = 2.0
)

var categoryLabels = map[string]string{
	"typical":          "Typical",
	"elevated":         "Elevated",
	"unusual":          "Unusual",
	"strongly_unusual": "Strongly unusual",
	"not_assessable":   "Not assessable",
}
var categoryOrder = map[string]int{"not_assessable": -1, "typical": 0, "elevated": 1, "unusual": 2, "strongly_unusual": 3}

// Component is one separately inspectable piece of evidence behind a category.
type Component struct {
	Key        string   `json:"key"`
	Label      string   `json:"label"`
	Percentile *float64 `json:"percentile"`
}

// VariableCategory is the per-variable summary.
type VariableCategory struct {
	Category          string      `json:"category"`
	Label             string      `json:"label"`
	Primary           string      `json:"primary_measure"`
	PrimaryPercentile *float64    `json:"primary_percentile"`
	Components        []Component `json:"components"`
	ReferenceProfiles int         `json:"reference_profiles"`
	ResolutionPercent *float64    `json:"resolution_percent"`
	CoarseResolution  bool        `json:"coarse_resolution"`
	RegionalFallback  bool        `json:"regional_fallback"`
	StructureFlag     bool        `json:"unusual_structure"`
	Notes             []string    `json:"notes"`
}

var componentLabels = []Component{
	{Key: "mahalanobis_squared", Label: "Residual-profile distance (primary)"},
	{Key: "weighted_squared_residual", Label: "Depth-weighted squared residual"},
	{Key: "fpca_distance_squared", Label: "Profile-shape (PCA score) distance"},
	{Key: "fpca_reconstruction_error", Label: "PCA reconstruction error"},
}

// Categorize turns one variable's stored ranks into a display category.
func Categorize(status string, group *string, fallback bool, profiles int, resolution *float64, values map[string]*float64) VariableCategory {
	out := VariableCategory{Primary: "mahalanobis_squared", ReferenceProfiles: profiles, ResolutionPercent: resolution, RegionalFallback: fallback, Components: []Component{}, Notes: []string{}}
	for _, c := range componentLabels {
		c.Percentile = values[c.Key]
		out.Components = append(out.Components, c)
	}
	out.PrimaryPercentile = values["mahalanobis_squared"]
	finish := func(cat string) VariableCategory {
		out.Category = cat
		out.Label = categoryLabels[cat]
		return out
	}
	if status != "diagnostic" || out.PrimaryPercentile == nil || math.IsNaN(*out.PrimaryPercentile) {
		out.Notes = append(out.Notes, "No complete, supported 10–500 m profile score is available, so no category is assigned.")
		return finish("not_assessable")
	}
	if profiles < minReference {
		out.Notes = append(out.Notes, "Too few separate reference profiles to rank this profile; no category is assigned.")
		return finish("not_assessable")
	}
	p := *out.PrimaryPercentile
	cat := "typical"
	switch {
	case p >= strongFrom && profiles >= strongMinRefs:
		cat = "strongly_unusual"
	case p >= unusualFrom:
		cat = "unusual"
	case p >= elevatedFrom:
		cat = "elevated"
	}
	if p >= strongFrom && profiles < strongMinRefs {
		out.Notes = append(out.Notes, "The reference is too small to resolve the strongest band, so the category is capped at Unusual.")
	}
	if resolution != nil && *resolution > coarseResolve {
		out.CoarseResolution = true
		out.Notes = append(out.Notes, "Rank resolution is coarse: one reference profile moves the percentile by more than two points.")
	}
	if fallback {
		out.Notes = append(out.Notes, "Regional comparison support is sparse; the rank uses the global group.")
	}
	if s := values["fpca_distance_squared"]; s != nil && *s >= unusualFrom || values["fpca_reconstruction_error"] != nil && *values["fpca_reconstruction_error"] >= unusualFrom {
		out.StructureFlag = true
		out.Notes = append(out.Notes, "The profile’s vertical shape ranks high even if its overall magnitude does not.")
	}
	return finish(cat)
}

// Combined is the whole-profile summary: the highest assessable variable category.
type Combined struct {
	PolicyVersion  string                      `json:"policy_version"`
	Category       string                      `json:"category"`
	Label          string                      `json:"label"`
	Variable       *string                     `json:"driving_variable"`
	Variables      map[string]VariableCategory `json:"variables"`
	Bands          map[string]float64          `json:"band_lower_bounds_percentile"`
	Interpretation string                      `json:"interpretation"`
}

// Combine derives the profile-level category from anomaly comparison JSON. It never invents a rank.
func Combine(result json.RawMessage) *Combined {
	var r struct {
		Variables map[string]struct {
			Status      string `json:"status"`
			Percentiles *struct {
				Group      *string             `json:"group"`
				Fallback   bool                `json:"fallback"`
				Profiles   int                 `json:"profiles"`
				Resolution *float64            `json:"resolution_percent"`
				Values     map[string]*float64 `json:"values"`
			} `json:"percentiles"`
		} `json:"variables"`
	}
	if json.Unmarshal(result, &r) != nil || len(r.Variables) == 0 {
		return nil
	}
	c := &Combined{PolicyVersion: CategoryPolicyVersion, Category: "not_assessable", Variables: map[string]VariableCategory{}, Bands: map[string]float64{"elevated": elevatedFrom, "unusual": unusualFrom, "strongly_unusual": strongFrom},
		Interpretation: "A readable summary of descriptive ranks against retained history. Not a probability, an event, an alert or a safety statement."}
	for name, v := range r.Variables {
		var group *string
		fallback, n := false, 0
		var res *float64
		var values map[string]*float64
		if v.Percentiles != nil {
			group, fallback, n, res, values = v.Percentiles.Group, v.Percentiles.Fallback, v.Percentiles.Profiles, v.Percentiles.Resolution, v.Percentiles.Values
		}
		vc := Categorize(v.Status, group, fallback, n, res, values)
		c.Variables[name] = vc
		if categoryOrder[vc.Category] > categoryOrder[c.Category] {
			n := name
			c.Category, c.Variable = vc.Category, &n
		}
	}
	c.Label = categoryLabels[c.Category]
	return c
}

// profileAnomaly adds the derived category to the stored comparison; the stored result is unchanged.
func (s *Server) profileAnomaly(w http.ResponseWriter, r *http.Request) {
	raw, status := compose(r, s.profileAnomalyStored, url.Values{})
	if status != 200 {
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Cache-Control", "no-store")
		w.WriteHeader(status)
		w.Write(raw)
		return
	}
	var doc map[string]json.RawMessage
	if json.Unmarshal(raw, &doc) != nil {
		problem(w, 503, "evidence_unavailable")
		return
	}
	if result, ok := doc["result"]; ok && !bytes.Equal(bytes.TrimSpace(result), []byte("null")) {
		if c := Combine(result); c != nil {
			b, _ := json.Marshal(c)
			doc["combined_evidence"] = b
		}
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	json.NewEncoder(w).Encode(doc)
}
