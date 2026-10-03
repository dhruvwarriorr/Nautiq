# Edge-case register

This is an implementation and verification register, not a claim that all future product behavior exists. **Tested** refers to current automated/local checks; **pilot** refers to measured offline source/science behavior; **planned** requires implementation in its owning phase. New incidents extend this register. No finite review can prove that every possible failure has been found.

| ID | Edge/failure | Required response | Owner / state |
| --- | --- | --- | --- |
| D01 | Timeout, connection reset, truncated/empty body | Bounded retry; no checksum publication of incomplete bytes | Phase 0 acquisition, tested/pilot |
| D02 | 429, long/date Retry-After, auth failure | Respect delay or stop; no blind retry storm | Phase 0 acquisition, tested policy; production scheduler planned |
| D03 | Redirect/private IP/userinfo/non-HTTPS URL | Deny in pilot; production pins allowed public destination on connect | Phase 0 tested allowlist; production egress planned |
| D04 | Changed raw object/corrupt cache receipt | Immutable hash identity; fail checksum, never silent overwrite | Phase 0 tested |
| D05 | Compressed index bomb, huge lines/object/batch | Hard byte/expansion limits, source-local failure | Phase 0 tested |
| D06 | Discovery path traversal, malformed date/position | Reject index row; track counts | Phase 0 tested |
| D07 | Cursor ties, late/out-of-order changes | Overlap windows and stable tie-breaker; persist before advance | Ingestion Phase 2 planned |
| D08 | Same profile through multiple providers/revisions | Stable profile identity + immutable revisions + source links | Phase 0 duplicate rejection; canonical selection Phase 2 planned |
| D09 | R/A/D disagreement, variable-specific QC, adjusted errors | Explicit training/display policies; retain variable-specific validity | Strict D/QC1 Phase 0 tested; live policy planned |
| D10 | NetCDF masked identifier padding/fill values | Decode padding correctly; masked numeric values stay missing | Phase 0 tested/pilot |
| D11 | Missing time/position QC, invalid units/ranges | Reject/quarantine with reason; no scientific output | Phase 0 tested/pilot |
| D12 | Duplicate/reversed pressure, wide gaps, missing surface/bottom | Sort, reject conflicting duplicates, mask gaps, no extrapolation | Phase 0 tested |
| D13 | Core secondary/multiprofile or BGC per-parameter modes | Explicit parser scope and native discriminator | Phase 0 records rejection; full parser Phase 2 planned |
| D14 | Oversized NetCDF dimensions/unsupported calendar | Bound arrays; reject unsupported format | Phase 0 dimension guards; sandbox worker planned |
| D15 | Lat axis reversed, 0..360 lon, CRS/curvilinear grid | Explicit normalization; validate before field sampling | Phase 0 regular OISST pilot; general Field Service planned |
| D16 | Land cells, cloud/missing masks, biased coastal nearest cell | Preserve masks/coordinates; unavailable across unsupported coast | OISST mask pilot; route sampling planned |
| D17 | Forecast nulls, wrong units, duplicate/missing time | Count missing; reject shape/time/unit incompatibility | Phase 0 tested/pilot |
| D18 | Forecast init cycle absent/expired/horizon gaps | Record missing cycle; block reproducible trip gate | Phase 0 tested/pilot |
| D19 | Preliminary SST revised, analysis contains Argo | Separate revision and dependent evidence; no false independence | Source/science policy; pipeline planned |
| D20 | No official feed/HTTP200 empty/partial geography | Advisory state unknown; never infer known-none | Phase 0 explicit blocked gate; advisory adapter planned |
| D21 | Cancellation, late bulletin, ambiguous text geometry | Issuer-version precedence; retain potential relevance | Advisory phase planned |
| D22 | License permits display but forbids export/commercial endpoint | Separate access/display/export approvals; block unsupported use | Catalog pilot; production enforcement planned |
| A01 | DB commit succeeds, broker publish fails | Transactional outbox retries | SQL foundation implemented; dispatcher Phase 2 planned |
| A02 | Broker acknowledgement/consumer acknowledgement lost | Stable event ID/inbox commit; duplicate no-op | SQL uniqueness tested locally; consumers planned |
| A03 | Object succeeds, DB fails; DB succeeds, lake manifest fails | Reconcile orphans/manifests; readiness waits for complete product | Phase 2 planned |
| A04 | New revision arrives while old prediction runs | Revision compare-and-set; stale result cannot overwrite new | Batch science planned |
| A05 | Poison event, schema drift, expired lease | Durable quarantine/version error; bounded replay | Phase 2 planned |
| A06 | Queue retention exhausted/backfill flood | Reconstruct from manifests; reserve live-ingest quota | Phase 2 capacity/ops planned |
| A07 | Redis/NATS/ML/web outage | Diagnostics degrade; required-DB API readiness remains independent | Phase 1 tested locally |
| A08 | DB/schema missing/newer/migration changed | Fail closed; transaction rollback; never delete data volume | Phase 1 migration runner tested locally |
| A09 | Concurrent migrations or long schema lock | Advisory transaction lock and lock/statement timeout | Phase 1 implemented; contention test planned for production |
| A10 | gRPC role swapped/runtime healthy but model absent | Verify identity; separate runtime and scientific capability | Phase 1 tested/pilot |
| A11 | Large RPC/concurrency flood/parser crash | Message/task bounds and worker isolation | Phase 1 RPC bounds; scientific sandbox planned |
| A12 | Fail-fast optional fan-out cancels valid observations | Separate optional work; per-layer error envelope | Query orchestration planned |
| A13 | Stale cache warning or missing advisory invalidation | Versioned key + validity TTL; never stale favorable | Trip/cache phase planned |
| A14 | Restore contains mismatched DB/object/model state | Integrity/manifest checks; block scientific/trip release | Production restore gate planned |
| M01 | Same profile/revision split across train/test | Stable identity grouping; fail leakage check | Phase 0 tested |
| M02 | Baseline/scale/PCA uses held-out labels | Fit on train only; separate tuning/calibration/test | Phase 0 tested |
| M03 | Repeated test selection/spatial/float dependence | Freeze gates and new audit block; independent buffered audits | Phase 0 limitation reported; release audit planned |
| M04 | Sample sparse by depth/month/coast/variable | Counts/coverage masks; unsupported depths unavailable | Phase 0 pilot |
| M05 | ML fails to improve baseline/subgroup regression | Keep climatology; no automatic promotion | Phase 0 report; release gate planned |
| M06 | Mean labelled median/reference interval labelled confidence | Explicit estimand/predictive interpretation | Scientific contracts; serving planned |
| M07 | Quantile crossing/too few calibration profiles | Rearrangement before calibration; finite-sample rank/unavailable | Phase 0 tested |
| M08 | Correlated/drifting calibration, adaptive reference absorbs event | Publish limits; fixed reference, reviewed calibration releases | Phase 0 limitation; production monitoring planned |
| M09 | Near-zero scale, ill-conditioned covariance | Versioned floor/shrinkage; no unstable inverse | Phase 0 pilot |
| M10 | More sampled depths inflate anomaly score/missing depths imputed 0 | Fixed complete-case comparison and depth weights | Phase 0 tested/pilot; sparse FPCA planned |
| M11 | PCA sign/reordered modes mislabel thermocline | Reviewed loading interpretation; version basis | Scientific review planned |
| M12 | Synthetic sensitivity mistaken for true recall | Label sensitivity only; require expert/quiet-period labels | Phase 0 report; validation planned |
| M13 | Isolated profile mistaken for regional heatwave | Separate detector, daily coverage/duration/spatial support | Event phase planned |
| M14 | Out-of-domain/unphysical/bundle version mismatch | Fallback/unavailable with distinct method release | Serving gate planned |
| M15 | Delayed-mode labels unavailable for current monitoring | Show verification lag; never infer healthy model from no labels | Monitoring policy planned |
| P01 | Empty query/partial layer/nonfinite JSON | Empty lists; null+reason; no fabricated observation | Planned OpenAPI/spec |
| P02 | Dateline bbox, invalid polygon, ambiguous local time | Explicit geometry/time resolution or typed error | Planned query contract |
| P03 | Nearby 10m profile displayed as local SST | Actual position/depth/distance; reviewed matching method | Planned observation UI contract |
| P04 | Cursor pagination spans revisions | Pin snapshot and filter-bound deterministic cursor | Planned query contract |
| P05 | Known warning plus missing forecast/another unknown feed | Warning primary; retain all missing/adverse diagnostics | Planned trip truth table |
| P06 | Threshold equality/user threshold loosens required rules | `>=` triggers; preferences cannot bypass warnings/inputs | Planned trip contract |
| P07 | Route speed/stops/return unknown/oversized sample space | Require timing; bounds; no invisible downsampling | Planned route contract |
| P08 | Calmest hour shorter than trip/missing gap inside best window | Full contiguous assessed interval or no window | Planned trip contract |
| P09 | Feed failure interpreted as alert recovery | Fresh positive recovery evidence; correction/retraction workflow | Alert phase planned |
| P10 | Duplicate POST/delivery/ownership race | Idempotency, optimistic version, per-user authorization | Auth/saved-state phase planned |
| P11 | CSV formulas/private export link/license leak | Sanitize cells, scoped expiring links, export rights | Export phase planned |
| P12 | Offline verdict/out-of-order search/session expiry | Expiry labels/query IDs/auth recovery; never renew stale verdict | UI phase planned |
| P13 | Color-only warning/inaccessible map | Text/icon severity and keyboard/table alternatives | UI accessibility gate planned |
| P14 | LLM invents input/value/advisory/verdict or query exceeds limits | Typed schema/policy and normal API execution; constrained explanation | Language phase planned |

