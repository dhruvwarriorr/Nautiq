# Nautiq — Implementation Blueprint

> **Purpose:** Turn the five design documents into an executable build order.  
> This file answers: **What do I implement first, what depends on what, and how do I know each layer is correct?**

---

## 1. Build philosophy

Do not try to build every service, source and model simultaneously.

The target architecture is modular, but implementation should proceed by **vertical slices**.

A useful slice goes from:

```text
real source
→ ingestion
→ normalized storage
→ backend query
→ UI
→ evidence
```

before adding another source or model.

Rules:

1. first make data correct;
2. then make scientific baselines correct;
3. then add ML;
4. then add trip decision support;
5. then harden production operations;
6. do not introduce infrastructure before a real requirement exists.

These are release principles, not one serial dependency chain. Observation/science and forecast/advisory/trip delivery are independent tracks after canonical data and provenance foundations. Trip verdicts must not wait for FPCA/ML; they do require verified advisory completeness and reproducible forecast inputs.

---

## 2. Monorepo

```text
nautiq/
├── apps/
│   └── web/                     # Next.js
│
├── services/
│   ├── api/                     # Go Core API
│   ├── ingestion/               # Go provider discovery/fetch
│   ├── notifications/           # Go alerts/delivery
│   ├── ml-inference/            # Python gRPC
│   └── field-service/           # Python gRPC/Zarr
│
├── workers/
│   ├── normalizer-go/
│   ├── normalizer-py/
│   └── batch-science/
│
├── ml/
│   ├── nautiq_ml/
│   │   ├── climatology/
│   │   ├── features/
│   │   ├── expected_state/
│   │   ├── calibration/
│   │   ├── profile_anomaly/
│   │   ├── events/
│   │   └── evaluation/
│   ├── training/
│   └── notebooks/
│
├── packages/
│   ├── proto/
│   ├── schemas/
│   ├── source-catalog/
│   └── ui/
│
├── data-pipelines/
│   ├── argo/
│   ├── argovis/
│   ├── incois/
│   ├── copernicus/
│   ├── satellite-sst/
│   └── advisories/
│
├── migrations/
├── infrastructure/
├── tests/
│   └── fixtures/
├── docs/
└── docker-compose.yml
```

Do not create empty directories for every possible source on day one. Create them as adapters are implemented.

---

## 3. Phase 0 — validate assumptions before coding the whole product

### Goal

Prove that the planned data and scientific design are feasible.

Phase 0 tooling and measured evidence are documented in `10-Phase-0-Delivery.md`. Commands are `make phase0`, `make phase0-replay`, and `make phase0-gate`. The last exits nonzero for unproven gates. No fabricated data is used to satisfy feasibility gates. Source adapters not yet implemented remain explicitly blocked.

### Tasks

1. Obtain/sample each critical source:
   - Argo GDAC;
   - one gridded SST source;
   - one wave/wind forecast source;
   - one official advisory source if accessible.
2. Verify:
   - format;
   - latency;
   - update cadence;
   - licensing/display rules;
   - data coverage in the target geography.
3. Count:
   - historical profiles;
   - profiles by region/month/depth;
   - coastal gaps.
4. Build an offline, tested executable experiment (a notebook may explain the results, but is not the source of truth):
   - harmonic climatology;
   - simple residuals;
   - HGBR baseline;
   - LightGBM candidate;
   - profile residual score;
   - FPCA prototype.
5. Measure whether the problem is learnable.

### Exit criteria

- source access is known;
- training row/profile counts are known;
- baseline climatology metrics exist;
- at least one real fishing/trip forecast source is confirmed;
- no major license blocker is unresolved.

Split the exit decision: **observation slice feasible**, **scientific prototype executed**, **trip sources operational**, and **public release approved**. The first two can pass independently; passing a sample download is not passing cadence, license, coastal coverage, forecast-cycle or advisory-completeness gates. `--require-ready` checks all declared gates and never turns an unimplemented check green. A single sample cannot prove uptime/update latency; repeated probes and issuer/product review are separate operational deliverables.

