// Package notifications evaluates evidence without converting unknown conditions into recovery.
package notifications

import (
	"crypto/sha256"
	"embed"
	"encoding/hex"
	"encoding/json"
	"math"
	"sort"
	"time"
)

//go:embed policy.json
var PolicyJSON []byte

//go:embed engine.go worker.go mail.go
var implementation embed.FS

func Hash(b []byte) string { h := sha256.Sum256(b); return hex.EncodeToString(h[:]) }
func JSON(v any) []byte {
	b, e := json.Marshal(v)
	if e != nil {
		panic(e)
	}
	return b
}
func CodeSHA() string {
	data := []byte{}
	for _, name := range []string{"engine.go", "worker.go", "mail.go"} {
		b, _ := implementation.ReadFile(name)
		data = append(data, []byte(name)...)
		data = append(data, b...)
	}
	return Hash(data)
}

type Rule struct {
	WatchlistID     string   `json:"watchlist_id"`
	Type            string   `json:"type"`
	Variable        string   `json:"variable,omitempty"`
	Units           string   `json:"units,omitempty"`
	Limit           *float64 `json:"limit,omitempty"`
	Enabled         bool     `json:"enabled"`
	Channel         string   `json:"channel"`
	CooldownMinutes int      `json:"cooldown_minutes,omitempty"`
}
type Pin struct {
	Kind     string `json:"kind"`
	ID       string `json:"id"`
	SHA      string `json:"sha256,omitempty"`
	Product  string `json:"product,omitempty"`
	Revision string `json:"revision,omitempty"`
}
type Evidence struct {
	Outcome     string          `json:"outcome"`
	Fingerprint string          `json:"fingerprint"`
	Severity    int             `json:"severity"`
	Fresh       bool            `json:"fresh"`
	AsOf        time.Time       `json:"as_of"`
	Reasons     []string        `json:"reasons"`
	Pins        []Pin           `json:"source_pins"`
	Facts       json.RawMessage `json:"facts"`
	Retired     []string        `json:"retired_revisions,omitempty"`
	Warnings    []string        `json:"warning_revisions,omitempty"`
	BlobHashes  []string        `json:"field_evidence_sha256,omitempty"`
	Blobs       [][]byte        `json:"-"`
}
type State struct {
	Active     bool      `json:"active"`
	Episode    int       `json:"episode"`
	Severity   int       `json:"severity"`
	Notified   string    `json:"notified_fingerprint"`
	LastNotice time.Time `json:"last_notice"`
	ClearCount int       `json:"clear_count"`
	ClearPin   string    `json:"clear_pin"`
	LastClear  time.Time `json:"last_clear"`
	Warnings   []string  `json:"warning_revisions"`
	Correction string    `json:"correction_fingerprint"`
}
type Decision struct {
	State   State
	Notice  string
	Dedup   string
	Pending bool
}

func Advance(previous State, e Evidence, cooldown time.Duration) Decision {
	d := Decision{State: previous}
	relevant := []string{}
	for _, old := range previous.Warnings {
		for _, retired := range e.Retired {
			if old == retired {
				relevant = append(relevant, old)
				break
			}
		}
	}
	sort.Strings(relevant)
	correctionPin := Hash(JSON(relevant))
	dedupPin := e.Fingerprint
	if e.AsOf.Before(previous.LastNotice) {
		return d
	}
	if e.Outcome == "unknown" || e.Outcome == "corrected" {
		d.State.ClearCount = 0
		d.State.ClearPin = ""
		d.State.LastClear = time.Time{}
		if previous.Active && len(relevant) > 0 && previous.Correction != correctionPin {
			d.Notice = "corrected"
			d.State.Correction = correctionPin
			dedupPin = correctionPin
		}
	} else if e.Outcome == "triggered" {
		d.State.ClearCount = 0
		d.State.ClearPin = ""
		d.State.LastClear = time.Time{}
		if !previous.Active {
			d.State.Episode++
			d.Notice = "new"
		} else if previous.Notified != e.Fingerprint {
			if e.Severity > previous.Severity {
				d.Notice = "escalated"
			} else if len(relevant) > 0 {
				d.Notice = "updated"
			} else if e.AsOf.Sub(previous.LastNotice) >= cooldown {
				d.Notice = "updated"
			} else {
				d.Pending = true
			}
		}
		d.State.Active = true
		if d.Notice != "" {
			d.State.Notified = e.Fingerprint
			d.State.Severity = e.Severity
			d.State.Warnings = e.Warnings
			d.State.Correction = ""
		}
	} else if e.Outcome == "clear" && e.Fresh {
		if previous.Active && previous.ClearPin != e.Fingerprint && (previous.LastClear.IsZero() || e.AsOf.Sub(previous.LastClear) >= time.Minute) {
			d.State.ClearCount++
			d.State.ClearPin = e.Fingerprint
			d.State.LastClear = e.AsOf
			if d.State.ClearCount >= 2 {
				d.Notice = "recovered"
				d.State.Active = false
				d.State.Severity = 0
				d.State.Warnings = nil
				d.State.Notified = ""
			}
		}
	} else {
		d.State.ClearCount = 0
		d.State.ClearPin = ""
		d.State.LastClear = time.Time{}
	}
	if d.Notice != "" {
		d.State.LastNotice = e.AsOf
		d.Dedup = Hash(JSON([]any{d.State.Episode, d.Notice, dedupPin}))
	}
	return d
}

// A partial fresh exceedance can trigger; only complete fresh coverage can recover.
func Threshold(maximum *float64, limit float64, complete bool) (string, int) {
	if maximum == nil || math.IsNaN(*maximum) || math.IsInf(*maximum, 0) {
		return "unknown", 0
	}
	if *maximum >= limit {
		severity := 1
		if limit > 0 && *maximum >= 1.5*limit {
			severity = 2
		}
		if limit > 0 && *maximum >= 2*limit {
			severity = 3
		}
		return "triggered", severity
	}
	if complete {
		return "clear", 0
	}
	return "unknown", 0
}
