"""Step handlers: input_text, input_selector, set_clipboard."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict

from tasks.scenario.steps import register_step
from tasks.scenario.context import ScenarioContext
from tasks.scenario.utils import (
    _get_implicit_wait_config, _retry_find_element, resolve_step_selector_fields,
)
from services.scenario_selector import selector_summary, spec_eid

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


@register_step("input_text")
def handle_input_text(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    text = str(step.get("text") or "")
    via = str(step.get("via") or "u2")
    clear_first = bool(step.get("clear_first", False))
    serial = sc.serial
    device = sc.device

    if not text:
        result["ok"] = False
        result["message"] = "input_text: empty text"
        return

    if via not in ("u2", "a11y_key"):
        result["ok"] = False
        result["message"] = f"input_text: unknown via={via!r}"
        return

    d = device.u2
    if d is None:
        device.ensure_u2_healthy()
        d = device.u2
    if _cancelled(sc):
        _mark_cancelled(result, "input_text: cancelled by user")
        return

    typed = False
    if clear_first and d is not None:
        replace_text = getattr(d, "adb_keyboard_replace_text", None)
        if callable(replace_text):
            try:
                replace_text(text)
                typed = True
                result["message"] = "input_text via u2 replace_text"
                log.info(f"[{serial}] input_text: clear_first replace_text OK")
            except Exception as replace_exc:
                log.info(f"[{serial}] input_text: clear_first replace_text failed: {replace_exc}")
        if not typed:
            try:
                d.clear_text()
            except Exception as clear_exc:
                log.info(f"[{serial}] input_text: clear_first failed: {clear_exc}")

    # Strategy 1: u2 send_keys — setText on focused field, then IME (Unicode OK on Android 14).
    if not typed and d is not None:
        try:
            d.send_keys(text)
            typed = True
            result["message"] = "input_text via u2 send_keys"
            log.info(f"[{serial}] input_text: strategy 1 (send_keys) OK")
        except Exception as u2_exc:
            log.info(f"[{serial}] input_text: strategy 1 failed: {u2_exc}")

    # Strategy 2: a11y ACTION_SET_TEXT via relay/STF (Unicode OK; no shell INJECT_EVENTS).
    if _cancelled(sc):
        _mark_cancelled(result, "input_text: cancelled by user")
        return
    if not typed:
        try:
            if device._a11y_mutate("type", {"text": text}, timeout=6.0):
                typed = True
                result["message"] = "input_text via a11y type"
                log.info(f"[{serial}] input_text: strategy 2 (a11y type) OK")
        except Exception as a11y_exc:
            log.info(f"[{serial}] input_text: strategy 2 failed: {a11y_exc}")

    # Strategy 3: adb shell input text via relay (ASCII only)
    if _cancelled(sc):
        _mark_cancelled(result, "input_text: cancelled by user")
        return
    if not typed:
        is_ascii = all(ord(c) < 128 for c in text)
        if is_ascii:
            escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace(" ", "%s").replace("\n", "%n")
            try:
                from runtime.transports.adb_relay_server import get_relay_manager
                relay = get_relay_manager()
                loop = getattr(device, "_loop", None)
                resolver = getattr(device, "_resolve_relay_serial", None)
                target_serial = (
                    resolver() if callable(resolver)
                    else getattr(device, "_adb_serial", None) or getattr(device, "serial", None) or serial
                )
                if relay and loop and target_serial and relay.relay_for_serial(target_serial):
                    actual_serial = relay.resolve_serial(str(target_serial))
                    fut = asyncio.run_coroutine_threadsafe(
                        relay.adb_shell(actual_serial, f'input text "{escaped}"', timeout=20.0), loop,
                    )
                    out = fut.result(timeout=25.0) or ""
                    low = out.lower()
                    if any(m in low for m in ("error:", "exception", "securityexception")):
                        raise RuntimeError(out.strip() or "adb shell input text failed")
                    typed = True
                    result["message"] = "input_text via adb relay shell input text"
                    log.info(f"[{serial}] input_text: strategy 3 (adb relay shell) OK serial={actual_serial}")
                else:
                    log.info(f"[{serial}] input_text: strategy 3 skipped (no adb relay/loop)")
            except Exception as shell_exc:
                log.info(f"[{serial}] input_text: strategy 3 failed: {shell_exc}")

    # Strategy 4: agent type (a11y ACTION_SET_TEXT; avoids paste→shell Unicode path on Android 14+).
    if _cancelled(sc):
        _mark_cancelled(result, "input_text: cancelled by user")
        return
    if not typed and getattr(device, "_agent_send", None) is not None:
        log.info(f"[{serial}] input_text: trying strategy 4 (agent type)")
        device._send_to_agent({"type": "type", "text": text})
        if _wait_or_cancel(sc, 0.7):
            _mark_cancelled(result, "input_text: cancelled by user")
            return
        typed = True
        result["message"] = "input_text via agent type"

    if not typed:
        result["ok"] = False
        result["message"] = f"input_text: all strategies failed for {text!r}"


@register_step("input_selector")
def handle_input_selector(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    spec, by, value, _ = resolve_step_selector_fields(step)
    text = str(step.get("text") or "")
    clear_first = bool(step.get("clear_first", True))
    if spec is None or spec.is_empty() or not text:
        result["ok"] = False
        result["message"] = "input_selector: selector/value/text required"
        return
    try:
        u2 = sc.device.u2
        if u2 is None:
            sc.device.ensure_u2_healthy()
            u2 = sc.device.u2
        if u2 is None:
            raise RuntimeError("u2 not available")
        iw_timeout, iw_poll = _get_implicit_wait_config(step, sc.scenario_iw_config)
        eid = _retry_find_element(
            u2, by, value, timeout=iw_timeout, poll=iw_poll, cancel_event=sc.cancel_event,
            spec=spec, device=sc.device,
        )
        lbl = selector_summary(spec)
        if eid is None:
            raise RuntimeError(f"element not visible after {iw_timeout:.0f}s: {lbl}")
        if isinstance(eid, dict):
            eid = eid.get("eid", spec_eid(spec))
        if _cancelled(sc):
            _mark_cancelled(result, "input_selector: cancelled by user")
            return
        u2.element_click(eid)
        if _wait_or_cancel(sc, 0.3):
            _mark_cancelled(result, "input_selector: cancelled by user")
            return
        if clear_first:
            if _cancelled(sc):
                _mark_cancelled(result, "input_selector: cancelled by user")
                return
            u2.clear_text()
            if _wait_or_cancel(sc, 0.3):
                _mark_cancelled(result, "input_selector: cancelled by user")
                return
        if _cancelled(sc):
            _mark_cancelled(result, "input_selector: cancelled by user")
            return
        u2.send_keys(text)
        result["message"] = f"input_selector {lbl} → {text!r}"
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"input_selector failed: {exc}"


@register_step("set_clipboard")
def handle_set_clipboard(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    text = str(step.get("text") or "")
    try:
        if _cancelled(sc):
            _mark_cancelled(result, "set_clipboard: cancelled by user")
            return
        sc.device.set_clipboard(text)
        if _wait_or_cancel(sc, 0.3):
            _mark_cancelled(result, "set_clipboard: cancelled by user")
            return
        log.info(f"[{sc.serial}] set_clipboard: {len(text)} chars")
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"set_clipboard failed: {exc}"
