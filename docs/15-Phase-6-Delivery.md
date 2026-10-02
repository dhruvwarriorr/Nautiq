# Predictive intervals, calibration and coverage evidence

Nautiq now benchmarks LightGBM q10/q50/q90 against CatBoost MultiQuantile, publishes native models in immutable releases, computes profile-based Mondrian conformal intervals, serves typed inference and revision-matched profile comparisons, and monitors fixed-reference coverage. These are diagnostic capabilities. Scientific production approval and qualified coverage remain disabled until empirical and review requirements are met.

## Model fitting and selection

The uncertainty release pins an exact expected-mean release, climatology release, training snapshot, grid checksum, feature schema, policy, code fingerprint and dependency environment. Both families learn residual quantiles over the frozen climatological mean. The q50 estimate is a predictive median; it is separate from the conditional mean inherited from the expected-state release. Bathymetry and coast distance remain omitted until source validation.

All depths and revisions of a stable profile stay together. Training uses 2005–2016; tuning uses 2017–2019; calibration uses 2020–2021; the already inspected 2022–2024 block is diagnostic test evidence. Train-only profile weights prevent densely sampled profiles dominating losses. LightGBM tunes leaves 7/15 with separate q10/q50/q90 trees. CatBoost tunes depths 3/4 using one MultiQuantile model per variable. Both use seed 42, bounded rounds and tune-only early stopping. Model/configuration selection never uses calibration or test labels.

Family choice first admits candidates within the frozen 1% tolerance of minimum tuning profile pinball, then compares closeness to raw 80% tuning coverage, crossings and the existing LightGBM operational path. Measured native prediction p95 must fit the 100 ms selection budget. Reported benchmark pinball uses reordered quantiles; fitting and configuration selection use the native tuning quantile loss. Benchmark timing lives outside content-addressed scientific identity. Both family benchmarks remain visible regardless of selection: pinball, raw crossings, raw row coverage, calibrated row coverage, profile-group coverage with descriptive Wilson ranges, full-profile coverage diagnostic, interval width, fallback counts and unavailable counts. Reports include region, depth band, region × depth and season groups.

Native LightGBM text and CatBoost JSON have checksums. CatBoost export removes only volatile model GUID and finish-time metadata; native trees and parameters remain intact. Loading uses the native libraries and never executable pickle. Repeated fitting must produce identical canonical scientific bundles.

## Calibration unit, hierarchy and interpretation

The declared unit is `stable_profile_maximum_within_group`. Each distinct calibration profile contributes the maximum nonnegative CQR score `max(q10 - observed, observed - q90, 0)` across supported depths in the named group. Correction is the exact finite order statistic at `ceil((n + 1) × 0.8)`. At least 20 distinct profiles and a finite rank are required. Depth rows are not counted as independent calibration samples.

The immutable fallback hierarchy is region × depth → region → depth → global. Selection depends on calibration counts and rank, not test outcomes. Every prediction records requested/used groups, profile count, rank, correction and skipped groups. Sparse or unsupported locations receive nullable bounds with an explicit reason. Models respect their actual training latitude/longitude/depth envelope and the parent reference’s support checks.

Raw quantiles are reordered before calibration; raw crossings remain reported. Bounds are q10 minus correction and q90 plus correction, without clipping. They describe natural predictive variability, not instrument error or uncertainty in a fitted mean. The nominal target concerns a profile within a group. Hierarchical fallback does not establish conditional or full-profile joint coverage, and oceanographic spatial dependence limits exchangeability. Wilson ranges are descriptive under an independence assumption, not a spatial-dependence correction.

Overall and adequately sampled subgroups must meet frozen empirical coverage and width criteria. Qualification also requires a reviewed gate ID, new untouched test, exchangeability approval, independence audit approval and source/coverage approval. These review flags remain false. The original historical test has been examined during preceding work, so the application does not describe it as untouched.

## Independent audits and monitoring

Spatial buffered and platform-held folds refit climatology, quantiles and calibration entirely on the complement. Held profiles do not enter any fit or calibration score. Sparse complements retain unavailable outputs. Audit reports expose held/complement counts and their independently fitted reference hashes.

Monitoring checks a bounded 90-day post-test window of current revisions. Only verified delayed-mode adjusted QC1 observations enter trusted monitoring labels; this does not change the frozen snapshot. Every trusted miss and suspect remains in reported fixed-reference coverage. Suspect profile IDs are recorded for exclusion from a future adaptive candidate window. Automatic recalibration, retraining and anomaly verdicts are absent. A new adaptive candidate would require separate reviewed code/policy/version and publication.

Monitoring reports include supported row and profile-group coverage, descriptive confidence ranges, widths, raw crossings, pending comparisons, untrusted labels and unmodeled rows. Insufficient or missing coverage cannot report on-target status. Reports have immutable calculation evidence and are stale after a parent/revision change or after three minutes without refresh.

## Persistence, inference and application

Migration 008 adds uncertainty releases, tracking, explicit selection, leased jobs, profile comparisons and monitoring health. Historical frozen calculations stay retained. Parent selection changes stale current interval comparisons and monitoring; returning to matching parent selections restores revision-matched cached comparisons. Publications check current revision, both parent selections, exact selected interval release, lease token and lease expiration under the shared scientific selection lock. Source raw/canonical hashes and SQL projections are verified before comparison. RPC outages defer retry; invalid contracts are quarantined.

