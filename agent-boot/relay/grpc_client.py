"""
relay/grpc_client.py — GrpcRelayClient

Drop-in replacement for the WebSocket connection in agent.py.
Reads from the same send_queue as the WS sender — items are either:
  - str  : JSON message (register / heartbeat / result) → AgentMsg(meta=...)
  - VideoPacket: typed scrcpy frame → AgentMsg(video=...) without legacy repack
  - bytes: binary blob in 0x53 frame format → AgentMsg(video=VideoFrame(...))

ControlMsg objects received from the server are put into ctrl_q where
_consume_ctrl() in agent.py picks them up and routes them.

Reconnect: exponential backoff 1s → 30s (gRPC channel reconnects TCP automatically;
the RPC stream itself must be re-initiated on failure).
"""
from __future__ import annotations

import asyncio
import logging
import os
import struct
import time
from typing import Optional

import grpc
from grpc import aio as grpc_aio

from .video_packet import VideoPacket

log = logging.getLogger("grpc_client")

# Matches scrcpy_relay.py binary frame format
_PTS_CONFIG_MASK = 0x8000_0000_0000_0000


def _env_int(name: str, default: int, *, lo: int = 1, hi: int = 128 * 1024 * 1024) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except Exception:
        return default
    return max(lo, min(hi, value))


_GRPC_MAX_MESSAGE_BYTES = _env_int(
    "RELAY_GRPC_MAX_MESSAGE_BYTES",
    4 * 1024 * 1024,
    lo=1024 * 1024,
)
_GRPC_MAX_VIDEO_FRAME_BYTES = _env_int(
    "RELAY_GRPC_MAX_VIDEO_FRAME_BYTES",
    max(512 * 1024, _GRPC_MAX_MESSAGE_BYTES - 128 * 1024),
    lo=128 * 1024,
    hi=_GRPC_MAX_MESSAGE_BYTES,
)
_GRPC_LARGE_VIDEO_FRAME_WARN_BYTES = _env_int(
    "RELAY_GRPC_LARGE_VIDEO_FRAME_WARN_BYTES",
    min(_GRPC_MAX_VIDEO_FRAME_BYTES, 1024 * 1024),
    lo=64 * 1024,
    hi=_GRPC_MAX_VIDEO_FRAME_BYTES,
)
_GRPC_VIDEO_STATS_INTERVAL_S = _env_int(
    "RELAY_GRPC_VIDEO_STATS_INTERVAL_S",
    30,
    lo=5,
    hi=3600,
)
_GRPC_VIDEO_WRITE_WAIT_WARN_MS = _env_int(
    "RELAY_GRPC_VIDEO_WRITE_WAIT_WARN_MS",
    50,
    lo=1,
    hi=60_000,
)

_GRPC_CHANNEL_OPTIONS = [
    ("grpc.keepalive_time_ms",               10_000),
    ("grpc.keepalive_timeout_ms",              5_000),
    ("grpc.keepalive_permit_without_calls",        1),
    ("grpc.http2.max_pings_without_data",          0),
    ("grpc.http2.min_time_between_pings_ms",   5_000),
    ("grpc.initial_reconnect_backoff_ms",      1_000),
    ("grpc.max_reconnect_backoff_ms",         30_000),
    ("grpc.max_send_message_length",    _GRPC_MAX_MESSAGE_BYTES),
    ("grpc.max_receive_message_length", _GRPC_MAX_MESSAGE_BYTES),
]


def create_grpc_channel(
    addr: str,
    *,
    tls_enabled: bool = False,
    root_cert_file: str = "",
    options: list[tuple[str, int]] | None = None,
):
    channel_options = options if options is not None else _GRPC_CHANNEL_OPTIONS
    if not tls_enabled:
        return grpc_aio.insecure_channel(addr, options=channel_options)

    root_certificates = None
    if root_cert_file:
        with open(root_cert_file, "rb") as cert_file:
            root_certificates = cert_file.read()
    credentials = grpc.ssl_channel_credentials(root_certificates=root_certificates)
    return grpc_aio.secure_channel(addr, credentials, options=channel_options)


