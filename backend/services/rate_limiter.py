"""Sliding-window rate limiter for per-account platform activity.

Scope: per (platform, account_id, action_type) quotas to avoid triggering
platform bans. Uses a Redis sorted set with timestamp scores. Graceful no-op
when Redis is disabled.

Limits are keyed by action type because the safe volumes differ by an order of
magnitude: an account can read and like all day, but a connection request is the
scarcest, most scrutinised action it performs. A single blended quota would
either throttle browsing pointlessly or let friend requests run far too hot.

Usage:
    allowed = await rate_limiter.allow("platform", account_id, "connection_request")
    if not allowed:
        await rate_limiter.wait("platform", account_id)
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Dict, Mapping

from services import redis_store

log = logging.getLogger(__name__)


# Window sizes in seconds, keyed by the short suffix used in the Redis key.
_WINDOWS: dict[str, int] = {"m": 60, "h": 3600, "d": 86_400}
_LIMIT_FIELDS: dict[str, str] = {
    "m": "per_minute",
    "h": "per_hour",
    "d": "per_day",
}

# Default limits — override via config.yaml → anti_detection.rate_limits.
#
# `default` applies to any action without its own entry. Connection requests are
# deliberately far tighter: they are the action platforms police hardest, and a
# new account sending them at browsing speed is the clearest possible signal.
#
# Commenting gets its own bucket, well below `default`. A real run on 20/08 put
# 9 comments on the feed in 2 minutes 27 seconds because this step consulted no
# limiter at all — `default` would have allowed 200 an hour, which is still
# spam-rate for a human. Liking is cheaper and sits between the two: it is the
# ordinary browsing gesture, and pacing it at comment speed would make an
# account look stranger, not safer.
_DEFAULT_LIMITS: Dict[str, Dict[str, Dict[str, int]]] = {
    "instagram": {
        "default": {"per_minute": 5, "per_hour": 100, "per_day": 500},
        "connection_request": {"per_minute": 1, "per_hour": 6, "per_day": 20},
        "content_comment": {"per_minute": 1, "per_hour": 6, "per_day": 25},
        "content_like": {"per_minute": 3, "per_hour": 40, "per_day": 200},
    },
    "tiktok": {
        "default": {"per_minute": 8, "per_hour": 150, "per_day": 700},
        "connection_request": {"per_minute": 1, "per_hour": 8, "per_day": 25},
        "content_comment": {"per_minute": 1, "per_hour": 8, "per_day": 30},
        "content_like": {"per_minute": 4, "per_hour": 60, "per_day": 300},
    },
    "threads": {
        "default": {"per_minute": 5, "per_hour": 100, "per_day": 500},
        "connection_request": {"per_minute": 1, "per_hour": 6, "per_day": 20},
        "content_comment": {"per_minute": 1, "per_hour": 6, "per_day": 25},
        "content_like": {"per_minute": 3, "per_hour": 40, "per_day": 200},
    },
    "linkedin": {
        "default": {"per_minute": 4, "per_hour": 80, "per_day": 300},
        "connection_request": {"per_minute": 1, "per_hour": 5, "per_day": 15},
        "content_comment": {"per_minute": 1, "per_hour": 5, "per_day": 20},
        "content_like": {"per_minute": 2, "per_hour": 30, "per_day": 150},
    },
}

# Action types the scan-and-interact step reports under, so the step and the
# limiter cannot drift apart on spelling.
ACTION_CONTENT_COMMENT = "content_comment"
ACTION_CONTENT_LIKE = "content_like"

DEFAULT_ACTION = "default"

# Module-level limits dict, overridable via configure().
_LIMITS: Dict[str, Dict[str, Dict[str, int]]] = {
    platform: {action: dict(values) for action, values in actions.items()}
    for platform, actions in _DEFAULT_LIMITS.items()
}


def _normalize_platform_limits(raw: Mapping[str, object]) -> Dict[str, Dict[str, int]]:
    """Accept both the flat legacy shape and the per-action shape.

    Legacy flat config such as ``platform: {per_hour: 200}`` means "the default
    action's limits", so existing deployments keep working unchanged.
    """
    flat = {
        key: int(value)
        for key, value in raw.items()
        if isinstance(value, (int, float)) and key in _LIMIT_FIELDS.values()
    }
    nested = {
        str(action): {
            field: int(amount)
            for field, amount in dict(values).items()
            if field in _LIMIT_FIELDS.values()
        }
        for action, values in raw.items()
        if isinstance(values, Mapping)
    }
    if flat:
        nested.setdefault(DEFAULT_ACTION, {}).update(flat)
    return nested


def configure(limits: Mapping[str, Mapping[str, object]]) -> None:
    """Override defaults at startup from config.yaml."""
    global _LIMITS
    _LIMITS = {
        str(platform).strip().casefold(): _normalize_platform_limits(actions)
        for platform, actions in limits.items()
    }


def limits_for(platform: str, action_type: str = DEFAULT_ACTION) -> Dict[str, int]:
    """Effective limits for one action, falling back to the platform default."""
    platform_limits = _LIMITS.get(str(platform or "").strip().casefold(), {})
    merged = dict(platform_limits.get(DEFAULT_ACTION, {}))
    merged.update(platform_limits.get(str(action_type or "").strip().casefold(), {}))
    return merged


def _key(platform: str, account_id: str, action_type: str, window: str) -> str:
    """Scoped Redis key. `window` is 'm' (minute), 'h' (hour) or 'd' (day)."""
    return redis_store.key(
        f"ratelimit:{platform}:{account_id}:{action_type}:{window}"
    )


async def allow(
    platform: str,
    account_id: str,
    action_type: str = DEFAULT_ACTION,
) -> bool:
    """Return True if the action is allowed; records it on success.

    If Redis is disabled, returns True (no limiting). Not raising keeps the farm
    functional on boxes without Redis at the cost of detection risk.
    """
    if not redis_store.enabled():
        return True
    client = redis_store.client()
    if client is None:
        return True

    action = str(action_type or DEFAULT_ACTION).strip().casefold() or DEFAULT_ACTION
    limits = limits_for(platform, action)
    active = {
        suffix: int(limits.get(field, 0) or 0)
        for suffix, field in _LIMIT_FIELDS.items()
        if int(limits.get(field, 0) or 0) > 0
    }
    if not active:
        return True

    now = time.time()
    keys = {
        suffix: _key(platform, account_id, action, suffix) for suffix in active
    }
    try:
        pipe = client.pipeline()
        for suffix, key in keys.items():
            start = now - _WINDOWS[suffix]
            pipe.zremrangebyscore(key, 0, start)
            pipe.zcount(key, start, now)
        results = await pipe.execute()
    except Exception as exc:
        log.warning("rate_limiter: Redis pipeline failed (%s) — allowing", exc)
        return True

    # Two results per window, in insertion order: (removed, count).
    counts = {
        suffix: int(results[index * 2 + 1] or 0)
        for index, suffix in enumerate(keys)
    }
    for suffix, cap in active.items():
        if counts.get(suffix, 0) >= cap:
            log.info(
                "rate_limiter: %s/%s/%s %s cap %d reached",
                platform,
                account_id,
                action,
                _LIMIT_FIELDS[suffix],
                cap,
            )
            return False

    try:
        member = f"{now:.6f}:{random.randint(0, 1_000_000)}"
        pipe = client.pipeline()
        for suffix, key in keys.items():
            pipe.zadd(key, {member: now})
            # Double the window so a boundary read still sees the full history.
            pipe.expire(key, _WINDOWS[suffix] * 2)
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


async def check_or_wait(
    platform: str,
    account_id: str,
    action_type: str = DEFAULT_ACTION,
) -> None:
    """Convenience: block until an action is allowed."""
    if await allow(platform, account_id, action_type):
        return
    await wait(platform, account_id)
