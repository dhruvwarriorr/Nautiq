# Product surfaces delivery

This records the original section 15 acceptance. Subsequent notification evaluation, verified email recipients and schema 15 are documented in [alerts delivery](22-Phase-13-Delivery.md); the historical measurements and original bounds below are preserved.

The local product connects public ocean evidence to an authenticated private workspace, implementing blueprint section 15. Scientific promotion, public identity operations and notification evaluation/delivery remain separate gates.

## Delivered experience

| Surface | Behavior |
| --- | --- |
| `/map` | Selected native rasters, variable/forecast controls, bounded accepted-profile positions, immutable historical event geometry and official polygons/circles. Unsupported layers and source age remain explicit. Profile positions obey the selected box/window; event/authority supports carry their own dates and may extend beyond the box. |
| `/locations`, `/locations/[slug]`, `/regions/[slug]`, `/compare` | Named regional entry points, four point forecast timelines, pinned cycles, nearby original instruments with actual coordinates/time/distance/QC and official state. Named-region conditions describe the catalog center; no regional average or expected profile at an arbitrary point is invented. |
| `/research`, `/app/explorer` | Box/polygon, UTC interval, depth, temperature/salinity, Argo mode, QC, diagnostic percentile and exact profile-event membership. Snapshot pagination, original depth charts, expected state, intervals, residual heatmap and observation series retain source positions and references. |
| `/trips`, `/app/routes` | Timed outward/return/stopped routes, exact field bindings, explicit rescheduling, route diagram, retained overall status/worst samples, private account receipt claims and frozen evidence. Unknown legs are never colored safe. |
| `/app/watchlists`, `/app/alerts` | Owned points/radii, named places, polygons/routes; personal field-limit, official-advisory and source-stale rule configuration; immutable inbox evidence and acknowledgement. |
| `/app/reports`, `/app/exports` | Durable frozen jobs, status, cancellation, protected downloads and explicit format/redistribution refusals. |
| `/app/settings` | Notification opt-out, password rotation with all-session revocation and password-confirmed account deletion. |
| `/query` | Bounded deterministic grammar, typed preview and execution through existing typed views. Named regions and explicit research dates are required; relative times, ambiguous places, unsupported intents and incomplete trips require clarification. No arbitrary SQL/URLs, stored raw questions or invented values/verdicts. |
| `/insights`, `/methodology`, `/data-sources` | Discover retained diagnostics, methods, source terms, unavailable capabilities and approval boundaries. |

Research extrema/counts use all matching original levels; query previews contain at most 200 levels per profile. Full original profile panels remain available. Observation series preserve each instrument's position/time and do not interpolate across the ocean. Circle overlays approximate an exact retained center/radius with 48 segments and link to the original authority evidence.

**Alert evaluation and delivery remain unavailable.** Enabled rules record configuration intent. Empty inboxes establish neither active monitoring nor safe conditions. Evaluation, deduplication, cooldown, recovery and delivery belong to the next blueprint section.

## Private contracts

Schema 14 and the [typed API contract](../packages/schemas/product.openapi.json) add local handle accounts, salted Argon2id (64 MiB, three passes), random session proofs, SHA-256-only proof storage, five-session caps, 24-hour absolute expiry and 30-minute idle expiry. The same-origin Next.js proxy keeps proofs in HttpOnly, SameSite=Lax cookies, marked Secure for HTTPS. Exact `PRODUCT_WEB_ORIGIN` plus session-derived CSRF proof protect writes. Browser requests also bind the loaded account ID.

Ownership comes from the verified session; client owner fields are rejected. Cross-owner objects, references, receipts, rules, jobs, acknowledgements and downloads return 404. Saved objects, receipt claims, jobs and actions use UUID idempotency keys with atomic 24-hour replay records. Resource edits and cancellation require quoted versions. Account/session locks fence revocation and concurrent mutations. Unknown/duplicate fields, invalid UTF-8, malformed geometry, dateline crossings and work budgets fail explicitly.

An expired session hides private content and preserves the draft in that tab. Signing back into the same account restores it; a different account or explicit sign-out clears it. Account deletion removes owned records and queues artifacts and claimed original trip receipts for durable cleanup. Unlinked anonymous receipts retain their existing independent retention.

