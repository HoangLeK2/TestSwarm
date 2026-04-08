"""
relay/u2_executor.py — Batch + Flow executor for uiautomator2.

Batch: execute a list of primitive actions in one gRPC round-trip.
Flow:  execute named high-level patterns (find+click+wait, scroll-search, etc.)

All blocking u2 calls run in `loop.run_in_executor(None, ...)`.
"""
from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any

from relay.u2_session_pool import U2SessionPool

logger = logging.getLogger(__name__)

MAX_BATCH_ACTIONS = 100
MAX_FLOW_TIMEOUT = 60.0

# ── Selector resolver ──────────────────────────────────────────────────────────

_SELECTOR_KEYS = frozenset({
    "text", "textContains", "textStartsWith", "textMatches",
    "description", "descriptionContains", "descriptionStartsWith",
    "resourceId", "className", "packageName", "instance", "index",
})


def _resolve(dev: Any, selector: dict) -> Any:
    """Map JSON selector dict → uiautomator2 UiObject or XPath selector."""
    if not selector:
        raise ValueError("selector required")
    if "xpath" in selector:
        return dev.xpath(selector["xpath"])
    kwargs = {k: v for k, v in selector.items() if k in _SELECTOR_KEYS}
    if not kwargs:
        raise ValueError(f"unrecognised selector keys: {list(selector)}")
    return dev(**kwargs)


# ── Primitive op implementations (blocking) ────────────────────────────────────

def _op_click(dev: Any, act: dict) -> None:
    dev.click(int(act["x"]), int(act["y"]))


def _op_long_click(dev: Any, act: dict) -> None:
    dev.long_click(int(act["x"]), int(act["y"]), float(act.get("duration", 0.5)))


def _op_swipe(dev: Any, act: dict) -> None:
    dev.swipe(
        int(act["fx"]), int(act["fy"]),
        int(act["tx"]), int(act["ty"]),
        duration=float(act.get("duration", 0.2)),
    )


def _op_exists(dev: Any, act: dict) -> bool:
    sel = _resolve(dev, act.get("selector", {}))
    return bool(sel.exists)


def _op_get_text(dev: Any, act: dict) -> str:
    obj = _resolve(dev, act.get("selector", {}))
    if not obj.exists:
        raise RuntimeError("selector not found")
    return obj.get_text() if hasattr(obj, "get_text") else obj.info.get("text", "")


def _op_set_text(dev: Any, act: dict) -> None:
    _resolve(dev, act.get("selector", {})).set_text(act.get("text", ""))


def _op_press_key(dev: Any, act: dict) -> None:
    dev.press(act["key"])


def _op_wait_exists(dev: Any, act: dict) -> bool:
    return bool(_resolve(dev, act["selector"]).wait(timeout=float(act.get("timeout", 5))))


def _op_wait_gone(dev: Any, act: dict) -> bool:
    return bool(_resolve(dev, act["selector"]).wait_gone(timeout=float(act.get("timeout", 5))))


def _op_dump(dev: Any, act: dict) -> str:
    return dev.dump_hierarchy(compressed=bool(act.get("compressed", False)))


def _op_screenshot(dev: Any, act: dict) -> str:
    png = dev.screenshot(format="raw")
    return base64.b64encode(png).decode("ascii")


_OP_TABLE: dict[str, Any] = {
    "click":          _op_click,
    "long_click":     _op_long_click,
    "swipe":          _op_swipe,
    "exists":         _op_exists,
    "get_text":       _op_get_text,
    "set_text":       _op_set_text,
    "press_key":      _op_press_key,
    "wait_exists":    _op_wait_exists,
    "wait_gone":      _op_wait_gone,
    "dump_hierarchy": _op_dump,
    "screenshot":     _op_screenshot,
}

# ── Named flow implementations (blocking) ─────────────────────────────────────


def _flow_find_click_wait(dev: Any, p: dict) -> dict:
    """Find element, click, wait for it to disappear."""
    sel = _resolve(dev, p["selector"])
    found = bool(sel.wait(timeout=min(float(p.get("click_timeout", 10.0)), MAX_FLOW_TIMEOUT)))
    if not found:
        return {"found": False, "clicked": False, "gone": False}
    sel.click()
    gone = bool(sel.wait_gone(timeout=min(float(p.get("gone_timeout", 3.0)), MAX_FLOW_TIMEOUT)))
    return {"found": True, "clicked": True, "gone": gone}


def _flow_wait_and_click(dev: Any, p: dict) -> dict:
    """Wait for element to appear, then click."""
    sel = _resolve(dev, p["selector"])
    found = bool(sel.wait(timeout=min(float(p.get("wait_timeout", 10.0)), MAX_FLOW_TIMEOUT)))
    if not found:
        return {"found": False, "clicked": False}
    sel.click()
    return {"found": True, "clicked": True}


