# Execution contracts — v1

These policies turn the design into implementation decisions. Values below are initial engineering budgets or explicitly marked pilot science parameters, not validated vessel limits. Changing a scientific policy requires a new version and dataset/release. `02` owns source/QC/storage policy, `03` owns scientific interpretation, `04` owns reliability and `05` owns product behavior. Planned contracts are not enabled endpoints.

## 1. Phase and capability boundaries

| Capability | Current behavior | Enablement gate |
| --- | --- | --- |
| Platform runtime | Live dependency checks | Schema 10 and required dependency readiness |
| Observation query | Implemented local Argo canonical API/UI | Production source review remains separate |
| Historical climatology | Dynamic API flag: selected ready reference plus supported current comparison | Train-only artifact integrity; local prototype only, production approval false |
| Expected/profile inference | Dynamic implementation flags for exact selected/loaded releases | Qualification, coverage and scientific approval are separate |
| Field sampling | Dynamic flag for independent runtime and compatible selected fresh data | Exact product/cycle/mask/time contract; prototype approval false |
| Official advisory state | Unknown | Verified machine feed, completeness, cadence and rights |
| Trip assessment | False | Operational forecast/advisory inputs plus approved rules |

`/health/ready` only reports runtime eligibility for traffic. `/api/v1/health` is full diagnostics. Public capability declarations identify implementation support, not live availability; future result endpoints must check current source/release state separately.

## 2. Resource and time policy

| Operation | Initial hard budget | Failure behavior |
| --- | --- | --- |
| Phase 0 download | 64MiB/object, 192MiB/run, 512MiB expanded index, 4KiB/index line | Stop/quarantine and record reason; no truncated publication |
| Phase 0 provider fetch | 30s socket timeout, 120s wall deadline, 3 attempts, sequential requests ≥200ms apart | Retry transport/429/5xx; long Retry-After stops source |
| Runtime diagnostics | 3s overall | Sanitized unavailable result |
| Scientific runtime RPC | 1MiB send/receive, 16 concurrent RPCs, 4 workers | Resource exhausted, bounded shutdown |
| Implemented Phase 2 profile list | 1–200 items, default 50, max 366-day range, bounded bbox | 400 invalid input / 422 query budget exceeded |
| Planned route assessment | ≤100 waypoints, ≤24h trip, ≤10,000 space/time samples | Reject budget excess; no hidden downsampling |
| Planned REST JSON | 1MiB body, 10s operation deadline | 413 too large / 504 deadline |
| Planned exports | Background job with per-user row/byte quota | Explain quota; never unbounded synchronous allocation |

All valid/observed times are UTC RFC3339; queries require explicit offsets and reject nonexistent/ambiguous local times unless resolved by the UI. Durations use monotonic clocks; source ages use UTC with clock-skew tolerance. Negative source age beyond 5min is invalid-clock state, not fresh. Freshness budgets are per product, versioned and based on observed provider cadence. A null cadence in the catalog means unverified; never default it to healthy.

## 3. Profile query contract

Implemented Phase 2 `/api/v1/profiles`: required `bbox=west,south,east,north`, `start`, `end`; `start<end`, end exclusive. Dateline crossing is expressed as two boxes; split in the client rather than silently querying almost the whole globe. Canonical coordinates normalize longitude to [-180,180). IDs are stable, opaque API identifiers; revision digest is separate. Reject unknown parameters. Return current QC-accepted revisions as of a query snapshot. Cursor binds filters, snapshot, last sort tuple and schema version; altered/expired cursor returns a typed error. `packages/schemas/profiles.openapi.json` is the initial contract.

Implemented Phase 2 `/api/v1/profiles/{id}` returns raw location/time, original-level series, QC/mode, raw artifact digest/source reference and canonical revision. Standard-grid values are a separate derived product, never substituted for original levels without labels. Original pressure and converted depth retain units/conversion version. A missing variable is null with a reason; no serialization of nonfinite numbers.

Use `application/problem+json`: `type`, `title`, `status`, stable `code`, `request_id`; optional field violations. No raw SQL, provider payload, credential, filesystem path or stack trace. 404 is absent ID, 410 is explicitly unavailable retained artifact/expired job, 409 is revision/idempotency conflict, 429 is quota with Retry-After, 503 is unavailable required capability. Missing scientific prediction does not turn a valid observation response into a whole-request 500.

## 4. Observation/reference matching