---

## 4. Phase 1 — repository and local platform

### Build

- Next.js app;
- Go API;
- Python scientific package;
- PostgreSQL/PostGIS/Timescale;
- MinIO/S3-compatible storage;
- Redis;
- NATS;
- Docker Compose;
- protobuf generation.

### Required developer commands

```text
make setup
make up
make test
make lint
```

or an equivalent task runner.

### Exit criteria

One command launches the stack and a health page confirms all local dependencies.

Updated Phase 1 also requires: ordered checksum-verified migrations on existing volumes; transactional outbox/inbox tables as foundation only; separate liveness, required-dependency readiness and full diagnostics; explicit false scientific capabilities; bounded RPC payload/concurrency; correct scientific runtime identity; reproducible contracts; secret-free failures; CI tests. Runtime capability flags do not imply loaded science. `07` lists actual verification.

---

## 5. Phase 2 — first complete data slice: Argo

Implement only enough infrastructure to make one source excellent.

### Ingestion

- read GDAC index;
- cursor by update timestamp;
- domain filter;
- bounded downloads;
- raw object storage;
- checksums.

### Normalization

- parse NetCDF;
- build profile identity;
- map TEMP/PSAL/PRES;
- apply data mode/QC policy;
- store canonical profile + levels;
- Parquet write.

### API/UI

Add:

```http
GET /profiles
GET /profiles/{id}
```

UI:

- map markers;
- profile chart;
- source/QC/provenance.

### Exit criteria

A profile displayed in the browser can be traced back to the exact raw file.

Local implementation and measured API/rendered-page/raw-byte verification are recorded in `11-Phase-2-Delivery.md`; browser visual acceptance is reported separately.

---

## 6. Phase 3 — data correctness and reproducibility

Implemented locally; [12-Phase-3-Delivery.md](12-Phase-3-Delivery.md) maps every deliverable to code and measured verification. Training snapshots preserve original levels; the standard depth grid remains in Phase 4.

Before ML:

- revision handling;
- deduplication;
- QC rejection table;
- source metadata;
- freshness monitor;
- `calculation_id`;
- frozen scientific fixtures;
- Parquet training snapshot builder.

Revision identity, deduplication, source-native QC selection and idempotent commits are required in the first Argo slice, not postponed until after scientifically questionable data reaches the UI. Phase 3 broadens coverage, replay and revision-driven recomputation. Implement outbox publisher/inbox consumer before using NATS for canonical delivery; the Phase 1 tables alone do not provide delivery semantics.

### Required tests

- delayed-mode revision supersedes real-time correctly;
- duplicate same-profile records are linked, not double-counted;
- bad units fail;
- malformed NetCDF is quarantined;
- re-running ingestion is idempotent.

### Exit criteria

Reprocessing the same raw dataset produces the same canonical scientific result.

---

## 7. Phase 4 — climatology first

Implemented locally; [13-Phase-4-Delivery.md](13-Phase-4-Delivery.md) maps each deliverable to code, immutable real-data artifacts, comparison UI and measured verification. The reference uses training years only; local selection leaves scientific production approval false.

Implement the physics/statistical reference before boosting.

### Deliverables

- standard depth grid;
- harmonic seasonal climatology;
- spatial/depth pooling strategy;
- climatology uncertainty/spread;
- fallback behavior;
- evaluation by region/depth.

### UI

Add:

```text
Observed
Expected climatology
Difference
```

### Exit criteria

Nautiq can answer “warmer/cooler than historical normal” without ML.

This baseline becomes the model to beat.

---

## 8. Phase 5 — LightGBM expected-state residual model

Implemented locally; [14-Phase-5-Delivery.md](14-Phase-5-Delivery.md) maps all deliverables to code and measured checks. Both residual candidates remain diagnostic, with climatology active. Previously inspected test data, provisional promotion criteria and sparse independence audits do not authorize scientific production promotion.

