# Nautiq

Ocean and marine-condition intelligence. Start with the [document index](docs/01-Nautiq-Project-Overview.md), [execution contracts](docs/08-Execution-Contracts.md) and [failure register](docs/09-Edge-Case-Register.md). Designs, delivered code and measured readiness are distinct.

## Phase 0: source and scientific feasibility

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12; Docker, Go and Node are not required for this offline track. On macOS LightGBM also needs `brew install libomp`; Linux needs its OpenMP runtime (`libgomp1`). Dependencies are pinned in `ml/requirements-phase0.lock`.

```sh
make phase0          # Install dependencies, acquire/cache real samples, benchmark
make phase0-replay   # Verify hashes and rerun entirely offline
make phase0-gate     # Exit 2 while any readiness gate remains unproven
```

The catalog pins a historical Argo pilot, NOAA OISST analysis, wave/wind forecast samples and NDMA RSS candidate. The tool preserves immutable raw bytes and receipts under ignored `artifacts/phase0/`, writes a QC-passed Parquet snapshot, and evaluates train-only harmonic climatology, HGBR/LightGBM residual candidates, predictive calibration and profile structure. Reports distinguish access from cadence/licenses/coverage/scientific release. A partial report is an expected truthful outcome, not a fabricated successful release.

`make phase0` reuses verified cached bytes; it does not claim each rerun refreshes live forecasts. For a new acquisition use `.venv/bin/python -m nautiq_ml.phase0.cli --output artifacts/phase0/new-run-name`. Replay an existing acquisition with `--output` and `--offline`; preserve `catalog.json`, raw objects and receipts. Hash/code/environment changes identify a new scientific snapshot. Full reports are local artifacts; a compact checked-in summary and limits are in [Phase 0 delivery](docs/10-Phase-0-Delivery.md).

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

Copying `.env.example` is handled by setup without overwriting an existing `.env`. Its credentials are for local development. Services are reachable through the Compose network; web, API, MLflow and the MinIO console are exposed, bound to loopback. Change `WEB_PORT` or `API_PORT` in `.env` if needed. Passwords embedded in `DATABASE_URL` must be URL-safe (or percent-encoded).

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

## Phase 2: Argo observation slice

```sh
make setup
make up
make ingest             # One bounded live batch
make reconcile          # One bounded historical batch and repair
make phase2-verify      # Offline NetCDF contracts
make phase2-reliability # Disposable DB/object replay and recovery checks
make phase2-broker      # Brief local broker outage; restores services afterward
make phase2-smoke       # Live API, rendered pages and exact raw SHA verification
```

Open http://localhost:3000/profiles for real Argo positions and original-level temperature/salinity charts. Each profile includes source QC, parameter modes, timestamps, method versions and raw/canonical/Parquet hashes. The raw download is pinned to the displayed revision. List queries require a bounding box and UTC start/end, accept at most 366 days and use signed snapshot pagination. The [Phase 2 delivery](docs/11-Phase-2-Delivery.md) records implementation, measured verification and limits.

The source config is `packages/source-catalog/argo.json`: three workers, at most 20 files per run, six-hour live polling and daily historical reconciliation. `ARGO_OBSERVED_SINCE` fixes a persistent scope start (local default 2025-10-01); these batches do not establish complete source coverage. Raw artifacts remain immutable in MinIO; migrations preserve existing volumes. Display QC accepts source QC 1 with per-variable missingness; Phase 0 training keeps its separate strict D-only policy.

## Phase 3: correctness and reproducibility

Open http://localhost:3000/data to inspect source timing, QC audit groups and frozen training snapshots. Profile pages link to retained revisions and durable calculation evidence. See [delivery and measured verification](docs/12-Phase-3-Delivery.md).

```sh
make phase3-verify      # Frozen real-source fixture and offline policies
make phase3-reliability # Disposable DB: revisions, late jobs, frozen snapshots
make argo-replay        # Reprocess up to 1,000 retained raw files without refetching
make science-maintain  # Drain up to 500 summary jobs and refresh source monitor
make training-snapshot AS_OF=2026-10-02T04:45:13.911676Z
make verify-snapshot SNAPSHOT_ID=3b606239-35ae-53ae-938d-5c0935385a00
make phase3-smoke       # Evidence APIs, rendered pages and exact Parquet bytes
```

Snapshot commands require an explicit UTC selection time. Selection uses retained revision history at that time; inputs, method/code/runtime/QC/source policy and output checksums are frozen. The strict policy in `packages/source-catalog/argo-training.json` uses delayed-mode adjusted QC 1 labels and the documented 2005–2024 temporal splits. Temperature and salinity remain independently nullable. This is an original-level dataset; the separate standard-grid and climatology artifacts below preserve it unchanged. Default selection is at most 500 profiles, hard maximum 2,000 profiles/100,000 candidate levels/128 MiB Parquet; exceeding a budget fails rather than truncating.

