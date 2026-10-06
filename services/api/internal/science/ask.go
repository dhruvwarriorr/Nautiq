package science

import (
	"encoding/json"
	"fmt"
	"io"
	"math"
	"net/http"
	"net/url"
	"sort"
	"strings"
	"time"

	"nautiq.local/api/internal/product"
)

// AnswerVersion identifies the template set. Answers are assembled only from structured results of
// existing typed endpoints; no free text from a language model reaches them.
const AnswerVersion = "structured-answer-v1"

type Fact struct {
	Label  string `json:"label"`
	Value  string `json:"value"`
	Detail string `json:"detail,omitempty"`
	Status string `json:"status"`
	Href   string `json:"href,omitempty"`
}
type AnswerLink struct {
	Label string `json:"label"`
	Href  string `json:"href"`
}
type Answer struct {
	Version  string                  `json:"version"`
	State    string                  `json:"state"`
	Headline string                  `json:"headline"`
	Facts    []Fact                  `json:"facts"`
	Cannot   []string                `json:"cannot_tell_you"`
	Links    []AnswerLink            `json:"links"`
	AsOf     time.Time               `json:"as_of"`
	Research *product.ResearchFilter `json:"research,omitempty"`
}

func (s *Server) answer(w http.ResponseWriter, r *http.Request) {
	if _, ok := query(w, r); !ok {
		return
	}
	if r.Header.Get("Content-Type") != "application/json" {
		problem(w, 415, "json_required")
		return
	}
	data, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 8192))
	var in struct {
		Frame product.Frame `json:"frame"`
		Zone  string        `json:"time_zone"`
	}
	if err != nil || product.Strict(data, &in) != nil {
		problem(w, 400, "invalid_or_duplicate_json")
		return
	}
	now := time.Now().UTC()
	plan, err := product.PlanFromFrame(in.Frame, in.Zone, now)
	if err != nil {
		problem(w, 400, err.Error())
		return
	}
	if plan.State != "ready" {
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Cache-Control", "no-store")
		json.NewEncoder(w).Encode(map[string]any{"plan": plan, "answer": nil})
		return
	}
	a := Answer{Version: AnswerVersion, State: "answered", Facts: []Fact{}, Cannot: []string{}, Links: []AnswerLink{}, AsOf: now}
	switch plan.Intent {
	case "conditions":
		s.conditionsAnswer(r, plan, &a)
	case "events":
		s.eventsAnswer(r, plan, &a)
	case "research":
		s.researchAnswer(r, plan, &a)
	case "trip":
		tripAnswer(plan, &a)
	case "explain":
		explainAnswer(plan, &a)
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	json.NewEncoder(w).Encode(map[string]any{"plan": plan, "answer": a})
}

type sampleResult struct {
	Value  *float64 `json:"value"`
	Units  string   `json:"units"`
	Status string   `json:"status"`
	Reason string   `json:"reason"`
	At     string   `json:"requested_time"`
}
type timelineEntry struct {
	Status string        `json:"status"`
	Reason string        `json:"reason"`
	Result *sampleResult `json:"result"`
}
type condField struct {
	Product  string          `json:"product_id"`
	Variable string          `json:"variable"`
	Cycle    *time.Time      `json:"cycle"`
	State    string          `json:"state"`
	Timeline []timelineEntry `json:"timeline"`
}

var fieldLabels = map[string][2]string{
	"sst_c":             {"Sea surface temperature (forecast)", "°C"},
	"wave_height_m":     {"Significant wave height (forecast)", "m"},
	"wind_speed_m_s":    {"Wind speed (forecast)", "m/s"},
	"current_speed_m_s": {"Surface current speed (forecast)", "m/s"},
}
var fieldOrder = []string{"sst_c", "wave_height_m", "wind_speed_m_s", "current_speed_m_s"}

func number(v float64) string {
	return strings.TrimRight(strings.TrimRight(fmt.Sprintf("%.2f", v), "0"), ".")
}

var reasonWords = map[string]string{
	"no_supported_valid_time":              "the time is outside the retained forecast",
	"outside_horizon":                      "the time is outside the retained forecast",
	"masked_or_unsupported_source_support": "the point is on land or outside the data’s support",
}

func say(reason string) string {
	if v, ok := reasonWords[reason]; ok {
		return v
	}
	return strings.ReplaceAll(reason, "_", " ")
}

