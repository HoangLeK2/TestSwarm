"""
relay/u2_executor.py — Batch + Flow executor for uiautomator2.

Batch: execute a list of primitive actions in one gRPC round-trip.
Flow:  execute named high-level patterns (find+click+wait, scroll-search, etc.)

All blocking u2 calls run in `loop.run_in_executor(None, ...)`.
"""
from __future__ import annotations

import asyncio
import base64
import inspect
import json
import logging
import os
import re
import time
from collections import deque
from contextlib import asynccontextmanager
from typing import Any, Awaitable, Callable, Optional, TypeVar

from lxml import etree as LET

from relay.adb import lock_portrait_rotation, lock_rotation_after_shell_enabled
from relay.u2_session_pool import U2SessionPool
from relay.u2_xpath_util import normalize_u2_xpath

logger = logging.getLogger(__name__)

T = TypeVar("T")
U2HttpRpc = Callable[[str, dict[str, Any], float], tuple[Any, ...]]

MAX_BATCH_ACTIONS = 100
MAX_FLOW_TIMEOUT = 60.0
DEFAULT_CLICK_TIMEOUT = 0.35
DEFAULT_FLOW_WAIT_TIMEOUT = 3.0
DEFAULT_FLOW_GONE_TIMEOUT = 1.0
DEFAULT_SWIPE_DURATION = 0.12
DEFAULT_SCROLL_MAX_SWIPES = 5


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        logger.warning("u2-exec: invalid %s=%r; using %.3f", name, raw, default)
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.warning("u2-exec: invalid %s=%r; using %d", name, raw, default)
        return default


U2_EXECUTOR_CONCURRENCY = max(1, _env_int("U2_EXECUTOR_CONCURRENCY", 16))
U2_EXECUTOR_VISIBLE_RESERVED = max(0, _env_int("U2_EXECUTOR_VISIBLE_RESERVED", 4))
U2_EXECUTOR_BACKGROUND_CONCURRENCY = max(
    1,
    _env_int(
        "U2_EXECUTOR_BACKGROUND_CONCURRENCY",
        max(1, U2_EXECUTOR_CONCURRENCY - U2_EXECUTOR_VISIBLE_RESERVED),
    ),
)
U2_COMMAND_DEADLINE_MS = max(0, _env_int("U2_COMMAND_DEADLINE_MS", 0))
U2_BACKGROUND_DUMP_DEADLINE_GRACE_MS = max(
    0,
    _env_int("U2_BACKGROUND_DUMP_DEADLINE_GRACE_MS", 12000),
)
U2_BACKGROUND_DUMP_DEADLINE_GRACE_PER_WAVE_MS = max(
    0,
    _env_int("U2_BACKGROUND_DUMP_DEADLINE_GRACE_PER_WAVE_MS", 50),
)
U2_HIERARCHY_CACHE_TTL_MS = max(0, _env_int("U2_HIERARCHY_CACHE_TTL_MS", 120))
U2_VISIBLE_HIERARCHY_CACHE_TTL_MS = max(
    0,
    _env_int("U2_VISIBLE_HIERARCHY_CACHE_TTL_MS", 80),
)
U2_HIERARCHY_SINGLEFLIGHT_ENABLED = _env_bool("U2_HIERARCHY_SINGLEFLIGHT_ENABLED", True)
U2_XML_BATCH_OPTIMIZER_ENABLED = _env_bool("U2_XML_BATCH_OPTIMIZER_ENABLED", True)
U2_HTTP_DIRECT_TOUCH_ENABLED = _env_bool("U2_HTTP_DIRECT_TOUCH_ENABLED", True)
U2_HTTP_WAIT_POLL_ENABLED = _env_bool("U2_HTTP_WAIT_POLL_ENABLED", True)
U2_HTTP_EXISTS_RPC_ENABLED = _env_bool("U2_HTTP_EXISTS_RPC_ENABLED", True)
U2_HTTP_WAIT_VISIBLE_POLL_S = max(0.03, _env_float("U2_HTTP_WAIT_VISIBLE_POLL_S", 0.10))
U2_HTTP_WAIT_BACKGROUND_POLL_S = max(0.05, _env_float("U2_HTTP_WAIT_BACKGROUND_POLL_S", 0.25))
U2_HTTP_WAIT_TIMEOUT_CAP_S = max(0.1, _env_float("U2_HTTP_WAIT_TIMEOUT_CAP_S", 5.0))
U2_BREAKER_FAILURES = max(1, _env_int("U2_BREAKER_FAILURES", 3))
U2_BREAKER_BASE_S = max(0.0, _env_float("U2_BREAKER_BASE_S", 2.0))
U2_BREAKER_MAX_S = max(0.0, _env_float("U2_BREAKER_MAX_S", 30.0))

_READ_ONLY_BATCH_OPS = frozenset({
    "dump_hierarchy",
    "exists",
    "get_text",
    "screenshot",
    "sleep",
    "wait_exists",
    "wait_gone",
})

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

_VISIBLE_PRIORITIES = frozenset({"0", "1", "high", "visible", "focused", "interactive", "control"})
_HTTP_DIRECT_TOUCH_OPS = frozenset({"click", "swipe", "long_click", "u2_swipe_batch", "sleep", "click_spec"})
_XML_BOUNDS_RE = re.compile(r"^\[(\d+),(\d+)\]\[(\d+),(\d+)\]$")
_XPATH_BOUNDS_RE = re.compile(r"@?bounds\s*=\s*['\"](\[\d+,\d+\]\[\d+,\d+\])['\"]")
_XML_SELECTOR_ATTRS = {
    "text": "text",
    "description": "content-desc",
    "resourceId": "resource-id",
    "className": "class",
    "packageName": "package",
    "clickable": "clickable",
    "checked": "checked",
    "checkable": "checkable",
    "enabled": "enabled",
    "scrollable": "scrollable",
    "focused": "focused",
    "selected": "selected",
    "index": "index",
}
_XML_SELECTOR_SUPPORTED_KEYS = frozenset({
    "text",
    "textContains",
    "textStartsWith",
    "textMatches",
    "description",
    "descriptionContains",
    "descriptionStartsWith",
    "resourceId",
    "className",
    "packageName",
    "clickable",
    "checked",
    "checkable",
    "enabled",
    "scrollable",
    "focused",
    "selected",
    "index",
    "instance",
})
_XML_INDEXABLE_KEYS = frozenset({
    "text",
    "description",
    "resourceId",
    "className",
    "packageName",
    "clickable",
    "checked",
    "checkable",
    "enabled",
    "scrollable",
    "focused",
    "selected",
    "index",
})