A successful backfill/replay never renews live-source freshness. Monitoring separates local fetch age, observation time, expected cadence and verified provider freshness; provider cadence and coverage remain explicitly unverified. Frozen evidence does not approve a scientific release.

## Historical normal and profile differences

Open http://localhost:3000/climatology to review frozen seasonal references and their held-out evaluation. Profile pages compare observed standard-depth values with the expected conditional mean and report signed temperature/salinity differences, support, fallbacks and uncalibrated training residual spread. Original levels remain separately visible. See [delivery, fixed scientific policy and real-data measurements](docs/13-Phase-4-Delivery.md).

```sh
make phase4-verify
make phase4-reliability
make climatology-build SNAPSHOT_ID=3b606239-35ae-53ae-938d-5c0935385a00
make climatology-verify REFERENCE_ID=dd46a816-fa5b-5d4f-a296-9c2025d10c61
make climatology-select REFERENCE_ID=dd46a816-fa5b-5d4f-a296-9c2025d10c61
make climatology-maintain
make phase4-smoke
```

IDs refer to retained local data; fresh installations use their own verified snapshot and returned reference IDs. The historical dataset baseline is 2005–2024, while fitting uses only 2005–2016. Tuning/calibration/test years never alter coefficients, support or spread. Reference selection is an explicit local prototype action; scientific production approval remains false. Unsupported coverage returns null without suppressing original observations. Residual candidate evaluation and serving are described below; unqualified models retain climatology. Anomaly, field, advisory and trip verdicts remain unavailable.

## Residual expected means and model evidence

Open http://localhost:3000/models to compare LightGBM, HGBR and climatology, inspect exact release/MLflow pins and review grouped evaluations. Profile pages show diagnostic candidates, model explanations and the active serving mean. Both candidates failed the configured promotion checks, so climatology remains active. The reused historical test block cannot authorize promotion. See [delivery and real-data evidence](docs/14-Phase-5-Delivery.md).

```sh
make expected-setup
make phase5-verify
make phase5-reliability
make expected-build REFERENCE_ID=<verified-selected-climatology-id>
make expected-verify MODEL_ID=<returned-model-id>
make expected-select MODEL_ID=<returned-model-id>
# Set ML_RELEASE_ID=<same exact model ID> in .env, then restart:
docker compose up -d --no-deps ml-inference
make expected-maintain
make phase5-smoke
```

MLflow is available at http://localhost:5001, with persistent local SQLite metadata and proxied artifacts. `MLFLOW_PORT` changes its loopback port. Serving uses the exact `ML_RELEASE_ID` and verified native model bundle, never a latest registry version. An unset or mismatched runtime pin leaves inference unavailable while observations remain readable. `make expected-log MODEL_ID=...` retries experiment/registry logging without changing the scientific release. `expected_state` reports the implemented mean service; `ml_residual` remains false until a candidate qualifies. Static coastal features and anomaly verdicts remain unavailable. Diagnostic predictive intervals have a separate release and coverage gate, described below.

## Local services

| Service | Purpose |
| --- | --- |
| Next.js | Observation explorer, profile charts and dependency status page |
| Go API | Bounded profile/provenance API and dependency probes |
| Go ingestion | GDAC discovery, immutable raw acquisition and leased outbox publisher |
| Python normalizer | Durable Argo consumer, canonical revisions and immutable Parquet |
| Python ML runtime | Pinned native residual candidates and historical fallback via typed gRPC |
| MLflow | Persistent experiment metrics, exact native bundles and registry versions |
| Python field runtime | gRPC field-service boundary; no gridded data loaded yet |
| PostgreSQL 17 | Operational storage, PostGIS and TimescaleDB extensions |
| MinIO | Private `nautiq` S3 bucket, initialized idempotently |
| Redis | Cache runtime |
| NATS | JetStream enabled with persistent local storage |

The diagnostic health API returns HTTP 200 only when all checks pass; failures return HTTP 503 and the status page shows them. Traffic readiness checks the required DB/schema capabilities; Redis/NATS/ML/web failure does not remove API readiness. Error responses suppress connection details and credentials. Scientific gRPC and public capability flags explicitly report that no production model, gridded fields, advisories or trip engine are served yet. The local observation slice is implemented; this does not establish production source approval.

