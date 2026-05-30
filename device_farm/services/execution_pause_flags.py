"""Runtime pause flags so long-running batch activities can stop between steps."""
from __future__ import annotations

import logging
import time
from typing import Final

log = logging.getLogger(__name__)

_TTL_SEC: Final[int] = 7 * 24 * 3600
_LOCAL: dict[str, float] = {}


def _key(execution_id: str) -> str:
    return f"execution:{execution_id}:paused"


async def set_execution_paused(execution_id: str) -> None:
    if not execution_id:
        return
    _LOCAL[execution_id] = time.monotonic() + _TTL_SEC
    try:
        from services.redis_store import client, enabled, key

        if enabled():
            await client().setex(key(_key(execution_id)), _TTL_SEC, "1")
    except Exception as exc:
        log.debug("set_execution_paused redis: %s", exc)


async def clear_execution_paused(execution_id: str) -> None:
    if not execution_id:
        return
    _LOCAL.pop(execution_id, None)
    try:
        from services.redis_store import client, enabled, key

        if enabled():
            await client().delete(key(_key(execution_id)))
    except Exception as exc:
        log.debug("clear_execution_paused redis: %s", exc)


def is_execution_paused_local(execution_id: str | None) -> bool:
    """In-process pause flag (same worker as API)."""
    if not execution_id:
        return False
    expiry = _LOCAL.get(execution_id)
    if expiry is None:
        return False
    if expiry > time.monotonic():
        return True
    _LOCAL.pop(execution_id, None)
    return False


async def is_execution_paused_async(execution_id: str | None) -> bool:
    if is_execution_paused_local(execution_id):
        return True
    try:
        from services.redis_store import client, enabled, key

        if not enabled():
            return False
        r = client()
        if r is None:
            return False
        return bool(await r.exists(key(_key(execution_id))))
    except Exception as exc:
        log.debug("is_execution_paused_async: %s", exc)
        return False
