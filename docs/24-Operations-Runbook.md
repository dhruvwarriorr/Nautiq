# Deployment and recovery runbook

Use a trusted single host with Compose 2.24.4+, a private administrative shell and restricted Docker access. Docker access is privileged. The production overlay is a deployment template, not an automatic deployment or scientific release. Read the [delivery boundaries](23-Phase-14-Delivery.md) and [release review register](25-Release-Review.md) first.

## Prepare a separate deployment

1. Provision a new host/project and volumes; never apply production credentials to existing local volumes accidentally. Set `COMPOSE_PROJECT_NAME` deliberately. Existing PostgreSQL/MinIO volumes retain their original credentials; changing environment values does not rotate them.
2. Keep host disks encrypted. Create an operator-owned secret directory with mode 0700, outside the checkout/build context. Supply random credentials for `database_password`, `storage_root_user` and `storage_root_password`, and a PEM `tls_cert`/`tls_key` for the real hostname. Use a secret manager to deliver/rotate files; do not paste values into shell history, logs, tickets or Git. Certificate keys must be unencrypted at the mount so the unattended gateway can start; protect the host directory and mount only the gateway's files there.
3. Set non-secret deployment values: `NAUTIQ_SECRETS_DIR`, `PUBLIC_HOST` (certificate hostname without port), `PUBLIC_DOMAIN` (hostname plus external port if nonstandard), `HTTPS_PORT` and `HTTPS_BIND_ADDRESS`. The default bind is loopback. A reviewed public deployment must explicitly set the interface/firewall and validate it from another host. DNS and public certificate issuance remain operator work.
4. Use `COMPOSE_FILE=docker-compose.yml:docker-compose.production.yml` for all commands on Linux/macOS. If email is explicitly configured, append `:docker-compose.mail.yml`, supply `SMTP_HOST`, `SMTP_FROM`, `SMTP_PORT`/`SMTP_MODE` and mounted `smtp_username`/`smtp_password`. Local `.env` values are overridden for production secret keys. Avoid `docker compose config` output in logs: it can expose unrelated environment values.
5. Bootstrap fresh persistence with temporary placeholder app/worker file mounts, start only postgres/redis/nats/minio/storage-init, and apply the ordered migration SQL through the administrator. `scripts/migrate.py` uses the selected Compose project via environment; do not print the generated SQL with private values. Migration scripts contain no passwords.
6. Supply a protected administrator `backup_database_url` (host `postgres`, chosen administrator/database), and run the provisioner with the private directory mounted. It creates distinct SQL app/worker/operator DSNs and object-store IAM identities. It never overwrites credentials/roles. Database and object-store provisioning are separate transactions: after partial failure, inspect created roles/users/policies and recover or rotate explicitly before retrying.

```sh
# After administrator/bootstrap files and schema 16 exist:
docker compose run --rm --no-deps -T \
  -v "$NAUTIQ_SECRETS_DIR:/secure" \
  --entrypoint /opt/ops/bin/python operations-tools \
  -m nautiq_ml.operations.provision /secure/generated
```

Move the generated files into the protected mount directory through the secret manager, keeping its parent 0700. App and worker files may be 0644 inside that parent to accommodate distinct container UIDs. Never give app/notifier containers the administrator, operator or storage-root files. Review `roles.sql` and the storage IAM policies. Reapply reviewed grants after each migration; provisioner role creation is a first-install operation, not an upgrade command.

Build/publish images through your reviewed CI process, then supply a JSON map of every enabled service to `registry/name@sha256:<digest>`. `production_preflight.py` checks complete immutable image locks, secrets, certificate hostname/expiry/key match, private ports/network and app hardening. It creates a new Compose image overlay without starting services. The image map should cover the enabled production services; optional profiled workers need explicit digest locks before use too.

```sh
.venv/bin/python scripts/production_preflight.py \
  --images /private/release-images.json --output /private/release-lock.json
export COMPOSE_FILE="$COMPOSE_FILE:/private/release-lock.json"
docker compose up -d --no-build
```

The preflight checks certificate identity/expiry and key matching. Verify the public trust chain, actual ingress firewall and hostname from the deployment client separately. Run the authenticated application flows, status/health checks and private-port rejection on the actual host before accepting traffic. Keep the original image digests, migration hashes, runtime model UUIDs and approved configuration as protected release evidence. Roll back application images with the prior digest overlay and `--no-build`; never run an old image against an incompatible schema without a tested compatibility plan. Do not automatically downgrade migrations.

## Contain and diagnose an incident

