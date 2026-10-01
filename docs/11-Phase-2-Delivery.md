# Phase 2 delivery: Argo observation slice

Phase 2 is implemented locally. The Go ingestion service discovers real GDAC files, the Python normalizer publishes canonical original-level profiles and immutable Parquet, and the Go API serves the Next.js map/profile explorer with a revision-pinned raw download. Production source approval and the broader Phase 3 scientific release gates remain separate.

## Run and review

```sh
make setup
make up                # Applies migration 003 without resetting existing volumes
make ingest            # One bounded live-discovery batch
make reconcile         # One bounded historical batch plus normalization repair
make phase2-verify     # Offline synthetic NetCDF contracts
make phase2-reliability # Disposable DB/object verification; running stack required
make phase2-broker     # Briefly pauses local NATS/ingestion; restores them in finally
make phase2-smoke      # Real API, rendered HTML and exact raw-download verification
make test-migrations
```

Open [the explorer](http://localhost:3000/profiles), choose a marker or table row, and use **Download exact raw NetCDF**. Its bytes are pinned to the displayed canonical revision. The upstream GDAC link may subsequently change. The list needs a bounding box and UTC start/end; end is exclusive, the maximum range is 366 days, and pagination uses a filter-bound signed snapshot cursor.

The delivery profile [7902312, cycle 3](http://localhost:3000/profiles/2606038a-b17a-55fa-a503-1b7a06915047) has 505 accepted pressure levels, observation time `2025-10-01T06:50:57Z`, and retained raw SHA-256 `31d0840a36c6e868e2159c67d1d635a1a381ae1c7adcd18f1f9ea675c3669193`. The API and web downloads were independently hashed against that provenance. Source: `https://data-argo.ifremer.fr/dac/aoml/7902312/profiles/R7902312_003.nc`.

## Implemented behavior

| Requirement | Delivery |
| --- | --- |
| GDAC index, update cursor, domain filter | Streaming bounded gzip/CSV parsing; update timestamp/path ordering; 24-hour overlap; persisted discovery state; separate live/backfill scopes and shared conditional index cache |
| Bounded acquisition | Fixed public HTTPS GDAC destination pinned after DNS resolution; redirects denied; global provider lock, three workers, paced requests, bounded retries, 64 MiB raw cap, 512 MiB expanded index cap, 4 KiB line cap, ten-minute run deadline |
| Immutable raw/provenance | SHA-addressed private S3 objects, receipt/native metadata, byte verification, raw registry and `raw.received` outbox committed atomically; orphan reconstruction |
| NetCDF normalization | R uses raw variables, A/D use adjusted variables; per-parameter modes; source QC 1; explicit units/ranges; valid time/position; all supported N_PROF entries including secondary sampling profiles |
| Canonical identity/revisions | WMO/cycle/direction/sampling kind/native profile index; immutable raw+method+content revisions, source links, D>A>R selection and monotonic update time; same-version conflicts quarantined |
| Original levels | Accepted pressure levels with TEOS-10 depth conversion; independent nullable temperature/salinity, missing reasons, selected field/QC/native index; no interpolation or extrapolation |
| Lake publication | ZSTD Parquet with explicit nullable schema and immutable SHA manifest, verified before SQL readiness; bounded rolling integrity checks and reconstruction from retained raw |
| Crash-safe delivery | Leased/token-checked outbox, stable JetStream message ID, mark-published after broker ack; durable explicit-ack consumer, atomic inbox/canonical/outbox commit, replay/retention repair and poison quarantine |
| API | `/api/v1/profiles`, `/api/v1/profiles/{id}`, and revision-pinned `/raw`; PostGIS/time filters, bounded concurrency/deadlines, UTC time, stable snapshot pagination, typed `application/problem+json` failures |
| UI | Longitude/latitude marker map, accessible coordinate table, original-level temperature/salinity depth charts, missing-value/gap breaks, raw/canonical/Parquet hashes, source attribution, QC/modes and conversion versions |

Objects and revisions are never silently replaced. Missing lake objects can be reconstructed only when raw bytes and the installed normalizer reproduce the stored digest. Conflicting/corrupt artifacts remain quarantined and `science_ready=false`. Transport failures leave discoveries pending; definite GDAC 404/410 responses have explicit discovery quarantine records. Failed downloads never advance the cursor past unresolved work. Source-invalid secondary profiles can be rejected while accepted profiles in the same file are retained.

The API capability `observations` is true for this local slice. ML inference, gridded fields, advisories and trip assessments remain false. `science_ready` means a complete verified observation artifact; it does not approve a model, establish source freshness/coverage, or certify current local sea conditions.

## Dated verification

On **2026-10-01 at 17:11 UTC**, live GDAC acquisition had produced **120 retained profile files, 189 canonical profiles and 56,441 current original levels** at the measured checkpoint. Modes were R=108, A=79, D=2; observation times ranged from 2025-10-01 through 2026-09-28. The outbox was drained. There were 47 profile rejection records: 26 duplicate pressure-level conflicts and 21 profiles with no accepted measurements. Later scheduled/manual batches legitimately change these counts.

Passed locally:

- Go formatting/vet/race checks, Ruff, ESLint, TypeScript, Compose validation and production builds. The existing working-tree suites passed: 21 Python checks and three frontend contract checks, plus the API health checks. User-staged test removals were preserved; Phase 2 verification scripts remain independently runnable.
- Offline GDAC discovery ordering/ties, persisted state, domain/time filters, unsafe paths/destinations, index expansion/line caps and bounded provider error/size behavior. Synthetic R/D, per-parameter mode and multiprofile fixtures; independent variable missingness/QC, unit refusal, deterministic revisions, duplicate pressure refusal and corrupt NetCDF quarantine. The cached real Phase 0 corpus additionally yielded 236 accepted profiles including 59 secondary profiles and 32 per-profile rejections under this display policy.
- Disposable database: duplicate events and new-event replay, R→D supersession, late R refusal, atomic rollback after lake staging and successful retry, poison quarantine, Parquet integrity, missing manifest/Parquet reconstruction, corrupt lake withholding and repair, raw orphan/outbox recovery and retention replay.
- Local broker outage: pending state survives publication failure, active lease respected, expired lease reclaimed, published marker follows broker ack and committed replay leaves canonical identities unchanged. NATS/ingestion/normalizer were restored afterward.
- Fresh, repeated and legacy migrations; sentinel preservation, changed-checksum refusal, failed-upgrade rollback and outbox/inbox uniqueness.
- Live OpenAPI response validation, signed filter-bound pagination, invalid/repeated/unknown/budget/empty query behavior, rendered map/detail evidence, API raw checksum and web raw proxy checksum.

Actual browser visual/interaction acceptance was **not performed**: the available computer-use surface denied access to Zen. Rendered HTML and HTTP flows passed; manual visual review remains distinct.

## Boundaries and operation

Default domain is west=45, south=0, east=100, north=30. `ARGO_OBSERVED_SINCE` is an explicit stable scope start; the local default is 2025-10-01. Do not silently roll that scope on restart. Each run resolves at most 20 files, live polling runs every six hours, and a bounded historical batch runs daily after the live batch. Run `make reconcile` repeatedly for historical catch-up; these limits do not imply complete GDAC/domain coverage. Both tracks share provider concurrency and neither requires deleting volumes.

Only core GDAC R/D profile discovery is scheduled. The parser understands supported core/S-style parameter metadata, but BGC acquisition is not enabled. QC 1 and conservative variable bounds are the versioned local display policy, not the Phase 0 strict D-only training policy. Original adjustment errors and rejected values remain available in immutable raw NetCDF. Raw pressure is not represented as metres; depth is explicitly converted with the recorded GSW version.

Cursor keys are process-local: API restarts invalidate cursors with a typed error; refresh the query. Raw/lake integrity sweeps are bounded rolling batches (200 raw objects and 20 revisions per pass), so detection after external corruption is eventual. Multi-region broker/storage capacity, authentication, reviewed production rights/coverage, model snapshots/recomputation/freshness monitoring and production restore drills belong to subsequent delivery gates. No production deployment or readiness promotion was performed.