MinIO Community is source-only; the local Dockerfile builds the pinned server release rather than relying on unavailable registry images. See [the upstream release instructions](https://github.com/minio/minio/releases). This establishes the requested local runtime, not a production storage recommendation.

## Database and persistence

The PostgreSQL entrypoint initializes a new volume with migration 001. `make up` then applies ordered upgrades using `scripts/migrate.py`, with a transaction advisory lock, SHA-256 verification and rollback on failure. Existing v1 volumes are adopted and upgraded through schema 7 without deleting data; later applied-file edits and newer database versions are refused. Schema 2 adds outbox/inbox foundations; schema 3 adds Argo raw/canonical/revision storage and lease tokens. Phase 2 supplies the publisher, consumer and reconciliation. Schema 4 adds versioned QC audit, calculation manifests, revision-safe summary jobs, source monitoring and frozen training snapshots. Schema 5 adds immutable climatology references, explicit local selection and revision/reference-safe comparison jobs. Schema 6 adds expected-mean releases, MLflow metadata and leased profile comparison jobs; schema 7 invalidates/restores comparisons atomically when the historical reference changes. `make down` preserves volumes. Never reset volumes to apply an upgrade.

## Scope

Phase 0 feasibility tooling and the real-source pilot, Phase 1 local platform Phase 2 Argo observation slice and Phase 3 correctness/reproducibility and Phase 4 train-only climatology/comparisons are implemented. The residual expected-mean model slice is implemented with explicit release loading and qualified climatology fallback. Predictive quantile/CQR intervals and residual/PCA profile diagnostics are implemented with their own frozen releases. Qualified uncertainty/anomaly verdicts, field sampling, advisory ingestion and trip assessments remain unavailable. Health reports runtime connectivity, not scientific readiness. Operational source coverage, commercial/redistribution approvals and release audits remain explicit blocked gates. Argo workers and the coordinate map run locally; MLflow runs locally; scientific production approval and production operations remain outstanding.

See [Phase 1 delivery and verification](docs/07-Phase-1-Delivery.md) and the [implementation blueprint](docs/06-Nautiq-Implementation-Blueprint.md).

### Predictive interval evidence

Nautiq supports native LightGBM/CatBoost quantile comparisons, profile-based Mondrian CQR, explicit hierarchical calibration fallback, pinned typed inference and fixed-reference coverage monitoring. Inspect [delivery and validation](docs/15-Phase-6-Delivery.md), [measured evidence](docs/evidence/phase6-summary.json), the [API contract](packages/schemas/uncertainty.openapi.json), and `/uncertainty` in the local explorer. Mean and median are separate estimates. Diagnostic interval availability does not establish qualified coverage or scientific production approval.

```sh
make uncertainty-setup
make phase6-verify phase6-reliability phase6-smoke
make uncertainty-build MODEL_ID=<selected-expected-release-id>
make uncertainty-verify INTERVAL_ID=<interval-release-id>
make uncertainty-log INTERVAL_ID=<interval-release-id>
make uncertainty-benchmark INTERVAL_ID=<interval-release-id>
make uncertainty-select INTERVAL_ID=<interval-release-id>
# Set exact UNCERTAINTY_RELEASE_ID and matching ML_RELEASE_ID in local .env, then restart inference.
make uncertainty-maintain uncertainty-monitor
```

The Nautiq rename covers technical namespaces and fresh-stack defaults. Existing local data was preserved in renamed runtime resources; original resources remain backups. Immutable release bytes and historical registry receipts are retained.


## Profile magnitude and structure

The complete-case 10–500 m profile system is implemented: local uncertainty-normalized signed residuals, depth-weighted magnitude, Ledoit–Wolf correlated distance and a weighted discrete FPCA prototype. Separate historical ranks disclose comparison support; Z-scores and safely exported Isolation Forest remain comparison baselines. Review [delivery and validation](docs/16-Phase-7-Delivery.md), [measured evidence](docs/evidence/phase7-summary.json), [the API contract](packages/schemas/anomaly.openapi.json), and [/anomalies](http://localhost:3000/anomalies). Every supported profile shows its depth contributions and reconstruction. Missing layers retain explicit unavailable aggregate scores.

```sh
make anomaly-build INTERVAL_ID=<selected-uncertainty-release-id>
make anomaly-verify ANOMALY_ID=<profile-release-id>
make anomaly-log ANOMALY_ID=<profile-release-id>
make anomaly-benchmark ANOMALY_ID=<profile-release-id>
make anomaly-select ANOMALY_ID=<profile-release-id>
# Set ANOMALY_RELEASE_ID, retain its exact uncertainty/mean pins and restart ml-inference.
make anomaly-maintain
make phase7-verify phase7-reliability phase7-smoke
```

`profile_anomaly_diagnostics` means supported local implementation with exact selected/runtime pins and current revision evidence. Scientific `profile_anomaly` remains false: interval qualification, expert-reviewed events, quiet-period false-alert rates, independent audits and a new untouched test have not established a qualified anomaly verdict. Historical ranks are descriptive, not event probabilities. Fixed references never adapt automatically during an event.
