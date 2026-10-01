# Phase 1 delivery

The scope follows Section 4 of `06-Nautiuq-Implementation-Blueprint.md`.

## Implemented

- Next.js / TypeScript application shell and live `/status` page.
- Go Core API with liveness, dependency readiness and graceful shutdown.
- Installable Python scientific package with two lightweight gRPC runtimes.
- PostgreSQL 17 with PostGIS and TimescaleDB initialization.
- S3-compatible MinIO storage with an idempotently created private bucket.
- Redis and persistent NATS JetStream.
- Docker Compose with persistent volumes and loopback-bound published ports.
- Local protobuf generation and generated Go/Python clients and server contracts.
- `make setup`, `make up`, `make test`, `make lint`, plus build and smoke commands.
- A checks-only CI workflow; no deployment, commit or push automation.

## Decisions

The Phase 1 Python service contract exposes runtime health only. Both scientific service boundaries share the package and container image until distinct dependencies justify separate images. No inference values or observation data are fabricated.

Database health separately verifies the connection, PostGIS function, TimescaleDB extension, and initialized schema version. Storage checks authenticate and verify the bucket. NATS checks JetStream account information rather than just a TCP listener. Go calls the generated Python gRPC clients, and the health page is rendered from live server-side API checks.

MinIO's official prebuilt image was unavailable during implementation. Following upstream release guidance, `infrastructure/minio/Dockerfile` builds the server and client from pinned upstream tags. This decision is limited to the requested local platform.

The broader architecture's MLflow, production scientific bundles and worker services remain deferred. Phase 0 now has separate offline tooling, fixtures and measured feasibility evidence in `10-Phase-0-Delivery.md`; platform readiness still makes no claim about source cadence/licensing or production model quality.

## Verification

Validated locally on 2026-10-01:

- `make setup`: passed, including a repeat run preserving the existing environment file.
- `make test`: passed Go race tests, both Python gRPC service-role round trips, and three frontend health contract tests.
- `make lint`: passed Go formatting/vet, Ruff, ESLint, TypeScript, and Compose configuration checks.
- `make build`: passed native Go and production Next.js builds.
- `make proto`: regeneration produced identical Go and Python contract files.
- `make up`: built the containers, launched the stack, and passed the smoke gate.
- `make smoke`: all ten dependency checks passed and the rendered health page showed `Local platform ready.`
- Live PostgreSQL inspection: PostGIS 3.6.4, TimescaleDB 2.30.2, and platform schema version 1 installed.
- Browser inspection: healthy state and unavailable-API state rendered correctly, with no captured console errors.
- Controlled Redis outage: readiness returned HTTP 503, liveness remained HTTP 200, all other dependencies stayed healthy, and the status page displayed `Platform needs attention.` After Redis restarted, the smoke check passed again.

The stack was left running at `http://localhost:3000/status`. No commit or push was performed. CI configuration is provided but has not run on GitHub.

## Updated Phase 1 — 2026-10-01

- `/health/ready` requires PostgreSQL/PostGIS/Timescale/schema 2 and excludes optional dependencies and frontend circular gating. `/api/v1/health` retains full diagnostics and the existing UI contract.
- `/api/v1/capabilities` explicitly reports runtime support while observations, models, fields, advisories and trip assessment remain disabled. Protobuf adds capability flags without changing existing field numbers; both runtimes expose false scientific capabilities. Go verifies runtime role and nonempty version.
- gRPC requests/responses are limited to 1MiB with 16 concurrent RPCs/4 workers; unknown runtime roles fail startup.
- Client reconnect backoff is capped at 5s so restarted scientific runtimes do not remain diagnostically unavailable through a long default backoff.
- Diagnostic/readiness handlers admit at most 8 concurrent reports each; overload returns a complete unavailable report with Retry-After rather than unbounded dependency fan-out. Schema checks require both migration ledger entries and outbox/inbox tables as well as version 2.
- `scripts/migrate.py` runs ordered SHA-verified migrations with advisory locking, bounded DB locks/statements and one transaction. Existing v1 volumes upgrade without deletion. Legacy adoption checks schema capabilities; it cannot retrospectively prove original SQL bytes.
- Schema 2 adds constrained event outbox and consumer inbox tables. Publish/retry/consumer/reconciliation processes are not implemented yet; see architecture Section 19 and Phase 2 gates.
- Python serving uses a pinned runtime dependency lock. Offline science has a separate larger lock, keeping scientific training dependencies out of serving containers. Raw feasibility artifacts are excluded from Git and Docker build contexts.
- CI includes locked offline scientific fixture tests; live providers are not contacted by routine CI. Production secrets/networking, auth and workload load tests remain later gates.

Revalidated locally after these changes: Go race tests; Python scientific/contracts/gRPC tests; frontend tests; all lint/type checks; native/Next.js builds; rebuilt Compose stack; smoke including readiness/capabilities; and live API responses. `make test-migrations` verified fresh initialization, repeat application preserving a sentinel row, legacy upgrade, checksum refusal, atomic rollback and outbox/inbox uniqueness in a temporary database, then removed only that database.

A controlled simultaneous Redis + ML-runtime outage produced diagnostic HTTP 503 while readiness/liveness remained HTTP 200 and the web status page displayed the degraded state. Both services were restored and diagnostic health returned 200. These are local checks, not production acceptance or a GitHub CI result.