def parse_binary_video_frame(data: bytes):
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


def _parse_binary_frame(data: bytes):
    """Backward-compatible internal alias for older callers."""
    return parse_binary_video_frame(data)


def agent_message_from_item(item, relay_pb2):
    """Adapt one transport-neutral queue item to its gRPC message."""
    if isinstance(item, str):
        return relay_pb2.AgentMsg(meta=item.encode())

    if isinstance(item, VideoPacket):
        frame = relay_pb2.VideoFrame(
            serial=item.serial,
            data=item.data,
            is_config=item.is_config,
            is_key=item.is_key,
            pts_us=item.pts_us,
            width=item.width if item.is_config else 0,
            height=item.height if item.is_config else 0,
        )
        return relay_pb2.AgentMsg(video=frame)

    if isinstance(item, bytes):
        parsed = parse_binary_video_frame(item)
        if parsed is None:
            return None
        serial, payload, is_config, is_key, pts_us, width, height = parsed
        frame = relay_pb2.VideoFrame(
            serial=serial,
            data=payload,
            is_config=is_config,
            is_key=is_key,
            pts_us=pts_us,
            width=width if is_config else 0,
            height=height if is_config else 0,
        )
        return relay_pb2.AgentMsg(video=frame)

    return None


class _GrpcVideoSendStats:
    def __init__(self) -> None:
        self.sent = 0
        self.sent_bytes = 0
        self.large = 0
        self.dropped_oversize = 0
        self.dropped_bytes = 0
        self.max_bytes = 0
        self.write_wait_samples = 0
        self.write_wait_warn = 0
        self.write_wait_total_ms = 0
        self.write_wait_max_ms = 0
        self.last_log = time.monotonic()

    def record_sent(self, size: int) -> None:
        self.sent += 1
        self.sent_bytes += size
        self.max_bytes = max(self.max_bytes, size)
        if size >= _GRPC_LARGE_VIDEO_FRAME_WARN_BYTES:
            self.large += 1

    def record_drop(self, size: int) -> None:
        self.dropped_oversize += 1
        self.dropped_bytes += size
        self.max_bytes = max(self.max_bytes, size)

    def record_write_wait(self, wait_ms: int) -> None:
        self.write_wait_samples += 1
        self.write_wait_total_ms += max(0, wait_ms)
        self.write_wait_max_ms = max(self.write_wait_max_ms, wait_ms)
        if wait_ms >= _GRPC_VIDEO_WRITE_WAIT_WARN_MS:
            self.write_wait_warn += 1

    def log_if_due(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self.last_log < _GRPC_VIDEO_STATS_INTERVAL_S:
            return
        if not (
            self.sent
            or self.large
            or self.dropped_oversize
            or self.max_bytes
            or self.write_wait_warn
        ):
            self.last_log = now
            return
        log_fn = (
            log.warning
            if self.dropped_oversize or self.large or self.write_wait_warn
            else log.debug
        )
        avg_wait_ms = (
            round(self.write_wait_total_ms / self.write_wait_samples)
            if self.write_wait_samples
            else 0
        )
        log_fn(
            "gRPC video send stats sent=%d bytes=%d large=%d "
            "dropped_oversize=%d dropped_bytes=%d max_frame_bytes=%d "
            "limit=%d write_wait_samples=%d write_wait_avg_ms=%d "
            "write_wait_max_ms=%d write_wait_warn=%d",
            self.sent,
            self.sent_bytes,
            self.large,
            self.dropped_oversize,
            self.dropped_bytes,
            self.max_bytes,
            _GRPC_MAX_VIDEO_FRAME_BYTES,
            self.write_wait_samples,
            avg_wait_ms,
            self.write_wait_max_ms,
            self.write_wait_warn,
        )
        self.sent = 0
        self.sent_bytes = 0
        self.large = 0
        self.dropped_oversize = 0
        self.dropped_bytes = 0
        self.max_bytes = 0
        self.write_wait_samples = 0
        self.write_wait_warn = 0
        self.write_wait_total_ms = 0
        self.write_wait_max_ms = 0
        self.last_log = now


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
        channel=None,
        tls_enabled: bool = False,
        root_cert_file: str = "",
        max_video_frame_bytes: int | None = None,
    ) -> None:
        self._addr = server_addr          # "host:50051"
        self._api_key = api_key or ""
        self._agent_id = agent_id
        self._send_queue = send_queue     # shared with ScrcpyRelaySession (same as WS)
        self._loop = loop
        self._shared_channel = channel    # pre-created channel shared with control stream
        self._tls_enabled = tls_enabled
        self._root_cert_file = root_cert_file
        self._max_video_frame_bytes = (
            _GRPC_MAX_VIDEO_FRAME_BYTES
            if max_video_frame_bytes is None
            else max(1, max_video_frame_bytes)
        )
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

    async def _stream_once(self, channel=None, *, initial_meta: str | None = None) -> None:
        # Called either from start() (which already set _running=True) or
        # directly from agent.py — ensure the generator loop runs in both cases.
        self._running = True
        from .grpc_gen import relay_pb2, relay_pb2_grpc

        metadata = [
            ("x-relay-api-key", self._api_key),
            ("x-agent-id", self._agent_id),
        ]

        # Use shared channel if provided (agent.py creates it to share with
        # AgentControlClient so both streams run over the same TCP connection).
        shared = channel or self._shared_channel
        if shared is not None:
            stub = relay_pb2_grpc.RelayServiceStub(shared)
            call = stub.Stream(
                self._frame_generator(relay_pb2, initial_meta=initial_meta),
                metadata=metadata,
            )
            async for ctrl_msg in call:
                try:
                    self.ctrl_q.put_nowait(ctrl_msg)
                except asyncio.QueueFull:
                    pass
            return

        async with create_grpc_channel(
            self._addr,
            tls_enabled=self._tls_enabled,
            root_cert_file=self._root_cert_file,
        ) as ch:
            stub = relay_pb2_grpc.RelayServiceStub(ch)
            call = stub.Stream(
                self._frame_generator(relay_pb2, initial_meta=initial_meta),
                metadata=metadata,
            )
            # Drain ControlMsg responses from the server
            async for ctrl_msg in call:
                try:
                    self.ctrl_q.put_nowait(ctrl_msg)
                except asyncio.QueueFull:
                    pass

    async def _frame_generator(self, relay_pb2, *, initial_meta: str | None = None):
        """
        Yield AgentMsg objects from send_queue.

        initial_meta belongs to this RPC attempt and is yielded before the
        shared queue. If the RPC fails before consuming the generator, it
        cannot leak into a later attempt.

        Items are str (JSON → meta), typed VideoPacket, or legacy 0x53 bytes.
        Stops when self._running is False or a None sentinel is received.
        """
        if initial_meta is not None:
            yield relay_pb2.AgentMsg(meta=initial_meta.encode())

        stats = _GrpcVideoSendStats()
        while self._running:
            try:
                item = await asyncio.wait_for(self._send_queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                stats.log_if_due()
                continue  # keep the stream alive (keepalive handled by gRPC)

            if item is None:
                stats.log_if_due(force=True)
                return  # sentinel — clean shutdown

            message = agent_message_from_item(item, relay_pb2)
            if message is None:
                continue
            is_video = message.WhichOneof("payload") == "video"
            if is_video:
                size = len(message.video.data)
                if size > self._max_video_frame_bytes:
                    stats.record_drop(size)
                    stats.log_if_due(force=True)
                    continue
                stats.record_sent(size)
                stats.log_if_due()
                yielded_at = time.monotonic()
            yield message
            if is_video:
                stats.record_write_wait(
                    max(0, round((time.monotonic() - yielded_at) * 1_000))
                )
