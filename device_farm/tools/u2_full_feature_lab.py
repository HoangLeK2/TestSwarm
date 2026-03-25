#!/usr/bin/env python3
"""
uiautomator2 - Kịch bản đầy đủ tính năng
==========================================
Bao gồm: kết nối, màn hình, cử chỉ, nhập liệu, ứng dụng,
         tìm kiếm phần tử, chờ đợi, cuộn, clipboard,
         thông báo, xoay màn hình, file/screenshot, watcher.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import uiautomator2 as u2


# ─────────────────────────── helpers ────────────────────────────

def _now_ms() -> int:
    return int(time.time() * 1000)


def _safe_name(serial: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in serial)


def _run(cmd: list[str], timeout: int = 20, check: bool = False) -> subprocess.CompletedProcess[str]:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise RuntimeError(f"Lỗi lệnh: {' '.join(cmd)}\n{p.stderr}")
    return p


def _adb_devices(adb: str) -> list[str]:
    out = _run([adb, "devices"], timeout=10, check=True).stdout
    return [
        line.split()[0]
        for line in out.splitlines()[1:]
        if line.strip() and line.split()[1] == "device"
    ]


def _maybe_connect(adb: str, serial: str, timeout: int) -> None:
    if ":" in serial and serial not in _adb_devices(adb):
        _run([adb, "connect", serial], timeout=timeout, check=True)
        time.sleep(0.3)


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _write(p: Path, content: str) -> None:
    p.write_text(content, encoding="utf-8", errors="replace")


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


# ─────────────────────────── artifact capture ───────────────────

def capture(d: u2.Device, out: Path, tag: str) -> None:
    _ensure_dir(out)
    ts = _now_ms()
    for name, getter in [
        ("app_current", lambda: str(d.app_current())),
        ("info", lambda: str(d.info)),
        ("device_info", lambda: str(d.device_info)),
    ]:
        try:
            _write(out / f"{ts}_{tag}_{name}.txt", getter())
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


# ─────────────────────────── step runner ────────────────────────

@dataclass
class StepResult:
    name: str
    passed: bool
    duration_ms: int
    error: str = ""


@dataclass
class Runner:
    d: u2.Device
    out: Path
    timeout: float
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
        total = len(self.results)
        summary = {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "steps": [vars(r) for r in self.results],
        }
        _write(self.out / "report.json", json.dumps(summary, ensure_ascii=False, indent=2))
        print(f"\n{'═'*60}")
        print(f"KẾT QUẢ: {passed}/{total} bước thành công")
        for r in self.results:
            icon = "✓" if r.passed else "✗"
            line = f"  {icon} {r.name:40s} {r.duration_ms:>6} ms"
            if not r.passed:
                line += f"  → {r.error[:80]}"
            print(line)
        return summary


# ═══════════════════════════════════════════════════════════════
#                       CÁC BƯỚC KỊCH BẢN
# ═══════════════════════════════════════════════════════════════

def step_screen_power(d: u2.Device, out: Path, timeout: float) -> None:
    """Bật màn hình và mở khóa."""
    if not d.screen_on():
        d.screen_on()
        time.sleep(0.5)
    d.unlock()
    time.sleep(0.3)
    assert d.screen_on(), "Màn hình chưa bật"
    capture(d, out, "screen_on")


def step_home_and_info(d: u2.Device, out: Path, timeout: float) -> None:
    """Nhấn Home, ghi thông tin thiết bị."""
    d.press("home")
    time.sleep(0.8)
    info = d.info
    print(f"  → Model: {info.get('productName','?')}  "
          f"Display: {info.get('displayWidth')}x{info.get('displayHeight')}", flush=True)
    capture(d, out, "home")


def step_screenshot_hierarchy(d: u2.Device, out: Path, timeout: float) -> None:
    """Chụp ảnh màn hình và lấy cây hierarchy."""
    img_path = out / f"{_now_ms()}_manual.png"
    d.screenshot(str(img_path))
    assert img_path.exists(), "Không tạo được file ảnh"

    xml = d.dump_hierarchy()
    assert xml and "<hierarchy" in xml, "Hierarchy XML rỗng"
    print(f"  → Screenshot: {img_path.name}  |  XML length: {len(xml)}", flush=True)


def step_gestures(d: u2.Device, out: Path, timeout: float) -> None:
    """Thực hiện các cử chỉ: tap, double-tap, long-press, swipe, fling, drag."""
    w, h = d.window_size()
    cx, cy = w // 2, h // 2

    # Tap giữa màn hình
    d.click(cx, cy)
    time.sleep(0.2)

    # Double tap
    d.double_click(cx, cy, duration=0.1)
    time.sleep(0.2)

    # Long press
    d.long_click(cx, cy, duration=1.0)
    time.sleep(0.3)

    # Swipe lên / xuống
    d.swipe(cx, cy + h // 4, cx, cy - h // 4, duration=0.4)
    time.sleep(0.3)
    d.swipe(cx, cy - h // 4, cx, cy + h // 4, duration=0.4)
    time.sleep(0.3)

    # Swipe trái / phải
    d.swipe(cx + w // 4, cy, cx - w // 4, cy, duration=0.4)
    time.sleep(0.2)
    d.swipe(cx - w // 4, cy, cx + w // 4, cy, duration=0.4)
    time.sleep(0.2)

    # Fling (nhanh)
    d.swipe(cx, cy + h // 3, cx, cy - h // 3, duration=0.15)
    time.sleep(0.2)

    # Drag (nhấn giữ rồi kéo)
    d.drag(cx, cy, cx + 50, cy + 50, duration=0.5)
    time.sleep(0.2)

    capture(d, out, "gestures")
    d.press("home")
    time.sleep(0.5)


def step_multi_touch(d: u2.Device, out: Path, timeout: float) -> None:
    """Pinch in/out bằng touch chain."""
    w, h = d.window_size()
    cx, cy = w // 2, h // 2

    # Pinch out (zoom in)
    d.touch.down(cx - 50, cy).sleep(0.05).move(cx - 150, cy).sleep(0.1).up(cx - 150, cy)
    time.sleep(0.2)

    # Hai ngón tay qua TouchAction nếu device hỗ trợ
    try:
        t1 = d.touch.start(cx - 80, cy)
        t2 = d.touch.start(cx + 80, cy)
        t1.move(cx - 20, cy)
        t2.move(cx + 20, cy)
        t1.up()
        t2.up()
    except Exception:
        pass  # Không phải thiết bị nào cũng hỗ trợ multi-touch API này

    capture(d, out, "multi_touch")


def step_keyboard_input(d: u2.Device, out: Path, timeout: float) -> None:
    """Mở ứng dụng Notes/Notepad và gõ văn bản."""
    # Thử mở ứng dụng ghi chú phổ biến
    editors = [
        "com.google.android.keep",
        "com.samsung.android.app.notes",
        "com.miui.notes",
        "com.coloros.note",
    ]
    opened = False
    for pkg in editors:
        try:
            d.app_start(pkg)
            time.sleep(1.5)
            cur = d.app_current().get("package", "")
            if cur == pkg:
                opened = True
                break
        except Exception:
            continue

    if not opened:
        # Fallback: tìm bất kỳ ô nhập liệu nào trên màn hình hiện tại
        d.press("home")
        time.sleep(0.5)

    # Tìm EditText bất kỳ
    try:
        el = d(className="android.widget.EditText")
        if el.exists(timeout=3):
            el.click()
            time.sleep(0.3)
    except Exception:
        pass

    # Gõ văn bản qua send_keys
    try:
        d.send_keys("Xin chào uiautomator2! 123 @#$")
        time.sleep(0.5)
    except Exception:
        pass

    # Gõ qua shell input text (luôn hoạt động dù không focus)
    try:
        d.shell("input text 'Hello_UI2'")
        time.sleep(0.3)
    except Exception:
        pass

    capture(d, out, "keyboard_input")

    # Xóa văn bản vừa gõ (Ctrl+A → Delete)
    try:
        d.clear_text()
    except Exception:
        d.press("del")

    d.press("back")
    time.sleep(0.3)
    d.press("home")
    time.sleep(0.5)


def step_clipboard(d: u2.Device, out: Path, timeout: float) -> None:
    """Đặt và lấy nội dung clipboard."""
    try:
        d.set_clipboard("Nội dung clipboard từ u2")
        time.sleep(0.3)
        content = d.get_clipboard()
        print(f"  → Clipboard: {repr(content)}", flush=True)
    except Exception as e:
        print(f"  → Clipboard không hỗ trợ: {e}", flush=True)


def step_notification_panel(d: u2.Device, out: Path, timeout: float) -> None:
    """Mở và đóng thanh thông báo."""
    d.open_notification()
    time.sleep(1.0)
    capture(d, out, "notification_open")

    # Cuộn trong notification panel
    w, h = d.window_size()
    d.swipe(w // 2, h // 4, w // 2, h // 2, duration=0.4)
    time.sleep(0.3)

    d.press("back")
    time.sleep(0.4)


def step_quick_settings(d: u2.Device, out: Path, timeout: float) -> None:
    """Mở Quick Settings (kéo 2 lần)."""
    try:
        d.open_quick_settings()
        time.sleep(1.0)
        capture(d, out, "quick_settings")
        d.press("back")
        time.sleep(0.4)
    except Exception as e:
        print(f"  → open_quick_settings: {e}", flush=True)


def step_find_elements(d: u2.Device, out: Path, timeout: float) -> None:
    """
    Minh họa đầy đủ các cách tìm phần tử:
    by text, by resourceId, by className, by description,
    by XPath, by index, child/sibling.
    """
    d.press("home")
    time.sleep(0.5)

    results = {}

    # 1. Theo text
    el_text = d(text="OK")
    results["by_text(OK)_exists"] = el_text.exists(timeout=1)

    # 2. Theo textContains
    el_contains = d(textContains="Sett")
    results["by_textContains(Sett)"] = el_contains.exists(timeout=1)

    # 3. Theo className
    els_class = d(className="android.widget.TextView")
    count = 0
    try:
        count = els_class.count
    except Exception:
        pass
    results["className=TextView_count"] = count
    print(f"  → TextView trên màn hình: {count}", flush=True)

    # 4. Theo resourceId (ví dụ id launcher)
    el_rid = d(resourceId="com.android.launcher3:id/workspace")
    results["resourceId_workspace"] = el_rid.exists(timeout=1)

    # 5. XPath
    el_xpath = d.xpath("//android.widget.TextView")
    results["xpath_textview"] = el_xpath.exists

    # 6. Tìm con
    try:
        parent = d(className="android.widget.LinearLayout")
        if parent.exists(timeout=1):
            child = parent.child(className="android.widget.TextView")
            results["child_textview"] = child.exists(timeout=1)
    except Exception:
        results["child_textview"] = "N/A"

    # 7. Lấy thuộc tính của phần tử đầu tiên
    try:
        first_tv = d(className="android.widget.TextView")[0]
        attrs = {
            "text": first_tv.get_text(),
            "bounds": str(first_tv.info.get("bounds", {})),
            "enabled": first_tv.info.get("enabled"),
            "clickable": first_tv.info.get("clickable"),
        }
        results["first_textview_attrs"] = attrs
        print(f"  → TextView đầu tiên: {attrs['text']!r}", flush=True)
    except Exception as e:
        results["first_textview_attrs"] = str(e)

    _write(out / f"{_now_ms()}_find_elements.json",
           json.dumps(results, ensure_ascii=False, indent=2))
    capture(d, out, "find_elements")


def step_wait_strategies(d: u2.Device, out: Path, timeout: float) -> None:
    """
    Các chiến lược chờ:
    - wait until exists / gone
    - wait_activity
    - implicitly_wait
    - poll-based _wait_until
    """
    # Chờ một TextView xuất hiện (đang ở home nên chắc có)
    el = d(className="android.widget.TextView")
    appeared = el.wait(timeout=5)
    print(f"  → TextView appeared: {appeared}", flush=True)

    # Chờ biến mất (timeout ngắn, chỉ để demo)
    el_fake = d(text="__không_tồn_tại__")
    gone = el_fake.wait_gone(timeout=2)
    print(f"  → Fake element gone: {gone}", flush=True)

    # Poll-based
    ok = _wait_until(
        lambda: d(className="android.widget.TextView").exists(timeout=0),
        timeout_s=5.0,
    )
    print(f"  → Poll-based wait: {ok}", flush=True)

    # implicitly_wait thay đổi tạm thời
    d.implicitly_wait(3.0)
    capture(d, out, "wait_strategies")
    d.implicitly_wait(10.0)  # khôi phục


def step_scroll_and_swipe(d: u2.Device, out: Path, timeout: float) -> None:
    """Cuộn danh sách (ScrollView, RecyclerView) nhiều cách."""
    # Mở Settings để có màn hình cuộn được
    settings_pkg = "com.android.settings"
    d.app_start(settings_pkg)
    time.sleep(2.0)

    # 1. Scroll object bằng uiautomator2 selector
    try:
        scrollable = d(scrollable=True)
        if scrollable.exists(timeout=3):
            scrollable.scroll.to(text="About")
        time.sleep(0.5)
    except Exception:
        pass

    # 2. Swipe tọa độ
    w, h = d.window_size()
    d.swipe(w // 2, h * 3 // 4, w // 2, h // 4, duration=0.5)
    time.sleep(0.3)
    d.swipe(w // 2, h // 4, w // 2, h * 3 // 4, duration=0.5)
    time.sleep(0.3)

    # 3. Fling
    try:
        d(scrollable=True).fling.vert.toBeginning()
        time.sleep(0.3)
    except Exception:
        pass

    capture(d, out, "scroll")
    d.app_stop(settings_pkg)
    time.sleep(0.3)
    d.press("home")
    time.sleep(0.5)


def step_app_lifecycle(d: u2.Device, out: Path, timeout: float) -> None:
    """
    Quản lý vòng đời ứng dụng:
    start, foreground check, background, stop, install info.
    """
    pkg = "com.android.settings"

    # Start
    d.app_start(pkg)
    ok = _wait_until(lambda: d.app_current().get("package") == pkg, timeout_s=10)
    assert ok, f"Settings không lên foreground: {d.app_current()}"
    capture(d, out, "app_start")

    # Info
    try:
        info = d.app_info(pkg)
        print(f"  → App info: version={info.get('versionName')}  "
              f"size={info.get('totalSize')}", flush=True)
    except Exception as e:
        print(f"  → app_info: {e}", flush=True)

    # Danh sách app đang chạy
    try:
        running = d.app_list_running()
        print(f"  → Running apps ({len(running)}): {running[:5]}", flush=True)
    except Exception:
        pass

    # Đưa về nền
    d.press("home")
    time.sleep(0.5)
    assert d.app_current().get("package") != pkg, "App vẫn ở foreground sau home"

    # Stop
    d.app_stop(pkg)
    time.sleep(0.3)

    capture(d, out, "app_lifecycle")


def step_rotation(d: u2.Device, out: Path, timeout: float) -> None:
    """Xoay màn hình và khôi phục."""
    original = d.orientation
    print(f"  → Orientation hiện tại: {original}", flush=True)

    try:
        d.set_orientation("l")   # landscape
        time.sleep(1.0)
        capture(d, out, "landscape")

        d.set_orientation("n")   # portrait (natural)
        time.sleep(1.0)
        capture(d, out, "portrait")
    except Exception as e:
        print(f"  → Xoay màn hình: {e}", flush=True)
    finally:
        try:
            d.set_orientation(original)
        except Exception:
            d.set_orientation("n")
        time.sleep(0.5)


def step_hardware_keys(d: u2.Device, out: Path, timeout: float) -> None:
    """Các phím cứng: Home, Back, Menu, Volume, Power, Recent."""
    for key in ["home", "back", "menu", "volume_up", "volume_down"]:
        try:
            d.press(key)
            time.sleep(0.2)
        except Exception as e:
            print(f"  → press({key}): {e}", flush=True)

    # Recent apps
    try:
        d.press("recent")
        time.sleep(0.8)
        capture(d, out, "recent_apps")
        d.press("back")
        time.sleep(0.4)
    except Exception as e:
        print(f"  → press(recent): {e}", flush=True)

    d.press("home")
    time.sleep(0.4)


def step_watchers(d: u2.Device, out: Path, timeout: float) -> None:
    """Đăng ký và kiểm tra watchers."""
    # Dọn watcher cũ
    d.watcher.stop()
    d.watcher.reset()

    # Đăng ký watcher click OK (API dùng text trực tiếp, không keyword)
    w = d.watcher
    w("w_ok").when("OK").click()
    w("w_allow").when("Allow").click()
    w("w_close").when("Close").click()

    # Bật watcher
    w.start(interval=2.0)
    time.sleep(1.0)

    # Kiểm tra danh sách
    try:
        wlist = d.watcher.list()
        print(f"  → Watchers: {wlist}", flush=True)
    except Exception:
        pass

    # Tắt sau khi dùng
    d.watcher.stop()
    d.watcher.reset()


def step_shell_and_adb(d: u2.Device, out: Path, timeout: float) -> None:
    """Chạy lệnh shell qua uiautomator2."""
    commands = [
        "getprop ro.product.model",
        "getprop ro.build.version.release",
        "wm size",
        "wm density",
        "dumpsys battery | grep level",
        "pm list packages -3 | head -5",
    ]
    shell_results = {}
    for cmd in commands:
        try:
            out_txt, err_txt = d.shell(cmd)
            shell_results[cmd] = out_txt.strip() or err_txt.strip()
        except Exception as e:
            shell_results[cmd] = f"ERROR: {e}"
        print(f"  $ {cmd}\n    → {shell_results[cmd]}", flush=True)

    _write(out / f"{_now_ms()}_shell_results.json",
           json.dumps(shell_results, ensure_ascii=False, indent=2))


def step_push_pull_file(d: u2.Device, out: Path, timeout: float) -> None:
    """Push file lên thiết bị và pull về."""
    remote_path = "/sdcard/u2_test.txt"
    local_push = out / "push_src.txt"
    local_pull = out / "pull_dst.txt"

    _write(local_push, "Hello from uiautomator2 file test!")

    try:
        d.push(str(local_push), remote_path)
        time.sleep(0.3)
        d.pull(remote_path, str(local_pull))
        assert local_pull.exists(), "File pull không tồn tại"
        content = local_pull.read_text()
        print(f"  → Pull content: {content!r}", flush=True)
        # Dọn file trên thiết bị
        d.shell(f"rm {remote_path}")
    except Exception as e:
        print(f"  → push/pull: {e}", flush=True)


def step_xpath_advanced(d: u2.Device, out: Path, timeout: float) -> None:
    """XPath nâng cao: nhiều điều kiện, descendant, ancestor."""
    d.press("home")
    time.sleep(0.5)

    queries = {
        "all_clickable": '//android.widget.TextView[@clickable="true"]',
        "enabled_buttons": '//android.widget.Button[@enabled="true"]',
        "img_desc": '//android.widget.ImageView[@content-desc!=""]',
        "deep_text": '//*[@text!=""]',
    }

    results = {}
    for name, xp in queries.items():
        try:
            els = d.xpath(xp).all()
            results[name] = len(els)
        except Exception as e:
            results[name] = str(e)

    print(f"  → XPath results: {results}", flush=True)
    _write(out / f"{_now_ms()}_xpath_results.json",
           json.dumps(results, ensure_ascii=False, indent=2))


def step_accessibility_info(d: u2.Device, out: Path, timeout: float) -> None:
    """Lấy thông tin accessibility của các phần tử."""
    d.press("home")
    time.sleep(0.5)

    try:
        elements = d(className="android.widget.TextView").all()
        data = []
        for el in elements[:10]:
            info = el.info
            data.append({
                "text": info.get("text", ""),
                "desc": info.get("contentDescription", ""),
                "bounds": str(info.get("bounds", {})),
                "clickable": info.get("clickable", False),
                "focusable": info.get("focusable", False),
            })
        _write(out / f"{_now_ms()}_accessibility.json",
               json.dumps(data, ensure_ascii=False, indent=2))
        print(f"  → Đã lấy info của {len(data)} TextView", flush=True)
    except Exception as e:
        print(f"  → accessibility_info: {e}", flush=True)


def step_screen_record(d: u2.Device, out: Path, timeout: float) -> None:
    """Quay màn hình trong 3 giây."""
    video_path = out / f"{_now_ms()}_record.mp4"
    try:
        with d.screenrecord(str(video_path)):
            time.sleep(3.0)
            d.press("home")
            time.sleep(0.5)
        if video_path.exists():
            size = video_path.stat().st_size
            print(f"  → Video: {video_path.name}  {size} bytes", flush=True)
    except Exception as e:
        print(f"  → screenrecord: {e}", flush=True)


def step_toast_and_overlay(d: u2.Device, out: Path, timeout: float) -> None:
    """Phát hiện Toast message bằng watcher."""
    def on_toast():
        # Ghi lại nếu toast xuất hiện (không ném lỗi)
        pass

    # Mở Settings và điều hướng để kích hoạt toast (nếu có)
    d.app_start("com.android.settings")
    time.sleep(1.5)
    capture(d, out, "toast_check")
    d.app_stop("com.android.settings")
    d.press("home")
    time.sleep(0.3)


def step_text_search_scroll(d: u2.Device, out: Path, timeout: float) -> None:
    """Cuộn để tìm text trong danh sách."""
    pkg = "com.android.settings"
    d.app_start(pkg)
    time.sleep(2.0)

    # Tìm "About" bằng cách cuộn
    target_texts = ["About phone", "About device", "About tablet", "About"]
    found = False
    for text in target_texts:
        try:
            el = d(text=text)
            if not el.exists(timeout=1):
                # Cuộn xuống để tìm
                scrollable = d(scrollable=True)
                if scrollable.exists(timeout=2):
                    scrollable.scroll.to(text=text)
            if el.exists(timeout=2):
                print(f"  → Tìm thấy: {text!r}", flush=True)
                found = True
                el.click()
                time.sleep(1.0)
                capture(d, out, "about_page")
                d.press("back")
                break
        except Exception:
            continue

    if not found:
        print("  → Không tìm thấy trang About", flush=True)

    d.app_stop(pkg)
    d.press("home")
    time.sleep(0.3)


# ═══════════════════════════════════════════════════════════════
#                          MAIN
# ═══════════════════════════════════════════════════════════════

ALL_STEPS = [
    ("screen_power",          step_screen_power),
    ("home_and_info",         step_home_and_info),
    ("screenshot_hierarchy",  step_screenshot_hierarchy),
    ("gestures",              step_gestures),
    ("multi_touch",           step_multi_touch),
    ("keyboard_input",        step_keyboard_input),
    ("clipboard",             step_clipboard),
    ("notification_panel",    step_notification_panel),
    ("quick_settings",        step_quick_settings),
    ("find_elements",         step_find_elements),
    ("wait_strategies",       step_wait_strategies),
    ("scroll_and_swipe",      step_scroll_and_swipe),
    ("app_lifecycle",         step_app_lifecycle),
    ("rotation",              step_rotation),
    ("hardware_keys",         step_hardware_keys),
    ("watchers",              step_watchers),
    ("shell_and_adb",         step_shell_and_adb),
    ("push_pull_file",        step_push_pull_file),
    ("xpath_advanced",        step_xpath_advanced),
    ("accessibility_info",    step_accessibility_info),
    ("screen_record",         step_screen_record),
    ("toast_and_overlay",     step_toast_and_overlay),
    ("text_search_scroll",    step_text_search_scroll),
]


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="uiautomator2 - kịch bản đầy đủ tính năng")
    ap.add_argument("--serial", default="", help="ADB serial hoặc ip:port")
    ap.add_argument("--adb", default=os.environ.get("ADB", "adb"))
    ap.add_argument("--artifacts", default="artifacts")
    ap.add_argument("--timeout", type=float, default=25.0)
    ap.add_argument("--connect-timeout", type=int, default=10)
    ap.add_argument("--u2-connect-timeout", type=float, default=60.0)
    ap.add_argument("--steps", default="", help="Chạy các bước cụ thể (tên, cách nhau bằng dấu phẩy)")
    ap.add_argument("--stop-on-fail", action="store_true", help="Dừng ngay khi có bước thất bại")
    args = ap.parse_args(argv)

    # ── Kết nối ADB ──────────────────────────────────────────────
    serial = args.serial.strip()
    if serial:
        _maybe_connect(args.adb, serial, args.connect_timeout)
    else:
        serials = _adb_devices(args.adb)
        if not serials:
            print("Không có thiết bị ADB. Chạy: adb devices", file=sys.stderr)
            return 2
        serial = serials[0]

    out_dir = Path(args.artifacts) / _safe_name(serial)
    _ensure_dir(out_dir)
    print(f"Thiết bị  : {serial}")
    print(f"Artifacts : {out_dir.resolve()}")

    # ── Kết nối u2 ───────────────────────────────────────────────
    print(f"\n[u2] Đang kết nối tới {serial} ...", flush=True)
    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(u2.connect, serial)
        try:
            d = fut.result(timeout=args.u2_connect_timeout)
        except FuturesTimeoutError as e:
            raise RuntimeError(f"u2.connect timeout sau {args.u2_connect_timeout}s") from e

    d.implicitly_wait(10.0)
    d.settings["wait_timeout"] = 20.0
    d.settings["operation_delay"] = (0, 0.1)

    # Bật watchers cơ bản (API dùng text trực tiếp, không keyword)
    w = d.watcher
    w("g_ok").when("OK").click()
    w("g_allow").when("Allow").click()
    w.start()

    # ── Lọc bước cần chạy ────────────────────────────────────────
    selected_names = {s.strip() for s in args.steps.split(",") if s.strip()}
    steps_to_run = [
        (name, fn) for name, fn in ALL_STEPS
        if not selected_names or name in selected_names
    ]

    runner = Runner(d=d, out=out_dir, timeout=args.timeout)

    try:
        for name, fn in steps_to_run:
            ok = runner.run(name, lambda f=fn: f(d, out_dir, args.timeout))
            if not ok and args.stop_on_fail:
                print("\n[u2] Dừng do --stop-on-fail", file=sys.stderr)
                break
    finally:
        d.watcher.stop()
        d.watcher.reset()

    summary = runner.report()
    all_passed = summary["failed"] == 0
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())