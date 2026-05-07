---
title: "Cloud Local Production Hardening"
description: "Harden the existing cloud device_farm and local agent-boot split with cloud-owned leases, safer relay identity, bounded commands, artifacts, cleanup, and rollout tests."
status: pending
priority: P1
effort: 44h
branch: feat/boot-agent
tags: [backend, infra, security, database, relay]
created: 2026-04-30
---

# Cloud Local Production Hardening

## Overview

The system already has most building blocks:

- `device_farm`: FastAPI, DB, scheduler/campaigns, relay endpoints, `relay_agents`, gRPC/WS relay.
- `agent-boot`: local outbound relay, stable `.relay_id`, ADB/u2/scrcpy execution, heartbeat, device watcher, session managers.

This plan does not rebuild those layers. It closes the production gaps created by running `device_farm` in cloud while `agent-boot` runs on local machines behind NAT.

## Core Decision

`device_farm` owns scheduling, auth, audit, leases, and artifact metadata. `agent-boot` owns local device execution only. Cloud never connects to ADB/u2/scrcpy ports directly. All device operations require an active cloud-created lease.

## Phases

| # | Phase | Deliverable | Effort | Link |
|---|-------|-------------|--------|------|
| 01 | Cloud mode boundary | Cloud deploy stops spawning local `agent-boot`; local-only behavior is explicit | 4h | [phase-01-cloud-mode-boundary.md](./phase-01-cloud-mode-boundary.md) |
| 02 | Relay identity and security | Relay agents become revocable DB-backed nodes with version/protocol metadata | 8h | [phase-02-relay-agent-identity-security.md](./phase-02-relay-agent-identity-security.md) |
| 03 | Device leases | Add durable execution leases and unique active lease protection | 10h | [phase-03-device-lease-enforcement.md](./phase-03-device-lease-enforcement.md) |
| 04 | Command contract guards | Add `lease_id` to relay commands and reject invalid commands in `agent-boot` | 10h | [phase-04-command-contract-agent-guards.md](./phase-04-command-contract-agent-guards.md) |
| 05 | Artifacts, cleanup, quarantine | Cloud-first artifact flow plus cleanup/quarantine state | 8h | [phase-05-artifacts-cleanup-quarantine.md](./phase-05-artifacts-cleanup-quarantine.md) |
| 06 | Tests and rollout | Regression tests, fake agent tests, staged rollout switches | 4h | [phase-06-tests-rollout.md](./phase-06-tests-rollout.md) |

## Existing Code To Preserve

- `agent-boot/relay/agent.py`: current WS/gRPC relay loop, heartbeat, u2/a11y/scrcpy handlers.
- `agent-boot/relay/control_client.py`: low-volume gRPC control channel.
- `device_farm/runtime/transports/adb_relay_server.py`: relay manager and JSON command transport.
- `device_farm/runtime/transports/agent_control_servicer.py`: AgentControlService.
- `device_farm/db/models/relay_agent.py`: existing relay node table.
- `device_farm/common/session_lock.py` and `device_farm/db/models/mcp_session.py`: current user-facing manual sessions.

## Non-Goals

- Do not remove ADB. Keep it isolated inside `agent-boot`.
- Do not split relay into a separate microservice in this plan.
- Do not rewrite scheduler/campaign execution.
- Do not remove WebSocket fallback yet.
- Do not implement anti-detection/crawling behavior here.
- Metrics are out of scope per request, except tests may assert observable state.

## Success Criteria

- Cloud deployment never starts local `agent-boot` by default.
- A relay agent can be disabled/revoked without changing every local node.
- A device cannot have two active production leases.
- Every mutating relay command carries `lease_id`.
- `agent-boot` rejects stale/missing/wrong lease commands for protected operations.
- Raw shell command is blocked in production unless explicitly enabled for admin/debug.
- Failed cleanup quarantines the device and scheduler excludes it.
- Artifact metadata is tied to `execution_id`, `lease_id`, `serial`, and `relay_id`.
- Existing manual session APIs keep working during migration.

## Main Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Breaking existing manual device control | High | Introduce lease checks behind feature flag, then enforce |
| Old `agent-boot` cannot understand `lease_id` | High | Protocol version gate and compatibility mode |
| Confusing `DeviceSession` vs production lease | Medium | Add a new table, do not repurpose old `DeviceSession` |
| Agent reconnect during active lease | Medium | Cloud lease remains authoritative; agent rehydrates active lease map from cloud command/heartbeat |
| Too much security change at once | Medium | Per-agent DB tokens first, mTLS later if deploy path needs it |

## Implementation Order

1. Land phase 01 first. It changes default deployment safety without touching command semantics.
2. Land phase 02 before exposing cloud relay publicly.
3. Land phase 03 with cloud-only enforcement and compatibility reads.
4. Land phase 04 in soft mode: warn/reject only when `RELAY_REQUIRE_LEASE=1`.
5. Land phase 05 after leases exist.
6. Land phase 06 across every phase; do not wait until the end for tests.

## Cook Handoff

Use this after review:

```bash
/ck:cook --auto /Users/hoanglcpila.vn/deviceFarmer/plans/260430-cloud-local-production-hardening/plan.md
```
