"""Rate-limit storage backends (Redis + in-memory for tests)."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from threading import Lock

from rate_limit import counters

log = logging.getLogger(__name__)

_MEMORY: dict[str, tuple[int, float]] = {}
_MEMORY_LOCK = Lock()


@dataclass(frozen=True)
class RateLimitState:
    allowed: bool
    limit: int
    remaining: int
    reset_at: int
    retry_after: int
    backend_down: bool = False


class RateLimitStore:
    async def consume(self, key: str, *, limit: int, window_seconds: int) -> RateLimitState:
        raise NotImplementedError


class InMemoryRateLimitStore(RateLimitStore):
    async def consume(self, key: str, *, limit: int, window_seconds: int) -> RateLimitState:
        now = time.time()
        window_start = int(now // window_seconds) * window_seconds
        reset_at = window_start + window_seconds
        bucket_key = f"{key}:{window_start}"
        with _MEMORY_LOCK:
            count, _ = _MEMORY.get(bucket_key, (0, reset_at))
            count += 1
            _MEMORY[bucket_key] = (count, reset_at)
        remaining = max(0, limit - count)
        allowed = count <= limit
        retry_after = max(1, reset_at - int(now))
        if allowed:
            counters.inc_allowed()
        else:
            counters.inc_rejected()
        return RateLimitState(
            allowed=allowed,
            limit=limit,
            remaining=remaining,
            reset_at=reset_at,
            retry_after=retry_after,
        )


class RedisRateLimitStore(RateLimitStore):
    _LUA = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""

    async def consume(self, key: str, *, limit: int, window_seconds: int) -> RateLimitState:
        from services import redis_store

        if not redis_store.enabled():
            counters.inc_backend_down()
            log.warning("Rate limit backend unavailable; failing open")
            return RateLimitState(
                allowed=True,
                limit=limit,
                remaining=limit,
                reset_at=int(time.time()) + window_seconds,
                retry_after=0,
                backend_down=True,
            )
        r = redis_store.client()
        redis_key = redis_store.key(f"rate:{key}")
        try:
            count = int(await r.eval(self._LUA, 1, redis_key, window_seconds))
        except Exception as exc:
            counters.inc_backend_down()
            log.warning("Rate limit backend unavailable; failing open: %s", exc)
            return RateLimitState(
                allowed=True,
                limit=limit,
                remaining=limit,
                reset_at=int(time.time()) + window_seconds,
                retry_after=0,
                backend_down=True,
            )
        ttl = await r.ttl(redis_key)
        reset_at = int(time.time()) + max(1, int(ttl or window_seconds))
        remaining = max(0, limit - count)
        allowed = count <= limit
        retry_after = max(1, reset_at - int(time.time()))
        if allowed:
            counters.inc_allowed()
        else:
            counters.inc_rejected()
        return RateLimitState(
            allowed=allowed,
            limit=limit,
            remaining=remaining,
            reset_at=reset_at,
            retry_after=retry_after,
        )


def get_rate_limit_store() -> RateLimitStore:
    import os

    if os.environ.get("RATE_LIMIT_USE_MEMORY", "").strip().lower() in {"1", "true", "yes"}:
        return InMemoryRateLimitStore()
    return RedisRateLimitStore()


def clear_memory_store() -> None:
    with _MEMORY_LOCK:
        _MEMORY.clear()
