// Pure decision fixtures; numeric limits here are synthetic and never a release policy.
package main

import (
	"encoding/json"
	"fmt"
	"math"
	"nautiq.local/api/internal/trips"
	"strings"
	"time"
)

func check(ok bool, label string) {
	if !ok {
		panic("trip contract: " + label)
	}
}
func ptr(value float64) *float64 { return &value }
func fixture() trips.Input {
	now, _ := time.Parse(time.RFC3339, "2026-10-03T02:00:00Z")
	req := trips.Request{Activity: "fishing", ThresholdVersion: "synthetic-review-fixture", Waypoints: []trips.Point{{Latitude: 12, Longitude: 72, Time: now.Add(time.Hour)}, {Latitude: 12.05, Longitude: 72.05, Time: now.Add(2 * time.Hour)}, {Latitude: 12, Longitude: 72, Time: now.Add(3 * time.Hour)}}, SpacingKM: 5, StepMinutes: 30, Preferences: map[string]trips.Preference{}}
	p := trips.DefaultPolicy()
	p.Version = req.ThresholdVersion
	p.Approved = true
	p.Review = "isolated synthetic verification fixture; never production approval"
	for i := range p.Inputs {
		p.Inputs[i].Caution = ptr(2)
		p.Inputs[i].Critical = ptr(4)
		p.Inputs[i].Origin = "default_policy"
	}
	points, sampling, err := trips.Points(req, now)
	check(err == nil, "fixture route")
	input := trips.Input{AsOf: now, Request: req, Policy: p, Expected: points, Sampling: sampling, Fields: []trips.Field{}, AcquisitionIssues: []string{}}
	cycle := now.Add(-time.Hour)
	for _, spec := range p.Inputs {
		if !spec.Required {
			continue
		}
		f := trips.Field{Variable: spec.Variable, ProductID: spec.ProductID, ReleaseID: "synthetic", ManifestSHA: strings.Repeat("a", 64), EvidenceSHA: strings.Repeat("b", 64), Cycle: &cycle, ValidStart: now, ValidEnd: now.Add(24 * time.Hour), OperationalApproved: true, Samples: []trips.Sample{}}
		for _, point := range points {
			f.Samples = append(f.Samples, trips.Sample{Point: point, Value: ptr(1), Units: spec.Units, Status: "available"})
		}
		input.Fields = append(input.Fields, f)
	}
	return input
}
func clone(input trips.Input) trips.Input {
	data, _ := json.Marshal(input)
	var out trips.Input
	check(json.Unmarshal(data, &out) == nil, "clone")
	return out
}
func main() {
	base := fixture()
	check(trips.DefaultPolicy().Available(), "default limits are usable")
	check(trips.Evaluate(base).Status == "favorable", "fully supported fixture")
	for _, entry := range []struct {
		value  float64
		status string
	}{{2, "caution"}, {4, "unfavorable"}} {
		i := clone(base)
		i.Fields[0].Samples[0].Value = ptr(entry.value)
		v := trips.Evaluate(i)
		check(v.Status == entry.status && v.Worst[0].Value == entry.value && len(v.Rules) > 0, "inclusive threshold equality")
	}
	missing := clone(base)
	missing.Fields[0].Samples[0].Value = ptr(5)
	missing.Fields[1].Samples[0].Status = "masked"
	v := trips.Evaluate(missing)
	check(v.Status == "insufficient_data" && v.Worst[0].Value == 5 && v.Rules[0].Verdict == "unfavorable", "missing priority retains adverse evidence")
	noPolicy := clone(base)
	noPolicy.Policy.Approved = false
	check(trips.Evaluate(noPolicy).Status == "insufficient_data" && !trips.Evaluate(noPolicy).EngineAvailable, "unapproved release")
	for _, mutate := range []func(*trips.Input){func(i *trips.Input) { i.Fields[0].Cycle = nil }, func(i *trips.Input) { old := i.AsOf.Add(-100 * time.Hour); i.Fields[0].Cycle = &old }, func(i *trips.Input) { i.Fields[0].Samples = i.Fields[0].Samples[:1] }, func(i *trips.Input) { i.Fields[0].Samples[0].Units = "knots" }, func(i *trips.Input) { i.Fields[0].ValidEnd = i.AsOf }, func(i *trips.Input) { i.Fields = append(i.Fields, i.Fields[0]) }, func(i *trips.Input) { i.Expected[0].Longitude = 73 }} {
		i := clone(base)
		mutate(&i)
		check(trips.Evaluate(i).Status == "insufficient_data", "required evidence refusal")
	}
	pref := clone(base)
	pref.Request.Preferences = map[string]trips.Preference{"wave_height_m": {Caution: ptr(1), Critical: ptr(3)}}
	pref.Fields[0].Samples[0].Value = ptr(3)
	v = trips.Evaluate(pref)
	check(v.Status == "unfavorable" && v.Rules[0].Origin == "personal_preference", "tightening preference")
	for _, p := range []map[string]trips.Preference{{"wave_height_m": {Critical: ptr(5)}}, {"wave_height_m": {Caution: ptr(2), Critical: ptr(1)}}, {"unknown": {Caution: ptr(1)}}} {
		_, err := base.Policy.WithPreferences(p)
		check(err != nil, "cannot relax or bypass")
	}
	tight, err := base.Policy.WithPreferences(map[string]trips.Preference{"wave_height_m": {Critical: ptr(1)}})
	check(err == nil && *tight.Inputs[0].Caution == 1 && *tight.Inputs[0].Critical == 1, "a stricter critical limit pulls caution down")
	combo := clone(base)
	combo.Policy.Combinations = []trips.Combination{{ID: "combined", Verdict: "caution", All: []trips.Condition{{Variable: "wave_height_m", AtLeast: 1}, {Variable: "wind_speed_m_s", AtLeast: 1}}}}
	check(trips.Evaluate(combo).Status == "caution", "reviewed combination")
	trend := clone(base)
	trend.Policy.Deterioration = []trips.Deterioration{{ID: "rising", Variable: "wave_height_m", ChangeAtLeast: 0.5, WithinMinutes: 30}}
	trend.Fields[0].Samples[1].Value = ptr(1.5)
	check(trips.Evaluate(trend).Status == "caution", "reviewed deterioration")
	stop := base.Request
	stop.Waypoints = append([]trips.Point{stop.Waypoints[0], {Latitude: 12, Longitude: 72, Time: stop.Waypoints[0].Time.Add(30 * time.Minute)}}, stop.Waypoints[1:]...)
	points, _, err := trips.Points(stop, base.AsOf)
	check(err == nil && points[0].Latitude == points[1].Latitude, "stationary stop retained")
	for _, mutate := range []func(*trips.Request){func(r *trips.Request) { r.Waypoints[0].Latitude = math.NaN() }, func(r *trips.Request) { r.Waypoints[1].Time = r.Waypoints[0].Time }, func(r *trips.Request) { r.Waypoints[1].Longitude = -179 }, func(r *trips.Request) { r.StepMinutes = 0 }, func(r *trips.Request) { r.Waypoints[0].Time = base.AsOf.Add(-time.Hour) }} {
		copy := clone(base).Request
		mutate(&copy)
		_, _, err = trips.Points(copy, base.AsOf)
		check(err != nil, "route refusal")
	}
	budget := clone(base).Request
	budget.Waypoints = []trips.Point{{Latitude: 12, Longitude: 72, Time: base.AsOf.Add(time.Hour)}, {Latitude: 12, Longitude: 72, Time: base.AsOf.Add(25 * time.Hour)}}
	budget.StepMinutes = 1
	_, _, err = trips.Points(budget, base.AsOf)
	check(err != nil, "sample budget never coarsens")
	for _, input := range []trips.Input{base, missing, noPolicy, pref, combo, trend} {
		v := trips.Evaluate(input)
		data, _ := json.Marshal(input)
		var restored trips.Input
		json.Unmarshal(data, &restored)
		check(trips.Hash(v) == trips.Hash(trips.Evaluate(restored)), "exact stored-input replay")
		lower := strings.ToLower(v.Wording)
		check(!strings.Contains(lower, "safe") && !strings.Contains(lower, "guarantee") && !strings.Contains(lower, "all clear"), "safety wording")
	}
	check(len(trips.CodeSHA()) == 64, "embedded code fingerprint")
	fmt.Println("Trip Go contracts passed: all four verdicts, equality, missing precedence, preserved adverse samples, source/route/approval refusal, preferences, combinations, deterioration, exact replay and safety wording.")
}
