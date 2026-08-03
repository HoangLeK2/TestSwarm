from __future__ import annotations

import asyncio
import time

from relay import session_manager as sm


class _FakeSession:
    def __init__(self, serial: str, on_fatal=None, **kwargs):
        self.serial = serial
        self.on_fatal = on_fatal
        self.last_frame_time = 0.0
        self._alive = True
        self.paused = False
        self.pause_reasons: list[str] = []
        self.resume_reasons: list[str] = []

    def start(self) -> None:
        return None

    def stop(self) -> None:
        self._alive = False

    def pause_forwarding(self, *, reason: str = "warm_idle") -> None:
        self.paused = True
        self.pause_reasons.append(reason)

    def resume_forwarding(self, *, send_queue, loop, reason: str = "scrcpy_start") -> None:
        self.paused = False
        self.resume_reasons.append(reason)

    def is_alive(self) -> bool:
        return self._alive

    def matches_config(
        self,
        max_fps: int,
        max_width: int,
        enable_control: bool,
        port: int,
        bitrate: int,
        low_latency: bool,
    ) -> bool:
        return True


def test_stop_session_emits_manual_reason(monkeypatch):
    events: list[tuple[str, str]] = []
    monkeypatch.setattr(sm, "ScrcpyRelaySession", _FakeSession)
    async def _run() -> None:
        mgr = sm.ScrcpySessionManager(on_session_stopped=lambda s, r: events.append((s, r)))
        await mgr.start()
        try:
            await mgr.start_session("serial-1", 30, 720, True, 27183, asyncio.Queue(), asyncio.get_running_loop())
            await mgr.stop_session("serial-1", reason="manual_stop")
            assert ("serial-1", "manual_stop") in events
        finally:
            await mgr.stop()
    asyncio.run(_run())


def test_startup_failure_emits_reason(monkeypatch):
    class _StartupFailSession(_FakeSession):
        def start(self) -> None:
            raise RuntimeError("boom")

    events: list[tuple[str, str]] = []
    monkeypatch.setattr(sm, "ScrcpyRelaySession", _StartupFailSession)
    async def _run() -> None:
        mgr = sm.ScrcpySessionManager(on_session_stopped=lambda s, r: events.append((s, r)))
        await mgr.start()
        try:
            await mgr.start_session("serial-2", 30, 720, True, 27183, asyncio.Queue(), asyncio.get_running_loop())
            assert ("serial-2", "startup_failure") in events
        finally:
            await mgr.stop()
    asyncio.run(_run())


def test_fatal_runtime_error_triggers_stop(monkeypatch):
    class _FatalSession(_FakeSession):
        def start(self) -> None:
            if self.on_fatal:
                self.on_fatal(self.serial, "runtime_error")

    events: list[tuple[str, str]] = []
    monkeypatch.setattr(sm, "ScrcpyRelaySession", _FatalSession)
    async def _run() -> None:
        mgr = sm.ScrcpySessionManager(on_session_stopped=lambda s, r: events.append((s, r)))
        await mgr.start()
        try:
            await mgr.start_session("serial-3", 30, 720, True, 27183, asyncio.Queue(), asyncio.get_running_loop())
            await asyncio.sleep(0.05)
            assert ("serial-3", "runtime_error") in events
        finally:
            await mgr.stop()
    asyncio.run(_run())


def test_session_health_callback_passes_through(monkeypatch):
    class _HealthSession(_FakeSession):
        def __init__(self, serial: str, on_health=None, **kwargs):
            super().__init__(serial, **kwargs)
            self.on_health = on_health

        def start(self) -> None:
            if self.on_health:
                self.on_health(self.serial, "capture_reset_storm")

    events: list[tuple[str, str]] = []
    monkeypatch.setattr(sm, "ScrcpyRelaySession", _HealthSession)

    async def _run() -> None:
        mgr = sm.ScrcpySessionManager(
            on_session_health=lambda s, r: events.append((s, r))
        )
        await mgr.start()
        try:
            await mgr.start_session(
                "serial-health",
                30,
                720,
                True,
                27183,
                asyncio.Queue(),
                asyncio.get_running_loop(),
            )
            assert events == [("serial-health", "capture_reset_storm")]
        finally:
            await mgr.stop()

    asyncio.run(_run())


