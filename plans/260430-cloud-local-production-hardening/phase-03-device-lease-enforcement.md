# Phase 03 - Device Lease Enforcement

## Overview

Add durable cloud-owned execution leases. Do not repurpose existing `DeviceSession`; it currently records device-agent/manual session history, not production ownership.

## Priority

P1. This is the main protection against two jobs controlling one phone.

## Current State

- `common/session_lock.py` provides in-memory reservation/session cache.
- `mcp_sessions` persists manual user sessions.
- `AdbRelayManager.allocate_device()` has in-memory pool state.
- Campaign dispatch currently binds campaign devices by configured device list, not a durable lease table.

## Files

Modify:

- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/models/__init__.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/models/enums.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/crud/__init__.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/services/campaign_dispatch.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/services/scheduler.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/runtime/core/device_pool.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/api/routes/device_control/sessions.py`

Create:

- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/models/device_lease.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/crud/device_lease.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/migrations/032_device_leases.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/services/device_lease_service.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/tests/test_device_leases.py`

## Schema

```sql
CREATE TABLE device_leases (
  id VARCHAR(36) PRIMARY KEY,
  device_id VARCHAR(36) REFERENCES devices(id) ON DELETE SET NULL,
  relay_id VARCHAR(128) REFERENCES relay_agents(relay_id) ON DELETE SET NULL,
  serial VARCHAR(128) NOT NULL,
  user_id VARCHAR(36),
  execution_id VARCHAR(36) REFERENCES executions(id) ON DELETE SET NULL,
  campaign_id VARCHAR(36) REFERENCES campaigns(id) ON DELETE SET NULL,
  scenario_id VARCHAR(36),
  status VARCHAR(32) NOT NULL,
  lease_expires_at TIMESTAMPTZ NOT NULL,
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ended_at TIMESTAMPTZ,
  end_reason VARCHAR(64) NOT NULL DEFAULT '',
  metadata JSONB NOT NULL DEFAULT '{}'
);
```

Unique active lease:

```sql
CREATE UNIQUE INDEX uq_device_leases_active_serial
ON device_leases(serial)
WHERE status IN ('reserved', 'running', 'cleanup');
```

Status values:

- `reserved`
- `running`
- `cleanup`
- `ended`
- `expired`
- `failed`

## Lease Service API

```python
async def acquire_lease(db, *, serial, relay_id, user_id=None,
                        execution_id=None, campaign_id=None,
                        scenario_id=None, ttl_seconds=3600) -> DeviceLease: ...

async def mark_running(db, lease_id): ...
async def renew_lease(db, lease_id, ttl_seconds=3600): ...
async def begin_cleanup(db, lease_id): ...
async def end_lease(db, lease_id, reason): ...
async def expire_stale_leases(db): ...
```

## Integration Rules

- Manual session start can create a lease or link to one.
- Campaign execution must acquire lease before sending any device command.
- Scheduler must ignore:
  - active leased devices
  - offline relay agents
  - draining/disabled relay agents
  - quarantined devices from phase 05

## Implementation Steps

1. Add schema/model/CRUD.
2. Add `DeviceLeaseService`.
3. Add active-lease unique index and tests for concurrent acquire.
4. Integrate manual session start/end.
5. Integrate campaign dispatch path in soft mode:
   - acquire lease before execution.
   - release at end.
   - on exception, move to cleanup/failed.
6. Add stale lease recovery during startup, similar to crash recovery.
7. Keep `SessionLockStore` as cache only; DB lease is authority.

## Success Criteria

- Concurrent lease acquisition for one serial returns exactly one success.
- Restarted cloud process can see active/stale leases from DB.
- Scheduler cannot allocate an actively leased device.
- Existing manual session route still works.

## Risks

- Campaign code may have several command entry points.
- Mitigation: start with central paths used by campaign dispatch, then add guardrails in phase 04 so missed paths fail closed.
