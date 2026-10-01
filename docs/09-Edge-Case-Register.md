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
