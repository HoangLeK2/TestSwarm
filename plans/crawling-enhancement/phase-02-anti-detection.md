# Phase 2: Anti-Detection & Rate Limiting

## Objective

Prevent device/account bans through: delay jitter between actions, account rotation pool, device rotation, per-app rate limiting, session warming. Mobile-specific anti-detection (different from web proxy rotation).

## Problem

Current system runs steps with no delay between actions = bot-like behavior. Single account = fast ban if posting volume is high. No rate limits = platform blocks device.

## Implementation

### 2.1 Delay Jitter Between Steps

**File**: `tasks/scenario_task.py`

```python
import random, asyncio

async def run_step_with_jitter(ctx, step, idx, jitter_config):
    min_ms = jitter_config.get("min_ms", 500)
    max_ms = jitter_config.get("max_ms", 2000)
    
    result = await run_step(ctx, step, idx)
    
    # Jitter after each step
    delay = random.uniform(min_ms, max_ms) / 1000
    await asyncio.sleep(delay)
    return result
```

**Config** (campaign-level, in scenario variables):
```json
{
  "jitter": {
    "min_ms": 800,
    "max_ms": 3000,
    "scroll_extra_ms": 1500
  }
}
```

**Gesture jitter** (`tasks/scenario/steps/interaction.py`):
- Tap: randomize x,y by ±5px
- Scroll: randomize duration by ±200ms
- Input: type character-by-character with 80-200ms delays

```python
async def human_like_input(device, text: str):
    for char in text:
        await device.send_keys(char)
        await asyncio.sleep(random.uniform(0.08, 0.2))
```

### 2.2 Account Rotation Pool

**`db/models/account.py` và `services/account_manager.py` ĐÃ TỒN TẠI** và đầy đủ hơn plan:
- `Account` model có: `cooldown_until`, `status` (active/cooldown/banned/disabled), `usage_today_minutes`, `total_usage_minutes`, `DeviceAccount` join table, Fernet-encrypted password
- `account_manager.py` có: `start_account_usage()`, `end_account_usage()`, `check_and_reset_cooldowns()`, `reset_daily_usage()`

**Chỉ cần thêm**: `get_available_account(db, platform)` query vào `db/crud/account.py`:

```python
# db/crud/account.py (thêm function)
from datetime import datetime, timezone
from sqlalchemy import select, and_

async def get_available_account(db, platform: str):
    """Pick least-recently-used active account for platform, not in cooldown."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Account)
        .where(and_(
            Account.platform == platform,
            Account.status == "active",
            (Account.cooldown_until == None) | (Account.cooldown_until < now)
        ))
        .order_by(Account.last_used_at.asc().nullsfirst())
        .limit(1)
    )
    return result.scalar_one_or_none()
```

Sau khi dùng account, gọi `account_manager.start_account_usage(account_id)` và `end_account_usage(account_id, duration_minutes)` — đã có sẵn.

### 2.3 Device Rotation

**File**: `services/campaign_dispatch.py` (modify)

```python
async def route_with_rotation(campaign_id, scenario, device_pool):
    """
    For long campaigns: rotate devices to avoid triggering 
    per-device detection thresholds.
    """
    devices = await device_pool.get_available_devices()
    
    # Assign accounts to devices for this campaign
    assignments = []
    for device in devices:
        account = await account_pool.get_available(
            platform=scenario.platform,
            campaign_id=campaign_id
        )
        if account:
            assignments.append((device, account))
    
    # Distribute work evenly
    for i, (device, account) in enumerate(assignments):
        task_slice = get_slice(campaign_id, i, len(assignments))
        await queue.enqueue({
            "campaign_id": campaign_id,
            "device_id": device.serial,
            "account_id": account.id,
            "scenario_id": scenario.id,
            "slice": task_slice
        })
```

### 2.4 Per-App Rate Limiting

**File**: `services/rate_limiter.py` (new)

```python
import redis.asyncio as aioredis
import time

class RateLimiter:
    """
    Sliding window rate limiter per (platform, account_id).
    Uses Redis sorted set: key=limiter:{platform}:{account_id}, 
    score=timestamp, member=request_id
    """
    def __init__(self, redis: aioredis.Redis):
        self.redis = redis
        self.limits = {
            "facebook": {"per_hour": 200, "per_minute": 10},
            "instagram": {"per_hour": 100, "per_minute": 5},
            "tiktok":    {"per_hour": 150, "per_minute": 8},
        }

    async def check_and_record(self, platform: str, account_id: str) -> bool:
        """Returns True if request allowed, False if rate limited"""
        key = f"limiter:{platform}:{account_id}"
        now = time.time()
        window_start = now - 3600  # 1 hour window
        
        pipe = self.redis.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zadd(key, {str(now): now})
        pipe.zcount(key, window_start, now)
        pipe.expire(key, 3600)
        results = await pipe.execute()
        
        count = results[2]
        limit = self.limits.get(platform, {}).get("per_hour", 100)
        return count <= limit

    async def wait_if_needed(self, platform: str, account_id: str):
        allowed = await self.check_and_record(platform, account_id)
        if not allowed:
            # Back off 60 seconds
            import asyncio
            await asyncio.sleep(60 + random.uniform(0, 30))
```

### 2.5 Session Warming

**File**: `tasks/scenario/steps/navigation.py` (add warm step)

Before starting extraction, warm the session:
```python
async def warm_session(ctx, platform: str, warm_steps: int = 3):
    """
    Browse feed casually before extraction.
    Mimics human opening app and scrolling naturally.
    """
    for _ in range(warm_steps):
        scroll_amount = random.randint(300, 800)
        await ctx.device.swipe(540, 1500, 540, 1500 - scroll_amount, 
                               duration=random.uniform(0.3, 0.8))
        await asyncio.sleep(random.uniform(1.5, 4.0))
```

Add `warm_session` as a step type in the step registry:
```json
{
  "type": "warm_session",
  "platform": "facebook",
  "warm_steps": 3
}
```

## Files to Create/Modify

| File | Action | Notes |
|------|--------|-------|
| `tasks/scenario_task.py` | Modify | Add jitter after each step |
| `tasks/scenario/steps/interaction.py` | Modify | Human-like input, gesture jitter |
| `tasks/scenario/steps/navigation.py` | Modify | Add warm_session step type |
| `services/rate_limiter.py` | New | Sliding window rate limiter (fallback graceful nếu Redis off) |
| `services/fleet_dispatch.py` | Modify | Device + account rotation dùng `get_available_account()` |
| `db/crud/account.py` | Modify | Thêm `get_available_account()` — CRUD file có thể đã tồn tại |
| `core/config.py` | Modify | Add jitter defaults, rate limit config |

> **Không cần tạo**: `db/models/account.py` (đã có), `services/account_pool.py` (dùng `account_manager.py` sẵn), `db/models/account.py` migration (đã tồn tại)

## Configuration Example

```yaml
# config.yaml
anti_detection:
  jitter:
    enabled: true
    step_min_ms: 800
    step_max_ms: 3000
    scroll_extra_ms: 1500
  session_warm:
    enabled: true
    warm_steps: 3
  rate_limits:
    facebook:
      per_hour: 200
      per_minute: 10
    instagram:
      per_hour: 100
      per_minute: 5
```

## Risks

- Jitter increases campaign duration (acceptable; mitigate with more devices)
- Account pool requires managing login state on device — accounts must be pre-logged-in before campaign starts
- Rate limiter depends on Redis (Phase 1 dependency)