### Build

- shared feature package;
- grouped spatial/temporal split logic;
- LightGBM residual training;
- HGBR comparison;
- MLflow experiment logging;
- model bundle/release manifest;
- Python gRPC inference service.

### Evaluate

Compare:

```text
climatology
vs
HGBR baseline
vs
climatology + LightGBM residual
```

### Exit criteria

LightGBM is promoted only if it materially beats climatology on untouched test data without unacceptable subgroup regressions.

If it does not, climatology remains production.

---

## 9. Phase 6 — calibrated uncertainty

Implemented diagnostic workflow: [delivery and verification](15-Phase-6-Delivery.md). Scientific coverage qualification retains the empirical and independent review gates below.

Benchmark:

- LightGBM q10/q50/q90;
- CatBoost MultiQuantile.

Then add:

- CQR;
- region × depth Mondrian calibration;
- hierarchical fallback;
- coverage monitoring.

### Exit criteria

Nominal intervals have acceptable empirical coverage overall and in adequately sampled subgroups.

---

## 10. Phase 7 — profile anomaly system

Implement in this order.

### 10.1 Standardized residual profiles

- residual by standard depth;
- uncertainty normalization;
- depth coverage mask.

### 10.2 Residual-profile score

Prototype:

- squared standardized residual sum;
- robust/shrinkage Mahalanobis distance.

Calibrate to historical percentile by comparison group.

### 10.3 FPCA

- FPCA basis;
- component scores;
- reconstruction error;
- depth-mode interpretation.

### 10.4 Baselines

For comparison only:

- Z-score profile summaries;
- Isolation Forest.

### Exit criteria

A profile anomaly can be explained by depth and structure, not just a black-box score.

---

## 11. Phase 8 — gridded fields

Add one gridded source at a time.

Order:

1. satellite SST;
2. waves;
3. wind/weather;
4. currents.

Implement:

- field catalog;
- Zarr normalization;
- Field Service;
- point sampling;
- route sampling;
- raster tiles.

### Exit criteria

UI can show current/forecast fields with exact provider/cycle/valid-time metadata.

---

## 12. Phase 9 — event detection

### Surface thermal events

Implement climatology/percentile/persistence event logic on gridded SST.

### Generic regional anomalies

Implement spatiotemporal grouping of exceedance cells/profiles.

### Exit criteria

Nautiq distinguishes:

```text
one anomalous profile
vs
persistent regional event
```

and never labels the first as the second.

---

## 13. Phase 10 — official advisories

Implement:

- source adapter;
- geometry;
- validity window;
- feed health;
- revisions;
- UI layer.

### Critical rule

`unknown advisory state` is not equal to `no advisory`.

### Exit criteria

If the feed becomes stale, the UI says so and the trip engine cannot produce a favorable verdict.

---

## 14. Phase 11 — trip/fishing decision engine

### Inputs

- route/time;
- activity;
- advisory state;
- forecast field samples;
- threshold set;
- freshness.

### Rules

Implement as deterministic Go code with versioned thresholds.

Every verdict must return:

```text
status
rules fired
worst value/time/location
missing inputs
source cycles
threshold version
calculation_id
```

### Exit criteria

Every verdict is reproducible from stored inputs, and safety wording passes tests.

---

## 15. Phase 12 — product surfaces

Build in this order:

1. map;
2. location page;
3. profile explorer;
4. trip assessment;
5. route view;
6. watchlists;
7. alerts;
8. research explorer;
9. reports/exports;
10. natural-language query layer.

Authentication/ownership checks precede saved watchlists/routes, alerts and private reports/exports. Read-only public exploration can ship earlier. Offline fixtures, empty/partial/stale states and contract validation arrive with each surface rather than being added at the end.

Natural language comes late because it should sit on top of already-correct typed APIs.

---

