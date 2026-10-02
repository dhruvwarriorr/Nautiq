package main

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	pb "nautiq.local/api/gen/nautiq/platform/v1"
	"nautiq.local/api/internal/platform"
	"nautiq.local/api/internal/profiles"
	"nautiq.local/api/internal/science"
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	deps, closeDeps, err := platform.Dependencies(ctx)
	if err != nil {
		slog.Error("configure dependencies", "error", err)
		os.Exit(1)
	}
	defer closeDeps()
	pool, err := pgxpool.New(ctx, os.Getenv("DATABASE_URL"))
	if err != nil {
		slog.Error("configure observation storage")
		os.Exit(1)
	}
	defer pool.Close()
	storage, err := minio.New(os.Getenv("MINIO_ENDPOINT"), &minio.Options{Creds: credentials.NewStaticV4(os.Getenv("MINIO_ROOT_USER"), os.Getenv("MINIO_ROOT_PASSWORD"), ""), Secure: false})
	if err != nil {
		slog.Error("configure raw storage")
		os.Exit(1)
	}
	mux := http.NewServeMux()
	profiles.New(pool, storage).Register(mux)
	scientificConnection, err := grpc.NewClient(os.Getenv("ML_GRPC_ADDR"), grpc.WithTransportCredentials(insecure.NewCredentials()), grpc.WithDefaultCallOptions(grpc.MaxCallRecvMsgSize(1024*1024), grpc.MaxCallSendMsgSize(1024*1024)))
	if err != nil {
		slog.Error("configure scientific runtime")
		os.Exit(1)
	}
	defer scientificConnection.Close()
	scientific := science.New(pool, storage)
	scientific.Runtime = pb.NewPlatformServiceClient(scientificConnection)
	scientific.Register(mux)
	mux.HandleFunc("GET /health/live", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"status":"ok"}`))
	})
	mux.Handle("GET /api/v1/health", platform.Handler(deps))
	mux.Handle("GET /health/ready", platform.Readiness(deps))
	server := &http.Server{Addr: ":8080", Handler: mux, ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 10 * time.Second, WriteTimeout: 10 * time.Second, IdleTimeout: 60 * time.Second}
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		server.Shutdown(shutdown)
	}()
	slog.Info("Core API listening", "address", server.Addr)
	if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		slog.Error("serve", "error", err)
		os.Exit(1)
	}
}
