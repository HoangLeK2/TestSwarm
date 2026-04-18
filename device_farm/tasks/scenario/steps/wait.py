"""Step handlers: wait, wait_element, wait_stable, assert_element, dismiss_popup, verify_screen."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict

from tasks.scenario.steps import register_step
from tasks.scenario.context import ScenarioContext
from tasks.scenario.utils import (
    _retry_find_element, _wait_screen_stable, _auto_dismiss_popup,
)

log = logging.getLogger(__name__)


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
            break
        time.sleep(min(_CHUNK, max(0.0, deadline - time.monotonic())))


@register_step("wait_element")
def handle_wait_element(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    by = str(step.get("by") or "text")
    value = str(step.get("value") or "").strip()
    timeout = float(step.get("timeout", 10.0) or 10.0)
    if not value:
        result["ok"] = False
        result["message"] = "wait_element: empty value"
        return
    u2 = sc.device.u2
    iw_poll = float(step.get("poll", 0.5) or 0.5)
    eid = _retry_find_element(
        u2, by, value, timeout=timeout, poll=iw_poll, cancel_event=sc.cancel_event,
    ) if u2 else None
    if eid is None:
        result["ok"] = False
        if sc.cancel_event is not None and sc.cancel_event.is_set():
            result["message"] = f"wait_element cancelled ({by}={value!r})"
        else:
            result["message"] = f"wait_element {by}={value!r} not found after {timeout:.0f}s"
    else:
        result["message"] = f"wait_element found {by}={value!r}"


@register_step("assert_element")
def handle_assert_element(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    by = str(step.get("by") or "text")
    value = str(step.get("value") or "").strip()
    timeout = float(step.get("timeout", 5.0) or 5.0)
    if not value:
        result["ok"] = False
        result["message"] = "assert_element: empty value"
        return
    u2 = sc.device.u2
    iw_poll = float(step.get("poll", 0.5) or 0.5)
    eid = _retry_find_element(
        u2, by, value, timeout=timeout, poll=iw_poll, cancel_event=sc.cancel_event,
    ) if u2 else None
    if eid is None:
        result["ok"] = False
        if sc.cancel_event is not None and sc.cancel_event.is_set():
            result["message"] = f"assert_element cancelled ({by}={value!r})"
        else:
            result["message"] = f"assert_element FAILED: {by}={value!r} not visible after {timeout:.0f}s"


@register_step("wait_stable")
def handle_wait_stable(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    ws_timeout = float(step.get("timeout", 5.0) or 5.0)
    ws_stable = float(step.get("stable_duration", 0.4) or 0.4)
    stable = _wait_screen_stable(sc.device, timeout=ws_timeout, stable_duration=ws_stable)
    result["message"] = f"wait_stable: {'stable' if stable else 'timed_out'}"


@register_step("dismiss_popup")
def handle_dismiss_popup(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    retries = int(step.get("retries", 3) or 3)
    dismissed_count = 0
    for _ in range(retries):
        if _auto_dismiss_popup(sc.device):
            dismissed_count += 1
            time.sleep(0.3)
        else:
            break
    result["message"] = f"dismiss_popup: dismissed {dismissed_count} popup(s)"
    if dismissed_count > 0:
        result["dismissed_count"] = dismissed_count


@register_step("verify_screen")
def handle_verify_screen(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    screenshot_b64 = str(step.get("screenshot") or "").strip()
    vs_threshold = float(step.get("ssim_threshold", 0.75) or 0.75)
    vs_timeout = float(step.get("timeout", 8.0) or 8.0)
    vs_poll = float(step.get("poll", 0.5) or 0.5)
    if not screenshot_b64:
        result["ok"] = False
        result["message"] = "verify_screen: no screenshot provided"
        return
    try:
        from runtime.visual_anchor import wait_for_screen_match, _b64_to_bytes
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
