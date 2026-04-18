"""Phase 2 — Sliding-window rate limiter for crawl operations.

Scope: per (platform, account_id) quotas to avoid triggering platform bans.
Uses Redis sorted set with timestamp score. Graceful no-op when Redis disabled.

Usage:
    allowed = await rate_limiter.allow("facebook", account_id)
    if not allowed:
        await rate_limiter.wait("facebook", account_id)
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Dict, Mapping

from services import redis_store

log = logging.getLogger(__name__)


# Default limits — override via config.yaml → anti_detection.rate_limits.
# per_hour is the primary gate; per_minute is a burst check.
_DEFAULT_LIMITS: Dict[str, Dict[str, int]] = {
    "facebook": {"per_hour": 200, "per_minute": 10},
    "instagram": {"per_hour": 100, "per_minute": 5},
    "tiktok": {"per_hour": 150, "per_minute": 8},
    "linkedin": {"per_hour": 80, "per_minute": 4},
}

# Module-level limits dict, overridable via configure().
_LIMITS: Dict[str, Dict[str, int]] = dict(_DEFAULT_LIMITS)


def configure(limits: Mapping[str, Mapping[str, int]]) -> None:
    """Override defaults at startup from config.yaml."""
    global _LIMITS
    _LIMITS = {k: dict(v) for k, v in limits.items()}


def _key(platform: str, account_id: str, window: str) -> str:
    """Scoped Redis key. `window` is 'h' for hourly or 'm' for minute."""
    return redis_store.key(f"ratelimit:{platform}:{account_id}:{window}")


async def allow(platform: str, account_id: str) -> bool:
    """Return True if request allowed; records the request on success.

    If Redis is disabled, returns True (no limiting). Not raising keeps the
    crawl functional on boxes without Redis at the cost of detection risk.
    """
    if not redis_store.enabled():
        return True
    client = redis_store.client()
    if client is None:
        return True

    limits = _LIMITS.get(platform, {})
    per_hour = int(limits.get("per_hour", 0))
    per_minute = int(limits.get("per_minute", 0))
    if per_hour <= 0 and per_minute <= 0:
        return True

    now = time.time()
    # Atomic per-window sliding count + record.
    try:
        pipe = client.pipeline()
        hour_key = _key(platform, account_id, "h")
        min_key = _key(platform, account_id, "m")
        hour_start = now - 3600
        min_start = now - 60

        pipe.zremrangebyscore(hour_key, 0, hour_start)
        pipe.zcount(hour_key, hour_start, now)
        pipe.zremrangebyscore(min_key, 0, min_start)
        pipe.zcount(min_key, min_start, now)
        results = await pipe.execute()
        _, hour_count, _, min_count = results
    except Exception as exc:
        log.warning("rate_limiter: Redis pipeline failed (%s) — allowing", exc)
        return True

    if per_hour and hour_count >= per_hour:
        log.info("rate_limiter: %s/%s hour cap %d reached", platform, account_id, per_hour)
        return False
    if per_minute and min_count >= per_minute:
        log.info("rate_limiter: %s/%s minute cap %d reached", platform, account_id, per_minute)
        return False

    # Record this request in both windows.
    try:
        member = f"{now:.6f}:{random.randint(0, 1_000_000)}"
        pipe = client.pipeline()
        pipe.zadd(hour_key, {member: now})
        pipe.expire(hour_key, 3600)
        pipe.zadd(min_key, {member: now})
        pipe.expire(min_key, 120)
        await pipe.execute()
    except Exception as exc:
        log.debug("rate_limiter: record failed (%s) — ignored", exc)

    return True


async def wait(platform: str, account_id: str, max_wait_s: float = 90.0) -> None:
    """Back off when rate-limited, with random jitter.

    Sleeps 60s + random jitter (0-30s) by default, capped at `max_wait_s`.
    """
    delay = min(60.0 + random.uniform(0.0, 30.0), max_wait_s)
    await asyncio.sleep(delay)


async def check_or_wait(platform: str, account_id: str) -> None:
    """Convenience: block until a request is allowed."""
    if await allow(platform, account_id):
        return
    await wait(platform, account_id)