Scientific profile comparison uses the same position/time/depth and variable as the profile being scored. A queried location is not a profile location. Location summaries must declare their nearest/radius/aggregation rule and validated radius/time/depth support before enablement. No initial arbitrary matching radius is invented to make coastal answers possible. Surface analyses and 10m Argo temperature are separate measurements. Reanalysis/assimilation dependencies prevent calling correlated products independent evidence.

Required result evidence: stable source/profile ID, raw/revision digest, observed/received/calculated times, position/depth, QC policy, method release/estimand, coverage mask, valid interval and calculation manifest. Degraded fallback returns a different method release and explicit reason. Stale derived results are never labelled current after upstream supersession.

## 5. Trip rule contract — blocked until domain review

Precedence is deterministic and preserves all diagnostics:

| Condition (evaluated in order) | Primary verdict |
| --- | --- |
| Relevant active known official warning | `official_warning` |
| Unknown/stale/incomplete advisory coverage OR missing/stale/out-of-domain/out-of-horizon required field OR unresolved route timing | `insufficient_data` |
| Any required critical threshold met/exceeded (`value >= limit`) | `unfavorable` |
| Any caution threshold met/exceeded, or reviewed deterioration rule fires | `caution` |
| All required coverage/freshness/rules satisfied throughout trip | `favorable` |

Known adverse measurements remain prominent even if insufficiency is primary. Missing data never cancels a warning. A bulletin cancellation must be explicit/versioned; absence from a failed/partial fetch is not cancellation. A warning from one authority remains relevant even when another feed is stale. Advisory domain/type coverage is part of required input, not just age.

No default numeric wave/wind/vessel safety thresholds are approved. Threshold release must define activity, variable, unit, caution/critical boundaries, authoritative vs preference origin, inequality, horizon/freshness, optional variables, combinations and domain-review record. A preference may tighten policy, but cannot suppress warnings or make missing inputs optional. Without an approved threshold release the engine is unavailable.

Routes require timed waypoints (including stops/return) or an explicitly supplied travel-time model. Sampling selects space/time resolution justified by product resolution and hazard dynamics; worst sampled value is not a guarantee about unsampled extremes. Use consistent product cycles per variable across the request and pin provenance. A provider without initialization-cycle metadata is a prototype input only. Grid resolution, coastal masking, tide/local hazard omissions and forecast uncertainty remain disclosed. No automatic favorable verdict is generated from Phase 0 JSON.

## 6. Calculation and event contracts

Calculation manifest: immutable ID; input raw/revision digests or product/cycle/valid-time/object manifests; selected observations/sampling coordinates; all method/QC/feature/calibration/threshold versions; code/release digest; as-of time; valid window; output status/reasons. Store a new manifest for recomputation and link `supersedes`; preserve the prior result for alert/report reconstruction.

Event envelope v1: UUID event ID, bounded event type, positive schema version, stable aggregate key, 64-hex revision digest, created UTC time, bounded JSON object payload. Database outbox uniqueness is `(event_type, aggregate_key, revision_sha256)`; inbox uniqueness is `(consumer_name, event_id)`. Each distinct product/variable/cycle must have its own aggregate key. A schema/method recalculation has a new revision digest incorporating the method/input manifest; it cannot reuse an old event key and disappear as a duplicate. Do not put scientific file bytes in the event.

Leased outbox dispatch/inbox processing/reconciliation are implemented for Argo in Phase 2; see `11-Phase-2-Delivery.md` for measured checks and remaining production gates. SQL tables alone do not establish delivery. Required delivery checks: publish failure after commit, publish ack loss, consumer commit before ack failure, duplicate delivery, out-of-order revision, poison event, expired lease and full replay with identical canonical results.

## 7. Promotion and approval records

Phase 0 gates are explicit booleans with limitations; unexecuted gates are false. Report success means the tool completed, not that all gates passed. `make phase0-gate` exits 2 when any gate is unproven. Model/public-trip release additionally requires prespecified numerical quality gates, subgroup sizes, independent audits, operational source review, licenses, kill switches, auth, restore test and actual service load tests. Unknown entries cannot be filled with assumptions or synthetic fixtures. Record owner and evidence URI for every future approval; no automated promotion is implemented.


## Implemented calculation and snapshot contracts

