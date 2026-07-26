from __future__ import annotations

import asyncio
import json
import threading

import pytest

from relay.agent import CMD_ADB_CONNECT, CMD_SHELL, RelayAgent


async def _wait_event(event: threading.Event, timeout: float) -> bool:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, event.wait, timeout)


@pytest.mark.asyncio
async def test_ws_command_same_serial_keeps_order(monkeypatch):
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="r1",
        relay_mode="ws",
    )
    send_q: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    first_started = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()

    def _fake_execute(msg_id, serial, cmd, timeout, cmd_type):
        if msg_id == "cmd-1":
            first_started.set()
            release_first.wait(2.0)
        elif msg_id == "cmd-2":
            second_started.set()
        return json.dumps(
            {
                "type": "result",
                "msg_id": msg_id,
                "ok": True,
                "exit_code": 0,
                "output": "",
                "error": "",
            }
        )

    monkeypatch.setattr(agent, "_execute_command", _fake_execute)

    try:
        await agent._handle_server_msg(
            {
                "type": "command",
                "msg_id": "cmd-1",
                "serial": "dev-001",
                "cmd": "input tap 1 1",
                "timeout": 5,
                "cmd_type": CMD_SHELL,
            },
            send_q,
            loop,
        )
        await agent._handle_server_msg(
            {
                "type": "command",
                "msg_id": "cmd-2",
                "serial": "dev-001",
                "cmd": "input tap 2 2",
                "timeout": 5,
                "cmd_type": CMD_SHELL,
            },
            send_q,
            loop,
        )

        assert await asyncio.wait_for(_wait_event(first_started, 1.0), timeout=1.2)
        assert not second_started.wait(0.1)
        release_first.set()
        assert await asyncio.wait_for(_wait_event(second_started, 1.0), timeout=1.2)
    finally:
        release_first.set()
        agent._cancel_command_workers()


@pytest.mark.asyncio
async def test_ws_command_different_serials_run_in_parallel(monkeypatch):
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="r1",
        relay_mode="ws",
    )
    send_q: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    first_started = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()

    def _fake_execute(msg_id, serial, cmd, timeout, cmd_type):
        if msg_id == "cmd-1":
            first_started.set()
            release_first.wait(2.0)
        elif msg_id == "cmd-2":
            second_started.set()
        return json.dumps(
            {
                "type": "result",
                "msg_id": msg_id,
                "ok": True,
                "exit_code": 0,
                "output": "",
                "error": "",
            }
        )

    monkeypatch.setattr(agent, "_execute_command", _fake_execute)

    try:
        await agent._handle_server_msg(
            {
                "type": "command",
                "msg_id": "cmd-1",
                "serial": "dev-001",
                "cmd": "input tap 1 1",
                "timeout": 5,
                "cmd_type": CMD_SHELL,
            },
            send_q,
            loop,
        )
        await agent._handle_server_msg(
            {
                "type": "command",
                "msg_id": "cmd-2",
                "serial": "dev-002",
                "cmd": "input tap 2 2",
                "timeout": 5,
                "cmd_type": CMD_SHELL,
            },
            send_q,
            loop,
        )

        assert await asyncio.wait_for(_wait_event(first_started, 1.0), timeout=1.2)
        assert await asyncio.wait_for(_wait_event(second_started, 0.3), timeout=0.5)
    finally:
        release_first.set()
        agent._cancel_command_workers()


@pytest.mark.asyncio
async def test_adb_connect_command_refreshes_devices_immediately(monkeypatch):
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="r1",
        relay_mode="ws",
    )
    send_q: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    refreshed = asyncio.Event()

    def _fake_execute(msg_id, serial, cmd, timeout, cmd_type):
        assert cmd_type == CMD_ADB_CONNECT
        return json.dumps(
            {
                "type": "result",
                "msg_id": msg_id,
                "ok": True,
                "exit_code": 0,
                "output": "connected to dev-001",
                "error": "",
            }
        )

    async def _fake_refresh(_send_q, _loop, requested_serial):
        assert requested_serial == "dev-001"
        refreshed.set()

    monkeypatch.setattr(agent, "_execute_command", _fake_execute)
    monkeypatch.setattr(
        agent,
        "_refresh_devices_after_adb_connect",
        _fake_refresh,
    )

    try:
        await agent._handle_server_msg(
            {
                "type": "command",
                "msg_id": "cmd-connect",
                "serial": "dev-001",
                "cmd": "",
                "timeout": 5,
                "cmd_type": CMD_ADB_CONNECT,
            },
            send_q,
            loop,
        )

        await asyncio.wait_for(refreshed.wait(), timeout=1.0)
    finally:
        agent._cancel_command_workers()


