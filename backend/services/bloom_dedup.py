"""Phase 5 — Bloom filter dedup via RedisBloom (RedisStack module).

Two-layer dedup:
  1. Bloom filter (Redis, probabilistic) — skip DB when obviously duplicate
  2. DB unique constraint (content_hash + collection) — authoritative

Graceful no-op when:
  - Redis disabled
  - RedisBloom module not loaded (redis:alpine → use redis/redis-stack instead)

Uses xxhash.xxh64 (Phase 0 dep) so members are 16-char hex; SHA256 content_hash
fingerprints are also accepted directly.
"""
from __future__ import annotations

import logging
from typing import Optional

from services import redis_store

log = logging.getLogger(__name__)

# Module singletons (one filter per bucket).
_FILTERS_RESERVED: set[str] = set()
_BLOOM_AVAILABLE: Optional[bool] = None


async def _detect_bloom_support() -> bool:
    """True if RedisBloom module is loaded. Cached per process."""
    global _BLOOM_AVAILABLE
    if _BLOOM_AVAILABLE is not None:
        return _BLOOM_AVAILABLE
    if not redis_store.enabled():
        _BLOOM_AVAILABLE = False
        return False
    client = redis_store.client()
    if client is None:
        _BLOOM_AVAILABLE = False
        return False
    try:
        modules = await client.execute_command("MODULE", "LIST")
        # MODULE LIST returns list of [["name", "bf", "ver", ...], ...]
        names = set()
        for mod in modules or []:
            if isinstance(mod, (list, tuple)) and len(mod) >= 2:
                # Format: b"name", b"bf"
                try:
                    names.add(mod[1].decode() if isinstance(mod[1], bytes) else str(mod[1]))
                except Exception:
                    continue
        _BLOOM_AVAILABLE = "bf" in names
        if not _BLOOM_AVAILABLE:
            log.info(
                "bloom_dedup: RedisBloom module not loaded — running without Bloom fast-path. "
                "Install redis/redis-stack image to enable."
            )
    except Exception as exc:
        if "different loop" in str(exc) or "attached to a different" in str(exc):
            # Called from asyncio.run() in a worker thread — Redis client bound to main loop.
            # Don't permanently disable; just skip bloom for this call.
            log.debug("bloom_dedup: skipping (wrong event loop) — DB dedup used instead")
            return False
        log.warning("bloom_dedup: module detection failed (%s) — disabling", exc)
        _BLOOM_AVAILABLE = False
    return _BLOOM_AVAILABLE


def _filter_key(bucket: str) -> str:
    return redis_store.key(f"bloom:{bucket}")


async def _ensure_filter(bucket: str, capacity: int = 10_000_000, error_rate: float = 0.001) -> None:
    """Create Bloom filter if missing. Called lazily from is_duplicate/mark_seen."""
    key = _filter_key(bucket)
    if key in _FILTERS_RESERVED:
        return
    client = redis_store.client()
    if client is None:
        return
    try:
        await client.execute_command("BF.RESERVE", key, error_rate, capacity)
    except Exception as exc:
        # "item exists" is OK; only record other failures.
        msg = str(exc).lower()
        if "exists" not in msg:
            log.debug("BF.RESERVE %s failed (%s)", key, exc)
    _FILTERS_RESERVED.add(key)


async def is_duplicate(bucket: str, content_hash: str) -> bool:
    """True if content_hash *probably* already saved. False if definitely new."""
    if not await _detect_bloom_support():
        return False
    client = redis_store.client()
    if client is None:
        return False
    await _ensure_filter(bucket)
    try:
        res = await client.execute_command("BF.EXISTS", _filter_key(bucket), content_hash)
        return bool(int(res))
    except Exception as exc:
        log.debug("bloom_dedup: BF.EXISTS failed (%s)", exc)
        return False


async def mark_seen(bucket: str, content_hash: str) -> None:
    """Record content_hash so future is_duplicate(hash) returns True."""
    if not await _detect_bloom_support():
        return
    client = redis_store.client()
    if client is None:
        return
    await _ensure_filter(bucket)
    try:
        await client.execute_command("BF.ADD", _filter_key(bucket), content_hash)
    except Exception as exc:
        log.debug("bloom_dedup: BF.ADD failed (%s)", exc)
