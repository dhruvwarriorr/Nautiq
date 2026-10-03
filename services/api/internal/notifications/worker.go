package notifications

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"reflect"
	"sort"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Input struct {
	Owner        string          `json:"-"`
	RuleID       string          `json:"rule_id"`
	RuleVersion  int64           `json:"rule_version"`
	WatchID      string          `json:"watchlist_id"`
	WatchVersion int64           `json:"watch_version"`
	RouteID      string          `json:"route_id,omitempty"`
	RouteVersion int64           `json:"route_version"`
	Rule         Rule            `json:"rule"`
	Watch        json.RawMessage `json:"watch"`
	Route        json.RawMessage `json:"route,omitempty"`
	Lease        string          `json:"-"`
}
type Snapshot struct {
	Schema     int      `json:"schema_version"`
	Input      Input    `json:"input"`
	Evidence   Evidence `json:"observation"`
	Lifecycle  string   `json:"lifecycle"`
	PolicySHA  string   `json:"policy_sha256"`
	CodeSHA    string   `json:"code_sha256"`
	Supersedes *string  `json:"supersedes"`
	Previous   State    `json:"previous_state"`
}
type Provider interface {
	NotificationEvidence(context.Context, Input, time.Time) (Evidence, error)
}
type Worker struct {
	DB              *pgxpool.Pool
	Provider        Provider
	Mail            Mailer
	Origin          string
	ID              string
	lastMaintenance time.Time
}
type queryer interface {
	QueryRow(context.Context, string, ...any) pgx.Row
}

func Load(ctx context.Context, q queryer, id string) (Input, error) {
	in := Input{RuleID: id}
	var data []byte
	e := q.QueryRow(ctx, `SELECT r.owner_id::text,r.version,r.data,w.object_id::text,w.version,w.data,COALESCE(t.object_id::text,''),COALESCE(t.version,0),t.data
 FROM product_objects r JOIN product_objects w ON w.object_id=(r.data->>'watchlist_id')::uuid AND w.owner_id=r.owner_id AND w.kind='watchlists' AND w.deleted_at IS NULL
 LEFT JOIN product_objects t ON t.object_id=(w.data->>'route_id')::uuid AND t.owner_id=r.owner_id AND t.kind='routes' AND t.deleted_at IS NULL
 WHERE r.object_id=$1 AND r.kind='alert-rules' AND r.deleted_at IS NULL`, id).Scan(&in.Owner, &in.RuleVersion, &data, &in.WatchID, &in.WatchVersion, &in.Watch, &in.RouteID, &in.RouteVersion, &in.Route)
	if e == nil {
		e = json.Unmarshal(data, &in.Rule)
	}
	return in, e
}
func same(a, b Input) bool {
	return a.Owner == b.Owner && a.RuleID == b.RuleID && a.RuleVersion == b.RuleVersion && a.WatchID == b.WatchID && a.WatchVersion == b.WatchVersion && a.RouteID == b.RouteID && a.RouteVersion == b.RouteVersion && reflect.DeepEqual(a.Rule, b.Rule) && equalJSON(a.Watch, b.Watch) && equalJSON(a.Route, b.Route)
}
func Matches(a, b Input) bool { return same(a, b) }
func equalJSON(a, b []byte) bool {
	if len(a) == 0 && len(b) == 0 {
		return true
	}
	var x, y any
	return json.Unmarshal(a, &x) == nil && json.Unmarshal(b, &y) == nil && reflect.DeepEqual(x, y)
}

