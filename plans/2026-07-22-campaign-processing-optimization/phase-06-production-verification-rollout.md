# Phase 6: Production-shaped Verification and Rollout

## Objective

Prove the improvements under a real PostgreSQL + Temporal topology at 20, 60, and 120 devices, then release one behavior change at a time with observable rollback points.

## Test Matrix

| Stage | Devices | Purpose | Required result |
|---|---:|---|---|
| Warm-up | 20 | Cache/process warm-up | No assertions used for final comparison |
| Baseline | 20, 60, 120 | Old behavior under same environment | Raw JSON retained |
| Candidate | 20, 60, 120 | Phase-by-phase comparison | All correctness and capacity gates pass |
| Canary | 10 then 30 | Limited real campaign scope | No errors or metric regressions |
| Ramp | 60 then 120 | Target production capacity | Success criteria sustained across repeated runs |

## Tasks

- [ ] Record environment shape: git SHA, compose/deployment revision, PostgreSQL and Temporal topology, pool/concurrency settings, device/probe mode, and background load.
- [ ] Run each load level at least twice after warm-up; report p50/p95/p99 and raw counts, not averages alone.
- [ ] Compare HTTP dispatch, database wait/connections, SQL count, transaction duration, Temporal schedule-to-start, activity duration, outbox age, event delivery, terminal lag, and failures.
- [ ] Exercise cancellation during dispatch, partial device claims, worker restart, outbox publisher failure, Temporal start failure, all devices busy, sequential promotion, and DLQ paths.
- [ ] Run focused unit/integration suites plus `/api/live`, `/api/health`, and the exact campaign API/SSE surfaces.
- [ ] Run security checks for the metrics endpoint and dependency audit appropriate to changed packages.
- [ ] Run GitNexus `detect_changes({scope: "compare", base_ref: "main"})` and review staged, unstaged, and untracked changes before commit.
- [ ] Rebuild/recreate affected containers before live verification so results use the candidate code.
- [ ] Publish a before/after report with any target misses explicitly called out.

## Acceptance Gates

- [ ] Zero pool timeouts, `too many clients`, lost events, duplicate row claims, or incorrect terminal states.
- [ ] Database peak below 85% with the configured recovery reserve intact.
- [ ] Dispatch p95 at most five seconds and at least 30% faster than baseline at 120 devices.
- [ ] Device activity schedule-to-start p95 below two seconds.
- [ ] Finalization/control schedule-to-start p95 below one second.
- [ ] Oldest unpublished event age p95 and last-device-to-terminal p95 below two seconds.
- [ ] No material regression in cancellation, retry, fallback, sequential execution, SSE, or campaign result correctness.

## Deployment and Rollback

1. Deploy observability only and validate signal quality.
2. Deploy connection-budget configuration/safeguards.
3. Canary outbox hot-path removal; restore inline mode only via the temporary rollout flag if needed.
4. Deploy dispatch transaction changes separately.
5. Deploy control-queue isolation only if its decision gate was triggered.
6. Hold each step long enough to cover normal and peak campaign traffic.

Rollback the most recent phase, retain its telemetry, and preserve persisted execution/outbox data. Do not delete or rewrite failed campaign history during rollback.

## Final Deliverables

- Reproducible harness command and configuration.
- Raw baseline/candidate JSON plus concise comparison report.
- Capacity/runbook document for 120 phones.
- Dashboard and alerts for pool pressure, Temporal queueing, outbox lag, dispatch latency, and terminal lag.
- GitNexus impact and change-scope evidence attached to the implementation review.
