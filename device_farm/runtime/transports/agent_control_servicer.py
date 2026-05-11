"""
agent_control_servicer.py — AgentControlService gRPC servicer (server-side).

Runs on the same port as RelayService but as a completely separate HTTP/2 stream,
so bootstrap/restart commands (low-volume, long-running) never block H264 video.

Architecture:
  - One ControlConnection per connected agent-boot (keyed by relay_id)
  - serial → relay_id index for O(1) command routing from REST endpoints
  - Persistence callbacks injected by web/server.py (keeps this module DB-free)
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Callable, Optional

log = logging.getLogger("agent_control")

# Global singleton — set by grpc_relay_server.start_grpc_server()
_servicer: Optional["AgentControlServicer"] = None


def get_control_servicer() -> Optional["AgentControlServicer"]:
    return _servicer


def set_control_servicer(s: "AgentControlServicer") -> None:
    global _servicer
    _servicer = s


class ControlConnection:
    """One per connected agent-boot control stream."""

    def __init__(self, relay_id: str, send_q: asyncio.Queue) -> None:
        self.relay_id = relay_id
        self.serials: set[str] = set()
        self._q       = send_q
        self._pending: dict[str, asyncio.Future] = {}

    async def send_command(self, ctrl_msg, timeout: float) -> dict:
        kind   = ctrl_msg.WhichOneof("payload")
        msg_id = getattr(getattr(ctrl_msg, kind), "msg_id", "")
        loop   = asyncio.get_running_loop()
        fut    = loop.create_future()
        self._pending[msg_id] = fut
        await self._q.put(ctrl_msg)
        try:
            return await asyncio.wait_for(asyncio.shield(fut), timeout=timeout + 10.0)
        except asyncio.TimeoutError:
            return {"ok": False, "error": "timeout", "exit_code": -1, "output": ""}
        finally:
            self._pending.pop(msg_id, None)

    def resolve(self, result_msg) -> None:
        fut = self._pending.get(result_msg.msg_id)
        if fut and not fut.done():
            fut.set_result({
                "ok":        result_msg.ok,
                "exit_code": result_msg.exit_code,
                "output":    result_msg.output,
                "error":     result_msg.error,
            })


class AgentControlServicer:
    """
    gRPC servicer for AgentControlService.ControlStream.

    Not a subclass of the generated stub — we register it manually in
    grpc_relay_server.start_grpc_server() to avoid coupling to a specific
    generated file location.
    """

    def __init__(self) -> None:
        self._conns: dict[str, ControlConnection] = {}   # relay_id → conn
        self._serial_index: dict[str, str] = {}           # serial → relay_id

        self._on_register:  Optional[Callable] = None
        self._on_heartbeat: Optional[Callable] = None
        self._on_offline:   Optional[Callable] = None

    def set_persistence_callbacks(self, on_register, on_heartbeat, on_offline) -> None:
        self._on_register  = on_register
        self._on_heartbeat = on_heartbeat
        self._on_offline   = on_offline

    # ── gRPC bidi stream ────────────────────────────────────────────────────────
    async def ControlStream(self, request_iterator, context):
        from .grpc_gen import relay_pb2

        relay_id: Optional[str] = None
        conn: Optional[ControlConnection] = None
        send_q: asyncio.Queue = asyncio.Queue(maxsize=128)

        async def _reader():
            nonlocal relay_id, conn
            try:
                async for msg in request_iterator:
                    kind = msg.WhichOneof("payload")

                    if kind == "register":
                        r = msg.register
                        relay_id = r.relay_id or f"ctrl-{uuid.uuid4().hex[:8]}"
                        conn = ControlConnection(relay_id, send_q)
                        conn.serials = set(r.serials)
                        self._conns[relay_id] = conn
                        for s in r.serials:
                            self._serial_index[s] = relay_id

                        await send_q.put(relay_pb2.ServerControlMsg(
                            ack=relay_pb2.RegisterAck(
                                message=f"control channel registered {len(r.serials)} serials"
                            )
                        ))
                        log.info("control channel registered: relay_id=%s host=%s ip=%s serials=%d",
                                 relay_id, r.hostname, r.ip, len(r.serials))

                        if self._on_register:
                            asyncio.create_task(_safe(self._on_register({
                                "relay_id": relay_id,
                                "hostname": r.hostname,
                                "ip":       r.ip,
                                "version":  r.agent_version,
                                "serials":  list(r.serials),
                            })))

                    elif kind == "heartbeat" and conn is not None:
                        h = msg.heartbeat
                        new_serials = set(h.serials)
                        old_serials = {s for s, rid in self._serial_index.items() if rid == relay_id}
                        for s in old_serials - new_serials:
                            self._serial_index.pop(s, None)
                        for s in new_serials:
                            self._serial_index[s] = relay_id
                        conn.serials = new_serials

                        if self._on_heartbeat:
                            asyncio.create_task(_safe(self._on_heartbeat({
                                "relay_id": relay_id,
                                "serials":  sorted(new_serials),
                            })))

                    elif kind == "result" and conn is not None:
                        conn.resolve(msg.result)

            finally:
                if relay_id:
                    self._conns.pop(relay_id, None)
                    for s in list(self._serial_index):
                        if self._serial_index.get(s) == relay_id:
                            del self._serial_index[s]
                    if self._on_offline:
                        asyncio.create_task(_safe(self._on_offline(relay_id)))
                    log.info("control channel disconnected: relay_id=%s", relay_id)
                send_q.put_nowait(None)

        reader_task = asyncio.create_task(_reader())
        try:
            while True:
                out = await send_q.get()
                if out is None:
                    break
                yield out
        finally:
            reader_task.cancel()

    # ── Public API for REST endpoints ───────────────────────────────────────────

    def conn_for_serial(self, serial: str) -> Optional[ControlConnection]:
        rid = self._serial_index.get(serial)
        return self._conns.get(rid) if rid else None

    def find_serial_by_ip(self, ip: str) -> Optional[str]:
        """Return first registered serial whose IP part matches, ignoring port.
        Used when mDNS connects on a dynamic port different from what's in the DB.
        """
        for serial in self._serial_index:
            serial_ip = serial.split(":")[0] if ":" in serial else serial
            if serial_ip == ip:
                return serial
        return None

    def conn_for_relay(self, relay_id: str) -> Optional[ControlConnection]:
        return self._conns.get(relay_id)

    def online_relay_ids(self) -> list[str]:
        return list(self._conns.keys())

    async def bootstrap(self, serial: str, timeout: float = 180.0) -> dict:
        return await self._send(serial, "bootstrap", timeout)

    async def restart_u2(self, serial: str, timeout: float = 60.0) -> dict:
        return await self._send(serial, "restart_u2", timeout)

    async def restart_atx(self, serial: str, timeout: float = 30.0) -> dict:
        return await self._send(serial, "restart_atx", timeout)

    async def restart_scrcpy(self, serial: str, timeout: float = 30.0) -> dict:
        return await self._send(serial, "restart_scrcpy", timeout)

    async def shell(self, serial: str, cmd: str, timeout: float = 30.0) -> dict:
        return await self._send(serial, "shell", timeout, cmd=cmd)

    async def _send(self, serial: str, kind: str, timeout: float, *, cmd: str = "") -> dict:
        from .grpc_gen import relay_pb2

        conn = self.conn_for_serial(serial)
        if not conn:
            return {"ok": False, "error": "no control channel for serial", "exit_code": -1, "output": ""}

        msg_id   = str(uuid.uuid4())
        cmd_map  = {
            "bootstrap":      relay_pb2.BootstrapCmd,
            "restart_u2":     relay_pb2.RestartU2Cmd,
            "restart_atx":    relay_pb2.RestartAtxCmd,
            "restart_scrcpy": relay_pb2.RestartScrcpyCmd,
            "shell":          relay_pb2.ShellCmd,
        }
        cmd_cls  = cmd_map[kind]
        kwargs = {"msg_id": msg_id, "serial": serial, "timeout": int(timeout)}
        if kind == "shell":
            kwargs["cmd"] = cmd
        ctrl_msg = relay_pb2.ServerControlMsg(**{
            kind: cmd_cls(**kwargs)
        })
        return await conn.send_command(ctrl_msg, timeout)


async def _safe(coro) -> None:
    try:
        await asyncio.wait_for(coro, timeout=2.0)
    except Exception as exc:
        log.warning("control persistence callback failed: %s", exc)
