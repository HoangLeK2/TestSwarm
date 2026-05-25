# Phase 2 - Relay Provision Batch Backend

Status: Completed
Priority: P1
Effort: 5h

## Overview

Add backend support to provision relay-visible phones, including phones not yet registered as devices. This is the cloud-triggered version of "install STFService and required libraries on all visible phones".

## Requirements

- User can provision selected or all visible relay serials.
- Relay must belong to current user.
- Serial must be reported by that relay.
- Serial must pass same-LAN/CIDR visibility if cloud connection is expected.
- Allow USB serials if `agent-boot` can probe `wlan_ip`; mark devices without WiFi IP as `blocked_network`.
- Run commands with bounded concurrency.
- Return a job ID immediately.
- Prefer Temporal workflow/activity in production.
- Use FastAPI background task only as local/dev fallback when Temporal is disabled.

## Related Code

- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/api/routes/relay_agents.py`
  - existing `bootstrap_all`
  - existing `_serial_is_same_wifi`
  - existing `_relay_to_out_same_wifi`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/runtime/transports/agent_control_servicer.py`
  - existing `bootstrap(serial)`
- `/Users/hoanglcpila.vn/deviceFarmer/agent-boot/relay/adb.py`
  - existing `_bootstrap_device`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/services/relay_onboarding.py`
  - new service layer for job creation, visible serial resolution, and runner dispatch
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/temporal/relay_onboarding_workflows.py`
  - new durable workflow for provision jobs
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/temporal/relay_onboarding_activities.py`
  - new activities for per-serial bootstrap and DB item updates

## Proposed Endpoint

```http
POST /api/relay-agents/{relay_id}/jobs/provision
```

Request:

```json
{
  "mode": "all_visible",
  "serials": []
}
```

Response:

```json
{ "job_id": "...", "status": "pending", "total": 100 }
```

## Implementation Steps

1. Refactor visible serial resolution into a shared helper:
   - input: relay row, user id, mode, requested serials.
   - output: serials plus metadata/caps.
2. For `all_visible`, include relay serials that:
   - are not `pending-*`,
   - are same LAN/CIDR,
   - are not already owned by another user.
3. Create job row and one `relay_agent_job_items` row per serial.
4. Dispatch runner:
   - if Temporal enabled, start `RelayProvisionWorkflow`.
   - else spawn local background task attached to app event loop.
5. Inside runner:
   - get `AgentControlServicer`,
   - run `ctrl.bootstrap(serial, timeout=180)` with concurrency limit.
6. Recommended default concurrency:
   - start with 8.
   - make configurable with `RELAY_PROVISION_CONCURRENCY`.
7. Update job item after each serial.
8. Recompute job summary counters from item rows.
9. Mark final status:
   - `completed` if all ok,
   - `completed_with_errors` if partial failures.

## Pseudocode

```python
serials = resolve_visible_serials(row, user.id, body)
job = await relay_onboarding.create_provision_job(...)
await relay_onboarding.dispatch_job(job.id)
return RelayBatchJobOut.from_job(job)
```

## Success Criteria

- Provision endpoint returns quickly for 100 phones.
- Job progress updates while devices are being bootstrapped.
- Each phone has a dedicated item row with status/error.
- Unregistered relay-visible phones can be provisioned.
- User cannot provision another user's relay.

## Risks

- Running too many installs concurrently can overload USB hubs and ADB daemon.
- Keep concurrency configurable and conservative.
- If `agent-boot` command channel disconnects, mark remaining serials failed with clear error.
- FastAPI background tasks are not durable across server restart. Use Temporal for production 100+ phone runs.
