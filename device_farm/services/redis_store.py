"""Thin async Redis client wrapper for Device Farm shared state."""
from __future__ import annotations

import logging
from typing import Optional

from core.config import RedisConfig

log = logging.getLogger(__name__)

_client = None
_prefix: str = "df:"


async def init(cfg: RedisConfig) -> None:
    """Connect to Redis. No-op if disabled."""
    global _client, _prefix
    if not cfg.enabled:
        log.info("Redis disabled")
        return
    _prefix = cfg.prefix
    try:
        import redis.asyncio as aioredis
        _client = aioredis.from_url(cfg.url, decode_responses=True)
        await _client.ping()
        log.info("Redis connected: %s", cfg.url)
    except Exception as exc:
        log.warning("Redis connection failed (running without Redis): %s", exc)
        _client = None


def enabled() -> bool:
    return _client is not None


def client():
    return _client


def key(name: str) -> str:
    return f"{_prefix}{name}"


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