def _new_xml_parser() -> LET.XMLParser:
    return LET.XMLParser(
        resolve_entities=False,
        no_network=True,
        recover=False,
        huge_tree=False,
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
_U2_SELECTOR_MASKS = {
    "text": 0x01,
    "textContains": 0x02,
    "textMatches": 0x04,
    "textStartsWith": 0x08,
    "className": 0x10,
    "classNameMatches": 0x20,
    "description": 0x40,
    "descriptionContains": 0x80,
    "descriptionMatches": 0x0100,
    "descriptionStartsWith": 0x0200,
    "checkable": 0x0400,
    "checked": 0x0800,
    "clickable": 0x1000,
    "longClickable": 0x2000,
    "scrollable": 0x4000,
    "enabled": 0x8000,
    "focusable": 0x010000,
    "focused": 0x020000,
    "selected": 0x040000,
    "packageName": 0x080000,
    "packageNameMatches": 0x100000,
    "resourceId": 0x200000,
    "resourceIdMatches": 0x400000,
    "index": 0x800000,
    "instance": 0x01000000,
}


def _selector_key(key: object) -> str:
    raw = str(key or "").strip()
    return _SELECTOR_KEY_ALIASES.get(raw, raw)


def _u2_selector_payload(selector: dict) -> dict | None:
    if not isinstance(selector, dict) or not selector:
        return None
    payload: dict[str, Any] = {
        "mask": 0,
        "childOrSibling": [],
        "childOrSiblingSelector": [],
    }
    for raw_key, value in selector.items():
        key = _selector_key(raw_key)
        if key not in _U2_SELECTOR_MASKS or value is None:
            return None
        payload[key] = value
        payload["mask"] = int(payload["mask"]) | _U2_SELECTOR_MASKS[key]
    return payload if int(payload["mask"]) else None


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


def _xml_selector_supported(selector: dict) -> bool:
    if not isinstance(selector, dict) or not selector:
        return False
    if "xpath" in selector or "spec" in selector:
        return False
    return all(_selector_key(key) in _XML_SELECTOR_SUPPORTED_KEYS for key in selector)


def _xml_bool(value: Any) -> str:
    return "true" if bool(value) else "false"


def _xml_parse_root(xml: str) -> Any:
    return LET.fromstring(xml.encode("utf-8"), parser=_new_xml_parser())


def _bounds_center_from_parts(left: int, top: int, right: int, bottom: int) -> tuple[int, int] | None:
    if right <= left or bottom <= top:
        return None
    return (left + right) // 2, (top + bottom) // 2


def _bounds_center_from_sequence(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        left, top, right, bottom = (int(part) for part in value)
    except (TypeError, ValueError):
        return None
    return _bounds_center_from_parts(left, top, right, bottom)


def _bounds_center_from_string(raw: str) -> tuple[int, int] | None:
    match = _XML_BOUNDS_RE.match(str(raw or ""))
    if match is None:
        return None
    left, top, right, bottom = (int(group) for group in match.groups())
    return _bounds_center_from_parts(left, top, right, bottom)


def _bounds_center_from_xpath(xpath: str) -> tuple[int, int] | None:
    match = _XPATH_BOUNDS_RE.search(str(xpath or ""))
    if match is None:
        return None
    return _bounds_center_from_string(match.group(1))


def _xml_attr(node: Any, selector_key: str) -> str:
    attr = _XML_SELECTOR_ATTRS.get(selector_key)
    if not attr:
        return ""
    return str(node.attrib.get(attr, "") or "")


def _xml_bounds_center(node: Any) -> tuple[int, int] | None:
    return _bounds_center_from_string(str(node.attrib.get("bounds", "") or ""))


def _xml_node_matches(node: Any, selector: dict) -> bool:
    for raw_key, expected in selector.items():
        key = _selector_key(raw_key)
        if key == "instance":
            continue
        if key in _BOOL_KEYS:
            if bool(expected) and _xml_attr(node, key).lower() != _xml_bool(expected):
                return False
            if not bool(expected) and _xml_attr(node, key).lower() == "true":
                return False
            continue
        if key == "textContains":
            if str(expected) not in _xml_attr(node, "text"):
                return False
            continue
        if key == "textStartsWith":
            if not _xml_attr(node, "text").startswith(str(expected)):
                return False
            continue
        if key == "textMatches":
            try:
                if re.search(str(expected), _xml_attr(node, "text")) is None:
                    return False
            except re.error:
                return False
            continue
        if key == "descriptionContains":
            if str(expected) not in _xml_attr(node, "description"):
                return False
            continue
        if key == "descriptionStartsWith":
            if not _xml_attr(node, "description").startswith(str(expected)):
                return False
            continue
        if _xml_attr(node, key) != str(expected):
            return False
    return True


def _selector_cache_token(selector: dict) -> str:
    try:
        return json.dumps(
            selector,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        return repr(sorted(selector.items())) if isinstance(selector, dict) else repr(selector)


class _XmlNodeIndex:
    def __init__(self, root: Any, on_cache_event: Callable[[str], None] | None = None) -> None:
        self._nodes: list[Any] = []
        self._by_key: dict[tuple[str, str], list[Any]] = {}
        self._find_cache: dict[str, Any | None] = {}
        self._on_cache_event = on_cache_event
        for node in root.iter("node"):
            self._nodes.append(node)
            for key in _XML_INDEXABLE_KEYS:
                value = _xml_attr(node, key)
                if value:
                    self._by_key.setdefault((key, value), []).append(node)

    def _cache_event(self, key: str) -> None:
        if self._on_cache_event is not None:
            self._on_cache_event(key)

    def _candidates(self, selector: dict) -> list[Any]:
        indexed: list[list[Any]] = []
        for raw_key, expected in selector.items():
            key = _selector_key(raw_key)
            if key == "instance":
                continue
            if key in _BOOL_KEYS:
                if bool(expected):
                    indexed.append(self._by_key.get((key, "true"), []))
                continue
            if key in _XML_INDEXABLE_KEYS:
                indexed.append(self._by_key.get((key, str(expected)), []))
        if not indexed:
            return self._nodes
        return min(indexed, key=len)

    def find(self, selector: dict) -> Any | None:
        if not _xml_selector_supported(selector):
            raise ValueError("selector not supported by xml optimizer")
        cache_key = _selector_cache_token(selector)
        if cache_key in self._find_cache:
            self._cache_event("xml_selector_cache_hits")
            return self._find_cache[cache_key]
        matches = [
            node
            for node in self._candidates(selector)
            if _xml_node_matches(node, selector)
        ]
        if not matches:
            self._find_cache[cache_key] = None
            self._cache_event("xml_selector_cache_stores")
            return None
        try:
            instance = int(selector.get("instance", 0) or 0)
        except (TypeError, ValueError):
            instance = 0
        if instance < 0:
            instance = 0
        if instance >= len(matches):
            self._find_cache[cache_key] = None
            self._cache_event("xml_selector_cache_stores")
            return None
        node = matches[instance]
        self._find_cache[cache_key] = node
        self._cache_event("xml_selector_cache_stores")
        return node


def _xml_find_node_in_root(root: Any, selector: dict) -> Any | None:
    return _XmlNodeIndex(root).find(selector)


def _xml_find_node(xml: str, selector: dict) -> Any | None:
    return _xml_find_node_in_root(_xml_parse_root(xml), selector)


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


def _click_spec_bounds_center(spec: dict) -> tuple[int, int] | None:
    if not isinstance(spec, dict):
        return None
    center = _bounds_center_from_sequence(spec.get("bounds"))
    if center is not None:
        return center
    center = _bounds_center_from_xpath(str(spec.get("xpath") or ""))
    if center is not None:
        return center
    target = spec.get("target")
    if isinstance(target, dict):
        center = _bounds_center_from_sequence(target.get("bounds"))
        if center is not None:
            return center
        center = _bounds_center_from_xpath(str(target.get("xpath") or ""))
        if center is not None:
            return center
    return None


def _xml_selector_from_simple_spec(spec: dict) -> dict | None:
    if not isinstance(spec, dict) or spec.get("chain") or spec.get("xpath"):
        return None
    selector = _anchor_kwargs(spec)
    if not selector or not _xml_selector_supported(selector):
        return None
    return selector


def _xml_selector_from_click_spec(spec: dict) -> dict | None:
    return _xml_selector_from_simple_spec(spec)


def _selector_from_flow_params(params: dict) -> dict:
    selector = params.get("selector", {}) if isinstance(params, dict) else {}
    if not isinstance(selector, dict):
        return {}
    spec = selector.get("spec")
    if isinstance(spec, dict):
        simple_selector = _xml_selector_from_simple_spec(spec)
        if simple_selector is not None:
            return simple_selector
    return selector


def _force_fresh_xml(act: dict) -> bool:
    if not isinstance(act, dict):
        return False
    return any(
        bool(act.get(key))
        for key in (
            "force_fresh_xml",
            "force_fresh",
            "force_refresh",
            "fresh",
        )
    )


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


def _selector_exists_now(sel: Any) -> bool:
    """Check selector presence without inheriting uiautomator2 implicit wait."""
    exists = getattr(sel, "exists", None)
    if callable(exists):
        try:
            return bool(exists(timeout=0))
        except TypeError:
            return bool(exists(0))
    if exists is not None:
        return bool(exists)

    wait = getattr(sel, "wait", None)
    if callable(wait):
        try:
            return bool(wait(timeout=0))
        except TypeError:
            return bool(wait(0))

    return bool(exists)


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
    kwargs: dict[str, Any] = {
        "compressed": bool(act.get("compressed", False)),
    }
    if "pretty" in act:
        kwargs["pretty"] = bool(act.get("pretty", False))
    if act.get("max_depth") is not None:
        kwargs["max_depth"] = int(act["max_depth"])
    return dev.dump_hierarchy(**kwargs)


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
        if _selector_exists_now(sel):
            return {"found": True, "swipes": i}
        dev.swipe(fx, fy, tx, ty, duration=float(p.get("duration", DEFAULT_SWIPE_DURATION)))
    return {"found": _selector_exists_now(sel), "swipes": max_swipes}


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
        self._ui_generations: dict[str, int] = {}
        self._ui_mutations_in_flight: dict[str, int] = {}
        self._global_sem = asyncio.Semaphore(U2_EXECUTOR_CONCURRENCY)
        self._background_sem = asyncio.Semaphore(
            min(U2_EXECUTOR_BACKGROUND_CONCURRENCY, U2_EXECUTOR_CONCURRENCY)
        )
        self._background_waiting = 0
        self._dump_cache: dict[tuple[str, bool, int], tuple[float, str]] = {}
        self._xml_index_cache: dict[tuple[str, bool, int], tuple[float, str, _XmlNodeIndex]] = {}
        self._dump_inflight: dict[tuple[str, bool, int, bool], asyncio.Task[dict]] = {}
        self._dump_inflight_lock = asyncio.Lock()
        self._xml_poll_inflight: dict[tuple[Any, ...], asyncio.Task[dict]] = {}
        self._xml_poll_inflight_lock = asyncio.Lock()
        self._breaker: dict[str, tuple[int, float]] = {}
        self._stats: dict[str, int] = {
            "admitted": 0,
            "visible_admitted": 0,
            "background_admitted": 0,
            "deadline_drops": 0,
            "visible_deadline_drops": 0,
            "background_deadline_drops": 0,
            "background_dump_deadline_grace_applied": 0,
            "breaker_drops": 0,
            "breaker_opens": 0,
            "breaker_resets": 0,
            "hierarchy_visible_requests": 0,
            "hierarchy_background_requests": 0,
            "hierarchy_visible_success": 0,
            "hierarchy_background_success": 0,
            "hierarchy_visible_failures": 0,
            "hierarchy_background_failures": 0,
            "dump_cache_hits": 0,
            "dump_cache_stores": 0,
            "dump_singleflight_joins": 0,
            "dump_singleflight_leaders": 0,
            "dump_visible_singleflight_joins": 0,
            "dump_background_singleflight_joins": 0,
            "dump_visible_singleflight_leaders": 0,
            "dump_background_singleflight_leaders": 0,
            "dump_http_direct": 0,
            "dump_pool_fallbacks": 0,
            "xml_batch_optimized": 0,
            "xml_selector_hits": 0,
            "xml_selector_misses": 0,
            "xml_u2_calls_avoided": 0,
            "xml_optimizer_fallbacks": 0,
            "xml_parse_lxml": 0,
            "xml_parse_errors": 0,
            "xml_index_builds": 0,
            "xml_index_cache_hits": 0,
            "xml_index_cache_stores": 0,
            "xml_selector_cache_hits": 0,
            "xml_selector_cache_stores": 0,
            "xml_poll_coalesced_joins": 0,
            "xml_poll_coalesced_leaders": 0,
            "http_direct_batches": 0,
            "http_direct_actions": 0,
            "http_direct_failures": 0,
            "http_direct_unavailable": 0,
            "xml_click_fused": 0,
            "xml_click_misses": 0,
            "xml_click_failures": 0,
            "xml_click_no_bounds": 0,
            "click_spec_http_direct": 0,
            "click_spec_http_direct_bounds": 0,
            "http_wait_batches": 0,
            "http_wait_hits": 0,
            "http_wait_misses": 0,
            "http_wait_polls": 0,
            "http_wait_fallbacks": 0,
            "http_flow_fastpaths": 0,
            "http_flow_hits": 0,
            "http_flow_misses": 0,
            "http_flow_polls": 0,
            "http_flow_fallbacks": 0,
            "http_flow_failures": 0,
            "http_flow_swipes": 0,
            "http_exists_rpcs": 0,
            "http_exists_hits": 0,
            "http_exists_misses": 0,
            "http_exists_failures": 0,
            "http_exists_fallbacks": 0,
        }
        self._queue_wait_samples_ms: deque[int] = deque(maxlen=1024)
        self._visible_queue_wait_samples_ms: deque[int] = deque(maxlen=1024)
        self._background_queue_wait_samples_ms: deque[int] = deque(maxlen=1024)

    def _bump(self, key: str, amount: int = 1) -> None:
        self._stats[key] = self._stats.get(key, 0) + amount

    @staticmethod
    def _p95(samples: deque[int]) -> int:
        if not samples:
            return 0
        ordered = sorted(samples)
        return ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]

    def stats_snapshot(self, *, reset: bool = False) -> dict[str, int]:
        stats = dict(self._stats)
        stats.update(
            {
                "global_limit": U2_EXECUTOR_CONCURRENCY,
                "background_limit": min(
                    U2_EXECUTOR_BACKGROUND_CONCURRENCY,
                    U2_EXECUTOR_CONCURRENCY,
                ),
                "visible_reserved": U2_EXECUTOR_VISIBLE_RESERVED,
                "background_dump_deadline_grace_ms": U2_BACKGROUND_DUMP_DEADLINE_GRACE_MS,
                "background_dump_deadline_grace_per_wave_ms": (
                    U2_BACKGROUND_DUMP_DEADLINE_GRACE_PER_WAVE_MS
                ),
                "background_waiting": self._background_waiting,
                "dump_cache_entries": len(self._dump_cache),
                "xml_index_cache_entries": len(self._xml_index_cache),
                "dump_inflight": len(self._dump_inflight),
                "xml_poll_inflight": len(self._xml_poll_inflight),
                "breaker_open": sum(
                    1 for _failures, open_until in self._breaker.values()
                    if open_until > time.monotonic()
                ),
                "queue_wait_p95_ms": self._p95(self._queue_wait_samples_ms),
                "visible_queue_wait_p95_ms": self._p95(self._visible_queue_wait_samples_ms),
                "background_queue_wait_p95_ms": self._p95(self._background_queue_wait_samples_ms),
            }
        )
        if reset:
            for key in list(self._stats):
                self._stats[key] = 0
            self._queue_wait_samples_ms.clear()
            self._visible_queue_wait_samples_ms.clear()
            self._background_queue_wait_samples_ms.clear()
        return stats

    def ui_generation(self, serial: str) -> int:
        """Monotonic marker used to invalidate short-lived UI handoffs."""
        return self._ui_generations.get(serial, 0)

    def ui_mutation_in_flight(self, serial: str) -> int:
        return self._ui_mutations_in_flight.get(serial, 0)

    def begin_ui_mutation(self, serial: str) -> None:
        self._ui_generations[serial] = self.ui_generation(serial) + 1
        self._clear_dump_cache(serial)
        self._ui_mutations_in_flight[serial] = (
            self.ui_mutation_in_flight(serial) + 1
        )

    def end_ui_mutation(self, serial: str) -> None:
        self._ui_generations[serial] = self.ui_generation(serial) + 1
        self._clear_dump_cache(serial)
        remaining = self.ui_mutation_in_flight(serial) - 1
        if remaining > 0:
            self._ui_mutations_in_flight[serial] = remaining
        else:
            self._ui_mutations_in_flight.pop(serial, None)

    def _clear_dump_cache(self, serial: str) -> None:
        stale = [key for key in self._dump_cache if key[0] == serial]
        for key in stale:
            self._dump_cache.pop(key, None)
            self._xml_index_cache.pop(key, None)

    @staticmethod
    def _is_visible_priority(priority: str | int | None) -> bool:
        return str(priority or "").strip().lower() in _VISIBLE_PRIORITIES

    def _lane_prefix(self, priority: str | int | None) -> str:
        return "visible" if self._is_visible_priority(priority) else "background"

    def _bump_lane(self, base: str, priority: str | int | None, amount: int = 1) -> None:
        self._bump(f"{self._lane_prefix(priority)}_{base}", amount)

    def _bump_hierarchy_request(self, priority: str | int | None) -> None:
        self._bump(f"hierarchy_{self._lane_prefix(priority)}_requests")

    def _bump_hierarchy_result(self, priority: str | int | None, *, ok: bool) -> None:
        suffix = "success" if ok else "failures"
        self._bump(f"hierarchy_{self._lane_prefix(priority)}_{suffix}")

    def record_hierarchy_request(self, priority: str | int | None) -> None:
        self._bump_hierarchy_request(priority)

    def record_hierarchy_result(self, priority: str | int | None, *, ok: bool) -> None:
        self._bump_hierarchy_result(priority, ok=ok)

    def _effective_deadline_ms(self, deadline_ms: int | float | None) -> int:
        if deadline_ms is None:
            return U2_COMMAND_DEADLINE_MS
        try:
            return max(0, int(deadline_ms))
        except (TypeError, ValueError):
            return U2_COMMAND_DEADLINE_MS

    def _single_dump_deadline_ms(
        self,
        deadline_ms: int | float | None,
        *,
        priority: str | int | None,
    ) -> int:
        deadline = self._effective_deadline_ms(deadline_ms)
        if deadline > 0 and not self._is_visible_priority(priority):
            grace_ms = U2_BACKGROUND_DUMP_DEADLINE_GRACE_MS
            if U2_BACKGROUND_DUMP_DEADLINE_GRACE_PER_WAVE_MS > 0:
                limit = max(
                    1,
                    min(U2_EXECUTOR_BACKGROUND_CONCURRENCY, U2_EXECUTOR_CONCURRENCY),
                )
                waves = max(0, (self._background_waiting + limit - 1) // limit)
                if waves > 0:
                    grace_ms += waves * U2_BACKGROUND_DUMP_DEADLINE_GRACE_PER_WAVE_MS
            if grace_ms > 0:
                self._bump("background_dump_deadline_grace_applied")
                return deadline + grace_ms
        return deadline

    @asynccontextmanager
    async def _admit(
        self,
        *,
        serial: str,
        priority: str | int | None,
        deadline_ms: int | float | None,
    ):
        visible = self._is_visible_priority(priority)
        deadline = self._effective_deadline_ms(deadline_ms)
        queued_at = time.perf_counter()
        bg_acquired = False
        global_acquired = False
        try:
            if not visible:
                self._background_waiting += 1
                await self._background_sem.acquire()
                self._background_waiting = max(0, self._background_waiting - 1)
                bg_acquired = True
            await self._global_sem.acquire()
            global_acquired = True
            queue_wait_ms = int((time.perf_counter() - queued_at) * 1000.0)
            self._queue_wait_samples_ms.append(queue_wait_ms)
            if visible:
                self._visible_queue_wait_samples_ms.append(queue_wait_ms)
                self._bump("visible_admitted")
            else:
                self._background_queue_wait_samples_ms.append(queue_wait_ms)
                self._bump("background_admitted")
            self._bump("admitted")
            if deadline > 0 and queue_wait_ms > deadline:
                self._bump("deadline_drops")
                self._bump_lane("deadline_drops", priority)
                raise TimeoutError(
                    "u2 command deadline exceeded before execution: "
                    f"{queue_wait_ms}ms > {deadline}ms"
                )
            yield queue_wait_ms
        finally:
            if not visible and not bg_acquired:
                self._background_waiting = max(0, self._background_waiting - 1)
            if global_acquired:
                self._global_sem.release()
            if bg_acquired:
                self._background_sem.release()

    def _breaker_is_open(self, serial: str, *, priority: str | int | None) -> bool:
        if self._is_visible_priority(priority):
            return False
        failures, open_until = self._breaker.get(serial, (0, 0.0))
        if failures <= 0 or open_until <= 0:
            return False
        if open_until > time.monotonic():
            return True
        return False

    def _breaker_error(self, serial: str) -> str:
        failures, open_until = self._breaker.get(serial, (0, 0.0))
        remaining_ms = max(0, int((open_until - time.monotonic()) * 1000.0))
        return f"u2 breaker open serial={serial} failures={failures} retry_after_ms={remaining_ms}"

    def _record_outcome(self, serial: str, ok: bool, error: str | None = None) -> None:
        if ok:
            if serial in self._breaker:
                self._bump("breaker_resets")
            self._breaker.pop(serial, None)
            return
        if not error:
            return
        lowered = error.lower()
        breaker_eligible = (
            _looks_like_dead_session(RuntimeError(error))
            or "timeout" in lowered
            or "502" in lowered
            or "504" in lowered
        )
        if not breaker_eligible:
            return
        failures, _open_until = self._breaker.get(serial, (0, 0.0))
        failures += 1
        if failures >= U2_BREAKER_FAILURES:
            delay = min(
                U2_BREAKER_MAX_S,
                U2_BREAKER_BASE_S * (2 ** max(0, failures - U2_BREAKER_FAILURES)),
            )
            self._breaker[serial] = (failures, time.monotonic() + delay)
            self._bump("breaker_opens")
        else:
            self._breaker[serial] = (failures, 0.0)

    def _single_dump_cache_key(self, serial: str, act: dict) -> tuple[str, bool, int]:
        return (
            serial,
            bool(act.get("compressed", False)),
            self.ui_generation(serial),
        )

    def _single_dump_inflight_key(
        self,
        serial: str,
        act: dict,
        priority: str | int | None,
    ) -> tuple[str, bool, int, bool]:
        cache_key = self._single_dump_cache_key(serial, act)
        return (*cache_key, self._is_visible_priority(priority))

    def _single_dump_cache_ttl_ms(self, priority: str | int | None) -> int:
        if self._is_visible_priority(priority):
            return U2_VISIBLE_HIERARCHY_CACHE_TTL_MS
        return U2_HIERARCHY_CACHE_TTL_MS

    def _cached_single_dump(
        self,
        key: tuple[str, bool, int],
        *,
        priority: str | int | None,
    ) -> str | None:
        if self.ui_mutation_in_flight(key[0]) > 0:
            return None
        ttl_ms = self._single_dump_cache_ttl_ms(priority)
        if ttl_ms <= 0:
            return None
        cached = self._dump_cache.get(key)
        if cached is None:
            return None
        expires_at, xml = cached
        if expires_at < time.monotonic():
            self._dump_cache.pop(key, None)
            return None
        self._bump("dump_cache_hits")
        return xml

    def _store_single_dump_cache(
        self,
        key: tuple[str, bool, int],
        value: str,
        *,
        priority: str | int | None,
    ) -> None:
        if not value or self.ui_mutation_in_flight(key[0]) > 0:
            return
        ttl_ms = self._single_dump_cache_ttl_ms(priority)
        if ttl_ms <= 0:
            return
        previous = self._dump_cache.get(key)
        previous_xml = previous[1] if previous is not None else None
        self._dump_cache[key] = (time.monotonic() + ttl_ms / 1000.0, value)
        self._bump("dump_cache_stores")
        if previous_xml != value:
            self._xml_index_cache.pop(key, None)

    def _xml_index_from_dump(
        self,
        key: tuple[str, bool, int],
        xml: str,
        *,
        priority: str | int | None,
    ) -> _XmlNodeIndex:
        ttl_ms = self._single_dump_cache_ttl_ms(priority)
        if ttl_ms > 0:
            cached = self._xml_index_cache.get(key)
            if cached is not None:
                expires_at, cached_xml, cached_index = cached
                if expires_at >= time.monotonic() and cached_xml == xml:
                    self._bump("xml_index_cache_hits")
                    return cached_index
                self._xml_index_cache.pop(key, None)

        root = _xml_parse_root(xml)
        self._bump("xml_parse_lxml")
        xml_index = _XmlNodeIndex(root, on_cache_event=self._bump)
        self._bump("xml_index_builds")
        if ttl_ms > 0 and xml and self.ui_mutation_in_flight(key[0]) <= 0:
            self._xml_index_cache[key] = (
                time.monotonic() + ttl_ms / 1000.0,
                xml,
                xml_index,
            )
            self._bump("xml_index_cache_stores")
        return xml_index

    def _xml_poll_key(
        self,
        *,
        serial: str,
        selector: dict,
        timeout_s: float,
        compressed: bool,
        want_present: bool,
        priority: str | int | None,
        deadline_ms: int | float | None,
        poll_stat: str,
        bypass_first_cache: bool,
    ) -> tuple[Any, ...]:
        selector_token = _selector_cache_token(selector)
        return (
            serial,
            selector_token,
            bool(compressed),
            bool(want_present),
            self.ui_generation(serial),
            self._is_visible_priority(priority),
            int(max(0.0, min(timeout_s, U2_HTTP_WAIT_TIMEOUT_CAP_S)) * 1000),
            self._effective_deadline_ms(deadline_ms),
            str(poll_stat),
            bool(bypass_first_cache),
        )

    async def with_session(self, serial: str, coro: Callable[[], Awaitable[T]]) -> T:
        """Keep one warm u2 session for expand + dump (no reconnect between batches)."""
        if hasattr(self._pool, "session_scope"):
            async with self._pool.session_scope(serial):
                return await coro()
        return await coro()

    def _mark_direct_http_healthy(self, serial: str) -> None:
        marker = getattr(self._pool, "mark_direct_http_healthy", None)
        if callable(marker):
            result = marker(serial)
            if inspect.isawaitable(result):
                close = getattr(result, "close", None)
                if callable(close):
                    close()

    def _call_http_rpc(
        self,
        serial: str,
        payload: dict[str, Any],
        timeout: float,
    ) -> tuple[bool, str, Any]:
        if self._http_rpc is None:
            return False, "u2 HTTP RPC not configured", None
        raw = self._http_rpc(serial, payload, timeout)
        ok = bool(raw[0]) if len(raw) >= 1 else False
        error = str(raw[1] or "") if len(raw) >= 2 else ""
        result = raw[2] if len(raw) >= 3 else None
        if ok:
            self._mark_direct_http_healthy(serial)
        return ok, error, result

    def _run_http_exists_rpc(self, serial: str, selector: dict) -> bool:
        if not U2_HTTP_EXISTS_RPC_ENABLED:
            raise RuntimeError("u2 HTTP exists RPC disabled")
        payload_selector = _u2_selector_payload(selector)
        if payload_selector is None:
            raise RuntimeError("selector not supported by u2 HTTP exists RPC")
        ok, error, result = self._call_http_rpc(
            serial,
            {
                "jsonrpc": "2.0",
                "method": "exist",
                "id": 1,
                "params": [payload_selector],
            },
            0.6,
        )
        self._bump("http_exists_rpcs")
        if not ok:
            self._bump("http_exists_failures")
            raise RuntimeError(error or "u2 HTTP exists RPC failed")
        if result is None:
            self._bump("http_exists_failures")
            raise RuntimeError("u2 HTTP exists RPC returned no result")
        found = bool(result)
        self._bump("http_exists_hits" if found else "http_exists_misses")
        return found

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
            ok, error, _result = self._call_http_rpc(serial, payload, timeout)
            if not ok:
                raise RuntimeError(error or "u2_swipe_batch failed")
            if pause_s > 0 and idx + 1 < count:
                time.sleep(pause_s)
        return count

    def _http_touch_rpc_payload(self, act: dict, req_id: int) -> tuple[str, dict, float] | None:
        op = str(act.get("op", "") or "")
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": req_id,
        }
        timeout = 1.5
        if op == "click":
            payload["method"] = "click"
            payload["params"] = [int(act["x"]), int(act["y"])]
        elif op == "swipe":
            duration = max(0.0, float(act.get("duration", DEFAULT_SWIPE_DURATION)))
            steps = max(1, int(duration * 40))
            payload["method"] = "swipe"
            payload["params"] = [
                int(act["fx"]), int(act["fy"]),
                int(act["tx"]), int(act["ty"]),
                steps,
            ]
            timeout = max(1.5, duration + 0.8)
        elif op == "long_click":
            duration = max(0.1, float(act.get("duration", 0.5)))
            payload["method"] = "longClick"
            payload["params"] = [int(act["x"]), int(act["y"])]
            timeout = max(1.5, duration + 0.8)
        elif op == "click_spec":
            center = _click_spec_bounds_center(act.get("spec") or {})
            if center is None:
                return None
            x, y = center
            payload["method"] = "click"
            payload["params"] = [x, y]
        else:
            return None
        return op, payload, timeout

    def _can_run_http_direct_touch_batch(self, actions: list[dict], cancel_event: Any) -> bool:
        if not actions or cancel_event is not None:
            return False
        all_direct_touch = all(
            isinstance(act, dict)
            and str(act.get("op", "") or "") in _HTTP_DIRECT_TOUCH_OPS
            and (
                str(act.get("op", "") or "") != "click_spec"
                or _click_spec_bounds_center(act.get("spec") or {}) is not None
            )
            for act in actions
        )
        if not all_direct_touch:
            return False
        if not U2_HTTP_DIRECT_TOUCH_ENABLED or self._http_rpc is None:
            if self._http_rpc is None:
                self._bump("http_direct_unavailable")
            return False
        return True

    def _run_http_direct_touch_actions(
        self,
        *,
        serial: str,
        actions: list[dict],
        early_exit: bool,
    ) -> dict:
        results: list[dict] = []
        stopped_at: int | None = None
        error: str | None = None
        for idx, act in enumerate(actions):
            op = str(act.get("op", "") or "")
            action_started = time.perf_counter()
            try:
                value: Any = None
                if op == "sleep":
                    _op_sleep(None, act)
                elif op == "u2_swipe_batch":
                    value = self._run_u2_swipe_batch(serial, act)
                else:
                    prepared = self._http_touch_rpc_payload(act, idx + 1)
                    if prepared is None or self._http_rpc is None:
                        raise RuntimeError(f"http direct unsupported op: {op}")
                    _prepared_op, payload, timeout = prepared
                    ok, rpc_error, _result = self._call_http_rpc(
                        serial,
                        payload,
                        timeout,
                    )
                    if not ok:
                        raise RuntimeError(rpc_error or "u2 HTTP direct failed")
                    if op == "click_spec":
                        self._bump("click_spec_http_direct")
                        self._bump("click_spec_http_direct_bounds")

                entry: dict = {
                    "op": op,
                    "ok": True,
                    "duration_ms": round((time.perf_counter() - action_started) * 1000, 1),
                }
                if value is not None:
                    entry["value"] = value
                results.append(entry)
                self._bump("http_direct_actions")
            except Exception as exc:
                self._bump("http_direct_failures")
                error = f"action[{idx}] {op}: {exc}"
                results.append({
                    "op": op,
                    "ok": False,
                    "error": str(exc),
                    "duration_ms": round((time.perf_counter() - action_started) * 1000, 1),
                })
                if early_exit:
                    stopped_at = idx
                    break

        ok = all(bool(item.get("ok")) for item in results) and len(results) == len(actions)
        return {
            "ok": ok,
            "stopped_at": stopped_at,
            "results": results,
            "error": None if ok else error,
        }

    def _run_http_click_center(self, serial: str, x: int, y: int) -> None:
        if self._http_rpc is None:
            raise RuntimeError("u2 HTTP RPC not configured")
        ok, error, _result = self._call_http_rpc(
            serial,
            {
                "jsonrpc": "2.0",
                "method": "click",
                "id": 1,
                "params": [x, y],
            },
            1.5,
        )
        if not ok:
            raise RuntimeError(error or "u2 HTTP direct click failed")

    async def _run_http_direct_touch_batch(
        self,
        *,
        serial: str,
        actions: list[dict],
        early_exit: bool,
        priority: str | int | None,
        deadline_ms: int | float | None,
        batch_started: float,
    ) -> dict:
        def _finish(payload: dict) -> dict:
            payload["total_ms"] = round((time.perf_counter() - batch_started) * 1000, 1)
            return payload

        if self._breaker_is_open(serial, priority=priority):
            self._bump("breaker_drops")
            return _finish({
                "ok": False,
                "stopped_at": 0,
                "results": [],
                "error": self._breaker_error(serial),
            })

        self.begin_ui_mutation(serial)
        try:
            async with self._admit(
                serial=serial,
                priority=priority,
                deadline_ms=deadline_ms,
            ):
                result = await self._run_sync(
                    lambda: self._run_http_direct_touch_actions(
                        serial=serial,
                        actions=actions,
                        early_exit=early_exit,
                    )
                )
            self._bump("http_direct_batches")
            self._record_outcome(
                serial,
                bool(result.get("ok")),
                None if result.get("ok") else str(result.get("error") or ""),
            )
            return _finish(result)
        except TimeoutError as exc:
            self._record_outcome(serial, False, str(exc))
            return _finish({"ok": False, "stopped_at": 0, "results": [], "error": str(exc)})
        finally:
            self.end_ui_mutation(serial)

    def _wait_xml_selector(self, act: dict) -> dict | None:
        op = str(act.get("op", "") or "")
        if op in {"wait_exists", "wait_gone"}:
            selector = act.get("selector", {})
            return selector if _xml_selector_supported(selector) else None
        if op == "wait_exists_spec":
            return _xml_selector_from_simple_spec(act.get("spec") or {})
        return None

    def _can_run_http_wait_batch(self, actions: list[dict], cancel_event: Any) -> bool:
        if (
            not U2_HTTP_WAIT_POLL_ENABLED
            or self._http_dump is None
            or cancel_event is not None
            or len(actions) != 1
            or not isinstance(actions[0], dict)
        ):
            return False
        if str(actions[0].get("op", "") or "") not in {
            "wait_exists",
            "wait_exists_spec",
            "wait_gone",
        }:
            return False
        if self._wait_xml_selector(actions[0]) is None:
            self._bump("http_wait_fallbacks")
            return False
        return True

    async def _run_http_wait_batch(
        self,
        *,
        serial: str,
        act: dict,
        early_exit: bool,
        priority: str | int | None,
        deadline_ms: int | float | None,
        batch_started: float,
    ) -> dict:
        def _finish_from_entry(entry: dict) -> dict:
            ok = bool(entry.get("ok"))
            return {
                "ok": ok,
                "stopped_at": None if ok or not early_exit else 0,
                "results": [dict(entry)],
                "error": None if ok else str(entry.get("error") or "wait failed"),
                "total_ms": round((time.perf_counter() - batch_started) * 1000, 1),
            }

        op = str(act.get("op", "") or "")
        selector = self._wait_xml_selector(act)
        if selector is None:
            self._bump("http_wait_fallbacks")
            return _finish_from_entry({
                "op": op,
                "ok": False,
                "error": "wait selector not supported by http xml poll",
                "duration_ms": 0.0,
            })

        timeout = max(
            0.0,
            min(float(act.get("timeout", 5.0) or 0.0), U2_HTTP_WAIT_TIMEOUT_CAP_S),
        )
        action_started = time.perf_counter()
        poll_result = await self._poll_xml_selector_node(
            serial=serial,
            selector=selector,
            timeout_s=timeout,
            compressed=bool(act.get("compressed", False)),
            want_present=op != "wait_gone",
            priority=priority,
            deadline_ms=deadline_ms,
            batch_started=batch_started,
            poll_stat="http_wait_polls",
            bypass_first_cache=op == "wait_gone",
        )
        self._bump("http_wait_batches")
        if poll_result["satisfied"]:
            self._bump("http_wait_hits")
        else:
            self._bump("http_wait_misses")
        return _finish_from_entry({
            "op": op,
            "ok": True,
            "value": bool(poll_result["satisfied"]),
            "polls": int(poll_result.get("polls") or 0),
            "duration_ms": round((time.perf_counter() - action_started) * 1000, 1),
            **({"last_error": poll_result["error"]} if poll_result.get("error") else {}),
        })

    async def _poll_xml_selector_node(
        self,
        *,
        serial: str,
        selector: dict,
        timeout_s: float,
        compressed: bool,
        want_present: bool,
        priority: str | int | None,
        deadline_ms: int | float | None,
        batch_started: float,
        poll_stat: str,
        bypass_first_cache: bool = False,
    ) -> dict:
        key = self._xml_poll_key(
            serial=serial,
            selector=selector,
            timeout_s=timeout_s,
            compressed=compressed,
            want_present=want_present,
            priority=priority,
            deadline_ms=deadline_ms,
            poll_stat=poll_stat,
            bypass_first_cache=bypass_first_cache,
        )
        async with self._xml_poll_inflight_lock:
            task = self._xml_poll_inflight.get(key)
            leader = False
            if task is None or task.done():
                task = self._loop.create_task(
                    self._poll_xml_selector_node_uncached(
                        serial=serial,
                        selector=selector,
                        timeout_s=timeout_s,
                        compressed=compressed,
                        want_present=want_present,
                        priority=priority,
                        deadline_ms=deadline_ms,
                        batch_started=batch_started,
                        poll_stat=poll_stat,
                        bypass_first_cache=bypass_first_cache,
                    )
                )
                self._xml_poll_inflight[key] = task
                leader = True
                self._bump("xml_poll_coalesced_leaders")
            else:
                self._bump("xml_poll_coalesced_joins")

        try:
            deadline = self._effective_deadline_ms(deadline_ms)
            if deadline > 0:
                remaining = max(
                    0.001,
                    deadline / 1000.0 - (time.perf_counter() - batch_started),
                )
                result = await asyncio.wait_for(asyncio.shield(task), timeout=remaining)
            else:
                result = await task
            return dict(result)
        except asyncio.TimeoutError:
            self._bump("deadline_drops")
            return {
                "satisfied": False,
                "node": None,
                "polls": 0,
                "error": "u2 command deadline exceeded while waiting for XML poll",
            }
        finally:
            if leader:
                async with self._xml_poll_inflight_lock:
                    if self._xml_poll_inflight.get(key) is task:
                        self._xml_poll_inflight.pop(key, None)

    async def _poll_xml_selector_node_uncached(
        self,
        *,
        serial: str,
        selector: dict,
        timeout_s: float,
        compressed: bool,
        want_present: bool,
        priority: str | int | None,
        deadline_ms: int | float | None,
        batch_started: float,
        poll_stat: str,
        bypass_first_cache: bool = False,
    ) -> dict:
        timeout = max(0.0, min(timeout_s, U2_HTTP_WAIT_TIMEOUT_CAP_S))
        poll_s = (
            U2_HTTP_WAIT_VISIBLE_POLL_S
            if self._is_visible_priority(priority)
            else U2_HTTP_WAIT_BACKGROUND_POLL_S
        )
        deadline_at = time.perf_counter() + timeout
        polls = 0
        last_error = ""
        while True:
            if self._breaker_is_open(serial, priority=priority):
                self._bump("breaker_drops")
                return {
                    "satisfied": False,
                    "node": None,
                    "polls": polls,
                    "error": self._breaker_error(serial),
                }
            dump_timeout = max(0.2, min(1.0, deadline_at - time.perf_counter()))
            dump_act = {
                "op": "dump_hierarchy",
                "timeout": dump_timeout,
                "compressed": compressed,
            }
            dump_key = self._single_dump_cache_key(serial, dump_act)
            dump_result = await self._run_single_dump_batch(
                serial=serial,
                act=dump_act,
                early_exit=True,
                priority=priority,
                deadline_ms=deadline_ms,
                batch_started=batch_started,
                bypass_cache=bypass_first_cache or polls > 0,
            )
            polls += 1
            self._bump(poll_stat)
            dump_entry = dict(dump_result["results"][0])
            node = None
            found = False
            if dump_entry.get("ok") and dump_entry.get("value"):
                try:
                    xml_index = self._xml_index_from_dump(
                        dump_key,
                        str(dump_entry.get("value") or ""),
                        priority=priority,
                    )
                    node = xml_index.find(selector)
                    found = node is not None
                except Exception as exc:
                    last_error = str(exc)
                    self._bump("xml_parse_errors")
                    found = False
            else:
                last_error = str(dump_entry.get("error") or "dump_hierarchy unavailable")

            if found == want_present:
                return {
                    "satisfied": True,
                    "node": node,
                    "polls": polls,
                    "error": None,
                }
            remaining = deadline_at - time.perf_counter()
            if remaining <= 0:
                return {
                    "satisfied": False,
                    "node": node,
                    "polls": polls,
                    "error": last_error,
                }
            await asyncio.sleep(min(poll_s, remaining))

    def _can_run_http_flow(self, flow: str, params: dict) -> bool:
        if (
            not U2_HTTP_WAIT_POLL_ENABLED
            or not U2_HTTP_DIRECT_TOUCH_ENABLED
            or self._http_rpc is None
            or flow not in {"wait_and_click", "find_click_wait", "swipe_until_found"}
            or not isinstance(params, dict)
        ):
            return False
        selector = _selector_from_flow_params(params)
        if flow == "swipe_until_found":
            supported = _u2_selector_payload(selector) is not None
        else:
            supported = self._http_dump is not None and _xml_selector_supported(selector)
        if not supported:
            self._bump("http_flow_fallbacks")
            return False
        return True

    def _flow_window_size_from_params(self, params: dict) -> tuple[int, int] | None:
        raw = params.get("window_size")
        if raw is None:
            raw = params.get("size")
        try:
            if isinstance(raw, (list, tuple)) and len(raw) >= 2:
                width = int(raw[0])
                height = int(raw[1])
                if width > 0 and height > 0:
                    return width, height
            if isinstance(raw, dict):
                width = int(raw.get("width") or raw.get("w") or 0)
                height = int(raw.get("height") or raw.get("h") or 0)
                if width > 0 and height > 0:
                    return width, height
            width = int(params.get("width") or params.get("w") or 0)
            height = int(params.get("height") or params.get("h") or 0)
            if width > 0 and height > 0:
                return width, height
        except (TypeError, ValueError):
            return None
        return None

    def _flow_swipe_vector(self, params: dict) -> tuple[int, int, int, int] | None:
        size = self._flow_window_size_from_params(params)
        if size is None:
            return None
        width, height = size
        direction = str(params.get("direction", "up") or "up")
        try:
            step_ratio = float(params.get("step_ratio", 0.6))
        except (TypeError, ValueError):
            return None
        cx, cy = width // 2, height // 2
        dy = int(height * step_ratio / 2)
        dx = int(width * step_ratio / 2)
        vectors = {
            "up": (cx, cy + dy, cx, cy - dy),
            "down": (cx, cy - dy, cx, cy + dy),
            "left": (cx + dx, cy, cx - dx, cy),
            "right": (cx - dx, cy, cx + dx, cy),
        }
        return vectors.get(direction, vectors["up"])

    def _run_http_flow_swipe(
        self,
        serial: str,
        vector: tuple[int, int, int, int],
        duration: float,
    ) -> None:
        if self._http_rpc is None:
            raise RuntimeError("u2 HTTP RPC not configured")
        fx, fy, tx, ty = vector
        duration = max(0.0, min(0.8, duration))
        steps = max(1, int(duration * 40))
        timeout = max(1.5, duration + 0.8)
        ok, error, _result = self._call_http_rpc(
            serial,
            {
                "jsonrpc": "2.0",
                "method": "swipe",
                "id": 1,
                "params": [fx, fy, tx, ty, steps],
            },
            timeout,
        )
        if not ok:
            raise RuntimeError(error or "u2 HTTP direct swipe failed")

    async def _run_http_flow(
        self,
        *,
        serial: str,
        flow: str,
        params: dict,
        priority: str | int | None,
        deadline_ms: int | float | None,
        batch_started: float,
    ) -> dict | None:
        if not self._can_run_http_flow(flow, params):
            return None
        if self._breaker_is_open(serial, priority=priority):
            self._bump("breaker_drops")
            return {"ok": False, "value": None, "error": self._breaker_error(serial)}

        selector = _selector_from_flow_params(params)
        compressed = bool(params.get("compressed", False))
        if flow == "swipe_until_found":
            vector = self._flow_swipe_vector(params)
            if vector is None:
                self._bump("http_flow_fallbacks")
                return None
            max_swipes = max(0, int(params.get("max_swipes", DEFAULT_SCROLL_MAX_SWIPES)))
            try:
                duration = float(params.get("duration", DEFAULT_SWIPE_DURATION))
            except (TypeError, ValueError):
                self._bump("http_flow_fallbacks")
                return None
            for swipes in range(max_swipes + 1):
                try:
                    found = await self._run_sync(
                        lambda: self._run_http_exists_rpc(serial, selector)
                    )
                    self._bump("http_flow_polls")
                except Exception:
                    self._bump("http_exists_fallbacks")
                    if self._http_dump is None:
                        self._bump("http_flow_fallbacks")
                        return None
                    xml_found = await self._poll_xml_selector_node(
                        serial=serial,
                        selector=selector,
                        timeout_s=0.0,
                        compressed=compressed,
                        want_present=True,
                        priority=priority,
                        deadline_ms=deadline_ms,
                        batch_started=batch_started,
                        poll_stat="http_flow_polls",
                        bypass_first_cache=swipes > 0,
                    )
                    found = bool(xml_found["satisfied"])
                if found:
                    self._bump("http_flow_fastpaths")
                    self._bump("http_flow_hits")
                    self._record_outcome(serial, True)
                    return {
                        "ok": True,
                        "value": {"found": True, "swipes": swipes},
                        "error": None,
                    }
                if swipes >= max_swipes:
                    break
                self.begin_ui_mutation(serial)
                try:
                    async with self._admit(
                        serial=serial,
                        priority=priority,
                        deadline_ms=deadline_ms,
                    ):
                        await self._run_sync(
                            lambda: self._run_http_flow_swipe(serial, vector, duration)
                        )
                    self._bump("http_direct_actions")
                    self._bump("http_flow_swipes")
                except Exception as exc:
                    self._bump("http_flow_fastpaths")
                    self._bump("http_flow_failures")
                    self._record_outcome(serial, False, str(exc))
                    return {"ok": False, "value": None, "error": str(exc)}
                finally:
                    self.end_ui_mutation(serial)

            self._bump("http_flow_fastpaths")
            self._bump("http_flow_misses")
            self._record_outcome(serial, True)
            return {
                "ok": True,
                "value": {"found": False, "swipes": max_swipes},
                "error": None,
            }

        wait_timeout = (
            float(params.get("click_timeout", DEFAULT_FLOW_WAIT_TIMEOUT))
            if flow == "find_click_wait"
            else float(params.get("wait_timeout", DEFAULT_FLOW_WAIT_TIMEOUT))
        )
        wait_timeout = min(wait_timeout, MAX_FLOW_TIMEOUT)
        appeared = await self._poll_xml_selector_node(
            serial=serial,
            selector=selector,
            timeout_s=wait_timeout,
            compressed=compressed,
            want_present=True,
            priority=priority,
            deadline_ms=deadline_ms,
            batch_started=batch_started,
            poll_stat="http_flow_polls",
        )
        if not appeared["satisfied"]:
            self._bump("http_flow_fastpaths")
            self._bump("http_flow_misses")
            self._record_outcome(serial, True)
            value = {"found": False, "clicked": False}
            if flow == "find_click_wait":
                value["gone"] = False
            return {"ok": True, "value": value, "error": None}

        node = appeared.get("node")
        center = _xml_bounds_center(node) if node is not None else None
        if center is None:
            self._bump("http_flow_fallbacks")
            return None

        self.begin_ui_mutation(serial)
        try:
            async with self._admit(
                serial=serial,
                priority=priority,
                deadline_ms=self._single_dump_deadline_ms(deadline_ms, priority=priority),
            ):
                await self._run_sync(
                    lambda: self._run_http_click_center(serial, center[0], center[1])
                )
            self._bump("http_direct_actions")
        except Exception as exc:
            self._bump("http_flow_fastpaths")
            self._bump("http_flow_failures")
            self._record_outcome(serial, False, str(exc))
            return {"ok": False, "value": None, "error": str(exc)}
        finally:
            self.end_ui_mutation(serial)

        value = {"found": True, "clicked": True}
        if flow == "find_click_wait":
            gone_timeout = min(
                float(params.get("gone_timeout", DEFAULT_FLOW_GONE_TIMEOUT)),
                MAX_FLOW_TIMEOUT,
            )
            gone = await self._poll_xml_selector_node(
                serial=serial,
                selector=selector,
                timeout_s=gone_timeout,
                compressed=compressed,
                want_present=False,
                priority=priority,
                deadline_ms=deadline_ms,
                batch_started=batch_started,
                poll_stat="http_flow_polls",
                bypass_first_cache=True,
            )
            value["gone"] = bool(gone["satisfied"])

        self._bump("http_flow_fastpaths")
        self._bump("http_flow_hits")
        self._record_outcome(serial, True)
        return {"ok": True, "value": value, "error": None}

    async def _run_sync(self, fn: Callable[[], T]) -> T:
        try:
            from relay.runtime import u2_executor_pool
            executor = u2_executor_pool()
        except Exception:
            executor = None
        return await self._loop.run_in_executor(executor, fn)

    async def _execute_single_dump_entry(
        self,
        *,
        serial: str,
        act: dict,
        priority: str | int | None,
        deadline_ms: int | float | None,
    ) -> dict:
        if self._breaker_is_open(serial, priority=priority):
            self._bump("breaker_drops")
            return {
                "op": "dump_hierarchy",
                "ok": False,
                "error": self._breaker_error(serial),
                "duration_ms": 0.0,
            }
        action_started = time.perf_counter()
        try:
            async with self._admit(
                serial=serial,
                priority=priority,
                deadline_ms=self._single_dump_deadline_ms(deadline_ms, priority=priority),
            ):
                timeout = float(act.get("timeout") or act.get("timeout_s") or 5.0)
                compressed = bool(act.get("compressed", False))
                fn = _OP_TABLE["dump_hierarchy"]
                try:
                    value = ""
                    if self._http_dump is not None:
                        self._bump("dump_http_direct")
                        value = await self._run_sync(
                            lambda: self._http_dump(serial, timeout, compressed)
                        )
                        if value:
                            self._mark_direct_http_healthy(serial)
                    if not value:
                        if self._http_dump is not None:
                            self._bump("dump_pool_fallbacks")
                            logger.debug(
                                "u2_batch: atx-http dump empty serial=%s — "
                                "fallback to u2 dump_hierarchy",
                                serial,
                            )
                        value = await _run_with_retry(
                            self._pool,
                            self._loop,
                            serial,
                            lambda dev: fn(dev, act),
                        )
                    entry: dict = {
                        "op": "dump_hierarchy",
                        "ok": True,
                        "duration_ms": round((time.perf_counter() - action_started) * 1000, 1),
                    }
                    if value is not None:
                        entry["value"] = value
                    self._record_outcome(serial, True)
                    return entry
                except Exception as exc:
                    error = str(exc)
                    self._record_outcome(serial, False, error)
                    return {
                        "op": "dump_hierarchy",
                        "ok": False,
                        "error": error,
                        "duration_ms": round((time.perf_counter() - action_started) * 1000, 1),
                    }
        except TimeoutError as exc:
            error = str(exc)
            self._record_outcome(serial, False, error)
            return {
                "op": "dump_hierarchy",
                "ok": False,
                "error": error,
                "duration_ms": round((time.perf_counter() - action_started) * 1000, 1),
            }

    async def _run_single_dump_batch(
        self,
        *,
        serial: str,
        act: dict,
        early_exit: bool,
        priority: str | int | None,
        deadline_ms: int | float | None,
        batch_started: float,
        bypass_cache: bool = False,
    ) -> dict:
        def _finish_from_entry(entry: dict) -> dict:
            ok = bool(entry.get("ok"))
            self._bump_hierarchy_result(priority, ok=ok)
            return {
                "ok": ok,
                "stopped_at": None if ok or not early_exit else 0,
                "results": [dict(entry)],
                "error": None if ok else str(entry.get("error") or "dump_hierarchy failed"),
                "total_ms": round((time.perf_counter() - batch_started) * 1000, 1),
            }

        self._bump_hierarchy_request(priority)
        key = self._single_dump_cache_key(serial, act)
        inflight_key = self._single_dump_inflight_key(serial, act, priority)
        bypass_cache = bypass_cache or _force_fresh_xml(act)
        if not bypass_cache:
            cached = self._cached_single_dump(key, priority=priority)
            if cached is not None:
                return _finish_from_entry(
                    {
                        "op": "dump_hierarchy",
                        "ok": True,
                        "value": cached,
                        "duration_ms": 0.0,
                    }
                )

        if not U2_HIERARCHY_SINGLEFLIGHT_ENABLED:
            entry = await self._execute_single_dump_entry(
                serial=serial,
                act=act,
                priority=priority,
                deadline_ms=deadline_ms,
            )
            if entry.get("ok") and entry.get("value"):
                self._store_single_dump_cache(key, str(entry["value"]), priority=priority)
            return _finish_from_entry(entry)

        async with self._dump_inflight_lock:
            task = self._dump_inflight.get(inflight_key)
            leader = False
            if task is None or task.done():
                task = self._loop.create_task(
                    self._execute_single_dump_entry(
                        serial=serial,
                        act=act,
                        priority=priority,
                        deadline_ms=deadline_ms,
                    )
                )
                self._dump_inflight[inflight_key] = task
                leader = True
                self._bump("dump_singleflight_leaders")
                self._bump(f"dump_{self._lane_prefix(priority)}_singleflight_leaders")
            else:
                self._bump("dump_singleflight_joins")
                self._bump(f"dump_{self._lane_prefix(priority)}_singleflight_joins")

        try:
            deadline = self._single_dump_deadline_ms(deadline_ms, priority=priority)
            if deadline > 0:
                remaining = max(
                    0.001,
                    deadline / 1000.0 - (time.perf_counter() - batch_started),
                )
                entry = await asyncio.wait_for(asyncio.shield(task), timeout=remaining)
            else:
                entry = await task
        except asyncio.TimeoutError:
            self._bump("deadline_drops")
            self._bump_lane("deadline_drops", priority)
            entry = {
                "op": "dump_hierarchy",
                "ok": False,
                "error": "u2 command deadline exceeded while waiting for dump_hierarchy",
                "duration_ms": round((time.perf_counter() - batch_started) * 1000, 1),
            }
        finally:
            if leader:
                async with self._dump_inflight_lock:
                    if self._dump_inflight.get(inflight_key) is task:
                        self._dump_inflight.pop(inflight_key, None)

        if entry.get("ok") and entry.get("value"):
            self._store_single_dump_cache(key, str(entry["value"]), priority=priority)
        return _finish_from_entry(entry)

    def _can_optimize_xml_read_batch(self, actions: list[dict], cancel_event: Any) -> bool:
        if not U2_XML_BATCH_OPTIMIZER_ENABLED or cancel_event is not None:
            return False
        if len(actions) < 2 or not isinstance(actions[0], dict):
            return False
        if actions[0].get("op") != "dump_hierarchy":
            return False
        compressed = bool(actions[0].get("compressed", False))
        click_seen = False
        for idx, act in enumerate(actions):
            if not isinstance(act, dict):
                return False
            op = act.get("op")
            if op == "dump_hierarchy":
                if bool(act.get("compressed", False)) != compressed:
                    return False
                continue
            if click_seen:
                return False
            if op == "click_selector":
                if idx != len(actions) - 1 or self._http_rpc is None:
                    return False
                click_seen = True
            elif op == "click_spec":
                if idx != len(actions) - 1 or self._http_rpc is None:
                    return False
                spec = act.get("spec") or {}
                if (
                    _click_spec_bounds_center(spec) is None
                    and _xml_selector_from_click_spec(spec) is None
                ):
                    return False
                click_seen = True
            elif op not in {"exists", "get_text"}:
                return False
            if op == "click_spec":
                continue
            if not _xml_selector_supported(act.get("selector", {})):
                self._bump("xml_optimizer_fallbacks")
                return False
        return True

    async def _run_xml_read_batch(
        self,
        *,
        serial: str,
        actions: list[dict],
        early_exit: bool,
        priority: str | int | None,
        deadline_ms: int | float | None,
        batch_started: float,
    ) -> dict | None:
        def _finish(payload: dict) -> dict:
            payload["total_ms"] = round((time.perf_counter() - batch_started) * 1000, 1)
            return payload

        dump_result = await self._run_single_dump_batch(
            serial=serial,
            act=actions[0],
            early_exit=early_exit,
            priority=priority,
            deadline_ms=deadline_ms,
            batch_started=batch_started,
        )
        dump_entry = dict(dump_result["results"][0])
        if not dump_entry.get("ok"):
            if early_exit:
                return dump_result
            results = [dump_entry]
            for idx, act in enumerate(actions[1:], start=1):
                results.append({
                    "op": act.get("op", ""),
                    "ok": False,
                    "error": "dump_hierarchy unavailable",
                    "duration_ms": 0.0,
                })
                if early_exit:
                    return _finish({
                        "ok": False,
                        "stopped_at": idx,
                        "results": results,
                        "error": "dump_hierarchy unavailable",
                    })
            return _finish({
                "ok": False,
                "stopped_at": None,
                "results": results,
                "error": str(dump_entry.get("error") or "dump_hierarchy failed"),
            })

        xml = str(dump_entry.get("value") or "")
        try:
            xml_index = self._xml_index_from_dump(
                self._single_dump_cache_key(serial, actions[0]),
                xml,
                priority=priority,
            )
        except Exception:
            self._bump("xml_parse_errors")
            self._bump("xml_optimizer_fallbacks")
            return None
        results: list[dict] = []
        stopped_at: int | None = None
        error: str | None = None

        async def _click_center(center: tuple[int, int], op: str, *, direct_bounds: bool) -> None:
            x, y = center
            self.begin_ui_mutation(serial)
            try:
                if self._breaker_is_open(serial, priority=priority):
                    self._bump("breaker_drops")
                    raise RuntimeError(self._breaker_error(serial))
                async with self._admit(
                    serial=serial,
                    priority=priority,
                    deadline_ms=deadline_ms,
                ):
                    await self._run_sync(lambda: self._run_http_click_center(serial, x, y))
                self._record_outcome(serial, True)
                self._bump("http_direct_actions")
                self._bump("xml_click_fused")
                if op == "click_spec":
                    self._bump("click_spec_http_direct")
                    if direct_bounds:
                        self._bump("click_spec_http_direct_bounds")
            except Exception as exc:
                self._record_outcome(serial, False, str(exc))
                self._bump("http_direct_failures")
                self._bump("xml_click_failures")
                raise
            finally:
                self.end_ui_mutation(serial)

        for idx, act in enumerate(actions):
            action_started = time.perf_counter()
            op = str(act.get("op", "") or "")
            try:
                if op == "dump_hierarchy":
                    entry = dict(dump_entry)
                    if idx > 0:
                        entry["duration_ms"] = 0.0
                        self._bump("xml_u2_calls_avoided")
                    results.append(entry)
                    continue

                direct_click_center: tuple[int, int] | None = None
                if op == "click_spec":
                    spec = act.get("spec") or {}
                    direct_click_center = _click_spec_bounds_center(spec)
                    selector = _xml_selector_from_click_spec(spec)
                    if direct_click_center is None and selector is None:
                        raise RuntimeError("click_spec not supported by xml optimizer")
                    if direct_click_center is not None:
                        self._bump("xml_u2_calls_avoided")
                        await _click_center(direct_click_center, op, direct_bounds=True)
                        results.append({
                            "op": op,
                            "ok": True,
                            "value": True,
                            "duration_ms": round(
                                (time.perf_counter() - action_started) * 1000,
                                1,
                            ),
                        })
                        continue
                    node = xml_index.find(selector or {})
                else:
                    node = xml_index.find(act.get("selector", {}))
                self._bump("xml_u2_calls_avoided")
                if node is None:
                    self._bump("xml_selector_misses")
                    if op == "exists":
                        results.append({
                            "op": op,
                            "ok": True,
                            "value": False,
                            "duration_ms": round(
                                (time.perf_counter() - action_started) * 1000,
                                1,
                            ),
                        })
                        continue
                    if op in {"click_selector", "click_spec"}:
                        self._bump("xml_click_misses")
                        results.append({
                            "op": op,
                            "ok": True,
                            "value": False,
                            "duration_ms": round(
                                (time.perf_counter() - action_started) * 1000,
                                1,
                            ),
                        })
                        continue
                    raise RuntimeError("selector not found")

                self._bump("xml_selector_hits")
                value: Any = True
                if op == "get_text":
                    value = node.attrib.get("text", "")
                elif op in {"click_selector", "click_spec"}:
                    center = _xml_bounds_center(node)
                    if center is None:
                        self._bump("xml_click_no_bounds")
                        self._bump("xml_optimizer_fallbacks")
                        return None
                    await _click_center(center, op, direct_bounds=False)
                results.append({
                    "op": op,
                    "ok": True,
                    "value": value,
                    "duration_ms": round(
                        (time.perf_counter() - action_started) * 1000,
                        1,
                    ),
                })
            except Exception as exc:
                error = f"action[{idx}] {op}: {exc}"
                results.append({
                    "op": op,
                    "ok": False,
                    "error": str(exc),
                    "duration_ms": round(
                        (time.perf_counter() - action_started) * 1000,
                        1,
                    ),
                })
                if early_exit:
                    stopped_at = idx
                    break

        ok = all(bool(item.get("ok")) for item in results) and len(results) == len(actions)
        self._bump("xml_batch_optimized")
        return _finish({
            "ok": ok,
            "stopped_at": stopped_at,
            "results": results,
            "error": None if ok else error,
        })

    async def run_batch(
        self,
        serial: str,
        actions: list[dict],
        early_exit: bool = True,
        cancel_event: Any = None,
        priority: str | int | None = None,
        deadline_ms: int | float | None = None,
    ) -> dict:
        batch_started = time.perf_counter()

        def _finish(payload: dict) -> dict:
            payload["total_ms"] = round((time.perf_counter() - batch_started) * 1000, 1)
            return payload

        if not actions:
            return _finish({"ok": True, "stopped_at": None, "results": [], "error": None})

        if len(actions) > MAX_BATCH_ACTIONS:
            logger.warning(
                "u2_batch: %d actions exceeds cap %d, truncating",
                len(actions),
                MAX_BATCH_ACTIONS,
            )
            actions = actions[:MAX_BATCH_ACTIONS]

        if (
            len(actions) == 1
            and isinstance(actions[0], dict)
            and actions[0].get("op") == "dump_hierarchy"
            and cancel_event is None
        ):
            return await self._run_single_dump_batch(
                serial=serial,
                act=actions[0],
                early_exit=early_exit,
                priority=priority,
                deadline_ms=deadline_ms,
                batch_started=batch_started,
            )

        if self._can_run_http_wait_batch(actions, cancel_event):
            return await self._run_http_wait_batch(
                serial=serial,
                act=actions[0],
                early_exit=early_exit,
                priority=priority,
                deadline_ms=deadline_ms,
                batch_started=batch_started,
            )

        if self._can_run_http_direct_touch_batch(actions, cancel_event):
            return await self._run_http_direct_touch_batch(
                serial=serial,
                actions=actions,
                early_exit=early_exit,
                priority=priority,
                deadline_ms=deadline_ms,
                batch_started=batch_started,
            )

        if self._can_optimize_xml_read_batch(actions, cancel_event):
            optimized = await self._run_xml_read_batch(
                serial=serial,
                actions=actions,
                early_exit=early_exit,
                priority=priority,
                deadline_ms=deadline_ms,
                batch_started=batch_started,
            )
            if optimized is not None:
                return optimized

        mutates_ui = any(
            action.get("op") not in _READ_ONLY_BATCH_OPS
            for action in actions
        )
        if self._breaker_is_open(serial, priority=priority):
            self._bump("breaker_drops")
            return _finish({
                "ok": False,
                "stopped_at": 0,
                "results": [],
                "error": self._breaker_error(serial),
            })

        def _run_actions(dev: Any) -> dict:
            results: list[dict] = []
            for idx, act in enumerate(actions):
                if cancel_event is not None and cancel_event.is_set():
                    return _finish({
                        "ok": False,
                        "stopped_at": idx,
                        "results": results,
                        "error": "cancelled",
                        "cancelled": True,
                    })
                op = act.get("op", "")
                fn = None if op == "u2_swipe_batch" else _OP_TABLE.get(op)
                if op != "u2_swipe_batch" and fn is None:
                    results.append({
                        "op": op,
                        "ok": False,
                        "error": f"unknown op: {op}",
                        "duration_ms": 0.0,
                    })
                    if early_exit:
                        return _finish({
                            "ok": False,
                            "stopped_at": idx,
                            "results": results,
                            "error": f"action[{idx}] unknown op: {op}",
                        })
                    continue
                action_started = time.perf_counter()
                try:
                    if op == "u2_swipe_batch":
                        value = self._run_u2_swipe_batch(serial, act)
                    elif op == "dump_hierarchy" and self._http_dump is not None:
                        timeout = float(act.get("timeout") or act.get("timeout_s") or 5.0)
                        compressed = bool(act.get("compressed", False))
                        value = self._http_dump(serial, timeout, compressed)
                        if value:
                            self._mark_direct_http_healthy(serial)
                        if not value:
                            logger.debug(
                                "u2_batch: atx-http dump empty serial=%s — "
                                "fallback to u2 dump_hierarchy",
                                serial,
                            )
                            value = fn(dev, act)
                    else:
                        value = fn(dev, act)
                    if (
                        op == "app_start"
                        and act.get("use_monkey")
                        and lock_rotation_after_shell_enabled()
                    ):
                        lock_portrait_rotation(serial)
                    entry: dict = {"op": op, "ok": True}
                    if value is not None:
                        entry["value"] = value
                    entry["duration_ms"] = round((time.perf_counter() - action_started) * 1000, 1)
                    results.append(entry)
                    if (
                        cancel_event is not None
                        and cancel_event.is_set()
                        and idx + 1 < len(actions)
                    ):
                        return _finish({
                            "ok": False,
                            "stopped_at": idx + 1,
                            "results": results,
                            "error": "cancelled",
                            "cancelled": True,
                        })
                except Exception as exc:
                    results.append({
                        "op": op,
                        "ok": False,
                        "error": str(exc),
                        "duration_ms": round((time.perf_counter() - action_started) * 1000, 1),
                    })
                    if early_exit:
                        return _finish({
                            "ok": False,
                            "stopped_at": idx,
                            "results": results,
                            "error": f"action[{idx}] {op}: {exc}",
                        })
            return _finish({"ok": True, "stopped_at": None, "results": results, "error": None})

        if mutates_ui:
            self.begin_ui_mutation(serial)
        try:
            try:
                async with self._admit(
                    serial=serial,
                    priority=priority,
                    deadline_ms=deadline_ms,
                ):
                    result = await _run_with_retry(
                        self._pool,
                        self._loop,
                        serial,
                        _run_actions,
                    )
                self._record_outcome(
                    serial,
                    bool(result.get("ok")),
                    None if result.get("ok") else str(result.get("error") or ""),
                )
                return result
            except TimeoutError as exc:
                self._record_outcome(serial, False, str(exc))
                return _finish({"ok": False, "stopped_at": 0, "results": [], "error": str(exc)})
            except Exception as exc:
                self._record_outcome(serial, False, str(exc))
                return _finish({"ok": False, "stopped_at": 0, "results": [], "error": str(exc)})
        finally:
            if mutates_ui:
                self.end_ui_mutation(serial)

    async def execute_flow(
        self,
        serial: str,
        flow: str,
        params: dict,
        *,
        priority: str | int | None = None,
        deadline_ms: int | float | None = None,
    ) -> dict:
        fn = _FLOW_TABLE.get(flow)
        if fn is None:
            return {"ok": False, "value": None, "error": f"unknown flow: {flow}"}
        if self._breaker_is_open(serial, priority=priority):
            self._bump("breaker_drops")
            return {"ok": False, "value": None, "error": self._breaker_error(serial)}
        batch_started = time.perf_counter()
        optimized = await self._run_http_flow(
            serial=serial,
            flow=flow,
            params=params,
            priority=priority,
            deadline_ms=deadline_ms,
            batch_started=batch_started,
        )
        if optimized is not None:
            return optimized
        self.begin_ui_mutation(serial)
        try:
            async with self._admit(
                serial=serial,
                priority=priority,
                deadline_ms=deadline_ms,
            ):
                value = await _run_with_retry(
                    self._pool, self._loop, serial,
                    lambda d, _fn=fn, _p=params: _fn(d, _p),
                )
            self._record_outcome(serial, True)
            return {"ok": True, "value": value, "error": None}
        except TimeoutError as exc:
            self._record_outcome(serial, False, str(exc))
            return {"ok": False, "value": None, "error": str(exc)}
        except Exception as exc:
            logger.warning("u2_flow %s failed serial=%s: %s", flow, serial, exc)
            self._record_outcome(serial, False, str(exc))
            return {"ok": False, "value": None, "error": str(exc)}
        finally:
            self.end_ui_mutation(serial)

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