## Verification discipline

The register prioritizes high-impact source loss, scientific leakage and false reassurance. Each future implementation links its tests and acceptance evidence here. “Planned” rows are blocked capabilities or required future work, not silently completed fixes. Phase 0 source results and Phase 1 live verification are dated in `10` and `07`; rerun after code/config changes before claiming current acceptance.

## Phase 2 execution update — 2026-10-01

See [Phase 2 delivery](11-Phase-2-Delivery.md) for code paths, exact verification commands and local acceptance limits. This updates the earlier planned states above without promoting unrelated capabilities.

| IDs | Argo slice status |
| --- | --- |
| D01–D06 | Bounded discovery/transport and public-destination pinning implemented; offline discovery/order/line/expansion/path/domain/time/provider-error/size/unsafe-URL checks and live GDAC acquisition passed. Actual provider outage/429 behavior is not a live cadence audit. |
| D07–D14 | Overlap cursors, immutable revisions/source links, R/A/D per-variable display QC, native multiprofile identity and parser quotas implemented. Synthetic and real corpus checks passed, including secondary profiles and explicit rejection records. |
| A01–A03, A05 | Outbox/inbox, ack ordering, lease tokens, durable quarantine and raw/lake reconstruction implemented. Local broker outage/expired lease plus disposable SQL rollback/replay/orphan/missing/corrupt artifact checks passed. |
| A06 | Separate live/backfill scopes, live-first scheduling and bounded retained-stream reconstruction implemented. Production capacity/retention load testing remains a gate. |
| A11 | NetCDF parser child deadline, bounded arrays/objects and restricted normalizer container implemented; corrupt-file and dimension policy checks are local acceptance only. |
| P01, P02, P04 | Empty/null/typed invalid query responses, explicit UTC/bbox policy, bounded signed filter-bound snapshot pagination implemented and verified. Dateline-crossing requests are rejected and must be split explicitly. |
| P03, P13 | Explorer shows original observation position/depth, coordinate table and textual QC/missingness. Rendered HTML passed; actual visual/browser accessibility acceptance remains unverified because computer-use access was denied. |

