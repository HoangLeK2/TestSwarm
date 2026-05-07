"""Step handlers: input_text, input_selector, set_clipboard."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict

from tasks.scenario.steps import register_step
from tasks.scenario.context import ScenarioContext
from tasks.scenario.utils import _get_implicit_wait_config, _retry_find_element

log = logging.getLogger(__name__)


@register_step("input_text")
def handle_input_text(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    text = str(step.get("text") or "")
    via = str(step.get("via") or "u2")
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

    typed = False

    # Strategy 1: u2 setFastInputText
    if d is not None:
        try:
            d._rpc("setFastInputText", text)
            typed = True
            result["message"] = "input_text via u2 setFastInputText"
            log.info(f"[{serial}] input_text: strategy 1 (setFastInputText) OK")
        except Exception as fast_exc:
            log.info(f"[{serial}] input_text: strategy 1 failed: {fast_exc}")

    # Strategy 3: adb shell input text via relay
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

    # Strategy 4: agent paste
    if not typed and getattr(device, "_agent_send", None) is not None:
        log.info(f"[{serial}] input_text: trying strategy 4 (agent paste)")
        device._send_to_agent({"type": "paste", "text": text})
        time.sleep(0.7)
        typed = True
        result["message"] = "input_text via agent paste"

    if not typed:
        result["ok"] = False
        result["message"] = f"input_text: all strategies failed for {text!r}"


@register_step("input_selector")
def handle_input_selector(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    by = str(step.get("by") or "resource-id")
    value = str(step.get("value") or "").strip()
    text = str(step.get("text") or "")
    clear_first = bool(step.get("clear_first", True))
    if not value or not text:
        result["ok"] = False
        result["message"] = "input_selector: by/value/text required"
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
        )
        if eid is None:
            raise RuntimeError(f"element not visible after {iw_timeout:.0f}s: {by}={value!r}")
        if isinstance(eid, dict):
            eid = eid.get("eid", f"{by}::{value}")
        u2.element_click(eid)
        time.sleep(0.3)
        if clear_first:
            u2.clear_text()
            time.sleep(0.3)
        u2.send_keys(text)
        result["message"] = f"input_selector {by}={value!r} → {text!r}"
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"input_selector failed: {exc}"


@register_step("set_clipboard")
def handle_set_clipboard(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    text = str(step.get("text") or "")
    try:
        sc.device.set_clipboard(text)
        time.sleep(0.3)
        log.info(f"[{sc.serial}] set_clipboard: {len(text)} chars")
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"set_clipboard failed: {exc}"
