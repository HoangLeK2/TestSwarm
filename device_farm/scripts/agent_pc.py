#!/usr/bin/env python3
"""
agent.py — Device Farm Agent (PC-side, ADB-connected).

Chay tren may tinh co ADB ket noi Android device.
Dung ScrcpyReceiver de chup man hinh cao FPS, gui frame qua WebSocket.
Su dung WS tunnel de relay minitouch / uiautomator2 / STFService (khong can ADB forward thu cong).

Protocol:
  1. Agent → Server: hello  (device metadata)
  2. Server → Agent: hello_ack  {"tunnels": {"minitouch": PORT, "u2": PORT, "stfservice": PORT}}
  3. Agent sets up ADB-forward TCP bridges for each tunnel channel
  4. Agent → Server: tunnels_ready
  5. Agent streams frames continuously
  6. Server → Agent: tunnel_data  (minitouch/u2/stfservice data from server tools)
  7. Agent → Server: tunnel_data  (responses from device services)
  8. Server → Agent: tap/swipe/key  (WS fallback if minitouch tunnel unavailable)

Usage:
    python agent.py                  # shim at repo root
    python scripts/agent_pc.py
    python agent.py --serial 192.168.1.10:5555
    python agent.py --server ws://192.168.1.93:8081/device-agent --fps 30
    python agent.py --no-tunnels   # disable WS tunnels, use u2 for touch
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
from pathlib import Path
from typing import Dict, Optional

_root = Path(__file__).resolve().parent
_repo = _root.parent if _root.name == "scripts" else _root
sys.path.insert(0, str(_repo))

try:
    import websockets
except ImportError:
    print("pip install websockets", file=sys.stderr)
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("agent")


# ── ADB helpers ───────────────────────────────────────────────────────────────

def _run(cmd: list, timeout: int = 10) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception:
        return ""


def _adb_devices(adb: str = "adb") -> list:
    out = _run([adb, "devices"])
    return [
        line.split()[0] for line in out.splitlines()[1:]
        if line.strip() and len(line.split()) >= 2 and line.split()[1] == "device"
    ]


def _prop(adb: str, serial: str, p: str) -> str:
    return _run([adb, "-s", serial, "shell", "getprop", p])


def _screen_size(adb: str, serial: str) -> tuple:
    out = _run([adb, "-s", serial, "shell", "wm", "size"])
    for line in out.splitlines():
        if "size:" in line.lower() and "x" in line:
            part = line.split(":")[-1].strip()
            try:
                w, h = part.split("x")
                return int(w), int(h)
            except ValueError:
                pass
    return 1080, 1920


def _battery(adb: str, serial: str) -> int:
    out = _run([adb, "-s", serial, "shell", "dumpsys", "battery"])
    for line in out.splitlines():
        if "level:" in line:
            try:
                return int(line.split(":")[-1].strip())
            except ValueError:
                pass
    return -1


def _current_app(adb: str, serial: str) -> str:
    out = _run([adb, "-s", serial, "shell", "dumpsys", "activity", "activities"], timeout=5)
    for line in out.splitlines():
        if "mResumedActivity" in line:
            for token in line.split():
                if "/" in token and "." in token:
                    return token.split("/")[0]
    return ""


# ── WS Tunnel Bridge (PC-side via ADB port-forward) ──────────────────────────

class AgentTunnel:
    """
    One WS tunnel channel (PC-side).

    Server sends data via WS → we write to the ADB-forwarded local TCP port.
    We read responses from that local TCP port → relay back to server via WS.

    The ADB forward maps  localhost:LOCAL_PORT  →  localabstract:SERVICE  on device.
    """

    def __init__(self, channel: str) -> None:
        self.channel  = channel
        self._conn: Optional[_socket.socket] = None
        self._send_ws = None
        self.ready    = False

    def set_sender(self, send_ws) -> None:
        self._send_ws = send_ws

    def connect_tcp(self, host: str, port: int, timeout: float = 5.0) -> bool:
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

    def from_server(self, b64_data: str) -> None:
        conn = self._conn
        if not conn:
            return
        try:
            conn.sendall(base64.b64decode(b64_data))
        except Exception as e:
            log.debug(f"Tunnel [{self.channel}] write error: {e}")

    def _read_loop(self) -> None:
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


# ── ADB port-forward helpers ──────────────────────────────────────────────────

_ADB_FORWARD_MAP = {
    # channel → (local_port_attr, device_abstract_socket)
    "minitouch":  ("_mt_port",  "minitouch"),
    "stfservice": ("_stf_port", "stfservice"),
}

# u2 maps to device TCP port 9008 (am instrument, no ATX-agent)
_U2_DEVICE_PORT = 9008


def _adb_forward(adb: str, serial: str, local_port: int, remote: str) -> bool:
    """adb -s SERIAL forward tcp:LOCAL_PORT localabstract:REMOTE"""
    r = subprocess.run(
        [adb, "-s", serial, "forward", f"tcp:{local_port}", f"localabstract:{remote}"],
        capture_output=True, timeout=10,
    )
    return r.returncode == 0


def _adb_forward_tcp(adb: str, serial: str, local_port: int, remote_port: int) -> bool:
    """adb -s SERIAL forward tcp:LOCAL_PORT tcp:REMOTE_PORT"""
    r = subprocess.run(
        [adb, "-s", serial, "forward", f"tcp:{local_port}", f"tcp:{remote_port}"],
        capture_output=True, timeout=10,
    )
    return r.returncode == 0


def _adb_remove_forward(adb: str, serial: str, local_port: int) -> None:
    subprocess.run(
        [adb, "-s", serial, "forward", "--remove", f"tcp:{local_port}"],
        capture_output=True, timeout=5,
    )


def _find_free_port() -> int:
    with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── Screen capture backends ───────────────────────────────────────────────────

class ScrcpyBackend:
    def __init__(self, serial: str, adb: str, jar: str,
                 fps: int = 30, max_width: int = 800) -> None:
        from runtime.transports.scrcpy_receiver import ScrcpyReceiver
        self._serial = serial
        self._adb = adb
        self._port = 27183
        self._r = ScrcpyReceiver(
            serial=serial, adb_path=adb, port=self._port,
            server_jar=jar, max_fps=fps, max_width=max_width,
        )
        self.device_width = 0
        self.device_height = 0

    def start(self) -> None:
        subprocess.run(
            [self._adb, "-s", self._serial, "forward",
             f"tcp:{self._port}", "localabstract:scrcpy"],
            capture_output=True, timeout=10
        )
        self._r.start_receiver()
        log.info("ScrcpyReceiver started, waiting for first frame (up to 12s)...")
        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline:
            if self._r.get_latest_frame() is not None:
                self.device_width  = getattr(self._r, "device_width", 0)
                self.device_height = getattr(self._r, "device_height", 0)
                log.info(f"scrcpy ready: {self.device_width}x{self.device_height}")
                return
            time.sleep(0.2)
        raise RuntimeError("scrcpy: no frame within 12s")

    def get_jpeg(self) -> Optional[bytes]:
        return self._r.get_latest_frame()

    def stop(self) -> None:
        self._r.stop_receiver()
        subprocess.run(
            [self._adb, "-s", self._serial, "forward", "--remove", f"tcp:{self._port}"],
            capture_output=True, timeout=5
        )


class U2Backend:
    def __init__(self, serial: str) -> None:
        import uiautomator2 as u2
        log.info(f"u2.connect({serial})...")
        self._d = u2.connect(serial)
        log.info("u2 connected")
        self.device_width = 0
        self.device_height = 0

    def start(self) -> None:
        pass

    def get_jpeg(self) -> Optional[bytes]:
        import io
        try:
            img = self._d.screenshot(format="pillow")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=65)
            return buf.getvalue()
        except Exception as e:
            log.debug(f"u2 screenshot: {e}")
            return None

    def stop(self) -> None:
        pass

    def tap(self, x: int, y: int) -> None:
        self._d.click(x, y)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int) -> None:
        self._d.swipe(x1, y1, x2, y2, duration=ms / 1000)

    def key(self, k: str) -> None:
        self._d.press(k)

    def app(self) -> str:
        try:
            return self._d.app_current().get("package", "")
        except Exception:
            return ""


# ── Agent ─────────────────────────────────────────────────────────────────────

class DeviceAgent:
    def __init__(
        self,
        serial: str,
        server_url: str,
        scrcpy_jar: str,
        fps: int = 30,
        max_width: int = 800,
        adb: str = "adb",
        use_u2: bool = False,
        enable_tunnels: bool = True,
    ) -> None:
        self.serial     = serial
        self.server_url = server_url
        self.fps        = fps
        self.adb        = adb
        self.enable_tunnels = enable_tunnels

        # Metadata
        self.brand   = _prop(adb, serial, "ro.product.brand")
        self.model   = _prop(adb, serial, "ro.product.model")
        self.android = _prop(adb, serial, "ro.build.version.release")
        self.sdk     = _prop(adb, serial, "ro.build.version.sdk")
        self.screen_w, self.screen_h = _screen_size(adb, serial)
        log.info(f"Device: {self.brand} {self.model}  Android {self.android}  {self.screen_w}x{self.screen_h}")

        # Screen backend
        self._screen: Optional[ScrcpyBackend | U2Backend] = None
        self._u2: Optional[U2Backend] = None

        if use_u2:
            b = U2Backend(serial)
            b.start()
            self._screen = b
            self._u2 = b
        else:
            try:
                b = ScrcpyBackend(serial, adb, scrcpy_jar, fps, max_width)
                b.start()
                self._screen = b
                if b.device_width > 0:
                    self.screen_w, self.screen_h = b.device_width, b.device_height
                try:
                    self._u2 = U2Backend(serial)
                except Exception as e:
                    log.warning(f"u2 for input unavailable: {e}")
            except Exception as e:
                log.warning(f"scrcpy failed ({e}), using u2")
                b2 = U2Backend(serial)
                b2.start()
                self._screen = b2
                self._u2 = b2

        # Tunnel state
        self._tunnels: Dict[str, AgentTunnel] = {}
        self._forward_ports: Dict[str, int] = {}  # channel → local port

    def _status_payload(self, app: str = "", bat: int = -1) -> dict:
        return {
            "type":          "status",
            "serial":        self.serial,
            "brand":         self.brand,
            "model":         self.model,
            "android":       self.android,
            "sdk":           self.sdk,
            "battery":       bat,
            "current_app":   app,
            "screen_width":  self.screen_w,
            "screen_height": self.screen_h,
            "state":         "READY",
        }

    def _handle_cmd(self, msg: dict) -> None:
        """Fallback WS touch command (used when minitouch tunnel unavailable)."""
        t = msg.get("type")
        if not self._u2:
            return
        try:
            if t == "tap":
                self._u2.tap(int(msg.get("x", 0)), int(msg.get("y", 0)))
            elif t == "swipe":
                self._u2.swipe(
                    int(msg.get("x1", 0)), int(msg.get("y1", 0)),
                    int(msg.get("x2", 0)), int(msg.get("y2", 0)),
                    int(msg.get("ms", 300))
                )
            elif t == "key":
                self._u2.key(msg.get("key", "home"))
        except Exception as e:
            log.warning(f"cmd {t}: {e}")

    def _setup_tunnels(self, send_ws) -> Dict[str, AgentTunnel]:
        """
        Set up ADB port-forwards and connect WS tunnel bridges.
        Called in a thread-pool executor (blocking).
        """
        tunnels: Dict[str, AgentTunnel] = {}
        adb, serial = self.adb, self.serial

        # ── minitouch ─────────────────────────────────────────────────────────
        mt_port = _find_free_port()
        if _adb_forward(adb, serial, mt_port, "minitouch"):
            self._forward_ports["minitouch"] = mt_port
            time.sleep(0.3)
            mt = AgentTunnel("minitouch")
            mt.set_sender(send_ws)
            if mt.connect_tcp("127.0.0.1", mt_port):
                tunnels["minitouch"] = mt
                log.info(f"Tunnel: minitouch ✓ (adb fwd :{mt_port} → abstract:minitouch)")
            else:
                _adb_remove_forward(adb, serial, mt_port)
        else:
            log.warning("Tunnel: minitouch ✗ (adb forward failed)")

        # ── uiautomator2 HTTP ─────────────────────────────────────────────────
        u2_port = _find_free_port()
        if _adb_forward_tcp(adb, serial, u2_port, _U2_DEVICE_PORT):
            self._forward_ports["u2"] = u2_port
            time.sleep(0.3)
            u2t = AgentTunnel("u2")
            u2t.set_sender(send_ws)
            if u2t.connect_tcp("127.0.0.1", u2_port):
                tunnels["u2"] = u2t
                log.info(f"Tunnel: u2 ✓ (adb fwd :{u2_port} → tcp:{_U2_DEVICE_PORT})")
            else:
                _adb_remove_forward(adb, serial, u2_port)
        else:
            log.warning("Tunnel: u2 ✗ (adb forward failed)")

        # ── STFService ────────────────────────────────────────────────────────
        stf_port = _find_free_port()
        if _adb_forward(adb, serial, stf_port, "stfservice"):
            self._forward_ports["stfservice"] = stf_port
            time.sleep(0.3)
            stf = AgentTunnel("stfservice")
            stf.set_sender(send_ws)
            if stf.connect_tcp("127.0.0.1", stf_port):
                tunnels["stfservice"] = stf
                log.info(f"Tunnel: stfservice ✓ (adb fwd :{stf_port} → abstract:stfservice)")
            else:
                _adb_remove_forward(adb, serial, stf_port)
        else:
            log.warning("Tunnel: stfservice ✗ (adb forward failed)")

        return tunnels

    def _teardown_tunnels(self) -> None:
        for t in self._tunnels.values():
            t.close()
        self._tunnels = {}
        for ch, port in self._forward_ports.items():
            _adb_remove_forward(self.adb, self.serial, port)
            log.debug(f"Removed adb forward :{port} ({ch})")
        self._forward_ports = {}

    # ── asyncio tasks ──────────────────────────────────────────────────────────

    async def _frame_sender(self, ws) -> None:
        interval = 1.0 / max(1, self.fps)
        count = 0
        last: Optional[bytes] = None
        log.info(f"Frame sender: {self.fps} FPS target")
        while True:
            t0 = asyncio.get_event_loop().time()
            jpeg = self._screen.get_jpeg() if self._screen else None
            if jpeg and jpeg is not last:
                last = jpeg
                b64 = base64.b64encode(jpeg).decode("ascii")
                try:
                    await ws.send(json.dumps({"type": "frame", "jpeg_b64": b64}))
                    count += 1
                    if count == 1:
                        log.info(f"First frame sent! ({len(b64)} chars)")
                    elif count % 100 == 0:
                        log.info(f"Frames sent: {count}")
                except Exception:
                    break
            elapsed = asyncio.get_event_loop().time() - t0
            await asyncio.sleep(max(0.0, interval - elapsed))

    async def _status_sender(self, ws) -> None:
        while True:
            await asyncio.sleep(5)
            try:
                bat = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: _battery(self.adb, self.serial)
                )
                app = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: _current_app(self.adb, self.serial)
                )
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
                    # Fallback: WS command for touch (minitouch tunnel unavailable)
                    await loop.run_in_executor(None, self._handle_cmd, msg)

                elif msg_type == "hello_ack":
                    pass

                else:
                    log.debug(f"Recv: {msg_type}")

            except (json.JSONDecodeError, Exception):
                pass

    async def _run_once(self) -> None:
        log.info(f"Connecting to {self.server_url} ...")
        async with websockets.connect(self.server_url, open_timeout=10) as ws:
            loop = asyncio.get_running_loop()

            # ── 1. Send hello ────────────────────────────────────────────────
            bat = await loop.run_in_executor(
                None, lambda: _battery(self.adb, self.serial)
            )
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
            }))
            log.info(f"hello sent (serial={self.serial})")

            # ── 2. Wait for hello_ack ────────────────────────────────────────
            ack_raw = await asyncio.wait_for(ws.recv(), timeout=15.0)
            ack = json.loads(ack_raw)
            if ack.get("type") != "hello_ack":
                raise RuntimeError(f"Expected hello_ack, got: {ack}")
            log.info(f"hello_ack received  tunnels_info={ack.get('tunnels')}")

            # ── 3. WS sender wrapper ─────────────────────────────────────────
            _send_lock = asyncio.Lock()

            async def _send_async(msg: dict) -> None:
                async with _send_lock:
                    await ws.send(json.dumps(msg))

            def _send_sync(msg: dict) -> None:
                if not loop.is_closed():
                    asyncio.run_coroutine_threadsafe(_send_async(msg), loop)

            # ── 4. Set up tunnels ────────────────────────────────────────────
            if self.enable_tunnels:
                self._tunnels = await loop.run_in_executor(
                    None, lambda: self._setup_tunnels(_send_sync)
                )
            else:
                log.info("Tunnels disabled (--no-tunnels)")
                self._tunnels = {}

            # ── 5. Signal tunnels ready ──────────────────────────────────────
            await ws.send(json.dumps({"type": "tunnels_ready"}))
            log.info("tunnels_ready sent")

            # ── 6. Initial status ────────────────────────────────────────────
            bat = await loop.run_in_executor(
                None, lambda: _battery(self.adb, self.serial)
            )
            app = await loop.run_in_executor(
                None, lambda: _current_app(self.adb, self.serial)
            )
            await ws.send(json.dumps(self._status_payload(app, bat)))
            log.info("Initial status sent — agent running")

            try:
                await asyncio.gather(
                    self._frame_sender(ws),
                    self._status_sender(ws),
                    self._receiver(ws),
                    return_exceptions=True,
                )
            finally:
                self._teardown_tunnels()

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
    ap = argparse.ArgumentParser(description="Device Farm Agent (PC/ADB)")
    ap.add_argument("--serial", default="")
    ap.add_argument("--server",
                    default=os.environ.get("DEVICE_FARM_WS",
                                           "ws://192.168.1.93:8081/device-agent"))
    ap.add_argument("--scrcpy-jar",
                    default=os.environ.get("SCRCPY_JAR",
                                           "/opt/homebrew/share/scrcpy/scrcpy-server"))
    ap.add_argument("--fps",   type=int, default=30)
    ap.add_argument("--width", type=int, default=800)
    ap.add_argument("--adb",   default=os.environ.get("ADB", "adb"))
    ap.add_argument("--use-u2", action="store_true",
                    help="Use uiautomator2 screenshots instead of scrcpy")
    ap.add_argument("--no-tunnels", action="store_true",
                    help="Disable WS tunnels (minitouch/u2/stfservice)")
    args = ap.parse_args()

    serial = args.serial.strip()
    if not serial:
        devs = _adb_devices(args.adb)
        if not devs:
            log.error("No ADB devices found.")
            sys.exit(1)
        serial = devs[0]
        log.info(f"Auto-detected: {serial}")
    elif ":" in serial:
        subprocess.run([args.adb, "connect", serial], timeout=10)

    DeviceAgent(
        serial=serial,
        server_url=args.server,
        scrcpy_jar=args.scrcpy_jar,
        fps=args.fps,
        max_width=args.width,
        adb=args.adb,
        use_u2=args.use_u2,
        enable_tunnels=not args.no_tunnels,
    ).run()


if __name__ == "__main__":
    main()