def test_cleanup_idle_emits_reason(monkeypatch):
    monkeypatch.setattr(sm, "ScrcpyRelaySession", _FakeSession)
    events: list[tuple[str, str]] = []
    async def _run() -> None:
        mgr = sm.ScrcpySessionManager(on_session_stopped=lambda s, r: events.append((s, r)))
        await mgr.start()
        try:
            await mgr.start_session("serial-4", 30, 720, True, 27183, asyncio.Queue(), asyncio.get_running_loop())
            sess = mgr.get("serial-4")
            assert sess is not None
            sess.last_frame_time = time.monotonic() - (sm.SESSION_TTL + 1)
            await mgr._sweep()
            assert ("serial-4", "cleanup_idle") in events
        finally:
            await mgr.stop()
    asyncio.run(_run())


def test_concurrent_start_session_same_serial_coalesces(monkeypatch):
    starts = 0

    class _SlowStartSession(_FakeSession):
        def start(self) -> None:
            nonlocal starts
            starts += 1
            time.sleep(0.05)

    monkeypatch.setattr(sm, "ScrcpyRelaySession", _SlowStartSession)

    async def _run() -> None:
        mgr = sm.ScrcpySessionManager()
        await mgr.start()
        try:
            queue = asyncio.Queue()
            loop = asyncio.get_running_loop()
            await asyncio.gather(
                *[
                    mgr.start_session("serial-5", 30, 720, True, 27183, queue, loop)
                    for _ in range(3)
                ]
            )
            assert starts == 1
            assert mgr.count == 1
            stats = mgr.stats_snapshot(reset=True)
            assert stats["start_requests"] == 3
            assert stats["cold_starts"] == 1
            assert stats["same_config_reuses"] == 2
        finally:
            await mgr.stop()

    asyncio.run(_run())


def test_zero_max_sessions_means_unlimited(monkeypatch):
    monkeypatch.setattr(sm, "ScrcpyRelaySession", _FakeSession)
    monkeypatch.setattr(sm, "MAX_SESSIONS", 0)

    async def _run() -> None:
        mgr = sm.ScrcpySessionManager()
        await mgr.start()
        try:
            queue = asyncio.Queue()
            loop = asyncio.get_running_loop()
            for index in range(60):
                await mgr.start_session(
                    f"serial-{index}",
                    12,
                    540,
                    True,
                    27183 + index,
                    queue,
                    loop,
                )
            assert mgr.count == 60
        finally:
            await mgr.stop()

    asyncio.run(_run())


def test_positive_max_sessions_keeps_operator_ceiling(monkeypatch):
    monkeypatch.setattr(sm, "ScrcpyRelaySession", _FakeSession)
    monkeypatch.setattr(sm, "MAX_SESSIONS", 2)

    async def _run() -> None:
        mgr = sm.ScrcpySessionManager()
        await mgr.start()
        try:
            queue = asyncio.Queue()
            loop = asyncio.get_running_loop()
            for index in range(3):
                await mgr.start_session(
                    f"serial-{index}",
                    12,
                    540,
                    True,
                    27183 + index,
                    queue,
                    loop,
                )
            assert mgr.count == 2
            assert mgr.get("serial-2") is None
        finally:
            await mgr.stop()

    asyncio.run(_run())


def test_stop_session_discards_idle_serial_lock(monkeypatch):
    monkeypatch.setattr(sm, "ScrcpyRelaySession", _FakeSession)

    async def _run() -> None:
        mgr = sm.ScrcpySessionManager()
        await mgr.start()
        try:
            await mgr.start_session(
                "serial-6",
                30,
                720,
                True,
                27183,
                asyncio.Queue(),
                asyncio.get_running_loop(),
            )
            assert "serial-6" in mgr._serial_locks
            await mgr.stop_session("serial-6", reason="manual_stop")
            assert "serial-6" not in mgr._serial_locks
        finally:
            await mgr.stop()

    asyncio.run(_run())


