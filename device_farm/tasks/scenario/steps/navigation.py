"""Step handlers: launch_app, open_url, key, scroll_down, scroll_to."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict

from tasks.scenario.steps import register_step
from tasks.scenario.context import ScenarioContext

log = logging.getLogger(__name__)


@register_step("launch_app")
def handle_launch_app(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    app_field = step.get("app")
    app_pkg = ""
    app_component = ""
    if isinstance(app_field, dict):
        app_pkg = str(app_field.get("package") or app_field.get("app_package") or "").strip()
        app_component = str(app_field.get("component") or app_field.get("activity") or "").strip()
    elif isinstance(app_field, str):
        app_pkg = app_field.strip()

    raw_pkg = str(step.get("package") or step.get("app_package") or step.get("appPackage") or app_pkg or "").strip()
    raw_component = str(step.get("component") or step.get("activity") or step.get("title") or app_component or "").strip()
    pkg = raw_pkg
    component = ""

    if pkg and "/" in pkg:
        component = pkg
        pkg = pkg.split("/", 1)[0].strip()
    if raw_component and "/" in raw_component:
        component = raw_component
        if not pkg:
            pkg = raw_component.split("/", 1)[0].strip()
    elif raw_component and not pkg:
        pkg = raw_component

    if not pkg:
        result["ok"] = False
        result["message"] = "launch_app: empty package/component"
    else:
        try:
            sc.device.launch_app(pkg, component=component or None)
            launch_wait = float(step.get("wait_after", 2.0) or 2.0)
            time.sleep(launch_wait)
            log.info(f"[{sc.serial}] launch_app {pkg}: waited {launch_wait}s")
            _u2_poll_start = time.monotonic()
            while time.monotonic() - _u2_poll_start < 8.0:
                if getattr(sc.device, "_u2", None) is not None:
                    break
                time.sleep(0.5)
            if getattr(sc.device, "_u2", None) is None:
                log.warning(f"[{sc.serial}] launch_app {pkg}: u2 not ready after 8s poll")
        except Exception as exc:
            result["ok"] = False
            result["message"] = f"launch_app({pkg}) failed: {exc}"


@register_step("open_url")
def handle_open_url(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    url = str(step.get("url") or "").strip()
    if not url:
        result["ok"] = False
        result["message"] = "open_url: empty url"
    else:
        pkg = (step.get("package") or "").strip() or "com.android.chrome"
        try:
            sc.device.open_url(url, package=pkg)
        except Exception as exc:
            result["ok"] = False
            result["message"] = f"open_url failed: {exc}"


@register_step("key")
def handle_key(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    key = str(step.get("key") or "")
    if not key:
        result["ok"] = False
        result["message"] = "key: empty key"
    else:
        try:
            sc.device.key(key)
        except Exception as exc:
            result["ok"] = False
            result["message"] = f"key({key}) failed: {exc}"


@register_step("scroll_down")
def handle_scroll_down(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    try:
        repeats = int(step.get("repeats", 1) or 1)
    except Exception:
        repeats = 1
    try:
        start_y_ratio = float(step.get("start_y_ratio", 0.65))
    except Exception:
        start_y_ratio = 0.65
    try:
        end_y_ratio = float(step.get("end_y_ratio", 0.47))
    except Exception:
        end_y_ratio = 0.47
    try:
        duration_ms = int(step.get("duration_ms", 520) or 520)
    except Exception:
        duration_ms = 520
    try:
        pause_seconds = float(step.get("pause_seconds", 0.6) or 0.6)
    except Exception:
        pause_seconds = 0.6
    try:
        start_x_ratio = float(step.get("start_x_ratio", 0.5) or 0.5)
    except Exception:
        start_x_ratio = 0.5

    start_y_ratio = min(0.95, max(0.55, start_y_ratio))
    end_y_ratio = min(0.75, max(0.1, end_y_ratio))
    if end_y_ratio >= start_y_ratio:
        end_y_ratio = max(0.1, start_y_ratio - 0.22)

    start_x_ratio = min(0.95, max(0.05, start_x_ratio))
    sx = int(sc.w * start_x_ratio)
    sy1 = int(sc.h * start_y_ratio)
    sy2 = int(sc.h * end_y_ratio)
    failed = False
    for i in range(max(1, repeats)):
        log.info(f"[{sc.serial}] scroll swipe #{i + 1}: ({sx},{sy1})→({sx},{sy2})")
        try:
            sc.device.swipe(sx, sy1, sx, sy2, duration_ms=duration_ms)
        except Exception as exc:
            result["ok"] = False
            result["message"] = f"swipe scroll #{i + 1} failed: {exc}"
            failed = True
            break
        time.sleep(max(0.1, pause_seconds))
    if not failed:
        result["ok"] = True


@register_step("scroll_to")
def handle_scroll_to(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    by = str(step.get("by") or "text")
    value = str(step.get("value") or "").strip()
    direction = str(step.get("direction", "down") or "down")
    max_swipes = int(step.get("max_swipes", 5) or 5)
    if not value:
        result["ok"] = False
        result["message"] = "scroll_to: empty value"
        return

    sx = sc.w // 2
    if direction == "up":
        sy1, sy2 = int(sc.h * 0.3), int(sc.h * 0.7)
    else:
        sy1, sy2 = int(sc.h * 0.7), int(sc.h * 0.3)
    found = False
    swipes_done = 0
    for i in range(max_swipes):
        try:
            u2 = sc.device.u2
            if u2 is not None and u2.find_element(by, value, timeout=0) is not None:
                found = True
                swipes_done = i
                break
        except Exception:
            pass
        try:
            sc.device.swipe(sx, sy1, sx, sy2, duration_ms=500)
        except Exception:
            pass
        time.sleep(0.3)
        swipes_done = i + 1
    if not found:
        result["ok"] = False
        result["message"] = f"scroll_to {by}={value!r} not found after {max_swipes} swipes"
    else:
        result["message"] = f"scroll_to found {by}={value!r} after {swipes_done} swipe(s)"