These accounts have no verified email, MFA or recovery provider. Public identity/deployment operations need review. Implementation follows the [Argon2 package guidance](https://pkg.go.dev/golang.org/x/crypto/argon2) and [OWASP session guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html); local verification does not substitute for a public security review.

## Frozen reports and exports

Jobs pin exact input bytes, their JSON mirror, SHA-256 and the [product policy](../packages/source-catalog/product.json). The default non-root, read-only Compose `export-worker` uses fenced 90-second leases, three abandoned-lease attempts, immutable publication, cancellation fences and durable orphan/expiry cleanup. Database outages reconnect with queued work retained. States are queued/running/ready/blocked/failed/cancelled/expired.

Reports capture owned state, claimed trip provenance, bounded research references, named-location source pins or exact event references. Location/event source documents and claimed receipts are hash/mirror checked before freezing. Forecast values and official bulletin content are omitted pending redistribution review. JSON and escaped standalone HTML carry the recorded limitations; generation never renews freshness.

Exports support user-owned route/watchlist JSON, CSV and Parquet. Bounded **accepted original Argo levels** support JSON, CSV, Parquet and observation-level NetCDF. Argo's [published reuse terms](https://argo.ucsd.edu/data/acknowledging-argo/) permit reuse; files attach programme credit, DOI 10.17882/42182, original positions/times/depths/QC, raw URL/hash, revision, method, input and worker/runtime identity. This scoped permission does not approve other source redistribution, scientific promotion or production operation. CSV protects string cells against spreadsheet formulas while keeping numeric negative coordinates numeric. NetCDF is limited to scientifically appropriate original observation records and units.

Bounds: 100 objects/kind, 20 jobs/account/day, one research page of at most 100 profiles, 10,000 original rows, 4 MiB frozen input and 8 MiB artifact. Larger queries require refinement instead of silent truncation. Files expire after 72 hours; job inputs/metadata are removed after a further 24-hour grace period. Downloads require both an owning session and a five-minute single-use grant identifier. Bytes/size/hash are checked before atomic grant use. Attachments use no-store, nosniff, no-referrer and sandbox policies.

## Verification and operation

```sh
make migrate
docker compose build api web export-worker product-verifier trip-verifier
docker compose up -d api web export-worker
make lint test build test-migrations
make phase12-verify phase12-reliability phase12-smoke
```

- Independent offline CSV/Parquet/NetCDF readback: original values/units, source credit, formula protection, row consistency and policy drift refusal.
- Disposable PostgreSQL/actual MinIO: two-account isolation, strict inputs, CSRF, concurrent retries, stale edits, references, receipt claims, alert evidence corruption, job fences, corrupted artifact refusal, single-use grants, expiry, password rotation and account deletion.
- Disposable worker: actual immutable uploads, abandoned leases, damaged inputs/mirrors, cancellation during upload, orphan removal, retry exhaustion, expiry and metadata cleanup.
- Live worker/API: public pagination/empty/clarification states, four source variables, bounded map and actual Argo exports with matching **1,978 rows** in CSV, Parquet and NetCDF, plus private reports. Temporary accounts are deleted; checked-in evidence omits credentials and private routes.
- Desktop/mobile browser: typed query execution and 50 research rows, sign-up, route/watchlist/rule/report creation, HttpOnly isolation, same-account expired-draft restoration, different-account draft clearing and explicit unknown/stale conditions without overflow or console errors.

Standard lint/race/test/build, fresh/legacy migration/checksum/rollback and offline field/event/advisory/trip checks are implementation evidence. The older **live fresh-field and two-worst-trip-sample gates currently fail because retained GFS wave/weather cycles are stale**. Their results are not rewritten as successes. Reacquiring forecasts is needed for those fresh-source gates. Historical trip replay still requires its original serving runtime; the authenticated binary adds dependencies and does not alter old receipts.

Public deployment/security/backups, scientific calibration, repeated source cadence, complete marine advisories, approved trip thresholds and notification evaluation/delivery are not claimed. See [secret-free evidence](evidence/phase12-summary.json).