def test_idle_no_viewers_stop_warms_session_and_reuses_without_restart(monkeypatch):
    monkeypatch.setattr(sm, "ScrcpyRelaySession", _FakeSession)
    monkeypatch.setattr(sm, "WARM_IDLE_ENABLED", True)
    monkeypatch.setattr(sm, "WARM_IDLE_TTL_S", 120.0)

    async def _run() -> None:
        mgr = sm.ScrcpySessionManager()
        await mgr.start()
        try:
            queue = asyncio.Queue()
            loop = asyncio.get_running_loop()
            await mgr.start_session("serial-warm", 30, 720, True, 27183, queue, loop)
            sess = mgr.get("serial-warm")
            assert sess is not None

            await mgr.stop_session(
                "serial-warm",
                reason="unsubscribe_frames:idle_no_viewers",
            )

            assert mgr.get("serial-warm") is sess
            assert mgr.count == 1
            assert sess.paused is True
            assert sess.pause_reasons == ["unsubscribe_frames:idle_no_viewers"]

            await mgr.start_session("serial-warm", 30, 720, True, 27183, queue, loop)

            assert mgr.get("serial-warm") is sess
            assert sess.paused is False
            assert sess.resume_reasons == ["scrcpy_start"]
            stats = mgr.stats_snapshot(reset=True)
            assert stats["start_requests"] == 2
            assert stats["cold_starts"] == 1
            assert stats["warm_reuses"] == 1
        finally:
            await mgr.stop()

    asyncio.run(_run())


def test_warm_ttl_expiry_stops_session(monkeypatch):
    monkeypatch.setattr(sm, "ScrcpyRelaySession", _FakeSession)
    monkeypatch.setattr(sm, "WARM_IDLE_ENABLED", True)
    monkeypatch.setattr(sm, "WARM_IDLE_TTL_S", 120.0)
    events: list[tuple[str, str]] = []

    async def _run() -> None:
        mgr = sm.ScrcpySessionManager(
            on_session_stopped=lambda s, r: events.append((s, r))
        )
        await mgr.start()
        try:
            queue = asyncio.Queue()
            loop = asyncio.get_running_loop()
            await mgr.start_session("serial-warm-ttl", 30, 720, True, 27183, queue, loop)
            await mgr.stop_session(
                "serial-warm-ttl",
                reason="unsubscribe_frames:idle_no_viewers",
            )
            mgr._warm_until["serial-warm-ttl"] = time.monotonic() - 1

            await mgr._sweep()

            assert mgr.get("serial-warm-ttl") is None
            assert ("serial-warm-ttl", "warm_ttl_expired") in events
        finally:
            await mgr.stop()

    asyncio.run(_run())


def test_warm_session_uses_warm_ttl_instead_of_frame_idle_ttl(monkeypatch):
    monkeypatch.setattr(sm, "ScrcpyRelaySession", _FakeSession)
    monkeypatch.setattr(sm, "WARM_IDLE_ENABLED", True)
    monkeypatch.setattr(sm, "WARM_IDLE_TTL_S", 120.0)

    async def _run() -> None:
        mgr = sm.ScrcpySessionManager()
        await mgr.start()
        try:
            queue = asyncio.Queue()
            loop = asyncio.get_running_loop()
            await mgr.start_session("serial-static-warm", 30, 720, True, 27183, queue, loop)
            sess = mgr.get("serial-static-warm")
            assert sess is not None
            sess.last_frame_time = time.monotonic() - (sm.SESSION_TTL + 30)
            await mgr.stop_session(
                "serial-static-warm",
                reason="unsubscribe_frames:idle_no_viewers",
            )

            await mgr._sweep()

            assert mgr.get("serial-static-warm") is sess
            assert sess.paused is True
        finally:
            await mgr.stop()

    asyncio.run(_run())


