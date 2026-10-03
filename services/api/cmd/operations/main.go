// An operator-only CLI; never register these mutations on the public API.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"log/slog"
	"nautiq.local/api/internal/operations"
	"os"
	"regexp"
	"time"
)

func main() {
	action := flag.String("action", "status", "status, pause or resume")
	scope := flag.String("scope", "science", "exact control scope")
	reason := flag.String("reason", "", "bounded incident code, no personal text")
	actor := flag.String("actor", "", "operator identifier")
	revision := flag.Int64("revision", 0, "required expected revision")
	flag.Parse()
	if operations.LoadSecrets() != nil {
		slog.Error("configuration_refused")
		os.Exit(1)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	db, e := pgxpool.New(ctx, os.Getenv("DATABASE_URL"))
	if e != nil {
		slog.Error("configuration_refused")
		os.Exit(1)
	}
	defer db.Close()
	if *action == "status" {
		s, e := operations.Read(ctx, db, false)
		if e != nil {
			slog.Error("controls_unavailable")
			os.Exit(1)
		}
		json.NewEncoder(os.Stdout).Encode(s)
		return
	}
	if (*action != "pause" && *action != "resume") || !operations.ValidScope(*scope) || !regexp.MustCompile(`^[a-z][a-z0-9_]{2,63}$`).MatchString(*reason) || !regexp.MustCompile(`^[a-zA-Z0-9_.-]{1,64}$`).MatchString(*actor) || *revision < 1 {
		slog.Error("invalid_operator_request")
		os.Exit(1)
	}
	tx, e := db.Begin(ctx)
	if e != nil {
		slog.Error("controls_unavailable")
		os.Exit(1)
	}
	defer tx.Rollback(ctx)
	_, e = tx.Exec(ctx, "SELECT singleton FROM operations_controls WHERE singleton FOR UPDATE")
	if e != nil {
		slog.Error("controls_unavailable")
		os.Exit(1)
	}
	before, e := operations.Read(ctx, tx, false)
	if e != nil || before.Revision != *revision {
		slog.Error("control_revision_conflict")
		os.Exit(1)
	}
	raw, _ := json.Marshal(before)
	before.Paused[*scope] = *action == "pause"
	paused, _ := json.Marshal(before.Paused)
	_, e = tx.Exec(ctx, "UPDATE operations_controls SET paused=$1,revision=revision+1,updated_at=now() WHERE singleton", paused)
	after, _ := json.Marshal(before.Paused)
	if e == nil {
		_, e = tx.Exec(ctx, "INSERT INTO operations_audit(audit_id,action,scope,reason,actor,before_state,after_state) VALUES($1,$2,$3,$4,$5,$6,$7)", uuid.NewString(), *action, *scope, *reason, *actor, raw, after)
	}
	if e == nil {
		e = tx.Commit(ctx)
	}
	if e != nil {
		slog.Error("control_mutation_refused")
		os.Exit(1)
	}
	fmt.Printf("Control %s %s; revision %d. Scientific approval is unchanged.\n", *scope, *action, *revision+1)
}
