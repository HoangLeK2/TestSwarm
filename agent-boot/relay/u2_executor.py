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
import time
from typing import Any, Awaitable, Callable, Optional, TypeVar

from relay.adb import lock_portrait_rotation, lock_rotation_after_shell_enabled
from relay.u2_session_pool import U2SessionPool
from relay.u2_xpath_util import normalize_u2_xpath

logger = logging.getLogger(__name__)

T = TypeVar("T")
U2HttpRpc = Callable[[str, dict[str, Any], float], tuple[bool, str]]

MAX_BATCH_ACTIONS = 100
MAX_FLOW_TIMEOUT = 60.0
DEFAULT_CLICK_TIMEOUT = 0.35
DEFAULT_FLOW_WAIT_TIMEOUT = 3.0
DEFAULT_FLOW_GONE_TIMEOUT = 1.0
DEFAULT_SWIPE_DURATION = 0.12
DEFAULT_SCROLL_MAX_SWIPES = 5

# Error substrings that signal a dead session — these should trigger evict+retry.
# Kept as string patterns (not classes) because uiautomator2 exception hierarchy
# varies across versions; matching on message is version-stable.
_DEAD_SESSION_MARKERS = (
    "502 bad gateway",     # specific to atx-agent proxy; avoid generic "gateway"
    "504 gateway",         #   which would match app-under-test HTTP errors
    "read timeout",
    "connection refused",
    "connection reset",
    "connection aborted",
    "broken pipe",
    "device not ready",
    "atx-agent not running",
    "uiautomator not connected",
)


def _looks_like_dead_session(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _DEAD_SESSION_MARKERS)


async def _run_with_retry(
    pool: U2SessionPool,
    loop: asyncio.AbstractEventLoop,
    serial: str,
    fn: Callable[[Any], Any],
) -> Any:
    """
    Run `fn(device)` with one evict+retry attempt if the first try looks like a
    dead session. Non-session errors (ValueError, selector errors, etc.) are
    re-raised immediately — only transport-level failures trigger retry.
    """
    try:
        return await pool.run_locked(serial, fn)
    except Exception as exc:
        if not _looks_like_dead_session(exc):
            raise
        logger.warning(
            "u2-exec: dead-session marker (%s) for serial=%s — evict + retry once",
            exc, serial,
        )
        await pool.evict(serial)
        return await pool.run_locked(serial, fn)

# ── Selector resolver ──────────────────────────────────────────────────────────

_SELECTOR_KEYS = frozenset({
    "text", "textContains", "textStartsWith", "textMatches",
    "description", "descriptionContains", "descriptionStartsWith",
    "resourceId", "className", "packageName", "instance", "index",
    "clickable", "checked", "checkable", "enabled", "scrollable", "focused", "selected",
})

_SELECTOR_KEY_ALIASES = {
    "descriptionStartswith": "descriptionStartsWith",
}

_BOOL_KEYS = frozenset({"clickable", "checked", "checkable", "enabled", "scrollable", "focused", "selected"})


def _selector_key(key: object) -> str:
    raw = str(key or "").strip()
    return _SELECTOR_KEY_ALIASES.get(raw, raw)


def _resolve(dev: Any, selector: dict) -> Any:
    """Map JSON selector dict → uiautomator2 UiObject or XPath selector."""
    if not selector:
        raise ValueError("selector required")
    if "spec" in selector:
        return _resolve_spec(dev, selector["spec"])
    if "xpath" in selector:
        return dev.xpath(normalize_u2_xpath(selector["xpath"]))
    kwargs = {_selector_key(k): v for k, v in selector.items() if _selector_key(k) in _SELECTOR_KEYS}
    if not kwargs:
        raise ValueError(f"unrecognised selector keys: {list(selector)}")
    return dev(**kwargs)


