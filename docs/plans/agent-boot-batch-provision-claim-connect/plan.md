---
title: "Agent-Boot Batch Provision And Claim Connect"
description: "Turn agent-boot into the primary onboarding path for 100-phone batches: provision, claim, and connect devices without per-phone QR scanning."
status: implemented
priority: P1
effort: 24h
branch: feat/extra-data
tags: [feature, backend, frontend, api, database, relay, onboarding]
created: 2026-05-15
---

# Agent-Boot Batch Provision And Claim Connect

## Overview

Make `agent-boot` the main onboarding authority for bulk phone setup. If `agent-boot` already sees a phone through USB or WiFi ADB, cloud should not require scanning a unique QR for that phone. Cloud should let the user provision visible phones, claim them as devices, and push each device-agent connection URL through ADB in batch.

## Current State

- `agent-boot` can bootstrap devices locally through `agent-boot/bootstrap.py`.
- Relay UI can list relay-visible phones through `/api/relay-agents`.
- Current register route claims one relay serial at a time.
- Current push route sends one connect URL at a time.
- Existing `bootstrap-all` is synchronous and currently scoped to already registered user devices.
- For 100 phones, a blocking HTTP `bootstrap-all` request and per-device UI clicks will not scale.

## Target Flow

1. User enrolls `agent-boot` with `RELAY_ENROLLMENT_TOKEN`.
2. User plugs in 100 phones by USB or connects phones by WiFi ADB.
3. Cloud shows relay-visible phones owned by that user and same LAN/CIDR.
4. User clicks **Provision selected/all**.
5. Backend starts an async relay batch job and calls `agent-boot` bootstrap commands with bounded concurrency.
6. User clicks **Register & Connect selected/all**.
7. Backend creates/claims devices, stores phone metadata, creates each `device_key`, and pushes the correct STFService URL via ADB.
8. Phones connect to cloud automatically.
9. QR remains only as fallback for devices where ADB push failed.

## Phases

| # | Phase | Status | Effort | Link |
|---|-------|--------|--------|------|
| 1 | Batch Job Model And API Contract | Completed | 4h | [phase-01-batch-job-contract.md](./phase-01-batch-job-contract.md) |
| 2 | Relay Provision Batch Backend | Completed | 5h | [phase-02-provision-batch-backend.md](./phase-02-provision-batch-backend.md) |
| 3 | Claim And Connect Batch Backend | Completed | 6h | [phase-03-claim-connect-batch-backend.md](./phase-03-claim-connect-batch-backend.md) |
| 4 | Agent-Boot Bootstrap Reliability | Completed | 4h | [phase-04-agent-boot-bootstrap-reliability.md](./phase-04-agent-boot-bootstrap-reliability.md) |
| 5 | Cloud UI Bulk Onboarding | Completed | 3h | [phase-05-cloud-ui-bulk-onboarding.md](./phase-05-cloud-ui-bulk-onboarding.md) |
| 6 | Verification And Rollout | Completed | 2h | [phase-06-verification-rollout.md](./phase-06-verification-rollout.md) |

## Implementation Notes

- Added durable `relay_agent_jobs` and `relay_agent_job_items` rows.
- Added async local runner for provision and claim-connect jobs with bounded concurrency.
- Added batch APIs for provision, claim-connect, job summary, and job item listing.
- Updated Relay Agents UI with multi-select, all-visible actions, and active job progress.
- Updated `agent-boot` relay bootstrap so cloud-triggered provisioning installs STFService, u2 APKs, atx-agent, permissions, and returns structured bootstrap output.
- Dispatch is Temporal-first when `scheduler._client` and Temporal config are available; FastAPI local background task remains only as a dev/fallback path when Temporal is unavailable.
- Temporal workflow fans out per job item with bounded chunks, so retry/heartbeat/cancel visibility is per phone instead of one long batch activity.
- Device claim lookup now queries indexed serial aliases instead of scanning all devices per phone.
- Real 100-phone device-lab validation is still required before production rollout.

## Recommended Design

Use durable relay batch jobs with one row per phone item.

