from __future__ import annotations

import asyncio
import base64
import json
import logging
import struct
import uuid
from typing import Any, Dict, Optional

from fastapi import WebSocket, WebSocketDisconnect
from jose import JWTError, jwt
from starlette.websockets import WebSocketDisconnect as StarletteWSDisconnect

from services import pairing as _pairing_mod
from core.config import Config
from core.security import jwt_algorithm, jwt_secret_key
from db import crud as repo
from db.database import AsyncSessionLocal
from runtime.core import DeviceManager, DeviceState

log = logging.getLogger(__name__)


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


async def heartbeat(manager: DeviceManager) -> None:
    """Broadcast device status to all frontends every 5 seconds."""
    while True:
        await asyncio.sleep(5.0)
        for device in manager.all_devices():
            device._publish_status()


async def get_ws_user_id(ws: WebSocket) -> Optional[str]:
    """
    Extract user_id from JWT passed as ?token=... in the WebSocket URL.
    Returns None if token is missing/invalid; WS will behave as anonymous.
    """
    token = ws.query_params.get("token")
    if not token:
        return None
    try:
        payload = jwt.decode(token, jwt_secret_key(), algorithms=[jwt_algorithm()])
        user_id: Optional[str] = payload.get("sub")
        token_type: Optional[str] = payload.get("type")
        if not user_id or token_type == "refresh":
            return None
        return str(user_id)
    except JWTError:
        return None


