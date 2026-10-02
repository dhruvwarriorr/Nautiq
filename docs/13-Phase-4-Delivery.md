# Phase 4 delivery: historical climatology and profile comparisons

Phase 4 is implemented locally. Nautiq now compares an observed profile with a fixed historical seasonal conditional mean at that profile's own location, observation time and standard depths. It reports signed temperature and salinity differences, training support, explicit pooled fallbacks and missing coverage. Schema 5 preserves existing data and frozen snapshots. Selecting a local reference does **not** grant scientific production approval.

## Run and review

```sh
make setup
make up
make phase4-verify       # Offline harmonic, gridding, leakage and numerical checks
make phase4-reliability  # Disposable DB/S3: races, leases, checksums and rollback
make climatology-build SNAPSHOT_ID=3b606239-35ae-53ae-938d-5c0935385a00
make climatology-verify REFERENCE_ID=dd46a816-fa5b-5d4f-a296-9c2025d10c61
make climatology-select REFERENCE_ID=dd46a816-fa5b-5d4f-a296-9c2025d10c61
make climatology-maintain
make phase4-smoke        # Live contracts, exact differences and rendered pages
```

These IDs refer to retained local volumes. On a fresh installation, acquire/import real Argo inputs, build a verified snapshot at an explicit UTC selection time, and use the returned IDs. Building and selecting a reference are explicit bounded commands. Normalization, replay and lake repair automatically enqueue comparisons for the selected reference; the normalizer drains ten comparison jobs per maintenance cycle. The manual maintenance command drains up to 500 jobs. Changing fitting code or environment requires rebuilding the immutable reference; a worker refuses bundles with another code fingerprint.

