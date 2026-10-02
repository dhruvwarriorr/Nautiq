# Official advisory delivery

The implementation retains official CAP source evidence independently from Nautiq scientific diagnostics. The WMO registry identifies NDMA India's English RSS endpoint: [authority registry](https://alertingauthority.wmo.int/authorities.php?recId=331). Conditional retrieval follows NDMA's [mandatory ETag integration guide](https://sachet.ndma.gov.in/docs/Integration_Guide_For_Agencies.pdf). Message identities, references, validity and coordinate order follow [OASIS CAP 1.2](https://docs.oasis-open.org/emergency/cap/v1.2/CAP-v1.2-os.html).

`ml/nautiq_ml/advisories/` provides strict bounded UTF-8 XML/RSS parsing, allowlisted HTTPS requests without redirects, verified ETag caches, retained 200/304 receipts, original raw bytes, frozen feed reports and calculation manifests. A 304 requires reconstructable cached bytes. DTDs/entities, duplicate identities in an index, unsafe URLs and oversized/truncated input are refused. The adapter limits an index to 128 items, individual CAP to 1 MiB, an index to 4 MiB, retained input to 32 MiB and one poll to 300 seconds plus its bounded in-flight request. Sources are polled explicitly by default; `--watch` repeats every 15 minutes. The separate non-root readonly `advisory-worker` has a 512 MiB/one-CPU budget.

Schema 12 adds feed runs, immutable message variants, run membership, geometry projections, request cache and source health. Objects stage before one SQL transaction publishes revisions, health and an idempotent `advisory.feed.checked` outbox event. Interrupted publication cannot advance the source projection. A successful empty index and a failed request both retain previously observed messages. Replay re-parses the pinned raw messages with the recorded parser, runtime, policy and as-of time; it does not renew freshness. Maintenance checks first-run and current-run report/raw/calculation/membership/geometry mirrors and can restore availability when exact bytes are restored.

Every CAP language block and warning area is retained. CAP latitude/longitude pairs become WGS84 longitude/latitude. Valid polygons are retained exactly; circles remain geodesic center/radius evidence. Unmapped place names/geocodes, invalid or dateline-ambiguous polygons, missing expiry and incomplete classification remain unresolved. Effective time defaults only as CAP specifies, to issue time; expected onset is separate. Expiry is never invented. Test/private/exercise messages stay visible but do not become operational warnings.

Lifecycle resolution uses exact sender/identifier/sent references, same sender, increasing issue time and usable public/actual updates or cancellations. Missing parents and identity conflicts remain unresolved. An incomplete update cannot erase an earlier warning. Resolution is independent of arrival order. Disappearance never implies cancellation.

The Go API exposes `/api/v1/advisories`, `/advisories/{id}` and `/advisories/state`. Snapshot reads verify frozen reports, original receipts, calculation objects and parsed revision mirrors before interpreting them. Point intersections derive geometry from the verified frozen documents through PostGIS, preventing mutable geometry projections or publication races from altering a verdict. Work is bounded to 4,000 retained revisions, 64 ancestry reports, 32 MiB of unique raw input and the shared eight-second request deadline. Exceeding a bound returns unavailable evidence, never an empty all-clear. The [OpenAPI contract](../packages/schemas/advisories.openapi.json) specifies strict parameter handling.

The `/advisories` UI presents independent source transport, checked time, age, integrity and completeness; retained agency bulletins and original validity/revision details; a polygon inspection layer and keyboard-accessible table; and an explicit location/time query. Circles have exact center/radius text. Missing geometry is not guessed. Desktop/mobile inspection and the location form were exercised with real CAP data, with no browser errors or horizontal page overflow.

## Measured evidence and approval boundary

[Retained pilot summary](evidence/phase10-summary.json) records exact feed run/calculation/hash and receipt counts. The first real run parsed 99 bulletins. This feed's retained sample supplies no polygon/circle coverage; place names and geocodes remain unresolved. Later CAP updates commonly reference parents outside this sampled index. These facts are visible rather than converted into no-warning claims.

NDMA transport is separately labeled healthy/stale/partial/failed. INCOIS machine access is unconfigured. Marine geographic completeness, cadence and redistribution review remain unverified for both. `advisory_diagnostics` reports local evidence availability; `official_advisories` and `trip_assessment` remain false. A relevant, valid, geometry-supported official warning dominates unknown conditions from another source. Otherwise unknown remains unknown. The current catalog cannot return approved `known_none_intersecting`.

## Verification and operation

```sh
docker compose build advisory-worker
make migrate
make advisory-refresh
make advisory-verify RUN_ID=<retained-run>
make advisory-replay RUN_ID=<retained-run>
make advisory-maintain
make phase10-verify phase10-reliability phase10-smoke
```

Offline contracts exercise CAP coordinate order, geodesic circle representation, unknown validity, invalid polygons, all language blocks, public/test scope, exact update/cancel identity, out-of-order arrival, conflicts and hostile XML/URLs. Disposable SQL/real object-store checks exercise verified conditional 304, cache damage without refetch, immutable replay, report/membership/geometry corruption, recovery, rollback, outbox uniqueness and empty/failed feed retention. Real-source smoke checks cover archive/detail/state responses, strict query bounds, capability separation and server-rendered pages. Standard lint, race tests, builds and fresh/legacy/checksum/rollback migration checks pass.

No warning delivery, saved user state, vessel limits, scientific approval or production cadence is implied by this local delivery.
