"""Step handlers: wait, wait_element, wait_stable, assert_element, dismiss_popup, verify_screen."""
from __future__ import annotations

import logging
import time
from collections import OrderedDict
from typing import Any, Dict

from tasks.scenario.steps import register_step
from tasks.scenario.context import ScenarioContext
from tasks.scenario.utils import (
    _retry_find_element, _wait_screen_stable, _auto_dismiss_popup,
    resolve_step_selector_fields,
)
from services.scenario_selector import selector_summary

log = logging.getLogger(__name__)

_VERIFY_TEMPLATE_CACHE: "OrderedDict[str, bytes]" = OrderedDict()
_VERIFY_TEMPLATE_CACHE_MAX = 32


def _load_verify_template(template_key: str) -> bytes | None:
    cached = _VERIFY_TEMPLATE_CACHE.get(template_key)
    if cached is not None:
        _VERIFY_TEMPLATE_CACHE.move_to_end(template_key)
        return cached

    from services import minio_store

    data = minio_store.get_object_bytes(template_key)
    if data:
        _VERIFY_TEMPLATE_CACHE[template_key] = data
        while len(_VERIFY_TEMPLATE_CACHE) > _VERIFY_TEMPLATE_CACHE_MAX:
            _VERIFY_TEMPLATE_CACHE.popitem(last=False)
    return data


