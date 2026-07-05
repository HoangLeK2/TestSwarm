"""Device-level manual takeover state.

Execution pause/cancel flags are scoped to one execution. Manual takeover is
scoped to a device: while enabled, manual input is allowed even though a paused
scenario may still report ``scenario_active``.
"""
from __future__ import annotations

import logging
import time
from typing import Final

log = logging.getLogger(__name__)

_TTL_SEC: Final[int] = 12 * 3600
_LOCAL: dict[str, float] = {}


def _normalize_serial(serial: str | None) -> str:
    return str(serial or "").strip()


def _key(serial: str) -> str:
    return f"device:{serial}:manual_takeover"


def is_manual_takeover_local(serial: str | None) -> bool:
    serial = _normalize_serial(serial)
    if not serial:
        return False
    expiry = _LOCAL.get(serial)
    if expiry is None:
        return False
    if expiry > time.monotonic():
        return True
    _LOCAL.pop(serial, None)
    return False


async def is_manual_takeover_active(serial: str | None) -> bool:
    serial = _normalize_serial(serial)
    if not serial:
        return False
    if is_manual_takeover_local(serial):
        return True
    try:
        from services.redis_store import client, enabled, key

        if not enabled():
            return False
        r = client()
        if r is None:
            return False
        return bool(await r.exists(key(_key(serial))))
    except Exception as exc:
        log.debug("is_manual_takeover_active redis: %s", exc)
        return False


async def set_manual_takeover(serial: str | None) -> None:
    serial = _normalize_serial(serial)
    if not serial:
        return
    _LOCAL[serial] = time.monotonic() + _TTL_SEC
    try:
        from services.redis_store import client, enabled, key

        if enabled():
            await client().setex(key(_key(serial)), _TTL_SEC, "1")
    except Exception as exc:
        log.debug("set_manual_takeover redis: %s", exc)


async def clear_manual_takeover(serial: str | None) -> None:
    serial = _normalize_serial(serial)
    if not serial:
        return
    _LOCAL.pop(serial, None)
    try:
        from services.redis_store import client, enabled, key

        if enabled():
            await client().delete(key(_key(serial)))
    except Exception as exc:
        log.debug("clear_manual_takeover redis: %s", exc)
