# Nautiuq

Ocean and marine-condition intelligence. Start with the [document index](docs/01-Nautiuq-Project-Overview.md), [execution contracts](docs/08-Execution-Contracts.md) and [failure register](docs/09-Edge-Case-Register.md). Designs, delivered code and measured readiness are distinct.

## Phase 0: source and scientific feasibility

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12; Docker, Go and Node are not required for this offline track. On macOS LightGBM also needs `brew install libomp`; Linux needs its OpenMP runtime (`libgomp1`). Dependencies are pinned in `ml/requirements-phase0.lock`.

```sh
make phase0          # Install dependencies, acquire/cache real samples, benchmark
make phase0-replay   # Verify hashes and rerun entirely offline
make phase0-gate     # Exit 2 while any readiness gate remains unproven
```

The catalog pins a historical Argo pilot, NOAA OISST analysis, wave/wind forecast samples and NDMA RSS candidate. The tool preserves immutable raw bytes and receipts under ignored `artifacts/phase0/`, writes a QC-passed Parquet snapshot, and evaluates train-only harmonic climatology, HGBR/LightGBM residual candidates, predictive calibration and profile structure. Reports distinguish access from cadence/licenses/coverage/scientific release. A partial report is an expected truthful outcome, not a fabricated successful release.

`make phase0` reuses verified cached bytes; it does not claim each rerun refreshes live forecasts. For a new acquisition use `.venv/bin/python -m nautiuq_ml.phase0.cli --output artifacts/phase0/new-run-name`. Replay an existing acquisition with `--output` and `--offline`; preserve `catalog.json`, raw objects and receipts. Hash/code/environment changes identify a new scientific snapshot. Full reports are local artifacts; a compact checked-in summary and limits are in [Phase 0 delivery](docs/10-Phase-0-Delivery.md).

## Phase 1: local platform

Prerequisites: Docker with Compose and a running daemon, Go 1.26+, Node.js 24+, npm, and [uv](https://docs.astral.sh/uv/). Setup uses Python 3.12 (uv can obtain it) and installs pinned Go protobuf generators inside `.tools/`.

```sh
make setup
make up
```

`make up` builds and starts the stack, then waits for real dependency checks and checks the rendered status page. On first launch, source builds and image downloads can take several minutes.

- Web: http://localhost:3000
- Dependency health page: http://localhost:3000/status
- Core API readiness: http://localhost:8080/api/v1/health
- Core API liveness: http://localhost:8080/health/live
- Core API traffic readiness: http://localhost:8080/health/ready
- Implemented capabilities: http://localhost:8080/api/v1/capabilities
- MinIO console: http://localhost:9001

Copying `.env.example` is handled by setup without overwriting an existing `.env`. Its credentials are for local development. Services are reachable through the Compose network; only web, API and the MinIO console are exposed, bound to loopback. Change `WEB_PORT` or `API_PORT` in `.env` if needed. Passwords embedded in `DATABASE_URL` must be URL-safe (or percent-encoded).

```sh
make test       # Go race tests, Python gRPC round trip, frontend health contracts
make lint       # Go format/vet, Ruff, ESLint, TypeScript, Compose validation
make build      # Native Go and production Next.js builds
make proto      # Regenerate both Go and Python contracts
make smoke      # Recheck the running platform and status page
make logs
make down       # Stops containers; preserves data volumes
make migrate    # Ordered transactional upgrades on existing volumes
make test-migrations # Fresh/legacy/checksum/rollback tests in a disposable database
```

Generated protobuf code is retained in the repository so container builds require no generation toolchain. After contract edits, run `make proto`. Generation runs locally; it does not depend on a remote plugin service.

## Local services

| Service | Purpose |
| --- | --- |
| Next.js | Application shell and dependency status page |
| Go API | HTTP API and bounded concurrent dependency probes |
| Python ML runtime | gRPC scientific package runtime; no model loaded yet |
| Python field runtime | gRPC field-service boundary; no gridded data loaded yet |
| PostgreSQL 17 | Operational storage, PostGIS and TimescaleDB extensions |
| MinIO | Private `nautiuq` S3 bucket, initialized idempotently |
| Redis | Cache runtime |
| NATS | JetStream enabled with persistent local storage |

The diagnostic health API returns HTTP 200 only when all checks pass; failures return HTTP 503 and the status page shows them. Traffic readiness checks the required DB/schema capabilities; Redis/NATS/ML/web failure does not remove API readiness. Error responses suppress connection details and credentials. Scientific gRPC and public capability flags explicitly report that no production model, observations, fields, advisories or trip engine are served yet.

MinIO Community is source-only; the local Dockerfile builds the pinned server release rather than relying on unavailable registry images. See [the upstream release instructions](https://github.com/minio/minio/releases). This establishes the requested local runtime, not a production storage recommendation.

## Database and persistence

The PostgreSQL entrypoint initializes a new volume with migration 001. `make up` then applies ordered upgrades using `scripts/migrate.py`, with a transaction advisory lock, SHA-256 verification and rollback on failure. Existing v1 volumes are adopted and upgraded to schema 2 without deleting data; later applied-file edits and newer database versions are refused. Schema 2 adds outbox/inbox foundations; their publisher/consumer implementations arrive in Phase 2. `make down` preserves volumes. Never reset volumes to apply an upgrade.

## Scope

Phase 0 feasibility tooling and real-source pilot are implemented. Phase 1 is upgraded platform plumbing. Canonical production ingestion (Phase 2), model serving, field sampling, advisory ingestion and trip assessments remain future capabilities. Health reports runtime connectivity, not scientific readiness. Operational source coverage, commercial/redistribution approvals and release audits remain explicit blocked gates. MLflow, worker services and maps arrive when their phase requires them.

See [Phase 1 delivery and verification](docs/07-Phase-1-Delivery.md) and the [implementation blueprint](docs/06-Nautiuq-Implementation-Blueprint.md).
