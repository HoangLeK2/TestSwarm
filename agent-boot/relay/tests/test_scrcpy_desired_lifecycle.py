from __future__ import annotations

import asyncio

from relay.agent import (
    SCRCPY_DEFAULT_BITRATE,
    SCRCPY_DEFAULT_MAX_FPS,
    SCRCPY_DEFAULT_MAX_WIDTH,
    RelayAgent,
)


def _agent(monkeypatch) -> RelayAgent:
    monkeypatch.setenv("SCRCPY_AUTO_RESUME", "true")
    return RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="relay-1",
        enrollment_token="",
    )


def test_auto_resume_does_not_seed_scrcpy_for_online_devices(monkeypatch):
    agent = _agent(monkeypatch)
    agent._registry.on_adb_event("serial-1", "device")

    agent._ensure_default_scrcpy_desired()

    assert agent._scrcpy_desired == {}


def test_auto_resume_normalizes_existing_desired_ports_only(monkeypatch):
    agent = _agent(monkeypatch)
    agent._registry.on_adb_event("serial-1", "device")
    agent._registry.on_adb_event("serial-2", "device")
    agent._scrcpy_desired = {
        "serial-1": {
            "desired": True,
            "manual_stop": False,
            "cfg": {"port": 27183},
        },
        "serial-2": {
            "desired": True,
            "manual_stop": False,
            "cfg": {"port": 27183},
        },
    }

    agent._ensure_default_scrcpy_desired()

    assert agent._scrcpy_desired["serial-1"]["cfg"]["port"] == 27183
    assert agent._scrcpy_desired["serial-2"]["cfg"]["port"] == 27184


def test_resume_without_scrcpy_start_does_not_start_session(monkeypatch):
    agent = _agent(monkeypatch)
    agent._registry.on_adb_event("serial-1", "device")
    starts: list[str] = []

    async def fake_start_desired(logical, _queue, _loop):
        starts.append(logical)
        return True

    monkeypatch.setattr(agent, "_start_desired_scrcpy", fake_start_desired)

    async def run() -> None:
        agent._ensure_default_scrcpy_desired()
        await agent._resume_desired_scrcpy_sessions(
            asyncio.Queue(),
            asyncio.get_running_loop(),
            source="device-online",
        )

    asyncio.run(run())

    assert starts == []


def test_start_desired_scrcpy_reuses_existing_session_without_stop(monkeypatch):
    agent = _agent(monkeypatch)
    agent._scrcpy_desired = {
        "serial-1": {
            "desired": True,
            "manual_stop": False,
            "cfg": {
                "max_fps": 30,
                "max_width": 800,
                "enable_control": True,
                "port": 27183,
                "bitrate": 2_000_000,
                "low_latency": False,
            },
        }
    }

    class _FakeScrcpyManager:
        def __init__(self) -> None:
            self.starts: list[str] = []
            self.stops: list[tuple[str, str]] = []
            self.running = False

        async def start_session(self, **kwargs) -> None:
            self.starts.append(str(kwargs["serial"]))
            self.running = True

        async def stop_session(self, serial: str, reason: str = "manual_stop") -> None:
            self.stops.append((serial, reason))
            self.running = False

        def get(self, serial: str):
            return object() if self.running and serial == "serial-1" else None

    mgr = _FakeScrcpyManager()
    agent._scrcpy_mgr = mgr

    async def run() -> None:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        assert await agent._start_desired_scrcpy("serial-1", queue, loop)
        assert await agent._start_desired_scrcpy("serial-1", queue, loop)

    asyncio.run(run())

    assert mgr.starts == ["serial-1", "serial-1"]
    assert mgr.stops == []


def test_scrcpy_start_without_profile_uses_fleet_defaults(monkeypatch):
    agent = _agent(monkeypatch)

    class _FakeScrcpyManager:
        def __init__(self) -> None:
            self.starts: list[dict] = []

        async def start_session(self, **kwargs) -> None:
            self.starts.append(kwargs)

        def get(self, serial: str):
            return object() if serial == "serial-1" else None

    mgr = _FakeScrcpyManager()
    agent._scrcpy_mgr = mgr

    async def run() -> None:
        await agent._handle_server_msg(
            {"type": "scrcpy_start", "serial": "serial-1"},
            asyncio.Queue(),
            asyncio.get_running_loop(),
        )

    asyncio.run(run())

    cfg = agent._scrcpy_desired["serial-1"]["cfg"]
    assert cfg["max_fps"] == SCRCPY_DEFAULT_MAX_FPS
    assert cfg["max_width"] == SCRCPY_DEFAULT_MAX_WIDTH
    assert cfg["bitrate"] == SCRCPY_DEFAULT_BITRATE
    assert mgr.starts[-1]["max_fps"] == SCRCPY_DEFAULT_MAX_FPS
    assert mgr.starts[-1]["max_width"] == SCRCPY_DEFAULT_MAX_WIDTH
    assert mgr.starts[-1]["bitrate"] == SCRCPY_DEFAULT_BITRATE
