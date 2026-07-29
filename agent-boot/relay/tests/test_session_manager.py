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

    def start(self) -> None:
        return None

    def stop(self) -> None:
        self._alive = False

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
