"""
relay/session_manager.py — ScrcpySessionManager

Manages all active ScrcpyRelaySession instances with:
  - Max concurrent session limit (prevents OOM / adb daemon overload)
  - TTL-based idle cleanup (stop sessions with no frames for SESSION_TTL seconds)
  - Zombie detection (relay thread died without stop() being called)
  - Background asyncio cleanup task (no busy-loop polling)
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, Dict, Optional

from relay.scrcpy_relay import ScrcpyRelaySession

logger = logging.getLogger("relay.session_mgr")

SESSION_TTL     = 60    # seconds — kill sessions that went stale (no frames) for 1 minute.
                        # Frame-timeout in scrcpy_relay._connect_and_stream (5s) normally
                        # catches stalls first; this sweep is the safety net.
ZOMBIE_TIMEOUT  = 10    # seconds — relay thread must be alive within this after start
MAX_SESSIONS    = 48    # max concurrent scrcpy sessions per relay agent
CLEANUP_INTERVAL = 15   # seconds between cleanup sweeps (halved from 30 to match lower TTL)


class ScrcpySessionManager:
    """
    Registry + lifecycle manager for ScrcpyRelaySession objects.

    Usage (inside RelayAgent):
        mgr = ScrcpySessionManager()
        await mgr.start()           # starts background cleanup task
        await mgr.start_session(serial, ...)
        mgr.send_control(serial, data)
        await mgr.stop_session(serial)
        await mgr.stop()            # shuts down all sessions
    """

    def __init__(
        self,
        on_session_stopped: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self._sessions:  Dict[str, ScrcpyRelaySession] = {}
        self._started_at: Dict[str, float] = {}  # serial → time.monotonic() at start
        self._cleanup_task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._on_session_stopped = on_session_stopped
        self._starting_serials: set[str] = set()
        self._fatal_during_start: Dict[str, str] = {}

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background cleanup task. Call once at agent startup."""
        self._loop = asyncio.get_running_loop()
        self._cleanup_task = asyncio.create_task(
            self._cleanup_loop(), name="scrcpy-session-cleanup"
        )

    async def stop(self) -> None:
        """Stop all sessions and cancel background task."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        await self.stop_all_sessions()

    async def stop_all_sessions(self) -> None:
        """Stop all active sessions (e.g. on gRPC stream disconnect)."""
        serials = list(self._sessions)
        if serials:
            logger.info("stopping all %d sessions on stream disconnect", len(serials))
        for serial in serials:
            await self.stop_session(serial, reason="manual_stop")

    async def stop_all_for_serial(self, serial: str, reason: str = "device_offline") -> None:
        """
        Stop every session for one serial. Idempotent.

        Used by the device-offline cascade in RelayAgent._on_device_event: when a
        device disappears, we must tear down scrcpy cleanly or the relay thread
        will keep reconnecting for minutes until the retry budget exhausts.
        """
        if serial in self._sessions:
            await self.stop_session(serial, reason=reason)
        # Drop any pending fatal-during-start marker — device is gone.
        self._fatal_during_start.pop(serial, None)

    # ── Session API ───────────────────────────────────────────────────────────

    async def start_session(
        self,
        serial: str,
        max_fps: int,
        max_width: int,
        enable_control: bool,
        port: int,
        send_queue: asyncio.Queue,
        loop: asyncio.AbstractEventLoop,
        bitrate: int = 2_000_000,
        low_latency: bool = False,
    ) -> None:
        """Create and start a session. Stops any existing session for same serial."""
        await self.stop_session(serial)

        if len(self._sessions) >= MAX_SESSIONS:
            logger.warning(
                "max sessions (%d) reached — rejecting scrcpy for %s",
                MAX_SESSIONS, serial,
            )
            return

        session = ScrcpyRelaySession(
            serial=serial,
            max_fps=max_fps,
            max_width=max_width,
            enable_control=enable_control,
            port=port,
            send_queue=send_queue,
            loop=loop,
            bitrate=bitrate,
            low_latency=low_latency,
            on_fatal=self._on_session_fatal,
        )

        try:
            self._starting_serials.add(serial)
            # start() is blocking (JAR push ~1-2s) — run in executor
            await asyncio.get_running_loop().run_in_executor(None, session.start)
            self._sessions[serial] = session
            self._started_at[serial] = time.monotonic()
            logger.info("session started: %s (total=%d)", serial, len(self._sessions))
            self._starting_serials.discard(serial)
            fatal_reason = self._fatal_during_start.pop(serial, "")
            if fatal_reason:
                await self.stop_session(serial, reason=fatal_reason)
        except Exception as exc:
            logger.error("session start failed for %s: %s", serial, exc)
            self._emit_stopped(serial, "startup_failure")
            self._fatal_during_start.pop(serial, None)
        finally:
            self._starting_serials.discard(serial)

    async def stop_session(self, serial: str, reason: str = "manual_stop") -> None:
        """Stop and remove session for serial."""
        session = self._sessions.pop(serial, None)
        self._started_at.pop(serial, None)
        if session:
            await asyncio.get_running_loop().run_in_executor(None, session.stop)
            logger.info(
                "session stopped: %s (reason=%s, remaining=%d)",
                serial,
                reason,
                len(self._sessions),
            )
            self._emit_stopped(serial, reason)

    def send_control(self, serial: str, data: bytes) -> None:
        """Thread-safe — delegates to session.send_control()."""
        session = self._sessions.get(serial)
        if session:
            session.send_control(data)

    def get(self, serial: str) -> Optional[ScrcpyRelaySession]:
        return self._sessions.get(serial)

    @property
    def active_serials(self) -> list[str]:
        return list(self._sessions.keys())

    @property
    def count(self) -> int:
        return len(self._sessions)

    # ── Background cleanup ────────────────────────────────────────────────────

    async def _cleanup_loop(self) -> None:
        """Periodic sweep — kills idle sessions and zombie threads."""
        while True:
            try:
                await asyncio.sleep(CLEANUP_INTERVAL)
                await self._sweep()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("cleanup sweep error: %s", exc)

    async def _sweep(self) -> None:
        now = time.monotonic()
        to_stop: list[tuple[str, str]] = []

        for serial, session in list(self._sessions.items()):
            # Zombie: thread started but died without stop()
            started = self._started_at.get(serial, now)
            grace_elapsed = now - started
            if grace_elapsed > ZOMBIE_TIMEOUT and not session.is_alive():
                to_stop.append((serial, "zombie thread"))
                continue

            # TTL: no frames received for SESSION_TTL seconds
            last = session.last_frame_time
            if last > 0 and (now - last) > SESSION_TTL:
                to_stop.append((serial, f"idle {now - last:.0f}s > TTL {SESSION_TTL}s"))

        for serial, reason in to_stop:
            logger.info("cleanup stopping session %s: %s", serial, reason)
            reason_tag = "zombie_thread" if reason == "zombie thread" else "cleanup_idle"
            await self.stop_session(serial, reason=reason_tag)

    def _on_session_fatal(self, serial: str, reason: str) -> None:
        """
        Called from ScrcpyRelaySession relay thread when unrecoverable runtime
        error happens. Schedule async stop on event loop thread-safely.
        """
        if self._loop is None:
            return
        def _schedule_stop_or_emit() -> None:
            if serial in self._starting_serials:
                self._fatal_during_start[serial] = reason
                return
            if serial in self._sessions:
                asyncio.create_task(self.stop_session(serial, reason=reason))
                return
            # Fatal can happen during bootstrap before we register session in map.
            self._emit_stopped(serial, reason)

        self._loop.call_soon_threadsafe(_schedule_stop_or_emit)

    def _emit_stopped(self, serial: str, reason: str) -> None:
        cb = self._on_session_stopped
        if cb:
            try:
                cb(serial, reason)
            except Exception as exc:
                logger.debug("on_session_stopped callback error: %s", exc)
