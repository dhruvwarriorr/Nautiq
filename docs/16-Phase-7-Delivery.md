# Profile anomaly implementation and evidence

Nautiq now builds, tracks, selects and serves a fixed-reference profile anomaly diagnostic. Each supported profile is explained by signed depth residuals, integrated magnitude, correlated distance, PCA modes and reconstruction error. Climatology Z-scores and Isolation Forest remain separate comparison baselines. The implementation is complete for the declared complete-case prototype. Scientific anomaly approval, event labels and sparse functional inference remain unavailable.

## Residuals and coverage

The [frozen policy](../packages/source-catalog/anomaly.json) uses eleven standard depths from 10 to 500 m. Observations retain the parent grid's no-extrapolation, adjacent native-level and maximum-gap rules. Temperature and salinity are independent: a missing salinity layer does not prevent a supported temperature comparison. Every layer carries the observed value, expected conditional mean, signed residual, normalization scale, floor flag, coverage mask and unavailable reason. Missing layers receive no numeric imputation. An incomplete variable vector retains its depth evidence but has no aggregate score or percentile. The reference and quantile training envelopes still apply.

Normalization is `(observed - expected_mean) / max((rearranged_q90 - rearranged_q10)/2, floor)`. Quantiles come from the exact uncertainty parent and were fitted on training data with tuning-selected parameters. The floors are exploratory 0.05°C and 0.01 PSS-78. Half-interdecile width describes predictive variation in physical units; it is not automatically Gaussian sigma, instrument error or confidence in a fitted mean. The q50 median does not replace the expected conditional mean. Later conformal corrections are excluded from covariance, basis fitting and normalization so their calibration labels do not leak into those fits. The parent's calibrated intervals remain independently inspectable.

The scoring domain is the entire fixed 10–500 m vector. Normalized trapezoidal integration weights account for unequal depth spacing. No raw sum is compared across different observed coverage. Fitting and serving reject invalid grids, duplicated depths, mixed profile metadata, nonfinite locations/values and observations outside declared physical bounds.

## Magnitude, correlated distance and structure

[Scientific model code](../ml/nautiq_ml/anomaly/model.py) centers standardized residuals using complete training profiles. It exposes depth-weighted squared magnitude and Ledoit–Wolf shrinkage Mahalanobis squared distance. At least 20 complete training profiles are required. Singular or ill-conditioned covariance, or a degenerate retained PCA mode, returns an unsupported variable rather than fabricated scores. The condition limit is frozen at 10⁸. Signed per-depth covariance terms can be negative because depths interact; their sum is the nonnegative correlated distance. Positive integrated magnitude terms identify the largest contributing depth and the 10–100 m / 100–500 m bands. Signed departures retain warm/cool and salty/fresh direction separately from score magnitude.

The structural lens is a **weighted discrete FPCA prototype**, implemented with full-SVD PCA on the weighted standardized grid. It is not a validated smoothing or sparse functional-data model. Three components are fixed before test inspection, with no test-based component selection. The release stores basis loadings, eigenvalues, explained variance and training center. Each profile exposes signed component coefficients, score-space distance, per-component distance contributions, dominant component, reconstructed standardized curve and depth errors. Weighted reconstruction error is a separate historical lens. For reproducibility, the largest absolute component loading is oriented positive. Component numbers do not automatically mean a shallow thermocline or other oceanographic phenomenon; those labels require reviewed loadings and scientific evidence.

Isolation Forest fits only training vectors, using 64 frozen-seed trees and at most 256 samples per tree. Safe JSON tree nodes reproduce the fitted library's anomaly score, including float32 traversal and leaf path-length correction. Executable pickle is absent. The Z-score baseline uses the exact climatological mean and its disclosed training residual RMS scale. Both use the same complete variable/depth support and remain comparison-only lenses, without driving primary scores or alerts.

## Historical ranks and diagnostics

