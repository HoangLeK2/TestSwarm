from __future__ import annotations

import asyncio
import json

import pytest

from relay.agent import CMD_SHELL, RelayAgent
from relay.payloads import (
    CommandMessage,
    HeartbeatMessage,
    RegisterMessage,
    U2RequestMessage,
    decode_server_message,
)
from relay.runtime import dumps


def test_decode_server_message_returns_typed_command() -> None:
    msg = decode_server_message(
        b'{"type":"command","msg_id":"cmd-1","serial":"dev-1",'
        b'"cmd":"echo ok","timeout":"5","cmd_type":0,"extra":"ignored"}'
    )

    assert isinstance(msg, CommandMessage)
    assert msg.msg_id == "cmd-1"
    assert msg.serial == "dev-1"
    assert msg.timeout == "5"


def test_decode_server_message_returns_typed_u2_request() -> None:
    msg = decode_server_message(
        b'{"type":"u2_request","msg_id":"u2-1","serial":"dev-1",'
        b'"method":"POST","path":"/jsonrpc/0","body":"{}",'
        b'"content_type":"application/json","visible":true}'
    )

    assert isinstance(msg, U2RequestMessage)
    assert msg.method == "POST"
    assert msg.visible is True


def test_decode_unknown_message_falls_back_to_dict() -> None:
    msg = decode_server_message(b'{"type":"future_message","id":"x"}')

    assert msg["type"] == "future_message"
    assert "_schema_error" in msg


def test_outbound_control_structs_preserve_wire_shape() -> None:
    register = json.loads(
        dumps(RegisterMessage(relay_id="relay-1", serials=["dev-1"]))
    )
    heartbeat = json.loads(
        dumps(HeartbeatMessage(serials=["dev-1"], capabilities=[{"serial": "dev-1"}]))
    )

    assert register == {
        "type": "register",
        "relay_id": "relay-1",
        "serials": ["dev-1"],
        "version": "2.0.0",
    }
    assert heartbeat == {
        "type": "heartbeat",
        "serials": ["dev-1"],
        "capabilities": [{"serial": "dev-1"}],
    }


@pytest.mark.asyncio
async def test_typed_command_dispatch_reaches_command_worker(monkeypatch) -> None:
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="r1",
        relay_mode="ws",
    )
    send_q: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def _fake_execute(msg_id, serial, cmd, timeout, cmd_type):
        assert msg_id == "cmd-typed"
        assert serial == "dev-1"
        assert cmd == "echo ok"
        assert timeout == 5
        assert cmd_type == CMD_SHELL
        return json.dumps(
            {
                "type": "result",
                "msg_id": msg_id,
                "ok": True,
                "exit_code": 0,
                "output": "ok",
                "error": "",
            }
        )

    monkeypatch.setattr(agent, "_execute_command", _fake_execute)

    msg = decode_server_message(
        b'{"type":"command","msg_id":"cmd-typed","serial":"dev-1",'
        b'"cmd":"echo ok","timeout":"5","cmd_type":0}'
    )
    await agent._handle_server_msg(msg, send_q, loop)

    result = json.loads(await asyncio.wait_for(send_q.get(), timeout=1.0))
    assert result["ok"] is True
    assert result["msg_id"] == "cmd-typed"
    agent._cancel_command_workers()