// latestAnalysis samples a daily-analysis variable at the most recent days it can cover.
func (s *Server) latestAnalysis(r *http.Request, plan product.QueryPlan, variable string) (float64, time.Time, bool) {
	day := time.Now().UTC().Truncate(24 * time.Hour)
	for back := 0; back <= 3; back++ {
		at := day.AddDate(0, 0, -back).Add(12 * time.Hour)
		if at.After(time.Now()) {
			continue
		}
		raw, status := compose(r, s.conditions, url.Values{"latitude": {fstr(plan.Place.Latitude)}, "longitude": {fstr(plan.Place.Longitude)}, "time": {at.Format(time.RFC3339)}})
		if status != 200 {
			return 0, time.Time{}, false
		}
		var c struct {
			Fields []condField `json:"fields"`
		}
		if json.Unmarshal(raw, &c) != nil {
			return 0, time.Time{}, false
		}
		for _, f := range c.Fields {
			if f.Variable != variable || f.Cycle != nil {
				continue
			}
			for _, t := range f.Timeline {
				if t.Result != nil && t.Result.Value != nil {
					when, e := time.Parse(time.RFC3339Nano, t.Result.At)
					if e != nil {
						when = at
					}
					return *t.Result.Value, when, true
				}
			}
		}
	}
	return 0, time.Time{}, false
}

func (s *Server) conditionsAnswer(r *http.Request, plan product.QueryPlan, a *Answer) {
	start := plan.Window.Start
	raw, status := compose(r, s.conditions, url.Values{"latitude": {fstr(plan.Place.Latitude)}, "longitude": {fstr(plan.Place.Longitude)}, "time": {start}})
	slug := plan.Place.Slug
	a.Links = append(a.Links, AnswerLink{"Open the full location page", "/locations/" + slug}, AnswerLink{"Open the map", "/map"})
	if status != 200 {
		a.State = "unavailable"
		a.Headline = "Conditions for " + plan.Place.Name + " are unavailable right now."
		a.Facts = append(a.Facts, Fact{Label: "Evidence service", Value: "Unavailable", Status: "unavailable"})
		return
	}
	var c struct {
		Fields []condField `json:"fields"`
		Nearby []struct {
			ProfileID string    `json:"profile_id"`
			Observed  time.Time `json:"observed_at"`
			Distance  float64   `json:"distance_km"`
		} `json:"nearby_profiles"`
	}
	if json.Unmarshal(raw, &c) != nil {
		a.State = "unavailable"
		a.Headline = "Conditions evidence could not be read."
		return
	}
	byVar := map[string]condField{}
	for _, f := range c.Fields {
		byVar[f.Variable] = f
	}
	valued := 0
	for _, v := range fieldOrder {
		f, ok := byVar[v]
		meta := fieldLabels[v]
		if !ok {
			a.Facts = append(a.Facts, Fact{Label: meta[0], Value: "Unavailable", Detail: "No selected release.", Status: "unavailable", Href: "/fields"})
			continue
		}
		var first *sampleResult
		var firstAt, lastAt time.Time
		maxV := math.Inf(-1)
		count := 0
		reason := ""
		for _, t := range f.Timeline {
			if t.Result == nil {
				if reason == "" {
					reason = say(t.Reason)
				}
				continue
			}
			if t.Result.Value != nil {
				count++
				if at, e := time.Parse(time.RFC3339Nano, t.Result.At); e == nil {
					if first == nil {
						firstAt = at
					}
					lastAt = at
				}
				if first == nil {
					first = t.Result
				}
				maxV = math.Max(maxV, *t.Result.Value)
			} else if reason == "" {
				reason = say(firstNonEmpty(t.Result.Reason, t.Result.Status))
			}
		}
		cycle := "no forecast cycle (analysis)"
		if f.Cycle != nil {
			cycle = "forecast cycle " + f.Cycle.UTC().Format("2006-01-02 15:04 UTC")
		}
		if first == nil && f.Cycle == nil {
			// Daily analyses arrive a day late; show the newest one, clearly dated, instead of nothing.
			if v, at, ok := s.latestAnalysis(r, plan, v); ok {
				valued++
				a.Facts = append(a.Facts, Fact{Label: meta[0], Value: fmt.Sprintf("%s %s on %s (latest daily analysis)", number(v), meta[1], at.UTC().Format("2006-01-02")), Detail: "Daily analyses are published about a day late, so this is the most recent one, not a forecast for your time. Sampled at the place’s catalog point.", Status: "stale", Href: "/fields"})
				continue
			}
		}
		if first == nil {
			if f.Cycle == nil && strings.Contains(reason, "retained forecast") {
				reason = "the newest retained daily analysis does not cover this time (analyses are published with a delay)"
			}
			a.Facts = append(a.Facts, Fact{Label: meta[0], Value: "Unavailable", Detail: strings.TrimSpace(reason + ". Source: " + cycle + "."), Status: "unavailable", Href: "/fields"})
			continue
		}
		valued++
		st := "available"
		detail := cycle + ". Sampled at the place’s catalog point, not an average of the area."
		if f.State == "stale" {
			st = "stale"
			detail = "STALE: " + cycle + " is older than its allowed age; treat as historical, not current. " + detail
		}
		value := fmt.Sprintf("%s %s at %s", number(*first.Value), meta[1], strings.Replace(first.At[:min(len(first.At), 16)], "T", " ", 1)+" UTC")
		if count > 1 {
			value += fmt.Sprintf(" (highest of %d samples over %s h: %s %s)", count, number(lastAt.Sub(firstAt).Hours()), number(maxV), meta[1])
		}
		a.Facts = append(a.Facts, Fact{Label: meta[0], Value: value, Detail: detail, Status: st, Href: "/fields"})
	}
	if len(c.Nearby) > 0 {
		sort.Slice(c.Nearby, func(i, j int) bool { return c.Nearby[i].Distance < c.Nearby[j].Distance })
		n := c.Nearby[0]
		age := a.AsOf.Sub(n.Observed).Hours()
		a.Facts = append(a.Facts, Fact{Label: "Nearest original observation", Value: fmt.Sprintf("%d accepted Argo profile(s) within 100 km; nearest %s km away, observed %s (%s h ago)", len(c.Nearby), number(n.Distance), n.Observed.UTC().Format("2006-01-02 15:04 UTC"), number(age)), Detail: "Argo floats report their own position and depth; a profile is not the sea surface at this point.", Status: "available", Href: "/profiles/" + n.ProfileID})
	} else {
		a.Facts = append(a.Facts, Fact{Label: "Nearest original observation", Value: "No accepted Argo profile within 100 km in retained data.", Status: "unavailable", Href: "/profiles"})
	}
	a.Facts = append(a.Facts, Fact{Label: "Compared with normal", Value: "Not available at this point.", Detail: "A validated way to place a profile’s expected normal at an arbitrary point does not exist yet; expected-normal evidence is shown per Argo profile.", Status: "unavailable", Href: "/models"})
	switch {
	case valued == 0:
		a.State = "partial"
		a.Headline = "No usable forecast values for " + plan.Place.Name + " at the chosen time."
	case valued < len(fieldOrder):
		a.State = "partial"
		a.Headline = fmt.Sprintf("%d of %d sea-state measures are available for %s.", valued, len(fieldOrder), plan.Place.Name)
	default:
		a.Headline = "Sea state near " + plan.Place.Name + " from retained evidence."
	}
	a.Cannot = []string{"This is not a trip assessment or a safety judgement. Use the trip form for a timed route.", "Numbers are model or analysis values at a grid point, not a local measurement."}
}

