---
title: "Agent-Boot Command Latency Optimization"
description: "Reduce cloud-to-agent command latency during scenarios by removing control-path blocking, isolating maintenance work, and cutting redundant u2 XML dumps."
status: in_progress
priority: P0
effort: 18h
branch: TBD
tags: [performance, relay, agent-boot, control-plane, u2, scenario]
created: 2026-06-02
---

# Agent-Boot Command Latency Optimization

## Overview

Scenario orchestration stays in `device_farm` cloud/backend. `agent-boot` remains a primitive executor for ADB, u2, atx-agent, scrcpy, and bootstrap commands. The optimization target is the command delivery and execution path, not moving scenario logic to the edge.

The current problem is not raw ADB or gRPC baseline latency. The observed path can become slow because long operations such as bootstrap, restart, u2 recovery, and XML hierarchy dumps share blocking command paths with interactive actions.

## Current Evidence

- `agent-boot` connects to backend over gRPC and registers relay-visible serials.
- Scenario steps that touch the device are sent from backend to `agent-boot` as primitive commands or u2/a11y-style requests.
- XML hierarchy is effectively u2/atx based in the current code path, even when called through the `a11y_query("dump_hierarchy")` naming.
- `AgentControlClient` reads control messages and awaits command execution inline before reading the next command.
- Backend auto-bootstrap runs when relay devices come online and can share the same relay command path as user/scenario operations.
- Repeated XML refresh calls can cause avoidable u2 round trips.

## Non-Goals

- Do not move full scenario execution or `ui_flow` logic into `agent-boot`.
- Do not replace u2 XML dumping with a new AccessibilityService implementation in this plan.
- Do not redesign public APIs before internal latency evidence exists.
- Do not merge WebSocket and gRPC transport behavior into one large refactor.

## Target Architecture

```text
device_farm scenario engine
  -> primitive device operation
  -> relay command gateway
  -> agent-boot control reader
  -> per-device scheduler
       lane: interactive
       lane: maintenance
       query coalescing: dump_xml
  -> primitive executor
  -> async result / latency trace
```

Key rule: maintenance work must not create head-of-line blocking for interactive scenario commands.

## Phases

| # | Phase | Status | Effort | Link |
|---|-------|--------|--------|------|
| 1 | Latency Instrumentation | Implemented | 3h | [phase-01-latency-instrumentation.md](./phase-01-latency-instrumentation.md) |
| 2 | Agent-Boot Control Scheduler | Implemented | 5h | [phase-02-agent-boot-control-scheduler.md](./phase-02-agent-boot-control-scheduler.md) |
| 3 | Bootstrap And Recovery Isolation | Planned | 4h | [phase-03-bootstrap-recovery-isolation.md](./phase-03-bootstrap-recovery-isolation.md) |
| 4 | XML Dump Coalescing And Cache | In Progress | 4h | [phase-04-xml-dump-coalescing-cache.md](./phase-04-xml-dump-coalescing-cache.md) |
| 5 | Scenario Regression Benchmarks | Planned | 2h | [phase-05-scenario-regression-benchmarks.md](./phase-05-scenario-regression-benchmarks.md) |

## Design Decisions

1. Keep scenario state in backend.
2. Keep `agent-boot` primitive and observable.
3. Add timing before behavior changes.
4. Start with two lanes only: `interactive` and `maintenance`.
5. Treat XML dump as a query with coalescing/cache, not as an interactive action.
6. Preserve same-device mutate ordering for tap/type/key/swipe.
7. Do not let auto-bootstrap/recovery run in front of scenario commands.

## Key Files

- `/Users/hoangle/farm/device-farm/agent-boot/relay/control_client.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/agent.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/runtime.py`
- `/Users/hoangle/farm/device-farm/device_farm/runtime/transports/agent_control_servicer.py`
- `/Users/hoangle/farm/device-farm/device_farm/runtime/transports/adb_relay_server.py`
- `/Users/hoangle/farm/device-farm/device_farm/runtime/core/device_client.py`
- `/Users/hoangle/farm/device-farm/device_farm/web/server.py`
- `/Users/hoangle/farm/device-farm/device_farm/tasks/scenario_task.py`

## Required GitNexus Gate

Before editing any function/class/method symbols, run GitNexus impact analysis for the target symbol and record the blast radius. This session did not expose GitNexus tools, so implementation must either run the MCP tools in a session where they are available or use the documented CLI/index workflow first.

## Validation Commands

```bash
cd /Users/hoangle/farm/device-farm/agent-boot
uv run pytest relay/tests/test_grpc_client_tls.py relay/tests/test_fair_send_queue.py relay/tests/test_u2_session_pool.py
uv run python -m py_compile relay/control_client.py relay/agent.py relay/runtime.py

cd /Users/hoangle/farm/device-farm/device_farm
uv run pytest tests/test_agent_control_servicer.py tests/test_a11y_relay_api.py tests/test_relay_agents_routes.py
uv run python -m py_compile runtime/transports/agent_control_servicer.py runtime/transports/adb_relay_server.py runtime/core/device_client.py web/server.py
```

## Success Metrics

- Interactive command accepted latency p95 under 100ms when relay is connected.
- Interactive command queue wait p95 under 250ms while bootstrap/restart is pending.
- XML refresh storm coalesces to at most one active u2 dump per device.
- Scenario step latency improves without moving scenario logic into `agent-boot`.
- No regression in relay registration, bootstrap, restart, u2 batch, or scrcpy attach.

## Open Questions

- Should `shell` default to interactive or maintenance? Decision: keep all `shell` commands in the per-serial foreground lane to preserve scenario ordering; only bootstrap/restart commands run as maintenance.
- Should XML cache TTL be global or per caller? Recommendation: default per device with request override.
- Should current public APIs wait for final command result? Recommendation: yes initially; internal transport can still emit accepted/result timings.
