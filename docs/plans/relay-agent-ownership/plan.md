---
title: "Relay Agent Ownership Plan"
description: "Bind each agent-boot relay to a user-owned enrollment token so cloud APIs can answer who owns an agent and who may operate it."
status: completed
priority: P1
effort: 18h
branch: feat/extra-data
tags: [feature, backend, database, api, auth, frontend]
created: 2026-05-15
---

# Relay Agent Ownership Plan

## Overview

Add explicit ownership for `agent-boot` relay agents. Today relay agents are global records authenticated only by shared `RELAY_API_KEY`; device discovery is filtered by LAN and device ownership, but the relay itself has no owner. This plan adds a user-scoped enrollment token, persists `relay_agents.user_id`, and gates relay listing/actions by owner.

## Current Problem

- `relay_agents` has no `user_id`.
- `agent-boot` register payload has no user identity.
- `/api/relay-agents` can only infer visibility from same-LAN device metadata.
- The system can answer "which devices are claimed by user A", but not "which relay agent belongs to user A".

## Target Contract

- Every registered relay agent has exactly one owner user.
- `agent-boot` proves ownership with a user-scoped enrollment token, not by trusting hostname/IP.
- Cloud UI lists only relay agents owned by the current user.
- Device discovery still uses same-LAN/CIDR filtering inside the owner's relay.
- Dangerous actions (`push-connect-url`, `bootstrap-all`, restart) require both relay ownership and device ownership or a user-owned pending device.
- A user can revoke or rotate a relay token without affecting other users.

## Phases

| # | Phase | Status | Effort | Link |
|---|-------|--------|--------|------|
| 1 | Data Model & Migration | Completed | 3h | [phase-01-data-model.md](./phase-01-data-model.md) |
| 2 | Enrollment Token API | Completed | 4h | [phase-02-enrollment-api.md](./phase-02-enrollment-api.md) |
| 3 | Agent-Boot Identity Handshake | Completed | 4h | [phase-03-agent-handshake.md](./phase-03-agent-handshake.md) |
| 4 | Authorization Gates | Completed | 4h | [phase-04-authorization.md](./phase-04-authorization.md) |
| 5 | UI & Verification | Completed | 3h | [phase-05-ui-verification.md](./phase-05-ui-verification.md) |

## Recommended Design

Use enrollment tokens.

- User creates token from cloud.
- Server stores only token hash.
- User sets token in `agent-boot/.env`.
- Agent sends token on control-channel gRPC metadata (`x-relay-enrollment-token`).
- Server resolves token to `user_id` and persists `relay_agents.user_id`.

Why this design:

- Simple and explicit.
- Works for cloud and local deployments.
- Does not require browser/device to be on the same WiFi.
- Avoids guessing owner from device ownership or IP.
- Revocable and auditable.

## Non-Goals

- Do not replace ADB serial as technical device ID.
- Do not change high-throughput video stream semantics.
- Do not introduce organization/team sharing until user ownership is stable.
- Do not store raw enrollment tokens.
- Do not require SSID/BSSID matching for this phase.

## Key Files

- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/models/relay_agent.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/crud/relay_agent.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/migrations/038_relay_agent_ownership.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/api/routes/relay_agents.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/api/schemas/relay_agent.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/runtime/transports/agent_control_servicer.py`
- `/Users/hoanglcpila.vn/deviceFarmer/agent-boot/relay/control_client.py`
- `/Users/hoanglcpila.vn/deviceFarmer/agent-boot/main.py`
- `/Users/hoanglcpila.vn/deviceFarmer/front-end/src/features/devices/services/manage-api.ts`
- `/Users/hoanglcpila.vn/deviceFarmer/front-end/src/app/[locale]/dashboard/relay-agents/page.tsx`

## Validation Commands

```bash
cd /Users/hoanglcpila.vn/deviceFarmer/device_farm
uv run pytest tests/test_relay_agents_routes.py
uv run python -m py_compile db/models/relay_agent.py db/crud/relay_agent.py api/schemas/relay_agent.py api/routes/relay_agents.py runtime/transports/agent_control_servicer.py web/server.py main.py

cd /Users/hoanglcpila.vn/deviceFarmer/front-end
pnpm exec tsc --noEmit
pnpm exec eslint 'src/app/[locale]/dashboard/relay-agents/page.tsx' src/features/devices/services/manage-api.ts --max-warnings=0
```

## Open Questions

- Should relay ownership be user-only now, or user plus organization/team later?
- Should one enrollment token map to one relay only, or allow multiple machines under one token?
- Should revoking a relay token immediately force-disconnect active control streams?