func windowSource(w *product.ResolvedWindow) string {
	if w.Phrase == "explicit" {
		return "Taken from the dates you gave."
	}
	return "Resolved from “" + strings.ReplaceAll(w.Phrase, "_", " ") + "” in " + w.TimeZone + "."
}
func parseDay(v string) time.Time {
	t, _ := time.Parse(time.RFC3339, v)
	return t.UTC()
}
func firstNonEmpty(v ...string) string {
	for _, s := range v {
		if s != "" {
			return s
		}
	}
	return ""
}

func (s *Server) eventsAnswer(r *http.Request, plan product.QueryPlan, a *Answer) {
	a.Links = append(a.Links, AnswerLink{"Browse retained event runs", "/events"})
	q := url.Values{"limit": {"20"}}
	scope := "in the most recent retained runs"
	if plan.Place != nil {
		b := plan.Place.BBox
		q.Set("bbox", fstr(b[0])+","+fstr(b[1])+","+fstr(b[2])+","+fstr(b[3]))
		scope = "intersecting " + plan.Place.Name
	}
	if plan.Window != nil && (plan.Frame.When != "" && plan.Frame.When != "now" || plan.Frame.Start != "" && plan.Window.Phrase != "now") {
		a0, b0 := parseDay(plan.Window.Start), parseDay(plan.Window.End).Add(-time.Second)
		if b0.Before(a0) {
			b0 = a0
		}
		if b0.Sub(a0) <= 365*24*time.Hour {
			q.Set("start", a0.Format("2006-01-02"))
			q.Set("end", b0.Format("2006-01-02"))
			scope += " between " + a0.Format("2006-01-02") + " and " + b0.Format("2006-01-02")
		}
	}
	raw, status := compose(r, s.regionalEvents, q)
	var out struct {
		Items []json.RawMessage `json:"items"`
	}
	if status != 200 || json.Unmarshal(raw, &out) != nil {
		a.State = "unavailable"
		a.Headline = "Retained event evidence could not be read."
		return
	}
	a.Facts = append(a.Facts, Fact{Label: "Retained event candidates", Value: fmt.Sprintf("%d %s", len(out.Items), scope), Detail: "Diagnostic candidates, not approved events.", Status: "available", Href: "/events"})
	if len(out.Items) == 0 {
		a.Headline = "No retained event candidates."
	} else {
		a.Headline = fmt.Sprintf("%d retained event candidate(s).", len(out.Items))
	}
	a.Cannot = []string{"An empty list does not mean no event is happening: detection only covers retained, fixed-reference runs.", "A single unusual profile is not a regional event."}
}

