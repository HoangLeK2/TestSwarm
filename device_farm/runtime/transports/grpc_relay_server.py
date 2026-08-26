"""
grpc_relay_server.py — gRPC bidirectional relay server for agent-boot ↔ device_farm.

Each agent-boot instance opens one gRPC bidirectional stream. All N phones on that
agent-boot are multiplexed over this single HTTP/2 stream. Per-phone fairness and
backpressure isolation therefore happen in agent-boot's FairSendQueue; HTTP/2 does
not provide per-phone flow-control isolation inside this RPC.

Protocol (proto/relay.proto):
  agent-boot → device_farm : AgentMsg { meta: bytes (JSON) }
  device_farm → agent-boot : ControlMsg { serial, data, is_json }

The proto still contains AgentMsg.video for older agents, but production video
does not travel through backend gRPC anymore. H264 is published by the local
media adapter/go2rtc path so this service stays on control-plane traffic.

Auth: gRPC metadata  x-relay-api-key  (same key as WebSocket relay).
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

import grpc
from grpc import aio

from common.fast_codec import dumps, loads

from .adb_relay_server import _REQUEST_REPLY_TYPES
from .grpc_gen import relay_pb2, relay_pb2_grpc

log = logging.getLogger("grpc_relay")

def _env_int(name: str, default: int, *, lo: int = 1, hi: int = 128 * 1024 * 1024) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except Exception:
        return default
    return max(lo, min(hi, value))


def _grpc_max_message_bytes() -> int:
    return _env_int(
        "RELAY_GRPC_MAX_MESSAGE_BYTES",
        4 * 1024 * 1024,
        lo=1024 * 1024,
    )


class RelayServicer(relay_pb2_grpc.RelayServiceServicer):
    """
    Handles one bidirectional gRPC stream from one agent-boot instance.

    One instance is created per connected agent. Injected with AdbRelayManager
    so it can dispatch received frames and route control commands back.
    """

    def __init__(self, relay_manager: Any, api_key: Optional[str]) -> None:
        self._rm = relay_manager
        self._api_key = api_key

    async def Stream(
        self,
        request_iterator: Any,  # AsyncIterator[AgentMsg]
        context: aio.ServicerContext,
    ) -> None:
        # ── Auth ──────────────────────────────────────────────────────────────
        metadata = dict(context.invocation_metadata())
        token = metadata.get("x-relay-api-key", "")
        if self._api_key and token != self._api_key:
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "invalid relay API key")
            return

        agent_id = metadata.get("x-agent-id", f"grpc-{id(context)}")
        log.info("gRPC agent connected: %s", agent_id)

        # Per-agent ctrl queue — device_farm puts ControlMsg objects here,
        # _send_controls() drains them to the gRPC stream.
        ctrl_q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._rm.register_grpc_agent(agent_id, ctrl_q)

        # relay_id for AdbRelayManager registration — use agent_id
        relay_id: Optional[str] = None
        conn: Optional[Any] = None
        async def _recv_frames() -> None:
            nonlocal relay_id, conn
            try:
                async for msg in request_iterator:
                    payload = msg.WhichOneof("payload")
                    if payload == "video":
                        # Legacy agents may still send AgentMsg.video. Drop it
                        # here so backend does not become a media relay again.
                        continue
                    elif payload == "meta":
                        # JSON control message from agent (register / heartbeat / result)
                        try:
                            data = loads(msg.meta)
                        except Exception:
                            continue
                        relay_id, conn = await self._handle_json(
                            data, agent_id, ctrl_q, relay_id, conn
                        )
            finally:
                # Signal _send_controls() to exit so asyncio.gather() can complete
                # and the outer finally (unregister cleanup) runs correctly.
                try:
                    ctrl_q.put_nowait(None)
                except Exception:
                    pass

        async def _send_controls() -> None:
            while True:
                ctrl_msg = await ctrl_q.get()
                if ctrl_msg is None:  # sentinel — stop
                    break
                try:
                    await context.write(ctrl_msg)
                except Exception as exc:
                    log.debug("gRPC write error: %s", exc)
                    break

        try:
            await asyncio.gather(_recv_frames(), _send_controls())
        except Exception as exc:
            log.debug("gRPC stream error agent=%s: %s", agent_id, exc)
        finally:
            self._rm.unregister_grpc_agent(agent_id, expected_queue=ctrl_q)
            if relay_id:
                await self._rm.unregister(
                    relay_id,
                    "gRPC agent disconnected",
                    expected_conn=conn,
                )
            log.info("gRPC agent disconnected: %s", agent_id)

    async def _handle_json(
        self,
        msg: dict,
        agent_id: str,
        ctrl_q: asyncio.Queue,
        relay_id: Optional[str],
        conn: Optional[Any],
    ):
        """Handle JSON control messages from agent-boot (register/heartbeat/result)."""
        from .adb_relay_server import RelayConnection
        import uuid

        mtype = msg.get("type", "")

        if mtype == "register":
            relay_id = msg.get("relay_id") or f"grpc-{uuid.uuid4().hex[:8]}"
            serials = set(msg.get("serials") or [])
            conn = RelayConnection(relay_id, _GrpcWriteQueue(ctrl_q))
            conn.serials = serials
            await self._rm.register(conn)
            # Send ack back
            ack_json = dumps({
                "type": "ack",
                "message": f"registered {len(serials)} serials",
            }).encode()
            ack_msg = relay_pb2.ControlMsg(serial="", data=ack_json, is_json=True)
            try:
                ctrl_q.put_nowait(ack_msg)
            except asyncio.QueueFull:
                pass
            log.info("gRPC relay registered: id=%s serials=%s", relay_id, sorted(serials))

        elif mtype == "heartbeat" and conn is not None:
            new_serials = set(msg.get("serials") or [])
            # Capabilities FIRST. update_serials fires the device-online callback,
            # which binds u2 using wlan_ip from capabilities. With serials first the
            # callback always saw empty caps and had to wait for data that could
            # only arrive after it returned — see bind_relay_u2.
            caps = msg.get("capabilities")
            if caps:
                self._rm.update_capabilities(caps)
            await self._rm.update_serials(relay_id, new_serials)

        elif mtype == "result" and conn is not None:
            conn.resolve(
                msg.get("msg_id", ""),
                {
                    "ok":        msg.get("ok", False),
                    "output":    msg.get("output", ""),
                    "exit_code": msg.get("exit_code", -1),
                    "error":     msg.get("error", ""),
                },
            )

        elif mtype == "u2_result" and conn is not None:
            conn.resolve(
                msg.get("msg_id", ""),
                {
                    "ok":           msg.get("ok", False),
                    "status":       msg.get("status", 0),
                    "body":         msg.get("body", ""),
                    "content_type": msg.get("content_type", ""),
                },
            )

        elif mtype in _REQUEST_REPLY_TYPES and conn is not None:
            conn.resolve(msg.get("id", ""), msg)

        elif mtype in ("a11y_ack", "a11y_result") and conn is not None:
            conn.resolve(msg.get("id", ""), msg)

        return relay_id, conn


class _GrpcWriteQueue:
    """
    Adapter that makes a gRPC ctrl_q look like the asyncio.Queue used by
    RelayConnection._write_queue. Converts str/bytes items to ControlMsg proto.
    """

    def __init__(self, ctrl_q: asyncio.Queue) -> None:
        self._q = ctrl_q

    async def put(self, item: Any) -> None:
        if item is None:
            await self._q.put(None)
            return
        msg = _item_to_control_msg(item)
        if msg:
            await self._q.put(msg)

    def put_nowait(self, item: Any) -> None:
        if item is None:
            self._q.put_nowait(None)
            return
        msg = _item_to_control_msg(item)
        if msg:
            self._q.put_nowait(msg)


def _item_to_control_msg(item: Any) -> Optional[relay_pb2.ControlMsg]:
    """Convert a RelayConnection write_queue item to a ControlMsg proto."""
    if isinstance(item, relay_pb2.ControlMsg):
        return item
    if isinstance(item, str):
        # JSON command from device_farm → agent
        return relay_pb2.ControlMsg(serial="", data=item.encode(), is_json=True)
    if isinstance(item, bytes):
        # Binary scrcpy control: [0x43][slen][serial][ctrl_data]
        if len(item) >= 2 and item[0] == 0x43:
            slen = item[1]
            if len(item) >= 2 + slen:
                serial = item[2:2 + slen].decode("utf-8", errors="replace")
                ctrl_data = item[2 + slen:]
                return relay_pb2.ControlMsg(serial=serial, data=ctrl_data, is_json=False)
    return None


# ── Server startup ─────────────────────────────────────────────────────────────

async def start_grpc_server(
    relay_manager: Any,
    api_key: Optional[str] = None,
    port: int = 50051,
    tls_cert_file: str = "",
    tls_key_file: str = "",
    allow_insecure: bool = True,
    control_callbacks: tuple | None = None,
) -> Any:
    """Start gRPC relay server. Returns the server object (call stop() on shutdown)."""
    grpc_max_message_bytes = _grpc_max_message_bytes()
    server = aio.server(
        options=[
            ("grpc.max_send_message_length",    grpc_max_message_bytes),
            ("grpc.max_receive_message_length", grpc_max_message_bytes),
            ("grpc.so_reuseport", 1),
            ("grpc.max_concurrent_streams", 512),
            # Keepalive: detect dead agent connections within ~15s
            ("grpc.keepalive_time_ms", 10_000),
            ("grpc.keepalive_timeout_ms", 5_000),
            ("grpc.keepalive_permit_without_calls", 1),
            ("grpc.http2.max_pings_without_data", 0),
            # Allow client keepalive pings (otherwise gRPC closes as "abuse")
            ("grpc.http2.min_ping_interval_without_data_ms", 5_000),
            # Larger write buffer = fewer syscalls for video streaming
            ("grpc.http2.write_buffer_size", 65536),
        ]
    )
    relay_pb2_grpc.add_RelayServiceServicer_to_server(
        RelayServicer(relay_manager, api_key), server
    )

    # ── AgentControlService (control plane — separate from video stream) ────
    from .agent_control_servicer import AgentControlServicer, set_control_servicer
    ctrl_servicer = AgentControlServicer()
    if control_callbacks is not None:
        ctrl_servicer.set_persistence_callbacks(*control_callbacks)
    set_control_servicer(ctrl_servicer)
    relay_pb2_grpc.add_AgentControlServiceServicer_to_server(ctrl_servicer, server)

    # ── MediaAdapterControlService (media lifecycle/signaling only) ─────────
    from .media_adapter_control_servicer import (
        MediaAdapterControlServicer,
        set_media_adapter_servicer,
    )
    media_servicer = MediaAdapterControlServicer(api_key=api_key or "")
    if control_callbacks is not None:
        media_servicer.set_register_callback(control_callbacks[0])
    set_media_adapter_servicer(media_servicer)
    relay_pb2_grpc.add_MediaAdapterControlServiceServicer_to_server(media_servicer, server)
    env_name = os.environ.get("DEVICE_FARM_ENV", "").strip().lower()
    is_prod_like = env_name in {"prod", "production", "staging"}
    tls_ready = bool(tls_cert_file and tls_key_file)

    if tls_ready:
        with open(tls_key_file, "rb") as key_file, open(tls_cert_file, "rb") as cert_file:
            key_bytes = key_file.read()
            cert_bytes = cert_file.read()
        server_credentials = grpc.ssl_server_credentials(((key_bytes, cert_bytes),))
        server.add_secure_port(f"[::]:{port}", server_credentials)
        log.info("gRPC relay server uses TLS on port %d", port)
    else:
        if is_prod_like and not allow_insecure:
            raise RuntimeError(
                "Refusing insecure gRPC relay in production/staging. "
                "Set relay.tls_cert_file + relay.tls_key_file or explicitly enable allow_insecure_grpc."
            )
        server.add_insecure_port(f"[::]:{port}")
        log.warning("gRPC relay server is running WITHOUT TLS on port %d", port)
    await server.start()
    log.info("gRPC relay server listening on port %d", port)
    return server