Schema 4 adds `/api/v1/sources`, `/qc-rejections`, `/profiles/{id}/revisions`, `/profiles/{id}/statistics`, `/calculations/{id}`, `/training-snapshots`, `/training-snapshots/{id}` and its `/parquet` download. `packages/schemas/science.openapi.json` defines their bounded contract. List limits are 1–200 (default 50); unknown/repeated/malformed parameters fail. Requests use eight shared slots and eight-second deadlines; snapshot downloads have two slots and a 128 MiB ceiling, and verify full SHA-256 before success headers.

Calculation IDs are content-addressed immutable manifests, not request traces. Manifests pin raw/canonical inputs, code/runtime/method/QC policy, evaluation time and outputs. Normalization and original-level summaries become stale on supersession; a leased summary job checks the expected revision and current lease before publication. Summary endpoints join the current revision so an old aggregate is never labelled current. Historical training calculations remain frozen.

Snapshots require explicit timezone-aware `AS_OF`, preserve one selected revision per stable profile at that time, and freeze split assignments before later fitting. The policy requires profile/parameter D, adjusted fields and QC 1. All variables/native depths of a profile share a temporal split; a missing salinity label does not discard a valid temperature label. No interpolation or synthetic labels are introduced. Bounds apply to candidate profiles/levels before allocation; overflow fails rather than silently downsampling. Hash-verified object publication precedes one SQL manifest commit. See `12-Phase-3-Delivery.md` for real counts and replay evidence.

Local ingestion freshness uses only successful live upstream checks; legacy/backfill/reconciled/import/replay operations cannot refresh that timestamp. Provider freshness stays unverified until both cadence review and an observation-age budget exist. The source monitor reports queue age/count and QC audit-group counts, and expires after three minutes without a successful refresh. QC counts are audit groups, not a measured rejection rate over all source observations.

## Historical-reference and comparison contract

Schema 5 adds `/api/v1/climatology-releases`, `/climatology-releases/selected`, `/climatology-releases/{id}` and `/profiles/{id}/climatology`, described by `packages/schemas/climatology.openapi.json`. They reuse eight bounded evidence slots/eight-second deadlines and typed sanitized problems; list limits are 1–200, default 50. Invalid/absent IDs return evidence-not-found; unknown/repeated queries fail. An accepted profile returns its current revision and either reference-unavailable, pending, ready, partial or unavailable comparison state. Null expected values or observations never become zero differences or a whole-profile prediction failure.

Fit calculations freeze input snapshot/raw/revision hashes, grid/policy/method/code/runtime, fitting and dataset years, all evaluation blocks and artifact checksums. Comparisons bind profile revision and selected reference, hash-verify raw/canonical/bundle inputs and refuse SQL/lake divergence. Signed difference is observed minus conditional mean; direction is descriptive, with no anomaly/event/confidence verdict. Fitting ends in 2016; the dataset's end year 2024 is not advertised as fitting coverage.

Publication stages immutable output before an atomic SQL transaction. The canonical selection lock and final lease token/time, current ready revision and selected-reference checks prevent late work from publishing after revisions, reference switches or lease loss. Superseded live comparisons become stale; frozen fits/snapshots remain frozen. Temporary object/checksum failures retry with bounded backoff so restored verified artifacts recover; incompatible policy/code or invalid projections quarantine work. Fit is bounded to 2,000 profiles/100,000 levels, 128 MiB input Parquet and 16 MiB per output artifact; selecting a reference refuses >2,000 current profiles. Selection is explicit local configuration, never production approval. `/capabilities` reports climatology only for a selected ready reference with supported current comparison evidence; Expected-mean model capabilities follow the pinned-runtime contract below; calibrated uncertainty, scientific anomaly, advisory and trip capabilities remain unavailable; field sampling follows its independent contract below.

## Expected-mean model and inference contract

Schema 6 adds immutable expected-state releases, exact MLflow run/registry metadata, explicit selection and leased revision/model comparison jobs. Schema 7 stales/restores live model comparisons atomically when the selected climatology reference changes. The API contract is `packages/schemas/expected-state.openapi.json`: release inventory/detail/selection and `/profiles/{id}/expected-state` reuse existing bounded evidence slots, deadlines, strict query validation and sanitized problems.

