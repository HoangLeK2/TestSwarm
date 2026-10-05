# AI Device Lab production operations runbook

Status: `UNVALIDATED`. This runbook defines the rehearsal and evidence format. It does not assert that production capacity, alert delivery, restore, rollback, or the 12-device day has passed.

## Release inputs

The operations owner must sign one immutable target version before a rehearsal. The target must record:

- supported concurrent campaigns, devices, jobs per minute, and artifact bytes;
- API p95 and dispatch-lag p95 SLOs;
- database and object-store RPO/RTO;
- alert owner, escalation reference, and on-call window;
- build commit, schema version, worker/relay protocol versions, and config references.

The application stores these values through `OperationalTarget`. A later change uses a new version; reusing a version with different values is rejected. Do not put credentials, webhook secrets, encryption keys, raw account identities, or signed URLs in the target or evidence log.

## Preflight and deployment

1. Record the source commit and verify the working tree used to build the release.
2. Export the backend OpenAPI schema, regenerate the frontend client, then run typecheck and the AI Device Lab backend/browser suites.
3. Record the migration list and checksum. Applied migration bytes are immutable; fixes use a new migration.
4. Confirm that liveness and readiness endpoints are distinct. Readiness must block new starts when encryption, payment provider, private object storage, worker, or relay is unavailable.
5. Deploy the API, worker, and relay with compatible protocol versions. Record image/build identifiers and schema version from the running environment.
6. Run one tenant-scoped draft/readiness request. A dependency failure must leave `started_at` null and create no dispatch intent.

Required evidence: commands and exit codes, environment name, build/image IDs, schema version, endpoint responses with secrets removed, and the operator/time that performed the check.

## Alert rehearsal

Trigger one controlled failure at a time for database, queue/worker, object storage, relay, and payment provider. For each trigger record:

| Field | Required value |
|---|---|
| Target version | Signed operational target version |
| Dependency | One dependency only |
| Started/recovered at | UTC timestamps |
| Observable behavior | Readiness state, blocked reason, queue/dispatch behavior |
| Alert evidence | Alert ID and delivery timestamp; no credential or payload body |
| Owner/action | Acknowledging operator and runbook action |
| Result | `PASS`, `FAIL`, or `BLOCKED` |

An alert rule existing in config is not a pass. The owner must receive and acknowledge the alert. Never turn `unknown` or an undelivered alert into `PASS`.

## Campaign drain, cancellation, and expiry

- Cancellation and due-date expiry first stop future slots.
- Active run attempts keep the lifecycle operation at `awaiting_run_drain`.
- After all active attempts become terminal, retry completion with the same operation ID.
- Completion revokes unexpired job secret capabilities, closes current lane assignments, and releases active/draining/pending reservations.
- Expiry before `end_at` is rejected. Replaying the same idempotency key with different actor, campaign, or reason is rejected.
- If relay or storage is unavailable, keep the operation pending and the reservation non-reusable until drain evidence exists.

After release, run the Approved Device Target hygiene protocol. A failed reset or missing readback evidence quarantines the physical device or emulator instance; it cannot enter a new reservation.

## Backup and restore rehearsal

1. Freeze the rehearsal cutoff and record database transaction time, object manifest hashes, order/entitlement counts, slot/attempt counts, and report hashes.
2. Create the database backup and private-object backup using authorized key access. Store only private evidence references in this report.
3. Restore into an isolated environment with outbound provider callbacks and device dispatch disabled.
4. Reconcile tenant counts and exact hashes for payment history, quota ledger, slots/attempts, evidence manifests, reports, lifecycle operations, and KPI/acceptance snapshots.
5. Measure backup cutoff to latest restored record for RPO, and restore start to verified readiness for RTO.
6. Mark `FAIL` on any missing row/object, hash change, cross-tenant visibility, or unmeasured interval.

## Rollback rehearsal

Run rollback with a pending outbox item, an accepted payment inbox event, an active claim, and a draining campaign. Verify:

- replay produces one durable intent/grant and does not duplicate a charge or job;
- old API/worker versions understand the active schema, or forward recovery is used;
- accepted payment, quota, attempt, evidence, and report history remains present;
- active commands drain before release and secret capabilities remain scoped/revocable;
- the previous build becomes ready within the signed RTO.

Record before/after build IDs, row counts, operation checkpoints, timings, and the final reconciliation query references.

## Capacity rehearsal

Use the signed capacity as the load profile. Measure API p50/p95/p99, dispatch-lag p50/p95/p99, queue depth, claim age, terminal outcomes, upload failures, provider reconciliation lag, report latency, worker/relay saturation, and database pool usage. Run the permitted 12-Approved-Device-Target day separately and retain device/runtime evidence. Synthetic request load cannot replace device-target execution or 14-day evidence.

Stop the rehearsal when isolation, billing idempotency, secret scoping, or device control safety fails. Performance results above the signed target are `FAIL`; missing measurements are `BLOCKED`.

## Incident handoff

Every incident record needs environment/build/schema, tenant-safe correlation IDs, first symptom, affected campaigns, dependency state, mitigation, recovery time, reconciliation result, owner, and follow-up. Redact credentials, raw account identity, request bodies, signed URLs, and provider payloads.

The production gate stays closed until an independent operator/QA reviewer signs AC1–AC5 in `ADL-21-production-operations.md` with alert receipts, restore/rollback evidence, load results, and the 12-device run.
