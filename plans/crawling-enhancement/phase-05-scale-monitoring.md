# Phase 5: Scale & Monitoring

## Objective

Add Bloom filter deduplication for large-scale crawls, in-app stats logging, alert rules for blocked/failed states, and content change detection. (Prometheus/Grafana deferred — sẽ thêm sau khi cần.)

## 5.1 Bloom Filter Deduplication

Current dedup uses SHA256 hash stored in PostgreSQL — works but O(1) DB query per item. At 1M+ items, DB dedup becomes bottleneck.

**File**: `services/content_store.py` (modify)

```python
from redis.commands.bf import BFCommands  # redis-py >= 5.0

class BloomFilterDedup:
    """
    Two-layer dedup:
    1. Bloom filter (Redis): fast probabilistic check, no DB hit
    2. DB unique constraint: exact check, prevents duplicates
    """
    def __init__(self, redis_client, filter_name: str = "content_dedup"):
        self.redis = redis_client
        self.filter_name = filter_name

    async def initialize(self, capacity: int = 10_000_000, error_rate: float = 0.001):
        """Create Bloom filter if not exists. 10M items, 0.1% false positive."""
        try:
            await self.redis.bf().reserve(
                self.filter_name, error_rate, capacity
            )
        except Exception:
            pass  # already exists

    async def is_duplicate(self, content_hash: str) -> bool:
        return bool(await self.redis.bf().exists(self.filter_name, content_hash))

    async def mark_seen(self, content_hash: str):
        await self.redis.bf().add(self.filter_name, content_hash)


class ContentStore:
    def __init__(self, db, redis_client):
        self.db = db
        self.bloom = BloomFilterDedup(redis_client)
    
    async def save(self, item: ExtractedItem, collection: str) -> bool:
        content_hash = self._compute_hash(item)
        
        # Fast path: Bloom filter check (no DB hit)
        if await self.bloom.is_duplicate(content_hash):
            return False  # skip
        
        # Save to DB
        saved = await crud.content.upsert(self.db, item, content_hash, collection)
        if saved:
            await self.bloom.mark_seen(content_hash)
        return saved
```

## 5.2 Stats — Dùng lại DB sẵn có

`ExecutionResult` đã có `passed_steps`, `failed_steps`, `run_time_sec`, `error_detail`.  
Content items count lấy bằng cách join `content_items.execution_id`.

Chỉ cần thêm 2 thứ còn thiếu:

**a) LLM fallback counter** — ghi vào `Execution.meta` (JSON column sẵn có):
```python
# Khi LLM fallback trigger trong extraction.py:
execution.meta["llm_fallbacks"] = execution.meta.get("llm_fallbacks", 0) + 1
```

**b) Stats API endpoint** — aggregate từ DB, không cần column mới:

**File**: `api/routes/executions.py` (thêm endpoint)
```python
@router.get("/{id}/stats")
async def get_execution_stats(id: str, db=Depends(get_db)):
    execution = await crud.execution.get(db, id)
    result = await crud.execution_result.get_by_execution(db, id)
    content_count = await crud.content.count_by_execution(db, id)
    return {
        "execution_id": id,
        "status": execution.status,
        "run_time_sec": result.run_time_sec if result else None,
        "steps": {
            "passed": len(result.passed_steps) if result else 0,
            "failed": len(result.failed_steps) if result else 0,
        },
        "content": {
            "extracted": content_count,
            # deduped_skipped không track được từ DB (skip xảy ra trước khi lưu)
            # → track qua Execution.meta["deduped_count"] (increment khi skip)
            "deduped_skipped": execution.meta.get("deduped_count", 0),
        },
        "llm_fallbacks": execution.meta.get("llm_fallbacks", 0),
    }
```

**Không cần migration** — tất cả dùng `Execution.meta` JSON column sẵn có.

> Track dedup trong `content_store.save()`: khi Bloom filter trả `is_duplicate=True`, tăng `execution.meta["deduped_count"] += 1`.

## 5.3 Content Change Detection

Detect when previously crawled content changes (post edited, comment deleted).

**File**: `services/change_detector.py` (new)

```python
import hashlib

class ChangeDetector:
    """
    Re-crawl known items and detect diffs.
    Store diff history for audit trail.
    """
    async def check_for_changes(self, db, item: ExtractedItem) -> bool:
        existing = await crud.content.find_by_raw_key(db, item.raw_key)
        if not existing:
            return False  # new item, not a change
        
        new_hash = xxhash.xxh64(item.body.encode()).hexdigest()  # nhất quán với Phase 0
        if existing.content_hash == new_hash:
            return False  # unchanged
        
        # Record change
        await crud.content.record_change(db, existing.id, {
            "previous_body": existing.body,
            "new_body": item.body,
            "previous_likes": existing.likes_count,
            "new_likes": item.likes_count,
            "changed_at": datetime.utcnow(),
        })
        
        # Update content
        await crud.content.update_content(db, existing.id, item)
        return True
```

**DB migration**: Add `content_changes` table:
```sql
CREATE TABLE content_changes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content_item_id UUID REFERENCES content_items(id),
    previous_body TEXT,
    new_body TEXT,
    previous_likes_count INTEGER,
    new_likes_count INTEGER,
    changed_at TIMESTAMP DEFAULT now()
);
```

## Files Summary

| File | Action |
|------|--------|
| `services/change_detector.py` | New — content change tracking |
| `services/content_store.py` | Modify — add Bloom filter dedup |
| `tasks/scenario/steps/extraction.py` | Modify — increment `meta.llm_fallbacks` |
| `api/routes/executions.py` | Modify — add `/{id}/stats` endpoint |
| `db/crud/content.py` | Modify — add `count_by_execution`, `count_deduped_by_execution` |
| `db/models/content_change.py` | New — change history model |

## Dependencies

```toml
# No new deps — redis already in Phase 1
# RedisStack for Bloom filter (change docker image)
```

## Docker: Enable RedisStack (for Bloom filter)

```yaml
# docker-compose.yml
redis:
  image: redis/redis-stack:latest  # includes RedisBloom, RedisJSON, RediSearch
  ports:
    - "6379:6379"
    - "8001:8001"  # RedisInsight UI
```
