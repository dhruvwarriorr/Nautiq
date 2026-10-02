# Frozen harmonic numerical reference

`reference.json` pins the expected temperature mean, residual spread and fallback/support metadata for the deterministic analytical fixture in `scripts/verify_phase4.py:fixture`, under `packages/source-catalog/climatology.json`.

The anchor is latitude 14° N, longitude 66° E, depth 10 m, observation `2022-06-15T12:00:00Z`. Forty-eight synthetic profiles span four calendar years, twelve months and four platform identities; only the first 36 profiles train the model. Temperature is `24 + 2*sin(seasonal_phase) - 0.003*depth`, salinity `35 + 0.5*cos(seasonal_phase)`. The gate checks fitted results to absolute tolerance 1e-8 and independently checks interpolation, signed differences, fallback, sparse coverage, floors and held-out isolation.

This recipe tests implementation stability. It is not real-source scientific acceptance evidence. The separate retained real GDAC snapshot and measured held-out report are documented in `docs/13-Phase-4-Delivery.md`; no synthetic profile is inserted into the operational database by verification.
