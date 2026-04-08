---
title: "u2 Agent-Boot Batch Executor"
description: "Move uiautomator2 execution logic into agent-boot to reduce chatty gRPC round-trips via batch commands and named flows"
status: pending
priority: P1
effort: 12h
branch: feat/agent-boot
tags: [backend, performance, grpc, uiautomator2]
created: 2026-04-08
---

# u2 Agent-Boot Batch Executor

## Problem

Every uiautomator2 operation currently round-trips through the bidirectional
gRPC relay stream: `device_farm → ControlMsg(u2_request) → agent-boot →
urllib HTTP → atx-agent:7912 → JSON-RPC → uiautomator2:9008`. A single
high-level action such as `tap_selector()` translates into **three** such
round-trips (`find_element` + `element_click`, plus a reconnect/retry path).
Over a WAN relay link, every extra RTT is ~50–200 ms of latency per UI step.

## Goal

Push execution of uiautomator2 action sequences down into `agent-boot` so that:

1. A batch of N primitive actions executes in a single gRPC round-trip.
2. Common high-level flows (find+click+wait, scroll-search, input+confirm)
   run entirely on the device-side host, returning one aggregated result.
3. agent-boot holds a persistent `uiautomator2` Python session per device,
   skipping per-call HTTP setup.

## Non-Goals

- No changes to `relay.proto` — batch/flow messages ride the existing
  `ControlMsg`/`AgentMsg` JSON envelope (`is_json=true`, discriminated by
  `type` field).
- No new gRPC service / no new port.
- No removal of `u2_request` — it remains the escape hatch for one-off calls.

## Target Architecture

```
device_farm (batch intent)
  → BatchRequest {serial, actions:[...]}
  → ControlMsg(type="u2_batch", id)
  → agent-boot U2SessionPool.get(serial) → u2.Device
  → U2Executor.run_batch(actions) [sequential, early-exit on error]
  → AgentMsg(type="u2_batch_result", id, results:[...])
  → device_farm
```

```
device_farm (named flow)
  → FlowRequest {serial, flow, params}
  → ControlMsg(type="u2_flow", id)
  → agent-boot FlowExecutor.run(flow, params)
  → AgentMsg(type="u2_flow_result", id, ok, value, error)
```

## Phases

| # | File | Deliverable | Effort |
|---|------|-------------|--------|
| 01 | [phase-01-u2-session-pool.md](./phase-01-u2-session-pool.md)       | Persistent u2 session pool in agent-boot | 2.5h |
| 02 | [phase-02-batch-executor.md](./phase-02-batch-executor.md)         | `u2_batch` dispatcher + primitive ops    | 3.0h |
| 03 | [phase-03-flow-executor.md](./phase-03-flow-executor.md)           | Named flows (find_click_wait, etc.)      | 2.5h |
| 04 | [phase-04-device-farm-integration.md](./phase-04-device-farm-integration.md) | Client-side batch/flow API + `tap_selector` migration | 2.5h |
| 05 | [phase-05-testing.md](./phase-05-testing.md)                       | Unit tests + latency validation          | 1.5h |

## Success Criteria

- [ ] `tap_selector()` observed latency drops from 3 RTT to 1 RTT
      (measure on WAN with 80 ms RTT: expect ≥150 ms improvement per call).
- [ ] Existing `u2_request` path still works (backward compat regression test).
- [ ] Session pool survives device OFFLINE → ONLINE transitions.
- [ ] Batch early-exit returns partial results with clear error index.
- [ ] All new unit tests pass; no regressions in existing agent-boot tests.

## Risks

| Risk | Mitigation |
|------|------------|
| `uiautomator2` Python lib pulls heavy deps into agent-boot | Pin minimal extras; lazy-import inside pool module |
| Persistent sessions leak on crash | LRU eviction (300 s idle) + eviction hook on device OFFLINE |
| Batch action schema drift between client/agent | Version the envelope via `"schema": 1` field; reject unknown ops |
| Early-exit semantics mismatch caller expectation | Document explicitly; return `stopped_at` index in error result |
| agent-boot older than batch feature | Client falls back to legacy path on 30s timeout, logs WARNING once |

## Rollout

1. Land phases 01–03 behind a feature flag (`U2_BATCH_ENABLED=false` default).
2. Land phase 04 client-side; `tap_selector` checks flag, falls back to legacy.
3. Flip the flag in staging; measure latency for 24h.
4. Enable in production; keep legacy path for 1 release, then delete in a
   follow-up plan.