func (s *Server) researchAnswer(r *http.Request, plan product.QueryPlan, a *Answer) {
	f := *plan.Research
	a.Research = &f
	a.Links = append(a.Links, AnswerLink{"Open in the research explorer", "/research"})
	rows, err := product.ResearchRows(r.Context(), s.DB, f)
	if err != nil {
		a.State = "unavailable"
		a.Headline = "Observed profiles could not be read."
		return
	}
	unit := "°C"
	if f.Variable == "practical_salinity" {
		unit = "PSS-78"
	}
	if len(rows) == 0 {
		a.State = "partial"
		a.Headline = "No accepted Argo profiles match this place and window."
		a.Facts = append(a.Facts, Fact{Label: "Profiles", Value: "0", Detail: "Sparse coverage is normal; widen the window or choose a larger region.", Status: "unavailable"})
		a.Cannot = []string{"No profiles means no retained observation, not that conditions were normal."}
		return
	}
	platforms := map[string]bool{}
	lo, hi := math.Inf(1), math.Inf(-1)
	var first, last time.Time
	unusual := 0
	for i, p := range rows {
		platforms[p.Platform] = true
		if p.Minimum != nil {
			lo = math.Min(lo, *p.Minimum)
		}
		if p.Maximum != nil {
			hi = math.Max(hi, *p.Maximum)
		}
		if i == 0 || p.Observed.Before(first) {
			first = p.Observed
		}
		if p.Observed.After(last) {
			last = p.Observed
		}
		if p.Percentile != nil && *p.Percentile >= 95 {
			unusual++
		}
	}
	capped := ""
	if len(rows) >= f.Limit {
		capped = " (first page; open the explorer for the rest)"
	}
	a.Headline = fmt.Sprintf("%d accepted Argo profile(s) from %d float(s)%s.", len(rows), len(platforms), capped)
	if f.MinimumPercentile != nil {
		a.Headline = fmt.Sprintf("%d unusual-ranked Argo profile(s) from %d float(s)%s.", len(rows), len(platforms), capped)
	}
	a.Facts = append(a.Facts,
		Fact{Label: "Observed", Value: first.UTC().Format("2006-01-02") + " to " + last.UTC().Format("2006-01-02"), Detail: "Each profile keeps its own position, time and depth.", Status: "available"},
		Fact{Label: "Value range over all levels", Value: number(lo) + " to " + number(hi) + " " + unit, Detail: "Extremes across original depth levels, not a surface value.", Status: "available"},
	)
	if f.MinimumPercentile != nil {
		a.Facts = append(a.Facts, Fact{Label: "Filter applied", Value: "Only profiles at or above the 95th diagnostic percentile", Detail: "A descriptive rank against retained history, not a probability or alert.", Status: "available", Href: "/anomalies"})
	} else if unusual > 0 {
		a.Facts = append(a.Facts, Fact{Label: "Ranked at or above the 95th diagnostic percentile", Value: fmt.Sprintf("%d of %d listed", unusual, len(rows)), Detail: "A descriptive rank against retained history, not a probability or alert.", Status: "available", Href: "/anomalies"})
	}
	a.Cannot = []string{"Profile ranks are diagnostic and unreviewed; they do not establish an event.", "Profiles are sparse: absence of unusual profiles does not mean conditions were normal."}
}

