# Gap analysis and completion record

> Historical audit from 2026-10-04. The current product later removed official warnings and personal alerts and changed forecast providers. See the [current README](../README.md) and [release review](25-Release-Review.md).

Audit date: 2026-10-04. Sources: documents 01–25, the delivered code, the running local stack (`/api/v1/capabilities`, live data) and checked-in evidence under `docs/evidence/`. Each row is a claim about the repository at the start of this audit unless the **Status** column says otherwise. Statuses are updated at the end of the work in the "Completion record" section.

## What Nautiq is meant to be

An ocean and marine-condition intelligence product for India's coastal waters. It answers three questions from retained, source-traced evidence: what the sea is doing now (observations, forecasts, official advisories), how unusual that is against a fixed historical normal (climatology, residual ML, calibrated intervals, profile anomaly diagnostics, regional events), and what a timed trip faces (deterministic rules, with official warnings always taking precedence). Language models may only parse a question and paraphrase a validated structured result; they never produce observations, forecasts, advisory status, ML values or a safety verdict.

## What exists at audit time

Phases 0–14 of the blueprint are implemented: source feasibility, local platform, Argo ingestion, correctness/reproducibility, harmonic climatology, LightGBM/HGBR residual candidates, quantile/CQR intervals, residual-profile and FPCA diagnostics, gridded fields, event diagnostics, official advisories, deterministic trip engine, product workspace, alerts/notifications and production-operations controls. All releases are pinned in the local stack; climatology is the active serving mean because neither residual candidate passed its promotion checks.

## Gap list

### A. Missing product features

| ID | Gap | Source requirement | Status at audit |
| --- | --- | --- | --- |
| A1 | No guided entry: the home page is a link list and the navigation has six undifferentiated items. A first-time user cannot tell where to start, what the data can and cannot say, or what each state label means. | 05 §1, §19, §20 mobile priority "search → conditions → trip → alerts → evidence" | Open |
| A2 | The natural-language flow is a keyword grammar with a plan preview. No relative-time resolution, no answers (only links), a loose place matcher, no language-model intent parsing, and no "why is Nautiq showing caution" explanation. | 05 §10, 06 §15 item 10 | Open |
| A3 | No consumer-readable summary of model output: `/models`, `/uncertainty` and `/anomalies` are research pages. Profile evidence has no combined display category (typical / elevated / unusual / strongly unusual) with inspectable components. | 03 §13, 05 §19 | Open |
| A4 | No plain-language "what the model says here and why you may or may not rely on it" panel on location pages. | 05 §3, §11, §12 | Open |
| A5 | Trip form cannot be opened from a question or location with prefilled place and time. | 05 §10 | Open |
| A6 | Last-viewed conditions are not kept for weak connectivity. | 05 §20, §24 | Open |
| A7 | Home/navigation do not surface live data freshness or the private/diagnostic status of the product. | 05 §12, 25 | Open |

### B. ML work

| ID | Gap | Source requirement | Status at audit |
| --- | --- | --- | --- |
| B1 | No unified model monitoring: input missing-rate and distribution, spatial/depth coverage, expected-state error/bias with verification lag, profile-detector percentile and alert frequency, calibration summary exist only for intervals. | 03 §22, edge cases M08/M15 | Open |
| B2 | No combined profile evidence category derived from the stored components. | 03 §13 | Open |
| B3 | Static coastal features (`bathymetry_m`, `distance_to_coast_km`) are documented as candidate features but excluded pending a validated source. | 03 §6, §25 | Open |
| B4 | Model outputs are not shown together with evidence and limitations outside the profile page. | brief | Open |

### C. Scientific validation (cannot be satisfied by code)

