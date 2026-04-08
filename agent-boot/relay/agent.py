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

from relay.adb           import (
    _list_serials, _adb_connect, _adb_shell,
    _restart_u2, _restart_atx, _probe_capabilities,
    _screencap, _bootstrap_device,
)
from relay.mdns          import start_mdns_discovery
from relay.device_state  import DeviceRegistry, DeviceState
from relay.device_watcher import AdbDeviceWatcher
from relay.session_manager import ScrcpySessionManager
from relay.u2_session_pool import U2SessionPool

logger = logging.getLogger("relay.agent")

_HERE = os.path.dirname(os.path.abspath(__file__))
_RELAY_ID_FILE = os.path.join(os.path.dirname(_HERE), ".relay_id")

# CMD_TYPE constants — must match adb_relay_server.py
CMD_SHELL        = 0
CMD_RESTART_U2   = 1
CMD_ADB_CONNECT  = 2
CMD_RESTART_ATX  = 3
CMD_BOOTSTRAP    = 4  # push binaries + install APKs + start atx-agent + u2
CMD_SCREENCAP    = 5  # adb exec-out screencap -p → base64 PNG
CMD_PROBE_CAPS   = 6  # _probe_capabilities() → JSON dict in output


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
    Connects outbound to device_farm server, executes ADB commands received from the server.

    Supports two transport modes:
      - "grpc"  : gRPC bidirectional stream (HTTP/2 multiplexing, recommended for ≥5 phones)
      - "ws"    : WebSocket (legacy fallback, default when RELAY_MODE not set)

    Device changes are detected in real-time by AdbDeviceWatcher (<100ms latency).
    Scrcpy sessions are managed by ScrcpySessionManager (TTL + zombie cleanup).
    """

    def __init__(
        self,
        server_url: str,
        api_key: Optional[str],
        relay_id: str,
        relay_mode: str = "ws",
    ) -> None:
        self._api_key   = api_key
        self._relay_id  = relay_id
        self._relay_mode = relay_mode.lower().strip()

        if self._relay_mode == "grpc":
            # Accept "host:port" or "grpc://host:port" → strip scheme
            addr = server_url
            for prefix in ("grpc://", "ws://", "wss://", "http://", "https://"):
                if addr.startswith(prefix):
                    addr = addr[len(prefix):]
                    break
            # Strip any path (e.g. "/relay-agent")
            addr = addr.split("/")[0]
            # If no port given, use default gRPC relay port
            if ":" not in addr:
                addr = f"{addr}:50051"
            self._grpc_addr  = addr
            self._server_url = addr  # for logging
        else:
            # WS mode: normalise URL
            if not server_url.startswith("ws://") and not server_url.startswith("wss://"):
                server_url = f"ws://{server_url}/relay-agent"
            self._server_url = server_url
            self._grpc_addr  = ""

        self._registry   = DeviceRegistry()
        self._scrcpy_mgr = ScrcpySessionManager()

        self._u2_batch_enabled = os.getenv("U2_BATCH_ENABLED", "").lower() in ("1", "true")
        self._u2_pool: Optional[U2SessionPool] = None
        self._u2_executor: Optional[Any] = None

    async def run(self) -> None:
        zc = start_mdns_discovery()
        await self._scrcpy_mgr.start()

        if self._u2_batch_enabled:
            loop = asyncio.get_running_loop()
            self._u2_pool = U2SessionPool(loop=loop)
            await self._u2_pool.start()
            from relay.u2_executor import U2Executor
            self._u2_executor = U2Executor(pool=self._u2_pool, loop=loop)
            logger.info("u2 batch/flow enabled (U2_BATCH_ENABLED=true)")

        attempt    = 0
        base_delay = 0.5

        # Brief initial delay so device_farm server has time to start
        await asyncio.sleep(3.0)

        try:
            while True:
                try:
                    if self._relay_mode == "grpc":
                        await self._connect_and_stream_grpc()
                    else:
                        await self._connect_and_stream()
                    # Clean exit (server closed stream) — reset backoff but
                    # still wait 1s before reconnecting to avoid tight loops
                    # when the server repeatedly closes streams immediately.
                    attempt = 0
                    await asyncio.sleep(1.0)
                except Exception as exc:
                    attempt += 1
                    delay = min(base_delay * (2 ** attempt), 8.0)
                    delay += delay * 0.2 * random.random()
                    logger.warning(
                        "%s stream failed (attempt %d): %s — retry in %.1fs",
                        self._relay_mode.upper(), attempt, exc, delay,
                    )
                    await asyncio.sleep(delay)
        finally:
            if self._u2_pool:
                await self._u2_pool.stop()
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
                # Keep scrcpy sessions alive across transport reconnects.
                # Transient WS/gRPC reconnects are common on unstable networks; stopping
                # all sessions here causes 2-5s black/freeze gaps on every reconnect.
                # Sessions are explicitly cleaned up on scrcpy_stop or full agent shutdown.

    async def _connect_and_stream_grpc(self) -> None:
        """gRPC mode: bidirectional stream with HTTP/2 multiplexing."""
        from relay.grpc_client import GrpcRelayClient

        send_queue: asyncio.Queue = asyncio.Queue(maxsize=8)
        loop = asyncio.get_running_loop()

        logger.info("gRPC connecting → %s (relay_id=%s)", self._grpc_addr, self._relay_id)

        client = GrpcRelayClient(
            server_addr=self._grpc_addr,
            api_key=self._api_key,
            agent_id=self._relay_id,
            send_queue=send_queue,
            loop=loop,
        )

        # ── Register ──────────────────────────────────────────────────────────
        serials = self._registry.online_serials or _list_serials()
        register_msg = json.dumps({
            "type":     "register",
            "relay_id": self._relay_id,
            "serials":  serials,
            "version":  "2.0.0",
        })
        await send_queue.put(register_msg)

        # ── Device watcher + heartbeat ────────────────────────────────────────
        watcher = AdbDeviceWatcher(
            on_device_event=lambda s, st: self._on_device_event(s, st, send_queue),
        )
        watcher_task = asyncio.create_task(watcher.run(), name="device-watcher-grpc")
        hb_task = asyncio.create_task(
            self._periodic_heartbeat(send_queue), name="relay-heartbeat-grpc"
        )

        # ── ControlMsg consumer: routes server msgs to sessions ───────────────
        async def _consume_ctrl() -> None:
            while True:
                ctrl_msg = await client.ctrl_q.get()
                if ctrl_msg is None:
                    return
                if ctrl_msg.is_json:
                    try:
                        msg = json.loads(ctrl_msg.data.decode("utf-8", errors="replace"))
                        await self._handle_server_msg(msg, send_queue, loop)
                    except Exception as exc:
                        logger.debug("gRPC JSON msg error: %s", exc)
                else:
                    # Binary scrcpy control → route to session
                    self._scrcpy_mgr.send_control(ctrl_msg.serial, ctrl_msg.data)

        ctrl_task = asyncio.create_task(_consume_ctrl(), name="grpc-ctrl-consumer")

        try:
            # client.start() blocks and reconnects internally — run it directly
            # (the outer run() loop handles top-level reconnect/backoff)
            await client._stream_once()
        finally:
            client.stop()
            watcher_task.cancel()
            hb_task.cancel()
            ctrl_task.cancel()
            await send_queue.put(None)
            # Keep scrcpy sessions alive across transport reconnects.
            # Transient WS/gRPC reconnects are common on unstable networks; stopping
            # all sessions here causes 2-5s black/freeze gaps on every reconnect.
            # Sessions are explicitly cleaned up on scrcpy_stop or full agent shutdown.

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

        if ctx.state == DeviceState.OFFLINE and self._u2_pool:
            asyncio.create_task(self._u2_pool.evict(serial))

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

        elif mtype == "u2_request":
            asyncio.create_task(self._handle_u2_request(msg, send_queue))

        elif mtype == "u2_batch":
            asyncio.create_task(self._handle_u2_batch(msg, send_queue))

        elif mtype == "u2_flow":
            asyncio.create_task(self._handle_u2_flow(msg, send_queue))

        elif mtype == "ping":
            pass  # WebSocket ping/pong handles keepalive at transport layer

    async def _handle_u2_request(self, msg: dict, send_queue: asyncio.Queue) -> None:
        """Proxy an HTTP request to atx-agent (port 7912) on behalf of device_farm."""
        msg_id       = msg.get("msg_id", "")
        serial       = msg.get("serial", "")
        method       = msg.get("method", "GET").upper()
        path         = msg.get("path", "/")
        body         = msg.get("body", "")
        content_type = msg.get("content_type", "")
        timeout      = max(1.0, float(msg.get("timeout", 30)))

        loop   = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, self._do_u2_http, serial, method, path, body, content_type, timeout
        )
        result["type"]   = "u2_result"
        result["msg_id"] = msg_id
        # Use blocking put() — control results must never be dropped.
        # Scrcpy video frames use put_nowait (lossy); control results must not.
        await send_queue.put(json.dumps(result))

    def _do_u2_http(
        self,
        serial: str,
        method: str,
        path: str,
        body: str,
        content_type: str,
        timeout: float,
    ) -> dict:
        """Blocking: call atx-agent at device_ip:7912 and return a result dict."""
        import urllib.request
        import urllib.error

        # Derive device IP from serial (format: "ip:adb_port")
        host = serial.rsplit(":", 1)[0] if ":" in serial else serial
        url  = f"http://{host}:7912{path}"

        headers: dict = {}
        data: bytes | None = None
        if body:
            data = body.encode("utf-8") if isinstance(body, str) else body
            headers["Content-Type"] = content_type or "application/json"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp_body = resp.read()
                status    = resp.status
                ct        = resp.headers.get("Content-Type", "")
            return {
                "ok":           True,
                "status":       status,
                "body":         resp_body.decode("utf-8", errors="replace"),
                "content_type": ct,
            }
        except urllib.error.HTTPError as exc:
            body_err = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
            return {
                "ok":           False,
                "status":       exc.code,
                "body":         body_err,
                "content_type": "",
            }
        except Exception as exc:
            logger.debug("u2 HTTP error %s %s: %s", method, url, exc)
            return {
                "ok":           False,
                "status":       0,
                "body":         str(exc),
                "content_type": "",
            }

    async def _handle_u2_batch(self, msg: dict, send_queue: asyncio.Queue) -> None:
        """Execute a batch of primitive u2 actions and return aggregated results."""
        if self._u2_executor is None:
            result = {"ok": False, "stopped_at": 0, "results": [],
                      "error": "u2 batch not enabled"}
        else:
            result = await self._u2_executor.run_batch(
                serial=msg.get("serial", ""),
                actions=msg.get("actions") or [],
                early_exit=bool(msg.get("early_exit", True)),
            )
        result["type"] = "u2_batch_result"
        result["id"] = msg.get("id", "")
        await send_queue.put(json.dumps(result))

    async def _handle_u2_flow(self, msg: dict, send_queue: asyncio.Queue) -> None:
        """Execute a named high-level u2 flow and return result."""
        if self._u2_executor is None:
            result: dict = {"ok": False, "value": None, "error": "u2 batch not enabled"}
        else:
            result = await self._u2_executor.execute_flow(
                serial=msg.get("serial", ""),
                flow=msg.get("flow", ""),
                params=msg.get("params") or {},
            )
        result["type"] = "u2_flow_result"
        result["id"] = msg.get("id", "")
        result["flow"] = msg.get("flow", "")
        await send_queue.put(json.dumps(result))

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
            elif cmd_type == CMD_RESTART_ATX:
                output, rc = _restart_atx(serial, timeout=timeout)
            elif cmd_type == CMD_BOOTSTRAP:
                output, rc = _bootstrap_device(serial, timeout=max(timeout, 180))
            elif cmd_type == CMD_SCREENCAP:
                output, rc = _screencap(serial, timeout=timeout)
            elif cmd_type == CMD_PROBE_CAPS:
                import json as _json
                caps = _probe_capabilities(serial)
                output, rc = _json.dumps(caps), 0
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