func tripAnswer(plan product.QueryPlan, a *Answer) {
	a.State = "handoff"
	a.Headline = "Nautiq can check a timed route, but not judge a trip from a sentence."
	href := "/trips"
	if plan.Trip != nil {
		v := url.Values{"lat": {fstr(plan.Trip.Latitude)}, "lon": {fstr(plan.Trip.Longitude)}, "place": {plan.Trip.Place}}
		if plan.Trip.Departure != "" {
			v.Set("depart", plan.Trip.Departure)
		}
		href = "/trips?" + v.Encode()
	}
	a.Facts = append(a.Facts,
		Fact{Label: "Why a form", Value: "Every leg needs a time and place so the forecasts can be checked along the whole route, outward and back.", Status: "available"},
		Fact{Label: "Current policy", Value: "Trips are checked against the wave, wind and current limits for your activity, which you can tighten in Advanced settings.", Status: "unknown", Href: "/methodology"},
	)
	a.Links = append(a.Links, AnswerLink{"Open the trip form with your place and time", href}, AnswerLink{"How trip results are decided", "/methodology"})
	a.Cannot = []string{"A trip check reads forecasts only; it does not know about official warnings, local hazards or your vessel."}
}

var explanations = map[string][3]string{
	"caution": {"Why a trip shows caution, insufficient data or unfavorable",
		"A trip result follows a fixed order: (1) missing, stale or out-of-range inputs give “insufficient data”, never a favorable result; (2) a critical threshold gives “unfavorable”; (3) a caution threshold or worsening forecast gives “caution”; (4) only a fully checked trip can be “favorable”. All fired rules stay visible.",
		"The limits are general defaults for small boats, not advice for your vessel. Set your own in Advanced settings."},
	"insufficient": {"What “insufficient data” means",
		"At least one required input could not be checked: a forecast is stale or does not cover the whole trip, a leg crosses land, or timing is unknown.",
		"It is not a mild form of “fine”. Open the trip evidence to see which input is missing."},
	"unusual": {"What an unusual profile means",
		"Nautiq compares each Argo profile with a fixed historical normal for that place and season, scales the differences by typical variability, and ranks the result against retained history. Components are shown by depth.",
		"“Unusual” is a descriptive rank, not a probability and not an event. A single profile is not a regional heatwave."},
	"expected": {"What expected normal means",
		"The expected normal is a harmonic seasonal climatology fitted on 2005–2016 Argo data. A machine-learning residual model is tested against it but has not qualified, so the climatology is what Nautiq shows.",
		"It is a conditional historical mean at an Argo profile’s own position and depth, not a forecast and not available at arbitrary points."},
	"interval": {"What an expected interval means",
		"The interval is the range where an ordinary profile would fall around the expected normal, calibrated on separate profiles. It describes natural variability, not measurement error or uncertainty in the average.",
		"Calibration is diagnostic: there are no trusted new outcomes yet to confirm coverage, so intervals are labelled uncalibrated for release."},
	"freshness": {"What stale data means",
		"Each source has an allowed age. Beyond it, values are shown as stale and are not used to support a favorable trip result.",
		"Stale values describe the past forecast, not now."},
	"model": {"How the Nautiq model is used and what it cannot do",
		"Nautiq trains boosted-tree residual models against the climatology with leakage-safe splits, calibrates intervals, and scores profile structure. Every release is pinned, versioned and documented on the Models page.",
		"Neither residual candidate beat climatology enough to be promoted, so climatology serves. Models never produce trip verdicts or observations."},
	"evidence": {"What the evidence drawer shows",
		"Each result lists its source, observation or forecast time, method release and calculation identifier so it can be reproduced from stored inputs.",
		"Evidence shows how a number was produced, not that the method has been independently validated."},
	"personal_limits": {"How personal limits change a trip check",
		"Personal limits are your own preferences. They can make results stricter but never remove a required input.",
		"A personal limit being met is not a validated safety threshold."},
}

func explainAnswer(plan product.QueryPlan, a *Answer) {
	e := explanations[plan.Topic]
	a.Headline = e[0]
	a.Facts = append(a.Facts, Fact{Label: "How it works", Value: e[1], Status: "available"}, Fact{Label: "Limits", Value: e[2], Status: "unknown"})
	a.Links = append(a.Links, AnswerLink{"Methods and approval boundaries", "/methodology"}, AnswerLink{"Source rights and coverage", "/data-sources"})
	a.Cannot = []string{"This explanation is fixed text maintained with the product, not generated from your data."}
}
