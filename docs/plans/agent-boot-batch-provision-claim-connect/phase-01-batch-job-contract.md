# Phase 1 - Batch Job Model And API Contract

Status: Completed
Priority: P1
Effort: 4h

## Overview

Create a durable relay batch job model for long-running 100-phone operations. This prevents HTTP timeouts and gives the UI progress, retry, and per-device failure detail without storing all item state in one large JSONB blob.

## Requirements

- Persist job metadata in `relay_agent_jobs`.
- Persist one row per serial in `relay_agent_job_items`.
- Scope every job to `user_id` and `relay_id`.
- Support at least two job kinds:
  - `provision`
  - `claim_connect`
- Track status:
  - `pending`
  - `running`
  - `completed`
  - `completed_with_errors`
  - `failed`
  - `cancelled`
- Store per-device result/status in item rows.
- Keep item `result` JSON small and optional for command summaries.
- Never store raw enrollment tokens.

## Proposed Schema

Create `relay_agent_jobs`:

```sql
CREATE TABLE relay_agent_jobs (
  id          VARCHAR(36) PRIMARY KEY,
  user_id     VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  relay_id    VARCHAR(128) NOT NULL,
  kind        VARCHAR(32) NOT NULL,
  status      VARCHAR(32) NOT NULL DEFAULT 'pending',
  total       INTEGER NOT NULL DEFAULT 0,
  ok          INTEGER NOT NULL DEFAULT 0,
  failed      INTEGER NOT NULL DEFAULT 0,
  pending     INTEGER NOT NULL DEFAULT 0,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  started_at  TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Create `relay_agent_job_items`:

```sql
CREATE TABLE relay_agent_job_items (
  id          VARCHAR(36) PRIMARY KEY,
  job_id      VARCHAR(36) NOT NULL REFERENCES relay_agent_jobs(id) ON DELETE CASCADE,
  serial      VARCHAR(255) NOT NULL,
  device_id   VARCHAR(36) REFERENCES devices(id) ON DELETE SET NULL,
  status      VARCHAR(32) NOT NULL DEFAULT 'pending',
  step        VARCHAR(64) NOT NULL DEFAULT '',
  attempts    INTEGER NOT NULL DEFAULT 0,
  error       TEXT NOT NULL DEFAULT '',
  result      JSONB NOT NULL DEFAULT '{}',
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  started_at  TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(job_id, serial)
);
```

Indexes:

- `relay_agent_jobs(user_id, created_at DESC)`
- `relay_agent_jobs(relay_id, created_at DESC)`
- `relay_agent_jobs(status)`
- `relay_agent_job_items(job_id, status)`
- `relay_agent_job_items(job_id, serial)`
- `relay_agent_job_items(device_id)`

## Files

- Modify `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/models/relay_agent.py`
- Modify `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/models/__init__.py`
- Modify `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/crud/relay_agent.py`
- Prefer create `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/crud/relay_agent_job.py` if CRUD grows beyond small helpers
- Create `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/migrations/039_relay_agent_jobs.py`
- Modify `/Users/hoanglcpila.vn/deviceFarmer/device_farm/api/schemas/relay_agent.py`

## API Contract

Add schemas:

```python
class RelayBatchJobCreate(BaseModel):
    serials: list[str] = []
    mode: Literal["selected", "all_visible"] = "selected"

class RelayBatchJobItemOut(BaseModel):
    id: str
    serial: str
    device_id: str | None
    status: str
    step: str
    attempts: int
    error: str
    result: dict

class RelayBatchJobOut(BaseModel):
    id: str
    relay_id: str
    kind: str
    status: str
    total: int
    ok: int
    failed: int
    pending: int
    items: list[RelayBatchJobItemOut]
```

## Implementation Steps

1. Add model and migration.
2. Add CRUD helpers:
   - `create_relay_job`
   - `bulk_create_relay_job_items`
   - `get_relay_job`
   - `list_relay_job_items`
   - `mark_relay_job_item_running`
   - `finish_relay_job_item`
   - `recompute_relay_job_counts`
   - `finish_relay_job`
3. Add schema outputs.
4. Keep item `result` JSON small:
   - command output summary only.
   - truncate output/error.
   - store structured flags such as `stf_installed`, `u2_ready`, `push_ok`.

## Success Criteria

- Job rows are user-scoped.
- Job item progress can be updated incrementally.
- `GET job` refuses access when `user_id` mismatches.
- Retry can target failed items without parsing JSON arrays.

## Risks

- Long command output can bloat item `result`. Truncate.
- Server restart during job leaves status `running`. Add startup repair or timeout stale jobs later if needed.
