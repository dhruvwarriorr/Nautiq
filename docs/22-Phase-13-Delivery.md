# Alerts and notifications delivery

Blueprint section 16 is implemented with a private evidence inbox, a durable evaluator and in-app/email delivery. Personal limits remain preferences; scientific alert promotion, complete marine advisories, safe-trip claims and public production approval remain gated.

## Delivered behavior

- Owned enabled rules evaluate personal wave/wind/current limits, relevant official authority references or stale source cycles/transport. Points, radii, named locations, polygons and saved timed routes use existing native fields and PostGIS geography. Route legs/stops intersect authority geometry only during warning validity; already traversed legs are excluded and expired routes are never silently rescheduled.
- Rule/watchlist/route versions and selected source revisions are checked again during publication. Every evaluation freezes original input, observation, previous lifecycle state, policy/code hashes and exact field response bytes. Frozen lifecycle replay never refreshes sources or substitutes new observations.
- First triggers create `new` evidence. Repeated source revisions deduplicate; changed evidence respects a configurable 1–1,440 minute cooldown (omitted or API value zero selects the 60-minute default). Higher severity escalates immediately. Official replacements update immediately; verified cancellation/supersession creates a correction linked to the earlier alert without erasing evidence or asserting recovery.
- Recovery requires two distinct positive fresh observations at least 60 seconds apart. Missing, stale, failed or incomplete favorable evidence interrupts confirmation and leaves the episode active. Partial fresh evidence can establish an exceedance. Recovery of source transport does not establish complete warning coverage or safe conditions.
- The inbox retains evidence, acknowledgements, correction links and delivery outcomes. Newest-first owner-bound signed pagination holds a snapshot during navigation; first-page refresh runs every 30 seconds. Worker health and per-rule evaluation times distinguish configured rules from actual monitoring.

## Durable delivery and privacy

Schema 15 adds fenced evaluator state, frozen evidence, channel deliveries, worker health and notification recipient proofs. The default non-root/read-only `notifications` Compose service targets evaluation every 60 seconds with 90-second leases; one rule per tick bounds work. This is a local bounded scheduler, not a guaranteed latency SLA under backlog. API health still reports its own dependencies separately from notification worker health.

In-app delivery publishes transactionally with alert evidence. Email queues pin recipient verification/version, original evidence and owned rule versions. Opt-out, account deletion, changed rules/routes/watchlists, replaced recipient proofs, superseded alerts or corrupt evidence prevent queued attempts/retries. An account lock orders these mutations against in-flight SMTP acceptance. Inbox evidence remains available when notifications are opted out.

Email requires explicitly configured SMTP and a separately verified recipient. A random account-bound 15-minute proof is delivered to that address; only its SHA-256 is stored. Proofs have five guesses, request/verification quotas and idempotent mutation replay. Email verification is not sign-in identity or account recovery. Removing a recipient invalidates pending proofs and queued deliveries. Verification mail requests are synchronous and fail atomically if transport fails; users can request another proof.

Production transport requires certificate-verified STARTTLS or implicit TLS. Plaintext is allowed only to a literal loopback test collector, without authentication. Emails contain a generic private inbox link and no forecast measurements, bulletin text or private coordinates. SMTP attempts have an eight-second deadline, five automatic attempts and 60/120/240/480-second retry intervals. Explicit retry is limited to three requests per alert/day, requires the current latest evidence and rechecks all consent/ownership/recipient conditions. Identical idempotency keys replay the original result without consuming another retry allowance.

SMTP is **at least once**: acceptance followed by a database failure can repeat a message with its stable Message-ID. Local SMTP collector acceptance proves implementation behavior, not public provider deliverability. Push/SMS are not included.

Frozen snapshots are at most 32 KiB with at most 32 source pins; each retained field response is at most 900 KiB. Non-alert evaluation history and unreferenced source bytes purge after seven days in bounded batches. Alert-referenced evidence is retained until account deletion. No archive or unlimited-scale retention claim is made. Account deletion cascades private notification records.

The product policy advances to `product-surfaces-v2`. Existing frozen exports retain their original policy/runtime identity and may need their matching older worker; policy changes do not rewrite or reapprove frozen jobs. Original source releases and prior trip receipts remain immutable.

## Operation and acceptance

```sh
make migrate
docker compose build api web notifications notification-verifier product-verifier trip-verifier export-worker
docker compose up -d api web notifications export-worker
make phase13-verify phase13-reliability phase13-smoke
make lint test build test-migrations
make phase12-reliability phase11-reliability
```

Set `SMTP_HOST`, `SMTP_PORT`, `SMTP_MODE`, `SMTP_FROM` and optional authenticated credentials consistently for API/worker. The checked-in defaults leave email unavailable. Verify worker health and a recipient before enabling email rules; no secrets belong in evidence or version control.

The executable verifier uses disposable PostgreSQL/PostGIS, actual MinIO, synthetic native field RPC responses and a local SMTP collector. It checks lifecycle tables, ownership/CSRF, recipient proof, quota/idempotency, duplicate evaluation, cooldown/escalation, positive recovery, source geometry/time matching, lease/version/source publication fences, rollback, corrupted byte/mirror refusal, mail retry/exhaustion, consent/recipient changes, owner-bound pagination and deletion. These synthetic cases do not prove scientific calibration or real CAP acquisition completeness.

Live retained-source and browser results are recorded in [secret-free acceptance evidence](evidence/phase13-summary.json). Forecast reacquisition, repeated source cadence, marine advisory completeness/rights, external SMTP deliverability and public security/deployment operations remain separate acceptance gates. Historical evidence is preserved in [the previous product delivery](21-Phase-12-Delivery.md).
