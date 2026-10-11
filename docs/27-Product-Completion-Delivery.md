# Product completion delivery

> Historical delivery record from 2026-10-04. The current product later removed official warnings and personal alerts. Local-only test and verification harnesses are no longer distributed in the public repository. See the [current README](../README.md).

This closes the gaps recorded in [26-Gap-Analysis.md](26-Gap-Analysis.md) that code can close. It does not, and cannot, close the scientific, licensing, security-review or deployment gates, which stay explicit and false. Local implementation evidence is not independent review.

## What was delivered

| Gap | Delivery | Where |
| --- | --- | --- |
| A1, A7 guided entry and navigation | Redesigned home (question box, four task paths, state-label legend, live data freshness, an honest "what Nautiq will not do" block); `/start` two-minute guide with glossary; grouped navigation with current-page marking, a **More** menu and a persistent footer limitation; dismissible first-visit prompt. | `apps/web/app/page.tsx`, `app/start`, `components/ProductNav.tsx`, `SiteFooter.tsx`, `Welcome.tsx` |
| A2 natural-language experience | `/ask`: question → validated frame → explicit UTC plan → fixed-template answer. See below. `/query` redirects to `/ask`. | `services/api/internal/product/ask.go`, `internal/science/ask.go`, `apps/web/app/ask` |
| A3, A4, B4 model output with evidence and limits | Plain-language **ModelBrief** on `/models` and every location page; plain-language conditions summary at the top of each location page; per-profile combined evidence category with all components. | `components/ModelBrief.tsx`, `internal/science/evidence_category.go`, `profiles/[id]/Anomaly.tsx` |
| A5 | Trip form opens prefilled (start point and departure) from a question; other waypoints are labelled placeholders. | `app/trips/page.tsx`, `TripForm.tsx` |
| A6 | Last answer kept on the device as a labelled historical copy that is never refreshed; clearable. | `Ask.tsx`, `lib/device.ts` |
| B1 unified monitoring | `nautiq_ml/monitoring`, schema 17, `GET /api/v1/model-monitoring`, `/models/monitoring`, `make model-monitor`. | below |
| B2 combined profile evidence | `profile-evidence-category-v1`; derived on read, stored comparison unchanged. | below |
| B3 static coastal features | Real NOAA ETOPO 2022 acquisition, refit with and without features, measured outcome. Not released. | below |
| E2 | Optional language-model labelling is off by default, secret-file capable, rate limited, validated and absent from production overlay values. | below |

## Question → answer architecture

```text
text ──► (optional model labels intent/place/time) ──► Frame ──► validate ──► BuildPlan ──► Plan (explicit UTC window)
                 │  any failure                         ▲                                         │ shown to user, editable
                 └──► deterministic grammar ────────────┘                                         ▼
                                                      Frame (pinned window) ──► /answer ──► typed evidence ──► template answer
```

* A **Frame** has closed vocabularies: seven intents, five catalog places, two variables, a fixed list of time phrases (plus explicit dates), ten explanation topics. Anything else is rejected.
* Relative wording ("tomorrow morning", "this week", "last 7 days", "in October") resolves in the user's IANA zone to an explicit UTC window, shown in both local and UTC time. The resolved window is pinned into the frame so executing later cannot drift with the clock. "In October" means the most recent such month not in the future; the window is shown so the user can correct it.
* The answer step takes only a validated frame, never free text. It reads existing typed endpoints (conditions, advisory state, regional events, research rows) and fills fixed templates. Stale values are labelled stale, unknown is never an all-clear, a missing value is "Unavailable", and every answer lists what it does not tell you.
* Trip questions never yield a verdict. They hand off to the timed-route form.
* Explanations ("why caution", "what is expected normal", …) are fixed text maintained with the product and tested for non-claims.
* **Language model, when enabled.** Only intent/place/time labels come back, as strict JSON. Unknown fields, unknown places, non-JSON, dates the user did not write and rate-limit hits all fall back to the grammar, so a hostile or wrong model response cannot reach a scientific endpoint or add content. Question text is not stored. The API rate-limits provider calls (default 20 per minute). Configuration: `NAUTIQ_LLM_API_KEY` (or `_FILE`), `NAUTIQ_LLM_MODEL` (default `claude-haiku-4-5-20251001`), `NAUTIQ_LLM_BASE_URL` (https, or loopback for tests), `NAUTIQ_LLM_RATE_PER_MINUTE`. The production overlay blanks these. The live provider path has **not** been exercised against the real service in this work (no key); it is covered by contract tests against a local stub server.

Contract: [ask.openapi.json](../packages/schemas/ask.openapi.json). Behavior changes versus the earlier grammar: trip questions now resolve a window and hand off instead of stopping at "clarification required"; research requires a past window.

## Combined profile evidence category

`profile-evidence-category-v1` turns the stored empirical ranks into Typical (below the 90th percentile), Elevated (90–97.5), Unusual (97.5–99.5) and Strongly unusual (99.5 and above). The primary measure is the residual-profile (shrinkage Mahalanobis) rank; depth-weighted residual, PCA score distance and reconstruction rank are shown beside it and can flag an unusual vertical shape. Guards: fewer than 20 reference profiles gives "Not assessable"; fewer than 200 caps the label at Unusual because the strongest band cannot be resolved; rank resolution above two points and regional fallback are disclosed. Comparison baselines (Z-score, Isolation Forest) never drive the category. The bands are fixed engineering choices, not validated alert thresholds, and the category is not an event or a probability. Whole-profile category is the highest assessable variable.

