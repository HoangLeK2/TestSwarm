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
import os
import time
from typing import Callable, Dict, Optional

from relay.scrcpy_relay import ScrcpyRelaySession
from relay.runtime import scrcpy_executor

logger = logging.getLogger("relay.session_mgr")

SESSION_TTL     = 60    # seconds — kill sessions that went stale (no frames) for 1 minute.
                        # Frame-timeout in scrcpy_relay._connect_and_stream (5s) normally
                        # catches stalls first; this sweep is the safety net.
ZOMBIE_TIMEOUT  = 10    # seconds — relay thread must be alive within this after start
try:
    MAX_SESSIONS = max(0, int(os.getenv("SCRCPY_MAX_SESSIONS", "0")))
except (TypeError, ValueError):
    MAX_SESSIONS = 0
# 0 means unlimited. Operators may set a per-agent ceiling when measured CPU,
# bandwidth, or file-descriptor capacity requires one.
try:
    WARM_IDLE_TTL_S = max(0.0, float(os.getenv("SCRCPY_WARM_IDLE_TTL_S", "120")))
except (TypeError, ValueError):
    WARM_IDLE_TTL_S = 120.0
WARM_IDLE_ENABLED = os.getenv("SCRCPY_WARM_IDLE_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
WARM_STOP_REASONS = {
    "unsubscribe_frames:idle_no_viewers",
    "unsubscribe_frames:post_grace_idle",
}
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
        on_session_health: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self._sessions:  Dict[str, ScrcpyRelaySession] = {}
        self._started_at: Dict[str, float] = {}  # serial → time.monotonic() at start
        self._warm_since: Dict[str, float] = {}
        self._warm_until: Dict[str, float] = {}
        self._cleanup_task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._on_session_stopped = on_session_stopped
        self._on_session_health = on_session_health
        self._starting_serials: set[str] = set()
        self._fatal_during_start: Dict[str, str] = {}
        self._serial_locks: Dict[str, asyncio.Lock] = {}
        self._lifecycle_stats: Dict[str, int] = {
            "start_requests": 0,
            "cold_starts": 0,
            "same_config_reuses": 0,
            "warm_reuses": 0,
            "rejected_max_sessions": 0,
            "startup_failures": 0,
        }

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
    ) -> str:
        """Create and start a session. Stops any existing session for same serial."""
        self._bump_lifecycle_stat("start_requests")
        async with self._lock_for_serial(serial):
            existing = self._sessions.get(serial)
            if (
                existing is not None
                and existing.is_alive()
                and hasattr(existing, "matches_config")
                and existing.matches_config(max_fps, max_width, enable_control, port, bitrate, low_latency)
            ):
                resume = getattr(existing, "resume_forwarding", None)
                if callable(resume):
                    resume(send_queue=send_queue, loop=loop, reason="scrcpy_start")
                was_warm = serial in self._warm_until
                self._warm_since.pop(serial, None)
                self._warm_until.pop(serial, None)
                logger.info(
                    "session already running with same config: %s%s",
                    serial,
                    " (warm_reuse)" if was_warm else "",
                )
                if was_warm:
                    self._bump_lifecycle_stat("warm_reuses")
                    return "warm_reuse"
                self._bump_lifecycle_stat("same_config_reuses")
                return "same_config_reuse"

            await self._stop_session_unlocked(serial)

            if MAX_SESSIONS > 0 and len(self._sessions) >= MAX_SESSIONS:
                await self._evict_one_warm_session_unlocked()

            if MAX_SESSIONS > 0 and len(self._sessions) >= MAX_SESSIONS:
                logger.warning(
                    "max sessions (%d) reached — rejecting scrcpy for %s",
                    MAX_SESSIONS, serial,
                )
                self._bump_lifecycle_stat("rejected_max_sessions")
                return "rejected_max_sessions"

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
                on_health=self._on_session_health,
            )

            try:
                self._starting_serials.add(serial)
                # start() is blocking (JAR push ~1-2s) — run in scrcpy-specific
                # pool so a slow start cannot starve adb/u2 work.
                await asyncio.get_running_loop().run_in_executor(scrcpy_executor(), session.start)
                self._sessions[serial] = session
                self._started_at[serial] = time.monotonic()
                self._bump_lifecycle_stat("cold_starts")
                logger.info("session started: %s (total=%d)", serial, len(self._sessions))
                self._starting_serials.discard(serial)
                fatal_reason = self._fatal_during_start.pop(serial, "")
                if fatal_reason:
                    await self._stop_session_unlocked(serial, reason=fatal_reason)
                return "cold_start"
            except Exception as exc:
                logger.error("session start failed for %s: %s", serial, exc)
                self._emit_stopped(serial, "startup_failure")
                self._fatal_during_start.pop(serial, None)
                self._bump_lifecycle_stat("startup_failures")
                return "startup_failure"
            finally:
                self._starting_serials.discard(serial)

    async def stop_session(self, serial: str, reason: str = "manual_stop") -> None:
        """Stop and remove session for serial."""
        async with self._lock_for_serial(serial):
            await self._stop_session_unlocked(serial, reason=reason)
        self._discard_serial_lock_if_idle(serial)

    def _lock_for_serial(self, serial: str) -> asyncio.Lock:
        lock = self._serial_locks.get(serial)
        if lock is None:
            lock = asyncio.Lock()
            self._serial_locks[serial] = lock
        return lock

    def _discard_serial_lock_if_idle(self, serial: str) -> None:
        lock = self._serial_locks.get(serial)
        if (
            lock is not None
            and not lock.locked()
            and serial not in self._sessions
            and serial not in self._starting_serials
        ):
            self._serial_locks.pop(serial, None)

    def _bump_lifecycle_stat(self, key: str, amount: int = 1) -> None:
        self._lifecycle_stats[key] = self._lifecycle_stats.get(key, 0) + amount

    async def _stop_session_unlocked(self, serial: str, reason: str = "manual_stop") -> None:
        if self._should_warm_instead_of_stop(serial, reason):
            session = self._sessions.get(serial)
            if session is not None:
                pause = getattr(session, "pause_forwarding", None)
                if callable(pause):
                    pause(reason=reason)
                now = time.monotonic()
                self._warm_since[serial] = now
                self._warm_until[serial] = now + WARM_IDLE_TTL_S
                logger.info(
                    "session warmed: %s (reason=%s ttl=%.1fs)",
                    serial,
                    reason,
                    WARM_IDLE_TTL_S,
                )
                return

        session = self._sessions.pop(serial, None)
        self._started_at.pop(serial, None)
        self._warm_since.pop(serial, None)
        self._warm_until.pop(serial, None)
        if session:
            await asyncio.get_running_loop().run_in_executor(scrcpy_executor(), session.stop)
            logger.info(
                "session stopped: %s (reason=%s, remaining=%d)",
                serial,
                reason,
                len(self._sessions),
            )
            self._emit_stopped(serial, reason)

    def _should_warm_instead_of_stop(self, serial: str, reason: str) -> bool:
        if not WARM_IDLE_ENABLED or WARM_IDLE_TTL_S <= 0:
            return False
        if reason not in WARM_STOP_REASONS:
            return False
        session = self._sessions.get(serial)
        return bool(session is not None and session.is_alive())

    async def _evict_one_warm_session_unlocked(self) -> None:
        if not self._warm_until:
            return
        serial = min(
            self._warm_until,
            key=lambda item: (
                self._warm_until.get(item, 0.0),
                self._warm_since.get(item, 0.0),
            ),
        )
        logger.info("session warm eviction: %s", serial)
        await self._stop_session_unlocked(serial, reason="warm_lru_eviction")

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

    def stats_snapshot(self, *, reset: bool = False) -> dict[str, int]:
        """Aggregate stream health without emitting per-device labels."""
        totals = {
            "sessions": len(self._sessions),
            "frames": 0,
            "fps_x100": 0,
            "fps_min_x100": 0,
            "fps_max_x100": 0,
            "fps_active_sessions": 0,
            "fps_min_active_x100": 0,
            "idr_requests": 0,
            "idr_recoveries": 0,
            "worst_device_idr_recovery_p95_ms": 0,
            "idr_recovery_max_ms": 0,
            "idr_pending": 0,
            "producer_suppressed": 0,
            "connect_to_handshake_p95_ms": 0,
            "connect_to_handshake_max_ms": 0,
            "connect_to_first_frame_p95_ms": 0,
            "connect_to_first_frame_max_ms": 0,
            "start_to_handshake_p95_ms": 0,
            "start_to_handshake_max_ms": 0,
            "start_to_first_frame_p95_ms": 0,
            "start_to_first_frame_max_ms": 0,
            "gop_replay_packets": 0,
            "capture_resets": 0,
            "stream_errors": 0,
        }
        for key, value in self._lifecycle_stats.items():
            totals[key] = value
        if reset:
            for key in self._lifecycle_stats:
                self._lifecycle_stats[key] = 0
        observed_fps: list[int] = []
        active_fps: list[int] = []
        for session in list(self._sessions.values()):
            session_stats = getattr(session, "stats_snapshot", None)
            if not callable(session_stats):
                continue
            snapshot = session_stats(reset=reset)
            totals["frames"] += snapshot.get("frames", 0)
            fps_x100 = snapshot.get("fps_x100", 0)
            totals["fps_x100"] += fps_x100
            observed_fps.append(fps_x100)
            if snapshot.get("frames", 0) > 0:
                active_fps.append(fps_x100)
            totals["idr_requests"] += snapshot.get("idr_requests", 0)
            totals["idr_recoveries"] += snapshot.get("idr_recoveries", 0)
            totals["worst_device_idr_recovery_p95_ms"] = max(
                totals["worst_device_idr_recovery_p95_ms"],
                snapshot.get("idr_recovery_p95_ms", 0),
            )
            totals["idr_recovery_max_ms"] = max(
                totals["idr_recovery_max_ms"],
                snapshot.get("idr_recovery_max_ms", 0),
            )
            totals["idr_pending"] += snapshot.get("idr_pending", 0)
            totals["producer_suppressed"] += snapshot.get(
                "producer_suppressed",
                0,
            )
            totals["connect_to_handshake_p95_ms"] = max(
                totals["connect_to_handshake_p95_ms"],
                snapshot.get("connect_to_handshake_p95_ms", 0),
            )
            totals["connect_to_handshake_max_ms"] = max(
                totals["connect_to_handshake_max_ms"],
                snapshot.get("connect_to_handshake_max_ms", 0),
            )
            totals["connect_to_first_frame_p95_ms"] = max(
                totals["connect_to_first_frame_p95_ms"],
                snapshot.get("connect_to_first_frame_p95_ms", 0),
            )
            totals["connect_to_first_frame_max_ms"] = max(
                totals["connect_to_first_frame_max_ms"],
                snapshot.get("connect_to_first_frame_max_ms", 0),
            )
            totals["start_to_handshake_p95_ms"] = max(
                totals["start_to_handshake_p95_ms"],
                snapshot.get("start_to_handshake_p95_ms", 0),
            )
            totals["start_to_handshake_max_ms"] = max(
                totals["start_to_handshake_max_ms"],
                snapshot.get("start_to_handshake_max_ms", 0),
            )
            totals["start_to_first_frame_p95_ms"] = max(
                totals["start_to_first_frame_p95_ms"],
                snapshot.get("start_to_first_frame_p95_ms", 0),
            )
            totals["start_to_first_frame_max_ms"] = max(
                totals["start_to_first_frame_max_ms"],
                snapshot.get("start_to_first_frame_max_ms", 0),
            )
            totals["gop_replay_packets"] += snapshot.get("gop_replay_packets", 0)
            totals["capture_resets"] += snapshot.get("capture_resets", 0)
            totals["stream_errors"] += snapshot.get("stream_errors", 0)
        totals["fps_min_x100"] = min(observed_fps, default=0)
        totals["fps_max_x100"] = max(observed_fps, default=0)
        totals["fps_active_sessions"] = len(active_fps)
        totals["fps_min_active_x100"] = min(active_fps, default=0)
        return totals

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

            warm_until = self._warm_until.get(serial)
            if warm_until is not None:
                if now >= warm_until:
                    to_stop.append((serial, "warm TTL expired"))
                continue

            # TTL: no frames received for SESSION_TTL seconds
            last = session.last_frame_time
            if last > 0 and (now - last) > SESSION_TTL:
                to_stop.append((serial, f"idle {now - last:.0f}s > TTL {SESSION_TTL}s"))

        for serial, reason in to_stop:
            logger.info("cleanup stopping session %s: %s", serial, reason)
            if reason == "zombie thread":
                reason_tag = "zombie_thread"
            elif reason == "warm TTL expired":
                reason_tag = "warm_ttl_expired"
            else:
                reason_tag = "cleanup_idle"
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