## 16. Phase 13 — alerts and notifications

Implement:

- alert-rule evaluation;
- deduplication;
- cooldown;
- recovery;
- delivery retries;
- evidence snapshots.

Start with in-app/email.

Add push/SMS/other channels only when there is a real need.

---

## 17. Phase 14 — production hardening

Required before calling the product market-ready:

- authentication;
- TLS/private service networking;
- secret management;
- backups/restore test;
- source health;
- scientific kill switches;
- model rollback;
- tracing/metrics/logging;
- status page;
- incident runbooks;
- accessibility pass;
- safety/legal review of trip wording and advisory redistribution.

---

## 18. Test pyramid

### Go

```text
unit
provider adapter
trip-rule tables
DB integration
HTTP contracts
concurrency/race
```

Always run:

```bash
go test -race ./...
```

### Python

```text
feature unit tests
climatology tests
profile interpolation tests
split leakage tests
model serialization tests
calibration tests
FPCA/reconstruction tests
frozen inference regression
```

### Data

Fixture per provider:

```text
valid
minimum valid
revised
duplicate
bad QC
bad units
schema changed
corrupted
```

### Frontend

- component tests;
- Playwright flows;
- accessibility tests;
- visual regression for critical advisory/trip states.

### End-to-end scientific fixture

A frozen case should test:

```text
raw source
→ canonical observations
→ expected state
→ profile score
→ API response
→ UI evidence text
```

---

## 19. CI pipeline

On every pull request:

```text
format
lint
type check
Go tests + race where practical
Python tests
frontend tests
schema/contract compatibility
DB migration test
build
security scan
```

On main/staging:

```text
build images
integration test
deploy staging
run scientific smoke fixtures
run browser E2E
manual/controlled production promotion
```

A model promotion is separate from an application deploy.

---

## 20. Versioning

Version independently:

```text
observation schema
QC rules
training dataset
feature schema
climatology
ML models
calibration
FPCA basis
event detector
trip threshold set
API
```

A calculation stores the exact versions used.

Do not create one giant “v2” that hides scientific changes.

---

## 21. Architecture decision records

Create an ADR whenever a decision changes system shape.

Initial ADRs:

```text
ADR-001 Go for Core API/ingestion
ADR-002 Python for scientific services
ADR-003 PostgreSQL/PostGIS/Timescale for operational observations
ADR-004 Parquet + Zarr on object storage
ADR-005 NATS JetStream event backbone
ADR-006 Climatology + residual ML reference design
ADR-007 Residual-profile + FPCA anomaly design
ADR-008 Trip assessment is deterministic, not ML
ADR-009 Official advisories remain separate from Nautiq signals
ADR-010 Deployment starts simple; Kubernetes only when justified
```

---

## 22. Key implementation risks

### Too many technologies

Mitigation:

- one monorepo;
- local Compose;
- stable contracts;
- postpone Kubernetes;
- do not create a service until a separate runtime/scale need exists.

### Coastal data gaps

Mitigation:

- separate open-ocean profile ML from satellite/field products;
- publish coverage masks;
- say insufficient rather than extrapolate.

### ML looks good because of leakage

Mitigation:

- fixed reference definition;
- grouped profile splits;
- spatial/time holdouts;
- no same-time anomaly variables in the reference model.

### Forecast/advisory source licensing changes

Mitigation:

- provider adapters;
- source catalog;
- at least one replaceable path for each critical data class.

### Decision-support liability

Mitigation:

- deterministic rules;
- official advisories dominate;
- controlled wording;
- `unknown` state;
- legal/domain review before public launch.

### Scientific unit/schema bug

Mitigation:

- data contracts;
- plausible range tests;
- frozen fixtures;
- kill switches;
- source-level health dashboards.

---

## 23. What to build first this week

A practical first sequence:

### Day 1–2

- monorepo;
- Docker Compose;
- PostgreSQL/PostGIS;
- Next.js shell;
- Go health API;
- Python package skeleton.

