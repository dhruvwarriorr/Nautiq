package platform

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"os"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"
	"github.com/nats-io/nats.go"
	"github.com/nats-io/nats.go/jetstream"
	"github.com/redis/go-redis/v9"
	"google.golang.org/grpc"
	"google.golang.org/grpc/backoff"
	"google.golang.org/grpc/credentials/insecure"
	pb "nautiuq.local/api/gen/nautiuq/platform/v1"
)

func required(key string) (string, error) {
	value := os.Getenv(key)
	if value == "" {
		return "", fmt.Errorf("missing configuration: %s", key)
	}
	return value, nil
}

func Dependencies(ctx context.Context) (map[string]Check, func(), error) {
	keys := []string{"DATABASE_URL", "REDIS_ADDR", "NATS_URL", "MINIO_ENDPOINT", "MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD", "ML_GRPC_ADDR", "FIELD_GRPC_ADDR"}
	config := map[string]string{}
	for _, key := range keys {
		value, err := required(key)
		if err != nil {
			return nil, nil, err
		}
		config[key] = value
	}
	pool, err := pgxpool.New(ctx, config["DATABASE_URL"])
	if err != nil {
		return nil, nil, errors.New("invalid database configuration")
	}
	cache := redis.NewClient(&redis.Options{Addr: config["REDIS_ADDR"], DialTimeout: time.Second, ReadTimeout: time.Second, WriteTimeout: time.Second, MaxRetries: -1})
	storage, err := minio.New(config["MINIO_ENDPOINT"], &minio.Options{Creds: credentials.NewStaticV4(config["MINIO_ROOT_USER"], config["MINIO_ROOT_PASSWORD"], ""), Secure: false})
	if err != nil {
		pool.Close()
		cache.Close()
		return nil, nil, errors.New("invalid storage configuration")
	}
	checks := map[string]Check{
		"postgresql": func(ctx context.Context) error { return pool.Ping(ctx) },
		"postgis": func(ctx context.Context) error {
			var version string
			return pool.QueryRow(ctx, "SELECT postgis_version()").Scan(&version)
		},
		"timescaledb": func(ctx context.Context) error {
			var version string
			return pool.QueryRow(ctx, "SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'").Scan(&version)
		},
		"schema": func(ctx context.Context) error {
			var version int
			var complete bool
			err := pool.QueryRow(ctx, "SELECT (SELECT max(version) FROM platform_schema_version), (SELECT count(*)=7 FROM platform_migrations WHERE version IN (1,2,3,4,5,6,7)) AND to_regclass('public.event_outbox') IS NOT NULL AND to_regclass('public.consumer_inbox') IS NOT NULL AND to_regclass('public.profile_revisions') IS NOT NULL AND to_regclass('public.raw_artifacts') IS NOT NULL AND to_regclass('public.calculations') IS NOT NULL AND to_regclass('public.training_snapshots') IS NOT NULL AND to_regclass('public.climatology_releases') IS NOT NULL AND to_regclass('public.climatology_comparisons') IS NOT NULL AND to_regclass('public.expected_state_releases') IS NOT NULL AND to_regclass('public.expected_state_comparisons') IS NOT NULL").Scan(&version, &complete)
			if err == nil && (version != 7 || !complete) {
				return errors.New("unexpected schema version")
			}
			return err
		},
		"redis": func(ctx context.Context) error { return cache.Ping(ctx).Err() },
		"minio": func(ctx context.Context) error {
			found, err := storage.BucketExists(ctx, "nautiuq")
			if err == nil && !found {
				return errors.New("storage bucket missing")
			}
			return err
		},
		"nats_jetstream": func(ctx context.Context) error {
			remaining := time.Until(time.Now().Add(time.Second))
			if deadline, ok := ctx.Deadline(); ok {
				remaining = time.Until(deadline)
			}
			if remaining <= 0 {
				return ctx.Err()
			}
			conn, err := nats.Connect(config["NATS_URL"], nats.Timeout(remaining), nats.NoReconnect())
			if err != nil {
				return err
			}
			defer conn.Close()
			js, err := jetstream.New(conn)
			if err != nil {
				return err
			}
			_, err = js.AccountInfo(ctx)
			return err
		},
	}
	var connections []*grpc.ClientConn
	reconnect := backoff.DefaultConfig
	reconnect.MaxDelay = 5 * time.Second
	for name, key := range map[string]string{"ml_inference": "ML_GRPC_ADDR", "field_service": "FIELD_GRPC_ADDR"} {
		conn, err := grpc.NewClient(config[key], grpc.WithTransportCredentials(insecure.NewCredentials()),
			grpc.WithConnectParams(grpc.ConnectParams{Backoff: reconnect, MinConnectTimeout: time.Second}))
		if err != nil {
			pool.Close()
			cache.Close()
			for _, c := range connections {
				c.Close()
			}
			return nil, nil, err
		}
		connections = append(connections, conn)
		client := pb.NewPlatformServiceClient(conn)
		expectedRole := map[string]string{"ml_inference": "ml-inference", "field_service": "field-service"}[name]
		checks[name] = func(ctx context.Context) error {
			response, err := client.Check(ctx, &pb.CheckRequest{})
			if err == nil && (!response.Ready || response.Service != expectedRole || response.Version == "") {
				return errors.New("scientific runtime not ready")
			}
			return err
		}
	}
	checks["web"] = func(ctx context.Context) error {
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, "http://web:3000/health/live", nil)
		if err != nil {
			return err
		}
		response, err := (&http.Client{Timeout: 2 * time.Second}).Do(req)
		if err != nil {
			return err
		}
		defer response.Body.Close()
		if response.StatusCode != http.StatusOK {
			return errors.New("web unavailable")
		}
		return nil
	}
	return checks, func() {
		pool.Close()
		cache.Close()
		for _, c := range connections {
			c.Close()
		}
	}, nil
}
