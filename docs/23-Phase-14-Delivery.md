# Production operations delivery

Blueprint section 17 is implemented as executable deployment, incident and recovery controls. This is a local implementation delivery. Public production and scientific approval remain false; an external security, scientific and legal review cannot be manufactured by automated checks.

## Delivered controls

| Requirement | Implementation and acceptance |
| --- | --- |
| Authentication | Existing Argon2 accounts, hashed sessions, ownership checks, exact-origin CSRF, version/idempotency fences and deletion remain enforced. HTTPS web sessions use `__Host-nautiq_session`, Secure, HttpOnly, SameSite=Lax, Path=/ and no Domain. Recovery and public identity abuse review remain external gates. |
| TLS and private networking | Production Compose overlay exposes only the certificate-backed Caddy gateway. PostgreSQL, storage, broker, caches, MLflow, metrics and RPC have no host ports. Default backend network is internal; selected acquisition services have explicit egress. Certificates are supplied and verified, TLS 1.2/1.3 only. This is a trusted single-host deployment, not service mTLS across untrusted hosts. |
| Secrets and privilege | Bounded `_FILE` loaders reject conflicts, empty/invalid files and development credentials in production. Separate app, worker, operator, migration/backup and object-store identities; SQL RLS prevents the app writing scientific calculations. Private host directories protect files readable by different container UIDs. No runtime administrator mutations are exposed publicly; the operator release-lock function has restricted execution and a fixed search path. |
| Backup/restore | Coordinated writer shutdown, exported repeatable-read SQL snapshot and complete stable object inventory. Streaming authenticated AES-256-GCM archive; encrypted manifests include SQL counts/migration pins and every object checksum. Restore accepts only new isolated database/bucket names, verifies before extraction/use and copies/rehashes all objects. Restored sessions/grants are revoked and serving/writes/delivery are paused. Live targets are never replaced automatically. |
| Source health/status | `/status` and bounded `/api/v1/operations/status` show selected field cycles, source-age flags, integrity, authority transport/check time, worker heartbeat and incident scopes. Missing controls/SQL evidence becomes unavailable. Connection health and source transport never establish forecast accuracy, advisory completeness or safe conditions. |
| Scientific kill switches | Schema 16 stores revision-fenced scopes and append-only operator audit. Public serving gates fail closed on missing/corrupt controls. Trips, map layers, research filters and aggregate conditions respect dependency pauses. Notification claim/publication and email claim/delivery honor pauses without consuming queued attempts; a pause between claim and send returns the unattempted lease once. |
| Model rollback | Explicit retained UUID and expected control revision. Pause science first; verify complete current-compatible immutable model lineage; atomically replace the selected parent chain under the canonical lock, remove incompatible descendants and invalidate/requeue comparisons. Failure keeps science paused. No refitting or automatic resume. |
| Observability | Structured API logs include generated correlation ID, registered route template, status and duration. W3C trace context propagates to outgoing RPC; internal Prometheus counters/durations and queue/control/worker gauges have bounded labels. No bodies, credentials, queries, coordinates or raw user paths in HTTP telemetry. Metrics remain private. |
| Incident runbooks | [Deployment and recovery runbook](24-Operations-Runbook.md) covers source outage, corruption, rollback, mail/identity incidents, backup restoration, credential rotation and evidence ownership. |
| Accessibility | Semantic status tables, captions, header scopes and focusable labeled scroll regions; skip link now transfers focus to content. Visible focus indicators and labeled forms remain. Maps with evidence links expose a labeled group instead of flattening links inside an image role. Automated browser checks and manual keyboard/mobile checks are recorded in the acceptance evidence. This does not replace an independent assistive-technology audit. |
| Safety/legal review | [Review register](25-Release-Review.md) records product wording, personal limits, source attribution/redistribution boundaries and named external sign-offs still needed. `production-gate` always refuses promotion under the current policy. |

## Bounded operational behavior

The HTTP layer allows 64 concurrent requests, caps headers at 16 KiB and uses existing read/write deadlines. Control reads have a one-second budget; status and database metrics have two seconds. Backup archives support at most 50,000 objects and 2 GiB, with private on-disk staging; provision sufficient disk for dump, object copy and tar/decrypted copy. The local retained archive exceeds 10,000 objects, which is why the object count ceiling is 50,000. SQL archive commands have a five-minute deadline. Model rollback supports at most 2,000 active profiles; larger installations require a reviewed batching design.

Controls gate new public HTTP work. An already admitted public request can complete within its existing deadline. Notification publication and mail attempts also lock the control row, ordering them against a pause. Private RPC and administrator CLI access are a privileged diagnostic boundary, not public routes. Stop the affected writers/runtimes when complete containment is required. Pausing scientific serving does not change original receipts, source timestamps, frozen policy/code hashes, alert evidence or prior release approvals.

A same-origin application CSP restricts framing, forms, base URLs and objects; it does not claim a nonce-based script policy. Metrics reset on API restart; operators must scrape and retain them privately for incident history. This implementation supplies correlation and aggregate instrumentation, not a hosted tracing backend or a production monitoring SLA.

## Reproducible verification

```sh
make operations-setup
make migrate
make lint test build test-migrations
make phase14-verify
# Build current verifier/runtime images before acceptance.
docker compose build api web notifications notification-verifier operations-verifier operations-tools ml-inference field-service
make phase14-reliability phase14-production
make phase14-restore   # stops currently running local writers briefly; always restarts them
make phase13-reliability
make production-gate # expected exit 2: external release gates are unproven
```

The HTTPS verifier creates a separate Compose project with synthetic credentials and a disposable certificate, migrates and provisions fresh volumes, exercises the actual web/API path, verifies restricted SQL/object-store access, restores that provisioned schema with its RLS role references and restricted function ACLs, and removes its own project. The restore drill encrypts real retained SQL/object data and restores to uniquely named targets, verifies model rollback there and removes only those targets. It never points the application at restored data. Acceptance results and limits are in [secret-free evidence](evidence/phase14-summary.json).

The Docker [merge specification](https://docs.docker.com/reference/compose-file/merge/) requires Compose 2.24.4+ for the `!reset` overlay. Secret mounts follow [Compose secrets](https://docs.docker.com/reference/compose-file/secrets/). TLS follows the [Caddy TLS directive](https://caddyserver.com/docs/caddyfile/directives/tls). SQL snapshot coordination follows [PostgreSQL pg_dump](https://www.postgresql.org/docs/17/app-pgdump.html); authenticated decryption completes before use as required by the [cryptography GCM interface](https://cryptography.io/en/latest/hazmat/primitives/symmetric-encryption/).

Accessibility checks use [W3C WCAG guidance](https://www.w3.org/WAI/WCAG22/Understanding/). Automated overflow/offscreen contrast checks remain incomplete on status, trip, map, field and advisory views; manual computed status text contrast is at least 5.98:1 and focus outline contrast is 3.47:1. These checks are a bounded local pass, not full WCAG certification.