@register_step("wait")
def handle_wait(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    try:
        secs = float(step.get("seconds", 0.0) or 0.0)
    except Exception:
        secs = 0.0
    if secs <= 0:
        result["message"] = "wait 0s (skipped sleep)"
        return
    deadline = time.monotonic() + secs
    _CHUNK = 0.2
    while time.monotonic() < deadline:
        if sc.cancel_event is not None and sc.cancel_event.is_set():
            result["ok"] = False
            result["message"] = "wait: cancelled by user"
            result["cancelled"] = True
            return
        wait_s = min(_CHUNK, max(0.0, deadline - time.monotonic()))
        if sc.cancel_event is not None and sc.cancel_event.wait(wait_s):
            result["ok"] = False
            result["message"] = "wait: cancelled by user"
            result["cancelled"] = True
            return


@register_step("wait_element")
def handle_wait_element(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    spec, by, value, _ = resolve_step_selector_fields(step)
    timeout = float(step.get("timeout", 10.0) or 10.0)
    if spec is None or spec.is_empty():
        result["ok"] = False
        result["message"] = "wait_element: empty selector"
        return
    u2 = sc.device.u2
    iw_poll = float(step.get("poll", 0.5) or 0.5)
    lbl = selector_summary(spec)
    eid = _retry_find_element(
        u2, by, value, timeout=timeout, poll=iw_poll, cancel_event=sc.cancel_event,
        spec=spec, device=sc.device,
    ) if u2 else None
    if eid is None:
        result["ok"] = False
        if sc.cancel_event is not None and sc.cancel_event.is_set():
            result["message"] = f"wait_element cancelled ({lbl})"
        else:
            result["message"] = f"wait_element {lbl} not found after {timeout:.0f}s"
    else:
        result["message"] = f"wait_element found {lbl}"


@register_step("assert_element")
def handle_assert_element(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    spec, by, value, _ = resolve_step_selector_fields(step)
    timeout = float(step.get("timeout", 5.0) or 5.0)
    if spec is None or spec.is_empty():
        result["ok"] = False
        result["message"] = "assert_element: empty selector"
        return
    u2 = sc.device.u2
    iw_poll = float(step.get("poll", 0.5) or 0.5)
    lbl = selector_summary(spec)
    eid = _retry_find_element(
        u2, by, value, timeout=timeout, poll=iw_poll, cancel_event=sc.cancel_event,
        spec=spec, device=sc.device,
    ) if u2 else None
    if eid is None:
        result["ok"] = False
        if sc.cancel_event is not None and sc.cancel_event.is_set():
            result["message"] = f"assert_element cancelled ({lbl})"
        else:
            result["message"] = f"assert_element FAILED: {lbl} not visible after {timeout:.0f}s"


@register_step("wait_stable")
def handle_wait_stable(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    ws_timeout = float(step.get("timeout", 5.0) or 5.0)
    ws_stable = float(step.get("stable_duration", 0.4) or 0.4)
    stable = _wait_screen_stable(
        sc.device,
        timeout=ws_timeout,
        stable_duration=ws_stable,
        cancel_event=sc.cancel_event,
    )
    if sc.cancel_event is not None and sc.cancel_event.is_set():
        result["ok"] = False
        result["message"] = "wait_stable: cancelled by user"
        result["cancelled"] = True
        return
    result["message"] = f"wait_stable: {'stable' if stable else 'timed_out'}"


@register_step("dismiss_popup")
def handle_dismiss_popup(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    retries = int(step.get("retries", 3) or 3)
    dismissed_count = 0
    for _ in range(retries):
        if sc.cancel_event is not None and sc.cancel_event.is_set():
            result["ok"] = False
            result["message"] = "dismiss_popup: cancelled by user"
            result["cancelled"] = True
            return
        if _auto_dismiss_popup(sc.device):
            dismissed_count += 1
            if sc.cancel_event is not None:
                sc.cancel_event.wait(0.3)
            else:
                time.sleep(0.3)
        else:
            break
    result["message"] = f"dismiss_popup: dismissed {dismissed_count} popup(s)"
    if dismissed_count > 0:
        result["dismissed_count"] = dismissed_count


@register_step("verify_screen")
def handle_verify_screen(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    screenshot_b64 = str(step.get("screenshot") or "").strip()
    template_key = str(step.get("template_key") or "").strip()
    vs_threshold = float(step.get("ssim_threshold", 0.75) or 0.75)
    vs_timeout = float(step.get("timeout", 8.0) or 8.0)
    vs_poll = float(step.get("poll", 0.5) or 0.5)
    if not screenshot_b64 and not template_key:
        result["ok"] = False
        result["message"] = "verify_screen: no screenshot/template provided"
        return
    try:
        from runtime.visual_anchor import (
            wait_for_element_image,
            wait_for_screen_match,
            _b64_to_bytes,
        )
        if template_key:
            recorded_jpeg = _load_verify_template(template_key)
            if not recorded_jpeg:
                result["ok"] = False
                result["message"] = f"verify_screen: template not found ({template_key})"
                return
            match = wait_for_element_image(
                sc.device.take_screenshot,
                recorded_jpeg,
                timeout=vs_timeout,
                poll=vs_poll,
                threshold=vs_threshold,
            )
            if match:
                _cx, _cy, confidence = match
                result["image_confidence"] = round(confidence, 3)
                result["message"] = (
                    f"verify_screen: image confidence={confidence:.3f} ≥ {vs_threshold}"
                )
            else:
                result["ok"] = False
                result["image_confidence"] = 0.0
                result["message"] = (
                    f"verify_screen FAILED: image confidence < {vs_threshold}"
                )
            return
        else:
            recorded_jpeg = _b64_to_bytes(screenshot_b64)
        matched, ssim = wait_for_screen_match(
            sc.device.take_screenshot, recorded_jpeg,
            timeout=vs_timeout, poll=vs_poll,
            ssim_threshold=vs_threshold,
        )
        result["ssim"] = round(ssim, 3)
        if matched:
            result["message"] = f"verify_screen: SSIM={ssim:.3f} ≥ {vs_threshold}"
        else:
            result["ok"] = False
            result["message"] = f"verify_screen FAILED: SSIM={ssim:.3f} < {vs_threshold}"
    except ImportError:
        result["ok"] = False
        result["message"] = "verify_screen: opencv-python-headless not installed"
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"verify_screen error: {exc}"