No model, forecast/advisory, trip, auth, export, production restore or scientific-promotion state is changed by this update.


## Phase 3 execution update — 2026-10-02

See [Phase 3 delivery](12-Phase-3-Delivery.md) for exact commands and evidence.

| IDs | Correctness/reproducibility status |
| --- | --- |
| D08–D14 | Deterministic raw replay, linked duplicate artifacts, R→D precedence, bad-unit/malformed quarantine and grouped variable rejection audit verified. The frozen real GDAC fixture fixes raw hashes, original levels, source flags and numerical depth references. |
| A04 | Leased original-level summary recomputation uses revision and lease compare-and-set. Supersession while an old result stages was injected; old work became obsolete and could not publish as current. This verifies the implemented summary boundary; model predictions remain future work. |
| A03, A05 | Snapshot staging followed by forced SQL failure rolls back manifest/calculation publication. Exact digest validation rejects a corrupted frozen artifact; rebuilding never silently overwrites it. Candidate counts and selection use one database read snapshot; SQL/lake disagreement blocks publication. Repaired current artifacts recover obsolete summary jobs, and expired leases are reclaimed. |
| M01, M04 | One stable profile/revision per snapshot, fixed UTC temporal blocks, independent variable labels, candidate/byte budgets, counts and coverage recorded. Spatial/platform independence and coastal completeness remain unverified scientific release gates. |
| D19, M15 | Supersession invalidates live calculation evidence while frozen historical snapshots remain unchanged. Original as-of snapshots reproduce after upstream revision. Cadence/coverage stay unverified; live fetch age and delayed observation age are separate. |