Fit uses 2005–2016; tuning is 2017–2019; the percentile reference is 2020–2021; diagnostic test is 2022–2024. All depths of a stable profile stay together and split/identity leakage is rejected. Covariance, PCA, centering and forest never use calibration or test labels. Every lens gets its own frozen empirical comparison distribution from separate calibration profiles. Region → global is the predeclared hierarchy; at least 20 complete calibration profiles are required in the used group. Variable, depth grid, coverage policy and parent domain match. Sparse groups disclose fallback, distinct profile count and resolution `100/n` percentage points. Insufficient global support permits raw scores with null percentiles.

A percentile is `100 × count(reference_score <= new_score) / n`, with upper-inclusive ties. It is a descriptive historical rank, not a conformal probability, event probability or reviewed false-alert threshold. Calibration partition medians use their own reference and are explicitly in-sample diagnostics. No automatic typical/unusual category is emitted.

The benchmark report compares all six lenses on every partition, including complete/excluded counts and ranked support. Five predeclared profile-bootstrap seeds refit covariance/PCA using training only and report Spearman rank agreement on tuning profiles. A fixed 10–100 m addition of 1°C or 0.2 PSS-78 reports sensitivity on the diagnostic test. This does not establish event recall. Expert-reviewed event recall, quiet-period false-alert rates, new untouched test and independent spatial/platform complement audits remain explicit scientific promotion requirements, not invented measurements. The already inspected historical test cannot grant untouched approval. Review flags and SQL release approval are constrained false. Parent uncertainty is also unqualified.

## Releases, jobs and serving

Migration 009 adds immutable anomaly releases, tracking, singleton selection, leased jobs and revision-specific comparisons. The release pins uncertainty, expected mean, climatology, snapshot, policies, exact parent/grid checksums, code fingerprint and locked runtime. Scientific artifacts are content-addressed JSON and hash-verified against immutable lake objects, SQL mirrors and parent lineage. Repeated builds must produce identical release IDs and hashes. MLflow logs the exact bundle and a separate timing artifact; registry versions never silently choose a serving release. Historical fit/snapshot evidence remains frozen.

Selection requires all three matching selected parents. The runtime requires exact `ANOMALY_RELEASE_ID`, `UNCERTAINTY_RELEASE_ID` and `ML_RELEASE_ID` configuration. Each ancestor selection change stales current profile calculations; returning to matching parents restores only current-revision cached comparisons. Revised source profiles queue new work and stale old live evidence. Workers verify raw/canonical lake checksums and SQL projections, stage immutable calculations, then check revision, selected parents/release, lease ownership and expiry under the shared selection lock before atomic SQL publication. Outages defer retry; invalid contracts quarantine work. Late work cannot publish after revisions, model/parent switches or lease loss.

The typed `AnomalyService.Infer` request is one eleven-depth profile with independently optional observations. It refuses wrong pins, grids and invalid numbers. The bounded canonical response contains scientific primitives defined in [OpenAPI](../packages/schemas/anomaly.openapi.json); workers validate depth/observation identity, nonfinite values, coverage, score sums, component support and rank bounds. Budgets are 2,000 fitting/current profiles, 32,000 grid rows, 48 MiB per fit artifact, 1 MiB RPC messages, 256 KiB result JSON, three-second worker RPC deadlines and sixty-second leases. Runtime responsiveness and scientific availability remain separate.

Public evidence routes are:

- `GET /api/v1/anomaly-releases?limit=50`
- `GET /api/v1/anomaly-releases/selected`
- `GET /api/v1/anomaly-releases/{id}`
- `GET /api/v1/profiles/{id}/anomaly`

