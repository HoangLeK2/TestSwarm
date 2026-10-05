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
import os
import time
from collections import deque
from concurrent.futures import Executor
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Optional

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        logger.warning("u2-pool: invalid %s=%r; using %.3f", name, raw, default)
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.warning("u2-pool: invalid %s=%r; using %d", name, raw, default)
        return default


SESSION_TTL_SECONDS = max(1.0, _env_float("U2_SESSION_TTL_SECONDS", 300.0))
REAP_INTERVAL_SECONDS = max(1.0, _env_float("U2_REAP_INTERVAL_SECONDS", 30.0))
CONNECT_TIMEOUT_SECONDS = max(1.0, _env_float("U2_CONNECT_TIMEOUT_SECONDS", 8.0))
ALIVE_TIMEOUT_SECONDS = max(0.1, _env_float("U2_ALIVE_TIMEOUT_SECONDS", 3.0))
HEARTBEAT_INTERVAL_SECONDS = max(1.0, _env_float("U2_HEARTBEAT_INTERVAL_SECONDS", 10.0))
# Keep warm between rapid hierarchy / tap round-trips (scrcpy can briefly kill u2d).
HEARTBEAT_GRACE_AFTER_USE_SECONDS = max(
    0.0,
    _env_float("U2_HEARTBEAT_GRACE_AFTER_USE_SECONDS", 45.0),
)
# Skip .alive probe when session was used recently (avoids 3s timeout + reconnect storm).
PREPARE_SKIP_ALIVE_SECONDS = max(0.0, _env_float("U2_PREPARE_SKIP_ALIVE_SECONDS", 12.0))
KEEP_WARM_TTL_SECONDS = max(0.0, _env_float("U2_KEEP_WARM_TTL_SECONDS", 120.0))
KEEP_WARM_MAX_SESSIONS = max(0, _env_int("U2_KEEP_WARM_MAX_SESSIONS", 12))
HEARTBEAT_MAX_PROBES_PER_TICK = max(
    0,
    _env_int("U2_HEARTBEAT_MAX_PROBES_PER_TICK", 8),
)
HEARTBEAT_SKIP_RECENT_SECONDS = max(
    0.0,
    _env_float("U2_HEARTBEAT_SKIP_RECENT_SECONDS", HEARTBEAT_GRACE_AFTER_USE_SECONDS),
)
HEARTBEAT_RECONNECT_RECENT = _env_bool("U2_HEARTBEAT_RECONNECT_RECENT", False)
DIRECT_HTTP_HEALTH_TTL_SECONDS = max(
    0.0,
    _env_float("U2_DIRECT_HTTP_HEALTH_TTL_SECONDS", 30.0),
)
RESET_UIAUTOMATOR_COOLDOWN_SECONDS = max(
    0.0,
    _env_float("U2_RESET_UIAUTOMATOR_COOLDOWN_SECONDS", 30.0),
)

# Nested operations sharing the per-serial lock must not re-enter.
_active_session: contextvars.ContextVar[tuple[str, "_Entry"] | None] = contextvars.ContextVar(
    "u2_active_session",
    default=None,
)


async def _await_executor_completion(future: asyncio.Future[Any]) -> Any:
    """Preserve the serial lock until blocking work really stops on cancel."""
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(future)
            break
        except asyncio.CancelledError:
            if future.cancelled():
                raise
            cancelled = True
        except Exception:
            if cancelled:
                raise asyncio.CancelledError
            raise
    if cancelled:
        raise asyncio.CancelledError
    return result


