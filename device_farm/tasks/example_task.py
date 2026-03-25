"""
example_task.py — Demo task: launch an app, wait for a UI element, tap it.

Usage:
  from tasks.example_task import example_task
  task = Task(fn=example_task, name="example", priority=5)
  queue.put(task)

The task function receives a DeviceClient instance and may use any of its APIs.
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from runtime.core import DeviceClient

log = logging.getLogger(__name__)


def example_task(device: "DeviceClient") -> dict:
   
    serial = device.serial
    log.info(f"[{serial}] example_task started")

    chrome_pkg = "com.android.chrome"
    log.info(f"[{serial}] Launching Chrome via launch_app({chrome_pkg})")
    device.launch_app(chrome_pkg)

    time.sleep(2.0)
    frame = device.take_screenshot()
    if frame:
        log.info(f"[{serial}] Got frame: {len(frame)} bytes")
    else:
        log.warning(f"[{serial}] No frame available")

    log.info(f"[{serial}] example_task completed")
    return {
        "serial": serial,
        "model": device.model,
        "current_app": "",
        "frame_size": len(frame) if frame else 0,
    }


def launch_app_task(package: str):
    """
    Factory: returns a task function that launches a specific app.
    Usage: Task(fn=launch_app_task("com.example.myapp"), name="launch_app")
    """
    def _task(device: "DeviceClient") -> dict:
        serial = device.serial
        log.info(f"[{serial}] Launching {package}")

        if not device.u2:
            raise RuntimeError("uiautomator2 not available")

        device.u2.app_start(package)

        # Wait for app to appear in foreground
        pid = device.u2.app_wait(package, front=True, timeout=20.0)
        if pid == 0:
            raise TimeoutError(f"App {package} did not come to foreground within 20s")

        log.info(f"[{serial}] {package} is running (pid={pid})")
        return {"package": package, "pid": pid}

    _task.__name__ = f"launch_{package}"
    return _task


def screenshot_task(device: "DeviceClient") -> dict:
    """Grab a screenshot and return its size. Useful for health checks."""
    frame = device.take_screenshot()
    return {
        "serial": device.serial,
        "has_frame": frame is not None,
        "frame_bytes": len(frame) if frame else 0,
    }


def demo_u2_task(device: "DeviceClient") -> dict:
   
    serial = device.serial
    d = device.u2
    if not d:
        log.warning(f"[{serial}] demo_u2_task: uiautomator2 (U2CompatServer) not available, skipping U2-specific steps")
        return {
            "serial": serial,
            "info": {},
            "current_app": {"error": "u2_unavailable"},
            "page_source_preview": "",
            "found_textview": False,
            "screenshot_bytes": 0,
        }

    log.info(f"[{serial}] demo_u2_task started")

    # 0. Mở Chrome (Google) qua agent rồi cho U2 điều khiển
    chrome_pkg = "com.android.chrome"
    try:
        log.info(f"[{serial}] launch_app({chrome_pkg})")
        device.launch_app(chrome_pkg)
        time.sleep(3.0)
    except Exception as exc:
        log.warning(f"[{serial}] launch_app({chrome_pkg}) failed: {exc}")

    # 1. Device info từ U2 (chịu lỗi/tunnel rớt)
    try:
        info = d.device_info
        log.info(f"[{serial}] device_info: {info}")
    except Exception as exc:
        info = {}
        log.warning(f"[{serial}] device_info failed: {exc}")

    # 1.1 Tính kích thước màn hình (fallback mặc định nếu thiếu info)
    try:
        w = int(info.get("width") or info.get("display", {}).get("width") or 1080)
        h = int(info.get("height") or info.get("display", {}).get("height") or 1920)
    except Exception:
        w, h = 1080, 1920
    # 1.2 Tap vào thanh search/url của Chrome theo toạ độ rồi search "tin tức công nghệ"
    try:
        # Tap gần đỉnh màn hình để focus omnibox
        ox = w // 2
        oy = int(h * 0.10)
        log.info(f"[{serial}] tap omnibox approx at ({ox},{oy})")
        device.tap(ox, oy)
        time.sleep(1.0)
    except Exception as exc:
        log.warning(f"[{serial}] tap omnibox failed: {exc}")

    search_text = "tin tức công nghệ hôm nay"
    try:
        log.info(f"[{serial}] Trying to send_keys({search_text!r}) via U2")
        d.send_keys(search_text)
        # Nhấn enter bằng accessibility key event để submit search
        device.key("enter")
        log.info(f"[{serial}] Submitted search with ENTER key")
    except Exception as exc:
        log.warning(f"[{serial}] search via send_keys failed: {exc}")

    # Đợi kết quả search load
    time.sleep(4.0)

    # 1.3 Click vào một kết quả ở giữa màn hình
    try:
        rx = w // 2
        ry = int(h * 0.40)
        log.info(f"[{serial}] tap result approx at ({rx},{ry})")
        device.tap(rx, ry)
        time.sleep(4.0)
    except Exception as exc:
        log.warning(f"[{serial}] tap result failed: {exc}")

    # 1.4 Lướt xuống cuối trang bằng vài lần swipe
    try:
        sx = w // 2
        sy1 = int(h * 0.80)
        sy2 = int(h * 0.20)
        for i in range(3):
            log.info(f"[{serial}] swipe scroll #{i+1}: ({sx},{sy1})→({sx},{sy2})")
            device.swipe(sx, sy1, sx, sy2, duration_ms=600)
            time.sleep(1.0)
    except Exception as exc:
        log.warning(f"[{serial}] scroll swipes failed: {exc}")

    # 2. App hiện tại (foreground) theo U2
    try:
        cur = d.app_current()
        log.info(f"[{serial}] app_current: {cur}")
    except Exception as exc:
        cur = {"error": str(exc)}
        log.warning(f"[{serial}] app_current failed: {exc}")

    # 3. Lấy page_source (UI hierarchy) — chỉ log prefix để không spam
    try:
        src = d.page_source()
        src_preview = (src[:200] + "...") if len(src) > 200 else src
        log.info(f"[{serial}] page_source preview: {src_preview!r}")
    except Exception as exc:
        src_preview = ""
        log.warning(f"[{serial}] page_source failed: {exc}")

    # 4. Thử tìm bất kỳ TextView nào bằng xpath (chịu lỗi)
    try:
        tv = d.xpath("//android.widget.TextView")
        found_tv = tv.wait(timeout=5.0)
        log.info(f"[{serial}] xpath('//android.widget.TextView').wait(): {found_tv}")
    except Exception as exc:
        found_tv = False
        log.warning(f"[{serial}] xpath('//android.widget.TextView') failed: {exc}")

    frame = device.take_screenshot()
    if frame:
        log.info(f"[{serial}] screenshot bytes={len(frame)}")
    else:
        log.warning(f"[{serial}] No frame available from take_screenshot()")

    log.info(f"[{serial}] demo_u2_task completed")
    return {
        "serial": serial,
        "info": info,
        "current_app": cur,
        "page_source_preview": src_preview,
        "found_textview": found_tv,
        "screenshot_bytes": len(frame) if frame else 0,
    }