`UNCERTAINTY_RELEASE_ID` pins the exact inference release; `ML_RELEASE_ID` must equal its expected parent. Native models load once. The typed service bounds requests to 32 points and 1 MiB, refuses wrong IDs and invalid/nonfinite locations, and supplies explicit nulls for unsupported estimates. Conditional means remain independently available when interval calibration is missing.

Public routes:

- `GET /api/v1/uncertainty-releases?limit=50`
- `GET /api/v1/uncertainty-releases/selected`
- `GET /api/v1/uncertainty-releases/{id}`
- `GET /api/v1/uncertainty-releases/{id}/coverage`
- `GET /api/v1/profiles/{id}/uncertainty`

The [OpenAPI contract](../packages/schemas/uncertainty.openapi.json), [/uncertainty](http://localhost:3000/uncertainty) release pages and profile interval panels expose mean, median, raw quantiles, calibrated bounds, widths, observed containment, fallback and calibration support. Profile evidence must match the displayed revision. `predictive_intervals` means verified diagnostic implementation with current supported evidence; `calibrated_uncertainty` additionally requires qualified coverage. Anomaly, field, official advisory and trip capabilities retain their separate gates.

## Nautiq rename and preserved history

Branding, document filenames/links, npm/Python distribution names, Python packages, Go modules/imports, protobuf namespaces/generated bindings, Docker project/services/volumes, default database/login names and the active S3 bucket now use Nautiq. The local database and persistent volumes were copied without resetting data, and raw/storage objects were checked byte-for-byte. Original volumes/bucket remain backup archives. Historical scientific blobs, calculation hashes, source receipts, migration checksums and existing registry records retain their immutable provenance. Renamed code produces a new expected-state release rather than rewriting the earlier bundle.

## Measured local release

The selected interval release is `f8655167-eecc-5132-8980-9487d1cf5852`, pinning expected parent `6652e49f-b1a4-578c-a929-7eb5bb05db6a` and unchanged climatology `dd46a816-fa5b-5d4f-a296-9c2025d10c61`. Bundle SHA-256 is `2f2487ec7d328675eebee3c8dbee1f1f3cabd8ffb1e0cd7fb8cf45689fa00bbb`. Two complete builds produced identical scientific releases and tracking receipts. The uncertainty registry is `nautiq-predictive-intervals`, version 2, run `d11163e96ebb4b0586c09bb2324ba8e7`.

Both variables select LightGBM from tuning evidence. On the diagnostic test, temperature profile-group coverage is 83.04% across 41 profiles, with mean profile-weighted width 5.50 °C; salinity coverage is 69.61% across 37 profiles, with width 0.992 PSS-78. CatBoost gives 81.25% and 69.61%, with widths 5.35 °C and 0.987 PSS-78. Selected salinity overall coverage and several adequately sampled groups fail the frozen criteria. Qualified uncertainty therefore remains disabled, independently of the unapproved review gates.

There are 35 temperature and 23 salinity supported calibration profiles in the global pool, with exact ranks 29 and 20. Fine region/depth pools are sparse, so all test interval rows use disclosed hierarchical fallback. Eight native models retain both family comparisons; six LightGBM models serve the selected variables. Measured selected native prediction p95 is approximately 0.107 ms for temperature and 0.082 ms for salinity on a 15-point batch in the local container. These timings exclude RPC, feature construction and network overhead.

At the evidence capture, 525 current profiles have completed interval jobs: 400 partial comparisons and 125 unavailable comparisons, containing 11,030 supported variable/depth intervals. Unsupported outputs remain null. The 90-day trusted monitoring window has zero eligible profiles, so it reports insufficient trusted support rather than on-target coverage. The frozen 196-profile/61,281-level snapshot and 2,940-row training grid remain unchanged.

## Verification and measured local evidence

Current measured pins, benchmarks, coverage and capability snapshots are in [the compact evidence report](evidence/phase6-summary.json). Local checks passed and include deterministic fitting, partition leakage guards, finite ranks/profile maxima, sparse fallback, null support, immutable monitoring, native-model round trips, typed RPC contracts, checksum refusal, SQL rollback, registry idempotency, revision/selection races, lease loss, outage deferral, schema upgrades and current API/UI responses. The local API and HTML smoke checks passed. No interactive visual/browser acceptance was performed because no browser was available. These establish implementation behavior; they do not provide a new untouched scientific test or reviewer approval.

Run `make phase6-verify phase6-reliability phase6-smoke` after `make uncertainty-setup`, `make migrate` and a local stack build. Explicit commands `uncertainty-build`, `uncertainty-verify`, `uncertainty-log`, `uncertainty-benchmark`, `uncertainty-select`, `uncertainty-maintain` and `uncertainty-monitor` keep artifact creation and selection reviewable. Selection requires the matching parent releases; restart inference with the exact pins after activation.

The implementation follows the native [CatBoost MultiQuantile objective](https://catboost.ai/docs/en/concepts/loss-functions-regression), [CatBoost JSON export](https://catboost.ai/docs/en/concepts/python-reference_catboostregressor_save_model), [LightGBM quantile parameters](https://lightgbm.readthedocs.io/en/latest/Parameters.html) and the [CQR method](https://arxiv.org/abs/1905.03222), with the explicitly declared profile aggregation and fallback policy above.