func (w *Worker) Claim(ctx context.Context) (*Input, error) {
	_, e := w.DB.Exec(ctx, `INSERT INTO notification_rule_state(rule_id) SELECT object_id FROM product_objects WHERE kind='alert-rules' AND deleted_at IS NULL AND data->>'enabled'='true' ON CONFLICT DO NOTHING`)
	if e != nil {
		return nil, e
	}
	tx, e := w.DB.Begin(ctx)
	if e != nil {
		return nil, e
	}
	defer tx.Rollback(ctx)
	var id string
	e = tx.QueryRow(ctx, `SELECT n.rule_id::text FROM notification_rule_state n JOIN product_objects r ON r.object_id=n.rule_id
 WHERE r.deleted_at IS NULL AND r.data->>'enabled'='true' AND n.next_evaluation_at<=now() AND (n.lease_id IS NULL OR n.lease_expires_at<=now())
 ORDER BY n.next_evaluation_at,n.rule_id FOR UPDATE OF n SKIP LOCKED LIMIT 1`).Scan(&id)
	if errors.Is(e, pgx.ErrNoRows) {
		return nil, nil
	}
	if e != nil {
		return nil, e
	}
	in, e := Load(ctx, tx, id)
	if e != nil {
		return nil, e
	}
	in.Lease = uuid.NewString()
	_, e = tx.Exec(ctx, `UPDATE notification_rule_state SET lease_id=$2,lease_expires_at=now()+interval '90 seconds' WHERE rule_id=$1`, id, in.Lease)
	if e != nil {
		return nil, e
	}
	if e = tx.Commit(ctx); e != nil {
		return nil, e
	}
	return &in, nil
}
func pinsCurrent(ctx context.Context, tx pgx.Tx, pins []Pin) (bool, error) {
	// Coordinate with upstream publication through the same canonical locks.
	// Acquire in deterministic order and hold through the alert transaction.
	products := map[string]bool{}
	advisory := false
	for _, p := range pins {
		if p.Kind == "field" {
			products[p.Product] = true
		}
		advisory = advisory || p.Kind == "advisory_source"
	}
	if advisory {
		if _, e := tx.Exec(ctx, "SELECT pg_advisory_xact_lock_shared(78192403)"); e != nil {
			return false, e
		}
	}
	ordered := []string{}
	for product := range products {
		ordered = append(ordered, product)
	}
	sort.Strings(ordered)
	for _, product := range ordered {
		if _, e := tx.Exec(ctx, "SELECT pg_advisory_xact_lock_shared(hashtext($1))", "field:"+product); e != nil {
			return false, e
		}
	}
	for _, p := range pins {
		var ok bool
		var e error
		switch p.Kind {
		case "field":
			e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM field_selection s JOIN field_releases r USING(release_id) WHERE s.product_id=$1 AND r.release_id::text=$2 AND r.manifest_sha256=$3 AND r.status='ready')`, p.Product, p.ID, p.SHA).Scan(&ok)
		case "advisory_source":
			e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM advisory_sources WHERE source_id=$1 AND COALESCE(latest_run_id::text,'')=$2 AND md5(policy::text||transport||COALESCE(checked_at::text,''))=$3)`, p.Product, p.ID, p.Revision).Scan(&ok)
		default:
			continue
		}
		if e != nil {
			return false, e
		}
		if !ok {
			return false, nil
		}
	}
	return true, nil
}

