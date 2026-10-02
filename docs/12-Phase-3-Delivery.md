# Phase 3 delivery: data correctness and reproducibility

Phase 3 is implemented locally. The existing immutable Argo revision pipeline now produces structured QC audit records and reproducible calculation manifests, monitors local/source freshness separately, recomputes revision-safe original-level summaries, and builds frozen strict delayed-mode Parquet training snapshots. Schema 4 upgrades existing volumes without resetting data. No model or production scientific capability is enabled.

## Run and review

```sh
make setup
make up
make phase3-verify       # Frozen real GDAC fixture and offline policy checks
make phase3-reliability  # Disposable database and unique synthetic fault fixtures
make argo-replay         # Bounded retained raw replay; no new provider acquisition
make science-maintain    # Up to 500 summary jobs plus source monitoring
make training-snapshot AS_OF=2026-10-02T04:45:13.911676Z
make verify-snapshot SNAPSHOT_ID=3b606239-35ae-53ae-938d-5c0935385a00
make phase3-smoke        # Live contracts, HTML, and exact API/web Parquet bytes
```

Open [data quality](http://localhost:3000/data), [the verified snapshot](http://localhost:3000/training-snapshots/3b606239-35ae-53ae-938d-5c0935385a00), or [its calculation evidence](http://localhost:3000/calculations/88a837cc-b985-5c14-b5a6-b20827ef5e4e). Snapshot IDs refer to retained local volumes; a fresh checkout must acquire or import its own verified real inputs and use a new explicit selection time. Choose a selection time after inputs were registered if building on a fresh database.

For the existing Phase 0 cached acquisition, this bounded offline import verifies receipt hashes and raw sizes without calling GDAC:

```sh
docker compose run --rm --no-deps -v "$PWD/artifacts/phase0:/pilot:ro" normalizer \
  python -m nautiq_ml.argo.tools import-cache /pilot --limit 192
```

The normalizer consumes the durable raw outbox. Wait for `pending_event_count=0`, then maintain and build. Import again to continue a larger cache; registered artifacts are skipped. For more than 1,000 retained files, run the replay CLI with the returned `--after` UUID and a limit of 1–5,000. Replay reuses stable inbox/event identities and canonical hashes; it does not delete delivery history.

## Requirement coverage

| Requirement | Implementation and verification |
| --- | --- |
| Revision handling | Retained R/A/D revisions and source links, D>A>R precedence, monotonic update selection, same-version conflict quarantine; late R cannot replace D. History API and profile page expose retained revisions. |
| Deduplication | Stable native profile identity, unique canonical revision tuples, immutable raw links, inbox/outbox uniqueness; alternate artifacts link to the same profile and training example. Disposable replay asserts two profiles remain two and six level rows remain unique. |
| QC rejection table | `qc_rejections` records source/artifact, native profile index, variable, rule, reason, QC/normalizer versions, count, bounded sampled indices/context and audit time. Raw preserves exact rejected values. Legacy quarantine entries are explicitly marked as legacy context. |
| Source metadata | Versioned source catalog metadata, attribution/terms, expected cadence, independent freshness budgets, unverified coverage and false production approval; frozen snapshots pin the source metadata used at build time. |
| Freshness monitor | Successful **live** upstream checks, newest observation time, local ingestion age/state, provider cadence verification, queue count/age and QC audit-group count. Backfill/import/replay do not renew live freshness. Three-minute monitor expiry is exposed by the API. |
| `calculation_id` | Content-addressed immutable normalization, descriptive-summary and training manifests in SQL and private S3, pinned inputs/raw/canonical digests, method/code/environment/QC/policy/evaluation time and outputs. Detail API and pages retain historical evidence. |
| Revision-driven recomputation | Durable leased/token-checked summary jobs, current-revision validation under the canonical selection lock, stale live calculations on supersession, obsolete late work and independently frozen historical calculations. API and profile page require matching revision for a live summary. |
| Frozen fixtures | Checked-in real delayed-mode GDAC NetCDF, numerical/native/QC/hash manifest and malformed input under `packages/scientific-fixtures/argo`; offline gate runs in CI, alongside disposable revision/snapshot checks. Synthetic faults remain verification-only. |
| Parquet training snapshot | Explicit UTC as-of selection, one historical revision per stable profile, immutable raw/Parquet integrity checks, strict per-variable D/adjusted/QC1 labels, fixed temporal split, explicit nullable schema, ZSTD, content IDs/checksums, object staging before atomic SQL publication. |

Main code paths: `migrations/004_reproducibility.sql`, `ml/nautiq_ml/argo/{evidence,freshness,snapshots,tools,storage}.py`, the normalizer/parser, `services/api/internal/science/science.go`, and the `/data`, `/calculations/[id]`, `/training-snapshots/[id]` pages. `packages/schemas/science.openapi.json` defines the eight evidence routes; profile provenance additionally includes `calculation_id`.

## Frozen scientific policy

`packages/source-catalog/argo-training.json` pins baseline **2005–2024**, train **2005–2016**, tuning **2017–2019**, calibration **2020–2021**, test **2022–2024**, and geography west=45/south=0/east=100/north=30. Time conversion is UTC before assigning the split. Profile and selected pressure/label parameter modes must be D, selected fields adjusted and source QC 1. Missing salinity leaves valid temperature usable and vice versa; both missing drops that level. Original native level indices remain available.

This snapshot deliberately retains **original levels without interpolation**. The standard depth grid, climatology/features and fitted scientific model belong to Phase 4 and later. All labels/depths of a profile share one split. Temporal splits do not establish float or spatial independence, coastal coverage or calibrated model performance.

Default selection is 500 profiles; hard bounds are 2,000 candidate profiles, 100,000 candidate levels and 128 MiB Parquet. Preflight counts reject over-budget selections before loading level arrays; no silent truncation. Snapshot bounds and rows use one repeatable-read database snapshot after acquiring the canonical selection barrier. Snapshot object publication verifies checksums before inserting its SQL row. A same-as-of/policy/input/code/environment rebuild has the same content identity. Verified immutable Parquet levels and identity must agree with the SQL projection before labels are published. Future normalizer/QC/summary policy changes must bump their method version; runtime/code changes remain recorded in evidence.

Supersession marks live normalization/summary calculations stale and queues the new descriptive summary. A worker holding an expired/stolen lease or an obsolete input revision cannot publish a live aggregate. Frozen snapshots keep their original inputs and checksums. Original as-of history and latest canonical data are distinct products. Summary values are descriptive min/max/count/ranges, not climatology, anomaly scores or predictions.

## Dated local evidence

On **2026-10-02 at 04:44:49 UTC**, the local database had **352 retained profile files, 474 current canonical profiles and 129,865 original levels**. This includes an offline, hash-verified import of **192 historical cached files**, with **zero provider requests** for that import. Raw-delivery and summary-job queues were drained. There were **996 QC audit groups** at this checkpoint; these are grouped rejection records and include legacy context, not a scientifically normalized rejection rate. Scheduled ingestion legitimately changes later counts.

The frozen real snapshot was selected at **2026-10-02T04:45:13.911676Z**:

| Evidence | Value |
| --- | --- |
| Snapshot ID | `3b606239-35ae-53ae-938d-5c0935385a00` |
| Calculation ID | `88a837cc-b985-5c14-b5a6-b20827ef5e4e` |
| Parquet SHA-256 | `261232463f3664303d5782f695b90e4d8c76d123f705d9506a048053c68dd3da` |
| Selected historical profiles | 236 |
| Included strict delayed-mode profiles | 196 |
| Excluded non-delayed profiles | 40 |
| Original-level label rows | 61,281 |
| Train / tuning / calibration / test rows | 5,057 / 16,040 / 17,366 / 22,818 |
| Observed span | 2006-06-18 through 2024-12-23 |
| Release approval | false |

Full replay of all **352** retained raw files left all **474** current profiles unchanged. The sorted current profile/revision/Parquet/level/calculation fingerprint was `e35df1df53a1929ae93d72e150bc718a9c50188230dd13d8131b51f9c022778a` both before and after replay (334 normalized files and 18 quarantined files).

Two builds with the exact same selection time produced identical manifests, IDs and Parquet SHA. The CLI independently verified the stored manifest, file hash, row/profile counts and one split per profile. Live API and web proxy downloads matched the same exact bytes.

Passed locally:

- Frozen GDAC hashes, original-level numerical reference values/QC/native identity, repeated parsing/canonical revisions, malformed refusal, strict independent labels, UTC split boundaries, invalid policy rejection and freshness states.
- Disposable schema-4 database: R→D supersession, late R, same-event/new-artifact replay and linked duplicates; current calculation invalidation; summary supersession **during object staging**, with obsolete old jobs unable to overwrite current results; frozen historical rebuild after revision; identical same-time Parquet; independent missing salinity; profile/level budget refusal; atomic rollback after snapshot staging; checksum refusal for corrupted frozen Parquet and no silent overwrite; live/backfill/failure freshness separation; repaired current artifacts restart obsolete summary jobs; expired leases are reclaimed; concurrent readiness changes do not change a selection read snapshot; SQL/lake disagreement prevents frozen publication.
- Existing Argo parser/transport and disposable recovery verification, migration fresh/repeat/legacy/checksum/rollback checks; Go race checks, 21 existing Python checks and three frontend checks; Go format/vet, Ruff, ESLint, TypeScript, Compose validation and production builds.
- Live OpenAPI validation for sources, QC, revision history, normalization/summary calculations, snapshots; typed malformed/unknown/repeated/limit errors; exact API/web Parquet digests and rendered data/evidence/profile pages. All ten runtime dependency checks passed.

User-staged test removals and `.gitignore` changes were preserved. The new verification scripts live outside ignored test directories and remain runnable in a checkout without those tests. Rendered HTML/HTTP flows were checked; actual browser visual/interaction acceptance was not performed in this delivery.

## Operational and release boundaries

Provider cadence and complete source coverage remain **unverified**; the monitor implements truthful states rather than converting a recent download into source approval. Cadence metadata is an expectation until reviewed evidence exists. Local ingestion health, artifact integrity and a ready snapshot do not establish scientific release approval.

The snapshot builder is an explicit bounded offline command, never a live training loop. Calculation mirrors are durable in SQL/S3; automated coordinated production restore, large-corpus scaling, production licenses/coverage audits and scientific release validation remain separate gates. Production model, gridded fields, advisories and trip verdict capabilities remain false. No commit, push or deployment was performed for this work.
