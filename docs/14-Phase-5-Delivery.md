# Phase 5 delivery: residual expected means and model evidence

Implemented locally on 2026-10-02. The complete path now builds LightGBM residual candidates, compares them with HGBR and climatology, records an exact MLflow registry version, loads a hash-verified explicit release into Python gRPC, and publishes revision-safe profile comparisons through the API and web UI. **Climatology remains the serving mean for both variables.** Neither candidate passes the configured promotion checks, and the historical test block was previously inspected. Implementation completion does not approve a scientific production release.

## Delivery map

| Blueprint deliverable | Implementation and verification |
| --- | --- |
| Shared features | `ml/nautiq_ml/expected_state/features.py`: one feature builder used by training and inference; fixed names/version and domain/finite/depth checks |
| Grouped spatial/temporal splits | Stable profile/depth/revision consistency checks; frozen 2005–2016 train, 2017–2019 tune, 2020–2021 calibration, 2022–2024 test; deterministic platform and spatial complement audits |
| LightGBM residual training | `model.py`: train-only labels and reference, profile weights, two predeclared leaf counts, tuning-only early stopping and selection, deterministic single-thread native trees |
| HGBR comparison | Same features, train rows, weights, reference and evaluation rows; tuning selection across the same leaf counts; no executable pickle artifacts |
| MLflow logging | `tracking.py`: parameters, environment, partition metrics, promotion reasons, exact canonical bundle/manifest/native model artifacts, idempotent run and registered model version |
| Bundle and release manifest | `pipeline.py`, schema 6: immutable content-addressed artifacts, checksums, snapshot/reference/raw inputs, code/runtime fingerprints, explicit selection and rollback-safe publication |
| Python gRPC inference | `serving.py`, generated Python/Go contracts: explicit release match, nullable predictions, batch bounds, native model verification, model explanations and qualified climatology fallback |
| End-to-end evidence | `jobs.py`, schema 7 reference invalidation, Go `/expected-state-releases` and `/profiles/{id}/expected-state`, web `/models` and profile panels, offline/reliability/live gates |

## Run and inspect

```sh
make expected-setup       # Locked scientific and MLflow dependencies
make phase5-verify        # Offline features, leakage, native models and fallback
make phase5-reliability   # Disposable SQL/S3/MLflow/gRPC lifecycle checks
make expected-build REFERENCE_ID=dd46a816-fa5b-5d4f-a296-9c2025d10c61
make expected-verify MODEL_ID=<returned-release-id>
make expected-log MODEL_ID=<returned-release-id>    # Retry tracking independently
make expected-select MODEL_ID=<returned-release-id>
# Set ML_RELEASE_ID=<same exact release ID> in .env, then:
docker compose up -d --no-deps ml-inference
make expected-maintain
make phase5-smoke
```

Build/select commands require explicit IDs. Fresh installations create their own verified historical snapshot/reference first; these IDs refer to retained local data. An unset `ML_RELEASE_ID` leaves scientific inference unavailable while observations remain available. No latest-version lookup, registry alias or automatic promotion chooses the serving artifact. A selection/runtime mismatch returns a structured failure and defers workers until the exact pinned runtime is restarted.

- Model inventory: http://localhost:3000/models
- Selected release: http://localhost:3000/models/6652e49f-b1a4-578c-a929-7eb5bb05db6a
- Real profile: http://localhost:3000/profiles/e3e31b44-3347-54e0-be97-0686e0447bcc
- MLflow: http://localhost:5001 (loopback; `MLFLOW_PORT` is configurable)

MLflow uses a persistent SQLite backend and proxied artifacts on its own named volume. One tracking server worker fits the local 1 GiB budget. Experiment logging occurs after atomic scientific publication; a tracking outage does not invalidate a durable release and can be retried explicitly. The registry stores the exact native JSON bundle and version metadata. Serving verifies the S3 bundle, manifest, report, native model hashes, feature order, embedded reference, expected/climatology code and locked dependency/runtime compatibility and recomputed promotion decision.

## Features and evaluation policy

`packages/source-catalog/expected-state.json` fixes eight numeric reference features: latitude, longitude, depth in metres, first/second annual sine/cosine harmonics, and broad basin ID. There are no observed temperature/salinity inputs, calendar-year trend, platform/profile ID, present satellite SST or marine weather inputs. Bathymetry and coast distance are omitted because their static sources are not validated; coastal-distance evaluation is explicitly unavailable. Temperature is °C and practical salinity uses PSS-78.

