# Phase 6 - Verification And Rollout

Status: Completed
Priority: P1
Effort: 2h

## Overview

Verify the complete 100-phone onboarding contract and document operational guidance.

## Test Matrix

1. USB phone, WiFi on, unregistered:
   - provision succeeds,
   - claim succeeds,
   - push connect succeeds.
2. USB phone, WiFi off:
   - provision may succeed,
   - cloud-connect is blocked or push fails with clear reason.
3. WiFi ADB phone:
   - provision succeeds,
   - claim/connect succeeds.
4. Phone owned by another user:
   - hidden or rejected.
5. Invalid relay owner:
   - job creation rejected.
6. 100 serial mock:
   - endpoint returns job immediately,
   - Temporal or fallback runner tracks progress,
   - one item row exists per serial,
   - UI stays responsive.
7. Server restart during production Temporal job:
   - workflow can continue or fail items explicitly,
   - job is not lost silently.

## Automated Tests

- Extend `/Users/hoanglcpila.vn/deviceFarmer/device_farm/tests/test_relay_agents_routes.py`.
- Add tests for:
  - provision job creates user-scoped job,
  - all-visible resolution excludes other-owner serials,
  - claim/connect returns QR fallback on push failure,
  - job access is user-scoped,
  - concurrency runner records partial failures,
  - failed item retry does not rerun successful items,
  - item pagination/filtering works for large jobs.

## Manual Verification

```bash
cd /Users/hoanglcpila.vn/deviceFarmer/device_farm
uv run pytest tests/test_relay_agents_routes.py

cd /Users/hoanglcpila.vn/deviceFarmer/agent-boot
uv run main.py --relay-only
```

Manual steps:

1. Start backend with DB.
2. Create relay token in UI.
3. Start `agent-boot` with token.
4. Plug 3-5 phones for local smoke test.
5. Run provision selected.
6. Run register/connect selected.
7. Confirm phones appear online in Devices.

## Rollout Notes

- Keep old QR flow available.
- Keep old single-device register/push endpoints as fallback.
- Production recommendation: require Temporal for 100+ phone onboarding.
- Local/dev fallback may use FastAPI background task.
- Add env defaults:
  - `RELAY_PROVISION_CONCURRENCY=8`
  - `RELAY_CLAIM_CONNECT_CONCURRENCY=12`
- For 100 phones, recommend powered USB hubs and staged retries.

## Done Criteria

- User can onboard many phones through `agent-boot` without scanning QR per phone.
- Provision and claim/connect are observable through jobs.
- Per-phone state is stored in `relay_agent_job_items`.
- Failures are per-device, not all-or-nothing.
- Multi-user ownership boundary remains intact.
