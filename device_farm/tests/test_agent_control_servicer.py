"""Unit tests for AgentControlServicer — no gRPC transport needed."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from runtime.transports.agent_control_servicer import AgentControlServicer, ControlConnection


# ── ControlConnection ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_command_resolves_future():
    q = asyncio.Queue()
    conn = ControlConnection(relay_id="r1", send_q=q)

    # Fake proto msg with a msg_id
    fake_cmd = MagicMock()
    fake_cmd.WhichOneof.return_value = "bootstrap"
    fake_cmd.bootstrap.msg_id = "msg-001"

    async def _resolve_after():
        await asyncio.sleep(0.01)
        result_msg = MagicMock()
        result_msg.msg_id = "msg-001"
        result_msg.ok = True
        result_msg.exit_code = 0
        result_msg.output = "done"
        result_msg.error = ""
        conn.resolve(result_msg)

    asyncio.create_task(_resolve_after())
    result = await conn.send_command(fake_cmd, timeout=2.0)

    assert result["ok"] is True
    assert result["output"] == "done"
    assert result["exit_code"] == 0


@pytest.mark.asyncio
async def test_send_command_timeout():
    q = asyncio.Queue()
    conn = ControlConnection(relay_id="r1", send_q=q)

    fake_cmd = MagicMock()
    fake_cmd.WhichOneof.return_value = "bootstrap"
    fake_cmd.bootstrap.msg_id = "msg-timeout"

    result = await conn.send_command(fake_cmd, timeout=0.05)
    assert result["ok"] is False
    assert result["error"] == "timeout"


# ── AgentControlServicer ──────────────────────────────────────────────────────

def _make_servicer_with_conn(serial: str = "dev-001") -> tuple[AgentControlServicer, ControlConnection]:
    svc = AgentControlServicer()
    q = asyncio.Queue()
    conn = ControlConnection(relay_id="relay-1", send_q=q)
    conn.serials = {serial}
    svc._conns["relay-1"] = conn
    svc._serial_index[serial] = "relay-1"
    return svc, conn


def test_conn_for_serial_found():
    svc, conn = _make_servicer_with_conn("dev-001")
    assert svc.conn_for_serial("dev-001") is conn


def test_conn_for_serial_missing():
    svc, _ = _make_servicer_with_conn("dev-001")
    assert svc.conn_for_serial("unknown") is None


def test_conn_for_relay():
    svc, conn = _make_servicer_with_conn()
    assert svc.conn_for_relay("relay-1") is conn
    assert svc.conn_for_relay("relay-999") is None


def test_online_relay_ids():
    svc, _ = _make_servicer_with_conn()
    assert "relay-1" in svc.online_relay_ids()


def test_find_serial_by_ip():
    svc = AgentControlServicer()
    q = asyncio.Queue()
    conn = ControlConnection(relay_id="r2", send_q=q)
    conn.serials = {"192.168.1.5:5555"}
    svc._conns["r2"] = conn
    svc._serial_index["192.168.1.5:5555"] = "r2"

    assert svc.find_serial_by_ip("192.168.1.5") == "192.168.1.5:5555"
    assert svc.find_serial_by_ip("10.0.0.1") is None


@pytest.mark.asyncio
async def test_bootstrap_no_conn_returns_error():
    svc = AgentControlServicer()
    result = await svc.bootstrap("nonexistent-serial", timeout=1.0)
    assert result["ok"] is False
    assert "no control channel" in result["error"]


@pytest.mark.asyncio
async def test_restart_u2_no_conn_returns_error():
    svc = AgentControlServicer()
    result = await svc.restart_u2("nonexistent", timeout=1.0)
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_restart_scrcpy_no_conn_returns_error():
    svc = AgentControlServicer()
    result = await svc.restart_scrcpy("nonexistent", timeout=1.0)
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_start_grpc_server_wires_control_persistence_callbacks(monkeypatch):
    from runtime.transports import grpc_relay_server
    from runtime.transports.agent_control_servicer import get_control_servicer

    class _FakeServer:
        def __init__(self) -> None:
            self.started = False

        def add_insecure_port(self, _addr: str) -> int:
            return 1

        async def start(self) -> None:
            self.started = True

    fake_server = _FakeServer()

    monkeypatch.setattr(grpc_relay_server.aio, "server", lambda **_kwargs: fake_server)
    monkeypatch.setattr(
        grpc_relay_server.relay_pb2_grpc,
        "add_RelayServiceServicer_to_server",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        grpc_relay_server.relay_pb2_grpc,
        "add_AgentControlServiceServicer_to_server",
        lambda *_args, **_kwargs: None,
    )

    async def on_register(_payload: dict) -> bool:
        return True

    async def on_heartbeat(_payload: dict) -> None:
        return None

    async def on_offline(_relay_id: str) -> None:
        return None

    server = await grpc_relay_server.start_grpc_server(
        relay_manager=object(),
        api_key="relay-key",
        port=0,
        control_callbacks=(on_register, on_heartbeat, on_offline),
    )

    svc = get_control_servicer()
    assert server is fake_server
    assert fake_server.started is True
    assert svc is not None
    assert svc._on_register is on_register
    assert svc._on_heartbeat is on_heartbeat
    assert svc._on_offline is on_offline
