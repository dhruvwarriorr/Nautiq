# Execution contracts — v1

These policies turn the design into implementation decisions. Values below are initial engineering budgets or explicitly marked pilot science parameters, not validated vessel limits. Changing a scientific policy requires a new version and dataset/release. `02` owns source/QC/storage policy, `03` owns scientific interpretation, `04` owns reliability and `05` owns product behavior. Planned contracts are not enabled endpoints.

## 1. Phase and capability boundaries

| Capability | Current behavior | Enablement gate |
| --- | --- | --- |
| Platform runtime | Live dependency checks | Schema 3 and required dependency readiness |
| Observation query | Implemented local Argo canonical API/UI | Production source review remains separate |
| Expected/profile inference | False in gRPC/API capabilities | Pinned validated release and coverage mask |
| Field sampling | False | Reviewed product/cycle/mask/sampling contract |
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
