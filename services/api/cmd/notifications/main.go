package main

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	pb "nautiq.local/api/gen/nautiq/platform/v1"
	"nautiq.local/api/internal/notifications"
	"nautiq.local/api/internal/science"
)

func main() {
	if len(os.Args) > 1 && os.Args[1] == "--health" {
		client := http.Client{Timeout: 2 * time.Second}
		r, e := client.Get("http://127.0.0.1:8081/health/ready")
		if e != nil {
			os.Exit(1)
		}
		defer r.Body.Close()
		if r.StatusCode != 200 {
			os.Exit(1)
		}
		return
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	db, e := pgxpool.New(ctx, os.Getenv("DATABASE_URL"))
	if e != nil {
		slog.Error("notification database configuration failed")
		os.Exit(1)
	}
	defer db.Close()
	storage, e := minio.New(os.Getenv("MINIO_ENDPOINT"), &minio.Options{Creds: credentials.NewStaticV4(os.Getenv("MINIO_ROOT_USER"), os.Getenv("MINIO_ROOT_PASSWORD"), ""), Secure: false})
	if e != nil {
		slog.Error("notification storage configuration failed")
		os.Exit(1)
	}
	fields, e := grpc.NewClient(os.Getenv("FIELD_GRPC_ADDR"), grpc.WithTransportCredentials(insecure.NewCredentials()), grpc.WithDefaultCallOptions(grpc.MaxCallRecvMsgSize(1024*1024), grpc.MaxCallSendMsgSize(1024*1024)))
	if e != nil {
		slog.Error("notification field configuration failed")
		os.Exit(1)
	}
	defer fields.Close()
	provider := science.New(db, storage)
	provider.Fields = pb.NewFieldServiceClient(fields)
	origin := os.Getenv("PRODUCT_WEB_ORIGIN")
	if origin == "" {
		origin = "http://localhost:3000"
	}
	mail, e := notifications.SMTPFromEnv()
	if e != nil {
		slog.Error("notification mail configuration failed")
		os.Exit(1)
	}
	worker := &notifications.Worker{DB: db, Provider: provider, Origin: origin, ID: uuid.NewString()}
	if mail != nil {
		worker.Mail = mail
	}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health/ready", func(w http.ResponseWriter, r *http.Request) {
		var good bool
		e := db.QueryRow(r.Context(), `SELECT EXISTS(SELECT 1 FROM notification_worker_health WHERE worker_id=$1 AND success_at>now()-interval '90 seconds') AND (SELECT max(version)=15 FROM platform_schema_version)`, worker.ID).Scan(&good)
		if e != nil || !good {
			http.Error(w, "unavailable", 503)
			return
		}
		w.Write([]byte("ok"))
	})
	server := &http.Server{Addr: "127.0.0.1:8081", Handler: mux, ReadHeaderTimeout: 2 * time.Second, ReadTimeout: 3 * time.Second, WriteTimeout: 3 * time.Second}
	go func() {
		if e := server.ListenAndServe(); e != nil && e != http.ErrServerClosed {
			slog.Error("notification health server failed")
			stop()
		}
	}()
	defer server.Close()
	ticker := time.NewTicker(2 * time.Second)
	defer ticker.Stop()
	for {
		tickCtx, cancel := context.WithTimeout(ctx, 75*time.Second)
		e = worker.Tick(tickCtx)
		cancel()
		if e != nil {
			slog.Warn("notification tick deferred")
			_, _ = db.Exec(ctx, `UPDATE notification_worker_health SET last_error='tick_deferred',heartbeat_at=now() WHERE worker_id=$1`, worker.ID)
		}
		if len(os.Args) > 1 && os.Args[1] == "--once" {
			if e != nil {
				os.Exit(1)
			}
			return
		}
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}