This platform already exists. Use the updated Phase 1 readiness/migration verification rather than recreating it. Complete or explicitly block Phase 0 source/science gates before expanding the corresponding track.

### Day 3–4

- download a small real Argo dataset;
- store raw file;
- parse one profile;
- normalize it;
- save canonical rows.

### Day 5

- expose `/profiles/{id}`;
- render temperature/salinity depth chart;
- show raw-source provenance.

Then stop and review.

Do not begin ML until this slice is scientifically correct.

---

## 24. Delivery dependency graph

```text
Source-specific feasibility + local platform + contracts
      ├─ Argo + QC + immutable revisions + profile API/UI
      │    └─ frozen datasets + train-only climatology
      │         └─ residual ML + independent calibration
      │              └─ profile structural methods
      ├─ SST fields + baseline/coverage ── regional thermal events
      └─ wave/wind fields + cycle/route sampling
           + verified official advisories + reviewed thresholds
                └─ deterministic trip engine + UI

Each track: tests + provenance + failure states + bounded resources
Saved state: authentication + authorization before delivery
Validated result APIs → alerts/exports/reports → natural language
Public launch: operational coverage/licenses + scientific review + restore/security gates
```

This dependency order prevents the project from becoming a polished UI built on unverified scientific assumptions.

## 25. Change and acceptance discipline

Before each phase: pin the input/output contract, open assumptions, fixtures and measurable exit checks. Define unavailable behavior before adding successful UI states. Link requirements to `09-Edge-Case-Register.md`; each gate is either implemented/tested, measured/passed, or pending/blocked. A test on synthetic fixtures verifies code behavior, not real source access or model quality. Static local checks, live local smoke, provider feasibility, scientific release and production acceptance are separate claims.

Phase 0 dependency lock is `ml/requirements-phase0.lock`; Phase 1 Python serving has a separate runtime lock. CI runs offline scientific fixtures and platform checks, not live providers on every PR. Live feasibility runs preserve hashed artifacts locally and publish a reviewed compact evidence report. Missing provider credentials are reported, not bypassed. No commit, push, deployment or model promotion is automatic.

## Profile anomaly delivery status — 2026-10-02

The [implementation and verification report](16-Phase-7-Delivery.md) and [measured evidence](evidence/phase7-summary.json) complete the profile-anomaly tasks in section 10: standardized residual/mask evidence, weighted magnitude and shrinkage correlation distances with matched historical ranks, a stored weighted discrete PCA basis with component scores/reconstruction/depth-mode evidence, and comparison-only Z-score/Isolation Forest baselines. The actual shared package is `ml/nautiq_ml/anomaly/`. The fixed complete-case prototype rejects incomplete vectors rather than claiming validated sparse FPCA. Exact parent/revision release lineage, leased recomputation, APIs, registry tracking and explorer pages are implemented. Scientific event qualification remains a separate blocked gate.

## Gridded field delivery status — 2026-10-02

The [field implementation report](17-Phase-8-Delivery.md), [OpenAPI contract](../packages/schemas/fields.openapi.json) and [real-source evidence](evidence/phase8-summary.json) complete section 11. Separate adapters for NOAA OISST, GFS-Wave, GFS weather and single-run HYCOM currents publish immutable raw/Zarr/catalog/calculation evidence. The shared package is `ml/nautiq_ml/fields/`; `ml/Fields.Dockerfile` runs an independent read-only Field Service. Point, timed route, polygon and raster APIs preserve masks, cycle/time identities, bounded work and explicit unsupported states. The `/fields` explorer exposes provider/cycle/valid-time metadata, variable/time controls and route samples. Full regional acquisitions, raw replay, corruption recovery, production builds, live contracts and interactive browser checks establish the local implementation exit. Repeated provider cadence, coastal accuracy and scientific/public release approval remain unproven; regional events, advisories and trip rules are later work.