def _target_kwargs(target: dict) -> dict:
    if not isinstance(target, dict):
        return {}
    if target.get("xpath"):
        return {"xpath": target["xpath"]}
    cond = target.get("conditions") or {}
    kwargs: dict = {}
    by = str(target.get("by") or "").strip()
    value = str(target.get("value") or "").strip()
    if by == "resource-id" and value:
        kwargs["resourceId"] = value
    elif by == "class name" and value:
        kwargs["className"] = value
    elif by == "description" and value:
        kwargs["description"] = value
    elif by == "text" and value:
        kwargs["text"] = value
    else:
        by_key = _selector_key(by)
        if by_key in _SELECTOR_KEYS and by_key not in _BOOL_KEYS and value:
            kwargs[by_key] = value
    for k, v in cond.items():
        key = _selector_key(k)
        if key in _SELECTOR_KEYS and v is not None:
            if key in _BOOL_KEYS:
                if v:
                    kwargs[key] = True
            else:
                kwargs[key] = v
    for k, v in target.items():
        key = _selector_key(k)
        if key in _SELECTOR_KEYS and key not in kwargs and v is not None:
            if key in _BOOL_KEYS:
                if v:
                    kwargs[key] = True
            else:
                kwargs[key] = v
    for k in ("className", "resourceId", "text", "description"):
        if k in target and target[k] is not None and k not in kwargs:
            kwargs[k] = target[k]
    return kwargs


def _anchor_kwargs(spec: dict) -> dict:
    if spec.get("xpath"):
        return {"xpath": spec["xpath"]}
    by = str(spec.get("by") or "text").strip()
    value = str(spec.get("value") or "").strip()
    cond = spec.get("conditions") or {}
    kwargs: dict = {}
    if by == "resource-id" and value:
        kwargs["resourceId"] = value
    elif by in ("class name", "className") and value:
        kwargs["className"] = value
    elif by in ("description", "content-desc") and value:
        kwargs["description"] = value
    elif by == "text" and value:
        kwargs["text"] = value
    else:
        by_key = _selector_key(by)
        if by_key in _SELECTOR_KEYS and by_key not in _BOOL_KEYS and value:
            kwargs[by_key] = value
    for k, v in cond.items():
        key = _selector_key(k)
        if key in _SELECTOR_KEYS and v is not None:
            if key in _BOOL_KEYS:
                if v:
                    kwargs[key] = True
            else:
                kwargs[key] = v
    if spec.get("instance") is not None:
        kwargs["instance"] = int(spec["instance"])
    if spec.get("index") is not None:
        kwargs["index"] = int(spec["index"])
    if not kwargs and value:
        kwargs["text"] = value
    return kwargs


def _apply_chain(anchor: Any, chain: dict) -> Any:
    op = str(chain.get("op") or "").strip()
    if op == "child":
        return anchor.child(**_target_kwargs(chain.get("target") or {}))
    if op == "sibling":
        return anchor.sibling(**_target_kwargs(chain.get("target") or {}))
    if op == "relative":
        direction = str(chain.get("direction") or "right").strip().lower()
        method = getattr(anchor, direction, None)
        if method is None:
            raise ValueError(f"unsupported relative direction: {direction!r}")
        return method(**_target_kwargs(chain.get("target") or {}))
    if op == "child_by_text":
        text = chain.get("text") or ""
        target = chain.get("target") or {}
        tk = _target_kwargs(target)
        allow = bool(chain.get("allow_scroll_search", False))
        return anchor.child_by_text(text, allow_scroll_search=allow, **tk)
    if op == "child_by_description":
        desc = chain.get("description") or ""
        target = chain.get("target") or {}
        tk = _target_kwargs(target)
        allow = bool(chain.get("allow_scroll_search", False))
        return anchor.child_by_description(desc, allow_scroll_search=allow, **tk)
    raise ValueError(f"unsupported chain op: {op!r}")