Residual targets are observed labels minus the train-only frozen climatology conditional mean. Predictions add a candidate residual to that mean. Rows missing a variable or supported reference are excluded independently and counted. Every profile has equal total training weight; all its depths remain in the same temporal partition. LightGBM uses up to 80 rounds, a 10-round tuning patience and leaf counts 7/15. HGBR uses 80 rounds with internal random early stopping disabled. Calibration and test labels are evaluated without fitting or selecting trees. The implementation does not fit quantiles, infer a median from a mean, or advertise calibrated intervals.

All three methods are compared on identical eligible rows across four partitions. Reports contain row MAE, RMSE, median absolute error, signed bias, profile-weighted MAE and seeded profile-bootstrap 95% MAE intervals, with region, depth-band, season and all 15 individual-depth groups. Empty metrics are null with zero counts. A profile bootstrap does not prove serial-float independence.

Two spatial folds use stable 5° cells and remove a 1° latitude/longitude buffer from each complement. Two platform folds group every profile of a platform together. Each audit fully refits climatology support and coefficients on complement training profiles, then residual candidates on complement training labels with complement tuning selection. It scores held groups with climatology, HGBR and LightGBM. These diagnostic folds are distinct from the chronological test; insufficient complement/held support remains visible and is not an audit approval.

## Measured real-data release

The Nautiq namespace correction rebuilt the expected parent under a new code fingerprint. The earlier release remains immutable; the pins below describe the active renamed parent used by the predictive interval release.

The frozen source snapshot contains 196 delayed-mode historical profiles and 61,281 original levels, with 47/49/50/50 profiles in train/tune/calibration/test. The shared standard grid contains 2,940 rows. The reference remains `dd46a816-fa5b-5d4f-a296-9c2025d10c61`; original levels and its artifact hashes are unchanged.

| Pin | Value |
| --- | --- |
| Model release | `6652e49f-b1a4-578c-a929-7eb5bb05db6a` |
| Fit calculation | `50f58c0d-d850-593b-8668-ca9163519418` |
| Bundle SHA-256 | `80d90921ad2e0b626538b27d6d6e5b6129b0053ea247d569640578bb239ac0f9` |
| Report SHA-256 | `375ec6528b9e01d4b8f2e90e04bb31590423c0b0c1716daf955b46efcb649a39` |
| Implementation fingerprint | `ffcdf9b399fea5759e257723c0540fa51ae02df92226bbc97eba11cf055980a1` |
| MLflow registry | `nautiq-expected-mean`, exact version `1` |
| MLflow run | `466000ec092a4d5b82132d7792d4243b` |

The recorded Git base is `cd5434c59e275ac29f2c6acc0687f741777788af`; the pending implementation is identified by its code fingerprint. Two complete builds produced identical release IDs, checksums and registry/run metadata. The live gate also downloaded the MLflow bundle and matched its bytes to the S3 bundle checksum.

Diagnostic 2022–2024 test results on common supported rows:

| Variable / method | Profiles / rows | Profile MAE | Row MAE | RMSE | Bias |
| --- | --- | --- | --- | --- | --- |
| Temperature / climatology | 41 / 499 | 1.247973 | 1.139182 | 1.644798 | +0.017379 |
| Temperature / LightGBM | 41 / 499 | 1.231737 | 1.141481 | 1.613243 | +0.093751 |
| Temperature / HGBR | 41 / 499 | 1.165042 | 1.100422 | 1.537606 | +0.037723 |
| Salinity / climatology | 37 / 455 | 0.404995 | 0.333296 | 0.735520 | −0.120457 |
| Salinity / LightGBM | 37 / 455 | 0.397435 | 0.326634 | 0.736637 | −0.140580 |
| Salinity / HGBR | 37 / 455 | 0.385473 | 0.320002 | 0.720787 | −0.117118 |

LightGBM uses 15 leaves and tuning-selected 20 rounds for temperature / 14 for salinity. HGBR performs better on this sample. LightGBM's profile MAE improvements are only 1.3% and 1.9%, below the provisional 5% material-improvement check. Temperature regresses beyond the provisional 5% subgroup limit at 100/500/1500 m; salinity at 1000/1500 m, and salinity also fails the 0.1 absolute-bias check. Bias is observed minus predicted.

Spatial fold 0 has 102 complement profiles, 61 held profiles, and 167 temperature / 140 salinity supported held rows across 13 held profiles. Temperature profile MAE is 2.087093 / 1.940010 / 1.932302 for climatology / HGBR / LightGBM; salinity is 0.357034 / 0.289838 / 0.300638. Spatial fold 1 (41 complement / 135 held) and both platform folds (98 / 98 each) lack sufficient eligible complement support to fit both required partitions. Geographic buffers account for profiles belonging to neither spatial complement nor held set. These sparse audits cannot establish acceptable independence or representative coverage.

