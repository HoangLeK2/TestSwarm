# Phase 05 - Artifacts, Cleanup, Quarantine

## Overview

Tie artifacts and device health to leases. A device should only return to the scheduler after cleanup succeeds.

## Priority

P1. This prevents dirty state from one execution leaking into the next.

## Current State

- `capture_store.py` can save to MinIO/R2/S3 or local filesystem.
- Artifact metadata is not consistently modeled around relay/execution/lease.
- Agent has scrcpy/u2 cleanup primitives but no cloud-owned cleanup state.
- No durable quarantine table is present.

## Files

Modify:

- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/services/capture_store.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/services/image_store.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/services/campaign_dispatch.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/services/scheduler.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/runtime/transports/adb_relay_server.py`
- `/Users/hoanglcpila.vn/deviceFarmer/agent-boot/relay/agent.py`
- `/Users/hoanglcpila.vn/deviceFarmer/agent-boot/relay/session_manager.py`
- `/Users/hoanglcpila.vn/deviceFarmer/agent-boot/relay/u2_session_pool.py`

Create:

- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/models/artifact.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/models/device_quarantine.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/crud/artifact.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/crud/device_quarantine.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/migrations/033_artifacts_quarantine.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/services/artifact_service.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/services/device_cleanup_service.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/tests/test_cleanup_quarantine.py`

## Schema

Artifacts:

```sql
artifacts(
  id VARCHAR(36) PRIMARY KEY,
  execution_id VARCHAR(36),
  lease_id VARCHAR(36),
  relay_id VARCHAR(128),
  serial VARCHAR(128) NOT NULL,
  artifact_type VARCHAR(64) NOT NULL,
  storage_backend VARCHAR(32) NOT NULL,
  storage_key TEXT NOT NULL,
  content_type VARCHAR(128) NOT NULL,
  size_bytes BIGINT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  metadata JSONB NOT NULL DEFAULT '{}'
)
```

Quarantine:

```sql
device_quarantine_records(
  id VARCHAR(36) PRIMARY KEY,
  serial VARCHAR(128) NOT NULL,
  relay_id VARCHAR(128),
  lease_id VARCHAR(36),
  reason VARCHAR(128) NOT NULL,
  details TEXT NOT NULL DEFAULT '',
  status VARCHAR(32) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  cleared_at TIMESTAMPTZ
)
```

Active quarantine unique index:

```sql
CREATE UNIQUE INDEX uq_device_quarantine_active_serial
ON device_quarantine_records(serial)
WHERE status = 'active';
```

## Cleanup Contract

Cloud sends:

```json
{
  "type": "cleanup_session",
  "id": "cleanup-abc",
  "serial": "R5CT...",
  "lease_id": "lease-uuid",
  "actions": ["stop_scrcpy", "evict_u2", "probe_caps"]
}
```

Agent replies:

```json
{
  "type": "cleanup_result",
  "id": "cleanup-abc",
  "serial": "R5CT...",
  "lease_id": "lease-uuid",
  "ok": true,
  "checks": {
    "scrcpy_stopped": true,
    "u2_evicted": true,
    "adb_responsive": true
  }
}
```

## Implementation Steps

1. Add artifact and quarantine schema.
2. Add artifact service wrapping `capture_store` and object storage.
3. Persist artifact metadata for screenshots/XML/logs/videos created during execution.
4. Add cleanup command and result handling.
5. On execution end:
   - mark lease `cleanup`.
   - send cleanup command.
   - on success: end lease.
   - on failure: create active quarantine and end lease as failed.
6. Scheduler excludes active quarantined devices.
7. Add admin endpoint to clear quarantine with reason.
8. Add tests for cleanup success/failure and scheduler exclusion.

## Success Criteria

- Device returns to idle only after cleanup success.
- Cleanup failure creates active quarantine.
- Scheduler never assigns actively quarantined serial.
- Artifacts can be traced by execution, lease, relay, and serial.

## Risks

- Video artifacts may be large.
- Mitigation: only metadata in DB; bytes in object storage.