def _flow_find_get_text(dev: Any, p: dict) -> dict:
    """Find element, return its text."""
    sel = _resolve(dev, p["selector"])
    if not sel.wait(timeout=min(float(p.get("timeout", 5.0)), MAX_FLOW_TIMEOUT)):
        return {"found": False, "text": None}
    return {"found": True, "text": sel.get_text()}


def _flow_swipe_until_found(dev: Any, p: dict) -> dict:
    """Swipe in direction until element appears (scroll search)."""
    direction = p.get("direction", "up")
    max_swipes = max(0, int(p.get("max_swipes", 10)))
    step_ratio = float(p.get("step_ratio", 0.6))
    w, h = dev.window_size()
    cx, cy = w // 2, h // 2
    dy = int(h * step_ratio / 2)
    dx = int(w * step_ratio / 2)
    vectors = {
        "up":    (cx, cy + dy, cx, cy - dy),
        "down":  (cx, cy - dy, cx, cy + dy),
        "left":  (cx + dx, cy, cx - dx, cy),
        "right": (cx - dx, cy, cx + dx, cy),
    }
    fx, fy, tx, ty = vectors.get(direction, vectors["up"])
    sel = _resolve(dev, p["selector"])
    for i in range(max_swipes):
        if sel.exists:
            return {"found": True, "swipes": i}
        dev.swipe(fx, fy, tx, ty, duration=0.2)
    return {"found": bool(sel.exists), "swipes": max_swipes}


def _flow_input_and_confirm(dev: Any, p: dict) -> dict:
    """Find input field, type text, click confirm button."""
    timeout = min(float(p.get("wait_timeout", 5.0)), MAX_FLOW_TIMEOUT)
    inp = _resolve(dev, p["input_selector"])
    if not inp.wait(timeout=timeout):
        return {"found_input": False, "found_confirm": False, "clicked": False}
    inp.set_text(p.get("text", ""))
    btn = _resolve(dev, p["confirm_selector"])
    if not btn.wait(timeout=timeout):
        return {"found_input": True, "found_confirm": False, "clicked": False}
    btn.click()
    return {"found_input": True, "found_confirm": True, "clicked": True}


_FLOW_TABLE: dict[str, Any] = {
    "find_click_wait":   _flow_find_click_wait,
    "wait_and_click":    _flow_wait_and_click,
    "find_get_text":     _flow_find_get_text,
    "swipe_until_found": _flow_swipe_until_found,
    "input_and_confirm": _flow_input_and_confirm,
}


# ── Executor ───────────────────────────────────────────────────────────────────

class U2Executor:
    def __init__(self, pool: U2SessionPool, loop: asyncio.AbstractEventLoop) -> None:
        self._pool = pool
        self._loop = loop

    async def run_batch(
        self,
        serial: str,
        actions: list[dict],
        early_exit: bool = True,
    ) -> dict:
        if not actions:
            return {"ok": True, "stopped_at": None, "results": [], "error": None}

        if len(actions) > MAX_BATCH_ACTIONS:
            logger.warning("u2_batch: %d actions exceeds cap %d, truncating", len(actions), MAX_BATCH_ACTIONS)
            actions = actions[:MAX_BATCH_ACTIONS]

        try:
            dev = await self._pool.get_session(serial)
        except Exception as exc:
            return {"ok": False, "stopped_at": 0, "results": [],
                    "error": f"session unavailable: {exc}"}

        results: list[dict] = []
        for idx, act in enumerate(actions):
            op = act.get("op", "")
            fn = _OP_TABLE.get(op)
            if fn is None:
                entry = {"op": op, "ok": False, "error": f"unknown op: {op}"}
                results.append(entry)
                if early_exit:
                    return {"ok": False, "stopped_at": idx, "results": results,
                            "error": f"action[{idx}] unknown op: {op}"}
                continue
            try:
                value = await self._loop.run_in_executor(None, fn, dev, act)
                entry: dict = {"op": op, "ok": True}
                if value is not None:
                    entry["value"] = value
                results.append(entry)
            except Exception as exc:
                results.append({"op": op, "ok": False, "error": str(exc)})
                if early_exit:
                    return {"ok": False, "stopped_at": idx, "results": results,
                            "error": f"action[{idx}] {op}: {exc}"}
        return {"ok": True, "stopped_at": None, "results": results, "error": None}

    async def execute_flow(self, serial: str, flow: str, params: dict) -> dict:
        fn = _FLOW_TABLE.get(flow)
        if fn is None:
            return {"ok": False, "value": None, "error": f"unknown flow: {flow}"}
        try:
            dev = await self._pool.get_session(serial)
        except Exception as exc:
            return {"ok": False, "value": None,
                    "error": f"session unavailable: {exc}"}
        try:
            value = await self._loop.run_in_executor(None, fn, dev, params)
            return {"ok": True, "value": value, "error": None}
        except Exception as exc:
            logger.warning("u2_flow %s failed serial=%s: %s", flow, serial, exc)
            return {"ok": False, "value": None, "error": str(exc)}
