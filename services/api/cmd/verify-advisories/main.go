// Offline contract executable retained in Git when local test files are ignored.
package main

import (
	"fmt"
	"nautiq.local/api/internal/advisories"
	"time"
)

func check(ok bool) {
	if !ok {
		panic("advisory precedence contract failed")
	}
}
func main() {
	now, _ := time.Parse(time.RFC3339, "2026-10-03T02:00:00Z")
	expires := now.Add(time.Hour)
	m := advisories.Message{RevisionID: "warning", SourceID: "issuer", Sender: "IMD", Identifier: "a", Sent: now.Add(-time.Hour), Operational: true, Type: "Alert", Infos: []advisories.Info{{Event: "High waves", Effective: now.Add(-time.Hour), Expires: &expires, Areas: []advisories.Area{{}}}}}
	m.Identity = advisories.Identity{Sender: m.Sender, Identifier: m.Identifier, Sent: m.Sent}
	life := advisories.Lifecycle([]advisories.Message{m})
	s := advisories.Snapshot{AsOf: now, Sources: []advisories.Source{{ID: "issuer", Coverage: "stale_or_incomplete"}, {ID: "missing", Coverage: "unconfigured"}}, Items: []advisories.Bulletin{{Message: m, Lifecycle: life[m.RevisionID]}}, Issues: []string{}}
	start, end := now, now.Add(30*time.Minute)
	hit := map[string]map[int]bool{"warning": {0: true}}
	warning := advisories.Evaluate(s, start, end, hit)
	check(warning.Status == "official_warning" && len(warning.Unknown) == 2)
	check(advisories.Evaluate(s, start, end, nil).Status == "unknown")
	s.Items = nil
	check(advisories.Evaluate(s, start, end, nil).Status == "unknown")
	s.Sources = []advisories.Source{{ID: "complete", Coverage: "verified_complete"}}
	check(advisories.Evaluate(s, start, end, nil).Status == "unknown")
	s.ProductionApproved = true
	check(advisories.Evaluate(s, start, end, nil).Status == "known_none_intersecting")
	cancel := m
	cancel.RevisionID = "cancel"
	cancel.Identifier = "c"
	cancel.Type = "Cancel"
	cancel.Sent = now
	cancel.Identity = advisories.Identity{Sender: cancel.Sender, Identifier: cancel.Identifier, Sent: cancel.Sent}
	cancel.Infos = nil
	cancel.References = []advisories.Identity{m.Identity}
	life = advisories.Lifecycle([]advisories.Message{cancel, m})
	check(life[m.RevisionID].State == "cancelled")
	cancel.Sender = "attacker"
	life = advisories.Lifecycle([]advisories.Message{cancel, m})
	check(life[m.RevisionID].State == "active")
	m.Infos[0].Expires = nil
	s.Items = []advisories.Bulletin{{Message: m, Lifecycle: life[m.RevisionID]}}
	check(advisories.Evaluate(s, start, end, hit).Status == "unknown")
	check(!advisories.FiniteCoordinate(181, 0))
	fmt.Println("Advisory Go contracts passed: warning priority, empty/stale unknown, approval gate, exact cancellation and missing validity.")
}