Use generated `X-Request-ID` for HTTP correlation. Private `/internal/metrics` exposes request counts/aggregate durations, queue depth/failures, paused scopes and notification success age. Scrape on the backend network and retain/alert privately; do not route it through the gateway. Suggested alerts: DB metric unavailable, worker success age over 90 seconds, queue failures/backlog growth, unexpected scope pauses, repeated HTTP 5xx, stale source cycles and unavailable authority integrity. These thresholds are implementation defaults, not a response SLA. Assign a named on-call owner and escalation contact before production acceptance.

Use the operator CLI with a separate mounted `operator_database_url`. Reasons are short incident codes; never put private text in them. Query the revision before each mutation and use that exact expected revision. Conflicts mean another operator changed the state; inspect rather than bypassing the fence.

```sh
# Local diagnostic stack (administrator local defaults):
docker compose exec -T api /operations --action status
docker compose exec -T api /operations --action pause --scope science \
  --actor operator_id --reason source_integrity --revision 1
# Production: the app role must fail to pause; mount operator credentials explicitly.
docker compose run --rm --no-deps -T \
  -v "$NAUTIQ_SECRETS_DIR/operator_database_url:/run/secrets/operator_database_url:ro" \
  -e DATABASE_URL_FILE=/run/secrets/operator_database_url \
  --entrypoint /operations api --action status
```

Use the same production invocation with `--action pause|resume --scope <scope> --actor <id> --reason <code> --revision <observed>` for changes. Global `science` pause covers model, field, event, advisory, trip and alert evaluation. `email_delivery` and `product_writes` are separate controls. Resume only a diagnosed scope, after verifying original evidence, current runtime pins and intended downstream behavior. Resuming never grants scientific approval.

| Incident | Immediate containment | Recovery evidence |
| --- | --- | --- |
| Source outage/stale cycle | Pause field sampling (trip/aggregate requests also stop), or science; do not label old data fresh. Stop acquisition if malformed bytes are publishing. | New actual provider receipts, immutable hashes, cycle/valid time, masks and bounded sample verification; cadence/accuracy reviews remain separate. |
| Model/calculation corruption | Pause model inference or science; stop affected workers/runtimes. Preserve damaged evidence privately. | Verify retained raw/model/mirror hashes and policies using matching runtime; perform explicit selection rollback if needed. Never refit or overwrite evidence as a repair. |
| Advisory rights/completeness | Pause advisories; contain public trip/aggregate serving. Preserve authority revision, cancellation and transport evidence. | Authority/rights reviewer approval and real acquisition completeness; healthy RSS transport alone is insufficient. |
| Notification anomaly | Pause notification evaluation and email delivery; stop the notification process for complete containment. | Frozen lifecycle replay with original code, owned rule/source versions and recipient consent. No automatic favorable recovery from missing data. |
| Mail compromise | Pause email delivery and product writes; stop API/notifier if recipient verification transport must stop too. | Rotate SMTP credentials, revoke recipient proofs/queued delivery as necessary, inspect stable Message-ID acceptance and at-least-once duplicates. |
| Identity/session incident | Pause product writes, isolate affected public ingress and stop app writers as required. | Rotate/revoke affected credentials/sessions, ownership and CSRF checks, private retention/notification review. Do not log proofs or passwords. |
| Backup corruption/key loss | Refuse the archive; never restore unauthenticated bytes or overwrite live targets. | Obtain protected original key and verified offsite archive; repeat isolated restore. Lost encryption keys make archives unrecoverable. |

## Model selection rollback

Choose an explicit retained climatology/expected_state/uncertainty/anomaly UUID with complete current-compatible parent artifacts. The rollback command pauses science, verifies lineage and atomically switches the chain. Earlier code/model artifacts may require their matching original image first; current verification refuses mismatched code/dependencies. Do not modify frozen hashes to make an old model load.

Run with the separate operator database DSN and storage worker read credentials mounted into a compatible ML image, never with the API role. The operator role can change incident state, selections/comparison state/jobs and append audit, but cannot alter model artifacts/releases. Supply `DATABASE_URL_FILE=/run/secrets/operator_database_url` and the current control revision.

```sh
# Replace the mount location and UUID explicitly; retain separate secret files.
docker compose run --rm --no-deps -T \
  -v "$NAUTIQ_SECRETS_DIR/operator_database_url:/run/secrets/operator_database_url:ro" \
  -e DATABASE_URL_FILE=/run/secrets/operator_database_url \
  ml-inference python -m nautiq_ml.operations.rollback anomaly RETAINED_UUID \
  --actor operator_id --reason model_integrity --revision OBSERVED_REVISION
```

