"""
media_adapter_control_servicer.py — gRPC control plane for local media adapters.

Only stream lifecycle, WebRTC signaling, and status travel over this service.
H264 media is published by the adapter directly to go2rtc.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Callable, Optional

import grpc

log = logging.getLogger("media_adapter_control")

_servicer: Optional["MediaAdapterControlServicer"] = None


def get_media_adapter_servicer() -> Optional["MediaAdapterControlServicer"]:
    return _servicer


def set_media_adapter_servicer(s: "MediaAdapterControlServicer") -> None:
    global _servicer
    _servicer = s


class MediaAdapterConnection:
    """One outbound gRPC stream from one local media-adapter."""

    def __init__(self, adapter_id: str, send_q: asyncio.Queue) -> None:
        self.adapter_id = adapter_id
        self.relay_id = ""
        self.serials: set[str] = set()
        self.streams: dict[str, dict] = {}
        self._q = send_q
        self._pending: dict[str, asyncio.Future] = {}

    async def send_command(self, ctrl_msg, request_id: str, timeout: float) -> dict:
        loop = asyncio.get_running_loop()
        started = loop.time()
        fut = loop.create_future()
        self._pending[request_id] = fut
        await self._q.put(ctrl_msg)
        try:
            result = await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
            log.info(
                "media adapter command result adapter_id=%s request_id=%s total_ms=%.1f ok=%s",
                self.adapter_id,
                request_id,
                (loop.time() - started) * 1000.0,
                bool(result.get("ok", False)) if isinstance(result, dict) else False,
            )
            return result
        except asyncio.TimeoutError:
            log.warning(
                "media adapter command timeout adapter_id=%s request_id=%s timeout_s=%.1f total_ms=%.1f",
                self.adapter_id,
                request_id,
                timeout,
                (loop.time() - started) * 1000.0,
            )
            return {"ok": False, "error": "timeout", "retry_after_ms": 250}
        finally:
            self._pending.pop(request_id, None)

    def resolve(self, result_msg) -> None:
        fut = self._pending.get(result_msg.request_id)
        if fut and not fut.done():
            fut.set_result(_session_result_to_dict(result_msg))


class MediaAdapterControlServicer:
    """Server-side MediaAdapterControlService implementation."""

    def __init__(self, *, api_key: str = "") -> None:
        self._api_key = api_key
        self._conns: dict[str, MediaAdapterConnection] = {}
        self._serial_index: dict[str, str] = {}
        self._session_index: dict[str, str] = {}
        self._sessions: dict[str, dict] = {}
        self._on_register: Optional[Callable] = None

    def set_register_callback(self, on_register) -> None:
        self._on_register = on_register

    async def ControlStream(self, request_iterator, context):
        from .grpc_gen import relay_pb2

        if self._api_key:
            token = _metadata_value(context, "x-relay-api-key")
            if token != self._api_key:
                await context.abort(grpc.StatusCode.UNAUTHENTICATED, "invalid relay API key")
                return

        adapter_id: Optional[str] = None
        conn: Optional[MediaAdapterConnection] = None
        send_q: asyncio.Queue = asyncio.Queue(maxsize=512)
        enrollment_token = _metadata_value(context, "x-relay-enrollment-token")

        async def _reader():
            nonlocal adapter_id, conn
            try:
                async for msg in request_iterator:
                    kind = msg.WhichOneof("payload")
                    if kind == "register":
                        r = msg.register
                        candidate_adapter_id = r.adapter_id or f"media-{uuid.uuid4().hex[:8]}"
                        if self._on_register:
                            accepted = await _call_register_callback(self._on_register, {
                                "relay_id": r.relay_id or candidate_adapter_id,
                                "hostname": r.hostname,
                                "ip": r.ip,
                                "version": r.adapter_version,
                                "serials": list(r.serials),
                                "enrollment_token": enrollment_token,
                            })
                            if not accepted:
                                await context.abort(
                                    grpc.StatusCode.PERMISSION_DENIED,
                                    "invalid or missing media adapter enrollment token",
                                )
                                return
                        adapter_id = candidate_adapter_id
                        conn = MediaAdapterConnection(adapter_id, send_q)
                        conn.relay_id = r.relay_id
                        conn.serials = set(r.serials)
                        self._conns[adapter_id] = conn
                        self._index_serials(adapter_id, conn.serials)
                        await send_q.put(relay_pb2.MediaAdapterCommand(
                            ack=relay_pb2.MediaAdapterAck(
                                message=f"media adapter registered {len(r.serials)} serials"
                            )
                        ))
                        log.info(
                            "media adapter registered adapter_id=%s relay_id=%s host=%s serials=%d",
                            adapter_id,
                            r.relay_id,
                            r.hostname,
                            len(r.serials),
                        )
                    elif kind == "heartbeat" and conn is not None:
                        h = msg.heartbeat
                        self._unindex_serials(conn.serials)
                        conn.serials = set(h.serials)
                        conn.streams = {
                            s.serial: _stream_status_to_dict(s)
                            for s in h.streams
                            if s.serial
                        }
                        self._index_serials(conn.adapter_id, conn.serials)
                    elif kind == "session_result" and conn is not None:
                        conn.resolve(msg.session_result)
            finally:
                if adapter_id:
                    self._conns.pop(adapter_id, None)
                    if conn is not None:
                        self._unindex_serials(conn.serials)
                        for session_id, owner in list(self._session_index.items()):
                            if owner == adapter_id:
                                self._session_index.pop(session_id, None)
                                self._sessions.pop(session_id, None)
                    log.info("media adapter disconnected adapter_id=%s", adapter_id)
                await send_q.put(None)

        reader_task = asyncio.create_task(_reader())
        try:
            while True:
                out = await send_q.get()
                if out is None:
                    break
                yield out
        finally:
            if not reader_task.done():
                reader_task.cancel()
            try:
                await reader_task
            except asyncio.CancelledError:
                pass

    def conn_for_serial(self, serial: str) -> Optional[MediaAdapterConnection]:
        adapter_id = self._serial_index.get(serial)
        return self._conns.get(adapter_id) if adapter_id else None

    def conn_for_session(self, session_id: str) -> Optional[MediaAdapterConnection]:
        adapter_id = self._session_index.get(session_id)
        return self._conns.get(adapter_id) if adapter_id else None

    def has_serial(self, serial: str) -> bool:
        return self.conn_for_serial(serial) is not None

    def online_serials_snapshot(self) -> set[str]:
        return set(self._serial_index.keys())

    def streams_snapshot(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for conn in self._conns.values():
            out.update({serial: dict(stream) for serial, stream in conn.streams.items()})
        return out

    def stream_for_serial(self, serial: str) -> Optional[dict]:
        conn = self.conn_for_serial(serial)
        if conn is None:
            return None
        stream = conn.streams.get(serial)
        return dict(stream) if stream else None

    def session_info(self, session_id: str) -> Optional[dict]:
        session = self._sessions.get(session_id)
        return dict(session) if session else None

    async def create_session(self, payload: dict, timeout: float = 3.0) -> dict:
        from .grpc_gen import relay_pb2

        serial = str(payload.get("serial") or "")
        conn = self.conn_for_serial(serial)
        if not conn:
            return {"ok": False, "error": "no media adapter for serial", "retry_after_ms": 500}
        request_id = str(uuid.uuid4())
        cmd = relay_pb2.MediaAdapterCommand(start_session=relay_pb2.MediaAdapterStartSessionCmd(
            request_id=request_id,
            org_id=str(payload.get("org_id") or ""),
            user_id=str(payload.get("user_id") or ""),
            serial=serial,
            viewer_id=str(payload.get("viewer_id") or ""),
            ttl_seconds=int(payload.get("ttl_seconds") or 300),
            control=bool(payload.get("control", True)),
            profile=str(payload.get("profile") or ""),
            max_fps=int(payload.get("max_fps") or 0),
            max_width=int(payload.get("max_width") or 0),
            bitrate=int(payload.get("bitrate") or 0),
        ))
        result = await conn.send_command(cmd, request_id, timeout)
        if result.get("ok") and result.get("session_id"):
            session_id = str(result["session_id"])
            self._session_index[session_id] = conn.adapter_id
            self._sessions[session_id] = dict(result)
        return result

    async def answer_session(self, session_id: str, offer: dict, timeout: float = 3.0) -> dict:
        from .grpc_gen import relay_pb2

        conn = self.conn_for_session(session_id)
        if not conn:
            return {"ok": False, "error": "media adapter session not found", "retry_after_ms": 500}
        request_id = str(uuid.uuid4())
        cmd = relay_pb2.MediaAdapterCommand(answer_session=relay_pb2.MediaAdapterAnswerSessionCmd(
            request_id=request_id,
            session_id=session_id,
            sdp_type=str(offer.get("type") or ""),
            sdp=str(offer.get("sdp") or ""),
        ))
        result = await conn.send_command(cmd, request_id, timeout)
        if result.get("ok") and result.get("session_id"):
            self._sessions[str(result["session_id"])] = dict(result)
        return result

    async def heartbeat_session(self, session_id: str, ttl_seconds: int, timeout: float = 2.0) -> dict:
        from .grpc_gen import relay_pb2

        conn = self.conn_for_session(session_id)
        if not conn:
            return {"ok": False, "error": "media adapter session not found", "retry_after_ms": 500}
        request_id = str(uuid.uuid4())
        cmd = relay_pb2.MediaAdapterCommand(
            heartbeat_session=relay_pb2.MediaAdapterHeartbeatSessionCmd(
                request_id=request_id,
                session_id=session_id,
                ttl_seconds=int(ttl_seconds or 300),
            )
        )
        return await conn.send_command(cmd, request_id, timeout)

    async def close_session(self, session_id: str, timeout: float = 2.0) -> dict:
        from .grpc_gen import relay_pb2

        conn = self.conn_for_session(session_id)
        if not conn:
            return {"ok": True}
        request_id = str(uuid.uuid4())
        cmd = relay_pb2.MediaAdapterCommand(close_session=relay_pb2.MediaAdapterCloseSessionCmd(
            request_id=request_id,
            session_id=session_id,
        ))
        result = await conn.send_command(cmd, request_id, timeout)
        self._session_index.pop(session_id, None)
        self._sessions.pop(session_id, None)
        return result

    def _index_serials(self, adapter_id: str, serials: set[str]) -> None:
        for serial in serials:
            self._serial_index[serial] = adapter_id

    def _unindex_serials(self, serials: set[str]) -> None:
        for serial in serials:
            self._serial_index.pop(serial, None)


def _session_result_to_dict(result) -> dict:
    return {
        "ok": result.ok,
        "error": result.error,
        "retry_after_ms": result.retry_after_ms,
        "id": result.session_id,
        "session_id": result.session_id,
        "serial": result.serial,
        "viewer_id": result.viewer_id,
        "stream_name": result.stream_name,
        "stream_source": result.stream_source,
        "expires_at_unix_ms": result.expires_at_unix_ms,
        "type": result.sdp_type,
        "sdp": result.sdp,
    }


def _stream_status_to_dict(status) -> dict:
    return {
        "serial": status.serial,
        "stream_name": status.stream_name,
        "stream_source": status.stream_source,
        "active": status.active,
        "connected": status.connected,
        "width": status.width,
        "height": status.height,
        "frames": status.frames,
        "bytes": status.bytes,
        "keyframes": status.keyframes,
        "publish_errors": status.publish_errors,
        "last_frame_unix_ms": status.last_frame_unix_ms,
        "error": status.error,
    }


def _metadata_value(context, key: str) -> str:
    try:
        metadata = context.invocation_metadata() or ()
    except Exception:
        return ""
    wanted = key.lower()
    for item in metadata:
        try:
            k = str(item.key).lower()
            v = str(item.value)
        except AttributeError:
            try:
                k = str(item[0]).lower()
                v = str(item[1])
            except Exception:
                continue
        if k == wanted:
            return v.strip()
    return ""


async def _call_register_callback(callback, payload: dict) -> bool:
    try:
        result = await asyncio.wait_for(callback(payload), timeout=5.0)
    except Exception as exc:
        log.warning("media adapter register callback failed: %s", exc)
        return False
    return result is not False
