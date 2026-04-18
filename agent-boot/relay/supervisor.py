"""
relay/supervisor.py — RelaySupervisor

Top-down reconciler for the RelayAgent. Runs every TICK_SECONDS and asks: for
every device we *want* streaming, is a scrcpy session actually running? If not,
and no restart is in flight, schedule one. Wraps the restart call with a
per-serial circuit breaker so a permanently-flaky device cannot wedge the loop.

Design notes:
  - We do NOT own restart logic. We call the agent's existing
    `_resume_desired_scrcpy_sessions` helper — single source of truth.
  - `_restart_pending: set[str]` guarded by `asyncio.Lock` prevents
    double-scheduling if the supervisor and an event-driven path race.
  - Circuit breaker (aiobreaker): one per serial, opens after
    BREAKER_FAIL_MAX consecutive restart failures in BREAKER_WINDOW; stays
    open BREAKER_RESET_SECONDS before allowing a probe attempt.
  - Emits one structured tick log with per-state counts — lets operators see
    fleet health without trawling per-device lines.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any, Dict, Optional, Set

try:
    from aiobreaker import CircuitBreaker, CircuitBreakerError
except ImportError:  # aiobreaker optional at import time; agent disables supervisor
    CircuitBreaker = None  # type: ignore[assignment]
    CircuitBreakerError = Exception  # type: ignore[assignment,misc]

logger = logging.getLogger("relay.supervisor")

TICK_SECONDS            = 15.0
BREAKER_FAIL_MAX        = 5
BREAKER_RESET_SECONDS   = 60.0


class RelaySupervisor:
    """
    Periodic reconciler. Activated with `await sup.start()`, stopped with
    `await sup.stop()`. Safe to start/stop multiple times.
    """

    def __init__(self, agent: Any) -> None:
        self._agent = agent
        self._task: Optional[asyncio.Task] = None
        self._restart_pending: Set[str] = set()
        self._pending_lock = asyncio.Lock()
        self._breakers: Dict[str, Any] = {}

    # ── lifecycle ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name="relay-supervisor")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    # ── internals ────────────────────────────────────────────────────────────

    def _breaker_for(self, serial: str) -> Optional[Any]:
        if CircuitBreaker is None:
            return None
        br = self._breakers.get(serial)
        if br is None:
            br = CircuitBreaker(
                fail_max=BREAKER_FAIL_MAX,
                timeout_duration=timedelta(seconds=BREAKER_RESET_SECONDS),
                name=f"scrcpy-restart-{serial}",
            )
            self._breakers[serial] = br
        return br

    async def _run(self) -> None:
        logger.info(
            "supervisor started tick=%.0fs breaker_max=%d breaker_reset=%.0fs",
            TICK_SECONDS, BREAKER_FAIL_MAX, BREAKER_RESET_SECONDS,
        )
        while True:
            try:
                await asyncio.sleep(TICK_SECONDS)
                await self._tick()
            except asyncio.CancelledError:
                logger.info("supervisor stopping")
                return
            except Exception as exc:
                logger.warning("supervisor tick error: %s", exc)

    async def _tick(self) -> None:
        agent = self._agent

        queue = getattr(agent, "_active_send_queue", None)
        loop  = getattr(agent, "_active_loop", None)
        if queue is None or loop is None:
            # Transport not connected — nothing to reconcile.
            return

        desired: Dict[str, dict] = dict(getattr(agent, "_scrcpy_desired", {}) or {})
        if not desired:
            return

        healthy = scrcpy_missing = restart_pending = breaker_open = not_online = 0
        to_schedule: list[str] = []

        scrcpy_mgr = agent._scrcpy_mgr
        registry   = agent._registry

        for logical, state in desired.items():
            if not state.get("desired", False) or state.get("manual_stop", False):
                continue

            adb_serial = agent._adb_serial_prefer_usb_over_tcp(logical)
            ctx = registry.get(adb_serial)
            if not ctx or not ctx.is_available:
                not_online += 1
                continue

            if scrcpy_mgr.get(adb_serial) is not None:
                healthy += 1
                continue

            scrcpy_missing += 1
            restart_task = state.get("restart_task")
            if restart_task and not restart_task.done():
                restart_pending += 1
                continue

            breaker = self._breaker_for(logical)
            if breaker is not None and breaker.current_state == "open":
                breaker_open += 1
                logger.info(
                    "supervisor skip %s: breaker=open (cooldown ~%.0fs)",
                    logical, BREAKER_RESET_SECONDS,
                )
                continue

            to_schedule.append(logical)

        logger.info(
            "supervisor tick desired=%d healthy=%d missing=%d pending=%d breaker_open=%d offline=%d",
            len(desired), healthy, scrcpy_missing, restart_pending, breaker_open, not_online,
        )

        for logical in to_schedule:
            await self._schedule_restart(logical, queue, loop)

    async def _schedule_restart(
        self,
        logical: str,
        queue: asyncio.Queue,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        async with self._pending_lock:
            if logical in self._restart_pending:
                return
            self._restart_pending.add(logical)

        try:
            breaker = self._breaker_for(logical)
            logger.info("supervisor restart %s (breaker=%s)",
                        logical, breaker.current_state if breaker else "disabled")

            # Wrap only the single-serial restart helper — NOT the fleet-wide
            # resume sweep. Wrapping the fleet call would cause one device's
            # failure to open the breaker for a different, healthy device.
            agent = self._agent

            async def _do_restart() -> None:
                await agent._restart_with_backoff(logical, queue, loop, source="supervisor")

            if breaker is not None:
                await breaker.call_async(_do_restart)
            else:
                await _do_restart()

            # Mirror _resume_desired_scrcpy_sessions bookkeeping so the agent's
            # own event-driven paths stay consistent (they key off restart_task).
            state = agent._scrcpy_desired.get(logical)
            if state is not None:
                state["restart_task"] = None
        except CircuitBreakerError:
            logger.warning("supervisor %s: breaker opened — backing off %.0fs",
                           logical, BREAKER_RESET_SECONDS)
        except Exception as exc:
            logger.warning("supervisor %s: restart failed: %s", logical, exc)
        finally:
            async with self._pending_lock:
                self._restart_pending.discard(logical)