- Do not make the browser wait on a 100-phone bootstrap request.
- Persist job summary in `relay_agent_jobs`.
- Persist per-phone state in `relay_agent_job_items`, not one large JSONB blob.
- Reuse existing relay ownership and same-LAN gating.
- Reuse existing `ctrl.bootstrap()` and `ctrl.shell()` command path.
- Refactor single-device register/push into shared helpers used by batch endpoints.
- Keep route handlers thin; put orchestration in `services/relay_onboarding.py`.
- For production, prefer Temporal workflow/activity because this repo already runs Temporal workers. FastAPI background task is acceptable only as a local/dev fallback.

## Execution Architecture

```text
API route
  -> services/relay_onboarding.py
  -> relay_agent_jobs + relay_agent_job_items
  -> Temporal workflow/activity when enabled
     -> AgentControlServicer
     -> agent-boot ADB command
  -> fallback local background runner when Temporal disabled
```

Concurrency defaults:

- `RELAY_PROVISION_CONCURRENCY=8`
- `RELAY_CLAIM_CONNECT_CONCURRENCY=12`

Provision is heavier because it installs APKs and starts services. Claim/connect is lighter because it mostly creates DB rows and runs an ADB intent.

## Proposed APIs

```http
POST /api/relay-agents/{relay_id}/jobs/provision
GET  /api/relay-agents/{relay_id}/jobs/{job_id}
POST /api/relay-agents/{relay_id}/jobs/claim-connect
```

Provision request:

```json
{ "serials": ["R58N...", "192.168.1.20:5555"], "mode": "selected" }
```

Claim/connect request:

```json
{ "serials": ["R58N...", "192.168.1.20:5555"], "connect": true }
```

Job result:

```json
{
  "id": "job-id",
  "relay_id": "agent-host-abc",
  "kind": "provision",
  "status": "running",
  "total": 100,
  "ok": 72,
  "failed": 3,
  "pending": 25,
  "items": [
    { "serial": "R58N...", "status": "ok", "device_id": "...", "error": "" }
  ]
}
```

## Key Constraints

- ADB serial/connect ID remains the technical control identity.
- Phone display name comes from `agent-boot` probe, not user text input.
- Same-WiFi means same LAN/CIDR from phone `wlan_ip` and relay IP.
- USB-connected phones are valid for provisioning and ADB control, but cloud device-agent connection still needs phone network access to cloud.
- QR is fallback only.
- Batch actions must be owner-gated by `relay_agents.user_id`.
- Do not let User B operate User A's relay-visible phones.

## Key Files

- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/api/routes/relay_agents.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/api/schemas/relay_agent.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/models/relay_agent.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/crud/relay_agent.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/services/relay_onboarding.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/temporal/relay_onboarding_workflows.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/temporal/relay_onboarding_activities.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/temporal/worker.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/runtime/transports/agent_control_servicer.py`
- `/Users/hoanglcpila.vn/deviceFarmer/agent-boot/bootstrap.py`
- `/Users/hoanglcpila.vn/deviceFarmer/agent-boot/relay/adb.py`
- `/Users/hoanglcpila.vn/deviceFarmer/agent-boot/relay/agent.py`
- `/Users/hoanglcpila.vn/deviceFarmer/front-end/src/app/[locale]/dashboard/relay-agents/page.tsx`
- `/Users/hoanglcpila.vn/deviceFarmer/front-end/src/features/devices/services/manage-api.ts`

## Validation Commands

```bash
cd /Users/hoanglcpila.vn/deviceFarmer/device_farm
uv run pytest tests/test_relay_agents_routes.py
uv run python -m py_compile api/routes/relay_agents.py db/crud/relay_agent.py services/relay_onboarding.py runtime/transports/agent_control_servicer.py temporal/relay_onboarding_workflows.py temporal/relay_onboarding_activities.py

cd /Users/hoanglcpila.vn/deviceFarmer/agent-boot
uv run python -m py_compile bootstrap.py relay/adb.py relay/agent.py

cd /Users/hoanglcpila.vn/deviceFarmer/front-end
pnpm exec tsc --noEmit
pnpm exec eslint 'src/app/[locale]/dashboard/relay-agents/page.tsx' src/features/devices/services/manage-api.ts --max-warnings=0
```

## Open Questions

- Should cloud automatically run provision when new USB phones appear, or require explicit user click?
- Should provision install STFService only, or always include u2/atx-agent too?
- Should failed devices keep QR fallback visible immediately, or only after retry attempts?
- Should production require Temporal for 100+ phone onboarding, or allow local fallback in all environments?
