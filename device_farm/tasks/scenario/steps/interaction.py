"""Step handlers: tap, tap_ratio, tap_position, tap_selector, swipe_ratio, double_tap, pinch, drag, take_screenshot."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict

from tasks.scenario.steps import register_step
from tasks.scenario.context import ScenarioContext
from tasks.scenario.utils import (
    _execute_tap, _get_implicit_wait_config, _decode_element_image,
    _auto_dismiss_popup, _CONTAINER_CLASSES,
)

log = logging.getLogger(__name__)


@register_step("tap")
def handle_tap(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    selector = step.get("selector") or {}
    fallback = step.get("fallback") or {}
    screen_ctx = step.get("screen") or {}
    sel_by = str(selector.get("by") or "") or None
    sel_value = str(selector.get("value") or "").strip() or None
    fallback_rx = fallback.get("rx")
    fallback_ry = fallback.get("ry")
    tap_timeout = float(step.get("timeout", 4.0) or 4.0)

    has_real_selector = (
        sel_by and sel_value
        and not (sel_by == "class name" and sel_value in _CONTAINER_CLASSES)
    )

    # Visual Anchoring
    screen_screenshot_b64 = screen_ctx.get("screenshot")
    if sc.visual_anchor_enabled and screen_screenshot_b64 and not has_real_selector:
        try:
            from runtime.visual_anchor import wait_for_screen_match, _b64_to_bytes
            recorded_jpeg = _b64_to_bytes(screen_screenshot_b64)
            matched, ssim = wait_for_screen_match(
                sc.device.take_screenshot, recorded_jpeg,
                timeout=sc.va_screen_timeout, poll=sc.va_screen_poll,
                ssim_threshold=sc.va_ssim_threshold,
            )
            result["screen_ssim"] = round(ssim, 3)
            if not matched:
                log.info(f"[{sc.serial}] step#{idx+1} screen SSIM={ssim:.3f} < {sc.va_ssim_threshold} (proceeding)")
                result["screen_mismatch"] = True
        except ImportError:
            pass
        except Exception as exc:
            log.debug(f"[{sc.serial}] screen verify error: {exc}")

    elem_img_bytes = _decode_element_image(screen_ctx.get("element_image"))
    ss_anchor = screen_ctx.get("screenshot_anchor")

    iw_timeout, iw_poll = _get_implicit_wait_config(step, sc.scenario_iw_config)
    ok, msg, tap_bounds = _execute_tap(
        sc.device, by=sel_by, value=sel_value,
        fallback_rx=fallback_rx, fallback_ry=fallback_ry,
        timeout=tap_timeout, retries=1,
        implicit_wait_timeout=iw_timeout, implicit_wait_poll=iw_poll,
        element_image=elem_img_bytes, image_threshold=sc.va_image_threshold,
        screenshot_anchor=ss_anchor,
    )

    # Auto-dismiss popup on failure
    if not ok:
        now_t = time.monotonic()
        if now_t - sc.last_popup_t >= 5.0:
            dismissed = _auto_dismiss_popup(sc.device)
            sc.last_popup_t = time.monotonic()
            if dismissed:
                result["popup_dismissed"] = True
                ok, msg, tap_bounds = _execute_tap(
                    sc.device, by=sel_by, value=sel_value,
                    fallback_rx=fallback_rx, fallback_ry=fallback_ry,
                    timeout=tap_timeout, retries=1,
                    implicit_wait_timeout=iw_timeout, implicit_wait_poll=iw_poll,
                    element_image=elem_img_bytes, image_threshold=sc.va_image_threshold,
                    screenshot_anchor=ss_anchor,
                )

    result["ok"] = ok
    if msg:
        result["message"] = msg
        if "image match" in msg:
            result["method"] = "image_match"
        elif "fallback position" in msg:
            result["method"] = "fallback_position"
        elif msg.startswith("healed "):
            result["method"] = "healed_selector"
        elif "selector" in msg:
            result["method"] = "selector"
    if screen_ctx:
        result["screen_context"] = screen_ctx
    if tap_bounds:
        result["_bounds"] = tap_bounds

    # Self-healing hook
    if ok:
        try:
            from runtime.selector_healer import try_heal_selector, HEALING_ENABLED
            if HEALING_ENABLED:
                method = result.get("method", "")
                if method == "healed_selector":
                    import re as _re
                    msg_val = result.get("message", "")
                    m = _re.match(r"healed (\S+)=(.+?) \(was", msg_val)
                    if m:
                        result["healed_selector"] = {"by": m.group(1), "value": m.group(2).strip("'")}
                elif method == "image_match" and tap_bounds:
                    healed = try_heal_selector(sc.device, step, tap_bounds)
                    if healed:
                        result["healed_selector"] = healed
        except Exception as exc:
            log.debug("[%s] selector healing failed: %s", sc.serial, exc)

    if ok:
        time.sleep(0.3)


@register_step("tap_ratio")
def handle_tap_ratio(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    try:
        rx = float(step.get("x", 0.5) or 0.5)
        ry = float(step.get("y", 0.5) or 0.5)
    except Exception:
        rx, ry = 0.5, 0.5
    x = max(0, min(sc.w - 1, int(rx * sc.w)))
    y = max(0, min(sc.h - 1, int(ry * sc.h)))
    try:
        sc.device.tap(x, y)
        time.sleep(0.3)
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"tap_ratio at ({x},{y}) failed: {exc}"


@register_step("tap_position")
def handle_tap_position(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    pos = str(step.get("pos") or "middle_center")
    if pos == "top_center":
        rx, ry = 0.5, 0.1
    elif pos == "search_bar":
        rx, ry = 0.5, 0.18
    elif pos == "bottom_center":
        rx, ry = 0.5, 0.9
    else:
        rx, ry = 0.5, 0.5
    x = max(0, min(sc.w - 1, int(rx * sc.w)))
    y = max(0, min(sc.h - 1, int(ry * sc.h)))
    try:
        sc.device.tap(x, y)
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"tap_position {pos} at ({x},{y}) failed: {exc}"


@register_step("swipe_ratio")
def handle_swipe_ratio(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    try:
        rx1 = float(step.get("x1", 0.5)); ry1 = float(step.get("y1", 0.5))
        rx2 = float(step.get("x2", 0.5)); ry2 = float(step.get("y2", 0.5))
        duration_ms = int(step.get("duration_ms", 300) or 300)
    except Exception:
        rx1, ry1, rx2, ry2, duration_ms = 0.5, 0.5, 0.5, 0.5, 300
    x1 = max(0, min(sc.w - 1, int(rx1 * sc.w)))
    y1 = max(0, min(sc.h - 1, int(ry1 * sc.h)))
    x2 = max(0, min(sc.w - 1, int(rx2 * sc.w)))
    y2 = max(0, min(sc.h - 1, int(ry2 * sc.h)))
    try:
        sc.device.swipe(x1, y1, x2, y2, duration_ms=duration_ms)
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"swipe_ratio failed: {exc}"


@register_step("tap_selector")
def handle_tap_selector(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    by = str(step.get("by") or "text")
    value = str(step.get("value") or "").strip()
    fallback_rx = step.get("fallback_rx")
    fallback_ry = step.get("fallback_ry")
    sel_timeout = float(step.get("timeout", 8.0) or 8.0)
    if not value:
        result["ok"] = False
        result["message"] = "tap_selector: empty value"
        return

    elem_img_bytes = _decode_element_image(step.get("element_image"))
    iw_timeout, iw_poll = _get_implicit_wait_config(step, sc.scenario_iw_config)
    ok, msg, tap_bounds = _execute_tap(
        sc.device, by=by, value=value,
        fallback_rx=fallback_rx, fallback_ry=fallback_ry,
        timeout=sel_timeout, retries=1,
        implicit_wait_timeout=iw_timeout, implicit_wait_poll=iw_poll,
        element_image=elem_img_bytes, image_threshold=sc.va_image_threshold,
    )

    if not ok:
        now_t = time.monotonic()
        if now_t - sc.last_popup_t >= 5.0:
            dismissed = _auto_dismiss_popup(sc.device)
            sc.last_popup_t = time.monotonic()
            if dismissed:
                result["popup_dismissed"] = True
                ok, msg, tap_bounds = _execute_tap(
                    sc.device, by=by, value=value,
                    fallback_rx=fallback_rx, fallback_ry=fallback_ry,
                    timeout=sel_timeout, retries=1,
                    implicit_wait_timeout=iw_timeout, implicit_wait_poll=iw_poll,
                    element_image=elem_img_bytes, image_threshold=sc.va_image_threshold,
                )
    result["ok"] = ok
    if msg:
        result["message"] = msg
        if "image match" in msg:
            result["method"] = "image_match"
    if tap_bounds:
        result["_bounds"] = tap_bounds
    if ok:
        time.sleep(0.3)


@register_step("double_tap")
def handle_double_tap(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    try:
        rx = step.get("rx")
        ry = step.get("ry")
        if rx is not None and ry is not None:
            px = int(float(rx) * sc.w)
            py = int(float(ry) * sc.h)
        else:
            px = int(step.get("x", sc.w // 2))
            py = int(step.get("y", sc.h // 2))
        sc.device.double_tap(px, py)
        wait_after = float(step.get("wait_after", 0.5) or 0.5)
        if wait_after > 0:
            time.sleep(wait_after)
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"double_tap failed: {exc}"


@register_step("pinch")
def handle_pinch(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    try:
        rx = step.get("rx")
        ry = step.get("ry")
        if rx is not None and ry is not None:
            cx = int(float(rx) * sc.w)
            cy = int(float(ry) * sc.h)
        else:
            cx = int(step.get("cx", sc.w // 2))
            cy = int(step.get("cy", sc.h // 2))
        scale = float(step.get("scale", 0.5) or 0.5)
        duration_ms = int(step.get("duration_ms", 400) or 400)
        sc.device.pinch(cx, cy, scale, duration_ms)
        time.sleep(0.4)
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"pinch failed: {exc}"


@register_step("drag")
def handle_drag(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    try:
        if step.get("rx1") is not None:
            x1 = int(float(step.get("rx1", 0)) * sc.w)
            y1 = int(float(step.get("ry1", 0)) * sc.h)
            x2 = int(float(step.get("rx2", 0)) * sc.w)
            y2 = int(float(step.get("ry2", 0)) * sc.h)
        else:
            x1 = int(step.get("x1", 0))
            y1 = int(step.get("y1", 0))
            x2 = int(step.get("x2", 0))
            y2 = int(step.get("y2", 0))
        duration_ms = int(step.get("duration_ms", 1000) or 1000)
        sc.device.drag(x1, y1, x2, y2, duration_ms)
        time.sleep(0.4)
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"drag failed: {exc}"


@register_step("take_screenshot")
def handle_take_screenshot(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    import base64
    try:
        frame = sc.device.capture_screenshot()
        if frame is None:
            result["ok"] = False
            result["message"] = "take_screenshot: no frame available"
        else:
            save_path = step.get("save_path")
            if save_path:
                import os
                os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
                with open(save_path, "wb") as f:
                    f.write(frame)
            result["screenshot"] = base64.b64encode(frame).decode()
            log.info(f"[{sc.serial}] take_screenshot: {len(frame)} bytes")
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"take_screenshot failed: {exc}"


