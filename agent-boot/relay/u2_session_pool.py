"""
relay/u2_session_pool.py — Persistent per-device uiautomator2 session pool.

Keeps a warm u2.Device connection per serial so that batch/flow actions
skip per-call TCP setup.  Idle sessions are reaped after SESSION_TTL_SECONDS.

Feature-gated: only instantiated when U2_BATCH_ENABLED=true.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

SESSION_TTL_SECONDS = 300.0
REAP_INTERVAL_SECONDS = 30.0
CONNECT_TIMEOUT_SECONDS = 8.0


@dataclass
class _Entry:
    device: Any
    last_used: float
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    serial: str = ""


class U2SessionPool:
    """Thread-safe (asyncio) pool of persistent uiautomator2.Device sessions."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        connect_fn: Optional[Callable] = None,
    ) -> None:
        self._loop = loop
        self._connect_fn = connect_fn
        self._sessions: dict[str, _Entry] = {}
        self._global_lock = asyncio.Lock()
        self._reaper_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        self._reaper_task = self._loop.create_task(self._reap_loop())

    async def stop(self) -> None:
        if self._reaper_task:
            self._reaper_task.cancel()
        async with self._global_lock:
            for entry in self._sessions.values():
                self._close_blocking(entry)
            self._sessions.clear()

    async def get_session(self, serial: str) -> Any:
        async with self._global_lock:
            entry = self._sessions.get(serial)
        if entry is None:
            entry = await self._connect(serial)
        async with entry.lock:
            if not await self._is_alive(entry):
                await self._reconnect(entry)
            entry.last_used = time.monotonic()
        return entry.device

    async def evict(self, serial: str) -> None:
        async with self._global_lock:
            entry = self._sessions.pop(serial, None)
        if entry:
            self._close_blocking(entry)
            logger.info("u2-pool: evicted serial=%s", serial)

    # ── internals ──────────────────────────────────────────────────────────────

    def _get_connect_fn(self) -> Callable:
        if self._connect_fn:
            return self._connect_fn
        try:
            import uiautomator2 as u2
            return u2.connect
        except ImportError:
            logger.error("u2-pool: uiautomator2 not installed — pool disabled")
            raise

    async def _connect(self, serial: str) -> _Entry:
        fn = self._get_connect_fn()
        host = serial.rsplit(":", 1)[0] if ":" in serial else serial
        dev = await asyncio.wait_for(
            self._loop.run_in_executor(None, fn, host),
            timeout=CONNECT_TIMEOUT_SECONDS,
        )
        entry = _Entry(device=dev, last_used=time.monotonic(), serial=serial)
        async with self._global_lock:
            if serial not in self._sessions:
                self._sessions[serial] = entry
            else:
                self._close_blocking(entry)
                entry = self._sessions[serial]
        logger.info("u2-pool: connected serial=%s", serial)
        return entry

    async def _reconnect(self, entry: _Entry) -> None:
        self._close_blocking(entry)
        fn = self._get_connect_fn()
        host = entry.serial.rsplit(":", 1)[0] if ":" in entry.serial else entry.serial
        entry.device = await self._loop.run_in_executor(None, fn, host)
        logger.info("u2-pool: reconnected serial=%s", entry.serial)

    async def _is_alive(self, entry: _Entry) -> bool:
        try:
            return bool(
                await self._loop.run_in_executor(
                    None, lambda: entry.device.alive
                )
            )
        except Exception as exc:
            logger.debug("u2-pool: ping failed serial=%s err=%s", entry.serial, exc)
            return False

    def _close_blocking(self, entry: _Entry) -> None:
        try:
            if hasattr(entry.device, "stop"):
                entry.device.stop()
        except Exception:
            pass

    async def _reap_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(REAP_INTERVAL_SECONDS)
                now = time.monotonic()
                stale: list[str] = []
                async with self._global_lock:
                    for s, e in self._sessions.items():
                        if now - e.last_used > SESSION_TTL_SECONDS:
                            stale.append(s)
                for s in stale:
                    await self.evict(s)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning("u2-pool: reaper error %s", exc)
