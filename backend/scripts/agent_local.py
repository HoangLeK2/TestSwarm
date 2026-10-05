#!/usr/bin/env python3
"""
agent_local.py — Device Farm Agent chay TREN dien thoai Android (Termux).

Khong can ADB. Dien thoai tu ket noi WebSocket den server qua WiFi.
Dung lenh shell Android: screencap, input, getprop, dumpsys.

Protocol:
  1. Agent → Server: hello  (device metadata)
  2. Server → Agent: hello_ack  (confirms registration + WS tunnel info)
  3. Agent sets up WS tunnel bridges to minitouch / u2 / stfservice
  4. Agent → Server: tunnels_ready
  5. Agent streams frames (screencap JPEG) continuously
  6. Server → Agent: tunnel_data  (minitouch commands via relay)
  7. Agent → Server: tunnel_data  (minitouch/u2/stfservice responses)
  8. Server → Agent: tap/swipe/key  (fallback, if minitouch tunnel not ready)

Cai dat tren Termux:
    pkg update && pkg install python socat
    pip install websockets pillow

Chay:
    python agent_local.py --server ws://192.168.1.93:8081/device-agent
    python agent_local.py --server ws://192.168.1.93:8081/device-agent --fps 15 --no-tunnels
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import os
import socket as _socket
import subprocess
import sys
import threading
import time
from typing import Dict, Optional

try:
    from scripts import setup_agent as _setup
except ImportError:
    try:
        import setup_agent as _setup
    except ImportError:
        _setup = None  # type: ignore[assignment]
_SETUP_AVAILABLE = _setup is not None and hasattr(_setup, "run_setup")

try:
    import websockets
except ImportError:
    print("pip install websockets", file=sys.stderr)
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("agent_local")


# ── Shell helpers (chay tren Android shell) ────────────────────────────────────

def _run(cmd: list, timeout: int = 10) -> str:
    try:
        return subprocess.run(
            cmd, capture_output=True, timeout=timeout
        ).stdout.decode("utf-8", errors="replace").strip()
    except Exception:
        return ""


def _prop(p: str) -> str:
    return _run(["getprop", p])


def _screen_size() -> tuple:
    out = _run(["wm", "size"])
    for line in out.splitlines():
        if "size:" in line.lower() and "x" in line:
            part = line.split(":")[-1].strip()
            try:
                w, h = part.split("x")
                return int(w.strip()), int(h.strip())
            except ValueError:
                pass
    return 1080, 1920


def _battery() -> int:
    out = _run(["dumpsys", "battery"])
    for line in out.splitlines():
        if "level:" in line:
            try:
                return int(line.split(":")[-1].strip())
            except ValueError:
                pass
    return -1


def _current_app() -> str:
    out = _run(["dumpsys", "activity", "activities"], timeout=5)
    for line in out.splitlines():
        if "mResumedActivity" in line:
            for token in line.split():
                if "/" in token and "." in token:
                    return token.split("/")[0]
    return ""


def _capture_jpeg(max_width: int = 800, quality: int = 70) -> Optional[bytes]:
    """Chup man hinh bang screencap -p (PNG → JPEG, resize neu can)."""
    try:
        from PIL import Image
        import io

        result = subprocess.run(
            ["screencap", "-p"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode != 0 or not result.stdout:
            return None

        img = Image.open(io.BytesIO(result.stdout))

        if img.width > max_width:
            ratio = max_width / img.width
            new_h = int(img.height * ratio)
            img = img.resize((max_width, new_h), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return buf.getvalue()

    except Exception as e:
        log.debug(f"screencap error: {e}")
        return None


# ── Input commands (fallback khi minitouch tunnel khong co) ──────────────────

_KEYCODE_MAP = {
    "home":       "KEYCODE_HOME",
    "back":       "KEYCODE_BACK",
    "menu":       "KEYCODE_MENU",
    "power":      "KEYCODE_POWER",
    "enter":      "KEYCODE_ENTER",
    "volumeup":   "KEYCODE_VOLUME_UP",
    "volumedown": "KEYCODE_VOLUME_DOWN",
    "recent":     "KEYCODE_APP_SWITCH",
    "del":        "KEYCODE_DEL",
    "tab":        "KEYCODE_TAB",
}


def _tap(x: int, y: int) -> None:
    subprocess.run(["input", "tap", str(x), str(y)], timeout=3)


def _swipe(x1: int, y1: int, x2: int, y2: int, ms: int) -> None:
    subprocess.run(
        ["input", "swipe", str(x1), str(y1), str(x2), str(y2), str(ms)],
        timeout=5,
    )


def _long_tap(x: int, y: int, ms: int) -> None:
    subprocess.run(
        ["input", "swipe", str(x), str(y), str(x), str(y), str(ms)],
        timeout=5,
    )


def _key(k: str) -> None:
    keycode = _KEYCODE_MAP.get(k.lower())
    if not keycode:
        keycode = k if k.upper().startswith("KEYCODE_") else f"KEYCODE_{k.upper()}"
    subprocess.run(["input", "keyevent", keycode], timeout=3)


def _open_accessibility_settings() -> None:
    """Mo man hinh Accessibility Settings tren dien thoai."""
    log.info("Opening Accessibility Settings ...")
    # Thu 1: Mo thang trang Accessibility
    code, out, err = _run(["am", "start",
        "-a", "android.settings.ACCESSIBILITY_SETTINGS"], timeout=5)
    if code == 0:
        log.info("Accessibility Settings opened OK")
        return
    # Thu 2: fallback Intent
    _run(["am", "start",
        "-n", "com.android.settings/.Settings\\$AccessibilitySettingsActivity"], timeout=5)
    log.info("Accessibility Settings opened (fallback)")


def _exec_shell(cmd: str) -> None:
    """Thuc thi lenh shell tren dien thoai (dung de enable a11y qua settings put)."""
    if not cmd:
        return
    log.info(f"Shell: {cmd}")
    code, out, err = _run(cmd.split(), timeout=10)
    if out:
        log.info(f"Shell out: {out}")
    if err:
        log.warning(f"Shell err: {err}")


# ── WS Tunnel Bridge ──────────────────────────────────────────────────────────

class AgentTunnel:
    """
    One WS tunnel channel: bridges a local device service to the server via WebSocket.

    Server → Agent:  {"type": "tunnel_data", "channel": "<ch>", "data": "<b64>"}
                     → writes decoded bytes to local service socket
    Agent → Server:  reads bytes from local service → encodes base64 → sends tunnel_data
    """

    def __init__(self, channel: str) -> None:
        self.channel = channel
        self._conn: Optional[_socket.socket] = None
        self._send_ws = None  # set via set_sender()
        self.ready = False

    def set_sender(self, send_ws) -> None:
        self._send_ws = send_ws

    def connect_tcp(self, host: str, port: int, timeout: float = 5.0) -> bool:
        """Connect to a local TCP service (e.g. uiautomator2 on port 9008)."""
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            s.connect((host, port))
            s.settimeout(None)
            self._conn = s
            self.ready = True
            threading.Thread(target=self._read_loop, daemon=True,
                             name=f"tunnel-{self.channel}").start()
            return True
        except Exception as e:
            log.warning(f"Tunnel [{self.channel}] TCP {host}:{port} failed: {e}")
            try: s.close()
            except Exception: pass
            return False

    def connect_unix_abstract(self, name: str, timeout: float = 5.0) -> bool:
        """Connect to an Android abstract unix socket (e.g. minitouch, stfservice)."""
        s = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            s.connect("\0" + name)  # null prefix = abstract namespace
            s.settimeout(None)
            self._conn = s
            self.ready = True
            threading.Thread(target=self._read_loop, daemon=True,
                             name=f"tunnel-{self.channel}").start()
            return True
        except Exception as e:
            log.warning(f"Tunnel [{self.channel}] abstract:{name!r} failed: {e}")
            try: s.close()
            except Exception: pass
            return False

    def from_server(self, b64_data: str) -> None:
        """Forward data received from the server to the local service."""
        conn = self._conn
        if not conn:
            return
        try:
            conn.sendall(base64.b64decode(b64_data))
        except Exception as e:
            log.debug(f"Tunnel [{self.channel}] write error: {e}")

    def _read_loop(self) -> None:
        """Read bytes from local service, relay to server via WS."""
        conn = self._conn
        while conn and self.ready:
            try:
                data = conn.recv(8192)
                if not data:
                    break
                if self._send_ws:
                    b64 = base64.b64encode(data).decode("ascii")
                    self._send_ws({
                        "type":    "tunnel_data",
                        "channel": self.channel,
                        "data":    b64,
                    })
            except Exception:
                break
        self.ready = False
        log.info(f"Tunnel [{self.channel}] read-loop ended")

    def close(self) -> None:
        self.ready = False
        conn, self._conn = self._conn, None
        if conn:
            try: conn.close()
            except Exception: pass


# ── Service starters ──────────────────────────────────────────────────────────

# Possible minitouch binary locations (uiautomator2 APK installs here)
_MINITOUCH_PATHS = [
    "/data/data/com.github.uiautomator/files/minitouch",
    "/data/local/tmp/minitouch",
    "/data/local/minitouch",
]


def _ensure_minitouch() -> bool:
    """Try to ensure the minitouch binary is running. Returns True if it may be up."""
    # Check if already running
    if _run(["pgrep", "-f", "minitouch"]):
        log.info("minitouch already running")
        return True

    # Find binary
    for path in _MINITOUCH_PATHS:
        if os.path.exists(path):
            try:
                log.info(f"Starting minitouch from {path} ...")
                # -n minitouch: đặt tên abstract socket là "minitouch"
                # Cloud server dùng WS tunnel kết nối tới abstract:minitouch
                subprocess.Popen(
                    [path, "-n", "minitouch"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                time.sleep(0.8)
                log.info("minitouch started (socket: localabstract:minitouch)")
                return True
            except Exception as e:
                log.warning(f"minitouch start failed: {e}")
                return False

    log.warning("minitouch binary not found; touch will fall back to 'input' commands")
    return False


_U2_PORT = 9008  # am instrument only (no ATX-agent)
_U2_TEST_PKG = "com.github.uiautomator.test"
_U2_RUNNER   = "androidx.test.runner.AndroidJUnitRunner"


def _ensure_u2_server() -> int:
    """
    Đảm bảo uiautomator2-server đang chạy (am instrument, port 9008).
    Trả về 9008 nếu ok, 0 nếu thất bại. Cần cài com.github.uiautomator.test qua agent-boot.
    """
    try:
        s = _socket.create_connection(("127.0.0.1", _U2_PORT), timeout=1.5)
        s.close()
        log.info(f"uiautomator2-server đã lắng nghe trên :{_U2_PORT}")
        return _U2_PORT
    except Exception:
        pass

    log.info("Thử start uiautomator2 qua am instrument (:9008)...")
    try:
        subprocess.Popen(
            ["sh", "-c",
             f"am instrument -w {_U2_TEST_PKG}/{_U2_RUNNER} "
             "> /data/local/tmp/u2.log 2>&1"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(12):
            time.sleep(1)
            try:
                s = _socket.create_connection(("127.0.0.1", _U2_PORT), timeout=1.0)
                s.close()
                log.info("uiautomator2-server up trên :9008 (am instrument)")
                return _U2_PORT
            except Exception:
                pass
    except Exception as e:
        log.debug(f"am instrument start failed: {e}")

    log.warning("uiautomator2-server không khởi động được; u2 tunnel sẽ không hoạt động")
    return 0



class LocalAgent:
    def __init__(
        self,
        server_url: str,
        fps: int = 10,
        max_width: int = 800,
        enable_tunnels: bool = True,
        setup_result=None,
    ) -> None:
        self.server_url = server_url
        self.fps = fps
        self.max_width = max_width
        self.enable_tunnels = enable_tunnels
        self._setup_result = setup_result

        self._tunnels: Dict[str, AgentTunnel] = {}

        # Device info
        self.serial = (
            _prop("ro.serialno")
            or _prop("ro.boot.serialno")
            or "android-local"
        )
        self.brand   = _prop("ro.product.brand")
        self.model   = _prop("ro.product.model")
        self.android = _prop("ro.build.version.release")
        self.sdk     = _prop("ro.build.version.sdk")
        self.screen_w, self.screen_h = _screen_size()

        log.info(
            f"Device: {self.brand} {self.model}  "
            f"Android {self.android} (SDK {self.sdk})  "
            f"{self.screen_w}x{self.screen_h}  serial={self.serial}"
        )

    def _status_payload(self, app: str = "", bat: int = -1) -> dict:
        return {
            "type":         "status",
            "serial":       self.serial,
            "brand":        self.brand,
            "model":        self.model,
            "android":      self.android,
            "sdk":          self.sdk,
            "battery":      bat,
            "current_app":  app,
            "screen_width": self.screen_w,
            "screen_height": self.screen_h,
            "state":        "READY",
        }

    def _handle_cmd(self, msg: dict) -> None:
        """Xu ly lenh tu server (touch fallback + shell + accessibility)."""
        t = msg.get("type")
        try:
            if t == "tap":
                _tap(int(msg.get("x", 0)), int(msg.get("y", 0)))
            elif t == "swipe":
                _swipe(
                    int(msg.get("x1", 0)), int(msg.get("y1", 0)),
                    int(msg.get("x2", 0)), int(msg.get("y2", 0)),
                    int(msg.get("ms", 300)),
                )
            elif t == "long_tap":
                _long_tap(
                    int(msg.get("x", 0)), int(msg.get("y", 0)),
                    int(msg.get("ms", 800)),
                )
            elif t == "key":
                _key(msg.get("key", "home"))
            elif t == "open_accessibility_settings":
                _open_accessibility_settings()
            elif t == "shell":
                _exec_shell(msg.get("cmd", ""))
        except Exception as e:
            log.warning(f"cmd {t}: {e}")

    def _setup_tunnels(self, send_ws) -> Dict[str, AgentTunnel]:
        """
        Connect WS tunnel bridges to device services.
        Runs in a background thread (blocking I/O).
        """
        tunnels: Dict[str, AgentTunnel] = {}

        # ── minitouch ─────────────────────────────────────────────────────────
        _ensure_minitouch()
        mt = AgentTunnel("minitouch")
        mt.set_sender(send_ws)
        if mt.connect_unix_abstract("minitouch"):
            tunnels["minitouch"] = mt
            log.info("Tunnel: minitouch ✓ (abstract socket)")
        else:
            log.warning("Tunnel: minitouch ✗ (will use 'input' fallback)")

        # ── uiautomator2 HTTP (port 9008, am instrument) ───────────────────────
        u2_port = _ensure_u2_server()
        u2 = AgentTunnel("u2")
        u2.set_sender(send_ws)
        if u2_port and u2.connect_tcp("127.0.0.1", u2_port):
            tunnels["u2"] = u2
            log.info(f"Tunnel: u2 ✓ (TCP :{u2_port})")
        else:
            log.warning("Tunnel: u2 ✗")

        # ── STFService (abstract socket) ──────────────────────────────────────
        stf = AgentTunnel("stfservice")
        stf.set_sender(send_ws)
        if stf.connect_unix_abstract("stfservice"):
            tunnels["stfservice"] = stf
            log.info("Tunnel: stfservice ✓ (abstract socket)")
        else:
            log.warning("Tunnel: stfservice ✗")

        return tunnels

    def _teardown_tunnels(self) -> None:
        for t in self._tunnels.values():
            t.close()
        self._tunnels = {}

    # ── asyncio tasks ──────────────────────────────────────────────────────────

    async def _frame_sender(self, ws) -> None:
        interval = 1.0 / max(1, self.fps)
        count = 0
        last: Optional[bytes] = None
        loop = asyncio.get_event_loop()
        log.info(f"Frame sender started: target {self.fps} FPS")

        while True:
            t0 = loop.time()
            jpeg = await loop.run_in_executor(
                None, lambda: _capture_jpeg(self.max_width)
            )
            if jpeg and jpeg is not last:
                last = jpeg
                b64 = base64.b64encode(jpeg).decode("ascii")
                try:
                    await ws.send(json.dumps({"type": "frame", "jpeg_b64": b64}))
                    count += 1
                    if count == 1:
                        log.info(f"First frame sent! ({len(jpeg)} bytes JPEG)")
                    elif count % 50 == 0:
                        log.info(f"Frames sent: {count}")
                except Exception:
                    break
            elapsed = loop.time() - t0
            await asyncio.sleep(max(0.0, interval - elapsed))

    async def _status_sender(self, ws) -> None:
        loop = asyncio.get_event_loop()
        while True:
            await asyncio.sleep(5)
            try:
                bat = await loop.run_in_executor(None, _battery)
                app = await loop.run_in_executor(None, _current_app)
                await ws.send(json.dumps(self._status_payload(app, bat)))
            except Exception:
                break

    async def _receiver(self, ws) -> None:
        loop = asyncio.get_event_loop()
        async for raw in ws:
            try:
                msg = json.loads(raw)
                msg_type = msg.get("type")

                if msg_type == "tunnel_data":
                    channel  = msg.get("channel", "")
                    b64_data = msg.get("data", "")
                    if channel and b64_data:
                        tunnel = self._tunnels.get(channel)
                        if tunnel:
                            await loop.run_in_executor(
                                None, tunnel.from_server, b64_data
                            )

                elif msg_type in ("tap", "swipe", "long_tap", "key", "pinch"):
                    # Fallback: server sends WS command when minitouch tunnel is unavailable
                    await loop.run_in_executor(None, self._handle_cmd, msg)

                elif msg_type == "hello_ack":
                    pass  # already handled in handshake

                elif msg_type == "start_services":
                    # Server requests auto-start minitouch, u2 (ensure they are running)
                    services = msg.get("services") or []
                    if "minitouch" in services:
                        await loop.run_in_executor(None, _ensure_minitouch)
                    if "u2" in services:
                        u2_port = await loop.run_in_executor(None, _ensure_u2_server)
                        log.info(f"start_services u2: port={u2_port or 'unavailable'}")
                        # Reconnect the u2 AgentTunnel to the (possibly restarted) server.
                        # Without this step the old TCP connection to the dead NanoHTTPD
                        # stays in self._tunnels and the server-side _reconnect_u2() keeps
                        # getting connection errors through the stale tunnel socket.
                        if u2_port and self.enable_tunnels:
                            old = self._tunnels.pop("u2", None)
                            if old:
                                old.close()
                            new_u2 = AgentTunnel("u2")
                            new_u2.set_sender(_send_sync)
                            if new_u2.connect_tcp("127.0.0.1", u2_port):
                                self._tunnels["u2"] = new_u2
                                log.info("start_services: u2 tunnel reconnected")
                            else:
                                log.warning("start_services: u2 tunnel reconnect failed")
                        connected = list(self._tunnels.keys())
                        await ws.send(json.dumps({
                            "type": "tunnels_ready",
                            "connected": connected,
                        }))
                        log.info(f"start_services: tunnels_ready sent channels={connected}")
                    log.info(f"start_services done: {services}")

                elif msg_type == "set_stream_options":
                    # Hint for high FPS (scrcpy/MediaProjection); agent_local uses for frame rate
                    fps = msg.get("max_fps")
                    if isinstance(fps, (int, float)) and 1 <= fps <= 60:
                        self.fps = int(fps)
                        log.info(f"stream_options: max_fps={self.fps}")

                else:
                    log.debug(f"Recv: {msg_type}")

            except Exception as e:
                log.debug(f"_receiver error: {e}")

    async def _run_once(self) -> None:
        log.info(f"Connecting to {self.server_url} ...")
        async with websockets.connect(
            self.server_url,
            open_timeout=15,
            ping_interval=30,
            ping_timeout=60,
            close_timeout=5,
        ) as ws:
            loop = asyncio.get_running_loop()

            # ── 1. Send hello ────────────────────────────────────────────────
            bat = await loop.run_in_executor(None, _battery)
            await ws.send(json.dumps({
                "type":          "hello",
                "serial":        self.serial,
                "brand":         self.brand,
                "model":         self.model,
                "android":       self.android,
                "sdk":           self.sdk,
                "screen_width":  self.screen_w,
                "screen_height": self.screen_h,
                "battery":       bat,
                "capabilities":  ["u2", "stfservice", "minitouch"],
            }))
            log.info(f"hello sent (serial={self.serial})")

            # ── 2. Wait for hello_ack ────────────────────────────────────────
            ack_raw = await asyncio.wait_for(ws.recv(), timeout=15.0)
            ack = json.loads(ack_raw)
            if ack.get("type") != "hello_ack":
                raise RuntimeError(f"Expected hello_ack, got: {ack}")
            log.info(f"hello_ack received  tunnels_info={ack.get('tunnels')}")

            # ── 3. Set up WS tunnel sender ───────────────────────────────────
            _send_lock = asyncio.Lock()

            async def _send_async(msg: dict) -> None:
                async with _send_lock:
                    await ws.send(json.dumps(msg))

            def _send_sync(msg: dict) -> None:
                """Thread-safe WS sender (called from tunnel read-loop threads)."""
                if not loop.is_closed():
                    asyncio.run_coroutine_threadsafe(_send_async(msg), loop)

            # ── 4. Connect tunnels (blocking; run in thread-pool) ────────────
            if self.enable_tunnels:
                self._tunnels = await loop.run_in_executor(
                    None, lambda: self._setup_tunnels(_send_sync)
                )
            else:
                log.info("Tunnels disabled (--no-tunnels)")
                self._tunnels = {}

            # ── 5. Notify server that tunnels are ready ──────────────────────
            await ws.send(json.dumps({"type": "tunnels_ready"}))
            log.info("tunnels_ready sent")

            # ── 6. Initial status ────────────────────────────────────────────
            bat = await loop.run_in_executor(None, _battery)
            app = await loop.run_in_executor(None, _current_app)
            await ws.send(json.dumps(self._status_payload(app, bat)))
            log.info("Initial status sent — agent running")

            try:
                await asyncio.gather(
                    self._frame_sender(ws),
                    self._status_sender(ws),
                    self._receiver(ws),
                    self._service_watchdog(),
                    return_exceptions=True,
                )
            finally:
                self._teardown_tunnels()

    async def _service_watchdog(self) -> None:
        """Kiem tra va restart minitouch / u2 neu bi chet (chay song song voi frame sender)."""
        while True:
            await asyncio.sleep(30)
            if _SETUP_AVAILABLE and self._setup_result:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    lambda: _setup.ensure_services_running(self._setup_result),
                )

    async def run_async(self) -> None:
        while True:
            try:
                await self._run_once()
            except KeyboardInterrupt:
                break
            except Exception as e:
                log.warning(f"Connection error: {e}")
            self._teardown_tunnels()
            log.info("Reconnecting in 3s...")
            await asyncio.sleep(3)

    def run(self) -> None:
        try:
            asyncio.run(self.run_async())
        except KeyboardInterrupt:
            log.info("Agent stopped")


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Device Farm Agent - chay tren Android (Termux), khong can ADB"
    )
    ap.add_argument(
        "--server",
        default=os.environ.get("DEVICE_FARM_WS", "ws://192.168.1.93:8081/device-agent"),
        help="WebSocket URL cua server (mac dinh: ws://192.168.1.93:8081/device-agent)",
    )
    ap.add_argument("--fps",    type=int, default=10,  help="FPS muc tieu (mac dinh: 10)")
    ap.add_argument("--width",  type=int, default=800, help="Chieu rong toi da frame (mac dinh: 800)")
    ap.add_argument(
        "--no-tunnels",
        action="store_true",
        help="Tat WS tunnels (minitouch/u2/stfservice) — chi su dung screencap + input fallback",
    )
    ap.add_argument(
        "--auto-setup",
        action="store_true",
        help="Tu dong tai va cai minitouch, uiautomator2, STFService truoc khi ket noi",
    )
    args = ap.parse_args()

    # ── Auto setup ────────────────────────────────────────────────────────────
    setup_result = None
    if args.auto_setup:
        if _SETUP_AVAILABLE:
            log.info("Bat dau auto-setup ...")
            setup_result = _setup.run_setup(verbose=True)
        else:
            log.error("setup_agent.py khong tim thay — hay dat no cung thu muc voi agent_local.py")
            sys.exit(1)
    elif _SETUP_AVAILABLE:
        # Kiem tra nhanh trang thai (khong cai them)
        setup_result = _setup.quick_check()
        if not setup_result.u2_ready:
            log.warning("uiautomator2 server khong chay. Chay voi --auto-setup de cai tu dong.")
        if not setup_result.minitouch_ready:
            log.warning("minitouch khong chay. Touch se dung 'input' fallback.")

    LocalAgent(
        server_url=args.server,
        fps=args.fps,
        max_width=args.width,
        enable_tunnels=not args.no_tunnels,
        setup_result=setup_result,
    ).run()


if __name__ == "__main__":
    main()