@dataclass
class _Entry:
    device: Any
    last_used: float
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    serial: str = ""
    generation: int = 0
    keep_warm: bool = False
    keep_warm_since: float = 0.0


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
        self._heartbeat_cursor = 0
        self._direct_http_healthy_at: dict[str, float] = {}
        self._reset_cooldown_until: dict[str, float] = {}
        self._stats: dict[str, int] = {
            "connects": 0,
            "reconnects": 0,
            "evictions": 0,
            "alive_probes": 0,
            "alive_timeouts": 0,
            "alive_failures": 0,
            "heartbeat_ticks": 0,
            "heartbeat_probes": 0,
            "heartbeat_budget_skips": 0,
            "heartbeat_recent_skips": 0,
            "heartbeat_locked_skips": 0,
            "heartbeat_evictions": 0,
            "heartbeat_reconnects": 0,
            "direct_http_health_marks": 0,
            "reset_uiautomator_success": 0,
            "reset_uiautomator_failures": 0,
            "reset_uiautomator_skips": 0,
            "reset_uiautomator_http_healthy_skips": 0,
            "reset_uiautomator_cooldown_skips": 0,
            "reconnect_fallbacks": 0,
            "keep_warm_expired": 0,
            "keep_warm_lru_evictions": 0,
            "warm_reuses": 0,
            "prepare_recent_skips": 0,
        }
        self._prepare_samples_ms: deque[int] = deque(maxlen=512)
        self._lock_wait_samples_ms: deque[int] = deque(maxlen=512)
        self._exec_samples_ms: deque[int] = deque(maxlen=512)
        self._alive_probe_samples_ms: deque[int] = deque(maxlen=512)
        self._heartbeat_tick_samples_ms: deque[int] = deque(maxlen=256)

    def _bump(self, key: str, amount: int = 1) -> None:
        self._stats[key] = self._stats.get(key, 0) + amount

    @staticmethod
    def _p95(samples: deque[int]) -> int:
        if not samples:
            return 0
        values = sorted(samples)
        index = min(len(values) - 1, int(len(values) * 0.95))
        return values[index]

    def stats_snapshot(self, *, reset: bool = False) -> dict[str, int]:
        """Return pool churn/timing metrics for runtime stats."""
        keep_warm_count = sum(1 for entry in self._sessions.values() if entry.keep_warm)
        stats = dict(self._stats)
        stats.update(
            {
                "sessions": len(self._sessions),
                "keep_warm": keep_warm_count,
                "heartbeat_probe_budget": HEARTBEAT_MAX_PROBES_PER_TICK,
                "keep_warm_max_sessions": KEEP_WARM_MAX_SESSIONS,
                "direct_http_healthy_serials": sum(
                    1 for seen_at in self._direct_http_healthy_at.values()
                    if self._direct_http_health_recent(seen_at)
                ),
                "reset_cooldown_serials": sum(
                    1 for until in self._reset_cooldown_until.values()
                    if until > time.monotonic()
                ),
                "prepare_p95_ms": self._p95(self._prepare_samples_ms),
                "lock_wait_p95_ms": self._p95(self._lock_wait_samples_ms),
                "exec_p95_ms": self._p95(self._exec_samples_ms),
                "alive_probe_p95_ms": self._p95(self._alive_probe_samples_ms),
                "heartbeat_tick_p95_ms": self._p95(self._heartbeat_tick_samples_ms),
                "heartbeat_coverage_percent": int(
                    min(100, HEARTBEAT_MAX_PROBES_PER_TICK * 100 / max(1, len(self._sessions)))
                ),
            }
        )
        if reset:
            for key in list(self._stats):
                self._stats[key] = 0
            self._prepare_samples_ms.clear()
            self._lock_wait_samples_ms.clear()
            self._exec_samples_ms.clear()
            self._alive_probe_samples_ms.clear()
            self._heartbeat_tick_samples_ms.clear()
        return stats

    def mark_direct_http_healthy(self, serial: str) -> None:
        """Record that ATX direct HTTP just worked for a serial.

        If this is fresh, a stale uiautomator2 Python session should not trigger
        a device-side reset storm. A plain reconnect is enough to refresh the
        local session object.
        """
        self._direct_http_healthy_at[serial] = time.monotonic()
        self._bump("direct_http_health_marks")

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
        if enabled and not entry.keep_warm:
            entry.keep_warm_since = time.monotonic()
            self._bump("warm_reuses")
        if not enabled:
            entry.keep_warm_since = 0.0
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
                    if not entry.keep_warm:
                        entry.keep_warm_since = time.monotonic()
                        self._bump("warm_reuses")
                    entry.keep_warm = True
                recently_used = (
                    time.monotonic() - entry.last_used < PREPARE_SKIP_ALIVE_SECONDS
                )
                if recently_used:
                    self._bump("prepare_recent_skips")
                elif not await self._is_alive(entry):
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
                future = self._loop.run_in_executor(ex, fn, entry.device)
                return await _await_executor_completion(future)
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
        self._prepare_samples_ms.append(int(prepare_ms))
        lock_wait_started = time.perf_counter()
        async with entry.lock:
            lock_wait_ms = (time.perf_counter() - lock_wait_started) * 1000.0
            self._lock_wait_samples_ms.append(int(lock_wait_ms))
            entry.last_used = time.monotonic()
            exec_started = time.perf_counter()
            try:
                future = self._loop.run_in_executor(ex, fn, entry.device)
                return await _await_executor_completion(future)
            finally:
                exec_ms = (time.perf_counter() - exec_started) * 1000.0
                self._exec_samples_ms.append(int(exec_ms))
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
            self._direct_http_healthy_at.pop(serial, None)
            self._reset_cooldown_until.pop(serial, None)
        if entry:
            self._bump("evictions")
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

    def _connect_target(self, serial: str):
        """What to hand `u2.connect` for `serial`.

        An adbutils device pinned to the ADB server that owns this phone when
        routing knows it — otherwise the bare serial, and u2 resolves it itself
        through the `adbutils.adb` singleton, which is bound to one ADB server
        for the whole process and so is wrong for every phone not on it.

        Runs in the connect executor, never on the event loop: resolving a route
        can spawn `adb devices` and wait on admission.
        """
        host = serial.rsplit(":", 1)[0] if ":" in serial else serial
        from relay.adb import adb_device_for_u2

        try:
            device = adb_device_for_u2(serial)
        except Exception as exc:
            # Routing is an optimisation here; never let it block a connect.
            logger.warning(
                "u2-pool: adb route lookup failed serial=%s err=%s — using u2 default",
                serial, exc,
            )
            return host
        return device if device is not None else host

    def _direct_http_health_recent(self, seen_at: float) -> bool:
        return (
            DIRECT_HTTP_HEALTH_TTL_SECONDS > 0
            and time.monotonic() - seen_at <= DIRECT_HTTP_HEALTH_TTL_SECONDS
        )

    def _should_attempt_reset(self, serial: str) -> bool:
        seen_at = self._direct_http_healthy_at.get(serial)
        if seen_at is not None and self._direct_http_health_recent(seen_at):
            self._bump("reset_uiautomator_skips")
            self._bump("reset_uiautomator_http_healthy_skips")
            return False
        until = self._reset_cooldown_until.get(serial, 0.0)
        if until > time.monotonic():
            self._bump("reset_uiautomator_skips")
            self._bump("reset_uiautomator_cooldown_skips")
            return False
        if RESET_UIAUTOMATOR_COOLDOWN_SECONDS > 0:
            self._reset_cooldown_until[serial] = (
                time.monotonic() + RESET_UIAUTOMATOR_COOLDOWN_SECONDS
            )
        return True

    async def _connect(self, serial: str, *, keep_warm: bool = False) -> _Entry:
        fn = self._get_connect_fn()
        try:
            # _connect_target resolves the ADB route, which can spawn an `adb
            # devices` and wait on admission. Both belong in the executor — on
            # the loop thread they stall every other device in the process — and
            # inside wait_for, so a wedged ADB server cannot outlive the budget.
            dev = await asyncio.wait_for(
                self._loop.run_in_executor(
                    self._resolve_executor(),
                    lambda: fn(self._connect_target(serial)),
                ),
                timeout=CONNECT_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            # wait_for raises a bare TimeoutError. Callers up the stack report
            # str(exc), so an unlabelled one reaches the operator as an empty
            # error. Keep the type and add the operation context.
            raise TimeoutError(
                f"u2 connect timed out after {CONNECT_TIMEOUT_SECONDS}s serial={serial}"
            ) from exc
        entry = _Entry(
            device=dev,
            last_used=time.monotonic(),
            serial=serial,
            generation=self._next_generation(),
            keep_warm=keep_warm,
            keep_warm_since=time.monotonic() if keep_warm else 0.0,
        )
        async with self._global_lock:
            if serial not in self._sessions:
                self._sessions[serial] = entry
            else:
                self._close_blocking(entry)
                entry = self._sessions[serial]
                if keep_warm:
                    if not entry.keep_warm:
                        entry.keep_warm_since = time.monotonic()
                        self._bump("warm_reuses")
                    entry.keep_warm = True
        self._bump("connects")
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
        if callable(reset_fn) and self._should_attempt_reset(entry.serial):
            try:
                await asyncio.wait_for(
                    self._loop.run_in_executor(ex, reset_fn),
                    timeout=CONNECT_TIMEOUT_SECONDS * 2,
                )
                if await self._is_alive(entry):
                    entry.generation = self._next_generation()
                    self._bump("reset_uiautomator_success")
                    logger.info("u2-pool: reset_uiautomator succeeded serial=%s", entry.serial)
                    return
            except Exception as exc:
                self._bump("reset_uiautomator_failures")
                logger.warning(
                    "u2-pool: reset_uiautomator failed serial=%s err=%s — falling back to reconnect",
                    entry.serial, exc,
                )

        self._bump("reconnect_fallbacks")
        self._close_blocking(entry)
        fn = self._get_connect_fn()
        serial = entry.serial
        try:
            # Route resolution stays in the executor — see _connect.
            entry.device = await asyncio.wait_for(
                self._loop.run_in_executor(
                    ex, lambda: fn(self._connect_target(serial))
                ),
                timeout=CONNECT_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                f"u2 reconnect timed out after {CONNECT_TIMEOUT_SECONDS}s serial={entry.serial}"
            ) from exc
        entry.generation = self._next_generation()
        self._bump("reconnects")
        logger.info("u2-pool: reconnected serial=%s", entry.serial)

    async def _is_alive(self, entry: _Entry) -> bool:
        """
        Probe the session with a hard timeout. A crashed u2d (atx-agent) makes
        `.alive` block until TCP keepalive trips (minutes); wrapping in
        wait_for keeps us from hanging the caller.
        """
        started = time.perf_counter()
        try:
            self._bump("alive_probes")
            alive = bool(
                await asyncio.wait_for(
                    self._loop.run_in_executor(
                        self._resolve_executor(), lambda: entry.device.alive
                    ),
                    timeout=ALIVE_TIMEOUT_SECONDS,
                )
            )
            self._alive_probe_samples_ms.append(
                int((time.perf_counter() - started) * 1000.0)
            )
            return alive
        except asyncio.TimeoutError:
            self._alive_probe_samples_ms.append(
                int((time.perf_counter() - started) * 1000.0)
            )
            self._bump("alive_timeouts")
            logger.debug(
                "u2-pool: .alive probe timed out after %.1fs serial=%s — treating as dead",
                ALIVE_TIMEOUT_SECONDS, entry.serial,
            )
            return False
        except Exception as exc:
            self._alive_probe_samples_ms.append(
                int((time.perf_counter() - started) * 1000.0)
            )
            self._bump("alive_failures")
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
                stale: list[tuple[str, str]] = []
                async with self._global_lock:
                    for s, e in self._sessions.items():
                        if e.keep_warm:
                            warm_anchor = max(e.keep_warm_since, e.last_used)
                            if (
                                KEEP_WARM_TTL_SECONDS > 0
                                and warm_anchor > 0
                                and now - warm_anchor > KEEP_WARM_TTL_SECONDS
                            ):
                                stale.append((s, "keep_warm_expired"))
                            continue
                        if now - e.last_used > SESSION_TTL_SECONDS:
                            stale.append((s, "session_ttl"))

                    if KEEP_WARM_MAX_SESSIONS > 0:
                        stale_serials = {serial for serial, _ in stale}
                        warm_entries = [
                            (s, e)
                            for s, e in self._sessions.items()
                            if e.keep_warm and s not in stale_serials
                        ]
                        overflow = len(warm_entries) - KEEP_WARM_MAX_SESSIONS
                        if overflow > 0:
                            warm_entries.sort(key=lambda item: item[1].last_used)
                            for s, _ in warm_entries[:overflow]:
                                stale.append((s, "keep_warm_lru"))

                for s, reason in stale:
                    if reason == "keep_warm_expired":
                        self._bump("keep_warm_expired")
                    elif reason == "keep_warm_lru":
                        self._bump("keep_warm_lru_evictions")
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
                tick_started = time.perf_counter()
                async with self._global_lock:
                    entries = list(self._sessions.items())
                total_entries = len(entries)
                if total_entries:
                    start = self._heartbeat_cursor % total_entries
                    ordered = entries[start:] + entries[:start]
                    budget = HEARTBEAT_MAX_PROBES_PER_TICK
                    if budget > 0 and total_entries > budget:
                        self._heartbeat_cursor = (start + budget) % total_entries
                        self._bump("heartbeat_budget_skips", total_entries - budget)
                        ordered = ordered[:budget]
                    else:
                        self._heartbeat_cursor = 0
                else:
                    ordered = []
                self._bump("heartbeat_ticks")
                for serial, entry in ordered:
                    probed_generation = entry.generation
                    # Skip sessions currently in use — the in-line probe at
                    # get_session() will catch dead ones.
                    if entry.lock.locked():
                        self._bump("heartbeat_locked_skips")
                        continue
                    if time.monotonic() - entry.last_used < HEARTBEAT_SKIP_RECENT_SECONDS:
                        self._bump("heartbeat_recent_skips")
                        continue
                    self._bump("heartbeat_probes")
                    if not await self._is_alive(entry):
                        recently_used = (
                            time.monotonic() - entry.last_used
                            < HEARTBEAT_GRACE_AFTER_USE_SECONDS
                        )
                        if recently_used and HEARTBEAT_RECONNECT_RECENT:
                            try:
                                await self._reconnect(entry)
                                self._bump("heartbeat_reconnects")
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
                                self._bump("evictions")
                                self._bump("heartbeat_evictions")
                                self._close_blocking(entry)
                                logger.info(
                                    "u2-pool: heartbeat evicted dead session serial=%s", serial,
                                )
                self._heartbeat_tick_samples_ms.append(
                    int((time.perf_counter() - tick_started) * 1000.0)
                )
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning("u2-pool: heartbeat error %s", exc)
