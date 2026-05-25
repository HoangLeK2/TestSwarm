"""
relay/control_client.py — AgentControlClient

Manages the gRPC Channel 2 (AgentControlService.ControlStream).
Runs independently from the video stream (RelayService.Stream) on the same
gRPC channel object — HTTP/2 multiplexing keeps them isolated so a slow
bootstrap command (180s) never blocks H264 video frames.

Responsibilities:
  - Send RegisterMsg on connect
  - Send HeartbeatMsg every 30s
  - Receive ServerControlMsg (bootstrap / restart_u2 / restart_atx / shell)
  - Execute via relay_agent._execute_command (runs in thread pool)
  - Send CommandResultMsg back
  - Reconnect independently of Channel 1 with exponential backoff
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import socket
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from relay.agent import RelayAgent

logger = logging.getLogger("relay.control_client")

_AGENT_VERSION = "2.1.0"

# CMD_TYPE constants — must match agent.py / adb_relay_server.py
_CMD_SHELL           = 0
_CMD_RESTART_U2      = 1
_CMD_RESTART_ATX     = 3
_CMD_BOOTSTRAP       = 4
_CMD_SHELL_VAL       = 0
_CMD_RESTART_SCRCPY  = 7


def _primary_lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return ""
    finally:
        try:
            s.close()
        except Exception:
            pass


class AgentControlClient:
    """
    Manages AgentControlService.ControlStream (Channel 2) independently
    of the H264 video stream.
    """

    def __init__(self, grpc_channel, api_key: Optional[str], relay_agent: "RelayAgent") -> None:
        self._channel     = grpc_channel
        self._api_key     = api_key or ""
        self._agent       = relay_agent
        self._running     = True

    async def run(self) -> None:
        attempt, base = 0, 0.5
        while self._running:
            try:
                await self._stream_once()
                attempt = 0
                if self._running:
                    await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                if not self._running:
                    break
                attempt += 1
                delay = min(base * (2 ** attempt), 8.0) * (1.0 + 0.2 * random.random())
                logger.warning(
                    "control stream failed (attempt %d): %s — retry in %.1fs",
                    attempt, exc, delay,
                )
                await asyncio.sleep(delay)

    def stop(self) -> None:
        self._running = False

    async def _stream_once(self) -> None:
        from .grpc_gen import relay_pb2, relay_pb2_grpc

        meta = []
        if self._api_key:
            meta.append(("x-relay-api-key", self._api_key))
        if self._agent._enrollment_token:
            meta.append(("x-relay-enrollment-token", self._agent._enrollment_token))
        stub = relay_pb2_grpc.AgentControlServiceStub(self._channel)

        send_q: asyncio.Queue = asyncio.Queue(maxsize=64)

        # Send register immediately
        await send_q.put(relay_pb2.AgentControlMsg(
            register=relay_pb2.RegisterMsg(
                relay_id      = self._agent._relay_id,
                serials       = list(self._agent._registry.online_serials),
                hostname      = socket.gethostname(),
                ip            = _primary_lan_ip(),
                agent_version = _AGENT_VERSION,
            )
        ))

        async def _producer():
            while True:
                msg = await send_q.get()
                if msg is None:
                    return
                yield msg

        heartbeat_task = asyncio.create_task(self._heartbeat_loop(send_q))
        try:
            async for ctrl in stub.ControlStream(_producer(), metadata=meta):
                await self._handle(ctrl, send_q)
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
            # Drain producer
            try:
                send_q.put_nowait(None)
            except asyncio.QueueFull:
                pass

    async def _heartbeat_loop(self, q: asyncio.Queue) -> None:
        from .grpc_gen import relay_pb2
        while True:
            await asyncio.sleep(30)
            try:
                await q.put(relay_pb2.AgentControlMsg(
                    heartbeat=relay_pb2.HeartbeatMsg(
                        relay_id = self._agent._relay_id,
                        serials  = list(self._agent._registry.online_serials),
                    )
                ))
            except Exception:
                pass

    async def _handle(self, msg, q: asyncio.Queue) -> None:
        from .grpc_gen import relay_pb2

        kind = msg.WhichOneof("payload")
        if kind == "ack":
            logger.info("control channel registered: %s", msg.ack.message)
            return

        if kind not in ("bootstrap", "restart_u2", "restart_atx", "shell", "restart_scrcpy"):
            return

        cmd = getattr(msg, kind)
        cmd_type_map = {
            "bootstrap":      _CMD_BOOTSTRAP,
            "restart_u2":     _CMD_RESTART_U2,
            "restart_atx":    _CMD_RESTART_ATX,
            "shell":          _CMD_SHELL_VAL,
            "restart_scrcpy": _CMD_RESTART_SCRCPY,
        }
        cmd_type = cmd_type_map[kind]
        raw_cmd  = getattr(cmd, "cmd", "")
        serial   = cmd.serial
        timeout  = int(cmd.timeout) if cmd.timeout else 60
        msg_id   = cmd.msg_id

        loop = asyncio.get_event_loop()
        try:
            raw_result = await loop.run_in_executor(
                None,
                self._agent._execute_command,
                msg_id, serial, raw_cmd, timeout, cmd_type,
            )
            res = json.loads(raw_result) if isinstance(raw_result, str) else raw_result
        except Exception as exc:
            res = {"ok": False, "exit_code": -1, "output": "", "error": str(exc)}

        try:
            await q.put(relay_pb2.AgentControlMsg(
                result=relay_pb2.CommandResultMsg(
                    msg_id    = msg_id,
                    ok        = bool(res.get("ok", False)),
                    exit_code = int(res.get("exit_code", -1)),
                    output    = str(res.get("output", "")),
                    error     = str(res.get("error", "")),
                )
            ))
        except Exception as exc:
            logger.warning("failed to enqueue command result: %s", exc)