def _resolve_spec(dev: Any, spec: dict) -> Any:
    """Resolve nested scenario selector spec (anchor + optional chain)."""
    if not spec:
        raise ValueError("spec required")
    if spec.get("xpath"):
        return dev.xpath(normalize_u2_xpath(spec["xpath"]))
    kwargs = _anchor_kwargs(spec)
    if not kwargs:
        raise ValueError(f"empty anchor in spec: {spec!r}")
    if "xpath" in kwargs:
        obj = dev.xpath(normalize_u2_xpath(kwargs["xpath"]))
    else:
        obj = dev(**kwargs)
    chain = spec.get("chain")
    if isinstance(chain, dict) and chain.get("op"):
        obj = _apply_chain(obj, chain)
    return obj


# ── Primitive op implementations (blocking) ────────────────────────────────────

def _op_click(dev: Any, act: dict) -> None:
    dev.click(int(act["x"]), int(act["y"]))


def _op_long_click(dev: Any, act: dict) -> None:
    dev.long_click(int(act["x"]), int(act["y"]), float(act.get("duration", 0.5)))


def _op_swipe(dev: Any, act: dict) -> None:
    dev.swipe(
        int(act["fx"]), int(act["fy"]),
        int(act["tx"]), int(act["ty"]),
        duration=float(act.get("duration", DEFAULT_SWIPE_DURATION)),
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


def _op_sleep(dev: Any, act: dict) -> None:
    seconds = max(0.0, min(3.0, float(act.get("seconds", act.get("duration", 0.0)))))
    if seconds > 0:
        time.sleep(seconds)


def _op_wait_exists(dev: Any, act: dict) -> bool:
    return bool(_resolve(dev, act["selector"]).wait(timeout=float(act.get("timeout", 5))))


def _op_wait_gone(dev: Any, act: dict) -> bool:
    return bool(_resolve(dev, act["selector"]).wait_gone(timeout=float(act.get("timeout", 5))))


def _op_click_selector(dev: Any, act: dict) -> bool:
    """Tap when selector exists; returns False if not found (no exception)."""
    sel = _resolve(dev, act.get("selector", {}))
    timeout = float(act.get("timeout", DEFAULT_CLICK_TIMEOUT))
    if hasattr(sel, "click_exists"):
        return bool(sel.click_exists(timeout=timeout))
    if sel.wait(timeout=timeout):
        sel.click()
        return True
    return False


def _op_click_spec(dev: Any, act: dict) -> bool:
    spec = act.get("spec") or {}
    timeout = float(act.get("timeout", DEFAULT_CLICK_TIMEOUT))
    sel = _resolve_spec(dev, spec)
    if hasattr(sel, "click_exists"):
        return bool(sel.click_exists(timeout=timeout))
    if sel.wait(timeout=timeout):
        sel.click()
        return True
    return False


def _op_exists_spec(dev: Any, act: dict) -> bool:
    spec = act.get("spec") or {}
    timeout = float(act.get("timeout", DEFAULT_CLICK_TIMEOUT))
    sel = _resolve_spec(dev, spec)
    if hasattr(sel, "exists"):
        return bool(sel.exists(timeout=timeout))
    return bool(sel.wait(timeout=timeout))


def _op_wait_exists_spec(dev: Any, act: dict) -> bool:
    spec = act.get("spec") or {}
    timeout = float(act.get("timeout", 5.0))
    sel = _resolve_spec(dev, spec)
    return bool(sel.wait(timeout=min(timeout, MAX_FLOW_TIMEOUT)))


def _op_dump(dev: Any, act: dict) -> str:
    return dev.dump_hierarchy(compressed=bool(act.get("compressed", False)))


def _op_screenshot(dev: Any, act: dict) -> str:
    png = dev.screenshot(format="raw")
    return base64.b64encode(png).decode("ascii")


def _op_app_start(dev: Any, act: dict) -> None:
    pkg = str(act.get("package") or "").strip()
    if not pkg:
        raise ValueError("app_start: package required")
    activity = act.get("activity")
    kwargs: dict[str, Any] = {
        "stop": bool(act.get("stop") or act.get("stop_before")),
        "use_monkey": bool(act.get("use_monkey")),
    }
    if activity:
        dev.app_start(pkg, str(activity), **kwargs)
    else:
        dev.app_start(pkg, **kwargs)


def _op_app_stop(dev: Any, act: dict) -> None:
    pkg = str(act.get("package") or "").strip()
    if not pkg:
        raise ValueError("app_stop: package required")
    dev.app_stop(pkg)


def _op_app_clear(dev: Any, act: dict) -> None:
    pkg = str(act.get("package") or "").strip()
    if not pkg:
        raise ValueError("app_clear: package required")
    dev.app_clear(pkg)


def _op_app_wait(dev: Any, act: dict) -> int:
    pkg = str(act.get("package") or "").strip()
    if not pkg:
        raise ValueError("app_wait: package required")
    timeout = float(act.get("timeout", 20.0))
    front = bool(act.get("front", True))
    pid = dev.app_wait(pkg, front=front, timeout=timeout)
    return int(pid or 0)


def _op_open_url(dev: Any, act: dict) -> None:
    url = str(act.get("url") or "").strip()
    if not url:
        raise ValueError("open_url: url required")
    dev.open_url(url)


def _op_push_file(dev: Any, act: dict) -> None:
    local_path = str(act.get("local_path") or act.get("src") or "").strip()
    remote_path = str(act.get("remote_path") or act.get("dst") or "").strip()
    if not local_path or not remote_path:
        raise ValueError("push_file: local_path and remote_path required")
    mode = act.get("mode")
    if mode is not None:
        dev.push(local_path, remote_path, mode=int(mode))
    else:
        dev.push(local_path, remote_path)


def _op_pull_file(dev: Any, act: dict) -> None:
    remote_path = str(act.get("remote_path") or act.get("src") or "").strip()
    local_path = str(act.get("local_path") or act.get("dst") or "").strip()
    if not local_path or not remote_path:
        raise ValueError("pull_file: local_path and remote_path required")
    dev.pull(remote_path, local_path)


_OP_TABLE: dict[str, Any] = {
    "click":          _op_click,
    "click_selector": _op_click_selector,
    "click_spec":     _op_click_spec,
    "long_click":     _op_long_click,
    "swipe":          _op_swipe,
    "exists":         _op_exists,
    "exists_spec":    _op_exists_spec,
    "get_text":       _op_get_text,
    "set_text":       _op_set_text,
    "press_key":      _op_press_key,
    "sleep":          _op_sleep,
    "wait_exists":    _op_wait_exists,
    "wait_exists_spec": _op_wait_exists_spec,
    "wait_gone":      _op_wait_gone,
    "dump_hierarchy": _op_dump,
    "screenshot":     _op_screenshot,
    "app_start":      _op_app_start,
    "app_stop":       _op_app_stop,
    "app_clear":      _op_app_clear,
    "app_wait":       _op_app_wait,
    "open_url":       _op_open_url,
    "push_file":      _op_push_file,
    "pull_file":      _op_pull_file,
}

# ── Named flow implementations (blocking) ─────────────────────────────────────


def _flow_find_click_wait(dev: Any, p: dict) -> dict:
    """Find element, click, wait for it to disappear."""
    sel = _resolve(dev, p["selector"])
    found = bool(sel.wait(timeout=min(float(p.get("click_timeout", DEFAULT_FLOW_WAIT_TIMEOUT)), MAX_FLOW_TIMEOUT)))
    if not found:
        return {"found": False, "clicked": False, "gone": False}
    sel.click()
    gone = bool(sel.wait_gone(timeout=min(float(p.get("gone_timeout", DEFAULT_FLOW_GONE_TIMEOUT)), MAX_FLOW_TIMEOUT)))
    return {"found": True, "clicked": True, "gone": gone}


def _flow_wait_and_click(dev: Any, p: dict) -> dict:
    """Wait for element to appear, then click."""
    sel = _resolve(dev, p["selector"])
    found = bool(sel.wait(timeout=min(float(p.get("wait_timeout", DEFAULT_FLOW_WAIT_TIMEOUT)), MAX_FLOW_TIMEOUT)))
    if not found:
        return {"found": False, "clicked": False}
    sel.click()
    return {"found": True, "clicked": True}


def _flow_wait_and_click_spec(dev: Any, p: dict) -> dict:
    """Wait for scenario selector spec (incl. chain), then click."""
    spec = p.get("spec") or {}
    wt = min(float(p.get("wait_timeout", DEFAULT_FLOW_WAIT_TIMEOUT)), MAX_FLOW_TIMEOUT)
    sel = _resolve_spec(dev, spec)
    found = bool(sel.wait(timeout=wt))
    if not found:
        return {"found": False, "clicked": False}
    bounds = None
    try:
        info = sel.info
        if isinstance(info, dict):
            bounds = info.get("bounds")
    except Exception:
        pass
    sel.click()
    return {"found": True, "clicked": True, "bounds": bounds}


def _flow_find_get_text(dev: Any, p: dict) -> dict:
    """Find element, return its text."""
    sel = _resolve(dev, p["selector"])
    if not sel.wait(timeout=min(float(p.get("timeout", 5.0)), MAX_FLOW_TIMEOUT)):
        return {"found": False, "text": None}
    return {"found": True, "text": sel.get_text()}


def _flow_swipe_until_found(dev: Any, p: dict) -> dict:
    """Swipe in direction until element appears (scroll search)."""
    direction = p.get("direction", "up")
    max_swipes = max(0, int(p.get("max_swipes", DEFAULT_SCROLL_MAX_SWIPES)))
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
        dev.swipe(fx, fy, tx, ty, duration=float(p.get("duration", DEFAULT_SWIPE_DURATION)))
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
    "wait_and_click_spec": _flow_wait_and_click_spec,
    "find_get_text":     _flow_find_get_text,
    "swipe_until_found": _flow_swipe_until_found,
    "input_and_confirm": _flow_input_and_confirm,
}


