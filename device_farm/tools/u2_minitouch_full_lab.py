#!/usr/bin/env python3
"""
uiautomator2 + DeviceFarmer/minitouch – Kịch bản đầy đủ tính năng
====================================================================
Tham khảo protocol: https://github.com/DeviceFarmer/minitouch

Kiến trúc:
  - uiautomator2  → tìm phần tử, lấy hierarchy, chụp ảnh, shell, app lifecycle
  - minitouch     → TẤT CẢ thao tác cảm ứng (tap, swipe, long-press, pinch, multi-touch)

Luồng minitouch:
  1. Lấy ABI thiết bị
  2. Push binary libs/<ABI>/minitouch lên /data/local/tmp/minitouch
  3. Chạy minitouch qua adb shell (background)
  4. adb forward tcp:<port> localabstract:minitouch
  5. Kết nối TCP socket, đọc header (v / ^ / $)
  6. Gửi lệnh d/m/u/c/w qua socket
  7. Dọn dẹp khi kết thúc
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import uiautomator2 as u2


# ══════════════════════════════════════════════════════════════════
#  CẤU HÌNH MẶC ĐỊNH
# ══════════════════════════════════════════════════════════════════

MINITOUCH_REMOTE   = "/data/local/tmp/minitouch"
MINITOUCH_PORT     = 1111          # cổng TCP cục bộ sau khi forward
MINITOUCH_SOCKET   = "minitouch"   # tên abstract unix socket
DEFAULT_PRESSURE   = 50
DEFAULT_LIBS_DIR   = Path(__file__).parent / "libs"  # thư mục chứa binary đã build


# ══════════════════════════════════════════════════════════════════
#  ADB HELPERS
# ══════════════════════════════════════════════════════════════════

def _run(cmd: list[str], timeout: int = 20, check: bool = False) -> subprocess.CompletedProcess[str]:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise RuntimeError(f"Lệnh thất bại: {' '.join(cmd)}\n{p.stderr.strip()}")
    return p


def _adb(adb: str, serial: str, *args, timeout: int = 20, check: bool = False) -> str:
    cmd = [adb, "-s", serial] + list(args)
    return _run(cmd, timeout=timeout, check=check).stdout


def _adb_devices(adb: str) -> list[str]:
    out = _run([adb, "devices"], timeout=10, check=True).stdout
    return [
        line.split()[0]
        for line in out.splitlines()[1:]
        if line.strip() and len(line.split()) >= 2 and line.split()[1] == "device"
    ]


def _maybe_connect(adb: str, serial: str, timeout: int) -> None:
    if ":" in serial and serial not in _adb_devices(adb):
        _run([adb, "connect", serial], timeout=timeout, check=True)
        time.sleep(0.3)


def _get_abi(adb: str, serial: str) -> str:
    abi = _adb(adb, serial, "shell", "getprop", "ro.product.cpu.abi").strip().rstrip("\r")
    if not abi:
        raise RuntimeError("Không lấy được ABI từ thiết bị")
    return abi


def _get_sdk(adb: str, serial: str) -> int:
    sdk = _adb(adb, serial, "shell", "getprop", "ro.build.version.sdk").strip().rstrip("\r")
    try:
        return int(sdk)
    except ValueError:
        return 0


# ══════════════════════════════════════════════════════════════════
#  MINITOUCH MANAGER
# ══════════════════════════════════════════════════════════════════

@dataclass
class MiniTouchHeader:
    version:      int = 0
    max_contacts: int = 1
    max_x:        int = 1080
    max_y:        int = 1920
    max_pressure: int = 255
    pid:          int = 0


class MiniTouchManager:
    """
    Quản lý toàn bộ vòng đời của minitouch:
      push binary → chạy process → forward port → kết nối socket → gửi lệnh → cleanup
    """

    def __init__(
        self,
        adb: str,
        serial: str,
        libs_dir: Path,
        port: int = MINITOUCH_PORT,
    ):
        self.adb      = adb
        self.serial   = serial
        self.libs_dir = libs_dir
        self.port     = port

        self.header: MiniTouchHeader = MiniTouchHeader()
        self._sock:  Optional[socket.socket] = None
        self._proc:  Optional[subprocess.Popen] = None  # type: ignore[type-arg]
        self._lock   = threading.Lock()

    # ── setup / teardown ─────────────────────────────────────────

    def setup(self) -> MiniTouchHeader:
        abi = _get_abi(self.adb, self.serial)
        sdk = _get_sdk(self.adb, self.serial)
        print(f"  [minitouch] ABI={abi}  SDK={sdk}", flush=True)

        # Chọn binary phù hợp (PIE hay noPIE)
        use_nopie = sdk < 16
        binary_name = "minitouch-nopie" if use_nopie else "minitouch"
        local_bin = self.libs_dir / abi / binary_name

        if not local_bin.exists():
            # Thử fallback: kiểm tra binary đã có trên thiết bị chưa
            check = _adb(self.adb, self.serial, "shell", f"ls {MINITOUCH_REMOTE} 2>/dev/null").strip()
            if not check:
                raise FileNotFoundError(
                    f"Không tìm thấy binary: {local_bin}\n"
                    f"Hãy build minitouch (ndk-build) và đặt vào {self.libs_dir}/<abi>/minitouch\n"
                    f"Hoặc push thủ công: adb push <binary> {MINITOUCH_REMOTE}"
                )
            print(f"  [minitouch] Dùng binary đã có trên thiết bị: {MINITOUCH_REMOTE}", flush=True)
        else:
            # Push binary lên thiết bị
            print(f"  [minitouch] Đang push {local_bin} → {MINITOUCH_REMOTE}", flush=True)
            _run([self.adb, "-s", self.serial, "push", str(local_bin), MINITOUCH_REMOTE], check=True)
            _adb(self.adb, self.serial, "shell", f"chmod 755 {MINITOUCH_REMOTE}")

        # Android 10+ cần workaround: chạy qua run-as hoặc STFService
        # Ở đây ta thử chạy thẳng (hoạt động nếu đã root hoặc SDK<=28 workaround)
        self._kill_existing()

        # Chạy minitouch trong background
        cmd = [self.adb, "-s", self.serial, "shell",
               f"{MINITOUCH_REMOTE} -n {MINITOUCH_SOCKET}"]
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        time.sleep(0.8)  # cho minitouch khởi động

        # Forward port
        _run([self.adb, "-s", self.serial, "forward",
              f"tcp:{self.port}", f"localabstract:{MINITOUCH_SOCKET}"], check=True)
        print(f"  [minitouch] forward tcp:{self.port} → localabstract:{MINITOUCH_SOCKET}", flush=True)

        # Kết nối socket và đọc header
        self._connect_socket()
        return self.header

    def _kill_existing(self) -> None:
        _adb(self.adb, self.serial, "shell",
             f"pkill -f {MINITOUCH_REMOTE} 2>/dev/null; true")
        time.sleep(0.2)

    def _connect_socket(self, retries: int = 5) -> None:
        for attempt in range(retries):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(5.0)
                s.connect(("127.0.0.1", self.port))
                self._sock = s
                self._read_header()
                return
            except (ConnectionRefusedError, OSError):
                if attempt < retries - 1:
                    time.sleep(0.5)
                else:
                    raise RuntimeError(f"Không kết nối được minitouch socket tại port {self.port}")

    def _read_header(self) -> None:
        """Đọc header v / ^ / $ từ socket theo protocol minitouch."""
        assert self._sock
        buf = b""
        lines_read = 0
        while lines_read < 3:
            chunk = self._sock.recv(256)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.decode("utf-8", errors="replace").strip()
                if line.startswith("v "):
                    self.header.version = int(line.split()[1])
                elif line.startswith("^ "):
                    parts = line.split()
                    self.header.max_contacts = int(parts[1])
                    self.header.max_x        = int(parts[2])
                    self.header.max_y        = int(parts[3])
                    self.header.max_pressure = int(parts[4])
                elif line.startswith("$ "):
                    self.header.pid = int(line.split()[1])
                lines_read += 1
        self._sock.settimeout(None)  # blocking mode sau khi đọc header
        print(
            f"  [minitouch] Header: v={self.header.version}  "
            f"contacts={self.header.max_contacts}  "
            f"max=({self.header.max_x},{self.header.max_y})  "
            f"pressure={self.header.max_pressure}  pid={self.header.pid}",
            flush=True,
        )

    def teardown(self) -> None:
        """Gửi reset, đóng socket, dừng process, xóa forward."""
        try:
            self.reset()
        except Exception:
            pass
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:
                pass
            self._proc = None
        try:
            _run([self.adb, "-s", self.serial, "forward", "--remove", f"tcp:{self.port}"])
        except Exception:
            pass
        self._kill_existing()

    # ── low-level send ────────────────────────────────────────────

    def _send(self, data: str) -> None:
        assert self._sock, "minitouch socket chưa được kết nối"
        with self._lock:
            self._sock.sendall(data.encode("utf-8"))

    # ── protocol commands ─────────────────────────────────────────

    def commit(self) -> "MiniTouchManager":
        self._send("c\n")
        return self

    def wait(self, ms: int) -> "MiniTouchManager":
        """Lệnh w <ms> — minitouch tự sleep, KHÔNG block Python."""
        self._send(f"w {ms}\n")
        return self

    def down(self, contact: int, x: int, y: int, pressure: int = DEFAULT_PRESSURE) -> "MiniTouchManager":
        self._send(f"d {contact} {x} {y} {pressure}\n")
        return self

    def move(self, contact: int, x: int, y: int, pressure: int = DEFAULT_PRESSURE) -> "MiniTouchManager":
        self._send(f"m {contact} {x} {y} {pressure}\n")
        return self

    def up(self, contact: int) -> "MiniTouchManager":
        self._send(f"u {contact}\n")
        return self

    def reset(self) -> "MiniTouchManager":
        self._send("r\n")
        return self

    # ── tọa độ màn hình → tọa độ touch ───────────────────────────

    def screen_to_touch(self, screen_x: int, screen_y: int,
                        screen_w: int, screen_h: int) -> tuple[int, int]:
        """
        Chuyển tọa độ pixel màn hình sang không gian tọa độ minitouch.
        max_x / max_y của thiết bị thường KHÁC kích thước màn hình.
        """
        tx = int(screen_x / screen_w * self.header.max_x)
        ty = int(screen_y / screen_h * self.header.max_y)
        return tx, ty

    # ── gesture helpers ───────────────────────────────────────────

    def tap(self, tx: int, ty: int,
            pressure: int = DEFAULT_PRESSURE, hold_ms: int = 0) -> None:
        """Tap đơn. hold_ms > 0 → long press."""
        self.down(0, tx, ty, pressure).commit()
        if hold_ms > 0:
            self.wait(hold_ms)
        time.sleep(max(hold_ms / 1000, 0.05))
        self.up(0).commit()
        time.sleep(0.05)

    def double_tap(self, tx: int, ty: int,
                   pressure: int = DEFAULT_PRESSURE, gap_ms: int = 100) -> None:
        """Double tap."""
        self.tap(tx, ty, pressure)
        self.wait(gap_ms)
        time.sleep(gap_ms / 1000)
        self.tap(tx, ty, pressure)

    def long_press(self, tx: int, ty: int,
                   duration_ms: int = 1000, pressure: int = DEFAULT_PRESSURE) -> None:
        """Long press bằng cách giữ rồi thả."""
        self.down(0, tx, ty, pressure).commit()
        self.wait(duration_ms)
        time.sleep(duration_ms / 1000 + 0.05)
        self.up(0).commit()
        time.sleep(0.05)

    def swipe(self, x1: int, y1: int, x2: int, y2: int,
              duration_ms: int = 400, steps: int = 20,
              pressure: int = DEFAULT_PRESSURE) -> None:
        """Swipe mượt từ (x1,y1) đến (x2,y2)."""
        self.down(0, x1, y1, pressure).commit()
        delay = duration_ms / steps
        for i in range(1, steps + 1):
            mx = int(x1 + (x2 - x1) * i / steps)
            my = int(y1 + (y2 - y1) * i / steps)
            self.move(0, mx, my, pressure)
            self.wait(int(delay))
            self.commit()
            time.sleep(delay / 1000)
        self.up(0).commit()
        time.sleep(0.05)

    def fling(self, x1: int, y1: int, x2: int, y2: int,
              duration_ms: int = 100, pressure: int = DEFAULT_PRESSURE) -> None:
        """Fling (swipe nhanh) — ít bước hơn swipe."""
        self.swipe(x1, y1, x2, y2, duration_ms=duration_ms, steps=5, pressure=pressure)

    def drag(self, x1: int, y1: int, x2: int, y2: int,
             duration_ms: int = 600, pressure: int = DEFAULT_PRESSURE) -> None:
        """Drag: nhấn giữ rồi kéo chậm."""
        self.down(0, x1, y1, pressure).commit()
        self.wait(300)
        time.sleep(0.3)
        steps = 30
        delay = duration_ms / steps
        for i in range(1, steps + 1):
            mx = int(x1 + (x2 - x1) * i / steps)
            my = int(y1 + (y2 - y1) * i / steps)
            self.move(0, mx, my, pressure)
            self.wait(int(delay))
            self.commit()
            time.sleep(delay / 1000)
        self.up(0).commit()
        time.sleep(0.05)

    def pinch_in(self, cx: int, cy: int, radius: int = 200,
                 duration_ms: int = 500, steps: int = 20,
                 pressure: int = DEFAULT_PRESSURE) -> None:
        """
        Pinch in (zoom out): hai ngón từ ngoài vào giữa.
        contact 0: (cx-radius, cy) → (cx, cy)
        contact 1: (cx+radius, cy) → (cx, cy)
        """
        self.down(0, cx - radius, cy, pressure)
        self.down(1, cx + radius, cy, pressure)
        self.commit()
        delay = duration_ms / steps
        for i in range(1, steps + 1):
            f = i / steps
            self.move(0, int(cx - radius * (1 - f)), cy, pressure)
            self.move(1, int(cx + radius * (1 - f)), cy, pressure)
            self.wait(int(delay))
            self.commit()
            time.sleep(delay / 1000)
        self.up(0)
        self.up(1)
        self.commit()
        time.sleep(0.05)

    def pinch_out(self, cx: int, cy: int, radius: int = 200,
                  duration_ms: int = 500, steps: int = 20,
                  pressure: int = DEFAULT_PRESSURE) -> None:
        """
        Pinch out (zoom in): hai ngón từ giữa ra ngoài.
        contact 0: (cx, cy) → (cx-radius, cy)
        contact 1: (cx, cy) → (cx+radius, cy)
        """
        self.down(0, cx, cy, pressure)
        self.down(1, cx, cy, pressure)
        self.commit()
        delay = duration_ms / steps
        for i in range(1, steps + 1):
            f = i / steps
            self.move(0, int(cx - radius * f), cy, pressure)
            self.move(1, int(cx + radius * f), cy, pressure)
            self.wait(int(delay))
            self.commit()
            time.sleep(delay / 1000)
        self.up(0)
        self.up(1)
        self.commit()
        time.sleep(0.05)

    def multi_tap(self, points: list[tuple[int, int]],
                  pressure: int = DEFAULT_PRESSURE) -> None:
        """Tap đồng thời nhiều điểm."""
        for i, (x, y) in enumerate(points):
            self.down(i, x, y, pressure)
        self.commit()
        time.sleep(0.05)
        for i in range(len(points)):
            self.up(i)
        self.commit()
        time.sleep(0.05)

    def rotate_gesture(self, cx: int, cy: int, radius: int = 150,
                       angle_deg: float = 90, duration_ms: int = 600,
                       steps: int = 30, pressure: int = DEFAULT_PRESSURE) -> None:
        """
        Xoay bằng hai ngón tay quanh tâm (cx, cy) một góc angle_deg.
        """
        import math
        half = math.radians(angle_deg / 2)
        start0 = (-half, 0)   # (angle, contact)
        start1 = (math.pi - half, 1)

        def pos(angle: float) -> tuple[int, int]:
            return (
                int(cx + radius * math.cos(angle)),
                int(cy + radius * math.sin(angle)),
            )

        a0, a1 = -half, math.pi - half
        self.down(0, *pos(a0), pressure)
        self.down(1, *pos(a1), pressure)
        self.commit()

        delta = math.radians(angle_deg) / steps
        delay = duration_ms / steps
        for _ in range(steps):
            a0 += delta
            a1 += delta
            self.move(0, *pos(a0), pressure)
            self.move(1, *pos(a1), pressure)
            self.wait(int(delay))
            self.commit()
            time.sleep(delay / 1000)

        self.up(0)
        self.up(1)
        self.commit()
        time.sleep(0.05)


# ══════════════════════════════════════════════════════════════════
#  ARTIFACT + STEP RUNNER
# ══════════════════════════════════════════════════════════════════

def _now_ms() -> int:
    return int(time.time() * 1000)


def _ensure(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _write(p: Path, s: str) -> None:
    p.write_text(s, encoding="utf-8", errors="replace")


def capture(d: u2.Device, out: Path, tag: str) -> None:
    _ensure(out)
    ts = _now_ms()
    for name, fn in [
        ("app", lambda: str(d.app_current())),
        ("info", lambda: str(d.info)),
    ]:
        try:
            _write(out / f"{ts}_{tag}_{name}.txt", fn())
        except Exception as e:
            _write(out / f"{ts}_{tag}_{name}.err", repr(e))
    try:
        d.screenshot(str(out / f"{ts}_{tag}.png"))
    except Exception as e:
        _write(out / f"{ts}_{tag}_screenshot.err", repr(e))
    try:
        xml = d.dump_hierarchy(compressed=False)
        _write(out / f"{ts}_{tag}.xml", xml)
    except Exception as e:
        _write(out / f"{ts}_{tag}_hierarchy.err", repr(e))


@dataclass
class StepResult:
    name: str
    passed: bool
    duration_ms: int
    error: str = ""


@dataclass
class Runner:
    d: u2.Device
    mt: MiniTouchManager
    out: Path
    results: list[StepResult] = field(default_factory=list)

    def run(self, name: str, fn: Callable[[], None]) -> bool:
        print(f"\n{'─'*60}\n[STEP] {name}", flush=True)
        t0 = _now_ms()
        try:
            fn()
            dur = _now_ms() - t0
            self.results.append(StepResult(name, True, dur))
            print(f"  ✓  ({dur} ms)", flush=True)
            return True
        except Exception as exc:
            dur = _now_ms() - t0
            self.results.append(StepResult(name, False, dur, str(exc)))
            capture(self.d, self.out, f"FAILED_{name}")
            print(f"  ✗  {exc}  ({dur} ms)", file=sys.stderr, flush=True)
            return False

    def report(self) -> dict:
        passed = sum(1 for r in self.results if r.passed)
        total  = len(self.results)
        data   = {"total": total, "passed": passed, "failed": total - passed,
                  "steps": [vars(r) for r in self.results]}
        _write(self.out / "report.json", json.dumps(data, ensure_ascii=False, indent=2))
        print(f"\n{'═'*60}")
        print(f"KẾT QUẢ: {passed}/{total} bước thành công")
        for r in self.results:
            icon = "✓" if r.passed else "✗"
            line = f"  {icon} {r.name:45s} {r.duration_ms:>6} ms"
            if not r.passed:
                line += f"  → {r.error[:80]}"
            print(line)
        return data


# ══════════════════════════════════════════════════════════════════
#  CÁC BƯỚC KỊCH BẢN
# ══════════════════════════════════════════════════════════════════

def _wh(d: u2.Device) -> tuple[int, int]:
    return d.window_size()


def step_screen_on(r: Runner) -> None:
    """Bật màn hình và mở khóa."""
    if not r.d.screen_on():
        r.d.screen_on()
        time.sleep(0.5)
    try:
        r.d.unlock()
    except Exception:
        pass
    assert r.d.screen_on(), "Màn hình chưa bật"
    capture(r.d, r.out, "screen_on")


def step_home(r: Runner) -> None:
    """Nhấn Home và chụp ảnh màn hình chính."""
    r.d.press("home")
    time.sleep(0.8)
    info = r.d.info
    w, h = _wh(r.d)
    print(f"  → {info.get('productName')}  display={w}x{h}  "
          f"mt_max=({r.mt.header.max_x},{r.mt.header.max_y})", flush=True)
    capture(r.d, r.out, "home")


def step_tap(r: Runner) -> None:
    """Tap vào giữa màn hình bằng minitouch."""
    w, h = _wh(r.d)
    tx, ty = r.mt.screen_to_touch(w // 2, h // 2, w, h)
    print(f"  → Tap screen=({w//2},{h//2}) touch=({tx},{ty})", flush=True)
    r.mt.tap(tx, ty)
    time.sleep(0.3)
    capture(r.d, r.out, "tap")


def step_double_tap(r: Runner) -> None:
    """Double tap vào giữa màn hình."""
    w, h = _wh(r.d)
    tx, ty = r.mt.screen_to_touch(w // 2, h // 2, w, h)
    r.mt.double_tap(tx, ty, gap_ms=120)
    time.sleep(0.3)
    capture(r.d, r.out, "double_tap")


def step_long_press(r: Runner) -> None:
    """Long press 1 giây vào giữa màn hình."""
    w, h = _wh(r.d)
    tx, ty = r.mt.screen_to_touch(w // 2, h // 2, w, h)
    r.mt.long_press(tx, ty, duration_ms=1000)
    time.sleep(0.3)
    capture(r.d, r.out, "long_press")
    r.d.press("back")
    time.sleep(0.3)


def step_swipe_directions(r: Runner) -> None:
    """Swipe 4 hướng bằng minitouch."""
    r.d.press("home")
    time.sleep(0.5)
    w, h = _wh(r.d)
    cx, cy = w // 2, h // 2

    def sc(x: int, y: int) -> tuple[int, int]:
        return r.mt.screen_to_touch(x, y, w, h)

    # Lên
    r.mt.swipe(*sc(cx, cy + h // 4), *sc(cx, cy - h // 4), duration_ms=400)
    time.sleep(0.3)
    # Xuống
    r.mt.swipe(*sc(cx, cy - h // 4), *sc(cx, cy + h // 4), duration_ms=400)
    time.sleep(0.3)
    # Trái
    r.mt.swipe(*sc(cx + w // 4, cy), *sc(cx - w // 4, cy), duration_ms=400)
    time.sleep(0.3)
    # Phải
    r.mt.swipe(*sc(cx - w // 4, cy), *sc(cx + w // 4, cy), duration_ms=400)
    time.sleep(0.3)

    capture(r.d, r.out, "swipe")


def step_fling(r: Runner) -> None:
    """Fling nhanh từ dưới lên (mở app drawer trên một số launcher)."""
    r.d.press("home")
    time.sleep(0.5)
    w, h = _wh(r.d)
    tx1, ty1 = r.mt.screen_to_touch(w // 2, h * 3 // 4, w, h)
    tx2, ty2 = r.mt.screen_to_touch(w // 2, h // 4, w, h)
    r.mt.fling(tx1, ty1, tx2, ty2, duration_ms=120)
    time.sleep(0.5)
    capture(r.d, r.out, "fling")
    r.d.press("back")
    time.sleep(0.3)


def step_drag(r: Runner) -> None:
    """Drag icon trên màn hình chính."""
    r.d.press("home")
    time.sleep(0.8)
    w, h = _wh(r.d)
    # Drag từ 1/4 màn hình sang 3/4
    x1, y1 = r.mt.screen_to_touch(w // 4, h // 2, w, h)
    x2, y2 = r.mt.screen_to_touch(w * 3 // 4, h // 2, w, h)
    r.mt.drag(x1, y1, x2, y2, duration_ms=700)
    time.sleep(0.3)
    capture(r.d, r.out, "drag")
    r.d.press("back")
    time.sleep(0.3)


def step_pinch_in(r: Runner) -> None:
    """Pinch in (zoom out) bằng 2 ngón tay qua minitouch."""
    r.d.press("home")
    time.sleep(0.5)
    w, h = _wh(r.d)
    cx, cy = r.mt.screen_to_touch(w // 2, h // 2, w, h)
    # Bán kính = 30% chiều rộng touch space
    radius = int(r.mt.header.max_x * 0.25)
    r.mt.pinch_in(cx, cy, radius=radius, duration_ms=500)
    time.sleep(0.3)
    capture(r.d, r.out, "pinch_in")


def step_pinch_out(r: Runner) -> None:
    """Pinch out (zoom in) bằng 2 ngón tay."""
    w, h = _wh(r.d)
    cx, cy = r.mt.screen_to_touch(w // 2, h // 2, w, h)
    radius = int(r.mt.header.max_x * 0.25)
    r.mt.pinch_out(cx, cy, radius=radius, duration_ms=500)
    time.sleep(0.3)
    capture(r.d, r.out, "pinch_out")


def step_multi_tap(r: Runner) -> None:
    """Tap đồng thời 3 điểm."""
    w, h = _wh(r.d)
    points = [
        r.mt.screen_to_touch(w // 4, h // 2, w, h),
        r.mt.screen_to_touch(w // 2, h // 2, w, h),
        r.mt.screen_to_touch(w * 3 // 4, h // 2, w, h),
    ]
    if r.mt.header.max_contacts >= 3:
        r.mt.multi_tap(points)
    else:
        print(f"  → Thiết bị chỉ hỗ trợ {r.mt.header.max_contacts} contacts, bỏ qua 3-tap", flush=True)
        r.mt.tap(*points[0])
    time.sleep(0.3)
    capture(r.d, r.out, "multi_tap")


def step_rotate_gesture(r: Runner) -> None:
    """Gesture xoay bằng 2 ngón tay 90°."""
    w, h = _wh(r.d)
    cx, cy = r.mt.screen_to_touch(w // 2, h // 2, w, h)
    radius = int(r.mt.header.max_x * 0.2)
    r.mt.rotate_gesture(cx, cy, radius=radius, angle_deg=90, duration_ms=600)
    time.sleep(0.3)
    capture(r.d, r.out, "rotate_gesture")


def step_scroll_settings(r: Runner) -> None:
    """Mở Settings và cuộn bằng minitouch."""
    pkg = "com.android.settings"
    r.d.app_start(pkg)
    time.sleep(2.0)
    w, h = _wh(r.d)

    # Cuộn xuống 3 lần
    for _ in range(3):
        x1, y1 = r.mt.screen_to_touch(w // 2, h * 3 // 4, w, h)
        x2, y2 = r.mt.screen_to_touch(w // 2, h // 4, w, h)
        r.mt.swipe(x1, y1, x2, y2, duration_ms=400)
        time.sleep(0.4)

    capture(r.d, r.out, "scroll_down")

    # Cuộn lên về đầu
    for _ in range(3):
        x1, y1 = r.mt.screen_to_touch(w // 2, h // 4, w, h)
        x2, y2 = r.mt.screen_to_touch(w // 2, h * 3 // 4, w, h)
        r.mt.swipe(x1, y1, x2, y2, duration_ms=400)
        time.sleep(0.4)

    capture(r.d, r.out, "scroll_up")
    r.d.app_stop(pkg)
    r.d.press("home")
    time.sleep(0.5)


def step_tap_element(r: Runner) -> None:
    """Tìm phần tử bằng u2, lấy tọa độ, tap bằng minitouch."""
    pkg = "com.android.settings"
    r.d.app_start(pkg)
    time.sleep(2.0)

    # Tìm item đầu tiên trong Settings
    w, h = _wh(r.d)
    found = False
    for cls in ["android.widget.TextView", "android.widget.LinearLayout"]:
        items = r.d(className=cls, clickable=True)
        if items.exists(timeout=3) and items.count > 0:
            try:
                bounds = items[0].info["bounds"]
                # Lấy tâm phần tử
                ex = (bounds["left"] + bounds["right"]) // 2
                ey = (bounds["top"] + bounds["bottom"]) // 2
                tx, ty = r.mt.screen_to_touch(ex, ey, w, h)
                print(f"  → Tap element [{cls}] tại screen=({ex},{ey}) touch=({tx},{ty})", flush=True)
                r.mt.tap(tx, ty)
                time.sleep(0.8)
                capture(r.d, r.out, "tap_element")
                r.d.press("back")
                found = True
                break
            except Exception as e:
                print(f"  → {e}", flush=True)

    if not found:
        print("  → Không tìm thấy phần tử clickable", flush=True)

    r.d.app_stop(pkg)
    r.d.press("home")
    time.sleep(0.5)


def step_notification(r: Runner) -> None:
    """Kéo thanh thông báo bằng minitouch (swipe từ trên xuống)."""
    r.d.press("home")
    time.sleep(0.5)
    w, h = _wh(r.d)
    # Kéo từ cạnh trên màn hình xuống giữa
    x1, y1 = r.mt.screen_to_touch(w // 2, 0, w, h)
    x2, y2 = r.mt.screen_to_touch(w // 2, h // 2, w, h)
    r.mt.swipe(x1, max(y1, 5), x2, y2, duration_ms=400)
    time.sleep(1.0)
    capture(r.d, r.out, "notification_open")

    # Đóng bằng swipe ngược lại
    r.mt.swipe(x2, y2, x1, max(y1, 5), duration_ms=300)
    time.sleep(0.5)


def step_screenshot_hierarchy(r: Runner) -> None:
    """Chụp ảnh và lấy hierarchy qua u2."""
    img = r.out / f"{_now_ms()}_screen.png"
    r.d.screenshot(str(img))
    assert img.exists()
    xml = r.d.dump_hierarchy()
    assert xml and "<hierarchy" in xml
    print(f"  → {img.name}  XML={len(xml)} chars", flush=True)


def step_shell_info(r: Runner) -> None:
    """Lấy thông tin thiết bị qua shell."""
    cmds = [
        "getprop ro.product.model",
        "getprop ro.build.version.release",
        "wm size",
        "wm density",
        "dumpsys battery | grep level",
    ]
    results = {}
    for cmd in cmds:
        try:
            out, _ = r.d.shell(cmd)
            results[cmd] = out.strip()
        except Exception as e:
            results[cmd] = f"ERROR: {e}"
        print(f"  $ {cmd} → {results[cmd]}", flush=True)
    _write(r.out / f"{_now_ms()}_shell.json",
           json.dumps(results, ensure_ascii=False, indent=2))


def step_app_lifecycle(r: Runner) -> None:
    """Vòng đời app: start → kiểm tra → stop."""
    pkg = "com.android.settings"
    r.d.app_start(pkg)

    ok = _wait_until(lambda: r.d.app_current().get("package") == pkg, 10.0)
    assert ok, f"Settings không lên foreground: {r.d.app_current()}"
    capture(r.d, r.out, "app_start")

    try:
        info = r.d.app_info(pkg)
        print(f"  → version={info.get('versionName')}  size={info.get('totalSize')}", flush=True)
    except Exception:
        pass

    r.d.press("home")
    time.sleep(0.4)
    r.d.app_stop(pkg)
    time.sleep(0.3)


def step_minitouch_raw_sequence(r: Runner) -> None:
    """
    Demo gửi chuỗi lệnh minitouch protocol thô.
    Mô phỏng chính xác ví dụ pinch từ README của DeviceFarmer.
    """
    # Lấy tọa độ tương đối theo max_x / max_y
    mx = r.mt.header.max_x
    my = r.mt.header.max_y

    # Pinch in từ (10%,50%) và (90%,50%) vào (50%,50%)
    x_left   = int(mx * 0.10)
    x_right  = int(mx * 0.90)
    x_center = int(mx * 0.50)
    y_mid    = int(my * 0.50)

    steps_raw = 8
    print(f"  → Raw pinch: ({x_left},{y_mid})↔({x_right},{y_mid}) → ({x_center},{y_mid})", flush=True)

    r.mt.down(0, x_left,  y_mid)
    r.mt.down(1, x_right, y_mid)
    r.mt.commit()

    for i in range(1, steps_raw + 1):
        f = i / steps_raw
        r.mt.move(0, int(x_left  + (x_center - x_left)  * f), y_mid)
        r.mt.move(1, int(x_right + (x_center - x_right) * f), y_mid)
        r.mt.wait(30)
        r.mt.commit()
        time.sleep(0.03)

    r.mt.up(0)
    r.mt.up(1)
    r.mt.commit()
    time.sleep(0.1)
    capture(r.d, r.out, "raw_sequence")


def step_cleanup(r: Runner) -> None:
    """Reset minitouch và về màn hình chính."""
    r.mt.reset()
    r.d.press("home")
    time.sleep(0.5)
    capture(r.d, r.out, "final")


def _wait_until(pred: Callable[[], bool], timeout_s: float, interval: float = 0.25) -> bool:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        try:
            if pred():
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


# ══════════════════════════════════════════════════════════════════
#  DANH SÁCH BƯỚC
# ══════════════════════════════════════════════════════════════════

ALL_STEPS: list[tuple[str, Callable[[Runner], None]]] = [
    ("screen_on",             step_screen_on),
    ("home",                  step_home),
    ("screenshot_hierarchy",  step_screenshot_hierarchy),
    ("shell_info",            step_shell_info),
    ("tap",                   step_tap),
    ("double_tap",            step_double_tap),
    ("long_press",            step_long_press),
    ("swipe_directions",      step_swipe_directions),
    ("fling",                 step_fling),
    ("drag",                  step_drag),
    ("pinch_in",              step_pinch_in),
    ("pinch_out",             step_pinch_out),
    ("multi_tap",             step_multi_tap),
    ("rotate_gesture",        step_rotate_gesture),
    ("scroll_settings",       step_scroll_settings),
    ("tap_element",           step_tap_element),
    ("notification",          step_notification),
    ("app_lifecycle",         step_app_lifecycle),
    ("minitouch_raw_sequence",step_minitouch_raw_sequence),
    ("cleanup",               step_cleanup),
]


# ══════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════

def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="uiautomator2 + DeviceFarmer/minitouch full scenario")
    ap.add_argument("--serial",            default="",          help="ADB serial hoặc ip:port")
    ap.add_argument("--adb",               default=os.environ.get("ADB", "adb"))
    ap.add_argument("--artifacts",         default="artifacts")
    ap.add_argument("--libs-dir",          default=str(DEFAULT_LIBS_DIR),
                    help="Thư mục chứa libs/<abi>/minitouch đã build")
    ap.add_argument("--port",              type=int, default=MINITOUCH_PORT)
    ap.add_argument("--timeout",           type=float, default=25.0)
    ap.add_argument("--connect-timeout",   type=int,   default=10)
    ap.add_argument("--u2-connect-timeout",type=float, default=60.0)
    ap.add_argument("--steps",             default="",
                    help="Chỉ chạy các bước này (tên cách nhau bằng dấu phẩy)")
    ap.add_argument("--stop-on-fail",      action="store_true")
    ap.add_argument("--list-steps",        action="store_true", help="Liệt kê tất cả bước rồi thoát")
    args = ap.parse_args(argv)

    if args.list_steps:
        print("Các bước có sẵn:")
        for name, fn in ALL_STEPS:
            doc = (fn.__doc__ or "").strip().split("\n")[0]
            print(f"  {name:35s} – {doc}")
        return 0

    # ── ADB serial ──────────────────────────────────────────────
    serial = args.serial.strip()
    if serial:
        _maybe_connect(args.adb, serial, args.connect_timeout)
    else:
        serials = _adb_devices(args.adb)
        if not serials:
            print("Không tìm thấy thiết bị ADB. Chạy: adb devices", file=sys.stderr)
            return 2
        serial = serials[0]

    safe_serial = "".join(c if c.isalnum() or c in "-_." else "_" for c in serial)
    out_dir = Path(args.artifacts) / safe_serial
    _ensure(out_dir)

    print(f"Thiết bị   : {serial}")
    print(f"Artifacts  : {out_dir.resolve()}")
    print(f"libs-dir   : {args.libs_dir}")

    # ── Kết nối u2 ──────────────────────────────────────────────
    print(f"\n[u2] Kết nối tới {serial} ...", flush=True)
    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(u2.connect, serial)
        try:
            d = fut.result(timeout=args.u2_connect_timeout)
        except FuturesTimeoutError as e:
            raise RuntimeError(f"u2.connect timeout sau {args.u2_connect_timeout}s") from e

    d.implicitly_wait(10.0)
    d.settings["wait_timeout"] = 20.0

    # Watchers tự động đóng popup
    d.watcher("g_ok").when("OK").click()
    d.watcher("g_allow").when("Allow").click()
    d.watcher.start()

    # ── Khởi động minitouch ──────────────────────────────────────
    mt = MiniTouchManager(
        adb=args.adb,
        serial=serial,
        libs_dir=Path(args.libs_dir),
        port=args.port,
    )
    print("\n[minitouch] Khởi động ...", flush=True)
    header = mt.setup()

    # ── Lọc bước ────────────────────────────────────────────────
    selected = {s.strip() for s in args.steps.split(",") if s.strip()}
    steps_to_run = [
        (name, fn) for name, fn in ALL_STEPS
        if not selected or name in selected
    ]

    runner = Runner(d=d, mt=mt, out=out_dir)

    try:
        for name, fn in steps_to_run:
            ok = runner.run(name, lambda f=fn: f(runner))
            if not ok and args.stop_on_fail:
                print("\n[u2] Dừng do --stop-on-fail", file=sys.stderr)
                break
    finally:
        d.watcher.stop()
        d.watcher.reset()
        print("\n[minitouch] Dọn dẹp ...", flush=True)
        mt.teardown()

    summary = runner.report()
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())