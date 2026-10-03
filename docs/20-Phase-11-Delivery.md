# Deterministic trip decision delivery

`services/api/internal/trips/` implements the versioned deterministic Go rule engine, timed route validation and sampling plan. `services/api/internal/science/trips.go` integrates existing immutable forecast releases and official CAP evidence, publishes private calculation receipts and verifies frozen replay. `/trips` provides timed waypoint editing, activity and pinned-release selection, worst retained samples, missing conditions, source cycles and private evidence/replay controls. No model, scientific anomaly or language-model output chooses the trip status.

## Decision rules and review boundary

Primary precedence follows `08-Execution-Contracts.md`: relevant official warning; insufficient required evidence; critical threshold; caution threshold or reviewed deterioration; then favorable only when the complete approved policy is satisfied. All fired rules, missing inputs and worst retained samples remain in the output even when another condition determines primary status. Equality uses `value >= limit`. Each sample rule records value, units, time/location, limit and policy/preference origin. Reviewed combinations use co-timed samples; reviewed deterioration uses explicit change/time bounds. Missing inputs to these rules cannot silently permit a favorable result.

The catalog policy is `packages/source-catalog/trips.json`, embedded identically in the Go package. It declares fishing/boating activities, provisional input collection for wave height, wind speed and optional surface-current speed, source-age/horizon bounds, optional combinations/deterioration and limitations. **No numeric safety limits or domain review are approved.** Caution/critical values are null, approval false and review record empty. No request can supply or approve a new threshold release. Personal preferences require an approved policy, can only tighten its limits, and cannot bypass official warnings or make required inputs optional.

Consequently current real calculations return `insufficient_data`, or `official_warning` when retained official geometry/validity establishes an intersection. `engine_available` and `production_approved` remain false. `trip_diagnostics` reports retained local calculation availability; `trip_assessment` remains false. The source policies also withhold marine advisory completeness and operational forecast approval. Completing this implementation does not approve vessel capabilities, public safety wording, source rights/cadence/coastal performance or a production release.

## Whole timed route and pinned forecasts

Requests require two to 32 timed waypoints, including outward/return legs and stops; times must increase and include an offset. Equal positions with increasing times retain a stop. No speed/travel-time/vessel model is inferred. The bounded plan uses shortest great-circle segments, at most 1,000 km, 24 hours and 512 samples, spacing 0.5–5 km and time step 1–30 minutes. Over-budget requests are rejected without silent coarsening. Dateline-crossing legs require an explicit separately supported split and are refused in this version.

The existing Field Service samples one exact release/cycle per variable. The Go adapter verifies release/hash/variable and deterministic protobuf request identity, retains the complete returned sample evidence and normalizes its actual `requested_time`, coordinate, units, support status and value. Independent field requests share the overall API deadline; individual failures remain missing input. Required masks, unavailable samples, horizon gaps, stale/missing/future cycles, wrong units, incomplete sample plans and unapproved operational inputs prevent a favorable result. Stale retained adverse values remain visible with their support status. Tide/local hazards, coast/grid resolution and unsampled extremes remain limitations.

Official intersections use the verified frozen CAP documents. Each info validity window clips whole timed great-circle legs; stationary stops become points. PostGIS geography tests complete route segments against official polygons and geodesic circles, so a warning between discrete forecast samples is not lost. Text/geocode/missing/invalid areas and expiry remain unknown. Publication rechecks source run IDs and source policies under the advisory publication lock; a feed/policy change while fields were sampled returns a retry conflict before committing an obsolete result.

## Private, immutable calculation receipts

Schema 13 adds `trip_calculations`; the existing `calculations` table stores frozen full manifests. Receipt objects stage before one SQL transaction commits calculation and verdict. The immutable manifest contains the original request, frozen clock, threshold/preference policy, generated sampling positions, full advisory snapshot and intersection identities, complete forecast response bytes, normalized field samples, output, embedded source digest and Go/platform/dependency runtime fingerprint.

POST `/api/v1/trips` returns a calculation ID, SHA-256, verdict and a random 256-bit access token once. SQL retains only the token hash. GET `/trips/{id}` and POST `/trips/{id}/replay` require that token in an Authorization Bearer header; unknown/missing/wrong access returns 404. Tokens are never query parameters. Public `/calculations/{id}` excludes trip records. No public route catalog or trip event exposes user coordinates. This scoped receipt access is separate from authenticated saved routes/watchlists in later work.

Evidence reads verify object hashes and semantic SQL mirrors, including the stored verdict. Replay reconstructs normalized fields from captured response bytes, re-evaluates advisory state from the frozen snapshot/hits, and repeats all Go rules against the frozen inputs. The verdict must match exactly; freshness is not renewed. Replay requires the exact embedded source and runtime fingerprint and returns 409 when the serving release differs. It repeats the verdict from captured samples; independent original-grid reconstruction uses the Field Service's retained release/replay workflow.

The browser holds its token only in page memory. Input changes clear prior results; controls are disabled during requests. Reloading clears access. The UI presents useful grouped missing conditions while the full exact conditions remain in the private receipt. Timed tables and worst-sample tables have keyboard-accessible scrolling; original source releases and cycles are linked. The API/proxy enforce body, parameter, coordinate, time and work budgets.

## Validation

```sh
make migrate
make phase11-verify
docker compose build trip-verifier
make phase11-reliability phase11-smoke
```

The retained Go verification executable uses explicitly synthetic reviewed policies in isolation to cover all five statuses, inclusive thresholds, warning/missing precedence, preserved adverse evidence, missing/stale/future/unsupported input refusal, personal preferences, combinations, deterioration, stops, route budgets, exact stored-input replay and safety wording. The real catalog remains unapproved with null numeric limits. The executable runs with the race detector; the Python gate verifies catalog/embed equality and release boundaries.

The independent non-root `trip-verifier` tool creates and removes a disposable database. It exercises real SQL/object storage and the Go HTTP handlers with isolated CAP/forecast fixtures: token access, public-record exclusion, exact replay, damaged object and SQL mirror refusal/recovery, a warning polygon between forecast samples, validity clipping, a source change during acquisition and injected transaction rollback. Cleanup identifies only receipts using the test's unique release IDs and fixture object prefix, preserving pilot records.

[Real-source summary](evidence/phase11-summary.json) records a private receipt identity/hash and public source-cycle evidence, without access tokens or route coordinates. Real NOAA wave/wind samples and registered NDMA CAP evidence produce the expected `insufficient_data` result. Live tests verify private access, frozen replay, strict bounds and the web proxy. Browser checks exercise submission, evidence inspection, replay, responsive/keyboard tables and clearing obsolete results. Standard lint/race tests/builds and fresh/legacy/checksum/rollback migration checks pass; field/event/advisory APIs remain independent.

The implementation is local and reviewable. Approved activity limits and domain/safety review, complete marine advisories, operational forecast/coastal/cadence/rights evidence and authenticated public release remain outstanding external gates.
