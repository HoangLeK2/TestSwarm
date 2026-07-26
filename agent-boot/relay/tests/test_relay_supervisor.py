from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

from relay.supervisor import RelaySupervisor


class _Session:
    def __init__(self, *, streaming: bool, alive: bool = True) -> None:
        self._streaming = streaming
        self._alive = alive

    def is_streaming(self) -> bool:
        return self._streaming

    def is_alive(self) -> bool:
        return self._alive


class _SessionManager:
    def __init__(self, session: _Session | None) -> None:
        self._session = session

    def get(self, _serial: str) -> _Session | None:
        return self._session


class _Agent:
    def __init__(self, session: _Session | None) -> None:
        self._active_send_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._active_loop = asyncio.get_running_loop()
        self._scrcpy_desired = {
            "device-1": {
                "desired": True,
                "manual_stop": False,
                "restart_task": None,
            }
        }
        self._scrcpy_mgr = _SessionManager(session)
        self._registry = SimpleNamespace(
            get=lambda _serial: SimpleNamespace(is_available=True)
        )
        self.restart_calls: list[str] = []

    def _adb_serial_prefer_usb_over_tcp(self, logical: str) -> str:
        return logical

    async def _restart_with_backoff(
        self,
        logical: str,
        _queue: asyncio.Queue,
        _loop: asyncio.AbstractEventLoop,
        *,
        source: str,
    ) -> None:
        self.restart_calls.append(f"{logical}:{source}")


def test_tick_reports_retrying_session_as_recovering_not_healthy(caplog) -> None:
    async def _run() -> _Agent:
        agent = _Agent(_Session(streaming=False))
        supervisor = RelaySupervisor(agent)

        with caplog.at_level(logging.INFO, logger="relay.supervisor"):
            await supervisor._tick()
        return agent

    agent = asyncio.run(_run())
    assert "healthy=0" in caplog.text
    assert "recovering=1" in caplog.text
    assert "missing=0" in caplog.text
    assert agent.restart_calls == []


def test_tick_reports_handshaken_session_as_healthy(caplog) -> None:
    async def _run() -> _Agent:
        agent = _Agent(_Session(streaming=True))
        supervisor = RelaySupervisor(agent)

        with caplog.at_level(logging.INFO, logger="relay.supervisor"):
            await supervisor._tick()
        return agent

    agent = asyncio.run(_run())
    assert "healthy=1" in caplog.text
    assert "recovering=0" in caplog.text
    assert agent.restart_calls == []


def test_tick_restarts_when_session_object_is_stale_and_thread_is_dead(caplog) -> None:
    async def _run() -> _Agent:
        agent = _Agent(_Session(streaming=False, alive=False))
        supervisor = RelaySupervisor(agent)

        with caplog.at_level(logging.INFO, logger="relay.supervisor"):
            await supervisor._tick()
        return agent

    agent = asyncio.run(_run())
    assert "healthy=0" in caplog.text
    assert "recovering=0" in caplog.text
    assert "missing=1" in caplog.text
    assert agent.restart_calls == ["device-1:supervisor"]
