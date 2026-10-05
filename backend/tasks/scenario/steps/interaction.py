"""Step handlers: tap, tap_ratio, tap_position, tap_selector, swipe_ratio, double_tap, pinch, drag, take_screenshot."""
from __future__ import annotations

import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Dict

from tasks.scenario.steps import register_step
from tasks.scenario.context import ScenarioContext
from tasks.scenario.utils import (
    _execute_tap, _get_implicit_wait_config, _decode_element_image,
    _auto_dismiss_popup, _CONTAINER_CLASSES, resolve_step_selector_fields,
    _retry_find_element,
)

log = logging.getLogger(__name__)


def _cancelled(sc: ScenarioContext) -> bool:
    return sc.cancel_event is not None and sc.cancel_event.is_set()


def _mark_cancelled(result: Dict[str, Any], message: str) -> None:
    result["ok"] = False
    result["message"] = message
    result["cancelled"] = True


def _wait_or_cancel(sc: ScenarioContext, seconds: float) -> bool:
    if seconds <= 0:
        return _cancelled(sc)
    if sc.cancel_event is not None:
        return bool(sc.cancel_event.wait(seconds))
    time.sleep(seconds)
    return False


_BOUNDS_RE = re.compile(r"^\[(\d+),(\d+)\]\[(\d+),(\d+)\]$")


def _bounds_tuple(raw: str) -> tuple[int, int, int, int] | None:
    match = _BOUNDS_RE.match(str(raw or ""))
    if match is None:
        return None
    left, top, right, bottom = (int(group) for group in match.groups())
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def _bounds_center(raw: str) -> tuple[int, int] | None:
    bounds = _bounds_tuple(raw)
    if bounds is None:
        return None
    left, top, right, bottom = bounds
    return (left + right) // 2, (top + bottom) // 2


def _xml_attr_name(raw: Any) -> str:
    attr = str(raw or "content-desc").strip()
    if attr in {"description", "content_desc", "accessibility id", "accessibility_id"}:
        return "content-desc"
    if attr in {"className", "class name"}:
        return "class"
    if attr == "resourceId":
        return "resource-id"
    return attr


