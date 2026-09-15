"""Thin async Redis client wrapper for Device Farm shared state."""
from __future__ import annotations

import asyncio
import logging
import threading
import weakref

from core.config import RedisConfig

log = logging.getLogger(__name__)

_url: str | None = None
_prefix: str = "df:"

# One client per event loop.
#
# redis-py pools connections bound to the loop that opened them, while activities
# run on their own short-lived asyncio.run() loop. A single shared client hands an
# activity a connection whose futures live on the API loop ("got Future attached to
# a different loop"), and the connection the activity opens outlives its loop inside
# the pool — poisoning it for everyone afterwards. Callers swallow that error and
# fall back to "allow", so the failure is silent: the rate limiter stops limiting.
#
# Keyed by the loop object, not id(loop): CPython recycles addresses, so a freshly
# created loop can land on a dead one's id and inherit its client — the same bug
# again, now harder to see. The weak keys also drop entries when a loop is GC'd.
_clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, object]" = (
    weakref.WeakKeyDictionary()
)
# The rare caller with no running loop keeps one shared client, as before.
_no_loop_client = None
_clients_lock = threading.Lock()


def _new_client(url: str):
    import redis.asyncio as aioredis

    return aioredis.from_url(url, decode_responses=True)


def _running_loop():
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def _lookup():
    loop = _running_loop()
    if loop is None:
        return _no_loop_client
    return _clients.get(loop)


def _store(created):
    """Bind a client to the current loop (or the loop-less bucket)."""
    global _no_loop_client
    loop = _running_loop()
    with _clients_lock:
        if loop is None:
            _no_loop_client = created
        else:
            _clients[loop] = created


def _pop():
    """Detach and return the current loop's client, if any."""
    global _no_loop_client
    loop = _running_loop()
    with _clients_lock:
        if loop is None:
            existing, _no_loop_client = _no_loop_client, None
            return existing
        return _clients.pop(loop, None)


async def init(cfg: RedisConfig) -> None:
    """Connect to Redis. No-op if disabled."""
    global _url, _prefix
    if not cfg.enabled:
        log.info("Redis disabled")
        return
    _prefix = cfg.prefix
    try:
        client = _new_client(cfg.url)
        await client.ping()
    except Exception as exc:
        log.warning("Redis connection failed (running without Redis): %s", exc)
        return
    _url = cfg.url
    _store(client)
    log.info("Redis connected: %s", cfg.url)


def enabled() -> bool:
    """True once a reachable Redis was configured — independent of the loop."""
    return _url is not None


def client():
    """Client bound to the *current* event loop, created on first use.

    `from_url` opens no socket, so a per-loop client costs nothing until the first
    command; disposal happens in `dispose_loop_client`.
    """
    if _url is None:
        return None
    existing = _lookup()
    if existing is not None:
        return existing
    created = _new_client(_url)
    _store(created)
    return created


def key(name: str) -> str:
    return f"{_prefix}{name}"


async def dispose_loop_client() -> None:
    """Release this loop's client before the loop closes.

    Weak keys would drop the entry eventually; this closes the socket now, while
    the loop is still alive to run the close.
    """
    existing = _pop()
    if existing is not None:
        try:
            await existing.aclose()
        except Exception:
            pass


async def close() -> None:
    global _url, _no_loop_client
    with _clients_lock:
        clients = list(_clients.values())
        if _no_loop_client is not None:
            clients.append(_no_loop_client)
        _clients.clear()
        _no_loop_client = None
        _url = None
    for existing in clients:
        try:
            await existing.aclose()
        except Exception:
            pass
