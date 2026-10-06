package trips

import (
	"math"
	"sort"
	"time"
)

type Sample struct {
	Point  Point    `json:"point"`
	Value  *float64 `json:"value"`
	Units  string   `json:"units"`
	Status string   `json:"status"`
	Reason string   `json:"reason"`
}
type Field struct {
	Variable            string     `json:"variable"`
	ProductID           string     `json:"product_id"`
	ReleaseID           string     `json:"release_id"`
	ManifestSHA         string     `json:"manifest_sha256"`
	CalculationID       string     `json:"calculation_id"`
	Cycle               *time.Time `json:"cycle"`
	ValidStart          time.Time  `json:"valid_time_start"`
	ValidEnd            time.Time  `json:"valid_time_end"`
	OperationalApproved bool       `json:"operational_approved"`
	Samples             []Sample   `json:"samples"`
	Error               string     `json:"error"`
	EvidenceSHA         string     `json:"evidence_sha256"`
}
type Input struct {
	AsOf              time.Time `json:"as_of"`
	Request           Request   `json:"request"`
	Policy            Policy    `json:"policy"`
	Expected          []Point   `json:"expected_points"`
	Sampling          Sampling  `json:"sampling"`
	Fields            []Field   `json:"fields"`
	AcquisitionIssues []string  `json:"acquisition_issues"`
}
type Rule struct {
	ID       string   `json:"rule_id"`
	Verdict  string   `json:"verdict"`
	Variable string   `json:"variable"`
	Origin   string   `json:"origin"`
	Value    *float64 `json:"value"`
	Limit    *float64 `json:"limit"`
	Units    string   `json:"units"`
	Point    *Point   `json:"point"`
	Evidence string   `json:"evidence"`
}
type Worst struct {
	Variable string  `json:"variable"`
	Value    float64 `json:"value"`
	Units    string  `json:"units"`
	Point    Point   `json:"point"`
	Status   string  `json:"sample_status"`
}
type Cycle struct {
	Variable    string     `json:"variable"`
	ReleaseID   string     `json:"release_id"`
	Cycle       *time.Time `json:"cycle"`
	ManifestSHA string     `json:"manifest_sha256"`
	EvidenceSHA string     `json:"evidence_sha256"`
}
type Verdict struct {
	Status             string    `json:"status"`
	EngineAvailable    bool      `json:"engine_available"`
	Rules              []Rule    `json:"rules_fired"`
	Worst              []Worst   `json:"worst_samples"`
	Missing            []string  `json:"missing_inputs"`
	Cycles             []Cycle   `json:"source_cycles"`
	ThresholdVersion   string    `json:"threshold_version"`
	MethodVersion      string    `json:"method_version"`
	AsOf               time.Time `json:"as_of"`
	Sampling           Sampling  `json:"sampling"`
	Limitations        []string  `json:"limitations"`
	Wording            string    `json:"wording"`
	ProductionApproved bool      `json:"production_approved"`
}

