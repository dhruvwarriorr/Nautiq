// Package trips implements deterministic rules over frozen official and forecast inputs.
package trips

import (
	"crypto/sha256"
	"embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"math"
	"sort"
)

//go:embed policy.json engine.go route.go policy.go
var sources embed.FS

type InputSpec struct {
	Variable  string   `json:"variable"`
	ProductID string   `json:"product_id"`
	Units     string   `json:"units"`
	Required  bool     `json:"required"`
	MaxAge    float64  `json:"max_cycle_age_hours"`
	Caution   *float64 `json:"caution"`
	Critical  *float64 `json:"critical"`
	Origin    string   `json:"origin"`
}
type Condition struct {
	Variable string  `json:"variable"`
	AtLeast  float64 `json:"at_least"`
}
type Combination struct {
	ID      string      `json:"id"`
	All     []Condition `json:"all"`
	Verdict string      `json:"verdict"`
}
type Deterioration struct {
	ID            string  `json:"id"`
	Variable      string  `json:"variable"`
	ChangeAtLeast float64 `json:"change_at_least"`
	WithinMinutes float64 `json:"within_minutes"`
}
type Policy struct {
	Version       string          `json:"version"`
	Method        string          `json:"method_version"`
	Approved      bool            `json:"approved"`
	Review        string          `json:"review_record"`
	Activities    []string        `json:"activities"`
	Inequality    string          `json:"inequality"`
	MaxHorizon    float64         `json:"max_horizon_hours"`
	Inputs        []InputSpec     `json:"inputs"`
	Combinations  []Combination   `json:"combinations"`
	Deterioration []Deterioration `json:"deterioration"`
	Limitations   []string        `json:"limitations"`
}
type Preference struct {
	Caution  *float64 `json:"caution"`
	Critical *float64 `json:"critical"`
}

func DefaultPolicy() Policy {
	data, _ := sources.ReadFile("policy.json")
	var p Policy
	if json.Unmarshal(data, &p) != nil {
		panic("invalid embedded policy")
	}
	return p
}
func CodeSHA() string {
	h := sha256.New()
	for _, name := range []string{"engine.go", "policy.go", "policy.json", "route.go"} {
		data, _ := sources.ReadFile(name)
		h.Write([]byte(name))
		h.Write(data)
	}
	return hex.EncodeToString(h.Sum(nil))
}
func Hash(value any) string {
	data, _ := json.Marshal(value)
	h := sha256.Sum256(data)
	return hex.EncodeToString(h[:])
}
func finite(n float64) bool { return !math.IsNaN(n) && !math.IsInf(n, 0) }
func (p Policy) Available() bool {
	if !p.Approved || p.Review == "" || p.Version == "" || p.Method == "" || p.Inequality != "value >= limit" || !finite(p.MaxHorizon) || p.MaxHorizon <= 0 || p.MaxHorizon > 24 || len(p.Inputs) == 0 || len(p.Inputs) > 3 || len(p.Activities) == 0 {
		return false
	}
	seen := map[string]bool{}
	for _, s := range p.Inputs {
		if seen[s.Variable] || s.Units == "" || s.ProductID == "" || !finite(s.MaxAge) || s.MaxAge <= 0 || s.Caution == nil || s.Critical == nil || !finite(*s.Caution) || !finite(*s.Critical) || *s.Caution < 0 || *s.Critical < *s.Caution || s.Origin != "reviewed_policy" {
			return false
		}
		seen[s.Variable] = true
	}
	if len(p.Combinations) > 16 || len(p.Deterioration) > 16 {
		return false
	}
	ids := map[string]bool{}
	for _, c := range p.Combinations {
		if c.ID == "" || ids[c.ID] || len(c.All) < 2 || len(c.All) > 3 || (c.Verdict != "unfavorable" && c.Verdict != "caution") {
			return false
		}
		ids[c.ID] = true
		for _, term := range c.All {
			if !seen[term.Variable] || !finite(term.AtLeast) || term.AtLeast < 0 {
				return false
			}
		}
	}
	for _, d := range p.Deterioration {
		if d.ID == "" || ids[d.ID] || !seen[d.Variable] || !finite(d.ChangeAtLeast) || d.ChangeAtLeast <= 0 || !finite(d.WithinMinutes) || d.WithinMinutes <= 0 || d.WithinMinutes > 1440 {
			return false
		}
		ids[d.ID] = true
	}
	return true
}
func (p Policy) WithPreferences(preferences map[string]Preference) (Policy, error) {
	data, _ := json.Marshal(p)
	var out Policy
	json.Unmarshal(data, &out)
	if len(preferences) > 0 && !p.Available() {
		return out, errors.New("preferences_require_approved_policy")
	}
	keys := make([]string, 0, len(preferences))
	for k := range preferences {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, variable := range keys {
		pref := preferences[variable]
		found := false
		for i, s := range out.Inputs {
			if s.Variable != variable {
				continue
			}
			found = true
			if pref.Caution != nil {
				if !finite(*pref.Caution) || *pref.Caution < 0 || *pref.Caution > *s.Caution {
					return out, errors.New("preference_cannot_relax_policy")
				}
				out.Inputs[i].Caution = pref.Caution
			}
			if pref.Critical != nil {
				if !finite(*pref.Critical) || *pref.Critical < 0 || *pref.Critical > *s.Critical {
					return out, errors.New("preference_cannot_relax_policy")
				}
				out.Inputs[i].Critical = pref.Critical
			}
			if *out.Inputs[i].Critical < *out.Inputs[i].Caution {
				return out, errors.New("preference_threshold_order")
			}
		}
		if !found {
			return out, errors.New("unknown_preference_variable")
		}
	}
	return out, nil
}

func HashRaw(data []byte) string { hash := sha256.Sum256(data); return hex.EncodeToString(hash[:]) }
