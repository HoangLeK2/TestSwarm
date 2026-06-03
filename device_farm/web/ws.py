from __future__ import annotations

import asyncio
import base64
import ipaddress
import inspect
import json
import logging
import os
import struct
import time
import uuid
from typing import Any, Dict, Optional

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketDisconnect as StarletteWSDisconnect

from services import pairing as _pairing_mod
from core.config import Config
from db import crud as repo
from db.crud.user import get_user_org_id
from db.database import AsyncSessionLocal
from runtime.core import DeviceManager, DeviceState
from services.multi_control import MultiControlCoordinator
from tenancy.background import (
    ensure_device_org_id,
    list_device_serials_for_user,
    lookup_device_by_key,
)
from tenancy.context import tenant_context

log = logging.getLogger(__name__)

# Frontend stream sender tuning. H.264 is reference-frame based: sending old
# P-frames after the client/server has fallen behind produces visible bursty
# playback. Prefer dropping stale deltas and forcing a fresh IDR so viewers stay
# close to live.
STREAM_STALE_DELTA_DROP_MS = max(
    0.0,
    float(os.environ.get("STREAM_STALE_DELTA_DROP_MS", "180.0")),
)
STREAM_WS_LOCK_WAIT_MS = max(
    1.0,
    float(os.environ.get("STREAM_WS_LOCK_WAIT_MS", "60.0")),
)
STREAM_WS_SEND_TIMEOUT_MS = max(
    50.0,
    float(os.environ.get("STREAM_WS_SEND_TIMEOUT_MS", "250.0")),
)