## Unified model monitoring (design 03 §22)

`make model-monitor` reads stored comparisons for the selected releases over a window (default 90 days) and writes an immutable report and a `calculations` row of kind `model_monitor`. Sections: input availability and drift (PSI for latitude, longitude, season; spatial novelty; share of cells without an expected mean and why); expected-value error against outcomes with trusted (delayed-mode) and unverified (real-time) profiles kept apart; profile-rank tail shares tested only for bands the reference can resolve; interval calibration from the fixed-reference coverage monitor plus fallback-group usage. Overall status is `within_expectation` only when every section is adequately evidenced. Missing trusted labels are "not enough evidence", never health. Thresholds are unreviewed defaults stored with every report. Nothing is retrained, recalibrated, selected or promoted.

First real report (2026-10-04, 222 profiles from the last 90 days, all four selected releases current): inputs **investigate** (recent longitude distribution differs from the pilot training sample, PSI 0.37; latitude PSI 0.13 watch; 33% of profile-depth cells are outside the training envelope; 5% of recent profiles are in 5° cells with no training profile); outcomes **not enough evidence** (0 trusted delayed-mode profiles; unverified real-time MAE temperature 1.16 °C climatology versus 1.07 °C candidate, salinity 0.207 versus 0.194); profile ranking **within expectation** but only the 90th-percentile band is resolvable with a 28-profile reference (14.4% at or above versus 10% expected, p = 0.10); calibration **not enough evidence**. An earlier run of the same detector tested the 97.5 and 99.5 bands and reported a false "excess"; that showed a reference of about 28 profiles cannot resolve those bands, and the detector now refuses to test bands finer than the reference resolution.

## Static coastal-feature experiment (design 03 §6, §25)

Source: NOAA NCEI ETOPO 2022 60-arc-second bedrock product via OPeNDAP (DOI 10.25921/fd45-gt74), subset at 0.05° over the domain plus 3° margin (720 × 1220 cells, 9.5 MB, sha256 `567d4469…d03`, retained immutably in object storage). Derived features: bathymetry (m) by bilinear interpolation and great-circle distance to the nearest land cell centre. Terms and redistribution have not been reviewed; use is limited to this offline experiment.

Method: the complete frozen pipeline (train-only climatology, tuning-only selection, partition metrics, spatial and platform audits) was refit on identical rows (2,940 rows, 177 positions, none dropped) with and without the two features.

| Variable | Test profile MAE: climatology | LightGBM v1 features | LightGBM + static | Tuning change | Subgroup regressions v1 → +static |
| --- | --- | --- | --- | --- | --- |
| Temperature | 1.248 | 1.232 | 1.222 (0.8% lower than v1) | −0.1% | 3 → 6 |
| Salinity | 0.405 | 0.397 | 0.392 (1.3% lower than v1) | −1.0% | 2 → 1 |

Distance to coast carried 8.7% of the salinity model's total split gain and 1.4% of temperature's; bathymetry carried 1.6% and 0%. Only one of four spatial/platform audit folds per variable had enough training profiles; on that fold the static-feature LightGBM held-group MAE was 1.930 versus 1.932 (temperature) and 0.297 versus 0.301 (salinity). Conclusion recorded by the experiment: **not supported by pilot evidence**. The gain is under the 2% criterion, tuning did not improve, and temperature gained subgroup regressions. The 2022–2024 test block was inspected before, so even a favourable result could not approve a release. The features stay excluded from serving; the evidence is [static-features-summary.json](evidence/static-features-summary.json). A 0.05° grid cannot resolve shelves or channels, and bathymetry/coast distance describe where floats sample rather than what the water does, so any gain could be sampling geography.

## Schema 17 and operations

Migration `017_model_monitoring.sql` adds `model_monitoring_reports` and the `model_monitor` calculation kind. API readiness now requires version 17. Existing data is preserved. Role grants already cover new tables (`ALL TABLES`). Run `make model-monitor` on a schedule you choose (it is not started automatically). `make production-gate` still exits 2.

## What is still blocked

Unchanged and external: promotion of any residual model (needs an untouched audit block and reviewed gates); calibrated uncertainty (needs trusted delayed-mode outcomes); qualified anomaly or event verdicts (expert labels, quiet-period false-alert rates, independent audit); sparse functional PCA validation; coastal validation; approved trip thresholds and wording; INCOIS machine access and NDMA marine completeness; repeated cadence evidence; redistribution and commercial rights, including ETOPO terms review; independent security review of public identity; real host/TLS, offsite restore and on-call ownership. See the registers in [25-Release-Review.md](25-Release-Review.md) and [26-Gap-Analysis.md](26-Gap-Analysis.md).

At the time of delivery, unit tests were ignored by `.gitignore` and kept in the local working tree. The public source tree later also stopped tracking the phase verification harnesses; older Git commits retain their historical copies.
