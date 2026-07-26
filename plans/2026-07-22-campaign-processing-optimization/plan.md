---
title: "Campaign Processing Optimization Plan"
description: "Measure and optimize the 120-phone campaign path from dispatch through Temporal execution, event publication, and finalization."
status: pending
priority: P1
effort: 7-11d
branch: fix/stream-ui
tags: [performance, backend, database, temporal, observability, critical]
created: 2026-07-22
---

# Campaign Processing Optimization Plan

## Overview

Optimize the real campaign path at the current 120-phone target without changing campaign semantics. The order is deliberate: make the complete path measurable, bring database connection demand inside a safe budget, remove event publication from the activity hot path, reduce dispatch transactions and round trips, then isolate control work only if measurements still show queue starvation.

Target flow:

`HTTP dispatch -> snapshot/claim transaction -> commit -> bounded Temporal start -> metadata update -> device activities -> transactional event outbox -> existing outbox poller/SSE -> campaign finalization`

## Evidence Behind the Order

- Current configured app-side theoretical maximum is 174 database connections: web `15+15`, plus 6 workers each with activity pool `12+12`; this excludes Temporal's own connections.
- The local running PostgreSQL snapshot on 2026-07-22 had `max_connections=100` and 89 active/idle sessions. Production must be measured separately.
- A campaign-device execution commonly emits 77-99 events; step event emission currently performs inline outbox processing.
- `CampaignDispatcher.fan_out()` claims devices sequentially, and the API starts Temporal workflows before the dispatch transaction commits.
- Six workers with 20 activity slots provide exactly 120 slots while long device actions and finalization/control activities share capacity.
- Existing metrics cover only part of dispatch, and the defined Prometheus endpoint is not currently exposed.

## Non-goals

- Do not tune scenario waits, selectors, Facebook comment budgets, or device actions until step timing proves they dominate.
- Do not increase worker concurrency, batch size, or PostgreSQL limits blindly.
- Do not change frontend behavior or campaign business semantics.
- Do not run production write-load tests without operator approval.

## Phases

| # | Phase | Status | Effort | Depends on | Link |
|---|---|---|---|---|---|
| 1 | Baseline and observability | Pending | 1-1.5d | - | [phase-01](./phase-01-baseline-observability.md) |
| 2 | Database connection budget | Pending | 1-1.5d | 1 | [phase-02](./phase-02-database-connection-budget.md) |
| 3 | Outbox hot-path removal | Pending | 1-2d | 1, 2 | [phase-03](./phase-03-outbox-hot-path.md) |
| 4 | Dispatch transaction and round trips | Pending | 2-3d | 1, 2 | [phase-04](./phase-04-dispatch-transaction-roundtrips.md) |
| 5 | Worker capacity isolation | Conditional | 1-2d | 2-4 | [phase-05](./phase-05-worker-capacity-isolation.md) |
| 6 | Production-shaped verification and rollout | Pending | 1d | 1-5 | [phase-06](./phase-06-production-verification-rollout.md) |

## Success Criteria

- Zero database pool timeout or `too many clients` errors at 20, 60, and 120 concurrent campaign devices.
- PostgreSQL peak usage stays below 85% of `max_connections`, with at least 15 connections reserved for administration/recovery unless production policy sets a stricter limit.
- Dispatch endpoint p95 is at most 5 seconds at 120 devices and improves at least 30% from the measured baseline; record both the HTTP total and internal phases.
- Temporal schedule-to-start p95 is below 2 seconds for device activities and below 1 second for finalization/control work.
- Oldest unpublished event age p95 is below 2 seconds; concurrent pollers do not claim the same row.
- Last-device-complete to campaign-terminal p95 is below 2 seconds.
- Cancellation, retry, fallback, sequential promotion, SSE ordering, and result aggregation remain correct.

## Required Engineering Gates

- Capture a repeatable baseline before optimizing and store raw JSON with environment metadata.
- Run GitNexus `impact(..., direction: "upstream")` before editing every named symbol; stop and warn on HIGH or CRITICAL risk.
- Verify Temporal/PostgreSQL configuration names against primary documentation before changing infrastructure settings.
- Add focused unit/integration tests per phase and a production-shaped real PostgreSQL + Temporal harness for 20/60/120 devices.
- Run GitNexus `detect_changes({scope: "compare", base_ref: "main"})` before commit or PR.

## Rollout Order

Ship observability first. Then deploy database-budget safeguards, outbox changes, and dispatch changes separately so each effect is attributable and reversible. Implement phase 5 only if phase 4's 120-device run still violates finalization/control schedule-to-start targets.
