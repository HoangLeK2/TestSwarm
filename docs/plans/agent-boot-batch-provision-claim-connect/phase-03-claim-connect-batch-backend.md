# Phase 3 - Claim And Connect Batch Backend

Status: Completed
Priority: P1
Effort: 6h

## Overview

Add a batch endpoint that claims relay-visible phones as user devices and pushes each device-agent connection URL through `agent-boot` ADB. This removes per-phone QR scanning.

## Requirements

- Claim selected/all visible relay serials.
- Use phone-probed name and metadata.
- Create device if missing.
- Assign unowned existing pending/physical device to current user.
- Reject serial owned by another user.
- Push correct STFService URL through ADB.
- Return per-serial result.
- QR fallback only when ADB push fails.
- Write one `relay_agent_job_items` row per phone.
- Run claim/connect through `services/relay_onboarding.py`, not directly inside route handlers.
- Prefer Temporal for production durability.

## Related Code

- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/api/routes/relay_agents.py`
  - `register_relay_device`
  - `push_connect_url_to_device`
- `/Users/hoanglcpila.vn/deviceFarmer/front-end/src/features/devices/components/register-device-dialog.tsx`
  - current single-device flow
- `/Users/hoanglcpila.vn/deviceFarmer/front-end/src/features/devices/components/device-list/ConnectDialog.tsx`
  - current push/QR fallback patterns
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/services/relay_onboarding.py`
  - shared claim/connect helpers and job dispatch
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/temporal/relay_onboarding_workflows.py`
  - durable claim/connect workflow
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/temporal/relay_onboarding_activities.py`
  - per-serial activity with isolated DB session

## Proposed Endpoint

```http
POST /api/relay-agents/{relay_id}/jobs/claim-connect
```

Request:

```json
{
  "mode": "selected",
  "serials": ["R58N...", "192.168.1.20:5555"],
  "connect": true
}
```

Per-serial result:

```json
{
  "serial": "R58N...",
  "status": "connected",
  "device_id": "...",
  "device_name": "Galaxy S23",
  "push_ok": true,
  "qr_url": ""
}
```

If push fails:

```json
{
  "serial": "R58N...",
  "status": "claimed_push_failed",
  "device_id": "...",
  "push_ok": false,
  "qr_url": "wss://.../device-agent?key=...",
  "error": "..."
}
```

## Implementation Steps

1. Extract single-device claim logic from `register_relay_device` into helper:
   - `claim_relay_serial(db, row, serial, user) -> Device`
2. Extract connect URL construction into helper:
   - `build_device_agent_url(request, device)`
3. Extract ADB push into helper:
   - `push_connect_url(ctrl, serial, ws_url) -> RelayCommandOut`
4. Implement batch job runner:
   - concurrency 8-16 for `ctrl.shell` URL push.
   - `RELAY_CLAIM_CONNECT_CONCURRENCY` env override.
5. Create job and item rows before execution.
6. Run via Temporal workflow when enabled:
   - one activity per serial or bounded batches.
   - heartbeat progress from activity.
7. Keep existing single-device endpoints as wrappers around the helper.
8. Commit device creation per serial or in small batches:
   - avoid one failed serial rolling back 99 successful claims.
9. Store item results incrementally.
10. Recompute job counters from item statuses.

## Success Criteria

- User can register and connect 100 relay-visible phones without QR scanning.
- Existing single-device UI still works.
- Batch returns QR fallback only for failed ADB push.
- Another user's serial cannot be claimed.
- Failed items can be retried without retrying successful devices.

## Security Considerations

- `device_key` must only be pushed for devices owned by current user.
- Do not expose another user's relay serial through job result.
- Avoid logging full device-agent URLs if they contain keys.

## Risks

- Transaction handling can get messy if 100 serials share one DB session. Use one session per worker or commit per serial.
- ADB shell output may include long errors. Truncate.
- If Temporal is disabled, local background task is acceptable for dev but not enough for production restart safety.