No production model, field/advisory/trip capability or release approval is enabled by this update.

## Phase 4 execution update — 2026-10-02

See [delivery and exact verification commands](13-Phase-4-Delivery.md).

| Failure | Implemented behavior and evidence |
| --- | --- |
| Held-out labels or locations alter reference | Offline gate perturbs them; fitted coefficients, support, spread and fit hash remain identical. |
| New Year/leap year/unsupported depth | UTC calendar phase; continuous annual harmonics; unsupported depth/geography refused. |
| One variable missing; rejected native gap or wide bracket | Independent masks; no extrapolation or interpolation across missing labels/nonadjacent native indices/>250 m bracket. |
| Sparse local pool or training envelope absent | Ordered cell→basin→band support checks; explicit fallback/counts or null estimate; no nearest coastal substitution. |
| Zero residual variance | Versioned positive residual-scale floors; no calibrated interval claim. |
| Empty region/depth test subgroup | Null metrics, evaluated/candidate counts and coverage reasons; 2,000 m real test evaluates zero rows. |
| Revision/reference changes during object staging | Disposable gate interleaves both changes; final canonical-lock checks prevent obsolete work from publishing live. |
| Expired or stolen lease | Expired work is reclaimed; staging with lost token/time cannot publish. |
| Corrupt artifacts or mutable observation projection | Checksum or SQL/lake refusal; temporary checksum failures remain retryable and recover after verified byte restoration; invalid projection quarantines. |
| SQL publication fails after staging | No reference or fit calculation is published; immutable staged artifacts cannot overwrite another release. |
| Revision changes after frozen fit | Frozen reference/input checksums unchanged; old live comparison stale, replacement revision separately queued. |

These checks establish local implementation/recovery. Spatial/platform independence, representative coastal coverage and calibrated uncertainty remain scientific release gates. No ML/anomaly/event/field/advisory/trip approval follows from a supported warmer/cooler difference.

## Phase 5 execution update — 2026-10-02

| Failure or ambiguity | Delivered behavior and verification |
| --- | --- |
| Random rows, split revisions, held labels leaking into fit | Stable profile/depth identity checks and frozen temporal assignments; changed calibration/test labels leave native models unchanged in the offline gate |
| Residual-only spatial holdout still leaks the reference | Buffered spatial and grouped platform audits refit the full climatology/support and residual fitting on complements; missing support is explicit |
| A registered or marginally better candidate is called promoted | Reviewed criteria, untouched-test, independence/source, material-improvement, bias and subgroup checks are separate; both real candidates retain climatology |
| Nonboolean approval strings or zero baseline error pass a numerical gate | Policy parser requires boolean approvals; zero baseline MAE cannot qualify as material improvement |
| Registry latest, wrong runtime pin, changed native/reference code | Exact ID/checksum/native features, expected/climatology code and locked runtime dependency checks; gRPC wrong-release refusal and code-mismatch reliability check |
| Artifact logging bytes differ from scientific bundle | MLflow logs the same canonical bundle bytes; live artifact download matches S3 SHA-256; exact run/version metadata remains independent of serving selection |
| Missing variable, unsupported depth/coverage or unsafe candidate | Independently nullable observed/reference/candidate values; climatology fallback or unavailable mean, zero applied residual only with a supported fallback |
| Revision/model/reference changes after inference | Final lease/current-revision/selected-pins check and atomic stale/restore lifecycle; races verified in disposable SQL/S3/gRPC |
| Expired or stolen lease, RPC outage, corrupt model bundle | Lease recovery/ownership guard; deferred retry preserves valid observations; corrupt bundles cannot select/load; verified in disposable recovery checks |
| Model explanations mistaken for causal oceanography or uncertainty | Native TreeSHAP additive residual explanations are labelled model behavior; no calibrated interval, anomaly or scientific production claim |

