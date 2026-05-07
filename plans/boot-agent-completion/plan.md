---
title: "boot-agent: Completion Plan"
description: "Finish the remaining work to ship feat/boot-agent to main"
status: completed
priority: P1
effort: 10h
branch: feat/boot-agent
tags: [backend, android, grpc, frontend]
created: 2026-04-28
---

# boot-agent: Completion Plan

## Context

Most of the heavy lifting is **done** on `feat/boot-agent`. This plan covers
only what remains before merging to `main`.

## What Is Already Done

| Component | Status |
|-----------|--------|
| `agent-boot/bootstrap.py` — 7-step device bootstrap | ✅ |
| `agent-boot/relay/agent.py` — gRPC bidi relay daemon | ✅ |
| `agent-boot/relay/u2_session_pool.py` — persistent u2 sessions | ✅ |
| `agent-boot/relay/u2_executor.py` — batch + flow executor | ✅ |
| `agent-boot/relay/control_client.py` — separate control gRPC channel | ✅ |
| `agent-boot/relay/supervisor.py` — recovery supervisor | ✅ |
| `device_farm/runtime/transports/grpc_relay_server.py` — gRPC server | ✅ |
| `device_farm/runtime/transports/agent_control_servicer.py` | ✅ |
| `device_farm/api/routes/relay_agents.py` — list/get/bootstrap-all | ✅ |
| `device_farm/api/routes/devices.py` — bootstrap/restart-u2/restart-atx | ✅ |
| `device_farm/api/routes/device_control/campaign_fleet.py` — Temporal | ✅ |
| `device_farm/db/models/relay_agent.py` + migration 030 | ✅ |
| `device_farm/runtime/core/device_client.py` — u2_batch integration | ✅ |
| Frontend: relay status column + bootstrap button in device list | ✅ |
| STFService: IdentityActivity intent-injected QR support (staged) | 🔄 |

## What Remains

| # | Task | Effort | Phase |
|---|------|--------|-------|
| 1 | STFService APK: commit + build | 1h | 01 |
| 2 | auto-connect via `adb shell am start` in bootstrap.py | 1h | 01 |
| 3 | Relay Agent management UI page | 2h | 02 |
| 4 | U2_BATCH_ENABLED rollout (test + flip flag) | 1.5h | 03 |
| 5 | Integration tests: relay chain E2E | 2.5h | 04 |
| 6 | agent-boot README + .env.example | 0.5h | 05 |
| 7 | DB migration guard: check 030 runs on fresh install | 0.5h | 05 |

## Architecture Reference

```
Phone (STFService + atx-agent)
   ↕ USB/WiFi ADB
agent-boot (local machine)
   ↕ gRPC bidi (port 50051, outbound from agent)
device_farm (cloud/server)
   ↕ REST + WebSocket
Frontend (browser)
```

Data flows:
- **Video**: scrcpy → agent-boot scrcpy_relay → gRPC relay → device_farm → WS → browser
- **u2 commands**: device_farm → gRPC ControlMsg(u2_batch) → agent-boot U2Executor → atx-agent:7912
- **Bootstrap**: device_farm REST → agent_control_servicer → ControlStream → agent-boot bootstrap.py

## Phases

| # | Phase | Effort |
|---|-------|--------|
| 01 | [STFService APK + auto-connect](./phase-01-stf-apk.md) | 2h |
| 02 | [Relay Agent Management UI](./phase-02-relay-ui.md) | 2h |
| 03 | [U2 Batch Rollout](./phase-03-u2-batch-rollout.md) | 1.5h |
| 04 | [Integration Tests](./phase-04-tests.md) | 2.5h |
| 05 | [Cleanup & Ship](./phase-05-ship.md) | 1h |

## Success Criteria

- [x] agent-boot connects to device_farm, devices appear in device list with relay badge
- [x] Bootstrap button triggers bootstrap.py on target device, all steps pass
- [x] STFService auto-connects via ADB intent (no manual QR scan needed)
- [x] u2_batch path works: `tap_selector` uses 1 gRPC RTT (not 3)
- [x] All existing tests pass + new relay integration tests green
- [x] `main` merge ready

## Risks

| Risk | Mitigation |
|------|------------|
| STFService build requires Android SDK locally | Pre-build APK committed to bundle/apks/ |
| u2_batch introduces regression in existing scenarios | Feature flag; keep legacy path |
| gRPC port 50051 blocked in cloud deployment | Document in README; env var override |
| IdentityActivity auto-connect races with manual QR | Intent only processed if WsAgentService not running |
