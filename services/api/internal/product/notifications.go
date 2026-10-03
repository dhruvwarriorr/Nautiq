package product

import (
	"context"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"nautiq.local/api/internal/notifications"
	"net/http"
	"reflect"
	"time"
)

func (s *Server) registerNotifications(mux *http.ServeMux) {
	mux.Handle("GET /api/v1/notification-status", s.private(false, s.notificationStatus))
	mux.Handle("GET /api/v1/notification-settings", s.private(false, s.notificationSettings))
	mux.Handle("POST /api/v1/notification-email", s.private(true, s.requestEmail))
	mux.Handle("POST /api/v1/notification-email/verify", s.private(true, s.verifyEmail))
	mux.Handle("DELETE /api/v1/notification-email", s.private(true, s.removeEmail))
	mux.Handle("GET /api/v1/notification-evidence/{sha}", s.private(false, s.notificationEvidence))
	mux.Handle("POST /api/v1/alerts/{id}/replay", s.private(true, s.replayAlert))
	mux.Handle("POST /api/v1/alerts/{id}/retry-email", s.private(true, s.retryEmail))
}
func (s *Server) notificationAvailable(r *http.Request) bool {
	var available bool
	_ = s.DB.QueryRow(r.Context(), `SELECT EXISTS(SELECT 1 FROM notification_worker_health WHERE success_at>now()-interval '90 seconds' AND heartbeat_at>now()-interval '90 seconds')`).Scan(&available)
	return available
}
func (s *Server) notificationStatus(w http.ResponseWriter, r *http.Request, u Identity) {
	if !noQuery(w, r) {
		return
	}
	var rowsJSON []byte
	e := s.DB.QueryRow(r.Context(), `SELECT COALESCE(json_agg(t ORDER BY rule_id),'[]') FROM (SELECT r.object_id rule_id,r.name,r.version rule_version,r.data->>'enabled' enabled,n.last_evaluated_at,n.last_outcome,n.last_reason,n.next_evaluation_at,n.state->'active' active,n.state->'clear_count' recovery_confirmations,n.last_alert_id FROM product_objects r LEFT JOIN notification_rule_state n ON n.rule_id=r.object_id WHERE r.owner_id=$1 AND r.kind='alert-rules' AND r.deleted_at IS NULL) t`, u.ID).Scan(&rowsJSON)
	if e != nil {
		fail(w, 503, "notification_status_unavailable")
		return
	}
	var heartbeat *time.Time
	var smtp bool
	e = s.DB.QueryRow(r.Context(), `SELECT success_at,smtp_configured FROM notification_worker_health ORDER BY heartbeat_at DESC LIMIT 1`).Scan(&heartbeat, &smtp)
	if e != nil && !errors.Is(e, pgx.ErrNoRows) {
		fail(w, 503, "notification_status_unavailable")
		return
	}
	write(w, 200, map[string]any{"items": json.RawMessage(rowsJSON), "worker_available": s.notificationAvailable(r), "last_success_at": heartbeat, "email_transport_configured": smtp, "notifications_enabled": u.Notifications, "policy": json.RawMessage(notifications.PolicyJSON), "as_of": time.Now().UTC()})
}
func (s *Server) notificationSettings(w http.ResponseWriter, r *http.Request, u Identity) {
	if !noQuery(w, r) {
		return
	}
	var data []byte
	e := s.DB.QueryRow(r.Context(), `SELECT json_build_object('email',notification_email,'verified_at',email_verified_at,'email_version',email_version,'notifications_enabled',notifications_enabled) FROM product_accounts WHERE account_id=$1`, u.ID).Scan(&data)
	if e != nil {
		fail(w, 503, "notification_settings_unavailable")
		return
	}
	write(w, 200, map[string]any{"settings": json.RawMessage(data), "email_transport_configured": s.Mailer != nil})
}
func (s *Server) requestEmail(w http.ResponseWriter, r *http.Request, u Identity) {
	var input struct {
		Email string `json:"email"`
	}
	if !body(w, r, &input) {
		return
	}
	address, e := notifications.Address(input.Email)
	if e != nil {
		fail(w, 400, e.Error())
		return
	}
	if s.Mailer == nil {
		fail(w, 503, "email_transport_unconfigured")
		return
	}
	// Account and recipient budgets also apply to fresh idempotency keys; no plaintext address is stored in rate keys.
	s.mutation(w, r, u, input, func(tx pgx.Tx) (int, any, error) {
		if !s.rate(r.Context(), "email-challenge:"+u.ID, 3, time.Hour) || !s.rate(r.Context(), "email-recipient:"+address, 3, time.Hour) {
			return 0, nil, refusal{429, "email_verification_quota"}
		}
		proof, e := entropy(32)
		if e != nil {
			return 0, nil, e
		}
		token := hex.EncodeToString(proof)
		_, e = tx.Exec(r.Context(), `INSERT INTO notification_email_challenges(owner_id,email,proof_sha256,expires_at) VALUES($1,$2,$3,now()+interval '15 minutes') ON CONFLICT(owner_id) DO UPDATE SET email=$2,proof_sha256=$3,expires_at=now()+interval '15 minutes',attempts=0,created_at=now()`, u.ID, address, Hash([]byte(token)))
		if e != nil {
			return 0, nil, e
		}
		ctx, cancel := context.WithTimeout(r.Context(), 8*time.Second)
		defer cancel()
		if e = s.Mailer.Send(ctx, address, uuid.NewString(), "Verify your Nautiq notification email", "You requested notification email verification in Nautiq.\nPaste this proof in your signed-in notification settings within 15 minutes:\n"+token+"\n\nIf you did not request this, ignore this message. This is not account recovery.\n"+s.Origin+"/app/settings"); e != nil {
			return 0, nil, refusal{503, "email_verification_delivery_failed"}
		}
		return 202, map[string]any{"verification_sent": true, "expires_in_seconds": 900}, nil
	})
}
func (s *Server) verifyEmail(w http.ResponseWriter, r *http.Request, u Identity) {
	var input struct {
		Proof string `json:"proof"`
	}
	if !body(w, r, &input) {
		return
	}
	if !tokenPattern.MatchString(input.Proof) {
		fail(w, 400, "invalid_email_proof")
		return
	}
	s.mutation(w, r, u, input, func(tx pgx.Tx) (int, any, error) {
		if !s.rate(r.Context(), "email-verify:"+u.ID, 8, time.Hour) {
			return 0, nil, refusal{429, "email_verification_quota"}
		}
		var sha, email string
		var attempts int
		e := tx.QueryRow(r.Context(), `UPDATE notification_email_challenges SET attempts=attempts+1 WHERE owner_id=$1 AND expires_at>now() AND attempts<5 RETURNING proof_sha256,email,attempts`, u.ID).Scan(&sha, &email, &attempts)
		if missing(e) {
			return 400, map[string]any{"code": "email_proof_expired_or_exhausted"}, nil
		}
		if e != nil {
			return 0, nil, e
		}
		if subtle.ConstantTimeCompare([]byte(sha), []byte(Hash([]byte(input.Proof)))) != 1 {
			return 400, map[string]any{"code": "invalid_email_proof"}, nil
		}
		_, e = tx.Exec(r.Context(), `UPDATE product_accounts SET notification_email=$2,email_verified_at=now(),email_version=email_version+1 WHERE account_id=$1`, u.ID, email)
		if e != nil {
			return 0, nil, e
		}
		_, e = tx.Exec(r.Context(), `DELETE FROM notification_email_challenges WHERE owner_id=$1`, u.ID)
		return 200, map[string]any{"verified": true}, e
	})
}
func (s *Server) removeEmail(w http.ResponseWriter, r *http.Request, u Identity) {
	if r.ContentLength > 0 {
		fail(w, 400, "unexpected_body")
		return
	}
	s.mutation(w, r, u, nil, func(tx pgx.Tx) (int, any, error) {
		_, e := tx.Exec(r.Context(), `UPDATE product_accounts SET notification_email=NULL,email_verified_at=NULL,email_version=email_version+1 WHERE account_id=$1;`, u.ID)
		if e == nil {
			_, e = tx.Exec(r.Context(), `DELETE FROM notification_email_challenges WHERE owner_id=$1`, u.ID)
		}
		if e == nil {
			_, e = tx.Exec(r.Context(), `UPDATE notification_deliveries SET state='cancelled',reason='recipient_removed',lease_id=NULL,lease_expires_at=NULL WHERE owner_id=$1 AND channel='email' AND state IN ('pending','sending','blocked')`, u.ID)
		}
		return 200, map[string]bool{"removed": true}, e
	})
}
func (s *Server) notificationEvidence(w http.ResponseWriter, r *http.Request, u Identity) {
	sha := r.PathValue("sha")
	if !noQuery(w, r) {
		return
	}
	if !tokenPattern.MatchString(sha) {
		fail(w, 404, "not_found")
		return
	}
	var raw []byte
	e := s.DB.QueryRow(r.Context(), `SELECT raw_bytes FROM notification_evidence_blobs WHERE owner_id=$1 AND sha256=$2`, u.ID, sha).Scan(&raw)
	if missing(e) {
		fail(w, 404, "not_found")
		return
	}
	if e != nil || Hash(raw) != sha || !json.Valid(raw) {
		fail(w, 503, "notification_evidence_integrity")
		return
	}
	write(w, 200, json.RawMessage(raw))
}
func (s *Server) replayAlert(w http.ResponseWriter, r *http.Request, u Identity) {
	if r.ContentLength > 0 || !identifier(r.PathValue("id")) {
		fail(w, 400, "invalid_alert_replay")
		return
	}
	s.mutation(w, r, u, nil, func(tx pgx.Tx) (int, any, error) {
		var raw, projection []byte
		var sha, lifecycle, revision string
		e := tx.QueryRow(r.Context(), `SELECT evidence_bytes,evidence,evidence_sha256,state,event_revision FROM product_alerts WHERE owner_id=$1 AND alert_id=$2`, u.ID, r.PathValue("id")).Scan(&raw, &projection, &sha, &lifecycle, &revision)
		if missing(e) {
			return 0, nil, refusal{404, "not_found"}
		}
		if e != nil {
			return 0, nil, e
		}
		var x, y any
		var snap notifications.Snapshot
		if Hash(raw) != sha || json.Unmarshal(raw, &snap) != nil || json.Unmarshal(raw, &x) != nil || json.Unmarshal(projection, &y) != nil || !reflect.DeepEqual(x, y) {
			return 0, nil, refusal{503, "alert_evidence_integrity"}
		}
		if snap.CodeSHA != notifications.CodeSHA() || snap.PolicySHA != Hash(notifications.PolicyJSON) {
			return 0, nil, refusal{409, "original_notification_runtime_required"}
		}
		for _, hash := range snap.Evidence.BlobHashes {
			var b []byte
			if tx.QueryRow(r.Context(), `SELECT raw_bytes FROM notification_evidence_blobs WHERE owner_id=$1 AND sha256=$2`, u.ID, hash).Scan(&b) != nil || Hash(b) != hash {
				return 0, nil, refusal{503, "notification_evidence_integrity"}
			}
		}
		cooldown := snap.Input.Rule.CooldownMinutes
		if cooldown == 0 {
			cooldown = 60
		}
		decision := notifications.Advance(snap.Previous, snap.Evidence, time.Duration(cooldown)*time.Minute)
		if decision.Notice != lifecycle || decision.Dedup != revision {
			return 0, nil, refusal{503, "alert_replay_mismatch"}
		}
		return 200, map[string]any{"matched": true, "state": decision.Notice, "evidence_sha256": sha, "meaning": "Frozen lifecycle replay; no current source refresh or safety assessment."}, nil
	})
}

