# Phase 4: Dispatch Transaction and Round Trips

## Objective

Shorten the dispatch transaction, reduce per-device database round trips, and ensure no database row locks remain open while the API waits for Temporal RPCs.

## Target Transaction Boundary

1. Validate campaign and build immutable snapshot.
2. In one bounded database transaction, claim eligible devices and persist execution/link/result rows.
3. Commit claims before external Temporal calls.
4. Start workflows with existing bounded concurrency and idempotent workflow IDs.
5. Persist returned workflow metadata in bulk; reconcile partial start failures safely.
6. Hydrate the API response with one bulk execution query.

## Tasks

- [ ] Run GitNexus impact analysis for the campaign route, `CampaignDispatcher.fan_out`, `_create_device_execution`, device claim service, and `start_execution_runtime`; warn before any HIGH/CRITICAL edit.
- [ ] Measure current SQL statement count and lock/transaction duration per 20/60/120-device dispatch.
- [ ] Preserve device-row lock order and uniqueness guarantees while eliminating redundant per-row flushes.
- [ ] Build execution/link/result objects in chunks and flush per measured chunk rather than once per object.
- [ ] Commit snapshot and claims before starting Temporal workflows.
- [ ] Define an idempotent recovery state for executions claimed successfully but whose workflow start failed; reuse the existing metadata/state model unless evidence requires a migration.
- [ ] Keep the existing bounded Temporal start concurrency until phase-1 timing proves it is a bottleneck.
- [ ] Persist workflow IDs/run IDs in bulk after starts.
- [ ] Replace response-time N+1 execution reloads with the existing bulk-load path or a dedicated bulk query.
- [ ] Preserve all-busy, partial-claim, cancellation, retry, DLQ, fallback executor, and sequential campaign behavior.

## Expected Files

- `device_farm/api/routes/campaigns.py`
- `device_farm/services/campaign/dispatcher.py`
- `device_farm/services/campaign/execution_runtime.py`
- `device_farm/services/device_reserve/service.py`
- `device_farm/db/crud/device_reserve_session.py`
- `device_farm/db/crud/execution.py`
- `device_farm/tests/test_campaign_dispatch_n2n.py`
- `device_farm/tests/test_epic04_execution_runtime.py`
- `device_farm/tests/test_campaign_dispatch_transaction.py`

## Verification

- [ ] Assert no Temporal client call occurs inside an open dispatch database transaction.
- [ ] Test rollback on claim/persistence failure and recovery after partial Temporal-start failure.
- [ ] Test duplicate dispatch/idempotent retry and concurrent claims for the same device.
- [ ] Test response ordering and fields after bulk hydration.
- [ ] Compare SQL count, transaction duration, lock wait, HTTP p50/p95/p99, and failure rate against phase 1.
- [ ] Require p95 at most five seconds and at least 30% improvement at 120 devices, unless an agreed business SLA is stricter.

## Exit Gate

The 120-device dispatch has bounded SQL/transaction time, releases claims before Temporal RPCs, and passes correctness tests for every partial-failure boundary.
