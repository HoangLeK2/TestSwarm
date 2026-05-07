# Phase 04 - Command Contract And Agent Guards

## Overview

Make relay commands lease-aware. Cloud sends `lease_id`; local `agent-boot` maintains active lease ownership per serial and rejects stale commands.

## Priority

P1. DB leases protect cloud allocation; agent-side guards protect local execution.

## Current State

- Relay JSON commands primarily target by `serial`.
- A11y action already carries `session_id`, but it is not enforced as ownership.
- `u2_request`, `u2_batch`, `u2_flow`, `scrcpy_start`, `command` do not consistently require lease/session ownership.
- Raw shell is available via `CMD_SHELL`.

## Files

Modify:

- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/runtime/transports/adb_relay_server.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/runtime/transports/agent_control_servicer.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/proto/relay.proto`
- `/Users/hoanglcpila.vn/deviceFarmer/agent-boot/relay/agent.py`
- `/Users/hoanglcpila.vn/deviceFarmer/agent-boot/relay/control_client.py`
- `/Users/hoanglcpila.vn/deviceFarmer/agent-boot/relay/u2_executor.py`
- `/Users/hoanglcpila.vn/deviceFarmer/agent-boot/relay/session_manager.py`

Create tests:

- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/tests/test_relay_lease_contract.py`
- `/Users/hoanglcpila.vn/deviceFarmer/agent-boot/relay/tests/test_lease_guards.py`

## Command Contract

Add common fields to JSON envelope:

```json
{
  "type": "u2_batch",
  "id": "batch-abc",
  "serial": "R5CT...",
  "lease_id": "lease-uuid",
  "schema": 2,
  "actions": []
}
```

New command types:

```json
{ "type": "lease_start", "lease_id": "...", "serial": "...", "ttl_seconds": 3600 }
{ "type": "lease_renew", "lease_id": "...", "serial": "...", "ttl_seconds": 3600 }
{ "type": "lease_end", "lease_id": "...", "serial": "...", "reason": "completed" }
```

Protected operations:

- `u2_request`
- `u2_batch`
- `u2_flow`
- `a11y_action` mutate/query
- `scrcpy_start`
- `scrcpy_stop`
- `screencap`
- `bootstrap` after initial pairing, depending on rollout flag
- `restart_u2`, `restart_atx`, `restart_scrcpy` when attached to active execution

Debug/admin operations:

- raw `CMD_SHELL` stays disabled in production unless `RELAY_ALLOW_RAW_SHELL=1`.

## Agent State

In `agent-boot`:

```python
self._active_leases: dict[str, dict] = {
    serial: {
        "lease_id": "...",
        "deadline": monotonic_deadline,
    }
}
```

Guard:

```python
def _lease_allows(serial: str, lease_id: str, *, required: bool) -> tuple[bool, str]:
    if not required:
        return True, ""
    active = self._active_leases.get(serial)
    if not active:
        return False, "no_active_lease"
    if active["lease_id"] != lease_id:
        return False, "lease_mismatch"
    if active["deadline"] <= time.monotonic():
        return False, "lease_expired"
    return True, ""
```

## Rollout Flags

Cloud:

```env
RELAY_SEND_LEASE_ID=1
RELAY_REQUIRE_LEASE=0
RELAY_ALLOW_RAW_SHELL=0
```

Agent:

```env
AGENT_REQUIRE_LEASE=0
AGENT_ALLOW_RAW_SHELL=0
```

Rollout:

1. Send lease id, do not require.
2. Agent logs missing lease.
3. Agent requires lease for one canary node.
4. Cloud requires lease globally.

## Implementation Steps

1. Add `lease_id` parameter to relay manager public methods.
2. Thread `lease_id` from `DeviceLeaseService` callers to relay calls.
3. Add `lease_start/renew/end` messages.
4. Add agent active lease map and guard helpers.
5. Add guard to u2/a11y/scrcpy/screencap paths.
6. Block raw shell by default in production.
7. Add structured error responses:
   - `missing_lease`
   - `lease_mismatch`
   - `lease_expired`
   - `raw_shell_disabled`
8. Add tests for stale lease and wrong lease.

## Success Criteria

- Wrong `lease_id` command is rejected before touching ADB/u2/scrcpy.
- Missing lease command is rejected when enforcement flag is enabled.
- Old agents still work in soft mode.
- Raw shell is not available in production by default.

## Risks

- Scrcpy lifecycle may need exceptions for viewer-only sessions.
- Mitigation: support `lease_scope`: `control`, `view`, `maintenance`.