@register_step("tap_xml_match")
def handle_tap_xml_match(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    attr = _xml_attr_name(step.get("attr") or step.get("by"))
    contains = str(step.get("contains") or step.get("value") or "").strip()
    equals = str(step.get("equals") or "").strip()
    timeout = float(step.get("timeout", 6.0) or 6.0)
    poll = float(step.get("poll", 0.25) or 0.25)
    require_clickable = bool(step.get("clickable", True))

    if not contains and not equals:
        result["ok"] = False
        result["message"] = "tap_xml_match: missing contains/equals"
        return

    deadline = time.monotonic() + max(0.1, timeout)
    last_error = ""
    while time.monotonic() < deadline:
        if _cancelled(sc):
            _mark_cancelled(result, "tap_xml_match: cancelled by user")
            return
        try:
            xml = sc.device.hierarchy_xml(force_refresh=True) or ""
            root = ET.fromstring(xml)
            for node in root.iter():
                if require_clickable and (node.get("clickable") or "").lower() != "true":
                    continue
                value = node.get(attr) or ""
                if equals and value != equals:
                    continue
                if contains and contains not in value:
                    continue
                raw_bounds = node.get("bounds") or ""
                center = _bounds_center(raw_bounds)
                if center is None:
                    continue
                x, y = center
                sc.device.tap(x, y)
                result["message"] = (
                    f"tap_xml_match {attr} contains={contains!r} "
                    f"tap=({x},{y}) bounds={raw_bounds}"
                )
                left, top, right, bottom = _bounds_tuple(raw_bounds) or (x, y, x, y)
                result["_bounds"] = {"left": left, "top": top, "right": right, "bottom": bottom}
                if _wait_or_cancel(sc, 0.3):
                    _mark_cancelled(result, "tap_xml_match: cancelled by user")
                return
        except Exception as exc:
            last_error = str(exc)
        if sc.cancel_event is not None:
            sc.cancel_event.wait(poll)
        else:
            time.sleep(poll)

    result["ok"] = False
    needle = f"{attr} contains={contains!r}" if contains else f"{attr} equals={equals!r}"
    suffix = f": {last_error}" if last_error else ""
    result["message"] = f"tap_xml_match: {needle} not found{suffix}"


@register_step("tap")
def handle_tap(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    spec, sel_by, sel_value, (fallback_rx, fallback_ry) = resolve_step_selector_fields(step)
    screen_ctx = step.get("screen") or {}
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
        screenshot_anchor=ss_anchor, spec=spec,
        cancel_event=sc.cancel_event,
    )

    # Auto-dismiss popup on failure
    if not ok:
        if _cancelled(sc):
            _mark_cancelled(result, "tap: cancelled by user")
            return
        now_t = time.monotonic()
        if now_t - sc.last_popup_t >= 5.0:
            dismissed = _auto_dismiss_popup(sc.device)
            sc.last_popup_t = time.monotonic()
            if dismissed:
                if _cancelled(sc):
                    _mark_cancelled(result, "tap: cancelled by user")
                    return
                result["popup_dismissed"] = True
                ok, msg, tap_bounds = _execute_tap(
                    sc.device, by=sel_by, value=sel_value,
                    fallback_rx=fallback_rx, fallback_ry=fallback_ry,
                    timeout=tap_timeout, retries=1,
                    implicit_wait_timeout=iw_timeout, implicit_wait_poll=iw_poll,
                    element_image=elem_img_bytes, image_threshold=sc.va_image_threshold,
                    screenshot_anchor=ss_anchor, spec=spec,
                    cancel_event=sc.cancel_event,
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
        if _wait_or_cancel(sc, 0.3):
            _mark_cancelled(result, "tap: cancelled by user")


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
        if _wait_or_cancel(sc, 0.3):
            _mark_cancelled(result, "tap_ratio: cancelled by user")
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
        if _cancelled(sc):
            _mark_cancelled(result, "tap_position: cancelled by user")
            return
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
        if _cancelled(sc):
            _mark_cancelled(result, "swipe_ratio: cancelled by user")
            return
        sc.device.swipe(x1, y1, x2, y2, duration_ms=duration_ms)
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"swipe_ratio failed: {exc}"


@register_step("tap_selector")
def handle_tap_selector(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    spec, by, value, (fallback_rx, fallback_ry) = resolve_step_selector_fields(step)
    sel_timeout = float(step.get("timeout", 8.0) or 8.0)
    if spec is None or spec.is_empty():
        result["ok"] = False
        result["message"] = "tap_selector: empty selector"
        return

    elem_img_bytes = _decode_element_image(step.get("element_image"))
    iw_timeout, iw_poll = _get_implicit_wait_config(step, sc.scenario_iw_config)
    ok, msg, tap_bounds = _execute_tap(
        sc.device, by=by, value=value,
        fallback_rx=fallback_rx, fallback_ry=fallback_ry,
        timeout=sel_timeout, retries=1,
        implicit_wait_timeout=iw_timeout, implicit_wait_poll=iw_poll,
        element_image=elem_img_bytes, image_threshold=sc.va_image_threshold,
        spec=spec,
        cancel_event=sc.cancel_event,
    )

    if not ok:
        if _cancelled(sc):
            _mark_cancelled(result, "tap_selector: cancelled by user")
            return
        now_t = time.monotonic()
        if now_t - sc.last_popup_t >= 5.0:
            dismissed = _auto_dismiss_popup(sc.device)
            sc.last_popup_t = time.monotonic()
            if dismissed:
                if _cancelled(sc):
                    _mark_cancelled(result, "tap_selector: cancelled by user")
                    return
                result["popup_dismissed"] = True
                ok, msg, tap_bounds = _execute_tap(
                    sc.device, by=by, value=value,
                    fallback_rx=fallback_rx, fallback_ry=fallback_ry,
                    timeout=sel_timeout, retries=1,
                    implicit_wait_timeout=iw_timeout, implicit_wait_poll=iw_poll,
                    element_image=elem_img_bytes, image_threshold=sc.va_image_threshold,
                    spec=spec,
                    cancel_event=sc.cancel_event,
                )
    result["ok"] = ok
    if msg:
        result["message"] = msg
        if "image match" in msg:
            result["method"] = "image_match"
    if tap_bounds:
        result["_bounds"] = tap_bounds
    if ok:
        if _wait_or_cancel(sc, 0.3):
            _mark_cancelled(result, "tap_selector: cancelled by user")


@register_step("long_tap_selector")
def handle_long_tap_selector(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    from services.scenario_selector import selector_summary

    spec, by, value, _ = resolve_step_selector_fields(step)
    duration_ms = int(step.get("duration_ms", 800) or 800)
    if spec is None or spec.is_empty():
        result["ok"] = False
        result["message"] = "long_tap_selector: empty selector"
        return
    try:
        u2 = sc.device.u2
        if u2 is None:
            sc.device.ensure_u2_healthy()
            u2 = sc.device.u2
        if u2 is None:
            raise RuntimeError("u2 not available")
        iw_timeout, iw_poll = _get_implicit_wait_config(step, sc.scenario_iw_config)
        found = _retry_find_element(
            u2, by, value, timeout=iw_timeout, poll=iw_poll, spec=spec,
            device=sc.device, cancel_event=sc.cancel_event,
        )
        if _cancelled(sc):
            _mark_cancelled(result, "long_tap_selector: cancelled by user")
            return
        if found is None:
            raise RuntimeError(f"element not visible: {selector_summary(spec)}")
        if hasattr(u2, "find_element_with_bounds_spec"):
            info = u2.find_element_with_bounds_spec(spec)
        elif hasattr(u2, "find_element_with_bounds"):
            info = u2.find_element_with_bounds(by, value)
        else:
            info = None
        bounds = (info or {}).get("bounds") if isinstance(info, dict) else None
        if not bounds:
            raise RuntimeError(f"element bounds not found: {selector_summary(spec)}")
        cx = (bounds.get("left", 0) + bounds.get("right", 0)) // 2
        cy = (bounds.get("top", 0) + bounds.get("bottom", 0)) // 2
        if _cancelled(sc):
            _mark_cancelled(result, "long_tap_selector: cancelled by user")
            return
        u2.long_click(cx, cy, duration_ms / 1000.0)
        result["message"] = f"long_tap_selector {selector_summary(spec)} ({duration_ms}ms)"
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"long_tap_selector failed: {exc}"


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
            if _wait_or_cancel(sc, wait_after):
                _mark_cancelled(result, "double_tap: cancelled by user")
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
        if _cancelled(sc):
            _mark_cancelled(result, "pinch: cancelled by user")
            return
        sc.device.pinch(cx, cy, scale, duration_ms)
        if _wait_or_cancel(sc, 0.4):
            _mark_cancelled(result, "pinch: cancelled by user")
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
        if _cancelled(sc):
            _mark_cancelled(result, "drag: cancelled by user")
            return
        sc.device.drag(x1, y1, x2, y2, duration_ms)
        if _wait_or_cancel(sc, 0.4):
            _mark_cancelled(result, "drag: cancelled by user")
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"drag failed: {exc}"


@register_step("take_screenshot")
def handle_take_screenshot(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    """Store the frame and report where it went, rather than inlining the bytes.

    This used to put base64 straight into the step result, which then rode the
    whole Temporal path: activity result -> step_results -> every continue_as_new
    payload -> finalize. A measured 499KB JPEG is ~665KB once base64'd, against
    Temporal's 256KB warn / 2MB error blob limits — three of these steps in one
    scenario was enough to kill the workflow.

    The pre/post capture path (services/execution/capture_service.py) already
    stores to object storage and reports a URL; this brings the explicit step in
    line with it, and readers already accept a URL string here
    (api/routes/executions.py::_normalize_artifact_url).
    """
    try:
        frame = sc.device.capture_screenshot()
        if frame is None:
            result["ok"] = False
            result["message"] = "take_screenshot: no frame available"
            return

        save_path = step.get("save_path")
        if save_path:
            os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(frame)

        from services import capture_store
        from services.execution.capture_service import _append_artifact
        from services.execution.epic06_capture_adapter import _paths

        prefix, capture_dir, minio_prefix = _paths(sc, idx, "take_screenshot")
        local_path = os.path.join(capture_dir, f"{prefix}.jpg") if capture_dir else ""
        # save_capture raises when object storage is unavailable and the local
        # fallback is off. Storing the frame is this step's job, so a failure is
        # worth reporting — but it must not take the scenario down when the step
        # already did what the author asked and wrote save_path. Before this
        # change the step always "succeeded" by inlining base64, which is the
        # payload bug being fixed; the middle ground is to fail only when there
        # is nothing to show for the step at all.
        url = None
        try:
            url = capture_store.save_capture(
                frame,
                local_path,
                f"{minio_prefix}/{prefix}.jpg",
                "image/jpeg",
                skip_quality=True,
            )
        except Exception as store_exc:
            if not save_path:
                result["ok"] = False
                result["message"] = f"take_screenshot: could not store frame: {store_exc}"
                return
            log.warning(
                "[%s] take_screenshot: stored to %s but upload failed: %s",
                sc.serial, save_path, store_exc,
            )
        if not url:
            result["message"] = result.get("message") or (
                f"take_screenshot: saved to {save_path}, not uploaded"
                if save_path else "take_screenshot: frame not stored"
            )
            if not save_path:
                result["ok"] = False
            return

        result["screenshot"] = url
        _append_artifact(
            result,
            {
                "type": "take_screenshot",
                "execution_id": sc.execution_id,
                "step_id": str(step.get("id") or step.get("_id") or "") or None,
                "step_type": "take_screenshot",
                "step_index": idx,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "screenshot_url": url,
            },
        )
        log.info(f"[{sc.serial}] take_screenshot: {len(frame)} bytes -> {url}")
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"take_screenshot failed: {exc}"


# Template keys are content-addressed (`{sha256}.png`), so a key's bytes never
# change and this can be cached for the life of the worker. Without it a
# tap_image inside a loop step issues one object-storage GET per iteration.
_TEMPLATE_CACHE: "OrderedDict[str, bytes]" = OrderedDict()
_TEMPLATE_CACHE_MAX = 32


def _load_step_template(template_key: str) -> bytes | None:
    cached = _TEMPLATE_CACHE.get(template_key)
    if cached is not None:
        _TEMPLATE_CACHE.move_to_end(template_key)
        return cached

    from services import minio_store

    data = minio_store.get_object_bytes(template_key)
    if data:
        _TEMPLATE_CACHE[template_key] = data
        while len(_TEMPLATE_CACHE) > _TEMPLATE_CACHE_MAX:
            _TEMPLATE_CACHE.popitem(last=False)
    return data


@register_step("tap_image")
def handle_tap_image(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    """Tap wherever a cropped template appears on screen.

    The match runs on agent-boot, which has the frame; the farm only sends the
    template and receives a coordinate. Retries until ``timeout`` because the
    element the user cropped is often still animating in.
    """
    template_key = str(step.get("template_key") or "").strip()
    if not template_key:
        result["ok"] = False
        result["message"] = "tap_image: missing template_key"
        return

    # Imported before the try: `except ImageMatchError` is evaluated only when
    # something raises, and if the import itself had failed (cv2 missing, say)
    # that clause would raise NameError and escape as a crash instead of a step
    # failure — hiding the real cause.
    try:
        from services import minio_store
        from services.content.extraction.image_match_service import (
            DEFAULT_SCALE,
            DEFAULT_THRESHOLD,
            ImageMatchError,
            ImageMatchService,
        )
        from services.content.extraction.scenario_bridge import run_extraction_async
    except Exception as import_exc:
        result["ok"] = False
        result["message"] = f"tap_image unavailable: {import_exc}"
        return

    try:
        template = _load_step_template(template_key)
        if not template:
            result["ok"] = False
            result["message"] = f"tap_image: template not found ({template_key})"
            return

        threshold = float(step.get("threshold", DEFAULT_THRESHOLD) or DEFAULT_THRESHOLD)
        scale = float(step.get("scale", DEFAULT_SCALE) or DEFAULT_SCALE)
        screen_w = step.get("template_screen_w")
        timeout = float(step.get("timeout", 8.0) or 8.0)
        poll = float(step.get("poll", 0.5) or 0.5)

        service = ImageMatchService(threshold=threshold, scale=scale)
        deadline = time.monotonic() + timeout
        hit = None
        attempts = 0

        while True:
            if _cancelled(sc):
                _mark_cancelled(result, "tap_image: cancelled by user")
                return
            attempts += 1
            # Per-attempt budget, not the whole-step budget: passing `timeout`
            # here let a single slow attempt consume the entire deadline, so the
            # retry loop never got a second look at the screen. Each attempt is
            # one screenshot (tens of ms) plus a ~9ms match, so a few seconds is
            # generous; never exceed what is left of the step.
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            hit = run_extraction_async(
                service.find(
                    sc.device,
                    template,
                    template_screen_w=int(screen_w) if screen_w else None,
                    timeout=max(1.0, min(5.0, remaining)),
                )
            )
            if hit.found or time.monotonic() >= deadline:
                break
            if _wait_or_cancel(sc, poll):
                _mark_cancelled(result, "tap_image: cancelled by user")
                return

        if not hit or not hit.found:
            result["ok"] = False
            result["message"] = (
                f"tap_image: template not found on screen after {attempts} attempt(s), "
                f"threshold={threshold}"
            )
            return

        sc.device.tap(hit.cx, hit.cy)
        result["message"] = (
            f"tap_image at ({hit.cx},{hit.cy}) conf={hit.confidence:.3f} "
            f"after {attempts} attempt(s)"
        )
        result["match"] = {
            "x": hit.x, "y": hit.y, "w": hit.w, "h": hit.h,
            "confidence": hit.confidence,
        }
        if _wait_or_cancel(sc, 0.3):
            _mark_cancelled(result, "tap_image: cancelled by user")
    except ImageMatchError as exc:
        result["ok"] = False
        result["message"] = f"tap_image failed: {exc}"
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"tap_image failed: {exc}"