class WebSocketManager:
    """Manages frontend WebSocket connections (/ws)."""

    def __init__(self, manager: DeviceManager, db_enabled: bool = False) -> None:
        self.manager = manager
        self._connections: Dict[str, WebSocket] = {}
        self._queues: Dict[str, asyncio.Queue] = {}
        self._user_ids: Dict[str, Optional[str]] = {}
        self._allowed_serials: Dict[str, Optional[set[str]]] = {}
        self._lock = asyncio.Lock()
        self._db_enabled = db_enabled

    async def _load_allowed_serials(self, user_id: Optional[str]) -> Optional[set[str]]:
        """
        Per-connection serial allowlist.
        - DB disabled: None (allow all)
        - DB enabled + no user: empty set (allow none)
        - DB enabled + user: devices owned by that user
        """
        if not self._db_enabled:
            return None
        if not user_id:
            return set()
        try:
            async with AsyncSessionLocal() as db:
                devices = await repo.list_devices(db, user_id=user_id)
                return {d.serial for d in devices if d.serial}
        except Exception:
            return set()

    async def connect(self, ws: WebSocket, user_id: Optional[str] = None) -> None:
        await ws.accept()
        conn_id = str(uuid.uuid4())
        # maxsize=2: hold at most 2 frames in queue.
        # _safe_put drops the oldest when full → browser always gets latest frame.
        # Larger values add buffering latency (N × frame_interval ms).
        q: asyncio.Queue = asyncio.Queue(maxsize=2)
        allowed_serials = await self._load_allowed_serials(user_id)

        async with self._lock:
            self._connections[conn_id] = ws
            self._queues[conn_id] = q
            self._user_ids[conn_id] = user_id
            self._allowed_serials[conn_id] = allowed_serials

        all_devs = self.manager.all_devices()
        visible_devs = all_devs
        if allowed_serials is not None:
            visible_devs = [d for d in all_devs if d.serial in allowed_serials]

        # Subscribe only to devices visible to this user.
        for device in visible_devs:
            device.subscribe_frames(q)
            device.subscribe_status(q)
            # Push last frame immediately so browser shows something on open (binary format)
            # Skip for disconnected/dead devices — don't show stale preview
            frame = device.take_screenshot() if device.state in (DeviceState.READY, DeviceState.BUSY) else None
            if frame:
                serial_b = device.serial.encode()
                slen = len(serial_b)
                w = max(0, min(device.screen_width, 0xFFFF))
                h = max(0, min(device.screen_height, 0xFFFF))
                binary = bytes([0x01, slen]) + serial_b + struct.pack(">HH", w, h) + frame
                try:
                    q.put_nowait(binary)
                except Exception:
                    pass

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
            await self._cleanup(conn_id, q, visible_devs)
            return

        log.info(f"Frontend WS connected: {conn_id}")
        try:
            send_task = asyncio.create_task(self._sender(ws, q))
            recv_task = asyncio.create_task(self._receiver(ws))
            done, pending = await asyncio.wait(
                [send_task, recv_task], return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()
        except Exception as exc:
            log.debug(f"WS {conn_id} error: {exc}")
        finally:
            await self._cleanup(conn_id, q, self.manager.all_devices())
            log.info(f"Frontend WS disconnected: {conn_id}")

    async def _cleanup(self, conn_id: str, q: asyncio.Queue, devices) -> None:
        for device in devices:
            device.unsubscribe_frames(q)
            device.unsubscribe_status(q)
        async with self._lock:
            self._connections.pop(conn_id, None)
            self._queues.pop(conn_id, None)
            self._user_ids.pop(conn_id, None)
            self._allowed_serials.pop(conn_id, None)

    def subscribe_device(self, device) -> None:
        """Subscribe all active frontend connections to a newly-connected agent."""
        items = list(self._queues.items())
        log.info(f"subscribe_device({device.serial}): {len(items)} frontend connection(s)")
        for conn_id, q in items:
            allowed_serials = self._allowed_serials.get(conn_id)
            if allowed_serials is not None and device.serial not in allowed_serials:
                continue
            device.subscribe_frames(q)
            device.subscribe_status(q)
            try:
                q.put_nowait(device.status_dict())
            except Exception:
                pass

    async def _sender(self, ws: WebSocket, q: asyncio.Queue) -> None:
        while True:
            msg = await q.get()
            try:
                if isinstance(msg, (bytes, bytearray)):
                    await ws.send_bytes(msg)
                else:
                    await ws.send_json(msg)
            except Exception:
                break

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
            except Exception as exc:
                log.warning(f"Frontend WS receiver error (continuing): {exc}")
                continue

            msg_type = data.get("type")
            serial = data.get("serial")
            if conn_id is not None:
                allowed_serials = self._allowed_serials.get(conn_id)
                if allowed_serials is not None and serial not in allowed_serials:
                    continue
            device = self.manager.get_device(serial) if serial else None
            if not device:
                continue

            if msg_type == "tap":
                x, y = int(data.get("x", 0)), int(data.get("y", 0))
                log.info(
                    f"[INPUT] TAP {serial} ({x},{y}) agent={device._agent_send is not None}"
                )
                await loop.run_in_executor(None, device.tap, x, y)

            elif msg_type == "swipe":
                x1 = int(data.get("x1", 0))
                y1 = int(data.get("y1", 0))
                x2 = int(data.get("x2", 0))
                y2 = int(data.get("y2", 0))
                ms = int(data.get("ms", 300))
                adb_conn = False
                try:
                    adb_conn = bool(getattr(device, "_adb_transport", None) and device._adb_transport.connected)  # type: ignore[attr-defined]
                except Exception:
                    adb_conn = False
                log.info(
                    f"[INPUT] SWIPE {serial} ({x1},{y1})→({x2},{y2}) ms={ms} "
                    f"adb_mode={getattr(device, 'is_adb_mode', False)} adb_conn={adb_conn}"
                )
                await loop.run_in_executor(None, device.swipe, x1, y1, x2, y2, ms)

            elif msg_type == "key":
                key = data.get("key", "home")
                log.info(f"[INPUT] KEY {serial} key={key}")
                await loop.run_in_executor(None, device.key, key)

            elif msg_type == "long_tap":
                x, y = int(data.get("x", 0)), int(data.get("y", 0))
                ms = int(data.get("ms", 800))
                await loop.run_in_executor(None, device.long_tap, x, y, ms)

            elif msg_type == "pinch":
                cx = int(data.get("cx", 0))
                cy = int(data.get("cy", 0))
                scale = float(data.get("scale", 0.5))
                await loop.run_in_executor(None, device.pinch, cx, cy, scale)

            elif msg_type == "tap_selector":
                by = data.get("by", "text")
                value = data.get("value", "")
                if value:
                    log.info(f"[INPUT] TAP_SELECTOR {serial} {by}={value!r}")
                    await loop.run_in_executor(None, device.tap_selector, by, value)


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
            hello = await asyncio.wait_for(ws.receive_json(), timeout=15.0)
            msg_type = hello.get("type")
            serial = hello.get("serial") or hello.get("device_key")

            if msg_type != "hello" or not serial:
                log.warning(f"Agent WS: invalid hello: {hello}")
                await ws.close(code=4000)
                return

            serial = str(serial)
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
            # Extract device IP from WebSocket connection for ADB/scrcpy
            client_ip = ws.client.host if ws.client else ""

            if key:
                meta = {
                    "brand": hello.get("brand", ""),
                    "model": hello.get("model", ""),
                    "android_version": hello.get("android", ""),
                    "sdk_version": int(hello.get("sdk", 0) or 0),
                    "screen_width": int(hello.get("screen_width", 0) or 0),
                    "screen_height": int(hello.get("screen_height", 0) or 0),
                    "adb_ip": client_ip,
                    "adb_port": 5555,
                }
                try:
                    async with AsyncSessionLocal() as db:
                        bound = await repo.bind_pending_device(db, key, serial, **meta)
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
                            db, bound.id, ws.client.host if ws.client else ""
                        )
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

            loop = asyncio.get_running_loop()

            def _send(msg: Dict[str, Any]) -> None:
                if loop.is_closed():
                    log.debug("[DEVICE-WS] _send: loop closed, dropping %s", msg.get("type"))
                    return
                async def _do_send():
                    try:
                        await ws.send_json(msg)
                    except Exception as _exc:
                        log.warning("[DEVICE-WS] _send failed for %s: %s", msg.get("type"), _exc)
                asyncio.run_coroutine_threadsafe(_do_send(), loop)

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
            hello_ack_msg: Dict[str, Any] = {
                "type": "hello_ack",
                "serial": serial,
                "tunnels": device._tunnel_ports,
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

            # Request agent to auto-start minitouch, uiautomator2 (no-op if already running)
            try:
                await ws.send_json({"type": "start_services", "services": ["minitouch", "u2"]})
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
                            "adb_ip": client_ip,
                            "adb_port": 5555,
                        }
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
            if client_ip and self._config and self._config.device.scrcpy_control:
                try:
                    loop.run_in_executor(
                        None,
                        device.attach_scrcpy_stream,
                        client_ip,
                        5555,
                        True,  # enable_control (keys only, touch via U2)
                    )
                    log.info("Auto-attaching scrcpy stream for %s (ip=%s)", serial, client_ip)
                except Exception as exc:
                    log.warning("Auto-attach scrcpy failed for %s: %s", serial, exc)

            # ── Message loop ─────────────────────────────────────────────────
            log.info("Agent %s: ready, streaming…", serial)
            frame_count = 0
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

                if msg_type == "frame":
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

                else:
                    log.debug("Agent %s: unknown msg type: %r", serial, msg_type)

        except asyncio.TimeoutError:
            log.warning("[DEVICE-WS] Agent %s: hello timeout (15s)", serial or "unknown")
        except (WebSocketDisconnect, StarletteWSDisconnect) as exc:
            code = getattr(exc, "code", None)
            log.info("[DEVICE-WS] Agent %s: WS closed (code=%s)", serial or "unknown", code)
        except Exception as exc:
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
                    device.on_agent_disconnected(sender=_send)
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

