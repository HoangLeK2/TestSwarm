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
  - Route bootstrap to the dedicated async admission path
  - Execute other commands via relay_agent._execute_command (ADB thread pool)
  - Send CommandResultMsg back
  - Reconnect independently of Channel 1 with exponential backoff
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import socket
import time
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from relay.agent import RelayAgent

logger = logging.getLogger("relay.control_client")

_AGENT_VERSION = "2.1.0"

# The log spam this fixes came from logging every retry, not from retrying. So
# keep polling fast — an admin who re-enables an agent expects it back in
# seconds — and make the *log* quiet instead.
DISABLED_RETRY_DELAY_S = 5.0
DISABLED_RELOG_EVERY_S = 600.0


def _is_agent_disabled_error(exc: Exception) -> bool:
    """Server said this agent is disabled, not that the credentials are wrong."""
    code = getattr(exc, "code", None)
    try:
        status = code() if callable(code) else code
    except Exception:
        status = None
    if getattr(status, "name", "") == "FAILED_PRECONDITION":
        return True
    details = getattr(exc, "details", None)
    try:
        text = details() if callable(details) else details
    except Exception:
        text = None
    return "disabled by admin" in str(text or "").lower()

# CMD_TYPE constants — must match agent.py / adb_relay_server.py
_CMD_SHELL           = 0
_CMD_RESTART_U2      = 1
_CMD_RESTART_ATX     = 3
_CMD_BOOTSTRAP       = 4
_CMD_SHELL_VAL       = 0
_CMD_RESTART_SCRCPY  = 7

def _is_maintenance_kind(kind: str | None) -> bool:
    return kind in {"bootstrap", "restart_u2", "restart_atx", "restart_scrcpy"}


def _control_command_fields(msg) -> tuple[str | None, str, str, str, int]:
    kind = msg.WhichOneof("payload")
    cmd = getattr(msg, kind) if kind else None
    msg_id = str(getattr(cmd, "msg_id", "") or "")
    serial = str(getattr(cmd, "serial", "") or "")
    raw_cmd = str(getattr(cmd, "cmd", "") or "")
    timeout = int(getattr(cmd, "timeout", 0) or 0)
    return kind, msg_id, serial, raw_cmd, timeout


def _control_lane(msg) -> str:
    kind, _, _, _, _ = _control_command_fields(msg)
    if kind == "shell":
        return "interactive"
    if _is_maintenance_kind(kind):
        return "maintenance"
    return "interactive"


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
        disabled_logged_at = 0.0
        while self._running:
            try:
                await self._stream_once()
                attempt = 0
                disabled_logged_at = 0.0
                if self._running:
                    await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                if not self._running:
                    break
                if _is_agent_disabled_error(exc):
                    # An admin turned this agent off. Keep checking often so
                    # re-enabling feels immediate, but say it once rather than
                    # once per attempt.
                    now = time.monotonic()
                    if now - disabled_logged_at >= DISABLED_RELOG_EVERY_S:
                        disabled_logged_at = now
                        logger.warning(
                            "agent disabled by admin — retrying every %.0fs until it "
                            "is re-enabled",
                            DISABLED_RETRY_DELAY_S,
                        )
                    await asyncio.sleep(DISABLED_RETRY_DELAY_S)
                    continue
                attempt += 1
                disabled_logged_at = 0.0
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
        worker_queues: dict[tuple[str, str], asyncio.Queue] = {}
        worker_tasks: list[asyncio.Task] = []

        async def _worker(name: str, q: asyncio.Queue) -> None:
            while True:
                msg, received_at = await q.get()
                try:
                    await self._handle_timed(msg, send_q, received_at)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("control %s worker failed: %s", name, exc)

        def _queue_limit(lane: str) -> int:
            return 256 if lane == "interactive" else 64

        def _queue_for(serial: str, lane: str) -> asyncio.Queue:
            key = (serial or "-", lane)
            q = worker_queues.get(key)
            if q is not None:
                return q
            q = asyncio.Queue(maxsize=_queue_limit(lane))
            worker_queues[key] = q
            worker_tasks.append(asyncio.create_task(_worker(f"{key[0]}:{key[1]}", q)))
            return q

        try:
            async for ctrl in stub.ControlStream(_producer(), metadata=meta):
                received_at = asyncio.get_running_loop().time()
                lane = _control_lane(ctrl)
                _, _, serial, _, _ = _control_command_fields(ctrl)
                target_q = _queue_for(serial, lane)
                try:
                    target_q.put_nowait((ctrl, received_at))
                except asyncio.QueueFull:
                    await self._enqueue_queue_full_result(ctrl, send_q, serial=serial, lane=lane)
        finally:
            heartbeat_task.cancel()
            for task in worker_tasks:
                task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
            await asyncio.gather(*worker_tasks, return_exceptions=True)
            # Drain producer
            try:
                send_q.put_nowait(None)
            except asyncio.QueueFull:
                pass

    async def _enqueue_queue_full_result(
        self,
        msg,
        q: asyncio.Queue,
        *,
        serial: str,
        lane: str,
    ) -> None:
        from .grpc_gen import relay_pb2

        kind, msg_id, _, _, _ = _control_command_fields(msg)
        if not msg_id:
            logger.warning("control queue full kind=%s serial=%s lane=%s", kind, serial or "-", lane)
            return
        error = f"control queue full: serial={serial or '-'} lane={lane}"
        try:
            await asyncio.wait_for(
                q.put(relay_pb2.AgentControlMsg(
                    result=relay_pb2.CommandResultMsg(
                        msg_id=msg_id,
                        ok=False,
                        exit_code=-1,
                        output="",
                        error=error,
                    )
                )),
                timeout=1.0,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "control result queue full kind=%s serial=%s lane=%s",
                kind,
                serial or "-",
                lane,
            )
        except Exception as exc:
            logger.warning(
                "failed to enqueue queue-full result kind=%s serial=%s lane=%s error=%s",
                kind,
                serial or "-",
                lane,
                exc,
            )

    async def _handle_timed(self, msg, q: asyncio.Queue, received_at: float) -> None:
        kind, msg_id, serial, _, _ = _control_command_fields(msg)
        loop = asyncio.get_running_loop()
        start = loop.time()
        try:
            await self._handle(msg, q)
        finally:
            finished = loop.time()
            if kind != "ack":
                logger.info(
                    "control command handled kind=%s serial=%s msg_id=%s queue_wait_ms=%.1f total_ms=%.1f",
                    kind or "-",
                    serial or "-",
                    msg_id or "-",
                    (start - received_at) * 1000.0,
                    (finished - received_at) * 1000.0,
                )

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
            assigned = (msg.ack.relay_id or "").strip()
            if assigned and assigned != self._agent._relay_id:
                from .agent import save_relay_id

                self._agent._relay_id = save_relay_id(assigned)
                logger.info("relay identity issued by server: %s", assigned)
            if assigned:
                self._agent._identity_ready.set()
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

        try:
            if kind == "bootstrap":
                raw_result = await self._agent._execute_bootstrap_command(
                    msg_id,
                    serial,
                    timeout,
                )
            else:
                from relay.runtime import adb_executor

                loop = asyncio.get_running_loop()
                raw_result = await loop.run_in_executor(
                    adb_executor(),
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