func (w *Worker) Publish(ctx context.Context, in Input, e Evidence) (bool, error) {
	if e.Outcome != "triggered" && e.Outcome != "clear" && e.Outcome != "unknown" && e.Outcome != "corrected" {
		return false, errors.New("invalid_observation")
	}
	if e.AsOf.IsZero() || e.AsOf.After(time.Now().Add(5*time.Second)) || time.Since(e.AsOf) > 90*time.Second || len(e.Fingerprint) != 64 || e.Severity < 0 || e.Severity > 3 || len(e.Pins) > 32 {
		return false, errors.New("observation_contract")
	}
	tx, err := w.DB.Begin(ctx)
	if err != nil {
		return false, err
	}
	defer tx.Rollback(ctx)
	var enabled bool
	err = tx.QueryRow(ctx, `SELECT notifications_enabled FROM product_accounts WHERE account_id=$1 FOR UPDATE`, in.Owner).Scan(&enabled)
	if errors.Is(err, pgx.ErrNoRows) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	current, err := Load(ctx, tx, in.RuleID)
	if errors.Is(err, pgx.ErrNoRows) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	var oldJSON []byte
	var oldRule, oldWatch, oldRoute int64
	var previous *string
	err = tx.QueryRow(ctx, `SELECT state,rule_version,watch_version,route_version,last_alert_id::text FROM notification_rule_state WHERE rule_id=$1 AND lease_id=$2 AND lease_expires_at>now() FOR UPDATE`, in.RuleID, in.Lease).Scan(&oldJSON, &oldRule, &oldWatch, &oldRoute, &previous)
	if errors.Is(err, pgx.ErrNoRows) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	valid, err := pinsCurrent(ctx, tx, e.Pins)
	if err != nil {
		return false, err
	}
	if !same(current, in) || !current.Rule.Enabled || !valid {
		_, err = tx.Exec(ctx, `UPDATE notification_rule_state SET lease_id=NULL,lease_expires_at=NULL,next_evaluation_at=now(),last_reason='superseded_input' WHERE rule_id=$1`, in.RuleID)
		if err == nil {
			err = tx.Commit(ctx)
		}
		return false, err
	}
	var state State
	if err = json.Unmarshal(oldJSON, &state); err != nil {
		return false, errors.New("state_integrity")
	}
	if oldRule != in.RuleVersion || oldWatch != in.WatchVersion || oldRoute != in.RouteVersion {
		state = State{Episode: state.Episode + 1}
	}
	cooldown := in.Rule.CooldownMinutes
	if cooldown == 0 {
		cooldown = 60
	}
	decision := Advance(state, e, time.Duration(cooldown)*time.Minute)
	if len(e.Blobs) > 3 || len(e.BlobHashes) != len(e.Blobs) {
		return false, errors.New("field_evidence_contract")
	}
	for i, b := range e.Blobs {
		if len(b) > 900000 || Hash(b) != e.BlobHashes[i] {
			return false, errors.New("field_evidence_integrity")
		}
		_, err = tx.Exec(ctx, `INSERT INTO notification_evidence_blobs(owner_id,sha256,raw_bytes) VALUES($1,$2,$3) ON CONFLICT DO NOTHING`, in.Owner, e.BlobHashes[i], b)
		if err != nil {
			return false, err
		}
		var stored []byte
		err = tx.QueryRow(ctx, `SELECT raw_bytes FROM notification_evidence_blobs WHERE owner_id=$1 AND sha256=$2`, in.Owner, e.BlobHashes[i]).Scan(&stored)
		if err != nil {
			return false, err
		}
		if Hash(stored) != e.BlobHashes[i] {
			return false, errors.New("existing_source_evidence_integrity")
		}
	}
	frozen := Snapshot{Schema: 1, Input: in, Evidence: e, Lifecycle: decision.Notice, PolicySHA: Hash(PolicyJSON), CodeSHA: CodeSHA(), Supersedes: previous, Previous: state}
	raw := JSON(frozen)
	if len(raw) > 32768 {
		return false, errors.New("evidence_budget")
	}
	_, err = tx.Exec(ctx, `INSERT INTO notification_evaluations(evaluation_id,owner_id,rule_id,rule_version,outcome,evidence,evidence_bytes,evidence_sha256) VALUES($1,$2,$3,$4,$5,$6,$7,$8)`, uuid.NewString(), in.Owner, in.RuleID, in.RuleVersion, e.Outcome, raw, raw, Hash(raw))
	if err != nil {
		return false, err
	}
	if decision.Notice != "" {
		id := uuid.NewString()
		var got string
		err = tx.QueryRow(ctx, `INSERT INTO product_alerts(alert_id,owner_id,rule_id,rule_version,event_revision,state,evidence,evidence_bytes,evidence_sha256,supersedes) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) ON CONFLICT(owner_id,rule_id,rule_version,event_revision) DO NOTHING RETURNING alert_id::text`, id, in.Owner, in.RuleID, in.RuleVersion, decision.Dedup, decision.Notice, raw, raw, Hash(raw), previous).Scan(&got)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return false, err
		}
		if err == nil {
			if previous != nil {
				_, err = tx.Exec(ctx, `UPDATE notification_deliveries SET state='cancelled',reason='alert_superseded',lease_id=NULL,lease_expires_at=NULL WHERE alert_id=$1 AND state IN ('pending','sending')`, *previous)
				if err != nil {
					return false, err
				}
			}
			previous = &got
			channels := []string{"in_app"}
			if in.Rule.Channel == "email" || in.Rule.Channel == "both" {
				channels = append(channels, "email")
			}
			for _, channel := range channels {
				deliveryState := "pending"
				reason := ""
				if !enabled {
					deliveryState = "cancelled"
					reason = "notification_opt_out"
				}
				if channel == "in_app" && enabled {
					deliveryState = "sent"
				}
				_, err = tx.Exec(ctx, `INSERT INTO notification_deliveries(delivery_id,alert_id,owner_id,channel,state,reason,sent_at,email_version,destination)
    SELECT $1,$2,account_id,$4,$5,NULLIF($6,''),CASE WHEN $5='sent' THEN now() END,CASE WHEN $4='email' THEN email_version END,CASE WHEN $4='email' AND email_verified_at IS NOT NULL THEN notification_email END FROM product_accounts WHERE account_id=$3`, uuid.NewString(), got, in.Owner, channel, deliveryState, reason)
				if err != nil {
					return false, err
				}
			}
		}
	}
	reason := ""
	if len(e.Reasons) > 0 {
		reason = e.Reasons[0]
	}
	if decision.Pending {
		reason = "cooldown_pending"
	}
	_, err = tx.Exec(ctx, `UPDATE notification_rule_state SET state=$2,rule_version=$3,watch_version=$4,route_version=$5,next_evaluation_at=now()+interval '60 seconds',last_evaluated_at=$6,last_outcome=$7,last_reason=NULLIF($8,''),last_alert_id=$9,lease_id=NULL,lease_expires_at=NULL WHERE rule_id=$1`, in.RuleID, JSON(decision.State), in.RuleVersion, in.WatchVersion, in.RouteVersion, e.AsOf, e.Outcome, reason, previous)
	if err == nil {
		err = tx.Commit(ctx)
	}
	return err == nil, err
}

