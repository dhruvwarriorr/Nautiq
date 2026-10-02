# Nautiq event detection delivery

Nautiq retains and serves fixed-reference SST persistence candidates and separate sparse profile anomaly groups. A single unusual profile remains isolated evidence; it cannot acquire a heatwave polygon. The implementation includes archived source acquisition, seasonal fitting, native spatial/time components, profile snapshot grouping, immutable calculations, replay/recovery, bounded Go APIs and an event explorer. Scientific event approval remains false.

## Fixed daily reference and thermal method

The source is the [NOAA PSL high-resolution daily OISST archive](https://psl.noaa.gov/data/gridded/data.noaa.oisst.v2.highres.html). It is a blended satellite/in-situ analysis and does not supply independent Argo validation. Baseline and detection use the same archive/product/native grid, with no implicit combination with the recent NCEI field releases. Each quarterly NCSS request, raw response hash and normalized array is retained. Requests are bounded and restartable; an explicit refresh acquires a new revision while old inputs remain immutable.

The [versioned policy](../packages/source-catalog/events.json) fixes 1982–2011 as the 30-year baseline. For each seasonal day/cell, the detector pools ±5 actual daily observations around that day across baseline years, computes a mean and linear 90th percentile, interpolates February 29 from its neighbors, then applies a 31-day cyclic mean. At least 27 years and 80% finite pooled support are required. Missing seasonal support remains missing through smoothing. Baseline years cannot be a detection window. Reference updates require an explicit new method/policy/artifact.

The threshold-duration approach follows [Hobday et al. (2016)](https://passage.phys.ocean.dal.ca/~olivere/docs/Hobdayetal_2016_PO_HierarchMHWDefn.pdf) and the [author reference implementation](https://github.com/ecjoliver/marineHeatWaves). This implementation intentionally keeps unknown daily observations unknown rather than replacing them with climatology. Strict threshold exceedance for five consecutive days qualifies a cell. At most two observed finite below-threshold days can join two already-qualified runs; four-day runs cannot qualify by joining. A degenerate threshold-minus-mean scale is unavailable.

Connected components use four-neighbor space and same/adjacent cells across consecutive days. Regional candidates require at least four native cells and 1,000 km² on five consecutive supported days. Those regional minima are declared prototype policy choices. Geometry is the union of actual native cells and preserves holes; it is the union footprint over the run, not a claim that all cells qualified simultaneously. Daily support separately records that changing footprint. Intensity is SST departure from the seasonal mean in °C, with area-weighted means and peak values/dates. Prototype category is the floored departure/(threshold–mean), capped at four. Window boundaries and missing adjacent support disclose censoring.

## Sparse profile method

The exact selected anomaly release and its reference/expected/interval ancestors are pinned. Complete existing per-variable comparison evidence supplies historical weighted-squared-residual ranks. Rank at least 95 is a declared prototype exceedance choice, not event probability. Same-variable/same-direction points connect within 50 km and 48 actual UTC hours; graph chains are explicit. A regional point group needs three profiles, three distinct platforms and three observed dates spanning at least two days. Other components are `isolated_profile_anomalies`.

Every profile component retains MultiPoint geometry and dimensionless score intensity. No area or dense SST field is inferred between observations. Missing comparison/rank evidence and below-threshold variable counts are disclosed. A repeatable-read snapshot fixes the query time and all queried profile/revision/comparison identities, including missing comparisons. Final publication checks the entire snapshot and exact selected lineage under the existing canonical lock. Later revisions, new profiles/comparisons or changed ancestor selections produce `stale_snapshot` in the view; archived run/report bytes remain unchanged. Historical replay uses the frozen support and snapshot time.

## Persistence, API and user flow

Migration 011 adds source-request receipts, history/baseline datasets, detector runs, indexed PostGIS component projections and frozen profile inputs. Compressed arrays prohibit pickle/object dtype and enforce key/shape/unit/support/mask budgets. Raw, array, manifest, report and calculation hashes plus code/shared-dependency/runtime/policy identities are retained. Staging precedes atomic SQL/calculation/component/outbox publication; retries are idempotent. `regional.event.ready` uses the existing transactional publisher and a separate retained JetStream stream.

Go exposes `/api/v1/event-datasets`, `/event-runs` and `/events` with exact-ID detail routes, typed [OpenAPI](../packages/schemas/events.openapi.json), strict bounds and shared capacity/deadline limits. Detail reads verify report and exact parent object identities. The worker additionally verifies numeric contracts, calculation/SQL/lake agreement, exact binary geometry and source lineage. Maintenance marks damaged inputs/runs unavailable and restores readiness only after exact-byte verification. Catalogs remain indexed metadata views and show status explicitly.

`/events` links fixed baselines, daily source datasets, detection runs, component details and calculation evidence. Maps render native cell footprints or observed profile points. Keyboard-focusable tables expose coverage and changing regional support. SST and profile intensities use separate units; censored/frozen/current/stale states are visible. Empty results and unavailable evidence have distinct wording. SVG annotation text uses a single string to avoid server/browser hydration mismatches.

## Local measured evidence

The [measured snapshot](evidence/phase9-summary.json), captured on 2026-10-03, records real retained source inputs and local API checks. The explicit Arabian Sea pilot is 71–73°E, 11–13°N at native 0.25° resolution: 8×8 cells. The historical daily bundle contains 10,957 days and 120 retained quarterly raw requests, with zero missing pilot cell values. Its fitted baseline supports all 23,424 seasonal cell positions (366×64).

The real 2026-09-01 through 2026-09-30 window contains 30×64 observed values. It yields one persistent 64-cell SST candidate throughout that window, mean anomaly about 1.569 °C and maximum about 2.068 °C. Both boundaries are censored: the report does not establish the full event onset/end or an expert-confirmed marine heatwave. An October 1 request was unavailable at the archive; it was not silently filled or represented as current coverage.

The latest retained 2025-10-01 through 2026-09-30 profile snapshot queries 398 profiles. 11 variable points exceed the declared rank and form ten isolated groups, with zero regional profile candidates. Variable exclusions comprise 358 below-threshold and 427 missing-rank cases, with 0 missing comparisons. An earlier retained snapshot had 342 profiles/eight isolated points; background ingestion produced a distinct later snapshot rather than changing its report. New runs preserve fresh snapshot times and separate immutable identities. Synthetic positive/quiet/missing/race cases are confined to disposable verification databases.


## Verification and limits

```sh
make lint test build test-migrations
make phase9-verify phase9-reliability phase9-smoke
make smoke
make phase2-verify phase3-verify phase4-verify phase5-verify phase6-verify phase7-verify phase8-verify
```

The offline gate independently checks seasonal mean/percentile arithmetic, leap/support/masks, strict equality/duration/observed and unknown gaps, native holes/area, movement/connectivity, isolated versus regional profile rules, exact UTC gaps/dateline and packed NetCDF/missing whole days/safe deterministic arrays. Disposable SQL and real S3 checks exercise atomic rollback/retry, idempotency/outbox, exact replay, missing report/raw/parent withholding and restoration, projection/fingerprint refusal and revision publication races. Production builds, live schemas/queries/HTML and existing local regression suites pass. Desktop/mobile browser checks cover catalog, thermal and profile runs/components, calculation/dataset navigation, visible point/cell distinction, keyboard table regions, page overflow and hydration/error detection.

The API shares eight request slots, two integrity reads and an 8 s deadline. Worker budgets limit cells, daily/profile support, component/report sizes and source requests; oversized work fails instead of silently coarsening. Full operating-region historical coverage needs explicit bounded tiles/runs; the 2° pilot is not basin-wide coverage. Daily detail coverage counts eligible finite source/baseline pairs, so an unsupported baseline cannot establish an observed quiet cell.

These results establish local implementation and reproducibility. They do not establish expert-event agreement, quiet-period false-alert rate, coastal validation, repeated source cadence, rights review, live monitoring/alerts, production operations or scientific event approval. `event_detection_diagnostics` exposes supported diagnostics; `regional_events` remains false. The historical feasibility gate remains fail-closed. Official advisories and deterministic trip decisions are separate subsequent work.
