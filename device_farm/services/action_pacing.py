"""Pacing gate for account actions performed on a device.

The sliding-window limiter in :mod:`services.rate_limiter` has existed for a
while but had no callers, so the only thing bounding how fast an account acted
was whatever `target_count` a scenario happened to set. This module is the
synchronous entry point scenario steps call before touching the device.

Two separate protections:

* a hard cap per minute/hour/day, per action type (the limiter), and
* jitter between consecutive actions, because a perfectly regular cadence is
  itself a signal regardless of volume.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any

from services.platform_readiness import DEFAULT_PLATFORM

log = logging.getLogger(__name__)

# Applied before an action, not after, so the pause also covers the case where
# the previous step finished early.
_DEFAULT_JITTER_RANGE_S = (0.4, 1.8)


def _jitter_seconds(jitter_range: tuple[float, float] | None) -> float:
    low, high = jitter_range or _DEFAULT_JITTER_RANGE_S
    low = max(0.0, float(low))
    high = max(low, float(high))
    return random.uniform(low, high)


def check_action_allowed(
    *,
    identity: dict[str, str | None],
    action_type: str,
    platform: str = DEFAULT_PLATFORM,
) -> dict[str, Any]:
    """Whether this account may perform ``action_type`` right now.

    Returns ``{"allowed": bool, "reason": str, "limits": {...}}``. Never raises
    on infrastructure problems: if the limiter or the database is unreachable
    the action is allowed, matching the limiter's own fail-open stance — the
    alternative is a farm that stops working whenever Redis blips.
    """
    resolved_platform = str(platform or DEFAULT_PLATFORM).strip().casefold()
    action = str(action_type or "").strip().casefold()

    # Without Redis the limiter is a no-op, so resolving the tenant would be a
    # database round-trip per action that can only ever answer "allowed".
    try:
        from services import redis_store

        if not redis_store.enabled():
            return {
                "allowed": True,
                "reason": "limiter_disabled",
                "action_type": action,
                "platform": resolved_platform,
            }
    except Exception:
        pass

    try:
        from db.database import activity_session, run_activity_coro_blocking
        from services import rate_limiter
        from services.account_actions.coordinator import _resolve_tenant

        async def check() -> dict[str, Any]:
            async with activity_session() as db:
                _org_id, account_id, _, _ = await _resolve_tenant(
                    db, identity, require_ids=False
                )
            allowed = await rate_limiter.allow(
                resolved_platform, account_id, action
            )
            return {
                "allowed": bool(allowed),
                "reason": "" if allowed else "rate_limited",
                "account_id": account_id,
                "action_type": action,
                "platform": resolved_platform,
                "limits": rate_limiter.limits_for(resolved_platform, action),
            }

        return run_activity_coro_blocking(check())
    except Exception as exc:
        log.warning(
            "action_pacing: check failed for %s/%s (%s) — allowing",
            resolved_platform,
            action,
            exc,
        )
        return {
            "allowed": True,
            "reason": "pacing_unavailable",
            "action_type": action,
            "platform": resolved_platform,
            "error": str(exc),
        }


def pace_before_action(jitter_range: tuple[float, float] | None = None) -> float:
    """Sleep a short random interval. Returns the seconds actually slept."""
    delay = _jitter_seconds(jitter_range)
    if delay > 0:
        time.sleep(delay)
    return delay
