from __future__ import annotations

import asyncio

from relay.agent import RelayAgent


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