**Promotion is refused.** Thresholds are provisional and unreviewed; the test block was already inspected during earlier work; independence and source/coverage approvals are false. A future promotion needs reviewed criteria and genuinely untouched data. This delivery retains both fitted candidates for diagnostics while selecting climatology as the active serving mean. Registry registration, successful RPC and a `ready` bundle indicate implementation/artifact readiness only.

## Profile evidence and failure behavior

At the refreshed evidence capture, all 525 current ready profiles have completed comparison jobs: 329 partial supported comparisons, 196 unavailable comparisons and 7,884 supported observed variable/depth pairs. Unavailable values keep original observations independently readable. Candidate coverage uses the actual variable-specific ML training envelope and physical output limits in addition to the historical reference's support rules.

At 10 m in profile `e3e31b44-3347-54e0-be97-0686e0447bcc`, observed temperature is 28.813244°C, climatology is 27.435743°C, and the diagnostic candidate is 27.759734°C (residual +0.323991°C). The serving difference remains +1.377501°C, labelled warmer. Salinity is 34.595194 observed, 36.432316 climatology and 36.555809 diagnostic candidate (residual +0.123493); its serving difference remains −1.837121, labelled fresher. Applied ML correction is zero because promotion failed. The pinned comparison calculation is `c2c77faf-bb66-5abc-b581-c9ddcd960d01`.

Native TreeSHAP contributions plus model bias sum to the candidate residual. The UI shows the three largest contributions and explicitly explains that all eight plus bias reconstruct it. Explanations describe model behavior, not oceanographic causation. No anomaly verdict or calibrated confidence is inferred from signed differences.

Workers verify raw and canonical object hashes and SQL/original-level agreement, then use bounded typed RPC. Immutable output staging precedes SQL publication. Publication checks the lease token and expiry, current ready revision, selected model and matching selected historical reference under the existing canonical-selection lock. A profile revision, model switch or historical-reference switch stales old live evidence; matching retained comparisons can be restored on reselection while frozen fits and snapshots remain frozen. Runtime/object failures retry with bounded backoff; invalid policy/projection work is quarantined. A corrupt or incompatible bundle cannot be selected or loaded.

Schema 6 adds releases, tracking, selection, leased jobs and comparisons. Schema 7 adds atomic invalidation/restoration on a climatology-reference switch. Both are ordered checksum-verified migrations on retained volumes; no reset or edit of an applied migration is required.

Bounds: 2,000 profiles / 32,000 grid rows per fit, 32 MiB per model/report artifact, 32 points and 1 MiB per RPC, 16 concurrent RPCs / four runtime workers, three-second worker RPC timeout, 60-second leased jobs, and at most 2,000 jobs per manual maintenance call (default 500). Evidence HTTP requests retain eight slots and eight-second deadlines; list limits are 1–200. Capability probing has a one-second deadline and fails closed during runtime cold loading or outages. The model container has 2 GiB RAM, one CPU and read-only filesystem with bounded writable temporary storage.

## Verification and limits

Passed locally: lint/vet/TypeScript/Compose validation; production Go/Next.js builds; Go race tests, 21 Python and three frontend tests retained locally; fresh/legacy/checksum/rollback migration checks; regenerated Go/Python protobuf files reproduced byte for byte; offline and disposable reliability gates for the observation, reproducibility, climatology and residual-model slices; live API/raw/Parquet/reference/model gates and platform smoke. Residual-model checks cover leakage, deterministic fits, shared features, registry idempotence, bundle corruption, publication rollback, real typed gRPC validation, fallback/additivity, revision/model/reference publication races, expired/stolen leases and runtime deferral. The live gate validates the new OpenAPI schemas, exact MLflow artifact bytes, matching profile calculations, arithmetic, bounds and HTTP-rendered model/profile pages. This is rendered-HTML verification; interactive visual/browser acceptance and production deployment were not performed.

`expected_state` is true only when the exact selected model/checksum is loaded, matches the selected historical reference and has supported current comparison evidence. `ml_residual` remains false because promotion failed. Observations/climatology remain true; anomaly, field, advisory and trip capabilities remain false. This expected-mean endpoint does not supply intervals. The separately pinned diagnostic interval workflow is documented in [the uncertainty delivery](15-Phase-6-Delivery.md); qualified coverage, coastal topological support, representative source coverage, licensing/cadence approval and scientific production acceptance remain unestablished. Compact dated measurements are in `docs/evidence/phase5-summary.json`.

Native prediction/contribution behavior follows the [LightGBM Booster API](https://lightgbm.readthedocs.io/en/latest/pythonapi/lightgbm.Booster.html); local tracking and registry design follow the [MLflow tracking architecture](https://mlflow.org/docs/latest/self-hosting/architecture/tracking-server/) and [registry workflow](https://www.mlflow.org/docs/latest/ml/model-registry/workflow/).