`verify_phase5.py`, `verify_phase5_reliability.py` and `verify_phase5_smoke.py` own these gates. Local acceptance and real measurements are recorded in `14-Phase-5-Delivery.md`; no production deployment, visual browser acceptance or scientific release approval is implied.

## Implemented predictive interval evidence

The diagnostic quantile/CQR workflow, exact parent pins, profile aggregation unit, hierarchical fallback, revision/selection/lease checks and fixed-reference coverage monitor are delivered in [the uncertainty implementation report](15-Phase-6-Delivery.md). Its current measurements are in [the evidence snapshot](evidence/phase6-summary.json). `predictive_intervals` records supported implementation availability; `calibrated_uncertainty` requires empirical coverage and independent review gates. The already inspected historical test cannot establish untouched-test approval. Mean and median remain separate; no automatic recalibration or anomaly verdict is introduced.

## Profile anomaly controls delivered — 2026-10-02

| Failure | Implemented response | Evidence |
|---|---|---|
| Different depth coverage distorts score ranking | Require complete eleven-depth vectors per variable; retain null masks and reject incomplete aggregates | `phase7-verify`, `phase7-smoke` |
| Calibration/test labels fit covariance or PCA | Train-only fit; raw train-fitted quantile scale; separate frozen percentile reference; explicit leakage checks | `phase7-verify` |
| Singular covariance or degenerate basis | Shrinkage, frozen condition/rank guards and unsupported variable state | model fitting and offline checks |
| Arbitrary PCA component treated as oceanographic fact | Deterministic orientation plus numeric loadings, scores and reconstruction; no automatic physical labels | release/profile explorer |
| Sparse percentile group gives false precision | Region/global count-only hierarchy, minimum complete profile support, null ranks and published resolution | `phase7-verify`, `phase7-smoke` |
| Black-box baseline controls primary verdict | Z-score/Isolation Forest remain separate comparison lenses; safe JSON export parity | `phase7-verify` |
| Old revision or ancestor publishes late evidence | Source/canonical verification, shared selection lock, exact parents, final lease checks, staleness/restoration | `phase7-reliability` |
| Diagnostic percentile becomes a scientific alert | Approval false in policy/SQL/RPC/API; separate diagnostic capability; expert/quiet-period/untouched audits explicitly unavailable | capabilities and delivery evidence |

These controls complete the declared complete-case implementation. Sparse functional inference and scientifically validated event/false-alert behavior remain outstanding review requirements; see [delivery](16-Phase-7-Delivery.md).

## Gridded field execution update — 2026-10-02

| Register scope | Delivered behavior and verification |
| --- | --- |
| D14, D15, D17 | Native NetCDF/GRIB dimension/calendar/units/packing/parameter/level checks; descending latitude and regional longitude normalization; explicit projected/curvilinear refusal; offline encoded-provider fixtures and full real-source parsing |
| D16, P01, P03 | Land/missing support remains null or transparent; positive-weight coastal masks refuse interpolation; exact native coordinates/weights/time/distance and source resolution are exposed |
| D18, D19 | Actual source cycle separate from valid time; complete requested lead windows; no mixed-run HYCOM aggregation; preliminary/final SST precedence and no independent-Argo-validation claim |
| A01, A03, A05 | Staged immutable Zarr/raw hashes before atomic SQL/calculation/outbox publication; idempotence, forced rollback, late-cycle ordering, missing/corrupt chunks and verified-byte recovery tested in a disposable database |
| P02, P07 | Timed outward/return/stopped/dateline routes; invalid timing/geometry and oversize budgets rejected without coarsening; polygons require valid bounded geometry and explicit dateline splitting |
| P13 | Interactive desktop/mobile field rendering, timeline/variable controls, point/route actions, transparent masks, request cancellation and keyboard-accessible evidence tables checked locally |

[Field delivery](17-Phase-8-Delivery.md) and [real-source evidence](evidence/phase8-summary.json) distinguish encoded test fixtures from real provider acquisition/replay and browser checks. Provisional source-age limits do not establish repeated provider cadence or complete coverage. D20–D22 advisory completeness/rights, scientific coastal validation, regional events, approved trip thresholds and production operations remain pending. Field availability does not grant scientific release approval.

## Event detection execution update — 2026-10-03

