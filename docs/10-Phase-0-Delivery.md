# Phase 0 delivery and measured feasibility

Tooling and a real-source scientific pilot were executed locally on 2026-10-01. **Overall readiness is partial**: the observation/science prototype is executable; public trip and scientific release gates remain blocked. This document separates delivered tooling from evidence and approvals. The current platform is described in `07-Phase-1-Delivery.md`.

## Delivered

- Versioned source catalog with exact sample endpoints, attribution, access/license limits and unverified approvals.
- Bounded allowlisted HTTPS downloads with transport retries, redirect denial, size/deadline/decompression limits, immutable SHA-256 objects and receipt verification.
- Deterministic stratified GDAC discovery; strict adjusted D/QC1 core-profile parsing; masked identifier padding handling; TEOS-10 depth conversion; no extrapolation or wide-gap interpolation; variable-specific missing data and rejection records.
- Frozen Parquet plus catalog/QC/code/environment fingerprints; offline replay from original bytes.
- Train-only harmonic climatology, tuning-selected HGBR/LightGBM residual comparisons, independent profile-group calibration, shrinkage residual distances and weighted discrete FPCA prototype.
- Validated historical OISST array/masks/units and wave/wind point-forecast JSON units/horizon; official NDMA RSS index candidate checked without claiming marine completeness.
- JSON/Markdown reports and fail-closed readiness command. No production models, trip verdicts or live advisory ingestion are enabled.

## Commands

```sh
make phase0
make phase0-replay
make phase0-gate
```

Python 3.12 and uv suffice for this track. On macOS LightGBM needs libomp; the local missing dependency was installed with Homebrew. Runtime scientific serving remains separately locked and lightweight. Raw objects, receipts, Parquet, catalog copy, snapshot and full report live under ignored `artifacts/phase0/`. `make phase0` uses verified cached artifacts when present; choose a new `--output` directory for a fresh acquisition. A replay does not refresh source time.

## Measured pilot

GDAC index: 3,415,420 rows scanned; 57,404 invalid/unsupported index rows excluded; 128,892 supported-domain/baseline profile entries and 857 platform IDs; 115,275 D-file candidates. Counts are index availability, not QC-passed training counts or a complete scientific census.

192 stratified files retrieved. 116 stable profiles and 2,913 variable/depth rows accepted. Split profiles: {'calibration': 25, 'test': 27, 'train': 33, 'tune': 31}. Rejections: {'duplicate_pressure_levels': 1, 'multiprofile_file_requires_phase2_parser': 63, 'no_qc_passed_standard_levels': 12}. Multiprofile files remain explicitly unsupported in the pilot; their correct source-native identity and per-parameter policy are Phase 2 work.

| Variable | Climatology MAE | HGBR MAE | LightGBM MAE | Test profiles |
| --- | ---: | ---: | ---: | ---: |
| practical_salinity | 0.7561 | 0.5053 | 0.4962 | 22 |
| temperature_c | 1.1063 | 1.0965 | 1.1032 | 27 |

MAE is row-weighted in variable units (°C or practical salinity); profile-weighted and subgroup metrics are also retained in the evidence JSON. Temperature improvement is small in this sample; salinity improves but remains limited by sample/domain/calibration evidence. Neither result establishes a production win. The baseline is a pilot harmonic reference, not an independently validated operational climatology.

| Variable | Nominal simultaneous profile coverage | Observed test profile coverage | Mean interval width |
| --- | ---: | ---: | ---: |
| practical_salinity | 80% | 68.2% | 2.7405 |
| temperature_c | 80% | 85.2% | 7.6168 |

Salinity undercovers at profile level despite high row coverage. Temperature intervals are wide. These are release concerns, not acceptable-calibration claims. Calibration has only 22/25 profiles; serial/platform dependence and pilot sampling further limit interpretation. Quantile crossing before rearrangement is recorded. Synthetic profile perturbations are sensitivity diagnostics only; no expert-labelled false-alert/recall validation exists.

## Source results