The shared `ocean-reference-features-v1` schema contains latitude, longitude, standard depth, first/second annual harmonics and basin ID. Labels, year trends, IDs, current satellite/weather context and unvalidated coastal statics are excluded. Fit and support use only training data; tuning chooses predeclared candidate leaf counts/early stopping. Calibration/test only contribute diagnostics. Full spatial/platform audits refit the entire reference and residual model on held-group complements, with a spatial buffer. Reports compare climatology/HGBR/LightGBM on matched rows and preserve subgroup support counts/nulls. Provisional thresholds, the previously inspected test block and sparse independence audits cannot authorize promotion; climatology remains active.

Serving requires exact `ML_RELEASE_ID`, native model and bundle/report/manifest checksums, feature order, embedded-reference checksum, expected/climatology implementation compatibility, locked dependency/runtime fingerprints and a recomputed promotion decision. Registry latest versions and aliases cannot select a runtime. Typed gRPC batches have at most 32 points/1 MiB; missing means stay null. Expected state is a conditional mean, never an asserted median or calibrated interval. TreeSHAP contributions plus model bias reconstruct the diagnostic residual, with no causal claim.

Comparison publication verifies source/canonical Parquet and SQL projections, then the final current revision, lease token/time, selected model and matching climatology under the canonical selection lock. Temporary runtime/artifact failures retry; invalid projections/policies quarantine. Selection changes cannot publish obsolete inference. Frozen snapshots/model fits remain frozen and matching current cached comparisons can be restored. Scientific production approval is constrained false in SQL and response contracts. `expected_state` requires exact loaded/selected release/checksum and supported current evidence; `ml_residual` additionally requires a qualified promotion decision. Intervals, profile diagnostics and fields follow the independent contracts below; scientific anomaly, advisory and trip capabilities remain unavailable. See `14-Phase-5-Delivery.md` for measured results and budgets.

## Implemented predictive interval evidence

The diagnostic quantile/CQR workflow, exact parent pins, profile aggregation unit, hierarchical fallback, revision/selection/lease checks and fixed-reference coverage monitor are delivered in [the uncertainty implementation report](15-Phase-6-Delivery.md). Its current measurements are in [the evidence snapshot](evidence/phase6-summary.json). `predictive_intervals` records supported implementation availability; `calibrated_uncertainty` requires empirical coverage and independent review gates. The already inspected historical test cannot establish untouched-test approval. Mean and median remain separate; no automatic recalibration or anomaly verdict is introduced.

## Profile anomaly execution contract — 2026-10-02

[Profile delivery](16-Phase-7-Delivery.md) pins the exact uncertainty → expected mean → climatology → snapshot lineage. Normalization uses raw train-fitted q10/q90 half-width, not CQR corrections or Gaussian sigma. Covariance/PCA/forest fit only complete training vectors; percentile references use separate calibration profiles. The fixed eleven-depth 10–500 m mask is independent per variable, and incomplete vectors get null aggregate evidence. Weights, covariance terms, component scores, reconstruction and finite empirical rank support remain inspectable. Selection/revision/lease checks guard atomic publication, and every ancestor selection invalidates current comparisons. API and RPC budgets, hashes and unavailable states are specified in the delivery and [OpenAPI](../packages/schemas/anomaly.openapi.json). `profile_anomaly_diagnostics` reports exact pinned implementation support; scientific anomaly verdicts remain false. Fixed distributions never refit automatically.

## Implemented regional field contract

Schema 10 and `packages/schemas/fields.openapi.json` define the catalog, exact-release detail, point/route/polygon and raster endpoints. `field_sampling` requires a responsive independent Field Service plus compatible selected ready data with unmasked support inside provisional source-age budgets. A request still validates its location, time, mask and exact manifest pin. Scientific approval remains false. Forecast cycle is taken from source initialization; daily OISST has no cycle and preliminary/final revisions remain distinct.

Masked bilinear and linear forecast-time sampling refuse positive-weight missing support, outside-domain points, horizon extrapolation and mixed cycles. Vector components are interpolated before speed/direction; wave angles use circular components. Land is never replaced by nearby water. Timed routes require 2–32 waypoints, increasing explicit UTC times, at most 1,000 km/96 hours/512 samples, spacing 0.5–5 km and time step 1–30 minutes. Candidate polygon grids are bounded to 10,000 native cells; invalid or dateline-crossing polygons are rejected. These implementation limits supersede the broader planned route-assessment budgets for field sampling only.

