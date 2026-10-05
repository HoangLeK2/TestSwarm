"""Phased startup/shutdown contract.

Problem
-------
Long-lived subsystems (Redis, gRPC relay, scheduler engine, heartbeat,
event cleanup, Temporal worker threads, relay subprocess, ngrok) were each
wired by hand into `lifespan()` and `main.py`. Teardown order drifted,
background tasks used fire-and-forget `create_task`, and subprocesses had
no signal hookup — so shutdown was noisy and could leak.

Contract
--------
Everything with a lifetime longer than one request registers with
`LifecycleManager`. Registration chooses a phase so startup and shutdown
respect dependency order (LIFO on shutdown):

    INFRA       — redis, db connections
    TRANSPORT   — grpc, relay ws, mdns
    CONTROL     — dispatcher, watchdog, scheduler engine
    BACKGROUND  — heartbeat, event cleanup, temporal worker threads
    EGRESS      — ngrok tunnels, external publishers

Each phase shuts down fully before the previous one begins. Background
tasks are cancelled and awaited with a timeout; subprocesses receive
SIGTERM → grace → SIGKILL.
"""
from __future__ import annotations

import asyncio
import logging
import signal
import threading
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Awaitable, Callable, List, Optional

log = logging.getLogger(__name__)


class LifecyclePhase(IntEnum):
    INFRA = 0
    TRANSPORT = 1
    CONTROL = 2
    BACKGROUND = 3
    EGRESS = 4


@dataclass
class _Entry:
    phase: LifecyclePhase
    name: str
    close: Callable[[], Awaitable[None]]


class LifecycleManager:
    """Single registry for all long-lived runtime components.

    Use `register_task` for asyncio coroutines, `register_subprocess` for
    `subprocess.Popen` handles, and `register_resource` for anything with
    an async close method (redis, grpc, scheduler engines).
    """

    def __init__(self) -> None:
        self._entries: List[_Entry] = []
        self._tasks: List[asyncio.Task] = []
        self._lock = threading.Lock()
        self._shutdown_started = False

    # ── Registration ─────────────────────────────────────────────────────
    def register_task(
        self,
        phase: LifecyclePhase,
        name: str,
        coro_factory: Callable[[], Awaitable[None]],
    ) -> asyncio.Task:
        task = asyncio.create_task(coro_factory(), name=name)
        self._tasks.append(task)

        async def _close() -> None:
            if task.done():
                return
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            except Exception as exc:
                log.warning("lifecycle: task %s exited with error: %s", name, exc)

        self._add(phase, name, _close)
        return task

    def register_subprocess(
        self,
        phase: LifecyclePhase,
        name: str,
        proc,
        term_grace_seconds: float = 5.0,
    ) -> None:
        async def _close() -> None:
            try:
                if proc.poll() is not None:
                    return
                log.info("lifecycle: subprocess %s (pid=%s) SIGTERM", name, proc.pid)
                try:
                    proc.terminate()
                except Exception:
                    pass
                try:
                    await asyncio.get_running_loop().run_in_executor(
                        None, lambda: proc.wait(timeout=term_grace_seconds)
                    )
                except Exception:
                    log.warning(
                        "lifecycle: subprocess %s did not exit within %ss, SIGKILL",
                        name, term_grace_seconds,
                    )
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    try:
                        await asyncio.get_running_loop().run_in_executor(
                            None, lambda: proc.wait(timeout=2.0)
                        )
                    except Exception:
                        pass
            except Exception as exc:
                log.warning("lifecycle: subprocess %s cleanup error: %s", name, exc)

        self._add(phase, name, _close)

    def register_resource(
        self,
        phase: LifecyclePhase,
        name: str,
        close: Callable[[], Awaitable[None]],
    ) -> None:
        self._add(phase, name, close)

    def register_sync_resource(
        self,
        phase: LifecyclePhase,
        name: str,
        close: Callable[[], None],
    ) -> None:
        async def _close() -> None:
            try:
                close()
            except Exception as exc:
                log.warning("lifecycle: resource %s close error: %s", name, exc)

        self._add(phase, name, _close)

    # ── Shutdown ─────────────────────────────────────────────────────────
    async def shutdown(self) -> None:
        """Shut everything down in reverse phase order."""
        with self._lock:
            if self._shutdown_started:
                return
            self._shutdown_started = True
            snapshot = list(self._entries)
            self._entries.clear()

        # Group by phase so every entry in one phase finishes before we
        # touch the next phase's dependencies.
        by_phase: dict[LifecyclePhase, list[_Entry]] = {}
        for entry in snapshot:
            by_phase.setdefault(entry.phase, []).append(entry)
        for phase in sorted(by_phase.keys(), reverse=True):
            log.info("lifecycle: shutting down phase %s", phase.name)
            await asyncio.gather(
                *(self._close_one(entry) for entry in by_phase[phase]),
                return_exceptions=True,
            )

    async def _close_one(self, entry: _Entry) -> None:
        try:
            await entry.close()
        except Exception as exc:
            log.warning("lifecycle: %s/%s close error: %s", entry.phase.name, entry.name, exc)

    # ── Internal ─────────────────────────────────────────────────────────
    def _add(
        self,
        phase: LifecyclePhase,
        name: str,
        close: Callable[[], Awaitable[None]],
    ) -> None:
        with self._lock:
            if self._shutdown_started:
                # If we already started shutting down, fire-and-forget close
                # rather than keeping the ref (caller is racing shutdown).
                try:
                    asyncio.get_event_loop().create_task(close())
                except Exception:
                    pass
                return
            self._entries.append(_Entry(phase=phase, name=name, close=close))


# ── Process-wide signal handler for subprocesses ──────────────────────────
#
# Called by `main.py` before uvicorn runs. Forwards SIGTERM/SIGINT into a
# best-effort shutdown of registered subprocesses — the async lifecycle is
# already cancelled by uvicorn on SIGINT, but Popen children need their own
# wiring because the Python handler the harness had before did not exist.
_HANDLER_INSTALLED = False


def install_signal_handlers(teardown: Callable[[], None]) -> None:
    global _HANDLER_INSTALLED
    if _HANDLER_INSTALLED:
        return
    _HANDLER_INSTALLED = True

    def _handler(signum, _frame):
        log.info("lifecycle: signal %s received", signum)
        try:
            teardown()
        except Exception:
            pass
        signal.signal(signum, signal.SIG_DFL)
        try:
            import os
            os.kill(os.getpid(), signum)
        except Exception:
            pass

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _handler)
        except (ValueError, OSError):
            pass