The [/anomalies explorer](http://localhost:3000/anomalies), release detail and profile panel expose exact lineage, depth tables, signed residual/reconstruction figures, basis loading figures, independent score/percentile lenses, regional fallback, stability and unavailable support. The profile panel guards the displayed revision. All figures render on the server, carry accessible descriptions and retain readable numeric tables. No added browser model library is required. `profile_anomaly_diagnostics` requires an exact loaded/selected bundle and supported current comparisons with matching parents; `profile_anomaly` remains false because qualified anomaly verdicts lack scientific approval.

## Measured local evidence and validation

The [evidence snapshot](evidence/phase7-summary.json) contains the selected content pins, fitting counts, ranks, metrics, timing, current operational counts, capability report and validation status. The frozen 196-profile snapshot and existing parents are retained. Complete training profiles number 34 for temperature and 31 for salinity; separate calibration profiles number 28 and 21; diagnostic test profiles number 34 and 31. Both regional reference groups are below the 20-profile minimum, so historical ranks use disclosed global fallback. Their resolution is approximately 3.571 and 4.762 percentage points. Covariance condition numbers are approximately 42.98 and 38.54. The three retained modes explain about 93.87% and 90.47% of weighted training variation. These counts and descriptive metrics do not establish scientific validity.

The selected local release is `41180c9a-3184-571e-af59-958bec477e1b` with bundle SHA-256 `c6f83d0680961a83fbb1649fd0bdf019d738925fc9bef44db3f2ee55a628efaa` and fit calculation `2ed3519d-6ee9-50fc-8d18-d655185296ef`. Its registry receipt is `nautiq-profile-anomaly` version 3, run `84d9c1864b174c969831d68e5fac5eaa`. Two final builds matched the same release and artifact hashes. The Git commit field identifies the base checkout; the uncommitted implementation is additionally bound by its current code fingerprint. Existing uncertainty, mean, climatology and snapshot parents retain their immutable identities.

At capture, all 525 current profiles have completed comparison jobs: 241 support both variables, 27 support one variable and 257 have unavailable aggregate evidence. These represent 509 supported variable vectors and 525 current calculations, including explicit unavailable results. The frozen snapshot remains 196 profiles / 61,281 original levels. The diagnostic profile capability is true, while scientifically qualified anomaly and calibrated-uncertainty capabilities remain false.

The five training-bootstrap tuning rank correlations range from approximately 0.953–0.982 (temperature) and 0.886–0.975 (salinity) for correlated distance. PCA score-distance and reconstruction ranks are less stable in some resamples, as the full report shows. There is no reviewed stability pass threshold and no promotion claim. Native score timing excludes parent inference, RPC, network and storage; it is not end-to-end service latency.

Run `make phase7-verify phase7-reliability phase7-smoke`. Offline verification checks deterministic fitting, train/calibration/test separation, safe forest parity, weighted/component arithmetic, missing-variable handling, sparse percentile references, fixed-grid budgets and leakage refusal. The integration test creates a disposable database and uniquely scoped lake objects, then cleans both. It exercises exact immutable releases, tracking idempotency, publication rollback, corruption refusal, RPC budgets and pins, revision/selection races, all ancestor staleness/restoration, lease expiry and outage deferral. Live checks validate response schemas, exact MLflow artifact hash, current revision calculations, score/rank arithmetic, capabilities and rendered HTML. Standard lint, production Docker builds, migrations and existing scientific regressions are recorded in the evidence snapshot. Interactive browser visual acceptance was not performed; HTML acceptance does not establish scientific approval.

Local workflow:

```sh
make uncertainty-setup
make migrate
make anomaly-build INTERVAL_ID=<selected-uncertainty-release-id>
make anomaly-verify ANOMALY_ID=<profile-release-id>
make anomaly-log ANOMALY_ID=<profile-release-id>
make anomaly-benchmark ANOMALY_ID=<profile-release-id>
make anomaly-select ANOMALY_ID=<profile-release-id>
# Set ANOMALY_RELEASE_ID in .env and retain matching interval/mean parent pins.
docker compose up -d --no-deps ml-inference
make anomaly-maintain
```

The implementation follows the primary library contracts for [Ledoit–Wolf covariance](https://scikit-learn.org/1.8/modules/generated/sklearn.covariance.LedoitWolf.html), [PCA](https://scikit-learn.org/1.8/modules/generated/sklearn.decomposition.PCA.html) and [Isolation Forest](https://scikit-learn.org/1.8/modules/generated/sklearn.ensemble.IsolationForest.html), with the complete-case weighting, safe export and interpretation restrictions declared above.