HTTP JSON bodies are limited to 32 KiB. Eight shared evidence slots, 8 s HTTP/6 s RPC deadlines, four field workers/eight active RPCs and 1 MiB messages bound serving. Requests read at most 32 MiB compressed chunks with a 64 MiB decoded cache. Tiles are 256×256 RGBA, zoom 0–12, at most 300 KiB. Exact normalization calculation IDs identify durable frozen release evidence; returned sampling receipts separately pin request/output hashes, code/method and evaluation time. Ephemeral route requests do not create saved personal data. Immutable raw/chunk staging precedes atomic release/calculation/outbox publication; late cycles cannot replace newer selected data. Corruption withholds sampling until verified-byte recovery. See [delivery](17-Phase-8-Delivery.md) for measured evidence and source/production limits.

## Implemented event evidence contract

Schema 11 and `packages/schemas/events.openapi.json` define bounded history/baseline/run catalogs and indexed regional event queries. `event_detection_diagnostics` means a retained diagnostic implementation exists; `regional_events` remains false for scientific event approval. Detailed runs/components verify report, calculation, exact parent manifest/array/raw or anomaly-bundle/comparison hashes on read. Catalogs describe indexed metadata and may show unavailable or stale snapshots.

The frozen policy is `packages/source-catalog/events.json`. Baselines require the exact 1982–2011 daily axis, native 0.25° grid, at least 27 years and 80% finite seasonal support. Fixed ±5 actual-day pools, interpolated February 29 and 31-day cyclic smoothing never absorb detection-year labels. Strict exceedance must persist for five days. Two observed finite gap days join only two already-qualified runs; unknown days never bridge. SST components use four-neighbor space and same/adjacent cells on consecutive days; regional support requires four cells and 1,000 km² on five consecutive supported days. Intensity is area-weighted SST departure from seasonal mean in °C; prototype category uses departure divided by threshold–mean. Degenerate threshold scale is unavailable.

Profile candidates use the exact selected anomaly lineage and historical weighted-squared-residual rank at least 95, same variable/direction, 50 km and 48 actual UTC hours. A regional point group needs three profiles, three platforms and three dates spanning at least two days; other groups remain isolated. Grouping can chain successive observations. Profile intensity is dimensionless residual-score evidence, and percentile is descriptive rank, not event probability. Geometry is MultiPoint only. Entire queried profile snapshot identities and available/missing comparison IDs are rechecked under the shared canonical lock at publication. Later revisions, new profiles, comparisons or ancestor selection changes mark the view stale without mutating archived runs.

Hard budgets: 4,096 native cells, 366 detection days, 2,000 profiles/4,000 variable points, 500 components, 20,000 intervals and 200,000 qualified cell days. Source acquisition has three concurrent quarterly requests, 55 s sockets/120 s per-request retry deadline, 16 MiB raw objects and 128 MiB retained-input budget. Arrays expand to at most 192 MiB with no pickle/object dtype; compressed arrays/reports are at most 16 MiB. Go shares eight request slots, two integrity reads and an 8 s deadline. Read verification is bounded to exact retained bytes; numeric contracts are verified by the worker. Unknown, repeated, malformed, over-budget and dateline-crossing query bounds are refused. Replay preserves inputs and snapshot time; code changes create a new immutable identity. No public scientific approval, live refresh or notification follows from a historical candidate.

## Official CAP evidence contract

`packages/source-catalog/advisories.json` freezes source registration, access, work bounds and the independent marine-completeness/cadence/rights gates. Schema 12 and `ml/nautiq_ml/advisories/` retain exact original XML, conditional ETag receipts, parser/runtime/policy/code identities, feed runs, immutable message variants and explicit CAP references. Missing/rejected/failed source work is unknown; an empty index cannot cancel earlier warnings. Same-sender exact identity and increasing issue time are required for an actual/public Update or Cancel; incomplete updates and conflicting identities cannot withdraw retained warnings. Original effective/onset/expiry times and all languages are preserved. Unresolved text/geocode/geometry/validity is potential relevance, never an invented polygon or expiry.

Go API point-state interpretation verifies immutable report/raw/calculation and revision mirrors and derives PostGIS geometry from those frozen documents. A geometry-supported, valid official warning has priority even if another required source is stale/unknown. Otherwise `known_none_intersecting` requires every required source's verified complete fresh evidence and production approval; the current release has neither and returns unknown. `/advisories` exposes transport, age, integrity, coverage, bulletin validity and revision ambiguity separately. [Delivery and validation](19-Phase-10-Delivery.md) do not authorize trip thresholds or public release.
