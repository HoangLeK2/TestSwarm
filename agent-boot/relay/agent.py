"""
relay/agent.py — RelayAgent: WebSocket bidi stream + command dispatch.

1 WebSocket connection per agent.
Reconnect: jittered exponential backoff 0.5s → 60s.

Protocol:
  Text frames  → JSON control messages (register, heartbeat, result, ack, command, ...)
  Binary frames → scrcpy video (0x53 tag) or scrcpy control (0x43 tag)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import socket
import struct
import uuid
from typing import Any, Optional

from relay.adb           import _list_serials, _adb_connect, _adb_shell, _restart_u2, _probe_capabilities
from relay.mdns          import start_mdns_discovery
from relay.device_state  import DeviceRegistry, DeviceState
from relay.device_watcher import AdbDeviceWatcher
from relay.session_manager import ScrcpySessionManager

logger = logging.getLogger("relay.agent")

_HERE = os.path.dirname(os.path.abspath(__file__))
_RELAY_ID_FILE = os.path.join(os.path.dirname(_HERE), ".relay_id")

# CMD_TYPE constants — must match adb_relay_server.py
CMD_SHELL       = 0
CMD_RESTART_U2  = 1
CMD_ADB_CONNECT = 2


def _load_or_create_relay_id() -> str:
    if os.path.exists(_RELAY_ID_FILE):
        rid = open(_RELAY_ID_FILE).read().strip()
        if rid:
            return rid
    rid = f"{socket.gethostname()}-{uuid.uuid4().hex[:6]}"
    with open(_RELAY_ID_FILE, "w") as f:
        f.write(rid)
    return rid


class RelayAgent:
    """
    Connects outbound to device_farm WebSocket server (/relay-agent),
    executes ADB commands received from the server.

    Device changes are detected in real-time by AdbDeviceWatcher (<100ms latency).
    Scrcpy sessions are managed by ScrcpySessionManager (TTL + zombie cleanup).
    """

    def __init__(self, server_url: str, api_key: Optional[str], relay_id: str) -> None:
        # Normalise URL: accept "host:port" (legacy gRPC format) or full WS URL
        if not server_url.startswith("ws://") and not server_url.startswith("wss://"):
            # Legacy "host:port" → convert to ws://host:port/relay-agent
            server_url = f"ws://{server_url}/relay-agent"
        self._server_url = server_url
        self._api_key    = api_key
        self._relay_id   = relay_id
        self._registry   = DeviceRegistry()
        self._scrcpy_mgr = ScrcpySessionManager()

    async def run(self) -> None:
        zc = start_mdns_discovery()
        await self._scrcpy_mgr.start()
        attempt    = 0
        base_delay = 0.5

        # Brief initial delay so device_farm server has time to start
        await asyncio.sleep(3.0)

        try:
            while True:
                try:
                    await self._connect_and_stream()
                    attempt = 0
                except Exception as exc:
                    attempt += 1
                    delay = min(base_delay * (2 ** attempt), 8.0)
                    delay += delay * 0.2 * random.random()
                    logger.warning(
                        "WS stream failed (attempt %d): %s — retry in %.1fs", attempt, exc, delay
                    )
                    await asyncio.sleep(delay)
        finally:
            await self._scrcpy_mgr.stop()
            if zc:
                zc.close()

    async def _connect_and_stream(self) -> None:
        import websockets  # type: ignore

        headers: dict = {}
        if self._api_key:
            headers["x-relay-api-key"] = self._api_key

        # send_queue: str for JSON text frames, bytes for binary frames
        # maxsize=8: larger buffer absorbs IDR burst (1 large keyframe ~30-80KB)
        # without dropping the following P-frames. Drains instantly on LAN.
        # P-frames are dropped when full (decoder resyncs on next IDR).
        send_queue: asyncio.Queue = asyncio.Queue(maxsize=8)
        loop = asyncio.get_running_loop()

        async with websockets.connect(
            self._server_url,
            additional_headers=headers,
            ping_interval=30,
            ping_timeout=10,
            max_size=16 * 1024 * 1024,  # 16 MB — large scrcpy frames
        ) as ws:
            logger.info("WS connected → %s (relay_id=%s)", self._server_url, self._relay_id)

            # ── Register ──────────────────────────────────────────────────────
            serials = self._registry.online_serials or _list_serials()
            await ws.send(json.dumps({
                "type":     "register",
                "relay_id": self._relay_id,
                "serials":  serials,
                "version":  "2.0.0",
            }))
            logger.info("register sent: relay_id=%s serials=%s", self._relay_id, serials)

            # ── Device watcher + heartbeat ────────────────────────────────────
            watcher = AdbDeviceWatcher(
                on_device_event=lambda s, st: self._on_device_event(s, st, send_queue),
            )
            watcher_task = asyncio.create_task(watcher.run(), name="device-watcher")
            hb_task = asyncio.create_task(
                self._periodic_heartbeat(send_queue), name="relay-heartbeat"
            )

            # ── Sender task: drain send_queue → WS ───────────────────────────
            async def _sender() -> None:
                try:
                    while True:
                        item = await send_queue.get()
                        if item is None:
                            return
                        if isinstance(item, bytes):
                            await ws.send(item)
                        else:
                            await ws.send(item)
                except Exception as exc:
                    logger.debug("WS sender exited: %s", exc)

            sender_task = asyncio.create_task(_sender(), name="ws-sender")

            try:
                async for raw_msg in ws:
                    if isinstance(raw_msg, bytes):
                        await self._handle_binary(raw_msg, send_queue)
                    else:
                        try:
                            msg = json.loads(raw_msg)
                        except Exception:
                            continue
                        await self._handle_server_msg(msg, send_queue, loop)
            finally:
                watcher_task.cancel()
                hb_task.cancel()
                sender_task.cancel()
                await send_queue.put(None)
                await self._scrcpy_mgr.stop_all_sessions()

    async def _handle_binary(self, data: bytes, send_queue: asyncio.Queue) -> None:
        """Handle binary frame from server (currently: scrcpy control 0x43)."""
        if len(data) < 2:
            return
        tag = data[0]
        if tag == 0x43:
            # Scrcpy control: [0x43][slen][serial][ctrl_data]
            slen = data[1]
            if len(data) < 2 + slen:
                return
            serial = data[2:2 + slen].decode("utf-8", errors="replace")
            ctrl_data = data[2 + slen:]
            self._scrcpy_mgr.send_control(serial, ctrl_data)

    # ── Device event handling ─────────────────────────────────────────────────

    async def _on_device_event(
        self, serial: str, adb_state: str, send_queue: asyncio.Queue
    ) -> None:
        ctx, changed = self._registry.on_adb_event(serial, adb_state)
        if not changed:
            return

        logger.info("device %s → %s (retries=%d)", serial, ctx.state.value, ctx.retry_count)

        if ctx.state == DeviceState.ONLINE and not ctx.capabilities:
            loop = asyncio.get_running_loop()
            caps = await loop.run_in_executor(None, _probe_capabilities, serial)
            self._registry.set_capabilities(serial, caps)
            logger.info("capabilities %s: %s", serial, caps)

        if ctx.state == DeviceState.RECONNECTING and ":" in serial:
            loop = asyncio.get_running_loop()
            output, rc = await loop.run_in_executor(None, _adb_connect, serial)
            if rc == 0:
                logger.info("auto-reconnected %s — %s", serial, output)
            else:
                logger.debug("reconnect failed %s — %s", serial, output)

        await self._send_heartbeat(send_queue)

    async def _periodic_heartbeat(self, send_queue: asyncio.Queue) -> None:
        """Keepalive heartbeat every 30s."""
        while True:
            await asyncio.sleep(30)
            await self._send_heartbeat(send_queue)

    async def _send_heartbeat(self, send_queue: asyncio.Queue) -> None:
        serials = self._registry.online_serials
        caps_list = []
        for s in serials:
            ctx = self._registry.get(s)
            if ctx and ctx.capabilities:
                c = ctx.capabilities
                caps_list.append({
                    "serial":          s,
                    "android_version": c.get("android_version", ""),
                    "sdk":             c.get("sdk", ""),
                    "brand":           c.get("brand", ""),
                    "model":           c.get("model", ""),
                    "abi":             c.get("abi", ""),
                    "screen_width":    c.get("screen_width", 0),
                    "screen_height":   c.get("screen_height", 0),
                    "ram_gb":          c.get("ram_gb", 0),
                    "has_u2":          bool(c.get("u2", False)),
                    "has_stf":         bool(c.get("stf", False)),
                    "tags":            list(c.get("tags", [])),
                })

        try:
            send_queue.put_nowait(json.dumps({
                "type":         "heartbeat",
                "serials":      serials,
                "capabilities": caps_list,
            }))
        except asyncio.QueueFull:
            pass

    # ── Server message handling ───────────────────────────────────────────────

    async def _handle_server_msg(
        self, msg: dict, send_queue: asyncio.Queue, loop: asyncio.AbstractEventLoop
    ) -> None:
        mtype = msg.get("type", "")

        if mtype == "ack":
            logger.info("registered: %s", msg.get("message"))

        elif mtype == "command":
            result = await loop.run_in_executor(
                None,
                self._execute_command,
                msg.get("msg_id", ""),
                msg.get("serial", ""),
                msg.get("cmd", ""),
                int(msg.get("timeout", 30)),
                int(msg.get("cmd_type", CMD_SHELL)),
            )
            try:
                send_queue.put_nowait(result)
            except asyncio.QueueFull:
                pass

        elif mtype == "scrcpy_start":
            await self._scrcpy_mgr.start_session(
                serial         = msg.get("serial", ""),
                max_fps        = int(msg.get("max_fps") or 30),
                max_width      = int(msg.get("max_width") or 800),
                enable_control = bool(msg.get("control", True)),
                port           = int(msg.get("port") or 27183),
                send_queue     = send_queue,
                loop           = loop,
                bitrate        = int(msg.get("bitrate") or 2_000_000),
                low_latency    = bool(msg.get("low_latency", False)),
            )

        elif mtype == "scrcpy_stop":
            await self._scrcpy_mgr.stop_session(msg.get("serial", ""))

        elif mtype == "ping":
            pass  # WebSocket ping/pong handles keepalive at transport layer

    def _execute_command(
        self,
        msg_id: str,
        serial: str,
        cmd: str,
        timeout: int,
        cmd_type: int,
    ) -> str:
        """Run ADB command and return JSON result string."""
        if cmd_type != CMD_ADB_CONNECT:
            ctx = self._registry.get(serial)
            if ctx is None or not ctx.is_available:
                state_str = ctx.state.value if ctx else "unknown"
                return json.dumps({
                    "type":      "result",
                    "msg_id":    msg_id,
                    "ok":        False,
                    "exit_code": -1,
                    "output":    "",
                    "error":     f"serial {serial!r} not available (state={state_str})",
                })

        try:
            if cmd_type == CMD_ADB_CONNECT:
                output, rc = _adb_connect(serial, timeout=timeout)
            elif cmd_type == CMD_RESTART_U2:
                output, rc = _restart_u2(serial, timeout=timeout)
            else:
                output, rc = _adb_shell(serial, cmd, timeout=timeout)

            return json.dumps({
                "type":      "result",
                "msg_id":    msg_id,
                "ok":        rc == 0,
                "exit_code": rc,
                "output":    output,
                "error":     "" if rc == 0 else output,
            })
        except Exception as exc:
            return json.dumps({
                "type":      "result",
                "msg_id":    msg_id,
                "ok":        False,
                "exit_code": -1,
                "output":    "",
                "error":     str(exc),
            })