// Claims are fenced separately from network I/O. Owner locks order delivery with opt-out/deletion.
func (w *Worker) DeliverOne(ctx context.Context) (bool, error) {
	tx, e := w.DB.Begin(ctx)
	if e != nil {
		return false, e
	}
	defer tx.Rollback(ctx)
	_, e = tx.Exec(ctx, `UPDATE notification_deliveries SET state='failed',reason='retry_exhausted',lease_id=NULL,lease_expires_at=NULL WHERE state='sending' AND lease_expires_at<=now() AND attempts>=5`)
	if e != nil {
		return false, e
	}
	var id, owner string
	e = tx.QueryRow(ctx, `SELECT delivery_id::text,owner_id::text FROM notification_deliveries WHERE channel='email' AND attempts<5 AND next_attempt_at<=now() AND (state='pending' OR state='sending' AND lease_expires_at<=now()) ORDER BY next_attempt_at,delivery_id FOR UPDATE SKIP LOCKED LIMIT 1`).Scan(&id, &owner)
	if errors.Is(e, pgx.ErrNoRows) {
		return false, nil
	}
	if e != nil {
		return false, e
	}
	lease := uuid.NewString()
	_, e = tx.Exec(ctx, `UPDATE notification_deliveries SET state='sending',lease_id=$2,lease_expires_at=now()+interval '90 seconds',attempts=attempts+1 WHERE delivery_id=$1`, id, lease)
	if e != nil {
		return false, e
	}
	if e = tx.Commit(ctx); e != nil {
		return false, e
	}
	return w.DeliverClaim(ctx, id, owner, lease)
}
func (w *Worker) DeliverClaim(ctx context.Context, id, owner, lease string) (bool, error) {
	tx, e := w.DB.Begin(ctx)
	if e != nil {
		return false, e
	}
	defer tx.Rollback(ctx)
	var allowed bool
	var email *string
	var verified *time.Time
	var emailVersion int64
	e = tx.QueryRow(ctx, `SELECT notifications_enabled,notification_email,email_verified_at,email_version FROM product_accounts WHERE account_id=$1 FOR UPDATE`, owner).Scan(&allowed, &email, &verified, &emailVersion)
	if errors.Is(e, pgx.ErrNoRows) {
		return false, nil
	}
	if e != nil {
		return false, e
	}
	var raw, projection []byte
	var sha, state string
	var destination *string
	var pinnedVersion *int64
	var attempts int
	e = tx.QueryRow(ctx, `SELECT a.evidence_bytes,a.evidence,a.evidence_sha256,a.state,d.destination,d.email_version,d.attempts FROM notification_deliveries d JOIN product_alerts a USING(alert_id) WHERE d.delivery_id=$1 AND d.owner_id=$2 AND d.state='sending' AND d.lease_id=$3 AND d.lease_expires_at>now() FOR UPDATE OF d`, id, owner, lease).Scan(&raw, &projection, &sha, &state, &destination, &pinnedVersion, &attempts)
	if errors.Is(e, pgx.ErrNoRows) {
		return false, nil
	}
	if e != nil {
		return false, e
	}
	status, reason := "sent", ""
	var snap Snapshot
	var a, b any
	if json.Unmarshal(raw, &snap) != nil || json.Unmarshal(raw, &a) != nil || json.Unmarshal(projection, &b) != nil || Hash(raw) != sha || !reflect.DeepEqual(a, b) {
		status, reason = "blocked", "evidence_integrity"
	}
	if status == "sent" {
		for _, hash := range snap.Evidence.BlobHashes {
			var bytes []byte
			err := tx.QueryRow(ctx, `SELECT raw_bytes FROM notification_evidence_blobs WHERE owner_id=$1 AND sha256=$2`, owner, hash).Scan(&bytes)
			if err != nil || Hash(bytes) != hash {
				status, reason = "blocked", "source_evidence_integrity"
				break
			}
		}
	}
	if status == "sent" {
		snap.Input.Owner = owner
		current, err := Load(ctx, tx, snap.Input.RuleID)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return false, err
		}
		if err != nil || !same(current, snap.Input) || !current.Rule.Enabled {
			status, reason = "cancelled", "rule_or_watch_superseded"
		}
	}
	if !allowed {
		status, reason = "cancelled", "notification_opt_out"
	}
	if status == "sent" && (email == nil || verified == nil || destination == nil || pinnedVersion == nil || *pinnedVersion != emailVersion || *email != *destination) {
		status, reason = "blocked", "verified_recipient_required"
	}
	if status == "sent" && w.Mail == nil {
		status, reason = "blocked", "email_transport_unconfigured"
	}
	if status == "sent" {
		mailCtx, cancel := context.WithTimeout(ctx, 8*time.Second)
		err := w.Mail.Send(mailCtx, *destination, id, "Nautiq: private alert "+state, "A retained alert has a new lifecycle record.\nOpen your private Nautiq inbox: "+w.Origin+"/app/alerts\nSign in to inspect the immutable evidence, source age and limitations. This message does not establish safe conditions.\nManage notification preferences: "+w.Origin+"/app/settings")
		cancel()
		if err != nil {
			status, reason = "pending", "transport_failed"
			if attempts >= 5 {
				status, reason = "failed", "retry_exhausted"
			}
		}
	}
	backoff := time.Duration(60*(1<<(attempts-1))) * time.Second
	_, e = tx.Exec(ctx, `UPDATE notification_deliveries SET state=$4,reason=NULLIF($5,''),sent_at=CASE WHEN $4='sent' THEN now() ELSE sent_at END,next_attempt_at=now()+$6::interval,lease_id=NULL,lease_expires_at=NULL WHERE delivery_id=$1 AND owner_id=$2 AND lease_id=$3`, id, owner, lease, status, reason, fmt.Sprintf("%d seconds", int(backoff.Seconds())))
	if e == nil {
		e = tx.Commit(ctx)
	}
	return e == nil, e
}