func (s *Server) retryEmail(w http.ResponseWriter, r *http.Request, u Identity) {
	if r.ContentLength > 0 || !identifier(r.PathValue("id")) {
		fail(w, 400, "invalid_email_retry")
		return
	}
	s.mutation(w, r, u, nil, func(tx pgx.Tx) (int, any, error) {
		if !s.rate(r.Context(), "email-retry:"+u.ID, 3, 24*time.Hour) {
			return 0, nil, refusal{429, "email_retry_quota"}
		}
		var raw, projection []byte
		var sha string
		e := tx.QueryRow(r.Context(), `SELECT evidence_bytes,evidence,evidence_sha256 FROM product_alerts WHERE alert_id=$1 AND owner_id=$2`, r.PathValue("id"), u.ID).Scan(&raw, &projection, &sha)
		if missing(e) {
			return 0, nil, refusal{404, "not_found"}
		}
		if e != nil {
			return 0, nil, e
		}
		var snap notifications.Snapshot
		var x, y any
		if Hash(raw) != sha || json.Unmarshal(raw, &snap) != nil || json.Unmarshal(raw, &x) != nil || json.Unmarshal(projection, &y) != nil || !reflect.DeepEqual(x, y) {
			return 0, nil, refusal{503, "alert_evidence_integrity"}
		}
		snap.Input.Owner = u.ID
		current, e := notifications.Load(r.Context(), tx, snap.Input.RuleID)
		if e != nil && !missing(e) {
			return 0, nil, e
		}
		if e != nil || !current.Rule.Enabled || !notifications.Matches(current, snap.Input) {
			return 0, nil, refusal{409, "rule_or_watch_superseded"}
		}
		var ready bool
		e = tx.QueryRow(r.Context(), `SELECT a.notifications_enabled AND a.notification_email IS NOT NULL AND a.email_verified_at IS NOT NULL AND n.last_alert_id=$2::uuid FROM product_accounts a JOIN notification_rule_state n ON n.rule_id=$3 WHERE a.account_id=$1`, u.ID, r.PathValue("id"), snap.Input.RuleID).Scan(&ready)
		if e != nil {
			return 0, nil, e
		}
		if !ready || s.Mailer == nil {
			return 0, nil, refusal{409, "current_opt_in_recipient_and_transport_required"}
		}
		var id string
		e = tx.QueryRow(r.Context(), `UPDATE notification_deliveries d SET state='pending',attempts=0,next_attempt_at=now(),lease_id=NULL,lease_expires_at=NULL,reason=NULL,destination=a.notification_email,email_version=a.email_version FROM product_accounts a WHERE d.alert_id=$1 AND d.owner_id=$2 AND a.account_id=d.owner_id AND d.channel='email' AND d.state IN ('failed','blocked') RETURNING delivery_id::text`, r.PathValue("id"), u.ID).Scan(&id)
		if missing(e) {
			return 0, nil, refusal{409, "delivery_not_retryable"}
		}
		return 202, map[string]any{"queued": true}, e
	})
}
