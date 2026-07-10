"""
relay/u2_session_pool.py — Persistent per-device uiautomator2 session pool.

Keeps a warm u2.Device connection per serial so that batch/flow actions
skip per-call TCP setup.  Idle sessions are reaped after SESSION_TTL_SECONDS.

Reliability (Phase 2 stability work):
  - Heartbeat thread probes every HEARTBEAT_INTERVAL_SECONDS; dead sessions
    are evicted so the next caller reconnects instead of timing out.
  - `.alive` probe always wrapped with wait_for(ALIVE_TIMEOUT_SECONDS) — a
    crashed atx-agent can block the property access for minutes otherwise.
  - `_reconnect` prefers uiautomator2's built-in `reset_uiautomator()` first
    (stops+force-stops+restarts the u2d keeper, library-tested edge cases),
    falls back to a fresh connect if reset is unavailable or fails.

Feature-gated: only instantiated when U2_BATCH_ENABLED=true.
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
import time
from concurrent.futures import Executor
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Optional

logger = logging.getLogger(__name__)

SESSION_TTL_SECONDS       = 300.0
REAP_INTERVAL_SECONDS     = 30.0
CONNECT_TIMEOUT_SECONDS   = 8.0
ALIVE_TIMEOUT_SECONDS     = 3.0    # hard cap on .alive / .running() probes
HEARTBEAT_INTERVAL_SECONDS = 10.0  # how often the pool sweeps live sessions
# Keep warm between rapid extra_data / tap round-trips (scrcpy can briefly kill u2d).
HEARTBEAT_GRACE_AFTER_USE_SECONDS = 45.0
# Skip .alive probe when session was used recently (avoids 3s timeout + reconnect storm).
PREPARE_SKIP_ALIVE_SECONDS = 12.0

# When extra_data collect holds the per-serial lock, nested run_locked must not re-enter.
_active_session: contextvars.ContextVar[tuple[str, "_Entry"] | None] = contextvars.ContextVar(
    "u2_active_session",
    default=None,
)


@dataclass
class _Entry:
    device: Any
    last_used: float
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    serial: str = ""
    generation: int = 0
    keep_warm: bool = False


class U2SessionPool:
    """Thread-safe (asyncio) pool of persistent uiautomator2.Device sessions."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        connect_fn: Optional[Callable] = None,
        executor: Optional[Executor] = None,
    ) -> None:
        self._loop = loop
        self._connect_fn = connect_fn
        self._executor = executor
        self._sessions: dict[str, _Entry] = {}
        self._global_lock = asyncio.Lock()
        self._reaper_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._generation = 0

    def _resolve_executor(self) -> Optional[Executor]:
        """Lazy import of runtime pool so tests can pass `executor=None`."""
        if self._executor is not None:
            return self._executor
        try:
            from relay.runtime import u2_executor_pool
            self._executor = u2_executor_pool()
            return self._executor
        except Exception:
            # Tests / standalone use: fall back to default pool.
            return None

    async def start(self) -> None:
        self._reaper_task = self._loop.create_task(self._reap_loop())
        self._heartbeat_task = self._loop.create_task(self._heartbeat_loop())

    async def stop(self) -> None:
        for task in (self._reaper_task, self._heartbeat_task):
            if task:
                task.cancel()
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

    def has_session(self, serial: str) -> bool:
        """Return whether a warm/live entry exists without touching last_used."""
        return serial in self._sessions

    def mark_keep_warm(self, serial: str, enabled: bool = True) -> bool:
        """Mark an existing session as desired warm without touching last_used."""
        entry = self._sessions.get(serial)
        if entry is None:
            return False
        entry.keep_warm = enabled
        return True

    async def warm_session(self, serial: str, *, keep_warm: bool = True) -> bool:
        """Best-effort preconnect so the first real u2 action does not pay connect cost."""
        try:
            await self._prepare_entry(serial, keep_warm=keep_warm)
            logger.info("u2-pool: warmed serial=%s", serial)
            return True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("u2-pool: warm failed serial=%s err=%s", serial, exc)
            return False

    async def _prepare_entry(self, serial: str, *, keep_warm: bool = False) -> _Entry:
        async with self._global_lock:
            entry = self._sessions.get(serial)
        if entry is None:
            entry = await self._connect(serial, keep_warm=keep_warm)
        else:
            async with entry.lock:
                if keep_warm:
                    entry.keep_warm = True
                recently_used = (
                    time.monotonic() - entry.last_used < PREPARE_SKIP_ALIVE_SECONDS
                )
                if not recently_used and not await self._is_alive(entry):
                    await self._reconnect(entry)
                entry.last_used = time.monotonic()
        return entry

    @asynccontextmanager
    async def session_scope(self, serial: str) -> AsyncIterator[Any]:
        """Hold one u2 session + per-serial lock for a multi-batch collect (avoids heartbeat evict)."""
        active = _active_session.get()
        if active is not None and active[0] == serial:
            yield active[1].device
            return

        entry = await self._prepare_entry(serial)
        token = _active_session.set((serial, entry))
        try:
            async with entry.lock:
                yield entry.device
        finally:
            entry.last_used = time.monotonic()
            _active_session.reset(token)

    async def run_locked(self, serial: str, fn: Callable[[Any], Any]) -> Any:
        """Run sync fn(device) while holding the per-serial session lock (one connect)."""
        started = time.perf_counter()
        ex = self._resolve_executor()
        active = _active_session.get()
        if active is not None and active[0] == serial:
            entry = active[1]
            entry.last_used = time.monotonic()
            exec_started = time.perf_counter()
            try:
                return await self._loop.run_in_executor(ex, fn, entry.device)
            finally:
                total_ms = (time.perf_counter() - started) * 1000.0
                if total_ms >= 1000.0:
                    logger.info(
                        "u2-pool: run_locked timing serial=%s active_scope=true exec_ms=%.1f total_ms=%.1f",
                        serial,
                        (time.perf_counter() - exec_started) * 1000.0,
                        total_ms,
                    )

        prepare_started = time.perf_counter()
        entry = await self._prepare_entry(serial)
        prepare_ms = (time.perf_counter() - prepare_started) * 1000.0
        lock_wait_started = time.perf_counter()
        async with entry.lock:
            lock_wait_ms = (time.perf_counter() - lock_wait_started) * 1000.0
            entry.last_used = time.monotonic()
            exec_started = time.perf_counter()
            try:
                return await self._loop.run_in_executor(ex, fn, entry.device)
            finally:
                exec_ms = (time.perf_counter() - exec_started) * 1000.0
                total_ms = (time.perf_counter() - started) * 1000.0
                if total_ms >= 1000.0:
                    logger.info(
                        "u2-pool: run_locked timing serial=%s prepare_ms=%.1f lock_wait_ms=%.1f exec_ms=%.1f total_ms=%.1f",
                        serial,
                        prepare_ms,
                        lock_wait_ms,
                        exec_ms,
                        total_ms,
                    )

    async def evict(self, serial: str) -> None:
        async with self._global_lock:
            entry = self._sessions.pop(serial, None)
        if entry:
            self._close_blocking(entry)
            logger.info("u2-pool: evicted serial=%s", serial)

    # ── internals ──────────────────────────────────────────────────────────────

    def _next_generation(self) -> int:
        self._generation += 1
        return self._generation

    def _get_connect_fn(self) -> Callable:
        if self._connect_fn:
            return self._connect_fn
        try:
            import uiautomator2 as u2
            return u2.connect
        except ImportError:
            logger.error("u2-pool: uiautomator2 not installed — pool disabled")
            raise

    async def _connect(self, serial: str, *, keep_warm: bool = False) -> _Entry:
        fn = self._get_connect_fn()
        host = serial.rsplit(":", 1)[0] if ":" in serial else serial
        dev = await asyncio.wait_for(
            self._loop.run_in_executor(self._resolve_executor(), fn, host),
            timeout=CONNECT_TIMEOUT_SECONDS,
        )
        entry = _Entry(
            device=dev,
            last_used=time.monotonic(),
            serial=serial,
            generation=self._next_generation(),
            keep_warm=keep_warm,
        )
        async with self._global_lock:
            if serial not in self._sessions:
                self._sessions[serial] = entry
            else:
                self._close_blocking(entry)
                entry = self._sessions[serial]
                if keep_warm:
                    entry.keep_warm = True
        logger.info("u2-pool: connected serial=%s", serial)
        return entry

    async def _reconnect(self, entry: _Entry) -> None:
        """
        Try library-native reset first (it stops/force-stops/restarts the u2d
        keeper and waits until the service is ready). Fall back to close+connect
        if reset is unavailable or fails.
        """
        dev = entry.device
        ex = self._resolve_executor()
        reset_fn = getattr(dev, "reset_uiautomator", None)
        if callable(reset_fn):
            try:
                await asyncio.wait_for(
                    self._loop.run_in_executor(ex, reset_fn),
                    timeout=CONNECT_TIMEOUT_SECONDS * 2,
                )
                if await self._is_alive(entry):
                    entry.generation = self._next_generation()
                    logger.info("u2-pool: reset_uiautomator succeeded serial=%s", entry.serial)
                    return
            except Exception as exc:
                logger.warning(
                    "u2-pool: reset_uiautomator failed serial=%s err=%s — falling back to reconnect",
                    entry.serial, exc,
                )

        self._close_blocking(entry)
        fn = self._get_connect_fn()
        host = entry.serial.rsplit(":", 1)[0] if ":" in entry.serial else entry.serial
        entry.device = await asyncio.wait_for(
            self._loop.run_in_executor(ex, fn, host),
            timeout=CONNECT_TIMEOUT_SECONDS,
        )
        entry.generation = self._next_generation()
        logger.info("u2-pool: reconnected serial=%s", entry.serial)

    async def _is_alive(self, entry: _Entry) -> bool:
        """
        Probe the session with a hard timeout. A crashed u2d (atx-agent) makes
        `.alive` block until TCP keepalive trips (minutes); wrapping in
        wait_for keeps us from hanging the caller.
        """
        try:
            return bool(
                await asyncio.wait_for(
                    self._loop.run_in_executor(
                        self._resolve_executor(), lambda: entry.device.alive
                    ),
                    timeout=ALIVE_TIMEOUT_SECONDS,
                )
            )
        except asyncio.TimeoutError:
            logger.debug(
                "u2-pool: .alive probe timed out after %.1fs serial=%s — treating as dead",
                ALIVE_TIMEOUT_SECONDS, entry.serial,
            )
            return False
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
                        if e.keep_warm:
                            continue
                        if now - e.last_used > SESSION_TTL_SECONDS:
                            stale.append(s)
                for s in stale:
                    await self.evict(s)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning("u2-pool: reaper error %s", exc)

    async def _heartbeat_loop(self) -> None:
        """
        Periodically probe every live session. A session that fails .alive
        here is evicted so the next caller reconnects cleanly instead of
        inheriting a dead one.

        Identity check guards the race where a caller replaces the entry
        (via evict+reconnect) between our snapshot and the evict call — we
        only drop the session if it is *still* the one we probed.
        """
        while True:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
                async with self._global_lock:
                    entries = list(self._sessions.items())
                for serial, entry in entries:
                    probed_generation = entry.generation
                    # Skip sessions currently in use — the in-line probe at
                    # get_session() will catch dead ones.
                    if entry.lock.locked():
                        continue
                    if not await self._is_alive(entry):
                        recently_used = (
                            time.monotonic() - entry.last_used
                            < HEARTBEAT_GRACE_AFTER_USE_SECONDS
                        )
                        if recently_used:
                            try:
                                await self._reconnect(entry)
                            except Exception as exc:
                                logger.debug(
                                    "u2-pool: heartbeat reconnect failed serial=%s err=%s",
                                    serial,
                                    exc,
                                )
                            if await self._is_alive(entry):
                                continue
                            # A reconnect created a fresh generation. Do not
                            # evict it from the same stale heartbeat probe;
                            # the next caller/heartbeat will validate it.
                            if entry.generation != probed_generation:
                                continue
                        async with self._global_lock:
                            current = self._sessions.get(serial)
                            if current is entry and entry.generation == probed_generation:
                                self._sessions.pop(serial, None)
                                self._close_blocking(entry)
                                logger.info(
                                    "u2-pool: heartbeat evicted dead session serial=%s", serial,
                                )
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning("u2-pool: heartbeat error %s", exc)
