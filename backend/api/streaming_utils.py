"""Helpers for long-lived streaming responses (SSE, chunked export).

Ensures generators exit promptly when the client disconnects (F5, tab close)
so DB sessions and in-process subscribers are released.

Scope: HTTP streaming only (execution event SSE, content CSV export).
Does NOT apply to device/relay WebSockets (/device-agent, /relay-agent, /ws)
which must stay up 24/7 for phones.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Callable

from starlette.requests import Request


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except Exception:
        return default


# Hard cap so a missed disconnect cannot hold resources forever.
SSE_MAX_DURATION_SEC = max(60, _env_int("SSE_MAX_DURATION_SEC", 7200))
STREAM_DISCONNECT_POLL_SEC = max(0.1, float(os.environ.get("STREAM_DISCONNECT_POLL_SEC", "0.5")))


@asynccontextmanager
async def client_disconnect_scope(request: Request) -> AsyncIterator[asyncio.Event]:
    """Yield an event set when the ASGI client disconnects."""
    disconnected = asyncio.Event()

    async def _watch() -> None:
        try:
            while not disconnected.is_set():
                if await request.is_disconnected():
                    disconnected.set()
                    return
                await asyncio.sleep(STREAM_DISCONNECT_POLL_SEC)
        except asyncio.CancelledError:
            raise
        except Exception:
            disconnected.set()

    watcher = asyncio.create_task(_watch())
    try:
        yield disconnected
    finally:
        disconnected.set()
        watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watcher


def client_gone(disconnected: asyncio.Event) -> bool:
    return disconnected.is_set()


def stream_expired(started_monotonic: float, *, max_seconds: int | None = None) -> bool:
    limit = max_seconds if max_seconds is not None else SSE_MAX_DURATION_SEC
    return (time.monotonic() - started_monotonic) >= float(limit)


async def run_until_disconnect(
    request: Request,
    body: Callable[[asyncio.Event], AsyncIterator[bytes | str]],
    *,
    max_seconds: int | None = None,
) -> AsyncIterator[bytes | str]:
    """Wrap an async generator; stop when the client goes away or max duration hits."""
    started = time.monotonic()
    async with client_disconnect_scope(request) as disconnected:
        async for chunk in body(disconnected):
            if client_gone(disconnected) or stream_expired(started, max_seconds=max_seconds):
                break
            yield chunk
