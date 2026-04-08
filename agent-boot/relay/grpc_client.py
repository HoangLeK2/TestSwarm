"""
relay/grpc_client.py — GrpcRelayClient

Drop-in replacement for the WebSocket connection in agent.py.
Reads from the same send_queue as the WS sender — items are either:
  - str  : JSON message (register / heartbeat / result) → AgentMsg(meta=...)
  - bytes: binary blob in 0x53 frame format → AgentMsg(video=VideoFrame(...))

ControlMsg objects received from the server are put into ctrl_q where
_consume_ctrl() in agent.py picks them up and routes them.

Reconnect: exponential backoff 1s → 30s (gRPC channel reconnects TCP automatically;
the RPC stream itself must be re-initiated on failure).
"""
from __future__ import annotations

import asyncio
import logging
import struct
from typing import Optional

log = logging.getLogger("grpc_client")

# Matches scrcpy_relay.py binary frame format
_PTS_CONFIG_MASK = 0x8000_0000_0000_0000


def _parse_binary_frame(data: bytes):
    """Parse 0x53 binary frame → (serial, payload, is_config, is_key, pts_us, w, h).

    Returns None if the frame is malformed or not a video frame.
    """
    if len(data) < 3 or data[0] != 0x53:
        return None
    flags = data[1]
    slen = data[2]
    if len(data) < 3 + slen + 4 + 8:
        return None
    serial = data[3:3 + slen].decode("utf-8", errors="replace")
    off = 3 + slen
    w, h = struct.unpack(">HH", data[off:off + 4])
    pts_raw, = struct.unpack(">Q", data[off + 4:off + 12])
    payload = data[off + 12:]
    is_config = bool(flags & 0x01)
    is_key = bool(flags & 0x02)
    pts_us = int(pts_raw & ~_PTS_CONFIG_MASK)
    return serial, payload, is_config, is_key, pts_us, w, h


class GrpcRelayClient:
    """
    gRPC bidirectional relay client.

    Usage:
        client = GrpcRelayClient(addr, api_key, agent_id, send_queue, loop)
        ctrl_q = client.ctrl_q       # read ControlMsg objects from here
        asyncio.create_task(client.start())
    """

    def __init__(
        self,
        server_addr: str,
        api_key: Optional[str],
        agent_id: str,
        send_queue: asyncio.Queue,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._addr = server_addr          # "host:50051"
        self._api_key = api_key or ""
        self._agent_id = agent_id
        self._send_queue = send_queue     # shared with ScrcpyRelaySession (same as WS)
        self._loop = loop
        self.ctrl_q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._running = False

    async def start(self) -> None:
        """Connect and stream. Reconnects with exponential backoff on failure."""
        self._running = True
        backoff = 1.0
        while self._running:
            try:
                await self._stream_once()
                backoff = 1.0  # clean exit — reset backoff for next attempt
            except Exception as exc:
                if not self._running:
                    break
                log.warning("gRPC stream lost: %s — retry in %.1fs", exc, backoff)
                backoff = min(backoff * 2, 30.0)
            # Always sleep before retry — prevents tight reconnect loop when
            # the server closes the stream cleanly (no exception on client side).
            if self._running:
                await asyncio.sleep(backoff)

    def stop(self) -> None:
        self._running = False

    async def _stream_once(self) -> None:
        # Called either from start() (which already set _running=True) or
        # directly from agent.py — ensure the generator loop runs in both cases.
        self._running = True
        from grpc import aio
        from .grpc_gen import relay_pb2, relay_pb2_grpc

        metadata = [
            ("x-relay-api-key", self._api_key),
            ("x-agent-id", self._agent_id),
        ]

        async with aio.insecure_channel(
            self._addr,
            options=[
                ("grpc.keepalive_time_ms",               10_000),
                ("grpc.keepalive_timeout_ms",              5_000),
                ("grpc.keepalive_permit_without_calls",        1),
                ("grpc.http2.max_pings_without_data",          0),
                ("grpc.http2.min_time_between_pings_ms",   5_000),
                ("grpc.initial_reconnect_backoff_ms",      1_000),
                ("grpc.max_reconnect_backoff_ms",         30_000),
                ("grpc.max_send_message_length",    4 * 1024 * 1024),
                ("grpc.max_receive_message_length", 4 * 1024 * 1024),
            ],
        ) as channel:
            stub = relay_pb2_grpc.RelayServiceStub(channel)
            call = stub.Stream(
                self._frame_generator(relay_pb2),
                metadata=metadata,
            )
            # Drain ControlMsg responses from the server
            async for ctrl_msg in call:
                try:
                    self.ctrl_q.put_nowait(ctrl_msg)
                except asyncio.QueueFull:
                    pass

    async def _frame_generator(self, relay_pb2):
        """
        Yield AgentMsg objects from send_queue.

        Items are str (JSON → meta) or bytes (0x53 binary → video).
        Stops when self._running is False or a None sentinel is received.
        """
        while self._running:
            try:
                item = await asyncio.wait_for(self._send_queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                continue  # keep the stream alive (keepalive handled by gRPC)

            if item is None:
                return  # sentinel — clean shutdown

            if isinstance(item, str):
                # JSON message: register / heartbeat / result
                yield relay_pb2.AgentMsg(meta=item.encode())
                continue

            if isinstance(item, bytes):
                parsed = _parse_binary_frame(item)
                if parsed is None:
                    # Unknown binary frame — skip
                    continue
                serial, payload, is_config, is_key, pts_us, w, h = parsed
                vf = relay_pb2.VideoFrame(
                    serial=serial,
                    data=payload,
                    is_config=is_config,
                    is_key=is_key,
                    pts_us=pts_us,
                    width=w if is_config else 0,
                    height=h if is_config else 0,
                )
                yield relay_pb2.AgentMsg(video=vf)
