# Gridded ocean and weather fields

Nautiq acquires, normalizes, retains and serves four regional products: blended SST analysis, wave forecasts, wind/weather forecasts and surface currents. The field catalog, genuine Zarr stores, independent Field Service, point and timed-route sampling, polygon summaries and raster explorer are implemented. Every request pins one immutable release and exposes its provider, initialization cycle, valid times, native resolution, masks and calculation hashes. Scientific production approval, regional events, official advisories and trip verdicts remain separate gates.

## Sources and physical definitions

The versioned [catalog and limits](../packages/source-catalog/fields.json) cover 50–100°E, 10°S–30°N by default. Each adapter validates actual source coordinates and dimensions; the requested box is not substituted for the native cell extent.

| Product ID | Retained variables and source semantics | Primary documentation |
| --- | --- | --- |
| `noaa_oisst` | OISST v2.1 daily blended SST in °C; separate preliminary/final revisions; a UTC-day analysis window with no forecast cycle | [NOAA NCEI OISST](https://www.ncei.noaa.gov/products/optimum-interpolation-sst) |
| `noaa_gfs_wave` | Significant combined wind-wave/swell height, primary wave **mean** period (`PERPW`), primary wave direction **from** true north | [NOAA GFS-Wave](https://www.nco.ncep.noaa.gov/pmb/products/wave/), [GRIB wave parameter definitions](https://www.nco.ncep.noaa.gov/pmb/docs/grib2/grib2_doc/grib2_table4-2-10-0.shtml) |
| `noaa_gfs_weather` | Earth-relative east/north wind at 10 m, air temperature at 2 m, surface pressure; source LAND mask applied to all marine weather variables | [NOAA GFS NOMADS products](https://www.nco.ncep.noaa.gov/pmb/products/gfs/nomads/) |
| `hycom_espc` | FNMOC ESPC-D-V02 east/north surface currents at 0 m; a single initialization run selected from the retained run catalog | [HYCOM ESPC-D-V02](https://www.hycom.org/dataserver/espc-d-v02/global-analysis) |

OISST blends satellite and in-situ observations; it is not independent satellite validation of Argo. NOAA `PERPW` is not labelled peak period. Wind direction is the direction **from** which wind blows; current direction is the direction **toward** which water moves. Both are clockwise from true north and are derived after component interpolation. Wave direction uses circular component interpolation; cancellation has an unavailable direction. HYCOM requests a specific run rather than the mixed-run best-time aggregation. Attribution and the HYCOM as-is limitation are retained in each release.

## Acquisition, normalization and publication

The Python package is `ml/nautiq_ml/fields/`. HTTPS requests are restricted to catalog provider origins, with bounded downloads, redirect refusal, resolved-address checks, transport retries and immutable raw receipts. Receipts preserve request URL, SHA-256, byte count, object key and available transport validators. A failed or incomplete acquisition cannot silently publish a shortened requested forecast horizon. Latest GFS discovery allows for publication latency and falls back to the prior cycle only for missing upstream products. HYCOM chooses a complete single run. Explicit cycle/day commands make source selection reproducible.

NetCDF parsing checks CF units, calendar, fill/scaling, dimension order, depth and coordinates. GRIB parsing checks regular latitude/longitude geometry, parameter and level identity, instantaneous valid time, initialization cycle, units, earth-relative vectors and bitmaps before normalization. Unsupported calendars, projected/curvilinear grids, incompatible vector orientation, duplicate coordinates/times, implausible values, infinite values and excessive dimensions fail explicitly. Arrays normalize to ascending latitude and one continuous regional longitude branch; antimeridian regions are supported up to 180° span. Missing values remain NaN inside Zarr and null with a reason in public JSON. Vector components use a joint support mask.

Zarr v2 arrays use `(1,64,64)` chunks and Zstd compression, with consolidated metadata and separately verified coordinate chunks. The manifest pins every object's size/hash, exact raw inputs, product policy, method versions, source version, code fingerprint, locked dependency/runtime fingerprint and base Git commit. Content-derived release and normalization calculation IDs are deterministic. Immutable objects are staged and read-verified before one SQL transaction publishes the release, calculation and `field.ready` outbox event. Per-product database advisory locks serialize acquisition/publication. The existing leased dispatcher publishes field events to a separate JetStream stream so they cannot block Argo delivery.

Migration 010 adds product inventory, immutable releases, per-product selection and ingestion runs. Selection cannot move backward to an older cycle/day due to late arrival; final SST supersedes preliminary SST for the same day; a shorter replay of the same cycle cannot shrink the selected horizon. Retained releases preserve their original metadata and bytes. `field-maintain` verifies selected raw and normalized artifacts, marks damaged releases unavailable and restores readiness after identical verified bytes return. Offline replay reparses exact retained provider bytes and creates a new release for changed implementation/policy; it never fabricates a new upstream fetch time.

## Sampling and raster semantics

Point sampling uses masked bilinear spatial weights and linear interpolation between valid forecast times. Any missing corner with positive weight makes the sample unavailable; there is no nearest-water substitution or coastal extrapolation. An exact supported native cell does not require zero-weight neighbors. Daily SST is held only over its declared UTC day. Forecast queries outside the retained time window remain outside horizon. Every result lists requested coordinates/time, actual spatial/temporal support, weights, source distance, method and status.

Timed routes require 2–32 explicitly timed waypoints, including return legs and stops. Segments follow shortest great-circle paths. Sampling respects both space and time limits, includes endpoints and retains unsupported samples. Requests over budget fail rather than quietly coarsening. Responses include every sample, cumulative distance, available fraction and sampled extrema. Stale values can remain inspectable with stale status; extrema are sampled evidence, not a guarantee about unsampled conditions or a trip assessment.

Polygon summaries accept a validated GeoJSON Polygon, inspect native cell centers and use cosine-latitude area weights. Masks and outside coverage remain explicit, with total/available cell counts and partial status. Directional means are withheld. Self-intersections and oversized bounding grids fail. Antimeridian polygons must be split explicitly.

Raster tiles are 256×256 RGBA Web Mercator PNGs, sampled from native cells. Outside-domain and masked cells are transparent; supported cells are opaque. Fixed versioned color ranges appear in the explorer legend. A high map zoom does not add native scientific resolution. Tile headers pin the exact release, manifest, forecast cycle, requested valid time and freshness.

## Serving and contracts

The independent read-only `FieldService` exposes typed point, route, polygon and tile RPCs. Each call reloads hash-verified metadata and verifies fetched chunks, preventing stale caches from hiding missing/corrupt objects. Python errors become stable sanitized gRPC failures; Go returns bounded `application/problem+json` responses without provider bodies, SQL or credentials. Field failures leave observation and profile evidence readable.

The [OpenAPI contract](../packages/schemas/fields.openapi.json) describes:

- `GET /api/v1/fields?product_id=...&limit=...`
- `GET /api/v1/fields/{release_id}`
- `GET /api/v1/fields/sample?release_id=...&variable=...&latitude=...&longitude=...&time=...`
- `POST /api/v1/fields/route`
- `POST /api/v1/fields/polygon`
- `GET /api/v1/fields/{release_id}/tiles/{variable}/{z}/{x}/{y}?time=...`

Sampling requests require exact release IDs. Responses carry the durable normalization `calculation_id` and a separate sampling receipt with frozen request `as_of`, method/code hashes and deterministic request/output hashes. The receipt is returned to the caller; personal route coordinates are not persisted as saved state. Catalog queries expose latest acquisition status separately from retained release freshness. Freshness uses provisional product-specific source-age budgets, not download or replay time; these budgets do not establish measured provider cadence.

| Operation | Hard limits |
| --- | --- |
| Acquisition | 64 MiB per raw object, 128 MiB total downloads; 20 s socket timeout, 60 s acquisition deadline, two attempts |
| Normalization | 25 valid times, 2,000 cells per axis, 16 million variable cells; 4,096 objects, 128 MiB normalized output |
| Online reads | 32 MiB compressed-object budget; 64 MiB decompressed chunk cache; four RPC workers, eight active RPCs, 1 MiB messages |
| HTTP/RPC | Eight shared API evidence slots, 8 s HTTP / 6 s RPC deadlines; cooperative 5 s sampling deadline; 32 KiB JSON bodies |
| Route | 32 waypoints, 512 samples, 1,000 km, 96 h; spacing 0.5–5 km, time step 1–30 minutes |
| Polygon | At most 10,000 native cells in the candidate bounding grid |
| Raster | 256×256; zoom 0–12; 300 KiB response ceiling |

`field_sampling` becomes true when the independent runtime is responsive and a compatible selected ready source has unmasked support within its freshness budget. Each request still validates its location, time and release. Runtime health and sample availability do not imply scientific release approval. The SQL approval constraint and all evidence envelopes remain false for this prototype.

## Explorer and local operation

Open [/fields](http://localhost:3000/fields). Product cards show selected releases and acquisition state. A release page separates provider initialization from valid time, source revision, normalized publication time and selection status. Pan/zoom, timeline, variable selection and map clicks load pinned raster tiles; a keyboard-accessible coordinate form samples points. The route editor exposes all times/coordinates and every resulting sample. Changing inputs aborts requests and clears obsolete results. Masks, stale data, integrity failures and unsupported support remain visible. The existing visual system is retained without adding a browser mapping library.

```sh
make fields-setup
make migrate
docker compose up -d --build field-service api ingestion web
make field-refresh                    # Sequential acquisition of all four products
make field-ingest PRODUCT=noaa_gfs_wave CYCLE=2026-10-02T06:00:00Z HOURS=24
make field-ingest PRODUCT=noaa_oisst DAY=2026-10-01
make field-verify FIELD_ID=<returned-release-id>
make field-replay FIELD_ID=<retained-release-id> # No provider download
make field-maintain
make phase8-verify phase8-reliability phase8-smoke
```

Forecast acquisition defaults to a complete 24-hour window at three-hour steps. IDs and example dates above describe this retained local run; fresh installations use current returned IDs. `field-refresh` is explicit. To run hourly polling in a separate resource-limited worker:

```sh
SOURCE_GIT_COMMIT=$(git rev-parse HEAD) docker compose --profile fields-live up -d --build field-ingestion
```

The optional worker is excluded from default startup. It was not left running for this delivery. Polling failures are recorded per product while existing releases remain inspectable subject to freshness and integrity. Production scheduling, scoped identities, TLS, restore drills, measured sustained load and operational monitoring remain deployment work.

## Measured evidence and verification

The [measured snapshot](evidence/phase8-summary.json), captured on 2026-10-02, records all four real provider releases, native extents/resolutions, masks, code/runtime pins, exact point receipts, route/polygon counts and tiles. No synthetic product was inserted into the main database to satisfy this gate. Each full regional product was acquired, retained, then replayed from its raw bytes after correcting period semantics and adding sampling receipts. All four corrected releases passed full raw/chunk/decode verification. Earlier incompatible releases remain retained and unavailable; their immutable artifacts were not rewritten.

| Product | Corrected retained release | Shape (time, latitude, longitude) | Cycle / analysis window |
| --- | --- | --- | --- |
| SST | `2ae88303-5539-56c0-8fe7-779e87ca589c` | 1 × 160 × 200 | Preliminary analysis, 2026-10-01 UTC day; no cycle |
| Waves | `bffa17c3-2a53-53d8-a547-d37bdbddca5c` | 9 × 161 × 200 | 2026-10-02 06:00Z through 2026-10-03 06:00Z |
| Weather | `1c68666b-7777-59fc-82ec-9bfbfea0f87d` | 9 × 161 × 201 | 2026-10-02 06:00Z through 2026-10-03 06:00Z |
| Currents | `ac9a073e-d1d3-50ef-aabf-108a1608bc5b` | 9 × 1001 × 626 | 2026-10-01 12:00Z through 2026-10-02 12:00Z |

The Git field records base checkout `389db134ed5ad1c95d552ab5c0632c6aafcd84e4`; the exact uncommitted implementation is bound separately by its source fingerprint. No commit or push was performed. Existing Argo, snapshot, climatology, expected-mean, interval and profile-anomaly releases were preserved.

The running leased dispatcher published all eight retained `field.ready` outbox events; the independent `FIELDS` JetStream stream contains the matching eight messages. This verifies local broker delivery in addition to SQL outbox publication.

Offline checks use independent interpolation expectations and actual synthetic NetCDF/GRIB encoders to exercise coordinate transforms, packing/fill, masks, cycle/lead rejection, vector/circular arithmetic, time windows, route stops/returns/dateline, polygon budgets and real Zarr integrity. These fixtures verify implementation behavior only. Disposable integration checks cover all migrations, idempotent publication, SQL rollback, outbox uniqueness, late-cycle/preliminary-final ordering, exact RPC pins, corrupt/missing chunks, unavailable status and verified-byte recovery, and clean their database/objects afterward.

Live smoke validates schemas and exact release pins for all four real products, offshore support, masked land refusal, time/domain refusal, outward/return routes, polygon support, independent component-derived wind speed, PNG alpha and identity, frontend proxies, malformed input, rendered HTML and independent existing scientific capabilities. Interactive Chromium checks cover catalog/release rendering, point and route actions, variable/time changes and raster loading at desktop and mobile widths. Validation is local; it does not establish production acceptance.

Final validation passed `make lint`, generated Go/Python byte reproducibility, migration fresh/repeat/checksum/rollback checks, Go race tests, the existing 21 Python tests and frontend tests, all existing offline scientific gates, and the new offline/disposable/live field gates. Platform and existing observation/climatology/mean/interval/profile live smoke checks passed with field sampling enabled. Production field/API/ingestion/web images built successfully. The corrected 390 px mobile page has no document overflow; its automated accessibility check reports zero violations, with one contrast item requiring manual assessment. This is not a full accessibility certification. Invalid route-time editing leaves a readable error and does not add a waypoint or throw a page exception.

One acquisition/replay does not prove repeated source cadence, completeness, local coastal accuracy, redistribution/commercial approval or scientific validity. Current forecasts can age beyond their retained horizon; no live refresh is inferred from replay. The historical Phase 0 readiness gate remains fail-closed. Regional event detection, official warning completeness, reviewed vessel thresholds and favorable-trip logic have not been enabled by field sampling.