@pytest.mark.asyncio
async def test_post_adb_connect_refresh_publishes_heartbeat(monkeypatch):
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="r1",
        relay_mode="ws",
    )
    send_q: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    monkeypatch.setattr("relay.agent._list_serials", lambda: ["dev-001"])
    monkeypatch.setattr(
        agent,
        "_ensure_capabilities_for_serials",
        lambda _serials, _loop: asyncio.sleep(0),
    )
    monkeypatch.setattr(
        agent,
        "_apply_usb_preference_reconcile",
        lambda _send_q, _loop: asyncio.sleep(0),
    )

    await agent._refresh_devices_after_adb_connect(send_q, loop, "dev-001")

    heartbeat = json.loads(await asyncio.wait_for(send_q.get(), timeout=1.0))
    assert heartbeat["type"] == "heartbeat"
    assert heartbeat["serials"] == ["dev-001"]
    await asyncio.gather(*list(agent._capability_probe_tasks), return_exceptions=True)


@pytest.mark.asyncio
async def test_empty_registry_heartbeat_does_not_block_on_adb_snapshot(monkeypatch):
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="r1",
        relay_mode="ws",
    )
    send_q: asyncio.Queue = asyncio.Queue()

    list_calls: list[bool] = []
    monkeypatch.setattr(
        "relay.agent._list_serials",
        lambda: list_calls.append(True) or ["10AE7S00HD002JK"],
    )
    monkeypatch.setattr(
        agent,
        "_ensure_capabilities_for_serials",
        lambda _serials, _loop: asyncio.sleep(0),
    )
    monkeypatch.setattr(
        agent,
        "_apply_usb_preference_reconcile",
        lambda _send_q, _loop: asyncio.sleep(0),
    )

    await agent._send_heartbeat(send_q)

    heartbeat = json.loads(await asyncio.wait_for(send_q.get(), timeout=1.0))
    assert heartbeat["type"] == "heartbeat"
    assert heartbeat["serials"] == []
    assert list_calls == []
    await asyncio.gather(*list(agent._capability_probe_tasks), return_exceptions=True)


@pytest.mark.asyncio
async def test_heartbeat_publishes_serial_before_slow_capability_probe(monkeypatch):
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="r1",
        relay_mode="ws",
    )
    send_q: asyncio.Queue = asyncio.Queue()

    agent._registry.on_adb_event("dev-001", "device")
    probe_started = asyncio.Event()
    release_probe = asyncio.Event()

    async def _slow_capability_probe(_serials, _loop):
        probe_started.set()
        await release_probe.wait()
        agent._registry.set_capabilities(
            "dev-001",
            {
                "android_version": "14",
                "sdk": "34",
                "brand": "google",
                "model": "Pixel",
                "device_name": "Pixel",
                "wlan_ip": "192.168.1.20",
            },
        )
        agent._hb_caps_version += 1

    async def _skip_reconcile(_send_q, _loop):
        return None

    monkeypatch.setattr(agent, "_ensure_capabilities_for_serials", _slow_capability_probe)
    monkeypatch.setattr(agent, "_apply_usb_preference_reconcile", _skip_reconcile)

    await agent._send_heartbeat(send_q)

    heartbeat = json.loads(await asyncio.wait_for(send_q.get(), timeout=0.1))
    assert heartbeat["type"] == "heartbeat"
    assert heartbeat["serials"] == ["dev-001"]
    assert heartbeat["capabilities"] == []

    await asyncio.wait_for(probe_started.wait(), timeout=0.2)
    release_probe.set()
    await asyncio.gather(*list(agent._capability_probe_tasks), return_exceptions=True)

    followup = json.loads(await asyncio.wait_for(send_q.get(), timeout=0.2))
    assert followup["type"] == "heartbeat"
    assert followup["serials"] == ["dev-001"]
    assert followup["capabilities"][0]["serial"] == "dev-001"
    assert followup["capabilities"][0]["model"] == "Pixel"


@pytest.mark.asyncio
async def test_online_device_event_does_not_wait_for_capability_probe(monkeypatch):
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="r1",
        relay_mode="ws",
    )
    send_q: asyncio.Queue = asyncio.Queue()
    probe_started = asyncio.Event()
    release_probe = asyncio.Event()

    async def _slow_capability_probe(_serials, _loop):
        probe_started.set()
        await release_probe.wait()

    async def _skip_reconcile(_send_q, _loop):
        return None

    monkeypatch.setattr(agent, "_ensure_capabilities_for_serials", _slow_capability_probe)
    monkeypatch.setattr(agent, "_apply_usb_preference_reconcile", _skip_reconcile)

    await agent._on_device_event("dev-002", "device", send_q)

    heartbeat = json.loads(await asyncio.wait_for(send_q.get(), timeout=0.1))
    assert heartbeat["type"] == "heartbeat"
    assert heartbeat["serials"] == ["dev-002"]

    await asyncio.wait_for(probe_started.wait(), timeout=0.2)
    release_probe.set()
    await asyncio.gather(*list(agent._capability_probe_tasks), return_exceptions=True)