# ── Executor ───────────────────────────────────────────────────────────────────

class U2Executor:
    def __init__(
        self,
        pool: U2SessionPool,
        loop: asyncio.AbstractEventLoop,
        *,
        http_dump: Optional[Callable[[str, float, bool], str]] = None,
        http_rpc: Optional[U2HttpRpc] = None,
    ) -> None:
        self._pool = pool
        self._loop = loop
        self._http_dump = http_dump
        self._http_rpc = http_rpc

    async def with_session(self, serial: str, coro: Callable[[], Awaitable[T]]) -> T:
        """Keep one warm u2 session for expand + dump (no reconnect between batches)."""
        if hasattr(self._pool, "session_scope"):
            async with self._pool.session_scope(serial):
                return await coro()
        return await coro()

    def _run_u2_swipe_batch(self, serial: str, act: dict) -> int:
        if self._http_rpc is None:
            raise RuntimeError("u2_swipe_batch: u2 HTTP RPC not configured")
        count = max(0, min(MAX_BATCH_ACTIONS, int(act.get("count", 1))))
        if count <= 0:
            return 0
        fx = int(act["fx"])
        fy = int(act["fy"])
        tx = int(act["tx"])
        ty = int(act["ty"])
        duration = max(0.0, min(0.8, float(act.get("duration", DEFAULT_SWIPE_DURATION))))
        steps = max(1, int(duration * 40))
        pause_s = max(0.0, min(1.0, float(act.get("pause_s", 0.0))))
        timeout = max(1.5, duration + 0.8)
        for idx in range(count):
            payload = {
                "jsonrpc": "2.0",
                "method": "swipe",
                "id": idx + 1,
                "params": [fx, fy, tx, ty, steps],
            }
            ok, error = self._http_rpc(serial, payload, timeout)
            if not ok:
                raise RuntimeError(error or "u2_swipe_batch failed")
            if pause_s > 0 and idx + 1 < count:
                time.sleep(pause_s)
        return count

    async def run_batch(
        self,
        serial: str,
        actions: list[dict],
        early_exit: bool = True,
        cancel_event: Any = None,
    ) -> dict:
        if not actions:
            return {"ok": True, "stopped_at": None, "results": [], "error": None}

        if len(actions) > MAX_BATCH_ACTIONS:
            logger.warning("u2_batch: %d actions exceeds cap %d, truncating", len(actions), MAX_BATCH_ACTIONS)
            actions = actions[:MAX_BATCH_ACTIONS]

        def _run_actions(dev: Any) -> dict:
            results: list[dict] = []
            for idx, act in enumerate(actions):
                if cancel_event is not None and cancel_event.is_set():
                    return {
                        "ok": False,
                        "stopped_at": idx,
                        "results": results,
                        "error": "cancelled",
                        "cancelled": True,
                    }
                op = act.get("op", "")
                fn = None if op == "u2_swipe_batch" else _OP_TABLE.get(op)
                if op != "u2_swipe_batch" and fn is None:
                    results.append({"op": op, "ok": False, "error": f"unknown op: {op}"})
                    if early_exit:
                        return {
                            "ok": False,
                            "stopped_at": idx,
                            "results": results,
                            "error": f"action[{idx}] unknown op: {op}",
                        }
                    continue
                try:
                    if op == "u2_swipe_batch":
                        value = self._run_u2_swipe_batch(serial, act)
                    elif op == "dump_hierarchy" and self._http_dump is not None:
                        timeout = float(act.get("timeout") or act.get("timeout_s") or 5.0)
                        compressed = bool(act.get("compressed", False))
                        value = self._http_dump(serial, timeout, compressed)
                        if not value:
                            logger.debug(
                                "u2_batch: atx-http dump empty serial=%s — fallback to u2 dump_hierarchy",
                                serial,
                            )
                            value = fn(dev, act)
                    else:
                        value = fn(dev, act)
                    if op == "app_start" and act.get("use_monkey") and lock_rotation_after_shell_enabled():
                        lock_portrait_rotation(serial)
                    entry: dict = {"op": op, "ok": True}
                    if value is not None:
                        entry["value"] = value
                    results.append(entry)
                    if cancel_event is not None and cancel_event.is_set() and idx + 1 < len(actions):
                        return {
                            "ok": False,
                            "stopped_at": idx + 1,
                            "results": results,
                            "error": "cancelled",
                            "cancelled": True,
                        }
                except Exception as exc:
                    results.append({"op": op, "ok": False, "error": str(exc)})
                    if early_exit:
                        return {
                            "ok": False,
                            "stopped_at": idx,
                            "results": results,
                            "error": f"action[{idx}] {op}: {exc}",
                        }
            return {"ok": True, "stopped_at": None, "results": results, "error": None}

        try:
            return await _run_with_retry(
                self._pool,
                self._loop,
                serial,
                _run_actions,
            )
        except Exception as exc:
            return {"ok": False, "stopped_at": 0, "results": [], "error": str(exc)}

    async def execute_flow(self, serial: str, flow: str, params: dict) -> dict:
        fn = _FLOW_TABLE.get(flow)
        if fn is None:
            return {"ok": False, "value": None, "error": f"unknown flow: {flow}"}
        try:
            value = await _run_with_retry(
                self._pool, self._loop, serial,
                lambda d, _fn=fn, _p=params: _fn(d, _p),
            )
            return {"ok": True, "value": value, "error": None}
        except Exception as exc:
            logger.warning("u2_flow %s failed serial=%s: %s", flow, serial, exc)
            return {"ok": False, "value": None, "error": str(exc)}

    async def window_size(self, serial: str) -> tuple[int, int]:
        """Return (width, height) from u2 for swipe geometry."""
        try:
            size = await _run_with_retry(
                self._pool,
                self._loop,
                serial,
                lambda d: d.window_size(),
            )
            if isinstance(size, (list, tuple)) and len(size) >= 2:
                return int(size[0]), int(size[1])
        except Exception as exc:
            logger.debug("window_size failed serial=%s: %s", serial, exc)
        return 1080, 2340