Record emitted runtime UUID pins, pin/restart the ML service to that exact chain, run model verification and bounded profile inference/comparison checks, inspect status and failed queues, then explicitly resume science. The selection transaction never automatically updates process environment pins or resumes serving. Failed rollback keeps the initial pause and records failure without a partial selection switch.

## Encrypted backups and isolated restoration

Generate a private 32-byte key represented as 64 lowercase hexadecimal characters; store it independently in a managed secret store/key escrow. Use key mode 0600, backup directory 0700, encrypted host disk and enough staging capacity. Keep key IDs/rotation inventory privately, not keys alongside offsite archives. Schedule coordinated backups through the selected production Compose project; all ad hoc/external writers must also be stopped. The wrapper stops only running known writers and restarts them in `finally`; an interrupted host or forced process termination requires manual restoration of the recorded service state.

```sh
.venv/bin/python scripts/backup.py /private/backups --key-file /private/backup.key
# Explicit new targets; never the live DB/bucket:
docker compose run --rm --no-deps -T \
  -v /private/backups:/backup \
  -v /private/backup.key:/run/secrets/backup_key:ro \
  -e BACKUP_KEY_FILE=/run/secrets/backup_key operations-tools \
  restore /backup/EXACT_ARCHIVE.backup \
  --database restore_EXPLICIT_ID --bucket restore-EXPLICIT-ID
```

Only the operator backup tool mounts administrator/root-storage credentials. It is ephemeral and never public. Restore verifies the authenticated archive, SQL row counts/migration hashes and every copied object, revokes sessions/download grants and keeps science/product writes/alert evaluation/mail paused. Failed restores can leave uniquely named partial targets; inspect and remove only those isolated targets. Repeated names are refused.

The current scientific storage implementation pins bucket `nautiq`; an isolated `restore-*` bucket is a verified rehearsal target. For real disaster recovery, first create the source SQL role names as nonprivileged identities on the separate host (the dump preserves RLS policy role references but omits owners/ACLs). Keep their passwords and grants disabled until review. Restore to a separate host/project, copy the verified isolated object set into that project's fresh `nautiq` bucket under the reviewed storage policies, reapply reviewed SQL credentials/grants using its administrator (the restored security-definer row-lock helper has PUBLIC execution revoked; grant it only to the operator), retain paused controls and reverify all retained evidence before changing client ingress. No live DSN, bucket or gateway switch is automatic. Preserve original timestamps; obtain genuinely new sources before claiming freshness. Restored accounts require fresh sign-in; review restored recipient proofs/queued mail before explicit delivery resume.

Copy only encrypted archives to protected offsite storage and verify archive SHA-256 against the operator inventory. Define retention, backup interval/RPO and a tested target-host RTO with the operator; no recovery SLA is claimed. Drill offsite/key-escrow recovery on a separate host regularly. Remove private plaintext staging after every run, including crash leftovers, using host encryption and the approved retention policy. The local acceptance drill is not evidence of offsite durability.

## Rotation and audit

Rotate DB/storage/SMTP credentials through their administrator or secret manager, update only each service's mounted file, recreate affected containers and verify restricted access before revoking old credentials. File replacement alone does not reload process environments. Retain protected change evidence and investigate any credential printed in logs as a leak. Do not reuse the initial provisioner to overwrite existing roles. Rotate certificates before expiry and reverify hostname/trust chain; keep public/private keys matched. Keep prior backup keys until their retained archives expire.

`operations_audit` is append-only to app/worker/operator roles; the administrator can still alter it, so export protected audit evidence to independent retention for production. Record incident owner, times, request IDs, control revisions, immutable source/model/calculation IDs and corrective action. Omit private source contents, routes, addresses, credentials and session proofs from tickets and checked-in evidence.

## Question parsing and model monitoring

* **Model monitoring:** run `make model-monitor` (optional `WINDOW_DAYS`). It is read-only. A flag starts an investigation; do not retrain or recalibrate in response. Rerun after any release selection change; `/models/monitoring` warns when pins differ.
* **Optional language-model parsing:** disabled unless `NAUTIQ_LLM_API_KEY` (or `NAUTIQ_LLM_API_KEY_FILE` in production) is set. Question text is sent to the provider while enabled. To disable during an incident, unset the key and recreate the API; questions fall back to the built-in grammar automatically. The production overlay blanks these variables, so enabling is a deliberate act.
* **Static-feature experiment:** `make static-features-experiment REFERENCE_ID=...` reaches NOAA over HTTPS from the ML runtime and creates no release.