func near(a, b Point) bool {
	return math.Abs(a.Latitude-b.Latitude) < 1e-7 && math.Abs(a.Longitude-b.Longitude) < 1e-7 && math.Abs(float64(a.Time.Sub(b.Time))) <= float64(time.Millisecond)
}
func Evaluate(input Input) Verdict {
	effective, err := input.Policy.WithPreferences(input.Request.Preferences)
	out := Verdict{Status: "insufficient_data", EngineAvailable: input.Policy.Available(), Rules: []Rule{}, Worst: []Worst{}, Missing: append([]string{}, input.AcquisitionIssues...), Cycles: []Cycle{}, ThresholdVersion: input.Policy.Version, MethodVersion: input.Policy.Method, AsOf: input.AsOf, Sampling: input.Sampling, Limitations: append([]string{}, input.Policy.Limitations...)}
	if len(input.Request.Waypoints) < 2 {
		out.Missing = append(out.Missing, "timed_waypoints_required")
		out.Wording = "The trip cannot be assessed because timed route evidence is unavailable."
		return out
	}

	if err != nil {
		out.Missing = append(out.Missing, err.Error())
		effective = input.Policy
		out.EngineAvailable = false
	}
	if !out.EngineAvailable {
		out.Missing = append(out.Missing, "threshold_release_unapproved_or_invalid")
	}
	activity := false
	for _, a := range effective.Activities {
		activity = activity || a == input.Request.Activity
	}
	if !activity {
		out.Missing = append(out.Missing, "activity_not_in_threshold_release")
	}
	if input.Request.ThresholdVersion != effective.Version {
		out.Missing = append(out.Missing, "threshold_version_mismatch")
	}
	points, sampling, routeErr := Points(input.Request, input.AsOf)
	if routeErr != nil || len(points) != len(input.Expected) || sampling.SampleCount != input.Sampling.SampleCount {
		out.Missing = append(out.Missing, "route_sampling_unresolved")
	} else {
		for i, p := range points {
			if !near(p, input.Expected[i]) {
				out.Missing = append(out.Missing, "route_sampling_projection_mismatch")
				break
			}
		}
	}
	if effective.MaxHorizon <= 0 || input.Request.Waypoints[len(input.Request.Waypoints)-1].Time.Sub(input.Request.Waypoints[0].Time) > time.Duration(effective.MaxHorizon*float64(time.Hour)) {
		out.Missing = append(out.Missing, "policy_trip_horizon")
	}
	fields := map[string]Field{}
	for _, f := range input.Fields {
		if _, ok := fields[f.Variable]; ok {
			out.Missing = append(out.Missing, f.Variable+":multiple_cycles")
		}
		fields[f.Variable] = f
		out.Cycles = append(out.Cycles, Cycle{f.Variable, f.ReleaseID, f.Cycle, f.ManifestSHA, f.EvidenceSHA})
	}
	critical, caution := false, false
	for _, spec := range effective.Inputs {
		f, exists := fields[spec.Variable]
		if !exists || f.Error != "" {
			if spec.Required {
				reason := "missing"
				if f.Error != "" {
					reason = f.Error
				}
				out.Missing = append(out.Missing, spec.Variable+":"+reason)
			}
			continue
		}
		if f.ProductID != spec.ProductID || f.ReleaseID == "" || len(f.ManifestSHA) != 64 {
			out.Missing = append(out.Missing, spec.Variable+":source_pin_mismatch")
		}
		stale := f.Cycle == nil || f.Cycle.After(input.AsOf) || input.AsOf.Sub(*f.Cycle) > time.Duration(spec.MaxAge*float64(time.Hour))
		if spec.Required && stale {
			out.Missing = append(out.Missing, spec.Variable+":source_cycle_missing_or_stale")
		}
		if spec.Required && (f.ValidStart.After(input.Request.Waypoints[0].Time) || f.ValidEnd.Before(input.Request.Waypoints[len(input.Request.Waypoints)-1].Time)) {
			out.Missing = append(out.Missing, spec.Variable+":outside_forecast_horizon")
		}
		if spec.Required && len(f.Samples) != len(input.Expected) {
			out.Missing = append(out.Missing, spec.Variable+":incomplete_route_samples")
		}
		var worst *Worst
		for index, s := range f.Samples {
			valid := s.Value != nil && finite(*s.Value) && *s.Value >= 0 && s.Units == spec.Units
			if spec.Required && (s.Status != "available" || !valid || index >= len(input.Expected) || !near(s.Point, input.Expected[index])) {
				out.Missing = append(out.Missing, spec.Variable+":unsupported_sample")
			}
			if !valid {
				continue
			}
			if worst == nil || *s.Value > worst.Value {
				worst = &Worst{spec.Variable, *s.Value, s.Units, s.Point, s.Status}
			}
			if out.EngineAvailable && spec.Critical != nil && *s.Value >= *spec.Critical {
				critical = true
				point := s.Point
				origin := "default_policy"
				if pref, ok := input.Request.Preferences[spec.Variable]; ok && pref.Critical != nil {
					origin = "personal_preference"
				}
				out.Rules = append(out.Rules, Rule{spec.Variable + ":critical", "unfavorable", spec.Variable, origin, s.Value, spec.Critical, s.Units, &point, "sample retained even when other required evidence is missing or stale"})
			} else if out.EngineAvailable && spec.Caution != nil && *s.Value >= *spec.Caution {
				caution = true
				point := s.Point
				origin := "default_policy"
				if pref, ok := input.Request.Preferences[spec.Variable]; ok && pref.Caution != nil {
					origin = "personal_preference"
				}
				out.Rules = append(out.Rules, Rule{spec.Variable + ":caution", "caution", spec.Variable, origin, s.Value, spec.Caution, s.Units, &point, "sample threshold reached"})
			}
		}
		if worst != nil {
			out.Worst = append(out.Worst, *worst)
		}
	}
	if out.EngineAvailable {
		for _, combo := range effective.Combinations {
			for _, term := range combo.All {
				f, ok := fields[term.Variable]
				if !ok || f.Error != "" || len(f.Samples) != len(input.Expected) {
					out.Missing = append(out.Missing, combo.ID+":missing_or_unsupported_input")
					continue
				}
				for _, sample := range f.Samples {
					if sample.Value == nil || !finite(*sample.Value) || sample.Status != "available" {
						out.Missing = append(out.Missing, combo.ID+":missing_or_unsupported_input")
						break
					}
				}
			}
			for index, p := range input.Expected {
				met := true
				for _, term := range combo.All {
					f, ok := fields[term.Variable]
					if !ok || len(f.Samples) <= index || f.Samples[index].Value == nil || !finite(*f.Samples[index].Value) || !near(f.Samples[index].Point, p) || *f.Samples[index].Value < term.AtLeast {
						met = false
						break
					}
				}
				if met {
					point := p
					out.Rules = append(out.Rules, Rule{ID: combo.ID, Verdict: combo.Verdict, Origin: "default_policy", Point: &point, Evidence: "all combination terms reached at the same retained route sample"})
					critical = critical || combo.Verdict == "unfavorable"
					caution = caution || combo.Verdict == "caution"
				}
			}
		}
		for _, d := range effective.Deterioration {
			f, ok := fields[d.Variable]
			if !ok || f.Error != "" || len(f.Samples) != len(input.Expected) {
				out.Missing = append(out.Missing, d.ID+":missing_or_unsupported_input")
			} else {
				for _, sample := range f.Samples {
					if sample.Value == nil || !finite(*sample.Value) || sample.Status != "available" {
						out.Missing = append(out.Missing, d.ID+":missing_or_unsupported_input")
						break
					}
				}
			}
			f, ok = fields[d.Variable]
			if !ok {
				continue
			}
			for i, a := range f.Samples {
				if a.Value == nil || !finite(*a.Value) {
					continue
				}
				for _, b := range f.Samples[i+1:] {
					delta := b.Point.Time.Sub(a.Point.Time)
					if delta <= 0 || delta > time.Duration(d.WithinMinutes*float64(time.Minute)) || b.Value == nil || !finite(*b.Value) {
						continue
					}
					change := *b.Value - *a.Value
					if change >= d.ChangeAtLeast {
						point := b.Point
						limit := d.ChangeAtLeast
						out.Rules = append(out.Rules, Rule{d.ID, "caution", d.Variable, "default_policy", &change, &limit, b.Units, &point, "reviewed increase over retained timed samples"})
						caution = true
						break
					}
				}
			}
		}
	}
	sort.Strings(out.Missing)
	unique := out.Missing[:0]
	for _, m := range out.Missing {
		if len(unique) == 0 || unique[len(unique)-1] != m {
			unique = append(unique, m)
		}
	}
	out.Missing = unique
	if len(out.Missing) > 0 {
		out.Status = "insufficient_data"
	} else if critical {
		out.Status = "unfavorable"
	} else if caution {
		out.Status = "caution"
	} else {
		out.Status = "favorable"
		out.ProductionApproved = true
	}
	wording := map[string]string{"insufficient_data": "The trip cannot be checked because a forecast is missing, out of date or does not cover the whole route.", "unfavorable": "Somewhere on the route the forecast reaches a “too rough” limit for this activity.", "caution": "Somewhere on the route the forecast reaches a caution limit for this activity.", "favorable": "The forecast stays within your limits along the whole route. Conditions between samples and local hazards are still uncertain."}
	out.Wording = wording[out.Status]
	return out
}