| Failure | Delivered behavior | Verification |
| --- | --- | --- |
| Four warm days or equality with threshold | No qualified cell event | Independent arithmetic gate |
| Missing day treated as normal or used to join events | Explicit unknown coverage; no temporal bridge | Encoded archive and gap fixtures |
| Two short runs joined to manufacture persistence | Only independently five-day-qualified runs can join | Duration/gap fixtures |
| A single native cell called a regional event | Regional cell/area/day minima; rejected-component count retained | Regional support fixture |
| Land hole filled by a bounding polygon | Union of exact native cells preserves holes | Geometry/area fixture |
| A single unusual profile called a heatwave | Explicit isolated diagnostic, MultiPoint geometry, separate regional support rules | Offline, disposable and real profile runs |
| Calendar-day labels hide more than 48 hours | Use exact timezone-aware observed instants | UTC-gap fixture |
| New observation/comparison or ancestor changes during publication | Whole-snapshot and exact-lineage checks under shared lock; atomic rollback | Disposable race gate |
| Report, source, array, parent or calculation disappears | Integrity failure withholds details; exact-byte restoration verified | Disposable recovery gate and bounded API implementation |
| Older frozen run mistaken for live coverage or event absence | Frozen/current/stale state, explicit windows/coverage/censoring, no approval or live-alert claim | API/schema and desktop/mobile explorer |

[Event delivery](18-Phase-9-Delivery.md) and [measured evidence](evidence/phase9-summary.json) separate real retained NOAA/Argo diagnostics from synthetic fixtures. Expert-event comparison, quiet-period false-alert rates, repeated cadence, coastal validation and operational approval remain unproven.

Official CAP ingestion explicitly tests hostile XML/entities/URLs, duplicate index identities, truncation/byte/time budgets, damaged conditional caches, missing expiry, lat/lon reversal, text/geocode areas, invalid polygons, language multiplicity, private/test status, changed bytes under one identity, absent reference parents, wrong-sender cancellation, incomplete updates, arrival reordering, disappearance, atomic rollback and immutable projection corruption/recovery. Unknown feeds and geometry never establish an absence of warning; a verified relevant warning takes priority over unknown other feeds. See [delivery evidence](19-Phase-10-Delivery.md).

Trip verification covers all precedence branches, equality at limits, warning priority over missing/stale data, retained adverse samples, null/unapproved limits, stricter-only preferences, co-timed combinations and worsening rules, malformed/duplicate request keys, incorrect units/cycles/horizons/sample plans, timed stops/returns, sample budgets without coarsening, dateline refusal, warning intersections between forecast samples and validity clipping, source run/policy publication races, private token access, public calculation exclusion, immutable object/SQL mirror corruption and transaction rollback. Replay uses frozen inputs and cannot refresh an old verdict. Numeric safety/domain approval and operational source completeness remain external gates.

## Product ownership and export verification

| Failure | Delivered behavior | Verification |
| --- | --- | --- |
| Guessed or spoofed owner/route/watchlist/job/receipt | Verified session owner, strict client fields and cross-owner 404 | Two-account disposable API and real object storage |
| Lost response or concurrent repeat | Atomic UUID idempotency replay; changed payload conflicts | Concurrent API retries |
| Stale form or cancellation | Quoted version conflict; lease publication cannot restore cancelled job | API CAS and cancellation-during-upload worker check |
| Expiry while editing / different account | Hidden in-memory draft, same-account restoration, new-account draft reset | Actual browser session expiry and account switch |
| Rewritten alert/file/source evidence | Byte hash and JSON mirror checks; refuse response/download | Corrupted evidence/artifact/input fixtures |
| Formula strings or fabricated export completeness | CSV string sanitization; row/byte budgets require refinement; exact original-level units and source/QC | Independent CSV/Parquet/NetCDF readback |
| Failed worker, orphan or expired artifact | Durable fenced leases, bounded attempts, cleanup queue, DB reconnect and record grace-period purge | Actual MinIO and disposable DB lifecycle |
| Grant leaked/reused or crossed owner | Owning session plus five-minute single-use identifier, checked bytes and atomic use | API/download verification |
| Relative time, unnamed place, arbitrary query or apparent all-clear | Typed bounded preview/clarification; per-layer unknown/stale states remain explicit | Offline/public query, empty research and browser location checks |
| Configured rule mistaken for active monitoring | Evaluation/delivery unavailable, empty inbox has no safety meaning | API flags and rendered rule/inbox notices |

See [product acceptance](21-Phase-12-Delivery.md); fresh-source field/trip gates remain separate from product implementation acceptance.