| ID | Gap | Why blocked |
| --- | --- | --- |
| C1 | Promotion of any residual model | The 2022–2024 test block has been inspected repeatedly; a new untouched audit block, frozen release gates and independent review are required. Both candidates fail the provisional checks. |
| C2 | Calibrated uncertainty | Needs trusted delayed-mode outcomes after the calibration period (none trusted yet: 0 of 140 candidate profiles) and independent coverage review. |
| C3 | Qualified profile-anomaly verdict, event approval | Needs expert-labelled events, quiet-period false-alert rates, independent audit, untouched test. |
| C4 | Sparse functional PCA | The complete-case prototype rejects incomplete profiles; sparse FPCA needs separate smoothing/missingness/basis validation. |
| C5 | Coastal accuracy of surface fields | Needs coastal in-situ validation data. |
| C6 | Trip thresholds | Marine/domain and legal sign-off. Numeric limits remain unapproved (null). |

### D. Data-source access and licensing

| ID | Gap | Status |
| --- | --- | --- |
| D1 | INCOIS machine-readable advisories: not configured, no confirmed machine access | External |
| D2 | NDMA CAP RSS: transport works; cadence, marine completeness and redistribution unverified; retained run is stale | External (refresh is operational) |
| D3 | Repeated cadence evidence for every provider (single acquisitions cannot prove cadence) | External, needs time |
| D4 | Redistribution/commercial approval for forecast and advisory data | External |
| D5 | Forecast cycles older than their freshness budget (retained GFS wave/weather) | Operational: reacquire with `make field-refresh` |

### E. Security

| ID | Gap | Status |
| --- | --- | --- |
| E1 | Independent security review, abuse/recovery review for public identity (no verified email login recovery, no MFA) | External |
| E2 | Any new external call (optional language-model parsing) must be opt-in, secret-file backed, bounded, validated and absent from production egress by default | Implemented with this work; see completion record |

### F. Deployment and operational release gates

| ID | Gap | Status |
| --- | --- | --- |
| F1 | Real host, domain, certificate and firewall acceptance | External |
| F2 | Offsite backup retention, key escrow, target-host restore | External |
| F3 | Named on-call ownership, alert routing, response exercises | External |
| F4 | `make production-gate` must keep exiting 2 until the review records in `25-Release-Review.md` exist | Unchanged by design |
| F5 | The CI workflow file is deleted in the working tree (`.github/workflows/checks.yml` shows as deleted). Pre-existing, preserved. | Not touched |

## Completion record

Updated 2026-10-04. Details, measurements and limits are in [27-Product-Completion-Delivery.md](27-Product-Completion-Delivery.md).

| ID | Result |
| --- | --- |
| A1, A7 | **Done.** Home, `/start`, grouped navigation, footer, first-visit prompt, live freshness strip. |
| A2 | **Done locally.** `/ask` with validated frames, explicit correctable windows, fixed-template answers, trip hand-off. Optional language-model labelling is implemented and tested against a stub only; **not exercised against a real provider**. |
| A3, A4, B4 | **Done.** ModelBrief, plain-language location summary, profile evidence category. |
| A5, A6 | **Done.** Prefilled trip form; labelled last-answer copy on the device. |
| B1 | **Done locally.** Unified monitor, schema 17, API, page, `make model-monitor`. First real report: inputs investigate, outcomes and calibration not enough evidence, profile ranking within expectation (one resolvable band). |
| B2 | **Done.** `profile-evidence-category-v1`. |
| B3 | **Measured, not adopted.** Real ETOPO 2022 experiment: 0.8% and 1.3% lower test MAE, no tuning gain, more temperature subgroup regressions; not supported by pilot evidence. Static features stay out of serving. |
| C1–C6 | **Blocked, unchanged.** |
| D1–D4 | **Blocked, unchanged.** D5 (stale forecasts) was refreshed locally on 2026-10-04 with `make field-refresh` and `make advisory-refresh`; cadence is still unproven. |
| E1 | **Blocked, unchanged.** E2 done as described. |
| F1–F4 | **Blocked, unchanged.** `make production-gate` still exits 2. |