def _bind_pending_kw_only(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Only pass kwargs that bind_pending_device accepts (older images may lack adb_*)."""
    params = inspect.signature(repo.bind_pending_device).parameters
    return {k: v for k, v in meta.items() if k in params}


def _is_private_ip(host: str) -> bool:
    from core.net_utils import is_private_ip

    return is_private_ip(host)


def _is_trusted_device_lan_ip(host: str) -> bool:
    from core.net_utils import is_trusted_device_lan_ip

    return is_trusted_device_lan_ip(host)


def _parse_agent_binary_frame(buf: bytes) -> Dict[str, Any] | None:
    """Parse binary frame from agent (same protocol as server→browser).

    Frame layout (shared by 0x01 JPEG, 0x10 H264 config, 0x11 H264 video):
        buf[0]          frame_type
        buf[1]          serial_len (slen)
        buf[2..2+slen]  serial (not used server-side)
        buf[2+slen]     w : 2B BE
        buf[2+slen+2]   h : 2B BE
        buf[2+slen+4:]  payload (varies by type)

    For 0x10 config frames, payload:
        [flags : 1B] [avcc_record ...]
        flags bit 0: config_changed (1 = SPS/PPS changed, browser must reset decoder)

    For 0x11 video frames, payload:
        [is_key : 1B] [pts_hi : 4B BE] [pts_lo : 4B BE] [avcc_data ...]
    """
    if len(buf) < 6:
        return None
    frame_type = buf[0]
    slen = buf[1]
    if len(buf) < 2 + slen + 4:
        return None
    base = 2 + slen
    w = struct.unpack_from(">H", buf, base)[0]
    h = struct.unpack_from(">H", buf, base + 2)[0]
    doff = base + 4
    if frame_type == 0x01:
        return {"type": "jpeg", "w": w, "h": h, "data": buf[doff:]}
    if frame_type == 0x10:
        # flags byte added in v2 of protocol
        if len(buf) < doff + 1:
            return None
        flags = buf[doff]
        config_changed = bool(flags & 0x01)
        return {
            "type": "h264_config",
            "w": w, "h": h,
            "config_changed": config_changed,
            "data": buf[doff + 1:],
        }
    if frame_type == 0x11:
        if len(buf) < doff + 9:
            return None
        is_key = buf[doff] != 0
        pts_hi, pts_lo = struct.unpack_from(">II", buf, doff + 1)
        pts_us = pts_hi * 4_294_967_296 + pts_lo
        return {
            "type": "h264_video",
            "w": w,
            "h": h,
            "is_key": is_key,
            "pts_us": pts_us,
            "data": buf[doff + 9:],
        }
    return None


def _is_droppable_frame(buf: bytes) -> bool:
    """True for non-key H264 video frames (safe to drop when queue is stale)."""
    if not buf or len(buf) < 2:
        return False
    # Only H264 video frames are droppable; config/JPEG must be kept.
    if buf[0] != 0x11:
        return False
    slen = buf[1]
    base = 2 + slen
    # frame_type + slen + serial + w/h + is_key byte
    if len(buf) < base + 5:
        return False
    is_key = buf[base + 4] != 0
    return not is_key


def _is_config_frame(buf: bytes) -> bool:
    return bool(buf) and len(buf) >= 1 and buf[0] == 0x10


def _frame_serial_bytes(buf: bytes) -> bytes:
    """Extract raw serial bytes from wire frame; empty bytes if malformed."""
    if not buf or len(buf) < 2:
        return b""
    slen = buf[1]
    if len(buf) < 2 + slen:
        return b""
    return bytes(buf[2 : 2 + slen])


async def heartbeat(manager: DeviceManager) -> None:
    """Broadcast device status to all frontends every 5 seconds."""
    while True:
        await asyncio.sleep(5.0)
        for device in manager.all_devices():
            device._publish_status()


async def get_ws_user_id(ws: WebSocket) -> Optional[str]:
    """Extract user_id from JWT passed as ?token=... in the WebSocket URL."""
    ctx = await authenticate_ws(ws)
    return ctx.user_id if ctx else None


def _extract_ws_token(ws: WebSocket) -> Optional[str]:
    token = (ws.query_params.get("token") or "").strip()
    if token:
        return token
    proto = (ws.headers.get("sec-websocket-protocol") or "").strip()
    for part in proto.split(","):
        candidate = part.strip()
        if candidate.startswith("Bearer."):
            return candidate[len("Bearer.") :].strip() or None
    return None


async def authenticate_ws(ws: WebSocket):
    """Verify JWT for WebSocket handshake; returns AuthContext or None."""
    from api.auth.context import AuthContext, AuthError, decode_access_token

    token = _extract_ws_token(ws)
    if not token:
        return None
    try:
        return decode_access_token(token)
    except AuthError:
        return None


class WebSocketManager:
    """Manages frontend WebSocket connections (/ws)."""

    # Any WS message type that mutates device state. Blocked when read_only.
    WRITE_MESSAGE_TYPES: frozenset[str] = frozenset({
        "tap", "swipe", "key", "long_tap", "pinch", "double_tap", "drag",
        "tap_selector", "screen_on", "screen_off", "unlock", "swipe_ext",
        "install", "multi_action",
    })

    def __init__(
        self,
        manager: DeviceManager,
        db_enabled: bool = False,
        *,
        read_only: bool = False,
    ) -> None:
        self.manager = manager
        self._connections: Dict[str, WebSocket] = {}
        # ctrl_q: JSON status/control messages (subscribe_status)
        self._ctrl_queues: Dict[str, asyncio.Queue] = {}
        self._conn_send_locks: Dict[str, asyncio.Lock] = {}
        self._user_ids: Dict[str, Optional[str]] = {}
        self._allowed_serials: Dict[str, Optional[set[str]]] = {}
        self._conn_sender_groups: Dict[str, list[asyncio.Task]] = {}
        self._session_to_conn: Dict[str, str] = {}
        self._conn_sessions: Dict[str, Optional[str]] = {}
        self._max_devices_per_ws: int = max(1, int(os.environ.get("MAX_DEVICES_PER_WS", "3")))
        self._lock = asyncio.Lock()
        self._db_enabled = db_enabled
        # Safe-mode: reject write-type frames. BaseHTTPMiddleware can't see
        # WS frames, so the gate must live inside the receive loop.
        self._read_only = bool(read_only)
        self._multi_control = MultiControlCoordinator(manager)

    def bind_event_recorder(self, recorder) -> None:
        """Subscribe to EventRecorder to broadcast device_event messages to all frontends."""
        from runtime.core.event_recorder import EventRecorder
        if not isinstance(recorder, EventRecorder):
            return
        recorder.add_listener(self._on_device_event)

    def _on_device_event(self, event: dict) -> None:
        """Broadcast a device event to all connected frontend WebSockets."""
        msg = {"type": "device_event", **event}
        for conn_id, ctrl_q in list(self._ctrl_queues.items()):
            try:
                ctrl_q.put_nowait(msg)
            except Exception:
                pass

    async def send_to_user(self, user_id: str, msg: dict) -> None:
        """Queue one JSON message to every connected frontend for a user."""
        for conn_id, ctrl_q in list(self._ctrl_queues.items()):
            if self._db_enabled and self._user_ids.get(conn_id) != user_id:
                continue
            try:
                ctrl_q.put_nowait(msg)
            except Exception:
                pass

    async def _load_allowed_serials(
        self,
        user_id: Optional[str],
        *,
        org_id: Optional[str] = None,
    ) -> Optional[set[str]]:
        """
        Per-connection serial allowlist.
        - DB disabled: None (allow all)
        - DB enabled + no user: empty set (allow none)
        - DB enabled + user: org-scoped devices (see list_device_serials_for_user)
        """
        if not self._db_enabled:
            return None
        if not user_id:
            return set()
        try:
            async with AsyncSessionLocal() as db:
                return await list_device_serials_for_user(
                    db, user_id, org_id=org_id
                )
        except Exception as exc:
            log.warning(
                "WS allowlist load failed for user %s: %s",
                user_id,
                exc,
            )
            return set()

    async def connect(
        self,
        ws: WebSocket,
        user_id: Optional[str] = None,
        *,
        org_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        await ws.accept()
        conn_id = str(uuid.uuid4())
        # ctrl_q: JSON status/control — maxsize=16 (small msgs, generous headroom)
        ctrl_q: asyncio.Queue = asyncio.Queue(maxsize=16)
        allowed_serials = await self._load_allowed_serials(user_id, org_id=org_id)
        session_id = (ws.query_params.get("session_id") or "").strip()

        prev_ws_to_close = None
        async with self._lock:
            # Replace stale connection for the same frontend logical session.
            if session_id:
                prev_conn_id = self._session_to_conn.get(session_id)
                if prev_conn_id and prev_conn_id != conn_id:
                    prev_ws_to_close = self._connections.get(prev_conn_id)
            self._connections[conn_id] = ws
            self._ctrl_queues[conn_id] = ctrl_q
            self._user_ids[conn_id] = user_id
            self._allowed_serials[conn_id] = allowed_serials
            self._conn_sender_groups[conn_id] = []
            self._conn_send_locks[conn_id] = asyncio.Lock()
            self._conn_sessions[conn_id] = session_id
            if session_id:
                self._session_to_conn[session_id] = conn_id
        if prev_ws_to_close is not None:
            try:
                await prev_ws_to_close.close(code=4001)
            except Exception:
                pass

        if session_id:
            from auth.ws_session_registry import get_ws_session_registry

            await get_ws_session_registry().register(conn_id, session_id, ws)

        all_devs = self.manager.all_devices()
        visible_devs = all_devs
        if allowed_serials is not None:
            visible_devs = [d for d in all_devs if d.serial in allowed_serials]
        if len(visible_devs) > self._max_devices_per_ws:
            visible_devs = visible_devs[: self._max_devices_per_ws]

        # Subscribe status only; video path is latest-frame sender tasks.
        for device in visible_devs:
            device.subscribe_status(ctrl_q)

        # Send current status/logs only for visible devices.
        try:
            for device in visible_devs:
                await ws.send_json(device.status_dict())
                for line in device.get_log_lines()[-5:]:
                    await ws.send_json(
                        {"type": "log", "serial": device.serial, "line": line}
                    )
        except Exception as exc:
            log.info(
                f"WS {conn_id}: disconnected during handshake ({exc.__class__.__name__})"
            )
            await self._cleanup(conn_id, ctrl_q, visible_devs, session_id=session_id)
            return

        log.info(f"Frontend WS connected: {conn_id}")
        try:
            ws_send_lock = self._conn_send_locks[conn_id]
            async with self._lock:
                # Video senders are spawned on-demand via watch_serial/unwatch_serial.
                self._conn_sender_groups[conn_id] = []
            send_task = asyncio.create_task(self._sender_ctrl(ws, ctrl_q, ws_send_lock))
            recv_task = asyncio.create_task(self._receiver(ws))
            # Ping loop keeps TCP alive; excluded from wait so silent failures don't tear down connection.
            ping_task = asyncio.create_task(self._ws_ping_loop(ws, ws_send_lock))
            watchdog_task = asyncio.create_task(self._ws_pong_watchdog(ws, ws_send_lock))
            done, pending = await asyncio.wait(
                [send_task, recv_task], return_when=asyncio.FIRST_COMPLETED
            )
            ping_task.cancel()
            watchdog_task.cancel()
            for t in pending:
                t.cancel()
            for t in [*pending, ping_task, watchdog_task]:
                try:
                    await t
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass
        except Exception as exc:
            log.debug(f"WS {conn_id} error: {exc}")
        finally:
            await self._cleanup(conn_id, ctrl_q, self.manager.all_devices(), session_id=session_id)
            log.info(f"Frontend WS disconnected: {conn_id}")

    async def _cleanup(
        self,
        conn_id: str,
        ctrl_q: asyncio.Queue,
        devices,
        *,
        session_id: str = "",
    ) -> None:
        async with self._lock:
            sender_tasks = list(self._conn_sender_groups.get(conn_id, []))
        for task in sender_tasks:
            task.cancel()
        for task in sender_tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        for device in devices:
            device.unsubscribe_status(ctrl_q)
        from auth.ws_session_registry import get_ws_session_registry

        await get_ws_session_registry().unregister(conn_id)
        async with self._lock:
            self._connections.pop(conn_id, None)
            self._ctrl_queues.pop(conn_id, None)
            self._user_ids.pop(conn_id, None)
            self._allowed_serials.pop(conn_id, None)
            self._conn_sender_groups.pop(conn_id, None)
            self._conn_send_locks.pop(conn_id, None)
            self._conn_sessions.pop(conn_id, None)
            if session_id and self._session_to_conn.get(session_id) == conn_id:
                self._session_to_conn.pop(session_id, None)

    def subscribe_device(self, device) -> None:
        """Subscribe all active frontend connections to a newly-connected agent."""
        conn_ids = list(self._connections.keys())
        log.info(f"subscribe_device({device.serial}): {len(conn_ids)} frontend connection(s)")
        for conn_id in conn_ids:
            ctrl_q = self._ctrl_queues.get(conn_id)
            ws = self._connections.get(conn_id)
            if not ws or not ctrl_q:
                continue
            allowed_serials = self._allowed_serials.get(conn_id)
            if allowed_serials is not None and device.serial not in allowed_serials:
                continue
            device.subscribe_status(ctrl_q)
            try:
                ctrl_q.put_nowait(device.status_dict())
            except Exception:
                pass
            # Video senders are spawned on-demand via watch_serial/unwatch_serial.

    async def _sender_ctrl(
        self,
        ws: WebSocket,
        ctrl_q: asyncio.Queue,
        ws_send_lock: asyncio.Lock,
    ) -> None:
        """Send JSON control/status messages for one websocket connection."""
        while True:
            try:
                msg = await ctrl_q.get()
                async with ws_send_lock:
                    await ws.send_json(msg)
            except Exception:
                return

    async def _ws_ping_loop(
        self, ws: WebSocket, ws_send_lock: asyncio.Lock, interval: float = 30.0
    ) -> None:
        """JSON-level ping to keep TCP alive."""
        try:
            while True:
                await asyncio.sleep(interval)
                async with ws_send_lock:
                    await ws.send_json({"type": "ping", "ts": time.time()})
        except Exception:
            pass

    async def _ws_pong_watchdog(
        self,
        ws: WebSocket,
        ws_send_lock: asyncio.Lock,
        *,
        interval: float = 30.0,
        timeout: float = 60.0,
    ) -> None:
        last_pong = time.monotonic()
        ws.state.last_pong_at = last_pong  # type: ignore[attr-defined]
        try:
            while True:
                await asyncio.sleep(interval)
                seen = float(getattr(ws.state, "last_pong_at", last_pong))
                if time.monotonic() - seen > timeout:
                    async with ws_send_lock:
                        await ws.close(code=4408)
                    return
        except Exception:
            pass

    async def _device_sender(
        self,
        ws: WebSocket,
        device,
        ws_send_lock: asyncio.Lock,
    ) -> None:
        """Per-device sender for H264 binary frames on one websocket connection."""
        frame_q: asyncio.Queue = asyncio.Queue(maxsize=8)

        def _request_idr_recover(*, force: bool = False) -> None:
            recv = getattr(device, "_scrcpy_receiver", None)
            ctrl = getattr(recv, "control", None) if recv is not None else None
            if ctrl is None:
                return
            fn = getattr(ctrl, "request_idr", None) if force else (getattr(ctrl, "_request_idr_throttled", None) or getattr(ctrl, "request_idr", None))
            if fn is None:
                return
            try:
                fn()
            except Exception:
                pass

        def _frame_is_key(frame: object) -> bool:
            # Layout: [0x11][slen][serial][width:2][height:2][is_key:1]...
            if not isinstance(frame, (bytes, bytearray)) or len(frame) < 8:
                return False
            if frame[0] != 0x11:
                return False
            try:
                slen = int(frame[1])
                key_idx = 6 + slen
                return 0 <= key_idx < len(frame) and frame[key_idx] == 0x01
            except Exception:
                return False

        sent_total = 0
        dropped_total = 0
        last_stats_ts = time.monotonic()
        saw_key_sent = False
        last_force_idr_ts = time.monotonic()

        try:
            # Viewer refcount: drives DeviceClient auto-start/auto-stop.
            try:
                device.subscribe_frames(frame_q)
            except Exception:
                pass

            # Bootstrap cached config/key quickly (helps late-join).
            cfg_ref, key_ref = device.get_stream_bootstrap(max_key_age_s=60.0)
            try:
                async with ws_send_lock:
                    if cfg_ref:
                        await asyncio.wait_for(ws.send_bytes(cfg_ref), timeout=0.2)
                    if key_ref:
                        await asyncio.wait_for(ws.send_bytes(key_ref), timeout=0.2)
            except asyncio.TimeoutError:
                pass
            except Exception:
                return

            # Ensure first-frame latency: force at least one IDR.
            _request_idr_recover(force=True)

            while True:
                if not saw_key_sent and (time.monotonic() - last_force_idr_ts) >= 0.5:
                    _request_idr_recover(force=True)
                    last_force_idr_ts = time.monotonic()

                try:
                    frame = await asyncio.wait_for(frame_q.get(), timeout=1.5)
                except asyncio.TimeoutError:
                    continue

                is_key = _frame_is_key(frame)
                if is_key:
                    saw_key_sent = True

                try:
                    await asyncio.wait_for(
                        ws_send_lock.acquire(),
                        timeout=STREAM_WS_LOCK_WAIT_MS / 1000.0,
                    )
                except asyncio.TimeoutError:
                    dropped_total += 1
                    _request_idr_recover()
                    continue
                try:
                    await asyncio.wait_for(
                        ws.send_bytes(frame),
                        timeout=STREAM_WS_SEND_TIMEOUT_MS / 1000.0,
                    )
                except asyncio.TimeoutError:
                    _request_idr_recover()
                    raise
                finally:
                    ws_send_lock.release()

                sent_total += 1
                await asyncio.sleep(0)

                now = time.monotonic()
                if now - last_stats_ts >= 5.0:
                    if sent_total or dropped_total:
                        log.info(
                            "[WS device sender] serial=%s sent=%d dropped=%d",
                            getattr(device, "serial", "unknown"),
                            sent_total,
                            dropped_total,
                        )
                    sent_total = 0
                    dropped_total = 0
                    last_stats_ts = now
        finally:
            try:
                device.unsubscribe_frames(frame_q)
            except Exception:
                pass

    async def _receiver(self, ws: WebSocket) -> None:
        loop = asyncio.get_running_loop()
        conn_id: Optional[str] = None
        async with self._lock:
            for cid, conn in self._connections.items():
                if conn is ws:
                    conn_id = cid
                    break
        while True:
            try:
                data = await ws.receive_json()
            except (WebSocketDisconnect, StarletteWSDisconnect):
                break
            except RuntimeError as exc:
                # Starlette: receive_* raises this when the socket is no longer CONNECTED
                # (client gone, etc.) — not always WebSocketDisconnect. Must not `continue` spin.
                log.debug("Frontend WS receiver exit: %s", exc)
                break
            except Exception as exc:
                log.warning(f"Frontend WS receiver error (continuing): {exc}")
                await asyncio.sleep(0.05)
                continue

            msg_type = data.get("type")
            if msg_type in ("pong", "ping"):
                try:
                    ws.state.last_pong_at = time.monotonic()  # type: ignore[attr-defined]
                except Exception:
                    pass
                if msg_type == "ping":
                    try:
                        await ws.send_json({"type": "pong", "ts": time.time()})
                    except Exception:
                        break
                continue
            if msg_type == "multi_action":
                allowed_serials = (
                    self._allowed_serials.get(conn_id) if conn_id is not None else None
                )
                result = await self._multi_control.execute(
                    data,
                    allowed_serials=allowed_serials,
                    read_only=self._read_only,
                )
                try:
                    await ws.send_json(result)
                except Exception:
                    break
                continue
            serial = data.get("serial")
            if conn_id is not None:
                allowed_serials = self._allowed_serials.get(conn_id)
                if allowed_serials is not None and serial not in allowed_serials:
                    if msg_type == "watch_serial":
                        log.warning(
                            "watch_serial denied for %s (not in user allowlist, size=%d)",
                            serial,
                            len(allowed_serials),
                        )
                    continue

            # On-demand video senders (per connection + per serial).
            if msg_type in ("watch_serial", "unwatch_serial"):
                if not serial or conn_id is None:
                    continue
                if msg_type == "watch_serial":
                    device = self.manager.get_device(serial)
                    if not device:
                        log.debug("watch_serial ignored: unknown device %s", serial)
                        continue
                    async with self._lock:
                        ws_send_lock = self._conn_send_locks.get(conn_id)
                        if ws_send_lock is None:
                            continue
                        group = self._conn_sender_groups.get(conn_id, [])
                        if any(
                            getattr(t, "_device_serial", None) == serial and not t.done()
                            for t in group
                        ):
                            continue
                        task = asyncio.create_task(
                            self._device_sender(ws=ws, device=device, ws_send_lock=ws_send_lock),
                            name=f"ws-device-sender-{conn_id}-{serial}",
                        )
                        setattr(task, "_device_serial", serial)
                        group.append(task)
                        self._conn_sender_groups[conn_id] = group
                        log.info("watch_serial: started video sender for %s", serial)
                else:
                    async with self._lock:
                        group = self._conn_sender_groups.get(conn_id, [])
                        for t in list(group):
                            if getattr(t, "_device_serial", None) == serial and not t.done():
                                t.cancel()
                        self._conn_sender_groups[conn_id] = group
                continue
            device = self.manager.get_device(serial) if serial else None
            if not device:
                continue

            # Write-frame gates. BaseHTTPMiddleware can't see WS frames, so
            # every input-mutating message type is filtered here.
            #
            # 1) Global read-only mode: farm-wide observe-only deployments.
            # 2) Device-busy guard: covers both
            #    (a) dispatcher-owned tasks that flip state=BUSY
            #    (b) scenario runs started via Temporal / preview / fleet that
            #        do NOT flip state but bump `_scenario_active` via the
            #        `run_scenario_task` wrapper. Either signal means a script
            #        is driving the device and manual taps must not interleave.
            if msg_type in self.WRITE_MESSAGE_TYPES:
                if self._read_only:
                    log.debug(
                        "ws drop write frame type=%s serial=%s (read_only)",
                        msg_type, serial,
                    )
                    continue
                is_busy_state = getattr(device, "state", None) == DeviceState.BUSY
                scenario_active = int(getattr(device, "_scenario_active", 0) or 0) > 0
                if not scenario_active:
                    # Cross-process guard: Temporal workers may run in a separate process.
                    # In-memory _scenario_active is process-local, so fall back to Redis.
                    try:
                        from services import redis_store

                        if redis_store.enabled():
                            r = redis_store.client()
                            if r is not None:
                                v = await r.get(redis_store.key(f"device:{serial}:scenario_active"))
                                scenario_active = int(v or "0") > 0
                    except Exception:
                        pass
                if is_busy_state or scenario_active:
                    log.info(
                        "ws drop write frame type=%s serial=%s (busy_state=%s scenario_active=%s)",
                        msg_type, serial, is_busy_state, scenario_active,
                    )
                    reason = "busy_state" if is_busy_state else "scenario_active"
                    try:
                        await ws.send_json({
                            "type": "device_busy",
                            "serial": serial,
                            "reason": reason,
                            "scenario_active": scenario_active,
                        })
                    except Exception:
                        pass
                    continue

            # Fire-and-forget all input commands — don't await executor so the receiver
            # immediately loops back to receive_json() for the next message.
            # Commands execute in background threads; scrcpy socket lock serializes concurrent sends.
            # Exceptions in executor tasks without await are silently dropped (OK for input).

            if msg_type == "request_idr":
                # Viewer-driven keyframe request. Used on mount / reconnect /
                # tab visibility return so the browser decoder recovers in
                # ~100ms instead of waiting up to ~14s for a natural IDR.
                # Not gated by write-frame rules — this is a stream-level
                # recovery hint, not a device input mutation.
                recv = getattr(device, "_scrcpy_receiver", None)
                ctrl = getattr(recv, "control", None) if recv is not None else None
                fn = getattr(ctrl, "request_idr", None) if ctrl is not None else None
                if fn is not None:
                    try:
                        loop.run_in_executor(None, fn)
                    except Exception:
                        pass
                continue

            if msg_type == "tap":
                x, y = int(data.get("x", 0)), int(data.get("y", 0))
                log.info(
                    f"[INPUT] TAP {serial} ({x},{y}) route_hint={device.input_route_hint()} "
                    f"agent={device._agent_send is not None}"
                )
                loop.run_in_executor(None, device.tap, x, y)

            elif msg_type == "swipe":
                x1 = int(data.get("x1", 0))
                y1 = int(data.get("y1", 0))
                x2 = int(data.get("x2", 0))
                y2 = int(data.get("y2", 0))
                ms = int(data.get("ms", 300))
                log.info(
                    f"[INPUT] SWIPE {serial} ({x1},{y1})→({x2},{y2}) ms={ms} "
                    f"route_hint={device.input_route_hint()}"
                )
                loop.run_in_executor(None, device.swipe, x1, y1, x2, y2, ms)

            elif msg_type == "key":
                key = data.get("key", "home")
                log.info(f"[INPUT] KEY {serial} key={key} route_hint={device.input_route_hint()}")
                loop.run_in_executor(None, device.key, key)

            elif msg_type == "long_tap":
                x, y = int(data.get("x", 0)), int(data.get("y", 0))
                ms = int(data.get("ms", 800))
                loop.run_in_executor(None, device.long_tap, x, y, ms)

            elif msg_type == "pinch":
                cx = int(data.get("cx", 0))
                cy = int(data.get("cy", 0))
                scale = float(data.get("scale", 0.5))
                duration_ms = int(data.get("ms", 400))
                loop.run_in_executor(None, device.pinch, cx, cy, scale, duration_ms)

            elif msg_type == "double_tap":
                x, y = int(data.get("x", 0)), int(data.get("y", 0))
                log.info(f"[INPUT] DOUBLE_TAP {serial} ({x},{y})")
                loop.run_in_executor(None, device.double_tap, x, y)

            elif msg_type == "drag":
                x1 = int(data.get("x1", 0))
                y1 = int(data.get("y1", 0))
                x2 = int(data.get("x2", 0))
                y2 = int(data.get("y2", 0))
                ms = int(data.get("ms", 1000))
                log.info(f"[INPUT] DRAG {serial} ({x1},{y1})→({x2},{y2}) ms={ms}")
                loop.run_in_executor(None, device.drag, x1, y1, x2, y2, ms)

            elif msg_type == "tap_selector":
                by = data.get("by", "text")
                value = data.get("value", "")
                if value:
                    selector_route = "agent_boot_batch_flow" if device._batch_enabled() else "device_farm_u2_wrapper"
                    log.info(
                        f"[INPUT] TAP_SELECTOR {serial} {by}={value!r} route_hint={selector_route}"
                    )
                    loop.run_in_executor(None, device.tap_selector, by, value)

            elif msg_type == "screen_on":
                log.info(f"[INPUT] SCREEN_ON {serial}")
                loop.run_in_executor(None, device.screen_on)

            elif msg_type == "screen_off":
                log.info(f"[INPUT] SCREEN_OFF {serial}")
                loop.run_in_executor(None, device.screen_off)

            elif msg_type == "unlock":
                log.info(f"[INPUT] UNLOCK {serial}")
                loop.run_in_executor(None, device.unlock)

            elif msg_type == "swipe_ext":
                direction = data.get("direction", "up")
                scale = float(data.get("scale", 0.8))
                ms = int(data.get("ms", 500))
                log.info(f"[INPUT] SWIPE_EXT {serial} dir={direction} scale={scale} ms={ms}")
                loop.run_in_executor(None, device.swipe_ext, direction, scale, ms)

            elif msg_type == "install":
                apk_source = data.get("url") or data.get("apk_url", "")
                if apk_source:
                    log.info(f"[INPUT] INSTALL {serial} source={apk_source!r}")
                    loop.run_in_executor(None, device.install, apk_source)


class DeviceAgentSession:
    """
    Handles one WebSocket connection from the Android Agent APK.
    """

    def __init__(
        self,
        manager: DeviceManager,
        ws_manager: WebSocketManager,
        config: Optional[Config] = None,
    ) -> None:
        self._manager = manager
        self._ws_manager = ws_manager
        self._config = config
        self._sessions: Dict[str, WebSocket] = {}
        # Deduplicate concurrent connections for the same ?key= (pending device key / QR).
        # Without this, the agent (or OS/network) can open two sockets at once, and one
        # times out on hello → tunnel churn + black screen symptoms.
        self._active_keys: set[str] = set()
        self._lock = asyncio.Lock()

    async def handle(self, ws: WebSocket) -> None:
        import time as _time
        _connect_time = _time.monotonic()

        await ws.accept()
        client = getattr(ws, "client", None)
        if client and isinstance(client, (list, tuple)) and len(client) >= 2:
            client_addr = f"{client[0]}:{client[1]}"
        elif client and hasattr(client, "host"):
            client_addr = f"{client.host}:{client.port}"
        else:
            client_addr = str(client) if client else "unknown"
        log.info("[DEVICE-WS] Connection accepted from %s", client_addr)
        serial: Optional[str] = None
        db_session_id: Optional[str] = None
        _send = None  # set once the _send closure is created; used in finally for stale-reconnect guard
        _disconnect_reason: str = "unknown"
        _disconnect_ws_code: Optional[int] = None

        pair_id = ws.query_params.get("pair")
        key = ws.query_params.get("key")
        log.info("Agent WS: waiting for hello…")
        if key:
            async with self._lock:
                if key in self._active_keys:
                    # Key already has an active connection — this is a reconnect.
                    # Allow it (old connection will clean up in its own finally block).
                    log.info("[DEVICE-WS] Key %s… reconnecting (replacing old connection)", key[:8])
                self._active_keys.add(key)
        try:
            # ── Handshake ────────────────────────────────────────────────────
            # Reconnect races can deliver a heartbeat (e.g. pong) before hello.
            import time as _hello_time

            _hello_deadline = _hello_time.monotonic() + 15.0
            hello: Optional[dict] = None
            while True:
                _rem = _hello_deadline - _hello_time.monotonic()
                if _rem <= 0:
                    log.warning("Agent WS: hello timeout (no valid hello in 15s)")
                    await ws.close(code=4000)
                    return
                msg = await asyncio.wait_for(ws.receive_json(), timeout=_rem)
                if msg.get("type") == "hello":
                    hello = msg
                    break
                if msg.get("type") in ("pong", "ping"):
                    log.debug("Agent WS: skipping %s before hello", msg.get("type"))
                    continue
                log.warning("Agent WS: invalid hello (expected hello): %s", msg)
                await ws.close(code=4000)
                return

            msg_type = hello.get("type")
            serial = hello.get("serial") or hello.get("device_key")

            if msg_type != "hello" or not serial:
                log.warning("Agent WS: invalid hello payload: %s", hello)
                await ws.close(code=4000)
                return

            serial = str(serial)
            app_serial = serial
            # Extract device IP from WebSocket connection for ADB/scrcpy. This is
            # used only when it is a private/LAN address; public proxy addresses
            # cannot identify the Android device behind agent-boot.
            client_ip = ws.client.host if ws.client else ""
            trusted_client_ip = client_ip if _is_trusted_device_lan_ip(client_ip) else ""
            adb_serial_hint = str(hello.get("adb_serial") or "").strip()

            agent_boot_serial = ""
            if pair_id and pair_id in _pairing_mod.store:
                pair_meta = _pairing_mod.store.get(pair_id) or {}
                agent_boot_serial = str(
                    pair_meta.get("serial") or pair_meta.get("adb_serial") or ""
                ).strip()
            if not agent_boot_serial and trusted_client_ip:
                try:
                    from runtime.transports.agent_control_servicer import get_control_servicer

                    ctrl = get_control_servicer()
                    if ctrl is not None:
                        agent_boot_serial = str(ctrl.find_serial_by_ip(trusted_client_ip) or "").strip()
                except Exception as exc:
                    log.debug("agent-boot serial lookup skipped: %s", exc)
            if agent_boot_serial:
                serial = agent_boot_serial
                adb_serial_hint = agent_boot_serial
                log.info(
                    "[DEVICE-WS] mapped app serial %s to agent-boot ADB serial %s",
                    app_serial,
                    serial,
                )
            elif key and self._ws_manager._db_enabled:
                try:
                    async with AsyncSessionLocal() as db:
                        key_ref = await lookup_device_by_key(db, key)
                        if key_ref is not None and not str(key_ref.serial).startswith(
                            "pending-"
                        ):
                            serial = str(key_ref.serial)
                            adb_serial_hint = serial
                            log.info(
                                "[DEVICE-WS] mapped app serial %s to registered key serial %s",
                                app_serial,
                                serial,
                            )
                except Exception as exc:
                    log.debug("DB key serial lookup skipped: %s", exc)

            # ── Shared-secret auth (set AGENT_SECRET env var to enable) ────
            _required_secret = os.environ.get("AGENT_SECRET", "").strip()
            _env_name = os.environ.get("DEVICE_FARM_ENV", "").strip().lower()
            _strict_agent_auth = _env_name in {"prod", "production", "staging"} or (
                os.environ.get("AGENT_AUTH_REQUIRED", "").strip().lower() in {"1", "true", "yes", "on"}
            )
            _has_valid_pair = bool(pair_id and pair_id in _pairing_mod.store)
            _has_pending_key = bool(key)
            if _strict_agent_auth and not _required_secret and not (_has_valid_pair or _has_pending_key):
                log.warning(
                    "[DEVICE-WS] Agent %s from %s: rejected — strict auth requires secret or pair/key",
                    serial,
                    client_addr,
                )
                await ws.send_json(
                    {
                        "type": "error",
                        "message": "Agent auth required (set AGENT_SECRET or use pairing key).",
                    }
                )
                await ws.close(code=4003)
                return
            if _required_secret:
                _provided = (
                    hello.get("secret", "") or ws.query_params.get("secret", "")
                ).strip()
                if _provided != _required_secret:
                    log.warning(
                        "[DEVICE-WS] Agent %s from %s: rejected — invalid secret",
                        serial, client_addr,
                    )
                    await ws.send_json({
                        "type": "error",
                        "message": "Invalid agent secret. Set AGENT_SECRET on device.",
                    })
                    await ws.close(code=4003)
                    return
                log.debug("[DEVICE-WS] Agent %s: secret OK", serial)
            log.info(
                "[DEVICE-WS] Device connected: serial=%s brand=%s model=%s android=%s sdk=%s screen=%sx%s ip=%s",
                serial,
                hello.get("brand"),
                hello.get("model"),
                hello.get("android"),
                hello.get("sdk"),
                hello.get("screen_width"),
                hello.get("screen_height"),
                client_addr,
            )

            # NOTE: We allow connections without key/pair_id even when DB is enabled.
            # Phones connecting with just a ws:// URL (no key param) will be auto-registered
            # as new devices. Only reject when key= is explicitly provided but invalid.

            # ── Nếu có ?key= thì bắt buộc key phải khớp pending device; sai key → từ chối ──
            bound_device = None

            if key:
                meta = {
                    "brand": hello.get("brand", ""),
                    "model": hello.get("model", ""),
                    "android_version": hello.get("android", ""),
                    "sdk_version": int(hello.get("sdk", 0) or 0),
                    "screen_width": int(hello.get("screen_width", 0) or 0),
                    "screen_height": int(hello.get("screen_height", 0) or 0),
                }
                if adb_serial_hint:
                    meta["adb_serial"] = adb_serial_hint
                # Never store proxy/public WS source IP as adb_ip.
                if trusted_client_ip:
                    meta["adb_ip"] = trusted_client_ip
                    meta["adb_port"] = 5555
                try:
                    async with AsyncSessionLocal() as db:
                        key_ref = await lookup_device_by_key(db, key)
                        if not key_ref:
                            await ws.send_json(
                                {
                                    "type": "error",
                                    "message": "Mã QR không hợp lệ hoặc đã dùng. Đăng ký thiết bị mới và quét đúng mã QR.",
                                }
                            )
                            await ws.close(code=4001)
                            return
                        work_org = key_ref.org_id
                        if not work_org and key_ref.user_id:
                            work_org = await get_user_org_id(db, key_ref.user_id)
                        if not work_org:
                            await ws.send_json(
                                {
                                    "type": "error",
                                    "message": "Thiết bị chưa gắn tổ chức. Đăng ký lại thiết bị trên dashboard.",
                                }
                            )
                            await ws.close(code=4001)
                            return
                        if key_ref.org_id is None:
                            await ensure_device_org_id(
                                db, key_ref.device_id, work_org
                            )
                            await db.flush()
                        kw = _bind_pending_kw_only(meta)
                        with tenant_context(work_org):
                            try:
                                bound = await repo.bind_pending_device(
                                    db, key, serial, **kw
                                )
                            except TypeError as te:
                                if "unexpected keyword argument" not in str(te):
                                    raise
                                for drop in ("adb_ip", "adb_port"):
                                    kw.pop(drop, None)
                                bound = await repo.bind_pending_device(
                                    db, key, serial, **kw
                                )
                            if not bound:
                                await ws.send_json(
                                    {
                                        "type": "error",
                                        "message": "Mã QR không hợp lệ hoặc đã dùng. Đăng ký thiết bị mới và quét đúng mã QR.",
                                    }
                                )
                                await ws.close(code=4001)
                                return
                            db_sess = await repo.open_session(
                                db,
                                bound.id,
                                ws.client.host if ws.client else "",
                            )
                            bound_device = bound
                            db_session_id = db_sess.id
                        await db.commit()
                        log.info("Bound pending device key=%s… → serial=%s", key[:8], serial)
                except Exception as db_exc:
                    log.warning("Bind pending device failed: %s", db_exc)
                    await ws.send_json(
                        {"type": "error", "message": "Lỗi xác thực thiết bị."}
                    )
                    await ws.close(code=4001)
                    return

            if bound_device is None and self._ws_manager._db_enabled:
                try:
                    async with AsyncSessionLocal() as db:
                        bound_device = await repo.get_device_by_serial(db, serial)
                except Exception as _db_exc:
                    log.debug("DB lookup for adb hints skipped: %s", _db_exc)

            # ── Register device (in-memory) ─────────────────────────────────────
            is_new = self._manager.get_device(serial) is None
            device = self._manager.ensure_device(serial)
            caps = hello.get("capabilities")
            if isinstance(caps, list):
                device.set_agent_capabilities([str(c) for c in caps])
            else:
                device.set_agent_capabilities([])
            touch_mode = hello.get("touch_mode")
            if isinstance(touch_mode, str) and touch_mode:
                device.set_agent_touch_mode(touch_mode.strip())
            # Set ADB serial for legacy ADB fallback.
            # WiFi devices: use "client_ip:5555" (Build.getSerial() != ADB WiFi serial).
            # USB devices: Build.getSerial() == ADB serial so self.serial already works.
            _u2_always_tunnel = bool(
                self._config
                and getattr(self._config.device, "u2_always_tunnel", False)
            )
            _u2_relay_mapped = False
            if client_ip and client_ip not in ("127.0.0.1", "::1", "localhost"):
                resolved_serial = serial
                relay = None
                resolved_from_hint = ""
                relay_mapped = False
                # Keep a stable ADB-oriented hint even when relay is not online yet.
                # This prevents retry loops from falling back to app-generated serial.
                preferred_serial_hint = ""
                try:
                    from runtime.transports.adb_relay_server import get_relay_manager
                    relay = get_relay_manager()
                    hints: list[str] = []
                    if adb_serial_hint:
                        hints.append(adb_serial_hint)
                    if getattr(device, "_adb_serial", None):
                        hints.append(str(getattr(device, "_adb_serial")).strip())
                    if bound_device is not None:
                        _adb_serial = str(getattr(bound_device, "adb_serial", "") or "").strip()
                        _ip = str(getattr(bound_device, "adb_ip", "") or "").strip()
                        _port = int(getattr(bound_device, "adb_port", 5555) or 5555)
                        if _adb_serial:
                            hints.append(_adb_serial)
                        if _ip:
                            hints.append(f"{_ip}:{_port}")
                            hints.append(_ip)
                    if trusted_client_ip:
                        hints.append(f"{trusted_client_ip}:5555")

                    # Last fallback: phone-reported serial itself.
                    hints.append(serial)
                    deduped_hints = [h for h in dict.fromkeys(hints) if h]
                    preferred_serial_hint = deduped_hints[0] if deduped_hints else serial

                    if relay:
                        for hint in deduped_hints:
                            actual = relay.resolve_serial(hint)
                            if relay.relay_for_serial(actual):
                                resolved_serial = actual
                                resolved_from_hint = hint
                                relay_mapped = True
                                break

                        if not relay.relay_for_serial(resolved_serial):
                            resolved_serial = preferred_serial_hint
                            log.warning(
                                "[DEVICE-WS] relay serial unresolved for serial=%s client_ip=%s; "
                                "keeping preferred hint=%s",
                                serial,
                                client_ip,
                                preferred_serial_hint,
                            )
                        elif resolved_from_hint:
                            log.info(
                                "[DEVICE-WS] relay serial resolved for %s via hint=%s -> %s",
                                serial,
                                resolved_from_hint,
                                resolved_serial,
                            )
                        else:
                            relay_mapped = True
                    else:
                        resolved_serial = preferred_serial_hint
                        log.info(
                            "[DEVICE-WS] relay not ready for serial=%s; using preferred hint=%s",
                            serial,
                            preferred_serial_hint,
                        )
                except Exception as _relay_exc:
                    log.debug("relay resolve_serial skipped: %s", _relay_exc)

                device._adb_serial = resolved_serial
                _u2_relay_mapped = relay_mapped
                if relay_mapped:
                    # Relay owns u2 in cloud/Docker. WS client_ip is the TCP hop
                    # (NAT, load balancer, reverse proxy) — never the phone's LAN IP.
                    _u2_host_hint = ""
                    if relay:
                        _caps = relay.get_capabilities(resolved_serial) or {}
                        _u2_host_hint = str(_caps.get("wlan_ip") or "").strip()
                    if not _u2_host_hint and ":" in resolved_serial:
                        _u2_host_hint = resolved_serial.rsplit(":", 1)[0].strip()
                    if not _u2_host_hint:
                        _existing = str(getattr(device, "_u2_host", "") or "").strip()
                        _u2_host_hint = _existing
                    device._u2_host = _u2_host_hint or None
                elif not _u2_always_tunnel and _is_trusted_device_lan_ip(client_ip):
                    # Local LAN only: farm reaches atx-agent on device_ip:7912 directly.
                    # Never overwrite a relay-probed host (e.g. 172.16.x) with WS NAT hop.
                    _existing_u2 = str(getattr(device, "_u2_host", "") or "").strip()
                    if _existing_u2 and _existing_u2 != client_ip.strip():
                        pass
                    else:
                        device._u2_host = client_ip.strip()
                else:
                    device._u2_host = None
                # Tell relay agents to `adb connect ip:5555` only for trusted/private LAN IP.
                try:
                    if relay and trusted_client_ip:
                        asyncio.create_task(
                            relay.broadcast_adb_connect(f"{trusted_client_ip}:5555")
                        )
                except Exception as _relay_exc:
                    log.debug("relay adb_connect skipped: %s", _relay_exc)
            else:
                device._adb_serial = serial  # USB: Build.getSerial() matches ADB serial
                device._u2_host = None  # USB: no direct IP access; fall back to WS tunnel

            # STFService is not the source of truth for ADB identity. Persist
            # the serial resolved from agent-boot/control/relay when available.
            try:
                resolved_adb_serial = str(getattr(device, "_adb_serial", "") or "").strip()
                should_persist_adb_serial = bool(
                    resolved_adb_serial
                    and (
                        adb_serial_hint
                        or _u2_relay_mapped
                        or (resolved_adb_serial != serial and ":" in resolved_adb_serial)
                    )
                )
                if should_persist_adb_serial and self._ws_manager._db_enabled:
                    async with AsyncSessionLocal() as db:
                        await repo.update_device_adb_identity(
                            db,
                            serial,
                            adb_serial=resolved_adb_serial,
                            adb_ip=trusted_client_ip or None,
                            adb_port=5555 if trusted_client_ip else None,
                        )
                        await db.commit()
            except Exception as db_exc:
                log.debug("Persist adb serial skipped: %s", db_exc)

            loop = asyncio.get_running_loop()
            device.set_event_loop(loop)

            def _send(msg: Dict[str, Any]) -> None:
                if loop.is_closed():
                    log.debug("[DEVICE-WS] _send: loop closed, dropping %s", msg.get("type"))
                    return
                async def _do_send():
                    # Session guard: drop sends from stale closures after reconnect replacement.
                    cur = self._sessions.get(serial)
                    if cur is not ws:
                        return
                    try:
                        await ws.send_json(msg)
                    except Exception as _exc:
                        log.warning("[DEVICE-WS] _send failed for %s: %s", msg.get("type"), _exc)
                asyncio.run_coroutine_threadsafe(_do_send(), loop)

            # Bind relay u2 host before attach so _u2_host is set even if attach runs setup.
            if _u2_relay_mapped:
                try:
                    from runtime.transports.adb_relay_server import get_relay_manager

                    _ws_relay = get_relay_manager()
                    _ws_relay_serial = str(getattr(device, "_adb_serial", None) or serial)
                    if _ws_relay and _ws_relay.relay_for_serial(_ws_relay_serial):
                        _caps = _ws_relay.get_capabilities(_ws_relay_serial) or {}
                        _wlan = str(_caps.get("wlan_ip") or "").strip()
                        device.bind_relay_u2(
                            _ws_relay_serial,
                            host=_wlan or getattr(device, "_u2_host", None),
                        )
                except Exception as _bind_exc:
                    log.debug("[DEVICE-WS] relay u2 bind before attach skipped: %s", _bind_exc)

            tunnels = device.attach_agent_sender(_send)
            device.state = DeviceState.CONNECTING

            device.on_agent_status(
                {
                    "brand": hello.get("brand", ""),
                    "model": hello.get("model", ""),
                    "android": hello.get("android", ""),
                    "sdk": hello.get("sdk", 0),
                    "screen_width": hello.get("screen_width", 0),
                    "screen_height": hello.get("screen_height", 0),
                    "battery": hello.get("battery", -1),
                }
            )

            if is_new:
                self._ws_manager.subscribe_device(device)

            async with self._lock:
                old_ws = self._sessions.get(serial)
                if old_ws and old_ws is not ws:
                    log.info("[DEVICE-WS] Agent %s: closing stale previous WS session", serial)
                    try:
                        await old_ws.close(code=4001)
                    except Exception:
                        pass
                self._sessions[serial] = ws

            # Acknowledge — send tunnel ports + stream options (FPS for scrcpy/MediaProjection)
            # Local mode: WiFi devices use atx-agent at device_ip:7912 directly — omit u2
            # tunnel port from ack so APK won't create a ServiceTunnel that reconnects endlessly.
            # Cloud/Docker (u2_always_tunnel=True): keep u2 tunnel in ack only when
            # no relay owns the device. If relay is mapped, agent_boot_u2_proxy is used.
            tunnels_for_ack = dict(device._tunnel_ports)
            if (client_ip and client_ip not in ("127.0.0.1", "::1", "localhost")
                    and (not _u2_always_tunnel or _u2_relay_mapped)):
                tunnels_for_ack.pop("u2", None)
            hello_ack_msg: Dict[str, Any] = {
                "type": "hello_ack",
                "serial": serial,
                "tunnels": tunnels_for_ack,
            }
            if self._config:
                so = {
                    "max_fps": self._config.device.scrcpy_max_fps,
                    "max_width": self._config.device.scrcpy_max_width or 0,
                }
                # Tell agent whether to stream continuously or stop
                hello_ack_msg["stream_mode"] = self._config.streaming.mode
            else:
                so = {}
            hello_ack_msg["stream_options"] = so
            try:
                await ws.send_json(hello_ack_msg)
            except Exception as exc:
                log.warning("[DEVICE-WS] Agent %s: failed to send hello_ack (broken pipe?): %s", serial, exc)
                return

            # Request agent to auto-start uiautomator2 (no-op if already running)
            try:
                await ws.send_json({"type": "start_services", "services": ["u2"]})
            except Exception as exc:
                log.warning("[DEVICE-WS] Agent %s: failed to send start_services: %s", serial, exc)
                return

            # Hint for high-FPS capture (scrcpy / MediaProjection)
            cfg = self._config
            opts = {
                "type": "set_stream_options",
                "max_fps": cfg.device.scrcpy_max_fps if cfg else 60,
                "max_width": (cfg.device.scrcpy_max_width if cfg else 800) or 800,
            }

            await ws.send_json(opts)

            if not key:
                try:
                    async with AsyncSessionLocal() as db:
                        meta = {
                            "brand": hello.get("brand", ""),
                            "model": hello.get("model", ""),
                            "android_version": hello.get("android", ""),
                            "sdk_version": int(hello.get("sdk", 0) or 0),
                            "screen_width": int(hello.get("screen_width", 0) or 0),
                            "screen_height": int(hello.get("screen_height", 0) or 0),
                        }
                        if adb_serial_hint:
                            meta["adb_serial"] = adb_serial_hint
                        if trusted_client_ip:
                            meta["adb_ip"] = trusted_client_ip
                            meta["adb_port"] = 5555
                        db_dev = await repo.get_or_create_device(db, serial)
                        await repo.update_device_metadata(db, serial, **meta)
                        db_sess = await repo.open_session(db, db_dev.id, client_ip)
                        db_session_id = db_sess.id
                        await db.commit()
                except Exception as db_exc:
                    log.debug("DB record skipped: %s", db_exc)

            # ── Complete pairing if ?pair= was supplied ───────────────────────
            if pair_id and pair_id in _pairing_mod.store:
                p = _pairing_mod.store[pair_id]
                stored_user_id = p.get("user_id")
                db_device_key = None
                try:
                    async with AsyncSessionLocal() as db:
                        db_dev = await repo.get_device_by_serial(db, serial)
                        db_device_key = db_dev.device_key if db_dev else None
                        if stored_user_id:
                            await repo.assign_device_to_user(db, serial, stored_user_id)
                        await db.commit()
                except Exception as exc:
                    log.debug("Pairing DB update skipped: %s", exc)
                _pairing_mod.store[pair_id] = {
                    "status": "paired",
                    "user_id": stored_user_id,
                    "device": {
                        "serial": serial,
                        "brand": hello.get("brand", ""),
                        "model": hello.get("model", ""),
                        "android": hello.get("android", ""),
                        "screen_width": hello.get("screen_width", 0),
                        "screen_height": hello.get("screen_height", 0),
                        "device_key": db_device_key or "",
                    },
                }
                log.info(
                    "Pairing %s completed → serial=%s user=%s",
                    pair_id,
                    serial,
                    stored_user_id,
                )

            # ── Auto-attach scrcpy for screen streaming (if device IP available) ──
            # Stream attach must not depend on scrcpy_control.
            # scrcpy_control only toggles control channel (touch/key via scrcpy),
            # not whether video stream should start.
            if client_ip and self._config:
                _streaming = self._config.streaming
                if (
                    _streaming.mode == "continuous"
                    and getattr(_streaming, "auto_attach_scrcpy_on_connect", True)
                ):
                    allow_attach = True
                    if self._ws_manager._db_enabled:
                        try:
                            async with AsyncSessionLocal() as db:
                                allow_attach = await repo.relay_scrcpy_auto_attach_allowed(db, serial)
                        except Exception as exc:
                            log.warning(
                                "relay_scrcpy DB check failed for %s: %s",
                                serial,
                                exc,
                            )
                            allow_attach = True
                    if not allow_attach:
                        log.info(
                            "Skip auto-attach scrcpy (relay_scrcpy_enabled=false in DB): %s",
                            serial,
                        )
                        # H264 binary frames embed the DeviceClient.serial that owns the
                        # RelayScrcpyReceiver.  If relay-only slot (hardware serial) grabbed
                        # scrcpy first, frames are tagged 10AE7S… while the dashboard decodes
                        # only the agent serial (49c…).  When relay already streams for our
                        # resolved _adb_serial, re-attach here so register_scrcpy_receiver
                        # points at this agent's callbacks (correct prefix) — no second
                        # scrcpy_start (inherit path in attach_scrcpy_stream).
                        try:
                            from runtime.transports.adb_relay_server import get_relay_manager

                            _rm = get_relay_manager()
                            _adb = (getattr(device, "_adb_serial", None) or "").strip()
                            if _rm and _adb:
                                _tgt = _rm.resolve_serial(_adb)
                                if _rm.is_scrcpy_running(_tgt):
                                    loop.run_in_executor(
                                        None,
                                        device.attach_scrcpy_stream,
                                        _tgt,
                                        None,
                                        self._config.device.scrcpy_control,
                                    )
                                    log.info(
                                        "Inherited relay scrcpy for agent %s (DB relay_scrcpy off, target=%s)",
                                        serial,
                                        _tgt,
                                    )
                        except Exception as _inh_exc:
                            log.debug(
                                "scrcpy inherit-after-skip failed for %s: %s",
                                serial,
                                _inh_exc,
                            )
                    else:
                        try:
                            # Yield any relay-only device's scrcpy session for the same IP.
                            # A relay-only device (serial="ip:port") is created before the
                            # APK WS connects.  If it's running scrcpy and we start a second
                            # one, both fight for localabstract:scrcpy → rapid crash loop.
                            # _clear_scrcpy_without_stop() hands over without sending stop,
                            # so attach_scrcpy_stream below can inherit the running session.
                            for _other in self._manager.all_devices():
                                if _other.serial == serial:
                                    continue
                                _other_ip = (
                                    _other.serial.rsplit(":", 1)[0]
                                    if ":" in _other.serial
                                    else _other.serial
                                )
                                if _other_ip == client_ip and getattr(_other, "_scrcpy_active", False):
                                    log.debug(
                                        "WS device %s yielding scrcpy from relay device %s",
                                        serial, _other.serial,
                                    )
                                    _other._clear_scrcpy_without_stop()
                                    break

                            scrcpy_target = getattr(device, "_adb_serial", None) or client_ip
                            # Re-resolve target at attach time: when device-agent connects
                            # before relay registration, _adb_serial can remain a NAT/public
                            # client_ip:5555 that no relay owns. Resolve again against current
                            # relay registry; if unresolved, keep current target and do not
                            # force-bind to an unrelated relay serial.
                            try:
                                from runtime.transports.adb_relay_server import get_relay_manager

                                relay_mgr = get_relay_manager()
                                if relay_mgr:
                                    resolved = relay_mgr.resolve_serial(scrcpy_target)
                                    scrcpy_target = resolved
                                    if relay_mgr.relay_for_serial(scrcpy_target):
                                        device._adb_serial = scrcpy_target
                                    else:
                                        log.warning(
                                            "Auto-attach unresolved relay serial for %s: target=%s client_ip=%s",
                                            serial,
                                            scrcpy_target,
                                            client_ip,
                                        )
                            except Exception:
                                pass
                            loop.run_in_executor(
                                None,
                                device.attach_scrcpy_stream,
                                scrcpy_target,
                                # adb_port intentionally omitted — mDNS uses OS-assigned port,
                                # not :5555. relay manager resolves actual serial by IP.
                            )
                            log.info(
                                "Auto-attaching scrcpy stream for %s (client_ip=%s target=%s)",
                                serial, client_ip, scrcpy_target,
                            )
                        except Exception as exc:
                            log.warning("Auto-attach scrcpy failed for %s: %s", serial, exc)

            # ── Message loop ─────────────────────────────────────────────────
            log.info("Agent %s: ready, streaming…", serial)
            frame_count = 0

            async def _keepalive() -> None:
                """Send periodic ping to keep WS alive through NAT/router idle timeouts."""
                while True:
                    await asyncio.sleep(20)
                    try:
                        await ws.send_json({"type": "ping"})
                    except Exception:
                        break

            _keepalive_task = asyncio.create_task(_keepalive())
            try:
                while True:
                    raw_msg = await ws.receive()
                    # Handle disconnect
                    if raw_msg.get("type") == "websocket.disconnect":
                        break

                    # ── Binary frame from agent (H264 binary protocol, same as server→browser) ──
                    if raw_msg.get("bytes"):
                        binary = raw_msg["bytes"]
                        if len(binary) >= 2:
                            frame_type = binary[0]
                            if frame_type == 0x10:
                                # H264 config — parse and relay
                                parsed = _parse_agent_binary_frame(binary)
                                if parsed:
                                    device.on_agent_h264_config(parsed["data"], parsed["w"], parsed["h"])
                            elif frame_type == 0x11:
                                # H264 video frame — parse and relay
                                parsed = _parse_agent_binary_frame(binary)
                                if parsed:
                                    device.on_agent_h264_video(
                                        parsed["data"], parsed["is_key"], parsed["pts_us"]
                                    )
                            elif frame_type == 0x01:
                                # Binary JPEG — parse and relay
                                parsed = _parse_agent_binary_frame(binary)
                                if parsed:
                                    device.on_agent_frame_bytes(parsed["data"])
                        continue

                    # ── JSON text message ──────────────────────────────────────────
                    text = raw_msg.get("text", "")
                    if not text:
                        continue
                    try:
                        msg = json.loads(text)
                    except Exception:
                        continue
                    msg_type = msg.get("type")

                    if msg_type in ("ping", "pong"):
                        # keepalive round-trip — no action needed
                        pass

                    elif msg_type == "frame":
                        frame_count += 1
                        if frame_count == 1 or frame_count % 300 == 0:
                            log.debug("Agent %s: frame #%s", serial, frame_count)
                        jpeg_b64 = msg.get("jpeg_b64", "")
                        if jpeg_b64:
                            device.on_agent_frame_b64(jpeg_b64)

                    elif msg_type == "h264_config":
                        # Agent sends H264 SPS+PPS config as JSON+base64
                        # data_b64 can be either AVCDecoderConfigurationRecord or Annex B SPS+PPS
                        data_b64 = msg.get("data", "") or msg.get("data_b64", "")
                        if data_b64:
                            raw_config = base64.b64decode(data_b64)
                            w = int(msg.get("width", 0) or msg.get("w", 0) or device.screen_width or 0)
                            h = int(msg.get("height", 0) or msg.get("h", 0) or device.screen_height or 0)
                            # Detect if it's Annex B and convert to AVCDecoderConfigurationRecord if needed
                            from runtime.transports.h264_utils import annexb_to_avcc_record_maybe
                            avcc_record = annexb_to_avcc_record_maybe(raw_config)
                            device.on_agent_h264_config(avcc_record, w, h)
                            log.debug("Agent %s: h264_config %dx%d %d bytes", serial, w, h, len(avcc_record))

                    elif msg_type == "h264_frame":
                        # Agent sends H264 NAL unit(s) as JSON+base64
                        data_b64 = msg.get("data", "") or msg.get("data_b64", "")
                        if data_b64:
                            raw_data = base64.b64decode(data_b64)
                            is_key = bool(msg.get("key", False) or msg.get("is_key", False))
                            pts_us = int(msg.get("pts", 0) or msg.get("pts_us", 0) or 0)
                            # Convert Annex B → AVCC if needed
                            from runtime.transports.h264_utils import annexb_to_avcc_maybe
                            avcc_data = annexb_to_avcc_maybe(raw_data)
                            device.on_agent_h264_video(avcc_data, is_key, pts_us)

                    elif msg_type == "tunnel_data":
                        channel = msg.get("channel", "")
                        b64_data = msg.get("data", "")
                        if channel and b64_data:
                            device.route_tunnel_data(channel, b64_data)

                    elif msg_type == "tunnels_ready":
                        raw = msg.get("connected")
                        channels = set()
                        if isinstance(raw, list):
                            channels = {str(c).strip() for c in raw}
                        elif isinstance(raw, str):
                            s = raw.strip("[]").replace(",", " ")
                            channels = {x.strip() for x in s.split() if x.strip()}
                        device.on_agent_ready(ready_channels=channels)
                        log.info(
                            "[DEVICE-WS] Tunnels ready: serial=%s channels=%s",
                            serial,
                            channels,
                        )

                    elif msg_type == "status":
                        device.on_agent_status(msg)

                    elif msg_type == "log":
                        device.on_agent_log(msg.get("line", ""))

                    elif msg_type == "open_url_result":
                        device.on_agent_open_url_result(
                            msg.get("success", False),
                            msg.get("error", ""),
                        )

                    elif msg_type == "hierarchy":
                        # Response from dump_hierarchy WS command (AccessibilityService)
                        device.on_agent_hierarchy_response(
                            xml=msg.get("xml"),
                            error=msg.get("error"),
                        )

                    elif msg_type == "extra_data_result":
                        device.on_agent_extra_data_result(msg)

                    else:
                        log.debug("Agent %s: unknown msg type: %r", serial, msg_type)

            finally:
                _keepalive_task.cancel()

        except asyncio.TimeoutError:
            _disconnect_reason = "hello_timeout"
            _disconnect_ws_code = None
            log.warning("[DEVICE-WS] Agent %s: hello timeout (15s)", serial or "unknown")
        except (WebSocketDisconnect, StarletteWSDisconnect) as exc:
            code = getattr(exc, "code", None)
            _disconnect_reason = f"ws_closed({code})"
            _disconnect_ws_code = code
            log.info("[DEVICE-WS] Agent %s: WS closed (code=%s)", serial or "unknown", code)
        except Exception as exc:
            _disconnect_reason = f"ws_error: {type(exc).__name__}"
            _disconnect_ws_code = None
            log.warning("[DEVICE-WS] Agent %s: unhandled error: %s", serial or "unknown", exc, exc_info=True)
        finally:
            if key:
                try:
                    async with self._lock:
                        self._active_keys.discard(key)
                except Exception:
                    pass
            if serial:
                device = self._manager.get_device(serial)
                if device:
                    # Pass our _send so on_agent_disconnected() can detect when a
                    # faster reconnect has already replaced this session and skip teardown.
                    device.on_agent_disconnected(
                        sender=_send,
                        reason=_disconnect_reason,
                        ws_code=_disconnect_ws_code,
                    )
                async with self._lock:
                    self._sessions.pop(serial, None)
            if db_session_id:
                try:
                    async with AsyncSessionLocal() as db:
                        await repo.close_session(db, db_session_id)
                        await db.commit()
                except Exception:
                    pass
            duration = _time.monotonic() - _connect_time
            if duration >= 3600:
                dur_str = f"{duration / 3600:.1f}h"
            elif duration >= 60:
                dur_str = f"{duration / 60:.1f}m"
            else:
                dur_str = f"{duration:.0f}s"
            log.info(
                "[DEVICE-WS] Device disconnected: serial=%s ip=%s duration=%s",
                serial or "unknown", client_addr, dur_str,
            )
