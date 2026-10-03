package trips

import (
	"errors"
	"math"
	"time"
)

type Point struct {
	Latitude  float64   `json:"latitude"`
	Longitude float64   `json:"longitude"`
	Time      time.Time `json:"time"`
}
type Binding struct {
	Variable  string `json:"variable"`
	ReleaseID string `json:"release_id"`
}
type Request struct {
	Activity         string                `json:"activity"`
	ThresholdVersion string                `json:"threshold_version"`
	Waypoints        []Point               `json:"waypoints"`
	Fields           []Binding             `json:"fields"`
	SpacingKM        float64               `json:"spacing_km"`
	StepMinutes      float64               `json:"step_minutes"`
	Preferences      map[string]Preference `json:"preferences"`
}
type Sampling struct {
	DistanceKM  float64 `json:"distance_km"`
	SpacingKM   float64 `json:"spacing_km"`
	StepMinutes float64 `json:"step_minutes"`
	SampleCount int     `json:"sample_count"`
	Path        string  `json:"path"`
}

func Distance(a, b Point) float64 {
	lat1, lat2 := a.Latitude*math.Pi/180, b.Latitude*math.Pi/180
	dl := (b.Latitude - a.Latitude) * math.Pi / 180
	dn := (b.Longitude - a.Longitude) * math.Pi / 180
	v := math.Pow(math.Sin(dl/2), 2) + math.Cos(lat1)*math.Cos(lat2)*math.Pow(math.Sin(dn/2), 2)
	return 6371 * 2 * math.Asin(math.Sqrt(math.Min(1, v)))
}
func Interpolate(a, b Point, f float64) Point {
	xyz := func(p Point) [3]float64 {
		lat, lon := p.Latitude*math.Pi/180, p.Longitude*math.Pi/180
		return [3]float64{math.Cos(lat) * math.Cos(lon), math.Cos(lat) * math.Sin(lon), math.Sin(lat)}
	}
	x, y := xyz(a), xyz(b)
	angle := math.Acos(math.Max(-1, math.Min(1, x[0]*y[0]+x[1]*y[1]+x[2]*y[2])))
	var v [3]float64
	for i := range v {
		if angle < 1e-8 {
			v[i] = (1-f)*x[i] + f*y[i]
		} else {
			v[i] = (math.Sin((1-f)*angle)*x[i] + math.Sin(f*angle)*y[i]) / math.Sin(angle)
		}
	}
	return Point{Latitude: math.Atan2(v[2], math.Hypot(v[0], v[1])) * 180 / math.Pi, Longitude: math.Atan2(v[1], v[0]) * 180 / math.Pi, Time: a.Time.Add(time.Duration(float64(b.Time.Sub(a.Time)) * f)).UTC()}
}
func Points(req Request, asOf time.Time) ([]Point, Sampling, error) {
	meta := Sampling{SpacingKM: req.SpacingKM, StepMinutes: req.StepMinutes, Path: "shortest great-circle segments through every timed waypoint; stops retained"}
	if len(req.Waypoints) < 2 || len(req.Waypoints) > 32 || !finite(req.SpacingKM) || req.SpacingKM < 0.5 || req.SpacingKM > 5 || !finite(req.StepMinutes) || req.StepMinutes < 1 || req.StepMinutes > 30 {
		return nil, meta, errors.New("route_sampling_budget")
	}
	if req.Waypoints[0].Time.Before(asOf.Add(-5*time.Minute)) || req.Waypoints[len(req.Waypoints)-1].Time.Sub(req.Waypoints[0].Time) > 24*time.Hour {
		return nil, meta, errors.New("route_future_window_or_duration")
	}
	counts := []int{}
	total := 1
	for i, p := range req.Waypoints {
		if !finite(p.Latitude+p.Longitude) || p.Latitude < -85 || p.Latitude > 85 || p.Longitude < -180 || p.Longitude > 180 || p.Time.IsZero() {
			return nil, meta, errors.New("timed_waypoints_required")
		}
		if i == 0 {
			continue
		}
		a := req.Waypoints[i-1]
		if !p.Time.After(a.Time) {
			return nil, meta, errors.New("route_times_must_increase")
		}
		if math.Abs(p.Longitude-a.Longitude) > 180 {
			return nil, meta, errors.New("split_dateline_route_required")
		}
		d := Distance(a, p)
		meta.DistanceKM += d
		n := int(math.Max(1, math.Max(math.Ceil(d/req.SpacingKM), math.Ceil(p.Time.Sub(a.Time).Minutes()/req.StepMinutes))))
		counts = append(counts, n)
		total += n
	}
	if meta.DistanceKM > 1000 || total > 512 {
		return nil, meta, errors.New("route_distance_or_sample_budget")
	}
	result := make([]Point, 0, total)
	for i, n := range counts {
		for j := 0; j < n; j++ {
			result = append(result, Interpolate(req.Waypoints[i], req.Waypoints[i+1], float64(j)/float64(n)))
		}
	}
	result = append(result, req.Waypoints[len(req.Waypoints)-1])
	meta.SampleCount = len(result)
	return result, meta, nil
}