Open [historical references](http://localhost:3000/climatology), [the verified reference](http://localhost:3000/climatology/dd46a816-fa5b-5d4f-a296-9c2025d10c61), or [a supported observation](http://localhost:3000/profiles/e3e31b44-3347-54e0-be97-0686e0447bcc). Original-level observations remain separately visible.

## Requirement coverage

| Deliverable | Implementation and proof |
| --- | --- |
| Standard depth grid | Separate immutable Parquet derived from the frozen original-level snapshot; independent temperature/salinity coverage and exact/interpolation/missing reasons. No extrapolation or bridging rejected native levels. |
| Harmonic seasonal climatology | NumPy ridge fit with first/second annual harmonics and geographic terms; coefficients, support masks and residual scales use only training data. UTC season wraps continuously across New Year. |
| Spatial/depth pooling | Ordered 5° cell/depth → basin/depth → basin/depth-band candidates; each eligible pool requires profile/platform/month/year support. Geography and depth must stay inside that pool's observed training ranges. |
| Spread | Profile-weighted training residual RMS with a versioned positive floor; plotted ±1 RMS and explicitly described as uncalibrated variability, not mean confidence. |
| Fallback and refusal | Method group, support counts and fallback reasons retained per depth/variable. Unsupported geography/depth, sparse pools, wide gaps and missing labels return null independently. Invalid or corrupt artifacts fail closed. |
| Regional/depth evaluation | Separate train/tuning/calibration/test reports: MAE, RMSE, bias, profile-weighted MAE, missing/support counts and exploratory profile-bootstrap intervals overall, per basin and all 15 depths. |
| Observed / expected / difference UI | Server-rendered profile overlays and tables show observed standard-depth value, expected mean, signed difference/direction, spread, support, fallback and calculation links. Reference pages expose fitting years, policy and held-out evidence. |
| Durable evidence and recomputation | Content-addressed fit/grid/evaluation/manifest artifacts; frozen fit calculation and revision/reference-pinned comparison calculations. Atomic publication requires current revision, selected reference and an unexpired owned lease under the canonical selection lock. |

Code: `ml/nautiq_ml/climatology/{grid,model,pipeline}.py`, `packages/source-catalog/climatology.json`, `migrations/005_climatology.sql`, `services/api/internal/science/climatology.go`, and the reference/profile components under `apps/web/app`. The scientific runtime RPC still serves no ML model; climatology calculations run offline in the normalizer and the Go API serves their durable results.

## Fixed scientific policy

Method `harmonic-climatology-v1`, grid `argo-standard-grid-v1`:

- Depths: 10, 20, 30, 50, 75, 100, 150, 200, 300, 400, 500, 750, 1000, 1500, 2000 m. Existing TEOS-10 native depth conversion is reused. Interpolation requires adjacent retained native indices and two valid labels for the variable, with a maximum 250 m bracket. Grid values never replace original levels.
- Dataset baseline: **2005–2024**. Actual fitting partition: **2005–2016**; tuning 2017–2019, calibration 2020–2021 and test 2022–2024 stay out of fitted state. This sampled dataset has no 2005 observations. The source snapshot enforces delayed-mode, adjusted, QC1 training labels and one revision/split per stable profile.
- Domain: 0–30° N, 45–100° E. The prototype basin rule uses longitude <80° E for Arabian Sea and ≥80° E for Bay of Bengal. This is a declared coarse partition, **not** a coastline or hydrodynamic basin mask.
- Candidate pools require ≥12 stable profiles, ≥3 platforms, ≥4 UTC calendar months and ≥2 years. Bands are (0,100], (100,500] and (500,2000] m. Missing direct-depth support can fall back to an eligible band; band prediction never extends past its actual trained depths.
- Features: intercept, centered normalized latitude/longitude, first/second annual sine/cosine; depth bands add scaled depth and depth². Ridge penalty 1 leaves the intercept unpenalized. A profile's pooled depth rows have total weight one. Calendar year, platform ID, observation labels and external fields are not reference covariates. UTC elapsed fraction of the observation year supplies seasonal phase, with leap years handled explicitly.
- Training residual RMS uses the same profile weighting. Floors are 0.05 °C and 0.01 practical-salinity units. These floors are engineering policy, not validated uncertainty thresholds. Predictions outside -3–45 °C or 0–42 salinity are unavailable rather than clipped.
- Policy was fixed before the held-out report; no tuning, calibration, automatic refitting or promotion uses those reported labels. Bootstrap uses 200 deterministic profile resamples, seed 42; fewer than three evaluated profiles yields no interval. Resampling does not establish spatial or serial-float independence.

## Dated real-data evidence

Verified locally on **2026-10-02** using the retained real-source snapshot from Phase 3, with no new provider acquisition for fitting:

| Evidence | Value |
| --- | --- |
| Snapshot | `3b606239-35ae-53ae-938d-5c0935385a00` |
| Reference | `dd46a816-fa5b-5d4f-a296-9c2025d10c61` |
| Frozen fit calculation | `345f029f-0891-52e6-97d0-0521960085e0` |
| Train-only fit hash | `13d88e64949e6664fb57a5b31e9ac9681a474862ec5b44b806eed99f6c18b8a9` |
| Bundle SHA-256 | `8041ff6792c1b5034367d36b402178ae35ebaa3b832fb606f038abdfd483f9e7` |
| Standard-grid SHA-256 | `e46ff2ad4bb12b957c5a2b9acd2dd9fbb8c5f4d791cd43f55963f770a94c2311` |
| Evaluation SHA-256 | `870520a98aa9b068cfdb339fdaa3b84ef154be05116061b0ce90544fb4f52dd3` |
| Snapshot profiles / grid rows | 196 / 2,940 |
| Train / tuning / calibration / test profiles | 47 / 49 / 50 / 50 |
| Supported fitted pools | 68: 56 basin/depth and 12 basin/depth-band; **zero eligible cell pools** |
| Current profile comparisons | 474: 292 partial with 7,023 supported variable/depth pairs; 182 unavailable |
| Release approval | false |

Two builds from the same snapshot/policy/code/environment returned identical IDs, manifests and artifact hashes. Independent verification read and hashed the bundle, grid, evaluation and calculation manifest, and checked their stored mirrors/counts.

Held-out test values below describe only **supported pairs**, not the complete domain. Each variable has 750 candidate standard-depth rows (50 profiles ×15); temperature evaluates 499 rows from 41 profiles, salinity 455 rows from 37 profiles.

| Test group | Evaluated rows | Row MAE | Row RMSE | Bias | Profile-weighted MAE |
| --- | ---: | ---: | ---: | ---: | ---: |
| Temperature, overall (°C) | 499 | 1.139 | 1.645 | 0.017 | 1.248 |
| Temperature, Arabian Sea | 228 | 1.394 | 1.924 | -0.328 | 1.604 |
| Temperature, Bay of Bengal | 271 | 0.925 | 1.366 | 0.308 | 0.909 |
| Salinity, overall | 455 | 0.333 | 0.736 | -0.120 | 0.405 |
| Salinity, Arabian Sea | 214 | 0.290 | 0.382 | 0.046 | 0.330 |
| Salinity, Bay of Bengal | 241 | 0.372 | 0.944 | -0.269 | 0.484 |

Exploratory overall profile-bootstrap MAE intervals are 1.008–1.530 °C and 0.231–0.696 salinity units. Temperature has 123 missing observed rows and 128 outside the training envelope; salinity has 210 missing observed rows and 85 outside the envelope. All 15 per-depth tables and each partition's report are retained in the reference API/UI. At 2,000 m the test report evaluates zero rows; metrics are null, not zero performance error.

For the displayed real observation `e3e31b44-3347-54e0-be97-0686e0447bcc`, observed at **2025-10-01T11:10:42Z**, 10 m temperature is 28.813244 °C versus expected mean 27.435743 °C: **+1.377501 °C, warmer**. Salinity is 34.595194 versus 36.432316: **-1.837121, fresher**. These are interpolated observed values and basin/depth fallback means, with 23/21 temperature training profiles/platforms and 21/19 salinity profiles/platforms. Comparison calculation `26e84ed6-752c-51c2-b39d-8726d978ed13` pins the exact observation revision and reference. The sign is a descriptive difference, not a confidence verdict, profile anomaly score, marine heatwave or event assessment.

## Verification and limits

Passed locally:

- Offline frozen numerical reference, repeatable fitting, arbitrary held-out label/location changes leaving fitted state unchanged, UTC seasonal continuity, independent grid masks, no extrapolation/wide-gap/rejected-native bridging, domain/depth/envelope refusal, depth-band fallback, sparse support and residual-scale floors.
- Disposable database with 48 synthetic native profiles: identical repeated fit/artifacts; checksum refusal/recovery, unsupported-selection and input-budget refusal; forced SQL rollback after immutable staging; revision and reference changes **during comparison staging**; stale calculation state; independent bad salinity; expired and stolen leases; SQL observation divergence from canonical Parquet refusal; frozen reference retention. Synthetic inputs are verification-only and are never substituted for the real-data report.
- Live OpenAPI checks, current-revision/reference matching, exact difference arithmetic and direction, support counts, bounded/malformed/unknown queries, original-observation availability, reference/calculation pages and server-rendered profile comparisons.
- Fresh/repeat/legacy/checksum/rollback migrations; existing Argo normalization/transport/recovery and frozen-snapshot gates; 21 Python and three frontend checks, Go race checks, format/vet, Ruff, ESLint/TypeScript, Compose validation and native/production/container builds. All ten runtime dependency probes passed.

API budget is eight shared slots and eight-second request deadlines; inventories accept limits 1–200 (default 50). Fit input hard ceilings are 2,000 profiles and 100,000 original levels, snapshot Parquet 128 MiB, each reference artifact 16 MiB. Selection refuses >2,000 current profiles rather than partially selecting them; scaling beyond this prototype needs a new bounded selection design. Comparison leases last 60 seconds and publication rechecks ownership/time. Errors are typed and sanitized.

`climatology` capability is true only when a selected ready reference has a supported comparison for a current ready revision. Observations remain independently queryable. ML expected-state, anomaly, field, advisory and trip capabilities remain false. Source cadence, representative coastal coverage, licensing review, serial/platform/spatial independence and scientific release acceptance remain outstanding gates. Geographical training rectangles do not prove ocean/coastal topology. Spread has no calibrated coverage claim and cannot authorize operational decisions.

Rendered HTML/HTTP flows were verified; actual browser visual/interaction acceptance was not performed. Existing staged test removals and `.gitignore` changes remain untouched. This implementation was not committed or pushed.