func (w *Worker) Tick(ctx context.Context) error {
	if w.ID == "" {
		return errors.New("worker_identity_required")
	}
	_, e := w.DB.Exec(ctx, `INSERT INTO notification_worker_health(worker_id,smtp_configured) VALUES($1,$2) ON CONFLICT(worker_id) DO UPDATE SET heartbeat_at=now(),smtp_configured=$2`, w.ID, w.Mail != nil)
	if e != nil {
		return e
	}
	in, e := w.Claim(ctx)
	if e != nil {
		return e
	}
	if in != nil {
		c, cancel := context.WithTimeout(ctx, 35*time.Second)
		observation, err := w.Provider.NotificationEvidence(c, *in, time.Now().UTC())
		cancel()
		if err != nil {
			reason := "source_evidence_unavailable"
			for _, code := range []string{"saved_route_expired", "invalid_or_dateline_watch_geometry", "selected_field_unavailable", "field_evidence_contract", "threshold_evidence", "advisory_source_superseded"} {
				if err.Error() == code {
					reason = code
				}
			}
			observation = Evidence{Outcome: "unknown", AsOf: time.Now().UTC(), Reasons: []string{reason}, Fingerprint: Hash(JSON([]string{in.RuleID, reason})), Facts: JSON(map[string]any{"status": "unknown"})}
		}
		if _, e = w.Publish(ctx, *in, observation); e != nil {
			return e
		}
	}
	for i := 0; i < 4; i++ {
		more, err := w.DeliverOne(ctx)
		if err != nil {
			return err
		}
		if !more {
			break
		}
	}
	if time.Since(w.lastMaintenance) > time.Minute {
		_, e = w.DB.Exec(ctx, `DELETE FROM notification_evaluations WHERE evaluation_id IN (SELECT evaluation_id FROM notification_evaluations WHERE created_at<now()-interval '7 days' ORDER BY created_at LIMIT 1000);
  DELETE FROM notification_email_challenges WHERE expires_at<=now(); DELETE FROM notification_worker_health WHERE heartbeat_at<now()-interval '1 day';
  DELETE FROM notification_evidence_blobs WHERE (owner_id,sha256) IN (SELECT b.owner_id,b.sha256 FROM notification_evidence_blobs b WHERE b.created_at<now()-interval '7 days' AND NOT EXISTS(SELECT 1 FROM product_alerts a WHERE a.owner_id=b.owner_id AND COALESCE(a.evidence#>'{observation,field_evidence_sha256}','[]') ? b.sha256) AND NOT EXISTS(SELECT 1 FROM notification_evaluations e WHERE e.owner_id=b.owner_id AND COALESCE(e.evidence#>'{observation,field_evidence_sha256}','[]') ? b.sha256) ORDER BY b.created_at LIMIT 1000)`)
		if e != nil {
			return e
		}
		w.lastMaintenance = time.Now()
	}
	_, e = w.DB.Exec(ctx, `UPDATE notification_worker_health SET success_at=now(),last_error=NULL,heartbeat_at=now() WHERE worker_id=$1`, w.ID)
	return e
}