def test_max_sessions_evicts_warm_session_before_rejecting_new_start(monkeypatch):
    monkeypatch.setattr(sm, "ScrcpyRelaySession", _FakeSession)
    monkeypatch.setattr(sm, "MAX_SESSIONS", 1)
    monkeypatch.setattr(sm, "WARM_IDLE_ENABLED", True)
    monkeypatch.setattr(sm, "WARM_IDLE_TTL_S", 120.0)

    async def _run() -> None:
        mgr = sm.ScrcpySessionManager()
        await mgr.start()
        try:
            queue = asyncio.Queue()
            loop = asyncio.get_running_loop()
            await mgr.start_session("serial-old", 30, 720, True, 27183, queue, loop)
            await mgr.stop_session(
                "serial-old",
                reason="unsubscribe_frames:idle_no_viewers",
            )

            await mgr.start_session("serial-new", 30, 720, True, 27184, queue, loop)

            assert mgr.get("serial-old") is None
            assert mgr.get("serial-new") is not None
            assert mgr.count == 1
        finally:
            await mgr.stop()

    asyncio.run(_run())


def test_stats_snapshot_aggregates_stream_health_without_serial_labels(
    monkeypatch,
):
    class _StatsSession(_FakeSession):
        def __init__(self, serial: str, **kwargs):
            super().__init__(serial, **kwargs)
            frames, fps_x100, recovery_ms = {
                "phone-A": (10, 800, 75),
                "phone-B": (12, 750, 120),
            }[serial]
            self.stats = {
                "frames": frames,
                "fps_x100": fps_x100,
                "idr_requests": 2,
                "idr_recoveries": 1,
                "idr_recovery_p95_ms": recovery_ms,
                "idr_recovery_max_ms": recovery_ms,
                "idr_pending": 0,
                "connect_to_handshake_p95_ms": recovery_ms + 1,
                "connect_to_handshake_max_ms": recovery_ms + 2,
                "connect_to_first_frame_p95_ms": recovery_ms + 3,
                "connect_to_first_frame_max_ms": recovery_ms + 4,
                "start_to_handshake_p95_ms": recovery_ms + 5,
                "start_to_handshake_max_ms": recovery_ms + 6,
                "start_to_first_frame_p95_ms": recovery_ms + 7,
                "start_to_first_frame_max_ms": recovery_ms + 8,
                "gop_replay_packets": 3,
            }

        def stats_snapshot(self, *, reset: bool = False) -> dict[str, int]:
            return dict(self.stats)

    monkeypatch.setattr(sm, "ScrcpyRelaySession", _StatsSession)

    async def _run() -> None:
        mgr = sm.ScrcpySessionManager()
        await mgr.start()
        try:
            queue = asyncio.Queue()
            loop = asyncio.get_running_loop()
            for index, serial in enumerate(("phone-A", "phone-B")):
                await mgr.start_session(
                    serial,
                    12,
                    540,
                    True,
                    27183 + index,
                    queue,
                    loop,
                )
            assert mgr.stats_snapshot(reset=True) == {
                "sessions": 2,
                "frames": 22,
                "fps_x100": 1550,
                "fps_min_x100": 750,
                "fps_max_x100": 800,
                "fps_active_sessions": 2,
                "fps_min_active_x100": 750,
                "idr_requests": 4,
                "idr_recoveries": 2,
                "worst_device_idr_recovery_p95_ms": 120,
                "idr_recovery_max_ms": 120,
                "idr_pending": 0,
                "producer_suppressed": 0,
                "connect_to_handshake_p95_ms": 121,
                "connect_to_handshake_max_ms": 122,
                "connect_to_first_frame_p95_ms": 123,
                "connect_to_first_frame_max_ms": 124,
                "start_to_handshake_p95_ms": 125,
                "start_to_handshake_max_ms": 126,
                "start_to_first_frame_p95_ms": 127,
                "start_to_first_frame_max_ms": 128,
                "gop_replay_packets": 6,
                "capture_resets": 0,
                "stream_errors": 0,
                "start_requests": 2,
                "cold_starts": 2,
                "same_config_reuses": 0,
                "warm_reuses": 0,
                "rejected_max_sessions": 0,
                "startup_failures": 0,
            }
        finally:
            await mgr.stop()

    asyncio.run(_run())
