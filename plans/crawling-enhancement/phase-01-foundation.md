# Phase 1: Foundation — Reliability & Persistent Queue

## Objective

Replace in-memory `TaskQueue` with Redis-backed persistent queue. Add checkpoint/resume, dead-letter queue, and exponential backoff retry. Ensures crawl jobs survive crashes and can be inspected/retried.

## Problem

Current `runtime/core/task_queue.py` is in-memory only. If the server crashes mid-campaign, all queued tasks are lost. No retry on transient errors. No visibility into failed jobs.

## Implementation

### 1.1 Redis-Backed Task Queue

**File**: `runtime/core/task_queue.py` (rewrite)

```python
import redis.asyncio as aioredis
import json, uuid
from dataclasses import dataclass, asdict

QUEUE_KEY = "device_farm:task_queue"
DLQ_KEY = "device_farm:dead_letter_queue"
PROCESSING_KEY = "device_farm:processing"

class RedisTaskQueue:
    def __init__(self, redis_url: str):
        self.redis = aioredis.from_url(redis_url)

    async def enqueue(self, task: dict, priority: int = 5) -> str:
        task_id = str(uuid.uuid4())
        payload = json.dumps({"id": task_id, "priority": priority, **task})
        # Redis sorted set: score = priority (lower = higher priority)
        await self.redis.zadd(QUEUE_KEY, {payload: priority})
        return task_id

    async def dequeue(self) -> dict | None:
        # Pop lowest score (highest priority)
        items = await self.redis.zpopmin(QUEUE_KEY, count=1)
        if not items:
            return None
        payload_str, score = items[0]
        task = json.loads(payload_str)
        # Track in-flight
        await self.redis.hset(PROCESSING_KEY, task["id"], payload_str)
        return task

    async def ack(self, task_id: str):
        await self.redis.hdel(PROCESSING_KEY, task_id)

    async def nack(self, task_id: str, error: str, max_retries: int = 3):
        raw = await self.redis.hget(PROCESSING_KEY, task_id)
        if not raw:
            return
        task = json.loads(raw)
        task["retries"] = task.get("retries", 0) + 1
        task["last_error"] = error
        await self.redis.hdel(PROCESSING_KEY, task_id)
        if task["retries"] >= max_retries:
            await self.redis.lpush(DLQ_KEY, json.dumps(task))
        else:
            # Re-enqueue with backoff score boost
            backoff_score = task["priority"] + (task["retries"] * 10)
            await self.redis.zadd(QUEUE_KEY, {json.dumps(task): backoff_score})

    async def recover_in_flight(self):
        """On startup: re-enqueue any tasks stuck in processing (crash recovery)"""
        stuck = await self.redis.hgetall(PROCESSING_KEY)
        for task_id, payload_str in stuck.items():
            task = json.loads(payload_str)
            task["retries"] = task.get("retries", 0) + 1
            await self.redis.hdel(PROCESSING_KEY, task_id)
            await self.redis.zadd(QUEUE_KEY, {json.dumps(task): task.get("priority", 5)})
```

**Note**: `RedisConfig` và `redis_store.py` đã tồn tại. Dùng `redis_store.client()` thay vì tạo client mới:
```python
from services import redis_store

class RedisTaskQueue:
    def __init__(self):
        self.redis = redis_store.client()  # đã init trong main.py startup
    ...
```

### 1.2 Checkpoint / Resume

**File**: `tasks/scenario_task.py`

After each step completes, write checkpoint to execution record:

```python
async def run_scenario_task(execution_id, device, scenario, db):
    execution = await crud.execution.get(db, execution_id)
    start_step = execution.checkpoint_step or 0  # resume from checkpoint
    
    for idx, step in enumerate(scenario.steps[start_step:], start=start_step):
        if execution.status == "paused":
            break
        try:
            result = await run_step(ctx, step, idx)
            # Save checkpoint after each step
            await crud.execution.update_checkpoint(db, execution_id, idx + 1)
        except Exception as e:
            await queue.nack(execution.task_id, str(e))
            raise
    
    await queue.ack(execution.task_id)
```

**DB migration**: Chỉ thêm `checkpoint_step` — lưu `task_id` vào `Execution.meta["task_id"]` (tận dụng JSON column có sẵn):

```sql
ALTER TABLE executions ADD COLUMN checkpoint_step INTEGER DEFAULT 0;
```

### 1.3 Dead Letter Queue

**`ExecutionDLQ` table đã có sẵn** (`db/models/execution_dlq.py`) với đầy đủ fields: `retry_count`, `status` (pending/retrying/resolved), `last_attempt_at`, `error`.

API endpoints DLQ theo comment trong model: `GET /api/executions/dlq`, `POST /api/executions/dlq/{id}/retry` — chỉ cần implement route handler, **không cần tạo table**.

Khi `nack()` đạt max retries: ghi vào `ExecutionDLQ` (DB) thay vì Redis list:
```python
async def nack(self, task_id: str, error: str, execution_id: str, device_serial: str, max_retries: int = 3):
    ...
    if task["retries"] >= max_retries:
        # Ghi vào DB ExecutionDLQ thay vì Redis list
        async with AsyncSessionLocal() as db:
            await crud.execution_dlq.create(db, execution_id=execution_id,
                                             device_serial=device_serial, error=error)
```

### 1.4 Exponential Backoff

Already have `tenacity` in deps. Wrap device operations:

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type((DeviceConnectionError, TimeoutError))
)
async def safe_tap(device, x, y):
    return await device.tap(x, y)
```

## Files to Create/Modify

| File | Action | Notes |
|------|--------|-------|
| `runtime/core/task_queue.py` | Rewrite | Redis sorted set; dùng `redis_store.client()` |
| `runtime/core/dispatcher.py` | Modify | Call ack/nack; crash recovery on startup |
| `tasks/scenario_task.py` | Modify | Checkpoint sau mỗi step; lưu task_id vào meta |
| `db/models/execution.py` | Modify | Chỉ thêm `checkpoint_step` column |
| `db/crud/execution.py` | Modify | Add `update_checkpoint()` |
| `db/crud/execution_dlq.py` | New | CRUD cho `ExecutionDLQ` (model đã có) |
| `api/routes/executions.py` | Modify | Thêm DLQ endpoints (model + table đã có) |
| `docker-compose.yml` | Modify | Đổi sang `redis/redis-stack` (cần cho Bloom filter Phase 5) |

## Dependencies

```toml
redis = {extras = ["hiredis"], version = "^5.0"}
# tenacity, redis_store đã có
```

> **Quan trọng**: Đổi Redis image sang `redis/redis-stack:latest` ngay từ Phase 1 để Phase 5 Bloom filter không cần migrate lại.

## Testing

- Unit: `test_task_queue.py` — enqueue, dequeue, ack, nack, recover_in_flight
- Integration: crash server mid-task → restart → verify task re-queued
- Load: 100 concurrent enqueues → all dequeued without loss

## Risks

- Redis as SPOF → run Redis with AOF persistence (`appendonly yes`)
- In-flight tasks on crash may re-run → ensure step handlers are idempotent (dedup by content_hash already handles this)