- Argo: authoritative NetCDF index/files accessible; pilot QC/replay demonstrated. [GDAC access](https://argo.ucsd.edu/data/data-from-gdacs/) and [attribution](https://argo.ucsd.edu/data/acknowledging-argo/).
- NOAA OISST v2.1: historical 2024-09-01 analysis sample parsed; 15,702 valid and 10,698 missing/land cells in the configured domain. It blends satellite and in-situ observations, so it is not independent satellite truth. No live cadence claim. [Product description](https://www.ncei.noaa.gov/products/optimum-interpolation-sst).
- Open-Meteo wave/wind: 48 hourly points near 15°N,70°E with no missing requested variables in the retrieved samples; resolved grid coordinates differ from requested coordinates and are recorded. Initialization cycles are absent, so reproducible trip-source acceptance fails. Free endpoint evaluation does not establish commercial endpoint approval. [Marine API](https://open-meteo.com/en/docs/marine-weather-api) and [access terms](https://open-meteo.com/en/pricing).
- NDMA SACHET: official public India RSS index retrieved with 99 items in this snapshot. Index identity/date/link checks pass, but no CAP geometry/validity/cancellation or complete marine coverage contract has been validated. Advisory state remains unknown. [Official RSS page](https://sachet.ndma.gov.in/CapFeed) and [CAP integration guide](https://sachet.ndma.gov.in/docs/Integration_Guide_For_Agencies.pdf).
- INCOIS direct marine advisory adapter remains unconfirmed. Public forecast pages are not proof of a supported complete advisory API.

## Gate results

| Gate | Result |
| --- | --- |
| argo_slice_feasible | passed for pilot |
| official_advisory_feed_verified | unproven / blocked |
| operational_source_cadence_validated | unproven / blocked |
| production_licenses_approved | unproven / blocked |
| scientific_prototype_executed | passed for pilot |
| scientific_release_validated | unproven / blocked |
| sst_sample_accessible | passed for pilot |
| trip_forecast_cycles_reproducible | unproven / blocked |
| wave_and_wind_samples_accessible | passed for pilot |

`make phase0-gate` was exercised and exited 2. Offline replay downloaded zero bytes and reproduced the exact Parquet hash and test metrics. This verifies replay of the pilot, not long-term provider availability, generalization or production acceptance.

## Required next evidence

1. Full core secondary-profile/BGC handling and a reviewed near-real-time QC matrix before production ingestion; retain the pilot training policy.
2. Larger representative frozen datasets, validated static geography/coastal masks, buffered spatial/platform audits and prespecified numerical release gates. Keep climatology fallback; do not promote from this pilot.
3. Revised calibration experiment addressing salinity undercoverage, interval width, subgroup sample sizes and dependent observations; no automatic adaptive release.
4. Cycle-resolved operational forecast products, route/time/coastal sampling validation and repeated cadence/uptime measurements.
5. Verified CAP/advisory issuer/domain/type completeness, cancellations, geometry, age expectations and redistribution/commercial review; reviewed activity threshold set.
6. Actual event detector and expert/quiet-period labels before claiming heatwave recall or profile false-alert rate.

## Verification and evidence

21 Python tests passed (acquisition bounds, retries, corrupted cache, identifier padding, QC, no extrapolation, held-out-label independence, calibration rank, forecast expiry, unknown empty RSS, schemas and gRPC), plus Go race/health-concurrency tests and frontend contracts. Eight upstream NetCDF4/NumPy deprecation warnings arise while writing synthetic NetCDF fixtures; no test failures. Lint/type checks, native/Next.js builds, live Compose smoke and migration integration checks passed. GitHub CI is configured but has not executed in this local work.

Compact evidence: [phase0-summary.json](evidence/phase0-summary.json). Full local evidence: `artifacts/phase0/report.json`, `snapshot.json`, `catalog.json`, `observations.parquet`, raw bytes and receipts. Do not commit raw sample corpora by default; retain them for replay under the source terms. No commit, push, deployment or model promotion was performed.
