"""
relay/u2_executor.py — Batch + Flow executor for uiautomator2.

Batch: execute a list of primitive actions in one gRPC round-trip.
Flow:  execute named high-level patterns (find+click+wait, scroll-search, etc.)

All blocking u2 calls run in `loop.run_in_executor(None, ...)`.
"""
from __future__ import annotations

import asyncio
import base64
import io
import hashlib
import inspect
import json
import logging
import os
import re
import time
import unicodedata
from collections import deque
from contextlib import asynccontextmanager
from typing import Any, Awaitable, Callable, Optional, TypeVar

from lxml import etree as LET

from relay.adb import _adb_shell, lock_portrait_rotation, lock_rotation_after_shell_enabled
from relay.extra_data.parsers.facebook.comment_pipeline import (
    parse_fb_comments_from_xml_with_diagnostic,
)
from relay.fb_labels import MODE_EXACT, MODE_PHRASE, MODE_WORD, LabelSet
from relay.fb_labels import fold as _fold
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
# A swipe is a fling: the list keeps moving after the gesture returns. Probing
# the selector before it stops reads the mid-flight tree, misses the target, and
# fires the next swipe immediately — max_swipes burns as one burst.
DEFAULT_SWIPE_SETTLE_S = 0.35
MAX_SWIPE_SETTLE_S = 2.0


def _swipe_settle_s(p: dict) -> float:
    """Seconds to let a fling stop before re-probing the selector."""
    raw = p.get("settle_s", DEFAULT_SWIPE_SETTLE_S)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = DEFAULT_SWIPE_SETTLE_S
    return max(0.0, min(MAX_SWIPE_SETTLE_S, value))


def _first_wait_s(p: dict) -> float:
    """Seconds the first probe may wait for a still-rendering screen."""
    raw = p.get("first_wait_s", 0.0)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(MAX_FLOW_TIMEOUT, value))


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
_KEYEVENTS = {
    "home": "KEYCODE_HOME",
    "back": "KEYCODE_BACK",
    "recent": "KEYCODE_APP_SWITCH",
    "app_switch": "KEYCODE_APP_SWITCH",
    "menu": "KEYCODE_MENU",
    "power": "KEYCODE_POWER",
    "enter": "KEYCODE_ENTER",
    "tab": "KEYCODE_TAB",
    "delete": "KEYCODE_DEL",
    "del": "KEYCODE_DEL",
    "volume_up": "KEYCODE_VOLUME_UP",
    "volume_down": "KEYCODE_VOLUME_DOWN",
}
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


def _bounds_tuple_from_string(raw: str) -> tuple[int, int, int, int] | None:
    match = _XML_BOUNDS_RE.match(str(raw or ""))
    if match is None:
        return None
    left, top, right, bottom = (int(group) for group in match.groups())
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


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


def _adb_keyevent_name(key: Any) -> str | None:
    raw = str(key or "").strip()
    if not raw:
        return None
    lower = raw.lower()
    if lower in _KEYEVENTS:
        return _KEYEVENTS[lower]
    upper = raw.upper()
    if upper.startswith("KEYCODE_"):
        return upper
    if raw.isdigit():
        return raw
    return None


def _adb_key_command(key: Any) -> str | None:
    raw = str(key or "").strip().lower()
    if raw == "home":
        return "am start -a android.intent.action.MAIN -c android.intent.category.HOME"
    keyevent = _adb_keyevent_name(key)
    if keyevent:
        return f"input keyevent {keyevent}"
    return None


def _press_key_via_adb(serial: str, key: Any) -> bool:
    cmd = _adb_key_command(key)
    if not serial or not cmd:
        return False
    output, rc = _adb_shell(serial, cmd, timeout=5)
    if rc != 0:
        logger.warning(
            "u2_batch: adb key fallback failed serial=%s key=%s output=%s",
            serial,
            key,
            str(output)[-300:],
        )
        return False
    return True


def _op_press_key(dev: Any, act: dict) -> None:
    key = act["key"]
    try:
        dev.press(key)
    except Exception:
        serial = str(act.get("_serial") or "")
        if _press_key_via_adb(serial, key):
            return
        raise


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


def _selector_wait(sel: Any, timeout_s: float) -> bool:
    """Wait up to timeout_s for the selector. Both UiObject and XPathSelector
    expose wait(); XPathSelector returns an element rather than a bool."""
    wait = getattr(sel, "wait", None)
    if callable(wait):
        try:
            return bool(wait(timeout=timeout_s))
        except TypeError:
            return bool(wait(timeout_s))
    return _selector_exists_now(sel)


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


_SCREENSHOT_JPEG_QUALITY = 80


def _op_screenshot(dev: Any, act: dict) -> str:
    """Return the screen as base64 JPEG, straight from the device.

    uiautomator2's `screenshot()` calls `takeScreenshot(scale, quality)`, which
    already returns base64 JPEG, then decodes it to a Pillow image. Re-encoding
    that to PNG does not undo the JPEG step — the pixels are lossy either way —
    it only costs a decode plus an encode and inflates the payload.

    Measured on a real 1260x2800 screen: 648ms / 2704KB via Pillow+PNG versus
    276ms / 499KB taking the JPEG as-is, with byte-identical OCR output (259
    text boxes, mean confidence 70.2 both ways).
    """
    del act
    rpc = getattr(dev, "jsonrpc", None)
    if rpc is not None:
        try:
            data = rpc.takeScreenshot(1, _SCREENSHOT_JPEG_QUALITY)
            # Type-check rather than truth-check: a stub or a changed API could
            # hand back something non-base64 that is still truthy, and we would
            # ship it to the farm as if it were an image.
            if isinstance(data, bytes):
                data = data.decode("ascii", "ignore")
            if isinstance(data, str) and data.strip():
                return data  # already base64
        except Exception as exc:  # pragma: no cover - falls back below
            logger.debug("takeScreenshot fast path unavailable: %s", exc)

    image = dev.screenshot(format="pillow")
    if image is None:
        raise RuntimeError("screenshot: device returned no image")
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=_SCREENSHOT_JPEG_QUALITY)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


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
    settle_s = _swipe_settle_s(p)
    # The target is often already on screen and the screen is often still
    # rendering. Probing at timeout=0 answers "no" before the frame exists and
    # scrolls the target away, so give the first probe the caller's budget.
    first_wait_s = _first_wait_s(p)
    if first_wait_s and _selector_wait(sel, first_wait_s):
        return {"found": True, "swipes": 0}
    for i in range(max_swipes):
        if _selector_exists_now(sel):
            return {"found": True, "swipes": i}
        dev.swipe(fx, fy, tx, ty, duration=float(p.get("duration", DEFAULT_SWIPE_DURATION)))
        if settle_s:
            time.sleep(settle_s)
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


def _fb_fold(value: Any) -> str:
    # One normalisation for the whole codebase; see relay/fb_labels.py for why
    # folding makes naive substring matching unsafe on Vietnamese.
    return _fold(value)


def _fb_keyword_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    values = raw if isinstance(raw, list) else str(raw).split(",")
    out: list[str] = []
    for value in values:
        clean = str(value or "").strip()
        if not clean or (clean.startswith("${") and clean.endswith("}")):
            continue
        out.append(clean)
    return out


def _fb_node_label(node: Any) -> str:
    parts = [
        str(node.attrib.get("text", "") or ""),
        str(node.attrib.get("content-desc", "") or ""),
    ]
    return " ".join(dict.fromkeys(part for part in parts if part)).strip()


def _fb_all_labels(root: Any) -> list[str]:
    labels: list[str] = []
    for node in root.iter("node"):
        label = _fb_node_label(node)
        if label:
            labels.append(label)
    return labels


def _fb_is_clickable(node: Any) -> bool:
    return str(node.attrib.get("clickable", "") or "").casefold() == "true"


# Controls that destroy something the automation depends on, or act on the
# account's behalf in a way no scenario asked for. Every locating mistake ends
# the same way — a tap on the wrong control — so this is checked at the moment
# of tapping, independently of whatever logic chose the coordinates. A screenshot
# from a real run showed the friends-surface overflow sheet open with "Ẩn những
# người bạn có thể biết" one tap away: pressing it removes the account's entire
# suggestion source, permanently.
# Distinctive phrases: safe to look for anywhere in the label.
_FB_DESTRUCTIVE_PHRASES = LabelSet(
    name="destructive_phrases",
    mode=MODE_PHRASE,
    why="Multi-word wording no person's name can contain.",
    tokens=(
        "an nhung nguoi ban co the biet",
        "hide people you may know",
        "an bai viet",
        "hide post",
        "bao cao",
        "report",
        "bo theo doi",
        "unfollow",
        "huy ket ban",
        "unfriend",
        "dang xuat",
        "log out",
        "roi nhom",
        "leave group",
        "chap nhan",   # accepting a stranger's request is not ours to decide
        "delete comment",
        "block",
    ),
    collides_with_names=("bao cao",),
    collision_reason=(
        "'Bảo' and 'Cao' are both common name syllables, so a clickable label "
        "reading 'Bảo Cao' is refused. Accepted: losing one candidate is "
        "cheaper than reporting a stranger's post from the account, and this "
        "check only ever refuses a tap — it never performs one."
    ),
)

# Short button words that are also ordinary Vietnamese name syllables. "Chặn",
# "Gỡ" and "Xóa" fold to "chan", "go" and "xoa" — and so do parts of Chân Thị
# Mai, Gogo Nguyen and Xoan Nguyen. Matched only as a complete label, which is
# what a button carries and a person's row never does.
_FB_DESTRUCTIVE_EXACT = LabelSet(
    name="destructive_exact",
    mode=MODE_EXACT,
    why="Single syllables that are also names; only a whole-label match is a button.",
    tokens=("go", "xoa", "chan", "an"),
    collides_with_names=("an",),
    collision_reason=(
        "'An' is a complete Vietnamese given name, so a clickable name node "
        "labelled exactly 'An' will refuse the tap. Accepted: skipping one "
        "candidate costs a friend request, while tapping 'Ẩn những người bạn "
        "có thể biết' removes the account's entire suggestion source forever."
    ),
)

# Observed on a real device: the dismiss control next to Add Friend is labelled
# "Xóa <name>", so this one needs a prefix rule. Deliberately only this one —
# "Gỡ" and "Chặn" appear bare, while "Gỡ"/"Chặn" as a prefix would swallow names
# like "Go Thi Lan" and "Chan Thi Mai".
_FB_DESTRUCTIVE_PREFIXES: tuple[str, ...] = ("xoa ",)


def _fb_is_destructive_label(label: str) -> bool:
    folded = _fb_fold(label)
    if not folded:
        return False
    if _FB_DESTRUCTIVE_EXACT.matches_folded(folded):
        return True
    if _FB_DESTRUCTIVE_PHRASES.matches_folded(folded):
        return True
    # A prefix only counts when what follows is a person's name, not another
    # word that happens to start the same way ("Xoan Nguyen" is not "Xóa ...").
    return any(folded.startswith(prefix) for prefix in _FB_DESTRUCTIVE_PREFIXES)


def _fb_guarded_click(dev: Any, root: Any, x: int, y: int) -> dict[str, Any]:
    """Tap (x, y) unless the control there is one we must never press.

    Returns {"tapped": bool, "blocked_label": str}. The caller decides what to
    do about a refusal; this function's only job is to make sure a mislocated
    tap cannot be the thing that destroys the account's suggestion source.
    """
    blocked = _fb_label_at_point(root, x, y)
    if blocked:
        return {"tapped": False, "blocked_label": blocked}
    dev.click(x, y)
    return {"tapped": True, "blocked_label": ""}


def _fb_label_at_point(root: Any, x: int, y: int) -> str:
    """Destructive label of the smallest clickable node covering (x, y)."""
    best: tuple[int, str] | None = None
    for node in root.iter("node"):
        bounds = _bounds_tuple_from_string(str(node.attrib.get("bounds", "") or ""))
        if not bounds or not _fb_is_clickable(node):
            continue
        left, top, right, bottom = bounds
        if not (left <= x <= right and top <= y <= bottom):
            continue
        label = _fb_node_label(node)
        if not _fb_is_destructive_label(label):
            continue
        area = max(1, (right - left) * (bottom - top))
        if best is None or area < best[0]:
            best = (area, label)
    return best[1] if best else ""


# ── Screens the scenario did not ask for ─────────────────────────────────────
#
# A run meets three different kinds of unexpected screen and they need opposite
# handling, so lumping them into one "not ready" outcome guarantees getting one
# of them wrong: either retrying something that must stop, or stopping for
# something a single Back would have cleared.

SURFACE_OK = "ok"
SURFACE_DISMISSABLE = "dismissable"     # a sheet or dialog over our screen
SURFACE_BLOCKED = "blocked"             # checkpoint / re-login / restriction
SURFACE_UNKNOWN = "unknown"

# Account-level walls. These must never be retried: repeating an action against
# a checkpoint is how a recoverable account becomes an unrecoverable one.
_FB_BLOCKING_MARKERS = LabelSet(
    name="blocking_markers",
    mode=MODE_PHRASE,
    why=(
        "Matched against the whole screen's text, so only sentence-length "
        "wording is safe here — a screen full of names is the normal case."
    ),
    tokens=(
        "tam thoi bi chan",
        "temporarily blocked",
        "ban tam thoi bi chan",
        "xac nhan danh tinh",
        "confirm your identity",
        "xac minh danh tinh",
        "verify your identity",
        "tai khoan cua ban da bi vo hieu hoa",
        "account has been disabled",
        "dang nhap lai",
        "log in again",
        "nhap ma",
        "enter the code",
        "chung toi da phat hien hoat dong bat thuong",
        "unusual activity",
        "ban dang di qua nhanh",
        "you're going too fast",
        "you are going too fast",
    ),
)

# Sheets and dialogs that sit on top of a screen we can still use.
_FB_DISMISSABLE_MARKERS = LabelSet(
    name="dismissable_markers",
    mode=MODE_PHRASE,
    why="Also matched against the whole screen; sentence-length wording only.",
    tokens=(
        "nhan goi y ket ban tot hon",
        "get better friend suggestions",
        "improve friend suggestions",
        "tai sao toi nhin thay",
        "why am i seeing",
        "an nhung nguoi ban co the biet",
        "hide people you may know",
        "bat thong bao",
        "turn on notifications",
        "khong phai bay gio",
        "not now",
        "de sau",
        "maybe later",
        # Commenting on a post in a group the account has not joined makes
        # Facebook open its join questionnaire, full-screen, with the rules
        # checkbox already ticked and Send one tap away. Observed on a real run
        # on 20/08: the flow did not recognise it, kept rescanning and swiping
        # the form, and reported success for 88 iterations. Dismissable rather
        # than blocked — it is a modal we can back out of, not an account wall.
        "cau hoi danh cho nguoi tham gia",
        "quy tac nhom cua quan tri vien",
        "answer questions to join",
        "membership questions",
    ),
)


def _fb_handle_unexpected_surface(dev: Any, xml: str) -> dict[str, Any]:
    """Classify the screen and clear it when that is possible.

    Returns ``{"state", "xml", "marker", "cleared"}``. ``xml`` is the hierarchy
    the caller should keep working from — re-read after a successful dismiss,
    unchanged otherwise.

    Both flows used to leave SURFACE_DISMISSABLE computed and unused: the only
    branch anybody wrote was for SURFACE_BLOCKED, so a dialog we knew how to
    name still stopped nothing. One Back is the whole treatment; if the screen
    survives it, say so and let the caller stop rather than guess.
    """
    surface = _fb_classify_surface(xml)
    state = surface.get("state")
    if state != SURFACE_DISMISSABLE:
        return {**surface, "xml": xml, "cleared": False}

    # Only act on a dialog we can name. _fb_overlay_bounds also reports
    # DISMISSABLE from geometry alone — a wide node anchored to the bottom —
    # and a feed's own list container fits that shape. Pressing Back on a
    # healthy feed, or aborting the run because of it, is far worse than
    # missing an unnamed sheet. Identity decides; position only assists.
    if not str(surface.get("marker") or "").strip():
        return {**surface, "state": SURFACE_OK, "xml": xml, "cleared": False}

    try:
        dev.press("back")
    except Exception:
        return {**surface, "xml": xml, "cleared": False}
    time.sleep(0.6)
    try:
        after_xml = dev.dump_hierarchy(compressed=False)
    except Exception:
        return {**surface, "xml": xml, "cleared": False}

    after = _fb_classify_surface(after_xml)
    if after.get("state") == SURFACE_DISMISSABLE:
        return {
            **after,
            "xml": after_xml,
            "cleared": False,
            "fingerprint": _fb_surface_fingerprint(after_xml),
        }
    return {**after, "xml": after_xml, "cleared": True}


def _fb_overlay_bounds(root: Any) -> tuple[int, int, int, int] | None:
    """Bounds of a sheet/dialog covering the lower part of the screen.

    Detected by geometry rather than by resource-id: Facebook renames ids freely
    between builds, but a bottom sheet is always a large container anchored to
    the bottom edge. The content underneath stays in the hierarchy, so without
    this a flow happily computes coordinates for buttons nobody can press.
    """
    screen_right = _fb_screen_right(root)
    screen_bottom = 0
    for node in root.iter("node"):
        bounds = _bounds_tuple_from_string(str(node.attrib.get("bounds", "") or ""))
        if bounds:
            screen_bottom = max(screen_bottom, bounds[3])
    if screen_bottom <= 0 or screen_right <= 0:
        return None

    for node in root.iter("node"):
        bounds = _bounds_tuple_from_string(str(node.attrib.get("bounds", "") or ""))
        if not bounds:
            continue
        left, top, right, bottom = bounds
        width = right - left
        height = bottom - top
        covers_width = width >= screen_right * 0.9
        anchored_to_bottom = bottom >= screen_bottom * 0.97
        # A sheet covers a good part of the screen but not all of it: full-height
        # nodes are the page itself.
        sheet_height = screen_bottom * 0.25 <= height <= screen_bottom * 0.85
        if covers_width and anchored_to_bottom and sheet_height:
            return bounds
    return None


def _fb_classify_surface(hierarchy_xml: str) -> dict[str, Any]:
    """What kind of screen are we on, and what should the caller do about it?"""
    root = _xml_parse_root(hierarchy_xml)
    labels = _fb_all_labels(root)
    folded_all = _fb_fold(" ".join(labels))

    blocking_marker = _FB_BLOCKING_MARKERS.first_match_folded(folded_all)
    if blocking_marker:
        return {
            "state": SURFACE_BLOCKED,
            "marker": blocking_marker,
            "retryable": False,
            "message": "account-level block detected; stopping without retrying",
        }

    overlay = _fb_overlay_bounds(root)
    dismiss_marker = _FB_DISMISSABLE_MARKERS.first_match_folded(folded_all)
    if overlay is not None or dismiss_marker:
        return {
            "state": SURFACE_DISMISSABLE,
            "marker": dismiss_marker,
            "overlay_bounds": list(overlay) if overlay else None,
            "retryable": True,
        }

    return {"state": SURFACE_OK, "retryable": True}


def _fb_surface_fingerprint(hierarchy_xml: str) -> str:
    """Stable id for a screen, so repeat sightings can be counted.

    Unknown screens are worth cataloguing rather than guessing at: what shows up
    forty times a week deserves a handler, and what shows up once does not.
    """
    root = _xml_parse_root(hierarchy_xml)
    labels = sorted({_fb_fold(label) for label in _fb_all_labels(root) if label})
    return hashlib.sha256(" ".join(labels[:40]).encode("utf-8")).hexdigest()[:16]


_FB_ADD_FRIEND_TOKENS = LabelSet(
    name="add_friend_tokens",
    mode=MODE_PHRASE,
    why="Multi-word button wording; 'ban be'/'friend' alone would hit names.",
    tokens=("them ban be", "nut them ban be", "add friend", "nut add friend"),
)

# "Hủy lời mời" also contains no add-friend wording, but the accessibility label
# of a sent-request button on some builds reads "Nút thêm bạn bè, Hủy lời mời".
_FB_ADD_FRIEND_NEGATIONS = LabelSet(
    name="add_friend_negations",
    mode=MODE_PHRASE,
    why="Wording that turns an apparent Add Friend button into a sent request.",
    tokens=("huy loi moi", "cancel request"),
)


def _fb_is_add_friend_label(label: str) -> bool:
    folded = _fb_fold(label)
    return _FB_ADD_FRIEND_TOKENS.matches_folded(folded) and not (
        _FB_ADD_FRIEND_NEGATIONS.matches_folded(folded)
    )


# Post-tap states meaning "the request left". Kept in ONE place: this list and
# the verification in _fb_pending_request_near used to drift apart, so a row that
# turned into "Đã gửi lời mời" counted as a failed tap and aborted the batch.
_FB_REQUEST_SENT_TOKENS = LabelSet(
    name="request_sent_tokens",
    mode=MODE_PHRASE,
    why="Three-word status wording; no name folds to any of these.",
    tokens=(
        "huy loi moi",
        "huy yeu cau",
        "cancel request",
        "cancel friend request",
        "request sent",
        "friend request sent",
        "da gui loi moi",
        "da gui yeu cau",
        "loi moi da gui",
    ),
)


def _fb_is_request_sent_label(label: str) -> bool:
    return _FB_REQUEST_SENT_TOKENS.matches(label)


def _fb_is_connection_action_label(label: str) -> bool:
    return _fb_is_add_friend_label(label) or _fb_is_request_sent_label(label)


def _fb_same_row_labels(root: Any, bounds: tuple[int, int, int, int]) -> list[str]:
    _left, top, _right, bottom = bounds
    center_y = (top + bottom) // 2
    row_labels: list[str] = []
    for node in root.iter("node"):
        node_bounds = _bounds_tuple_from_string(str(node.attrib.get("bounds", "") or ""))
        if node_bounds is None:
            continue
        n_top, n_bottom = node_bounds[1], node_bounds[3]
        node_center_y = (n_top + n_bottom) // 2
        if abs(node_center_y - center_y) > 180:
            continue
        label = _fb_node_label(node)
        if label:
            row_labels.append(label)
    return row_labels


def _fb_nearby_labels(
    root: Any,
    bounds: tuple[int, int, int, int],
    *,
    y_padding: int,
) -> list[str]:
    _left, top, _right, bottom = bounds
    labels: list[str] = []
    for node in root.iter("node"):
        node_bounds = _bounds_tuple_from_string(str(node.attrib.get("bounds", "") or ""))
        if node_bounds is None:
            continue
        if node_bounds[3] < top - y_padding or node_bounds[1] > bottom + y_padding:
            continue
        label = _fb_node_label(node)
        if label:
            labels.append(label)
    return labels


def _fb_bool_param(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    folded = _fb_fold(value)
    if folded in {"1", "true", "yes", "y", "on", "enabled"}:
        return True
    if folded in {"0", "false", "no", "n", "off", "disabled"}:
        return False
    return bool(value)


# The mutual-friends subtitle under a name. Declared once because three call
# sites used to carry their own copy of the same two strings.
_FB_MUTUAL_CONTEXT_TOKENS = LabelSet(
    name="mutual_context_tokens",
    mode=MODE_PHRASE,
    why="Two-word subtitle wording; matched against rows that are mostly names.",
    tokens=("ban chung", "mutual friend"),
)


def _fb_contains_any(root: Any, tokens: tuple[str, ...]) -> bool:
    folded = _fb_fold(" ".join(_fb_all_labels(root)))
    return any(token and token in folded for token in tokens)


def _fb_click_label(
    dev: Any,
    root: Any,
    labels: tuple[str, ...],
    *,
    contains: bool = False,
) -> bool:
    folded_labels = tuple(_fb_fold(label) for label in labels if _fb_fold(label))
    matches: list[tuple[int, int, int, int]] = []
    for node in root.iter("node"):
        node_label = _fb_node_label(node)
        folded = _fb_fold(node_label)
        if not folded:
            continue
        matched = (
            any(label in folded for label in folded_labels)
            if contains
            else any(
                label == folded or f"{label} {label}" == folded
                for label in folded_labels
            )
        )
        if not matched:
            continue
        bounds = _bounds_tuple_from_string(str(node.attrib.get("bounds", "") or ""))
        if bounds is not None:
            matches.append(bounds)
    if not matches:
        return False
    left, top, right, bottom = sorted(matches, key=lambda item: (item[1], item[0]))[0]
    dev.click((left + right) // 2, (top + bottom) // 2)
    return True


_FB_SUGGESTION_CONTEXT_TOKENS = LabelSet(
    name="suggestion_context_tokens",
    mode=MODE_WORD,
    why=(
        "Matched against every label on screen at once, which on this surface "
        "is a list of people. 'goi y' would sit inside a name as a substring."
    ),
    tokens=(
        "nhung nguoi ban co the biet",
        "people you may know",
        "goi y",
        "suggestions",
    ),
)

_FB_FRIEND_HEADER_TOKENS = LabelSet(
    name="friend_header_tokens",
    mode=MODE_WORD,
    why="The 'Bạn bè' section header, matched against a screen full of names.",
    tokens=("ban be", "friends"),
)


def _fb_friend_suggestions_ready(root: Any) -> bool:
    labels = _fb_fold(" ".join(_fb_all_labels(root)))
    has_suggestion_context = _FB_SUGGESTION_CONTEXT_TOKENS.matches_folded(labels)
    has_friend_header = _FB_FRIEND_HEADER_TOKENS.matches_folded(labels)
    has_add_button = _FB_ADD_FRIEND_TOKENS.matches_folded(labels)
    return has_suggestion_context and (has_add_button or has_friend_header)


_FB_CLOSE_CONTROL_EXACT = LabelSet(
    name="close_control_exact",
    mode=MODE_EXACT,
    why=(
        "A dismiss button carries nothing but 'Đóng', 'Close' or 'X'. As a "
        "substring 'x' matches almost every label there is."
    ),
    tokens=("dong", "close", "x"),
)


def _fb_dismiss_friend_suggestion_prompt(dev: Any, root: Any) -> bool:
    if not _fb_contains_any(
        root,
        (
            "nhan goi y ket ban tot hon",
            "get better friend suggestions",
            "improve friend suggestions",
        ),
    ):
        return False

    close_like: list[tuple[int, int, int, int]] = []
    for node in root.iter("node"):
        if not _fb_is_clickable(node):
            continue
        bounds = _bounds_tuple_from_string(str(node.attrib.get("bounds", "") or ""))
        if bounds is None:
            continue
        left, top, right, bottom = bounds
        width = right - left
        height = bottom - top
        label = _fb_fold(_fb_node_label(node))
        if label and not _FB_CLOSE_CONTROL_EXACT.matches_folded(label):
            continue
        if right < 700 or top < 500 or width > 220 or height > 220:
            continue
        close_like.append(bounds)
    if not close_like:
        return False
    left, top, right, bottom = sorted(close_like, key=lambda item: (-item[2], item[1]))[0]
    dev.click((left + right) // 2, (top + bottom) // 2)
    return True


def _fb_open_friend_suggestions_surface(dev: Any, p: dict) -> dict[str, Any]:
    attempts: list[str] = []
    wait_s = max(0.0, min(float(p.get("surface_wait_s", 0.8) or 0.8), 4.0))
    max_menu_scrolls = max(0, int(p.get("surface_menu_scrolls", 4) or 4))

    def _dump_root() -> tuple[str, Any]:
        xml = dev.dump_hierarchy(compressed=False)
        return xml, _xml_parse_root(xml)

    xml, root = _dump_root()
    if _fb_friend_suggestions_ready(root):
        return {"ready": True, "opened": False, "attempts": attempts, "xml": xml}

    for _ in range(2):
        close_bounds: tuple[int, int, int, int] | None = None
        for node in root.iter("node"):
            if not _fb_is_clickable(node):
                continue
            bounds = _bounds_tuple_from_string(
                str(node.attrib.get("bounds", "") or "")
            )
            if bounds is None:
                continue
            left, top, right, bottom = bounds
            if left > 260 or top > 420 or right - left > 220 or bottom - top > 220:
                continue
            folded = _fb_fold(_fb_node_label(node))
            if folded in {"dong", "close", "quay lai", "back", "x"}:
                close_bounds = bounds
                break
        if close_bounds is None:
            break
        left, top, right, bottom = close_bounds
        dev.click((left + right) // 2, (top + bottom) // 2)
        attempts.append("close_detail_overlay")
        time.sleep(wait_s)
        xml, root = _dump_root()
        if _fb_friend_suggestions_ready(root):
            return {"ready": True, "opened": True, "attempts": attempts, "xml": xml}

    menu_tap = p.get("menu_tap") or [90, 208]
    try:
        menu_x, menu_y = int(menu_tap[0]), int(menu_tap[1])
    except (TypeError, ValueError, IndexError):
        menu_x, menu_y = 90, 208
    dev.click(menu_x, menu_y)
    attempts.append("tap_menu")
    time.sleep(wait_s)

    for i in range(max_menu_scrolls + 1):
        xml, root = _dump_root()
        if _fb_friend_suggestions_ready(root):
            return {"ready": True, "opened": True, "attempts": attempts, "xml": xml}
        if _fb_click_label(dev, root, ("Tìm bạn bè", "Find friends"), contains=False):
            attempts.append("tap_find_friends")
            time.sleep(wait_s)
            xml, root = _dump_root()
            if _fb_friend_suggestions_ready(root):
                return {"ready": True, "opened": True, "attempts": attempts, "xml": xml}
        if _fb_click_label(dev, root, ("Xem thêm", "See more"), contains=False):
            attempts.append("tap_see_more")
            time.sleep(wait_s)
            continue
        if i < max_menu_scrolls:
            try:
                dev.swipe(650, 2100, 650, 900, duration=0.45)
                attempts.append("scroll_menu")
                time.sleep(wait_s)
            except Exception as exc:
                attempts.append(f"scroll_menu_failed:{exc}")
                break

    return {
        "ready": False,
        "opened": False,
        "attempts": attempts,
        "xml": xml,
        "reason": "friend_surface_not_ready",
    }


def _fb_visible_person_row_labels(
    root: Any,
    bounds: tuple[int, int, int, int],
) -> list[str]:
    _left, top, right, bottom = bounds
    labels: list[str] = []
    for node in root.iter("node"):
        node_bounds = _bounds_tuple_from_string(str(node.attrib.get("bounds", "") or ""))
        if node_bounds is None:
            continue
        n_left, n_top, n_right, n_bottom = node_bounds
        if n_bottom < top - 200 or n_top > bottom + 70:
            continue
        if n_right < 0 or n_left > right + 80:
            continue
        label = _fb_node_label(node)
        folded = _fb_fold(label)
        if not folded:
            continue
        if _FB_MUTUAL_CONTEXT_TOKENS.matches_folded(folded) and n_bottom < top - 80:
            continue
        package_name = str(node.attrib.get("package", "") or "")
        if package_name and not package_name.startswith("com.facebook"):
            continue
        if _fb_is_connection_action_label(label):
            continue
        compact = folded.replace(" ", "")
        if compact in {
            "go",
            "gogo",
            "banbebanbe",
            "friendsfriends",
        } or folded.startswith("xoa "):
            continue
        if folded in {
            "quay lai",
            "ban be",
            "friends",
            "goi y",
            "suggestions",
            "loi moi ket ban",
            "friend requests",
            "ban be cua ban",
            "your friends",
            "tim kiem",
            "search",
            "quan ly",
            "manage",
        }:
            continue
        labels.append(label)
    return list(dict.fromkeys(labels))


def _fb_parent_map(root: Any) -> dict[Any, Any]:
    return {child: parent for parent in root.iter("node") for child in parent}


def _fb_person_row_scope(root: Any, parents: dict[Any, Any], button: Any) -> Any | None:
    """Nearest ancestor that represents the whole suggestion card.

    Facebook renders each suggestion as a container whose content-desc is the
    row summary ("Thai Hanh, 2 bạn chung"), with the avatar, name, Add Friend
    and Remove buttons nested inside. Reading the card is exact; the geometric
    window this replaces guessed a pixel band around the button and, on a dense
    real screen, swept in the neighbouring person's name — so a request could be
    recorded against the wrong identity.
    """
    node = parents.get(button)
    depth = 0
    while node is not None and depth < 8:
        label = _fb_node_label(node)
        if label and not _fb_is_connection_action_label(label):
            children = list(node.iter("node"))
            # A card holds the button plus the surrounding text; a bare wrapper
            # around the button alone tells us nothing.
            if len(children) > 2:
                return node
        node = parents.get(node)
        depth += 1
    return None


def _fb_row_labels_in_scope(scope: Any) -> list[str]:
    """Labels belonging to one suggestion card, in document order."""
    labels: list[str] = []
    for node in scope.iter("node"):
        label = _fb_node_label(node)
        folded = _fb_fold(label)
        if not folded:
            continue
        package_name = str(node.attrib.get("package", "") or "")
        if package_name and not package_name.startswith("com.facebook"):
            continue
        if _fb_is_connection_action_label(label):
            continue
        # "Xóa <name>" / "Gỡ" dismiss the suggestion; they repeat the name and
        # would otherwise win the display-name pick.
        if folded.startswith("xoa ") or folded.replace(" ", "") in {"go", "gogo"}:
            continue
        labels.append(label)
    scope_label = _fb_node_label(scope)
    if scope_label:
        labels.insert(0, scope_label)
    return list(dict.fromkeys(labels))


def _fb_mutual_count_from_text(text: str) -> int:
    folded = _fb_fold(text)
    for pattern in (r"(\d+)\s+ban chung", r"(\d+)\s+mutual friend"):
        match = re.search(pattern, folded)
        if match:
            return int(match.group(1))
    return 0


def _fb_display_name_from_row(labels: list[str], row_text: str) -> str:
    prioritized = sorted(
        labels,
        key=lambda item: 1 if _FB_MUTUAL_CONTEXT_TOKENS.matches(item) else 0,
    )
    for label in prioritized:
        clean = str(label or "").strip()
        if not clean:
            continue
        folded_clean = _fb_fold(clean)
        if _FB_MUTUAL_CONTEXT_TOKENS.matches_folded(folded_clean):
            continue
        clean = re.split(
            r"\s*,\s*\d+\s+b",
            clean,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        clean = re.split(
            r"\s*,\s*\d+\s+mutual",
            clean,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        clean = clean.strip(" ,")
        if clean:
            return clean[:120]
    return row_text[:120]


def _fb_still_offering_add_friend(hierarchy_xml: str, target_id: str) -> bool:
    """Is this exact person still showing an Add Friend button on screen?

    Identity beats coordinates for verifying a send. Facebook re-flows the
    friends surface constantly — a "X accepted your request" banner appears, the
    sent row is removed — so a position-based check reads whichever button
    happened to slide into the tapped spot and calls a successful send a
    failure. Matching on the row fingerprint is immune to that.
    """
    wanted = str(target_id or "")
    if not wanted:
        return False
    candidates, _qualified, _rejected = _fb_visible_connectable_people(
        hierarchy_xml,
        common_keywords=[],
        forbidden_keywords=[],
        min_score=0,
        require_common=False,
    )
    return any(str(item.get("target_id") or "") == wanted for item in candidates)


def _fb_connection_state_near(hierarchy_xml: str, tap_y: int) -> str:
    """State of the connection control around tap_y after a tap.

    Returns "sent" (button flipped to a cancel/sent state), "add_friend" (the
    button is still offering to add — the tap did not take), or "gone" (no
    connection control there at all).

    "gone" counts as success: Facebook usually removes a suggestion row once the
    request is sent, and the old check only looked for a cancel label — so every
    successful send on that UI was reported as an unverified tap.
    """
    after_root = _xml_parse_root(hierarchy_xml)
    still_offering = False
    for node in after_root.iter("node"):
        bounds = _bounds_tuple_from_string(str(node.attrib.get("bounds", "") or ""))
        if not bounds:
            continue
        if abs(((bounds[1] + bounds[3]) // 2) - tap_y) > 260:
            continue
        label = _fb_node_label(node)
        if _fb_is_request_sent_label(label):
            return "sent"
        if _fb_is_add_friend_label(label):
            still_offering = True
    return "add_friend" if still_offering else "gone"


def _fb_pending_request_near(hierarchy_xml: str, tap_y: int) -> bool:
    return _fb_connection_state_near(hierarchy_xml, tap_y) != "add_friend"


def _fb_scroll_people_surface(dev: Any, p: dict) -> bool:
    try:
        width, height = dev.window_size()
    except Exception:
        width, height = 1080, 2400
    x = int(width * float(p.get("scroll_x_ratio", 0.5) or 0.5))
    y1 = int(height * float(p.get("scroll_y1_ratio", 0.78) or 0.78))
    y2 = int(height * float(p.get("scroll_y2_ratio", 0.34) or 0.34))
    duration = max(0.1, min(float(p.get("scroll_duration_s", 0.45) or 0.45), 2.0))
    try:
        dev.swipe(x, y1, x, y2, duration=duration)
        return True
    except Exception:
        return False


def _fb_score_text(
    text: str,
    *,
    display_name: str,
    search: str,
    required: list[str],
    optional: list[str],
    forbidden: list[str],
) -> tuple[int, list[str], list[str], bool]:
    folded = _fb_fold(text)
    if any(_fb_fold(token) and _fb_fold(token) in folded for token in forbidden):
        return 0, [], [], True

    matched: list[str] = []
    missing: list[str] = []
    score = 0

    display_folded = _fb_fold(display_name)
    if display_folded and display_folded in folded:
        score += 70
        matched.append(display_name)

    search_folded = _fb_fold(search)
    if search_folded and search_folded in folded and search_folded != display_folded:
        score += 15
        matched.append(search)

    for token in required:
        folded_token = _fb_fold(token)
        if folded_token and folded_token in folded:
            score += 25
            matched.append(token)
        else:
            missing.append(token)

    for token in optional:
        folded_token = _fb_fold(token)
        if folded_token and folded_token in folded:
            score += 8
            matched.append(token)

    return score, matched, missing, False


_FB_POST_STOPWORDS = frozenset(
    {
        "anh",
        "ban",
        "bac",
        "bai",
        "cai",
        "cac",
        "cho",
        "cua",
        "duoc",
        "hay",
        "hon",
        "la",
        "lam",
        "minh",
        "mot",
        "moi",
        "nen",
        "nguoi",
        "nhi",
        "thi",
        "the",
        "toi",
        "voi",
        "you",
        "the",
        "and",
        "for",
        "that",
        "this",
        "with",
        "from",
    }
)


def _fb_post_terms(*values: Any) -> list[str]:
    terms: list[str] = []
    for value in values:
        folded = _fb_fold(value)
        for term in re.findall(r"[a-z0-9]{3,}", folded):
            if term in _FB_POST_STOPWORDS:
                continue
            terms.append(term)
    return list(dict.fromkeys(terms))


def _fb_post_partial_score(
    text: str,
    *,
    display_text: str,
    search: str,
    required: list[str],
) -> tuple[int, list[str]]:
    terms = _fb_post_terms(display_text, search, *required)
    if not terms:
        return 0, []
    folded = _fb_fold(text)
    matched_terms = [term for term in terms if term in folded]
    if not matched_terms:
        return 0, []
    required_count = max(2, min(5, (len(terms) + 1) // 2))
    if len(matched_terms) < required_count:
        return 0, matched_terms
    score = 65 + min(35, len(matched_terms) * 8)
    return score, matched_terms


# Connection state of the profile owner's own control. Facebook shows the same
# three states everywhere; the farm already speaks this vocabulary in
# services/social_actions/facebook.py.
FRIEND_STATE_AVAILABLE = "available"
FRIEND_STATE_PENDING = "pending"
FRIEND_STATE_CONNECTED = "connected"

_FB_FRIEND_CONNECTED_LABELS = LabelSet(
    name="friend_connected_labels",
    mode=MODE_EXACT,
    why=(
        "'Bạn bè' and 'Bạn' are the button labels on a connected profile — and "
        "also the two most common words in any Vietnamese friend row. Only a "
        "label that is nothing but this word is the button."
    ),
    tokens=("ban be", "friends", "ban"),
)

# Everything under this heading belongs to other people. A profile page carries
# suggestion cards with their own Add Friend buttons, which is why counting the
# connection controls on screen can never identify the owner's.
_FB_PROFILE_SUGGESTION_HEADINGS = LabelSet(
    name="profile_suggestion_headings",
    mode=MODE_PHRASE,
    why="Section headings, four words or more; nothing shorter belongs here.",
    tokens=(
        "nhung nguoi ban co the biet",
        "people you may know",
        "goi y cho ban",
        "suggested for you",
    ),
)


def _fb_scroll_profile_to_top(dev: Any, *, max_swipes: int = 2) -> int:
    """Swipe a profile page back toward its header. Returns swipes performed.

    Deliberately does not read the hierarchy between swipes: a dump is the
    expensive call here, and doing two per swipe pushed this flow past its relay
    timeout. Callers only reach for this when the header was not found, so a
    couple of blind swipes is the cheaper bet than measuring.
    """
    try:
        width, height = dev.window_size()
    except Exception:
        width, height = 1080, 2400
    x = int(width * 0.5)
    y1 = int(height * 0.35)
    y2 = int(height * 0.80)
    swipes = 0
    for _ in range(max(0, max_swipes)):
        try:
            dev.swipe(x, y1, x, y2, duration=0.3)
        except Exception:
            return swipes
        swipes += 1
        time.sleep(0.3)
    return swipes


def _fb_profile_suggestion_top(root: Any) -> int | None:
    """Y of the first suggestion heading, or None when the page has none."""
    best: int | None = None
    for node in root.iter("node"):
        folded = _fb_fold(_fb_node_label(node))
        if not _FB_PROFILE_SUGGESTION_HEADINGS.matches_folded(folded):
            continue
        bounds = _bounds_tuple_from_string(str(node.attrib.get("bounds", "") or ""))
        if bounds and (best is None or bounds[1] < best):
            best = bounds[1]
    return best


def _fb_profile_owner_connection(
    hierarchy_xml: str, display_name: str
) -> dict[str, Any]:
    """Find the connection control belonging to the profile's owner.

    Anchored to the owner's name rather than to a position. A profile page also
    lists friend suggestions, each with its own Add Friend button, so "the only
    connection control on screen" is not a thing that exists and "the topmost
    one" stops being the owner's as soon as the page is scrolled — silently
    friending somebody else.

    Returns {"found": bool, "state": ..., "bounds": [...], "label": ...}.
    """
    root = _xml_parse_root(hierarchy_xml)
    wanted = _fb_fold(display_name)
    if not wanted:
        return {"found": False, "reason": "owner_name_unknown"}

    # The owner's name is a whole label on the profile header, never a fragment
    # of a longer one — matching loosely is how "Trang" swallowed every person
    # named Trang earlier in this codebase.
    name_top: int | None = None
    for node in root.iter("node"):
        if _fb_fold(_fb_node_label(node)) == wanted:
            bounds = _bounds_tuple_from_string(str(node.attrib.get("bounds", "") or ""))
            if bounds and (name_top is None or bounds[1] < name_top):
                name_top = bounds[1]
    if name_top is None:
        return {"found": False, "reason": "owner_name_not_visible"}

    suggestion_top = _fb_profile_suggestion_top(root)
    best: tuple[int, dict[str, Any]] | None = None
    for node in root.iter("node"):
        if not _fb_is_clickable(node):
            continue
        label = _fb_node_label(node)
        folded = _fb_fold(label)
        if not folded:
            continue
        bounds = _bounds_tuple_from_string(str(node.attrib.get("bounds", "") or ""))
        if not bounds:
            continue
        if bounds[1] < name_top:
            continue  # above the owner's name: navigation chrome
        if suggestion_top is not None and bounds[1] >= suggestion_top:
            continue  # belongs to a suggestion card
        if _fb_is_add_friend_label(label):
            state = FRIEND_STATE_AVAILABLE
        elif _fb_is_request_sent_label(label):
            state = FRIEND_STATE_PENDING
        elif _FB_FRIEND_CONNECTED_LABELS.matches_folded(folded):
            state = FRIEND_STATE_CONNECTED
        else:
            continue
        # Nearest control below the name is the owner's action row.
        distance = bounds[1] - name_top
        if best is None or distance < best[0]:
            best = (distance, {"state": state, "bounds": list(bounds), "label": label})
    if best is None:
        return {"found": False, "reason": "owner_action_row_not_found"}
    return {"found": True, **best[1]}


def _fb_dedupe_action_buttons(
    buttons: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Collapse the same on-screen control reported at several nesting levels.

    Facebook renders one button as a clickable Button wrapping a clickable
    ViewGroup carrying the same label, so counting nodes counts each control
    twice. Callers use the count to decide "this profile offers exactly one
    connection action" — with duplicates that test never passes and a perfectly
    ordinary profile is rejected as ambiguous.

    Two nodes are the same control when their labels agree and their bounds
    overlap; the outer one is kept because it is the reliable tap target.
    """
    groups: list[dict[str, Any]] = []
    for button in buttons:
        bounds = button.get("bounds") or []
        if len(bounds) != 4:
            continue
        folded = _fb_fold(str(button.get("label") or ""))
        merged = False
        for group in groups:
            if _fb_fold(str(group.get("label") or "")) != folded:
                continue
            other = group.get("bounds") or []
            if len(other) != 4:
                continue
            overlaps = (
                bounds[0] <= other[2]
                and other[0] <= bounds[2]
                and bounds[1] <= other[3]
                and other[1] <= bounds[3]
            )
            if overlaps:
                area = (bounds[2] - bounds[0]) * (bounds[3] - bounds[1])
                other_area = (other[2] - other[0]) * (other[3] - other[1])
                if area > other_area:
                    group["bounds"] = bounds
                merged = True
                break
        if not merged:
            groups.append(dict(button))
    return groups


def _fb_dedupe_post_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    for candidate in sorted(
        candidates,
        key=lambda item: (
            (int(item["bounds"][1]) + int(item["bounds"][3])) // 2,
            -int(item["score"]),
        ),
    ):
        center_y = (int(candidate["bounds"][1]) + int(candidate["bounds"][3])) // 2
        merged = False
        for idx, existing in enumerate(deduped):
            existing_center_y = (
                int(existing["bounds"][1]) + int(existing["bounds"][3])
            ) // 2
            if abs(center_y - existing_center_y) > 220:
                continue
            if int(candidate["score"]) > int(existing["score"]) or (
                int(candidate["score"]) == int(existing["score"])
                and bool(candidate.get("clickable"))
                and not bool(existing.get("clickable"))
            ):
                deduped[idx] = candidate
            merged = True
            break
        if not merged:
            deduped.append(candidate)
    return deduped


_FB_POST_SEARCH_CHROME_TOKENS = LabelSet(
    name="post_search_chrome_tokens",
    mode=MODE_PHRASE,
    why="Multi-word decorations in a search result card.",
    tokens=(
        "anh dai dien",
        "hinh minh hoa",
        "hinh nen",
        "lua chon khac",
        "nut thich",
        "nut binh luan",
        "nut chia se",
    ),
)

_FB_SEARCH_FIELD_TOKENS = LabelSet(
    name="search_field_tokens",
    mode=MODE_WORD,
    why="Matched against an EditText hint, but kept to words on principle.",
    tokens=("tim kiem", "search"),
)

# Chrome inside the comment sheet, used to tell a real commenter's name from the
# sheet's own controls. "thich"/"like"/"reply" are single words here: as
# substrings they would discard commenters whose names contain those letters.
_FB_COMMENT_SHEET_CHROME = LabelSet(
    name="comment_sheet_chrome",
    mode=MODE_WORD,
    why="Matched against candidate commenter names, so never as substrings.",
    tokens=(
        "phu hop nhat",
        "most relevant",
        "tat ca binh luan",
        "all comments",
        "viet binh luan",
        "write a comment",
        "tra loi",
        "reply",
        "thich",
        "like",
    ),
)

_FB_SEE_MORE_TOKENS = LabelSet(
    name="see_more_tokens",
    mode=MODE_PHRASE,
    why="Two-word expander link.",
    tokens=("xem them", "see more"),
)


def _fb_is_post_search_chrome_label(label: str) -> bool:
    folded = _fb_fold(label)
    if not folded:
        return True
    if _FB_POST_SEARCH_CHROME_TOKENS.matches_folded(folded):
        return True
    return bool(re.fullmatch(r"\d+\s+(binh luan|comments?|shares?)", folded))


def _fb_search_input_focused(root: Any) -> bool:
    for node in root.iter("node"):
        if str(node.attrib.get("class", "") or "") != "android.widget.EditText":
            continue
        if str(node.attrib.get("focused", "") or "").casefold() != "true":
            continue
        if _FB_SEARCH_FIELD_TOKENS.matches(_fb_node_label(node)):
            return True
    return False


def _fb_search_suggestion_bounds(
    root: Any,
    *,
    display_text: str,
    search: str,
    required: list[str],
) -> tuple[int, int, int, int] | None:
    candidates: list[tuple[int, tuple[int, int, int, int]]] = []
    for node in root.iter("node"):
        bounds = _bounds_tuple_from_string(str(node.attrib.get("bounds", "") or ""))
        if not bounds or not _fb_is_clickable(node):
            continue
        if bounds[1] < 280:
            continue
        row_text = " ".join(dict.fromkeys(_fb_nearby_labels(root, bounds, y_padding=24)))
        if not row_text:
            continue
        score, _matched, missing, forbidden_hit = _fb_score_text(
            row_text,
            display_name=display_text,
            search=search,
            required=required,
            optional=[],
            forbidden=[],
        )
        partial_score, _partial_matches = _fb_post_partial_score(
            row_text,
            display_text=display_text,
            search=search,
            required=required,
        )
        if forbidden_hit:
            continue
        if missing and partial_score <= 0:
            continue
        confidence = max(score, partial_score)
        if confidence <= 0:
            continue
        candidates.append((confidence, bounds))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1][1], item[1][0]))
    return candidates[0][1]


def _fb_profile_display_name(display_name: str) -> str:
    """Strip a search-only trailing alias that Facebook omits on profiles."""
    base_name = re.sub(r"\s*\([^()]+\)\s*$", "", display_name).strip()
    return base_name or display_name


# Post action-bar wording. These are single syllables in Vietnamese, so they are
# matched as whole words: "thich" sits inside no common name, but "Thi Chi" folds
# close enough that the substring rule was luck rather than design.
_FB_CONTENT_ACTION_WORDS = LabelSet(
    name="content_action_words",
    mode=MODE_WORD,
    why="Single-word action-bar labels under a post.",
    tokens=("thich", "binh luan", "chia se", "like", "comment", "share"),
)

# Two lists, not one: "remove like" disqualifies a control from being the
# *available* like button, but it is the accessibility label of the unlike
# action rather than a state the feed shows, so it does not by itself mean the
# post is liked.
_FB_LIKE_NOT_AVAILABLE_WORDS = LabelSet(
    name="like_not_available_words",
    mode=MODE_WORD,
    why="Wording that rules a control out as the pressable like button.",
    tokens=("bo thich", "unlike", "remove like"),
)

_FB_LIKE_ACTIVE_WORDS = LabelSet(
    name="like_active_words",
    mode=MODE_WORD,
    why="States meaning the post is already liked.",
    tokens=("bo thich", "da thich", "unlike"),
)

_FB_LIKE_AVAILABLE_WORDS = LabelSet(
    name="like_available_words",
    mode=MODE_WORD,
    why="States meaning the like button can still be pressed.",
    tokens=("nut thich", "thich", "like"),
)

_FB_COMMENT_ACTION_WORDS = LabelSet(
    name="comment_action_words",
    mode=MODE_WORD,
    why="The comment button under a post.",
    tokens=("nut binh luan", "binh luan", "comment"),
)

_FB_COMMENT_INPUT_TOKENS = LabelSet(
    name="comment_input_tokens",
    mode=MODE_PHRASE,
    why="Composer placeholder text; multi-word by construction.",
    tokens=(
        "viet binh luan",
        "binh luan cong khai",
        "write a comment",
        "comment as",
    ),
)

_FB_COMMENT_SUBMIT_EXACT = LabelSet(
    name="comment_submit_exact",
    mode=MODE_EXACT,
    why="'Đăng', 'Gửi' are also name syllables; only a bare label is the button.",
    tokens=("dang", "post", "send", "gui"),
)

_FB_COMMENT_SUBMIT_TOKENS = LabelSet(
    name="comment_submit_tokens",
    mode=MODE_PHRASE,
    why="Accessibility wording that names the button explicitly.",
    tokens=("nut dang", "nut gui", "post comment", "send comment"),
)

_FB_COMMENT_CLOSE_EXACT = LabelSet(
    name="comment_close_exact",
    mode=MODE_EXACT,
    why="'Đóng' folds to 'dong', which is inside names like 'Hồng Đông'.",
    tokens=("dong", "close"),
)

_FB_COMMENT_CLOSE_TOKENS = LabelSet(
    name="comment_close_tokens",
    mode=MODE_PHRASE,
    why="Accessibility wording that names the close control explicitly.",
    tokens=("nut dong", "close comments", "close comment"),
)


def _fb_is_content_action_label(label: str) -> bool:
    return _FB_CONTENT_ACTION_WORDS.matches(label)


def _fb_is_like_available_label(label: str) -> bool:
    folded = _fb_fold(label)
    if _FB_LIKE_NOT_AVAILABLE_WORDS.matches_folded(folded):
        return False
    return _FB_LIKE_AVAILABLE_WORDS.matches_folded(folded)


def _fb_is_like_active_label(label: str) -> bool:
    return _FB_LIKE_ACTIVE_WORDS.matches(label)


def _fb_is_comment_action_label(label: str) -> bool:
    return _FB_COMMENT_ACTION_WORDS.matches(label)


def _fb_is_comment_input_label(label: str) -> bool:
    return _FB_COMMENT_INPUT_TOKENS.matches(label)


def _fb_is_comment_submit_label(label: str) -> bool:
    folded = _fb_fold(label)
    return _FB_COMMENT_SUBMIT_EXACT.matches_folded(
        folded
    ) or _FB_COMMENT_SUBMIT_TOKENS.matches_folded(folded)


def _fb_is_comment_overlay_close_label(label: str) -> bool:
    folded = _fb_fold(label)
    return _FB_COMMENT_CLOSE_EXACT.matches_folded(
        folded
    ) or _FB_COMMENT_CLOSE_TOKENS.matches_folded(folded)


_DEFAULT_SOCIAL_POST_TERMS: dict[str, list[str]] = {
    "like_terms": ["nut thich", "thich", "like"],
    "liked_terms": ["bo thich", "da thich", "unlike", "remove like"],
    "comment_terms": ["nut binh luan", "binh luan", "comment"],
    "comment_input_terms": [
        "viet binh luan",
        "binh luan cong khai",
        "write a comment",
        "comment as",
    ],
    "comment_submit_terms": [
        "dang",
        "post",
        "send",
        "gui",
        "nut dang",
        "nut gui",
        "post comment",
        "send comment",
    ],
    "overlay_close_terms": ["dong", "close", "nut dong", "close comments", "close comment"],
    "forbidden_context_terms": [
        "them ban be",
        "add friend",
        "chia se trang ca nhan",
        "share profile",
        "cover photo",
        "anh dai dien",
    ],
}
_DEFAULT_SOCIAL_INPUT_CLASSES = [
    "android.widget.EditText",
    "android.widget.AutoCompleteTextView",
]


def _social_folded_terms(raw: Any, defaults: list[str]) -> list[str]:
    values = _fb_keyword_list(raw) if raw is not None else defaults
    terms = [_fb_fold(item) for item in values]
    return [term for term in terms if term]


def _social_post_terms(p: dict) -> dict[str, list[str]]:
    return {
        key: _social_folded_terms(p.get(key), defaults)
        for key, defaults in _DEFAULT_SOCIAL_POST_TERMS.items()
    }


def _social_input_classes(p: dict) -> list[str]:
    raw = p.get("comment_input_classes") or p.get("input_classes")
    if raw is None:
        return list(_DEFAULT_SOCIAL_INPUT_CLASSES)
    if isinstance(raw, str):
        values = [item.strip() for item in raw.split(",")]
    elif isinstance(raw, (list, tuple, set)):
        values = [str(item).strip() for item in raw]
    else:
        values = []
    return [item for item in values if item] or list(_DEFAULT_SOCIAL_INPUT_CLASSES)


def _social_label_matches(label: str, terms: list[str]) -> bool:
    folded = _fb_fold(label)
    return any(term and term in folded for term in terms)


def _social_label_exact_or_matches(label: str, terms: list[str]) -> bool:
    folded = _fb_fold(label)
    return folded in set(terms) or any(term and term in folded for term in terms)


def _fb_scan_keyword_terms(raw: Any) -> list[str]:
    terms = _fb_keyword_list(raw)
    return [term for term in (_fb_fold(item) for item in terms) if term]


def _fb_scan_post_keyword_match(
    text: str,
    *,
    terms: list[str],
    match_mode: str,
) -> tuple[bool, list[str]]:
    if not terms:
        return True, []
    folded = _fb_fold(text)
    matched = [term for term in terms if term in folded]
    if match_mode == "all":
        return len(matched) == len(terms), matched
    return bool(matched), matched


def _fb_find_comment_submit_bounds(
    root: Any,
    *,
    submit_terms: list[str],
    input_bounds: tuple[int, int, int, int] | None = None,
) -> tuple[int, int, int, int] | None:
    candidates: list[tuple[int, tuple[int, int, int, int]]] = []
    for node in root.iter("node"):
        bounds = _bounds_tuple_from_string(str(node.attrib.get("bounds", "") or ""))
        if not bounds or not _fb_is_clickable(node):
            continue
        label = _fb_node_label(node)
        if not _fb_is_comment_submit_label(label) and not _social_submit_label_matches(
            label,
            submit_terms,
        ):
            continue
        if input_bounds is not None:
            in_left, in_top, in_right, in_bottom = input_bounds
            left, top, right, bottom = bounds
            center_x = (left + right) // 2
            center_y = (top + bottom) // 2
            near_input_y = in_top - 180 <= center_y <= in_bottom + 220
            near_or_right_of_input = center_x >= in_left or left >= in_right - 160
            if not near_input_y or not near_or_right_of_input:
                continue
            score = abs(center_y - ((in_top + in_bottom) // 2)) + max(0, in_right - center_x)
        else:
            score = bounds[1]
        candidates.append((score, bounds))
    if not candidates:
        return None
    return min(candidates, key=lambda item: (item[0], item[1][1], item[1][0]))[1]


def _social_submit_label_matches(label: str, terms: list[str]) -> bool:
    folded = _fb_fold(label)
    for term in terms:
        term = str(term or "").strip()
        if not term:
            continue
        folded_term = _fb_fold(term)
        if folded == folded_term:
            return True
        if folded_term in {"dang", "gui", "post", "send"}:
            continue
        if folded_term and folded_term in folded:
            return True
    return False


# The three sort options in the comment filter sheet, one LabelSet each so the
# caller can tell which of them it saw.
_FB_COMMENT_SORT_OPTIONS: dict[str, LabelSet] = {
    "best": LabelSet(
        name="comment_sort_best",
        mode=MODE_PHRASE,
        why="Three-word option label.",
        tokens=("phu hop nhat",),
    ),
    "newest": LabelSet(
        name="comment_sort_newest",
        mode=MODE_WORD,
        why="'moi nhat' is two short syllables; words only.",
        tokens=("moi nhat",),
    ),
    "all": LabelSet(
        name="comment_sort_all",
        mode=MODE_PHRASE,
        why="Three-word option label.",
        tokens=("tat ca binh luan",),
    ),
}


def _fb_comment_filter_sheet_open(root: Any) -> bool:
    matched_options: set[str] = set()
    radio_count = 0
    for node in root.iter("node"):
        label = _fb_fold(_fb_node_label(node))
        class_name = str(node.attrib.get("class", "") or "")
        if class_name == "android.widget.RadioButton":
            radio_count += 1
        for option, label_set in _FB_COMMENT_SORT_OPTIONS.items():
            if label_set.matches_folded(label):
                matched_options.add(option)
    return radio_count >= 2 and len(matched_options) >= 2


# The sheet header reads "Đang hiển thị <n> bình luận", so both halves have to
# be present — either alone appears elsewhere.
_FB_COMMENTS_HEADER_TOKENS = LabelSet(
    name="comments_header_tokens",
    mode=MODE_PHRASE,
    why="Three-word header prefix of the comment sheet.",
    tokens=("dang hien thi",),
)

_FB_COMMENTS_HEADER_NOUN = LabelSet(
    name="comments_header_noun",
    mode=MODE_WORD,
    why="'bình luận' as words; only meaningful next to the header prefix.",
    tokens=("binh luan",),
)

_FB_COMMENTS_OVERLAY_TOKENS = LabelSet(
    name="comments_overlay_tokens",
    mode=MODE_PHRASE,
    why="Composer and reply placeholders unique to the comment overlay.",
    tokens=("viet binh luan", "tra loi binh luan"),
)


def _fb_comments_overlay_visible(root: Any) -> bool:
    for node in root.iter("node"):
        label = _fb_fold(_fb_node_label(node))
        header = _FB_COMMENTS_HEADER_TOKENS.matches_folded(
            label
        ) and _FB_COMMENTS_HEADER_NOUN.matches_folded(label)
        if header or _FB_COMMENTS_OVERLAY_TOKENS.matches_folded(label):
            return True
    return False


def _fb_close_comment_filter_sheet_if_needed(dev: Any, root: Any) -> bool:
    if not _fb_comment_filter_sheet_open(root):
        return False
    press = getattr(dev, "press", None)
    if callable(press):
        press("back")
        return True
    return False


def _fb_close_comment_overlay_if_needed(
    dev: Any,
    hierarchy_xml: str,
    *,
    input_terms: list[str],
    input_classes: list[str],
    close_terms: list[str],
) -> bool:
    root = _xml_parse_root(hierarchy_xml)
    if _fb_close_comment_filter_sheet_if_needed(dev, root):
        return True
    has_comment_input = False
    close_candidates: list[tuple[int, int, int, int]] = []
    for node in root.iter("node"):
        label = _fb_node_label(node)
        bounds = _bounds_tuple_from_string(str(node.attrib.get("bounds", "") or ""))
        class_name = str(node.attrib.get("class", "") or "")
        if class_name in input_classes or _social_label_matches(label, input_terms):
            has_comment_input = True
        if (
            bounds
            and _fb_is_clickable(node)
            and _social_label_exact_or_matches(label, close_terms)
        ):
            close_candidates.append(bounds)
    if not has_comment_input:
        return False
    if close_candidates:
        left, top, right, bottom = min(close_candidates, key=lambda item: (item[1], item[0]))
        dev.click((left + right) // 2, (top + bottom) // 2)
        return True
    press = getattr(dev, "press", None)
    if callable(press):
        press("back")
        return True
    return False


def _u2_selector_kwargs_from_xml_node(node: Any) -> dict[str, str]:
    kwargs: dict[str, str] = {}
    class_name = str(node.attrib.get("class", "") or "").strip()
    resource_id = str(node.attrib.get("resource-id", "") or "").strip()
    content_desc = str(node.attrib.get("content-desc", "") or "").strip()
    text = str(node.attrib.get("text", "") or "").strip()
    if class_name:
        kwargs["className"] = class_name
    if resource_id:
        kwargs["resourceId"] = resource_id
    if content_desc:
        kwargs["description"] = content_desc
    if text:
        kwargs["text"] = text
    return kwargs


def _u2_set_text_from_visible_xml_node(dev: Any, node: Any, text: str) -> bool:
    selector_kwargs = _u2_selector_kwargs_from_xml_node(node)
    class_name = selector_kwargs.get("className", "")
    bounds = _bounds_tuple_from_string(str(node.attrib.get("bounds", "") or ""))
    if bounds is not None:
        left, top, right, bottom = bounds
        dev.click((left + right) // 2, (top + bottom) // 2)
    for kwargs in (
        selector_kwargs,
        {"className": class_name} if class_name else {},
        {"className": "android.widget.EditText"},
        {"className": "android.widget.AutoCompleteTextView"},
    ):
        if not kwargs:
            continue
        try:
            dev(**kwargs).set_text(text)
            return True
        except Exception:
            continue
    return False


def _fb_find_visible_comment_input_node(
    root: Any,
    *,
    input_terms: list[str],
    input_classes: list[str],
) -> tuple[Any, tuple[int, int, int, int]] | None:
    for node in root.iter("node"):
        label = _fb_node_label(node)
        bounds = _bounds_tuple_from_string(str(node.attrib.get("bounds", "") or ""))
        if not bounds:
            continue
        class_name = str(node.attrib.get("class", "") or "")
        if class_name in input_classes or _social_label_matches(label, input_terms):
            return node, bounds
    return None


def _fb_set_visible_comment_text(
    dev: Any,
    root: Any,
    comment_text: str,
    *,
    input_terms: list[str],
    input_classes: list[str],
) -> tuple[bool, tuple[int, int, int, int] | None]:
    found = _fb_find_visible_comment_input_node(
        root,
        input_terms=input_terms,
        input_classes=input_classes,
    )
    if found is None:
        return False, None
    node, bounds = found
    if _u2_set_text_from_visible_xml_node(dev, node, comment_text):
        return True, bounds
    return False, bounds


def _fb_scroll_comment_overlay_toward_input(dev: Any, hierarchy_xml: str) -> bool:
    try:
        from relay.extra_data.parsers.facebook.comment_pipeline import (
            resolve_comment_scroll_swipe_from_xml,
        )
    except Exception:
        resolve_comment_scroll_swipe_from_xml = None
    swipe: tuple[int, int, int, int] | None = None
    if resolve_comment_scroll_swipe_from_xml is not None:
        try:
            swipe = resolve_comment_scroll_swipe_from_xml(hierarchy_xml, distance_ratio=0.28)
        except Exception:
            swipe = None
    if swipe is None:
        try:
            width, height = dev.window_size()
        except Exception:
            width, height = 1080, 2400
        x = int(width * 0.78)
        swipe = (x, int(height * 0.70), x, int(height * 0.42))
    fx, fy, tx, ty = swipe
    try:
        dev.swipe(fx, fy, tx, ty, duration=0.16)
        return True
    except Exception:
        return False


def _fb_screen_right(root: Any) -> int:
    right = 0
    for node in root.iter("node"):
        bounds = _bounds_tuple_from_string(str(node.attrib.get("bounds", "") or ""))
        if bounds is not None:
            right = max(right, bounds[2])
    return right or 1260


_FB_AUTHOR_NOISE_PHRASES = LabelSet(
    name="author_noise_phrases",
    mode=MODE_PHRASE,
    why="Multi-word chrome around a post header.",
    tokens=(
        "anh dai dien",
        "profile picture",
        "lua chon khac",
        "more options",
        "theo doi",
        "chia se voi",
        "shared with",
        "cong khai",
        "nhom cong khai",
        "duoc tai tro",
        "xem them",
        "see more",
    ),
)

# The timestamp and privacy words a post header carries. As substrings these are
# name syllables: "gio" is inside "Giới" and "Giỏi", so an author called Nguyễn
# Văn Giới was silently thrown away as chrome. Whole words only.
_FB_AUTHOR_NOISE_WORDS = LabelSet(
    name="author_noise_words",
    mode=MODE_WORD,
    why="Single words that are substrings of real Vietnamese names.",
    tokens=("follow", "gio", "phut", "ngay", "public", "sponsored"),
)


def _fb_is_author_noise(folded: str) -> bool:
    return _FB_AUTHOR_NOISE_PHRASES.matches_folded(
        folded
    ) or _FB_AUTHOR_NOISE_WORDS.matches_folded(folded)


def _fb_author_label_from_node(label: str) -> str:
    raw = str(label or "").strip()
    folded = _fb_fold(raw)
    for prefix in (
        "anh dai dien cua ",
        "profile picture of ",
        "profile photo of ",
    ):
        if folded.startswith(prefix):
            return raw[len(prefix) :].strip(" ,.")
    for sep in ("•", "·"):
        if sep in raw:
            raw = raw.split(sep, 1)[0]
    return raw.strip(" ,.")


def _fb_author_label_allowed(label: str) -> bool:
    clean = _fb_author_label_from_node(label)
    folded = _fb_fold(clean)
    if not folded or len(clean) > 96:
        return False
    if _fb_is_author_noise(folded):
        return False
    if _fb_is_connection_action_label(clean):
        return False
    if _fb_is_comment_action_label(clean) or _fb_is_add_friend_label(clean):
        return False
    compact = folded.replace(" ", "")
    if compact in {"go", "gogo", "banbe", "friends"}:
        return False
    return True


def _fb_author_candidate_near_post(
    root: Any,
    *,
    like_bounds: tuple[int, int, int, int],
    comment_bounds: tuple[int, int, int, int],
) -> dict[str, Any] | None:
    action_top = min(like_bounds[1], comment_bounds[1])
    search_top = max(0, action_top - 1300)
    search_bottom = max(0, action_top - 80)
    candidates: list[tuple[int, dict[str, Any]]] = []
    for node in root.iter("node"):
        label = _fb_node_label(node)
        bounds = _bounds_tuple_from_string(str(node.attrib.get("bounds", "") or ""))
        if not label or not bounds or not _fb_is_clickable(node):
            continue
        left, top, right, bottom = bounds
        if bottom < search_top or top > search_bottom:
            continue
        if right < 40 or left > 1080:
            continue
        clean = _fb_author_label_from_node(label)
        if not _fb_author_label_allowed(clean):
            continue
        score = 0
        klass = str(node.attrib.get("class", "") or "")
        if "Button" in klass:
            score += 45
        if "ImageView" in klass and "anh dai dien" in _fb_fold(label):
            score += 25
        if 120 <= left <= 760:
            score += 25
        if len(clean) <= 42:
            score += 10
        score += max(0, 20 - abs((bottom + top) // 2 - (action_top - 1050)) // 80)
        candidates.append(
            (
                -score,
                {
                    "label": clean,
                    "bounds": list(bounds),
                    "tap": [(left + right) // 2, (top + bottom) // 2],
                    "score": score,
                },
            )
        )
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]["bounds"][1], item[1]["bounds"][0]))
    return candidates[0][1]


def _fb_like_took_effect(
    dev: Any,
    *,
    fingerprint: str,
    keywords: list[str],
    match_mode: str,
    terms: dict[str, list[str]],
) -> bool:
    """Did the like actually register on the post it was aimed at?

    Re-finds the post by content fingerprint rather than by position, so a feed
    that scrolled or loaded new items above does not turn a successful like into
    a failure — or, worse, let another post's button answer for this one.

    A post that has scrolled out of view cannot be checked; that reports as
    unverified rather than as success, because the honest answer to "did it
    work" is "unknown" and a caller that needs certainty should be able to see
    the difference.
    """
    try:
        after_xml = dev.dump_hierarchy(compressed=False)
    except Exception:
        return False
    candidates, _qualified, _expands, _rows = _fb_visible_post_candidates(
        after_xml,
        keywords=keywords,
        match_mode=match_mode,
        seen_fingerprints=set(),
        seen_expand_keys=set(),
        like_terms=terms["like_terms"],
        liked_terms=terms["liked_terms"],
        comment_terms=terms["comment_terms"],
        forbidden_context_terms=terms["forbidden_context_terms"],
    )
    for item in candidates:
        if str(item.get("fingerprint")) == fingerprint:
            return bool(item.get("already_liked"))
    return False


def _fb_post_fingerprint(
    context_labels: list[str],
    *,
    like_terms: list[str],
    liked_terms: list[str],
    comment_terms: list[str],
) -> str:
    """Identify a post by its content, independent of its own action state.

    The action labels sit inside the same context band as the post text, so
    hashing the band wholesale gave a post one identity before it was liked and
    a different one after — "Thích" becomes "Bỏ thích". That broke the two
    things the identity exists for: the seen-set stopped recognising a post the
    moment it was liked (so it could be commented on twice on the next sweep),
    and a like could not be verified by re-finding the post it was aimed at.
    """
    action_terms = [*like_terms, *liked_terms, *comment_terms]
    stable = [
        label
        for label in dict.fromkeys(context_labels)
        if not _social_label_matches(label, action_terms)
    ]
    text = " ".join(stable)
    return hashlib.sha256(_fb_fold(text[:512]).encode("utf-8")).hexdigest()


def _fb_visible_post_candidates(
    hierarchy_xml: str,
    *,
    keywords: list[str],
    match_mode: str,
    seen_fingerprints: set[str],
    seen_expand_keys: set[str],
    like_terms: list[str],
    liked_terms: list[str],
    comment_terms: list[str],
    forbidden_context_terms: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    root = _xml_parse_root(hierarchy_xml)
    screen_right = _fb_screen_right(root)
    like_nodes: list[tuple[tuple[int, int, int, int], str, bool]] = []
    comment_nodes: list[tuple[tuple[int, int, int, int], str]] = []
    for node in root.iter("node"):
        label = _fb_node_label(node)
        bounds = _bounds_tuple_from_string(str(node.attrib.get("bounds", "") or ""))
        if not bounds or not _fb_is_clickable(node):
            continue
        is_like = _social_label_matches(label, like_terms) or _social_label_matches(
            label,
            liked_terms,
        )
        if is_like:
            like_nodes.append((bounds, label, _social_label_matches(label, liked_terms)))
        if not is_like and _social_label_matches(label, comment_terms):
            comment_nodes.append((bounds, label))

    candidates: list[dict[str, Any]] = []
    expand_requests: list[dict[str, Any]] = []
    # Rows whose structure was recognised, counted before any keyword filter.
    # `candidates` only ever holds posts that already matched, so it cannot tell
    # "nothing on screen looked like a post" from "posts found, keywords missed".
    rows_seen = 0
    for comment_bounds, comment_label in comment_nodes:
        comment_center_y = (comment_bounds[1] + comment_bounds[3]) // 2
        nearby_likes = [
            (bounds, label, active)
            for bounds, label, active in like_nodes
            if abs(((bounds[1] + bounds[3]) // 2) - comment_center_y) <= 180
        ]
        if not nearby_likes:
            continue
        like_bounds, like_label, already_liked = min(
            nearby_likes,
            key=lambda item: (abs(item[0][0] - comment_bounds[0]), item[0][0]),
        )
        action_top = min(like_bounds[1], comment_bounds[1])
        expand_search_bounds = (
            0,
            max(0, action_top - 900),
            screen_right,
            action_top + 80,
        )
        expand_bounds = _fb_see_more_bounds_near(root, expand_search_bounds)
        if expand_bounds is not None:
            expand_key = ":".join(str(part) for part in expand_bounds)
            if expand_key not in seen_expand_keys:
                expand_requests.append(
                    {
                        "expand_bounds": list(expand_bounds),
                        "expand_key": expand_key,
                        "like_bounds": list(like_bounds),
                        "comment_bounds": list(comment_bounds),
                    }
                )
                continue
        context_bounds = (
            min(like_bounds[0], comment_bounds[0]),
            min(like_bounds[1], comment_bounds[1]),
            max(like_bounds[2], comment_bounds[2]),
            max(like_bounds[3], comment_bounds[3]),
        )
        context_labels = _fb_nearby_labels(root, context_bounds, y_padding=760)
        context_text = " ".join(dict.fromkeys(context_labels))
        folded_context = _fb_fold(context_text)
        if any(token in folded_context for token in forbidden_context_terms):
            continue
        author = _fb_author_candidate_near_post(
            root,
            like_bounds=like_bounds,
            comment_bounds=comment_bounds,
        )
        rows_seen += 1
        matched, matched_terms = _fb_scan_post_keyword_match(
            context_text,
            terms=keywords,
            match_mode=match_mode,
        )
        if not matched:
            continue
        fingerprint = _fb_post_fingerprint(
            context_labels,
            like_terms=like_terms,
            liked_terms=liked_terms,
            comment_terms=comment_terms,
        )
        if fingerprint in seen_fingerprints:
            continue
        candidates.append(
            {
                "score": 80 + min(len(matched_terms) * 10, 40),
                "row_text": context_text[:700],
                "matched_keywords": matched_terms,
                "like_bounds": list(like_bounds),
                "comment_bounds": list(comment_bounds),
                "author_label": author.get("label") if author else None,
                "author_bounds": author.get("bounds") if author else None,
                "author_tap": author.get("tap") if author else None,
                "like_label": like_label,
                "comment_label": comment_label,
                "already_liked": already_liked,
                "target_id": f"ui_post:{fingerprint}",
                "fingerprint": fingerprint,
            }
        )

    qualified = sorted(
        candidates,
        key=lambda item: (int(item["comment_bounds"][1]), -int(item["score"])),
    )
    return candidates, qualified, expand_requests, rows_seen


def _flow_social_scan_posts_interact(dev: Any, p: dict) -> dict:
    """Scan visible social posts and like/comment only keyword matches."""
    keywords = _fb_scan_keyword_terms(p.get("keywords") or p.get("post_keywords"))
    terms = _social_post_terms(p)
    input_classes = _social_input_classes(p)
    match_mode = str(p.get("match_mode") or "any").strip().casefold()
    if match_mode not in {"any", "all"}:
        match_mode = "any"
    comment_text = str(p.get("comment_text") or "").strip()
    target_count = max(1, int(p.get("target_count", p.get("batch_size", 1)) or 1))
    max_scrolls = max(0, int(p.get("max_scrolls", 0) or 0))
    comment_wait_s = max(0.0, min(float(p.get("comment_wait_s", 0.8) or 0.8), 5.0))
    submit_wait_s = max(0.0, min(float(p.get("submit_wait_s", 0.6) or 0.6), 5.0))
    scroll_wait_s = max(0.0, min(float(p.get("scroll_wait_s", 0.7) or 0.7), 5.0))
    require_comment = _fb_bool_param(p.get("require_comment"), bool(comment_text))
    like_post = _fb_bool_param(p.get("like_post"), True)
    # Verification costs one hierarchy read per liked post. That is the price of
    # knowing whether the most-executed action in the system did anything; a
    # throughput-first run can decline it, but then `liked` means "tapped".
    verify_like = _fb_bool_param(p.get("verify_like"), True)
    seen_fingerprints: set[str] = set()
    seen_expand_keys: set[str] = set()
    actions: list[dict[str, Any]] = []
    total_candidates = 0
    total_rows_seen = 0
    screens_scanned = 0
    scrolls = 0
    overlay_closes = 0
    expanded_more_count = 0
    last_xml = ""

    blocked_surface: dict[str, Any] | None = None
    stuck_surface: dict[str, Any] | None = None

    for screen_index in range(max_scrolls + 1):
        xml = dev.dump_hierarchy(compressed=False)

        # This flow never asked what screen it was on. That is how it spent 88
        # iterations swiping a group-join form: no post rows to find, nothing
        # failing, ok every time.
        surface = _fb_handle_unexpected_surface(dev, xml)
        if surface.get("state") == SURFACE_BLOCKED:
            blocked_surface = surface
            break
        if surface.get("state") == SURFACE_DISMISSABLE and not surface.get("cleared"):
            stuck_surface = surface
            break
        xml = surface.get("xml") or xml

        if _fb_close_comment_overlay_if_needed(
            dev,
            xml,
            input_terms=terms["comment_input_terms"],
            input_classes=input_classes,
            close_terms=terms["overlay_close_terms"],
        ):
            overlay_closes += 1
            time.sleep(min(max(comment_wait_s, 0.2), 0.8))
            xml = dev.dump_hierarchy(compressed=False)
        last_xml = xml
        screen_expands = 0
        while True:
            candidates, qualified, expand_requests, rows_seen = _fb_visible_post_candidates(
                xml,
                keywords=keywords,
                match_mode=match_mode,
                seen_fingerprints=seen_fingerprints,
                seen_expand_keys=seen_expand_keys,
                like_terms=terms["like_terms"],
                liked_terms=terms["liked_terms"],
                comment_terms=terms["comment_terms"],
                forbidden_context_terms=terms["forbidden_context_terms"],
            )
            if not expand_requests or screen_expands >= 2:
                break
            request = expand_requests[0]
            seen_expand_keys.add(str(request["expand_key"]))
            left, top, right, bottom = request["expand_bounds"]
            dev.click((left + right) // 2, (top + bottom) // 2)
            expanded_more_count += 1
            screen_expands += 1
            time.sleep(0.2)
            xml = dev.dump_hierarchy(compressed=False)
            last_xml = xml
        total_candidates += len(candidates)
        total_rows_seen += rows_seen
        screens_scanned += 1

        for candidate in qualified:
            seen_fingerprints.add(str(candidate["fingerprint"]))
            liked = bool(candidate.get("already_liked"))
            like_verified = liked
            if like_post and not liked:
                left, top, right, bottom = candidate["like_bounds"]
                dev.click((left + right) // 2, (top + bottom) // 2)
                time.sleep(submit_wait_s)
                # The tap used to be assumed successful. It is the most
                # frequently executed action in the system and it was the only
                # one that never checked, so a miss looked exactly like a hit.
                like_verified = (
                    _fb_like_took_effect(
                        dev,
                        fingerprint=str(candidate["fingerprint"]),
                        keywords=keywords,
                        match_mode=match_mode,
                        terms=terms,
                    )
                    if verify_like
                    else False
                )
                liked = True if not verify_like else like_verified

            commented = False
            comment_error = ""
            if comment_text:
                left, top, right, bottom = candidate["comment_bounds"]
                dev.click((left + right) // 2, (top + bottom) // 2)
                time.sleep(comment_wait_s)
                comment_xml = dev.dump_hierarchy(compressed=False)
                comment_root = _xml_parse_root(comment_xml)
                if _fb_close_comment_filter_sheet_if_needed(dev, comment_root):
                    time.sleep(min(max(comment_wait_s, 0.2), 0.8))
                    comment_xml = dev.dump_hierarchy(compressed=False)
                    comment_root = _xml_parse_root(comment_xml)
                input_ok, input_bounds = _fb_set_visible_comment_text(
                    dev,
                    comment_root,
                    comment_text,
                    input_terms=terms["comment_input_terms"],
                    input_classes=input_classes,
                )
                if not input_ok:
                    if _fb_comments_overlay_visible(comment_root):
                        if _fb_scroll_comment_overlay_toward_input(dev, comment_xml):
                            time.sleep(min(max(comment_wait_s, 0.2), 0.8))
                            comment_xml = dev.dump_hierarchy(compressed=False)
                            comment_root = _xml_parse_root(comment_xml)
                            if _fb_close_comment_filter_sheet_if_needed(dev, comment_root):
                                time.sleep(min(max(comment_wait_s, 0.2), 0.8))
                                comment_xml = dev.dump_hierarchy(compressed=False)
                                comment_root = _xml_parse_root(comment_xml)
                            input_ok, input_bounds = _fb_set_visible_comment_text(
                                dev,
                                comment_root,
                                comment_text,
                                input_terms=terms["comment_input_terms"],
                                input_classes=input_classes,
                            )
                        if not input_ok:
                            comment_error = "comment input not found"
                    else:
                        dev.click((left + right) // 2, (top + bottom) // 2)
                        time.sleep(comment_wait_s)
                        comment_xml = dev.dump_hierarchy(compressed=False)
                        comment_root = _xml_parse_root(comment_xml)
                        if _fb_close_comment_filter_sheet_if_needed(dev, comment_root):
                            time.sleep(min(max(comment_wait_s, 0.2), 0.8))
                            comment_xml = dev.dump_hierarchy(compressed=False)
                            comment_root = _xml_parse_root(comment_xml)
                        input_ok, input_bounds = _fb_set_visible_comment_text(
                            dev,
                            comment_root,
                            comment_text,
                            input_terms=terms["comment_input_terms"],
                            input_classes=input_classes,
                        )
                        if not input_ok:
                            comment_error = "comment input not found"
                if input_ok:
                    comment_error = ""
                if not comment_error:
                    time.sleep(0.2)
                    submit_xml = dev.dump_hierarchy(compressed=False)
                    submit_root = _xml_parse_root(submit_xml)
                    found_input = _fb_find_visible_comment_input_node(
                        submit_root,
                        input_terms=terms["comment_input_terms"],
                        input_classes=input_classes,
                    )
                    if found_input is not None:
                        _node, input_bounds = found_input
                    submit_bounds = _fb_find_comment_submit_bounds(
                        submit_root,
                        submit_terms=terms["comment_submit_terms"],
                        input_bounds=input_bounds,
                    )
                    if submit_bounds is None:
                        comment_error = "comment submit button not found"
                    else:
                        left, top, right, bottom = submit_bounds
                        dev.click((left + right) // 2, (top + bottom) // 2)
                        time.sleep(submit_wait_s)
                        commented = True

            if require_comment and comment_text and not commented:
                actions.append(
                    {
                        "verified": False,
                        "target_type": "post",
                        "source": "visible_feed",
                        "target_id": candidate["target_id"],
                        "matched_keywords": candidate["matched_keywords"],
                        "row_text": candidate["row_text"],
                        "like_bounds": candidate["like_bounds"],
                        "comment_bounds": candidate["comment_bounds"],
                        "author_label": candidate.get("author_label"),
                        "author_bounds": candidate.get("author_bounds"),
                        "author_tap": candidate.get("author_tap"),
                        "liked": liked,
                        "like_verified": like_verified,
                        "commented": False,
                        "error": comment_error or "comment not submitted",
                    }
                )
                continue

            actions.append(
                {
                    "verified": True,
                    "target_type": "post",
                    "source": "visible_feed",
                    "target_id": candidate["target_id"],
                    "matched_keywords": candidate["matched_keywords"],
                    "row_text": candidate["row_text"],
                    "like_bounds": candidate["like_bounds"],
                    "comment_bounds": candidate["comment_bounds"],
                    "author_label": candidate.get("author_label"),
                    "author_bounds": candidate.get("author_bounds"),
                    "author_tap": candidate.get("author_tap"),
                    "liked": liked,
                    "like_verified": like_verified,
                    "commented": commented,
                }
            )
            verified_count = len([item for item in actions if item.get("verified") is True])
            if verified_count >= target_count:
                break

        verified_actions = [item for item in actions if item.get("verified") is True]
        if len(verified_actions) >= target_count:
            break
        if screen_index >= max_scrolls:
            break
        if not _fb_scroll_people_surface(dev, p):
            break
        scrolls += 1
        time.sleep(scroll_wait_s)

    verified_actions = [item for item in actions if item.get("verified") is True]

    if blocked_surface is not None and not verified_actions:
        return {
            "verified": False,
            "batch": True,
            "reason": "account_blocked",
            "retryable": False,
            "message": str(
                blocked_surface.get("message") or "account-level block detected"
            ),
            "surface_state": blocked_surface.get("state"),
            "surface_marker": blocked_surface.get("marker"),
            "interacted_count": 0,
            "screens_scanned": screens_scanned,
        }
    if stuck_surface is not None and not verified_actions:
        return {
            "verified": False,
            "batch": True,
            "reason": "surface_not_dismissable",
            "retryable": False,
            "message": (
                "a dialog covered the feed and one Back did not clear it: "
                f"{stuck_surface.get('marker') or 'unrecognised screen'}"
            ),
            "surface_state": stuck_surface.get("state"),
            "surface_marker": stuck_surface.get("marker"),
            "surface_fingerprint": stuck_surface.get("fingerprint"),
            "interacted_count": 0,
            "screens_scanned": screens_scanned,
        }

    if not verified_actions:
        return {
            "verified": False,
            "batch": True,
            # Two different problems that used to share one reason. A feed with
            # nothing on topic is normal and the caller should scroll on; a
            # screen with no post rows at all means we are not on a feed, and
            # repeating the scan there is the 88-iteration spin.
            "reason": (
                "screen_is_not_a_feed" if total_rows_seen == 0 else "no_matching_post"
            ),
            # Say which half failed. "Nothing matched" reads the same whether
            # the scanner saw twenty posts and rejected them all or never
            # recognised a post at all, and those need opposite fixes: one is a
            # keyword problem, the other means the action row was not found.
            "message": (
                "no post action row was recognised on any screen scanned"
                if total_rows_seen == 0
                else (
                    f"{total_rows_seen} post(s) recognised across "
                    f"{screens_scanned} screen(s) but none matched keywords "
                    f"{keywords!r} (match_mode={match_mode!r})"
                )
            ),
            "rows_seen": total_rows_seen,
            "target_count": target_count,
            "interacted_count": 0,
            "candidate_count": total_candidates,
            "screens_scanned": screens_scanned,
            "scrolls": scrolls,
            "overlay_closes": overlay_closes,
            "expanded_more_count": expanded_more_count,
            "keywords": keywords,
            "actions": actions[:5],
            "xml_chars": len(last_xml or ""),
        }

    return {
        "verified": True,
        "batch": True,
        "target_type": "post",
        "source": "visible_feed",
        "target_count": target_count,
        "interacted_count": len(verified_actions),
        "liked_count": len([item for item in verified_actions if item.get("liked")]),
        "commented_count": len(
            [item for item in verified_actions if item.get("commented")]
        ),
        "candidate_count": total_candidates,
        "rows_seen": total_rows_seen,
        "screens_scanned": screens_scanned,
        "scrolls": scrolls,
        "overlay_closes": overlay_closes,
        "expanded_more_count": expanded_more_count,
        "keywords": keywords,
        "actions": verified_actions,
        "message": f"interacted with {len(verified_actions)} matching feed posts",
    }


def _fb_see_more_bounds_near(
    root: Any,
    bounds: tuple[int, int, int, int],
) -> tuple[int, int, int, int] | None:
    left, top, right, bottom = bounds
    matches: list[tuple[int, int, int, int]] = []
    for node in root.iter("node"):
        label = _fb_node_label(node)
        node_bounds = _bounds_tuple_from_string(str(node.attrib.get("bounds", "") or ""))
        folded = _fb_fold(label)
        if node_bounds is None:
            continue
        if folded in ("xem them", "see more"):
            tap_bounds = node_bounds
        elif _FB_SEE_MORE_TOKENS.matches_folded(folded):
            node_left, node_top, node_right, node_bottom = node_bounds
            tap_bounds = (
                max(node_left, node_right - 320),
                node_top,
                node_right,
                node_bottom,
            )
        else:
            continue
        if tap_bounds[2] < left or tap_bounds[0] > right:
            continue
        if tap_bounds[3] < top - 80 or tap_bounds[1] > bottom + 80:
            continue
        matches.append(tap_bounds)
    if not matches:
        return None
    return min(matches, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))


def _fb_people_candidates(
    hierarchy_xml: str,
    *,
    display_name: str,
    search: str,
    required: list[str],
    optional: list[str],
    forbidden: list[str],
    min_score: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    root = _xml_parse_root(hierarchy_xml)
    candidates: list[dict[str, Any]] = []
    for node in root.iter("node"):
        label = _fb_node_label(node)
        bounds = _bounds_tuple_from_string(str(node.attrib.get("bounds", "") or ""))
        if (
            not bounds
            or not _fb_is_clickable(node)
            or not _fb_is_connection_action_label(label)
        ):
            continue
        row_labels = _fb_same_row_labels(root, bounds)
        row_text = " ".join(dict.fromkeys(row_labels))
        score, matched, missing, forbidden_hit = _fb_score_text(
            row_text,
            display_name=display_name,
            search=search,
            required=required,
            optional=optional,
            forbidden=forbidden,
        )
        if forbidden_hit or missing:
            continue
        display_folded = _fb_fold(display_name)
        label_bounds: list[tuple[int, int, int, int]] = []
        action_center_y = (bounds[1] + bounds[3]) // 2
        for label_node in root.iter("node"):
            candidate_label = _fb_node_label(label_node)
            candidate_bounds = _bounds_tuple_from_string(
                str(label_node.attrib.get("bounds", "") or "")
            )
            if not candidate_bounds or not display_folded:
                continue
            if display_folded not in _fb_fold(candidate_label):
                continue
            candidate_center_y = (candidate_bounds[1] + candidate_bounds[3]) // 2
            if abs(candidate_center_y - action_center_y) <= 180:
                label_bounds.append(candidate_bounds)
        target_label_bounds = (
            min(
                label_bounds,
                key=lambda item: (
                    item[3] - item[1],
                    (item[2] - item[0]) * (item[3] - item[1]),
                ),
            )
            if label_bounds
            else None
        )
        candidates.append(
            {
                "score": score + 5,
                "matched_keywords": matched,
                "row_text": row_text[:512],
                "bounds": list(bounds),
                "label_bounds": list(target_label_bounds) if target_label_bounds else None,
            }
        )

    qualified = [c for c in candidates if int(c["score"]) >= min_score]
    qualified.sort(key=lambda item: int(item["score"]), reverse=True)
    return candidates, qualified


def _flow_fb_select_people_profile(dev: Any, p: dict) -> dict:
    """Open one verified Facebook People profile without sending a friend request."""
    min_score = max(0, int(p.get("min_score", 80) or 80))
    require_unique = bool(p.get("require_unique", True))
    search = str(p.get("search") or "")
    display_name = str(p.get("display_name") or p.get("row_text") or search)
    required = _fb_keyword_list(p.get("required_keywords"))
    optional = _fb_keyword_list(p.get("optional_keywords"))
    forbidden = _fb_keyword_list(p.get("forbidden_keywords"))
    if display_name and display_name not in required:
        required = [display_name, *required]

    search_xml = dev.dump_hierarchy(compressed=False)
    candidates, qualified = _fb_people_candidates(
        search_xml,
        display_name=display_name,
        search=search,
        required=required,
        optional=optional,
        forbidden=forbidden,
        min_score=min_score,
    )
    if not qualified:
        return {
            "verified": False,
            "reason": "target_not_found",
            "message": "no Facebook People row matched required keywords",
            "candidate_count": len(candidates),
            "search_xml_chars": len(search_xml or ""),
        }
    if require_unique and len(qualified) > 1:
        return {
            "verified": False,
            "reason": "ambiguous_target",
            "message": "multiple Facebook People rows matched required keywords",
            "candidate_count": len(candidates),
            "ambiguous_count": len(qualified),
            "top_candidates": qualified[:3],
            "search_xml_chars": len(search_xml or ""),
        }

    confirmation_xml = dev.dump_hierarchy(compressed=False)
    confirmed_candidates, confirmed_qualified = _fb_people_candidates(
        confirmation_xml,
        display_name=display_name,
        search=search,
        required=required,
        optional=optional,
        forbidden=forbidden,
        min_score=min_score,
    )
    if not confirmed_qualified:
        return {
            "verified": False,
            "reason": "target_changed",
            "message": "Facebook People target changed before click",
            "candidate_count": len(confirmed_candidates),
            "search_xml_chars": len(search_xml or ""),
            "confirmation_xml_chars": len(confirmation_xml or ""),
        }
    if require_unique and len(confirmed_qualified) > 1:
        return {
            "verified": False,
            "reason": "ambiguous_target",
            "message": "multiple Facebook People rows matched before click",
            "candidate_count": len(confirmed_candidates),
            "ambiguous_count": len(confirmed_qualified),
            "top_candidates": confirmed_qualified[:3],
            "search_xml_chars": len(search_xml or ""),
            "confirmation_xml_chars": len(confirmation_xml or ""),
        }

    selected = confirmed_qualified[0]
    label_bounds = selected.get("label_bounds")
    if isinstance(label_bounds, list) and len(label_bounds) == 4:
        left, top, right, bottom = label_bounds
        tap_x = min(right - 1, left + 40)
        tap_y = min(bottom - 1, top + 30)
    else:
        left, top, _right, bottom = selected["bounds"]
        tap_x = max(1, left - 220)
        tap_y = (top + bottom) // 2
    dev.click(tap_x, tap_y)
    time.sleep(max(0.0, min(float(p.get("profile_wait_s", 1.0) or 1.0), 10.0)))

    profile_xml = dev.dump_hierarchy(compressed=False)
    profile_root = _xml_parse_root(profile_xml)
    profile_text = " ".join(_fb_all_labels(profile_root))
    profile_display_name = _fb_profile_display_name(display_name)
    profile_required = [
        profile_display_name
        if _fb_fold(token) == _fb_fold(display_name)
        else token
        for token in required
    ]
    profile_score, matched, missing, forbidden_hit = _fb_score_text(
        profile_text,
        display_name=profile_display_name,
        search=search,
        required=profile_required,
        optional=optional,
        forbidden=forbidden,
    )
    action_buttons: list[dict[str, Any]] = []
    for node in profile_root.iter("node"):
        label = _fb_node_label(node)
        bounds = _bounds_tuple_from_string(str(node.attrib.get("bounds", "") or ""))
        if (
            bounds
            and _fb_is_clickable(node)
            and _fb_is_connection_action_label(label)
        ):
            action_buttons.append({"label": label, "bounds": list(bounds)})
    action_buttons = _fb_dedupe_action_buttons(action_buttons)

    if forbidden_hit or missing or profile_score < min_score:
        return {
            "verified": False,
            "reason": "profile_not_verified",
            "message": "opened profile did not satisfy required keywords",
            "candidate_count": len(candidates),
            "missing_keywords": missing,
            "matched_keywords": matched,
            "confidence": profile_score,
            "selected_bounds": selected["bounds"],
            "profile_xml_chars": len(profile_xml or ""),
        }
    if len(action_buttons) != 1:
        return {
            "verified": False,
            "reason": "ambiguous_profile_action",
            "message": "profile does not expose exactly one Add Friend button",
            "candidate_count": len(candidates),
            "action_count": len(action_buttons),
            "selected_bounds": selected["bounds"],
            "action_buttons": action_buttons[:3],
            "profile_xml_chars": len(profile_xml or ""),
        }

    return {
        "verified": True,
        "target_type": "person",
        "source": "agent_boot",
        "confidence": max(int(selected["score"]), profile_score),
        "matched_keywords": list(dict.fromkeys([*selected["matched_keywords"], *matched])),
        "selected_bounds": selected["bounds"],
        "selected_label_bounds": selected.get("label_bounds"),
        "selected_tap": [tap_x, tap_y],
        "action_bounds": action_buttons[0]["bounds"],
        "candidate_count": len(candidates),
        "search_xml_chars": len(search_xml or ""),
        "confirmation_xml_chars": len(confirmation_xml or ""),
        "profile_xml_chars": len(profile_xml or ""),
    }


def _flow_fb_open_author_from_post_match(dev: Any, p: dict) -> dict:
    """Open and verify the author profile for one matched feed post action."""
    action = p.get("action") if isinstance(p.get("action"), dict) else {}
    if not action:
        return {
            "verified": False,
            "reason": "source_action_missing",
            "message": "matched post action payload is missing",
        }

    author_label = _fb_author_label_from_node(
        str(p.get("display_name") or action.get("author_label") or "")
    )
    author_tap = action.get("author_tap")
    like_bounds = action.get("like_bounds")
    comment_bounds = action.get("comment_bounds")
    if (
        not author_label
        or not _fb_author_label_allowed(author_label)
        or not isinstance(author_tap, list)
        or len(author_tap) != 2
        or not isinstance(like_bounds, list)
        or len(like_bounds) != 4
        or not isinstance(comment_bounds, list)
        or len(comment_bounds) != 4
    ):
        return {
            "verified": False,
            "reason": "author_binding_missing",
            "message": "matched post action does not expose a safe author binding",
            "source_action": {
                "target_id": action.get("target_id"),
                "author_label": action.get("author_label"),
            },
        }

    min_score = max(0, int(p.get("min_score", 80) or 80))
    required = _fb_keyword_list(p.get("required_keywords"))
    optional = _fb_keyword_list(p.get("optional_keywords"))
    forbidden = _fb_keyword_list(p.get("forbidden_keywords"))
    if author_label and author_label not in required:
        required = [author_label, *required]

    before_xml = dev.dump_hierarchy(compressed=False)
    terms = _social_post_terms(p)
    input_classes = _social_input_classes(p)
    if _fb_close_comment_overlay_if_needed(
        dev,
        before_xml,
        input_terms=terms["comment_input_terms"],
        input_classes=input_classes,
        close_terms=terms["overlay_close_terms"],
    ):
        time.sleep(max(0.1, min(float(p.get("overlay_close_wait_s", 0.3) or 0.3), 2.0)))
        before_xml = dev.dump_hierarchy(compressed=False)
    before_root = _xml_parse_root(before_xml)
    current_author = _fb_author_candidate_near_post(
        before_root,
        like_bounds=tuple(int(v) for v in like_bounds),
        comment_bounds=tuple(int(v) for v in comment_bounds),
    )
    if not current_author or _fb_fold(current_author.get("label")) != _fb_fold(author_label):
        return {
            "verified": False,
            "reason": "author_target_changed",
            "message": "matched post author is no longer visible at the expected row",
            "expected_author": author_label,
            "current_author": current_author,
            "before_xml_chars": len(before_xml or ""),
        }

    tap_x, tap_y = int(current_author["tap"][0]), int(current_author["tap"][1])
    dev.click(tap_x, tap_y)
    time.sleep(max(0.0, min(float(p.get("profile_wait_s", 1.0) or 1.0), 10.0)))

    profile_xml = dev.dump_hierarchy(compressed=False)
    profile_root = _xml_parse_root(profile_xml)
    profile_text = " ".join(_fb_all_labels(profile_root))
    profile_score, matched, missing, forbidden_hit = _fb_score_text(
        profile_text,
        display_name=author_label,
        search=str(p.get("search") or author_label),
        required=required,
        optional=optional,
        forbidden=forbidden,
    )
    action_buttons: list[dict[str, Any]] = []
    for node in profile_root.iter("node"):
        label = _fb_node_label(node)
        bounds = _bounds_tuple_from_string(str(node.attrib.get("bounds", "") or ""))
        if not bounds or not _fb_is_clickable(node):
            continue
        if _fb_is_add_friend_label(label) or _fb_is_connection_action_label(label):
            action_buttons.append({"label": label, "bounds": list(bounds)})
    action_buttons = _fb_dedupe_action_buttons(action_buttons)

    if forbidden_hit or missing or profile_score < min_score:
        return {
            "verified": False,
            "reason": "profile_not_verified",
            "message": "opened author profile did not satisfy profile keywords",
            "expected_author": author_label,
            "missing_keywords": missing,
            "matched_keywords": matched,
            "confidence": profile_score,
            "profile_opened": True,
            "source_post_target_id": action.get("target_id"),
            "profile_xml_chars": len(profile_xml or ""),
        }
    if len(action_buttons) != 1:
        return {
            "verified": False,
            "reason": "ambiguous_profile_action",
            "message": "author profile does not expose exactly one connection action",
            "expected_author": author_label,
            "action_count": len(action_buttons),
            "action_buttons": action_buttons[:3],
            "profile_opened": True,
            "source_post_target_id": action.get("target_id"),
            "profile_xml_chars": len(profile_xml or ""),
        }

    target_id_source = f"{action.get('target_id') or ''}|{_fb_fold(author_label)}"
    return {
        "verified": True,
        "target_type": "person",
        "source": "matched_feed_post_author",
        "confidence": profile_score,
        "target_id": "ui_author:" + hashlib.sha256(
            target_id_source.encode("utf-8")
        ).hexdigest(),
        "name": author_label,
        "display_name": author_label,
        "matched_keywords": matched,
        "selected_bounds": current_author["bounds"],
        "selected_tap": [tap_x, tap_y],
        "action_bounds": action_buttons[0]["bounds"],
        "profile_opened": True,
        "source_post_target_id": action.get("target_id"),
        "source_post_keywords": action.get("matched_keywords") or [],
        "before_xml_chars": len(before_xml or ""),
        "profile_xml_chars": len(profile_xml or ""),
    }


def _flow_social_open_author_from_post_match(dev: Any, p: dict) -> dict:
    platform = str(p.get("platform") or "facebook").strip().casefold()
    if platform == "facebook":
        return _flow_fb_open_author_from_post_match(dev, p)
    return {
        "verified": False,
        "reason": "unsupported_platform",
        "message": f"author-from-post resolver is not implemented for {platform!r}",
        "platform": platform,
    }


def _fb_commenter_author_nodes(
    root: Any,
    comments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    authors = [
        _fb_author_label_from_node(str(item.get("author") or ""))
        for item in comments
        if str(item.get("author") or "").strip()
    ]
    folded_authors = [(_fb_fold(author), author) for author in authors]
    restrict_to_parsed_authors = bool(folded_authors)
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node in root.iter("node"):
        label = _fb_author_label_from_node(_fb_node_label(node))
        folded = _fb_fold(label)
        bounds = _bounds_tuple_from_string(str(node.attrib.get("bounds", "") or ""))
        if not folded or not bounds or folded in seen:
            continue
        if restrict_to_parsed_authors:
            matched_author = next(
                (
                    author
                    for folded_author, author in folded_authors
                    if folded_author and folded == folded_author
                ),
                None,
            )
            if matched_author is None:
                continue
        else:
            matched_author = label
            if _FB_COMMENT_SHEET_CHROME.matches_folded(folded):
                continue
        if not _fb_author_label_allowed(matched_author):
            continue
        if bounds[1] < 260:
            continue
        class_name = str(node.attrib.get("class", "") or "")
        clickable = _fb_is_clickable(node)
        if not clickable and "TextView" not in class_name and "Button" not in class_name:
            continue
        tap_x = min(bounds[2] - 1, bounds[0] + max(24, min(80, (bounds[2] - bounds[0]) // 3)))
        tap_y = (bounds[1] + bounds[3]) // 2
        seen.add(folded)
        comment = next(
            (item for item in comments if _fb_fold(item.get("author")) == folded),
            {},
        )
        candidates.append(
            {
                "author_label": matched_author,
                "comment_text": str(comment.get("text") or "")[:512],
                "comment_key": comment.get("comment_key"),
                "bounds": list(bounds),
                "tap": [tap_x, tap_y],
            }
        )
    candidates.sort(key=lambda item: (int(item["bounds"][1]), int(item["bounds"][0])))
    return candidates


def _flow_fb_open_commenter_from_post_match(dev: Any, p: dict) -> dict:
    """Open and verify a commenter profile from a matched feed post action."""
    action = p.get("action") if isinstance(p.get("action"), dict) else {}
    comment_bounds = action.get("comment_bounds") if action else None
    if (
        not action
        or not isinstance(comment_bounds, list)
        or len(comment_bounds) != 4
    ):
        return {
            "verified": False,
            "reason": "comment_binding_missing",
            "message": "matched post action does not expose comment bounds",
            "source_action": {"target_id": action.get("target_id") if action else None},
        }

    min_score = max(0, int(p.get("min_score", 80) or 80))
    required = _fb_keyword_list(p.get("required_keywords"))
    optional = _fb_keyword_list(p.get("optional_keywords"))
    forbidden = _fb_keyword_list(p.get("forbidden_keywords"))
    wait_s = max(0.0, min(float(p.get("comment_wait_s", 1.0) or 1.0), 10.0))
    profile_wait_s = max(0.0, min(float(p.get("profile_wait_s", 1.0) or 1.0), 10.0))
    max_commenters = max(1, int(p.get("max_commenters", 5) or 5))

    left, top, right, bottom = [int(v) for v in comment_bounds]
    dev.click((left + right) // 2, (top + bottom) // 2)
    time.sleep(wait_s)

    comments_xml = dev.dump_hierarchy(compressed=False)
    comments, diagnostic = parse_fb_comments_from_xml_with_diagnostic(
        comments_xml,
        parent_post_id=str(action.get("target_id") or ""),
        max_items=max_commenters,
    )
    comments_root = _xml_parse_root(comments_xml)
    if _fb_close_comment_filter_sheet_if_needed(dev, comments_root):
        time.sleep(min(max(wait_s, 0.2), 0.8))
        comments_xml = dev.dump_hierarchy(compressed=False)
        comments, diagnostic = parse_fb_comments_from_xml_with_diagnostic(
            comments_xml,
            parent_post_id=str(action.get("target_id") or ""),
            max_items=max_commenters,
        )
        comments_root = _xml_parse_root(comments_xml)
    candidates = _fb_commenter_author_nodes(comments_root, comments)[:max_commenters]
    if not candidates:
        return {
            "verified": False,
            "reason": "no_commenter_candidate",
            "message": "comment sheet did not expose a tappable commenter candidate",
            "profile_opened": False,
            "comment_sheet_opened": True,
            "comment_count": len(comments),
            "diagnostic": diagnostic,
            "source_post_target_id": action.get("target_id"),
            "comments_xml_chars": len(comments_xml or ""),
        }

    tried: list[dict[str, Any]] = []
    press = getattr(dev, "press", None)
    for candidate in candidates:
        author_label = str(candidate.get("author_label") or "")
        profile_required = required
        if author_label and author_label not in profile_required:
            profile_required = [author_label, *profile_required]
        tap_x, tap_y = int(candidate["tap"][0]), int(candidate["tap"][1])
        dev.click(tap_x, tap_y)
        time.sleep(profile_wait_s)

        profile_xml = dev.dump_hierarchy(compressed=False)
        profile_root = _xml_parse_root(profile_xml)
        profile_text = " ".join(_fb_all_labels(profile_root))
        profile_score, matched, missing, forbidden_hit = _fb_score_text(
            profile_text,
            display_name=author_label,
            search=str(p.get("search") or author_label),
            required=profile_required,
            optional=optional,
            forbidden=forbidden,
        )
        owner = _fb_profile_owner_connection(profile_xml, author_label)
        if not owner.get("found"):
            # A profile opened from a comment can land mid-page, hiding the
            # owner's action row and leaving suggestion cards as the only
            # connection controls in view. Pay for the scroll only when the
            # first read came up empty.
            if _fb_scroll_profile_to_top(dev):
                profile_xml = dev.dump_hierarchy(compressed=False)
                profile_root = _xml_parse_root(profile_xml)
                profile_text = " ".join(_fb_all_labels(profile_root))
                owner = _fb_profile_owner_connection(profile_xml, author_label)
        action_buttons = (
            [{"label": owner.get("label"), "bounds": owner.get("bounds")}]
            if owner.get("found")
            else []
        )

        if (
            not forbidden_hit
            and not missing
            and profile_score >= min_score
            and owner.get("found")
            and owner.get("state") == FRIEND_STATE_AVAILABLE
        ):
            target_id_source = (
                f"{action.get('target_id') or ''}|{candidate.get('comment_key') or ''}|"
                f"{_fb_fold(author_label)}"
            )
            return {
                "verified": True,
                "target_type": "person",
                "source": "matched_feed_post_commenter",
                "confidence": profile_score,
                "target_id": "ui_commenter:" + hashlib.sha256(
                    target_id_source.encode("utf-8")
                ).hexdigest(),
                "name": author_label,
                "display_name": author_label,
                "matched_keywords": matched,
                "selected_bounds": candidate["bounds"],
                "selected_tap": [tap_x, tap_y],
                "action_bounds": action_buttons[0]["bounds"],
                "profile_opened": True,
                "comment_sheet_opened": True,
                "source_post_target_id": action.get("target_id"),
                "source_comment_key": candidate.get("comment_key"),
                "source_comment_text": candidate.get("comment_text"),
                "comments_xml_chars": len(comments_xml or ""),
                "profile_xml_chars": len(profile_xml or ""),
            }

        tried.append(
            {
                "author_label": author_label,
                "reason": (
                    "profile_not_verified"
                    if forbidden_hit or missing or profile_score < min_score
                    else str(owner.get("reason") or "")
                    or (
                        f"already_{owner.get('state')}"
                        if owner.get("found")
                        else "owner_action_row_not_found"
                    )
                ),
                "owner_state": owner.get("state"),
                "missing_keywords": missing,
                "matched_keywords": matched,
                "confidence": profile_score,
                "action_count": len(action_buttons),
            }
        )
        if callable(press):
            press("back")
            time.sleep(min(max(wait_s, 0.2), 0.8))

    reason_counts: dict[str, int] = {}
    for item in tried:
        key = str(item.get("reason") or "unknown")
        reason_counts[key] = reason_counts.get(key, 0) + 1
    breakdown = ", ".join(f"{k}×{v}" for k, v in sorted(reason_counts.items()))
    return {
        "verified": False,
        "reason": "no_verified_commenter_profile",
        # Name the reason each profile was turned away. "Satisfied no keywords"
        # is the same sentence whether the profile scored too low, tripped a
        # forbidden term, or simply showed more than one connection control —
        # and those need different fixes.
        "message": (
            f"opened {len(tried)} commenter profile(s), none accepted"
            + (f" ({breakdown})" if breakdown else "")
        ),
        "profile_opened": False,
        "comment_sheet_opened": True,
        "candidate_count": len(candidates),
        "tried": tried,
        "source_post_target_id": action.get("target_id"),
        "comments_xml_chars": len(comments_xml or ""),
    }


def _flow_social_open_commenter_from_post_match(dev: Any, p: dict) -> dict:
    platform = str(p.get("platform") or "facebook").strip().casefold()
    if platform == "facebook":
        return _flow_fb_open_commenter_from_post_match(dev, p)
    return {
        "verified": False,
        "reason": "unsupported_platform",
        "message": f"commenter-from-post resolver is not implemented for {platform!r}",
        "platform": platform,
    }


_FB_COMMON_CONTEXT_TOKENS = LabelSet(
    name="common_context_tokens",
    mode=MODE_PHRASE,
    why=(
        "Matched against a whole suggestion row, which is mostly a person's "
        "name — so two-word wording only. 'nhom'/'ban' alone would qualify "
        "every row and 'trang' would discard every person named Trang."
    ),
    tokens=(
        "ban chung",
        "mutual friend",
        "mutual friends",
        "cung nhom",
        "same group",
    ),
)

# Same-group used to score 30 against a default floor of 40, so it could never
# qualify a row on its own. That made the token dead weight exactly where it
# matters: an account with no friends has no mutuals, and shared groups are the
# only common context it can build. Group context is now worth as much as a
# mutual friend.
_FB_COMMON_CONTEXT_SCORES = {
    "ban chung": 40,
    "mutual friend": 40,
    "mutual friends": 40,
    "cung nhom": 40,
    "same group": 40,
}
# Substring match on the whole row. Only unambiguous phrases belong here.
#
# "trang" and "page" used to live in this list, which silently discarded every
# suggestion named Trang — one of the most common Vietnamese given names — since
# the row text is folded and matched as a substring. "theo doi"/"follow" was just
# as wrong: a person row carries a Follow button next to Add Friend. A row that
# exposes an Add Friend button is a person by construction, so the guard only
# needs to catch ads and anonymised entries.
_FB_NON_PERSON_CONTEXT_TOKENS = LabelSet(
    name="non_person_context_tokens",
    mode=MODE_PHRASE,
    why="Ad and anonymity wording that cannot occur inside a person's name.",
    tokens=(
        "like page",
        "thich trang",
        "advertisement",
        "duoc tai tro",
        "sponsored",
        "anonymous",
        "nguoi tham gia an danh",
    ),
)

# Matched on word boundaries only, so "Tham gia" (a group card) is caught while
# a name containing the same letters is not.
_FB_NON_PERSON_WORD_TOKENS = LabelSet(
    name="non_person_word_tokens",
    mode=MODE_WORD,
    why="'join' as a substring hits nothing here, but as a rule short verbs stay words.",
    tokens=("tham gia", "join"),
    collides_with_names=("tham gia",),
    collision_reason=(
        "A row whose text puts 'Thắm' next to 'Gia' is dropped as a group card. "
        "Accepted: that ordering is rare, while a group's 'Tham gia' button "
        "entering the person pipeline means friend-requesting a group."
    ),
)


def _fb_has_non_person_marker(folded_row_text: str) -> bool:
    return _FB_NON_PERSON_CONTEXT_TOKENS.matches_folded(
        folded_row_text
    ) or _FB_NON_PERSON_WORD_TOKENS.matches_folded(folded_row_text)


def _fb_visible_connectable_people(
    hierarchy_xml: str,
    *,
    common_keywords: list[str],
    forbidden_keywords: list[str],
    min_score: int,
    require_common: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Returns (candidates, qualified, rejected).

    `rejected` carries the row text and the exact gate that dropped it. A cold
    account rejects every row, and without this the flow could only report the
    count — leaving no way to tell "Facebook shows no context" apart from "our
    token list does not match this build's wording".
    """
    root = _xml_parse_root(hierarchy_xml)
    parents = _fb_parent_map(root)
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    common_tokens = tuple(
        token for token in (_fb_fold(item) for item in common_keywords) if token
    )
    forbidden_tokens = tuple(
        token for token in (_fb_fold(item) for item in forbidden_keywords) if token
    )

    def _reject(reason: str, row_text: str, **extra: Any) -> None:
        if len(rejected) < 24:
            rejected.append({"reason": reason, "row_text": row_text[:256], **extra})

    for node in root.iter("node"):
        label = _fb_node_label(node)
        bounds = _bounds_tuple_from_string(str(node.attrib.get("bounds", "") or ""))
        if not bounds or not _fb_is_clickable(node) or not _fb_is_add_friend_label(label):
            continue
        package_name = str(node.attrib.get("package", "") or "")
        if package_name and not package_name.startswith("com.facebook"):
            continue

        scope = _fb_person_row_scope(root, parents, node)
        row_labels = (
            _fb_row_labels_in_scope(scope)
            if scope is not None
            else _fb_visible_person_row_labels(root, bounds)
        )
        row_text = " ".join(dict.fromkeys(row_labels))
        folded = _fb_fold(row_text)
        if any(token and token in folded for token in forbidden_tokens):
            _reject("forbidden_keyword", row_text)
            continue
        if _fb_has_non_person_marker(folded):
            _reject("non_person_row", row_text)
            continue

        matched_common: list[str] = []
        score = 0
        mutual_count = _fb_mutual_count_from_text(row_text)
        for token in _FB_COMMON_CONTEXT_TOKENS.all_matches_folded(folded):
            matched_common.append(token)
            score += _FB_COMMON_CONTEXT_SCORES.get(token, 30)
        if mutual_count > 0:
            score += min(mutual_count, 10) * 5
        for token in common_tokens:
            if token in folded:
                matched_common.append(token)
                score += 20
        matched_common = list(dict.fromkeys(matched_common))
        if require_common and not matched_common:
            _reject("no_common_context", row_text)
            continue

        display_name = _fb_display_name_from_row(row_labels, row_text)
        folded_name = _fb_fold(display_name)
        if not folded_name or folded_name.replace(" ", "") in {"go", "gogo"}:
            _reject("no_display_name", row_text)
            continue
        fingerprint_src = (
            f"{folded_name}|{mutual_count}|{'|'.join(sorted(matched_common))}"
        )
        candidate = {
            "score": score,
            "row_text": row_text[:512],
            "display_name": display_name,
            "matched_common": matched_common,
            "mutual_count": mutual_count,
            "action_bounds": list(bounds),
            "target_id": "ui:" + hashlib.sha256(
                fingerprint_src.encode("utf-8")
            ).hexdigest(),
        }
        candidates.append(candidate)
        if int(score) < min_score:
            _reject(
                "below_min_score",
                row_text,
                score=int(score),
                min_score=int(min_score),
                matched_common=matched_common,
            )

    qualified = [item for item in candidates if int(item["score"]) >= min_score]
    qualified.sort(
        key=lambda item: (
            -int(item.get("mutual_count") or 0),
            -int(item["score"]),
            int(item["action_bounds"][1]),
            int(item["action_bounds"][0]),
        )
    )
    return candidates, qualified, rejected


# A moving list settles quickly; a few re-scans is generous. Beyond that the
# surface is churning and tapping into it is not safe.
_FB_MAX_RELOCATE_ATTEMPTS = 3


def _fb_confirm_candidate_bounds(dev: Any, candidate: dict[str, Any]) -> dict[str, Any] | None:
    """Re-locate the candidate immediately before tapping.

    Returns the candidate with fresh bounds, or None when the same person is no
    longer offering an Add Friend button at a matching position. Coordinates
    captured from an earlier dump are only trustworthy while the list is still;
    Facebook's friends surface is not, because it inserts pending-request cards
    above the suggestions after the first render.
    """
    target_id = str(candidate.get("target_id") or "")
    if not target_id:
        return candidate
    try:
        fresh_xml = dev.dump_hierarchy(compressed=False)
    except Exception:
        return candidate
    fresh, _qualified, _rejected = _fb_visible_connectable_people(
        fresh_xml,
        common_keywords=[],
        forbidden_keywords=[],
        min_score=0,
        require_common=False,
    )
    for item in fresh:
        if str(item.get("target_id") or "") == target_id:
            return {**candidate, "action_bounds": item["action_bounds"]}
    return None


def _flow_fb_connect_visible_people(dev: Any, p: dict) -> dict:
    """Send connection requests from visible suggestion rows with common context."""
    min_score = max(0, int(p.get("min_score", 40) or 40))
    require_common = _fb_bool_param(p.get("require_common"), True)
    common_keywords = _fb_keyword_list(p.get("common_keywords"))
    forbidden_keywords = _fb_keyword_list(p.get("forbidden_keywords"))
    open_surface = _fb_bool_param(p.get("open_surface"), False)
    dry_run = _fb_bool_param(p.get("dry_run"), False)
    batch_mode = (
        open_surface
        or dry_run
        or p.get("target_count") is not None
        or p.get("max_scrolls") is not None
        or _fb_bool_param(p.get("batch"), False)
    )
    target_count = max(1, int(p.get("target_count", 1) or 1))
    max_scrolls = max(0, int(p.get("max_scrolls", 0) or 0))
    no_more_common_limit = max(
        1, int(p.get("no_more_common_limit", 3) or 3)
    )
    stop_on_unverified = _fb_bool_param(p.get("stop_on_unverified"), True)
    wait_s = max(0.0, min(float(p.get("verify_wait_s", 0.8) or 0.8), 5.0))
    scroll_wait_s = max(0.0, min(float(p.get("scroll_wait_s", 0.7) or 0.7), 4.0))

    surface_result: dict[str, Any] | None = None
    initial_xml: str | None = None
    if open_surface:
        surface_result = _fb_open_friend_suggestions_surface(dev, p)
        initial_xml = str(surface_result.get("xml") or "")
        if not surface_result.get("ready"):
            return {
                "verified": False,
                "batch": batch_mode,
                "reason": surface_result.get("reason") or "friend_surface_not_ready",
                "message": "Facebook friend suggestions surface was not ready",
                "surface": surface_result,
                "before_xml_chars": len(initial_xml or ""),
            }

    if batch_mode:
        sent: list[dict[str, Any]] = []
        eligible: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        seen_target_ids: set[str] = set()
        screens_scanned = 0
        scrolls = 0
        total_candidates = 0
        total_qualified = 0
        no_more_common_screens = 0
        relocate_attempts = 0
        rejected_sample: list[dict[str, Any]] = []
        last_xml = initial_xml

        for screen_index in range(max_scrolls + 1):
            made_progress_on_screen = False
            while len(sent) < target_count:
                # Reused XML is second-hand: it came from the surface opener or
                # from the dump taken right after the previous tap, and the list
                # re-flows in between. Track that so the tap can be re-aimed.
                reused_xml = last_xml is not None
                before_xml = (
                    last_xml
                    if reused_xml
                    else dev.dump_hierarchy(compressed=False)
                )
                last_xml = None
                root = _xml_parse_root(before_xml)
                surface = _fb_handle_unexpected_surface(dev, before_xml)
                if surface.get("cleared"):
                    before_xml = surface.get("xml") or before_xml
                    root = _xml_parse_root(before_xml)
                    reused_xml = False
                elif surface.get("state") == SURFACE_DISMISSABLE:
                    # Computed and then ignored until now, which meant a sheet we
                    # could already name still blocked every send silently.
                    return {
                        "verified": False,
                        "batch": True,
                        "reason": "surface_not_dismissable",
                        "retryable": False,
                        "message": (
                            "a dialog covered the people list and one Back did "
                            f"not clear it: {surface.get('marker') or 'unrecognised screen'}"
                        ),
                        "surface_state": surface.get("state"),
                        "surface_marker": surface.get("marker"),
                        "surface_fingerprint": surface.get("fingerprint"),
                        "sent_count": len(sent),
                        "sent": sent,
                        "screens_scanned": screens_scanned,
                    }
                if surface["state"] == SURFACE_BLOCKED:
                    # Never retried: repeating an action against a checkpoint is
                    # how a recoverable account becomes an unrecoverable one.
                    return {
                        "verified": False,
                        "batch": True,
                        "reason": "account_blocked",
                        "retryable": False,
                        "message": str(surface.get("message") or "account-level block"),
                        "surface_state": surface["state"],
                        "surface_marker": surface.get("marker"),
                        "surface_fingerprint": _fb_surface_fingerprint(before_xml),
                        "sent_count": len(sent),
                        "sent": sent,
                        "screens_scanned": screens_scanned,
                    }
                if _fb_dismiss_friend_suggestion_prompt(dev, root):
                    time.sleep(wait_s)
                    before_xml = dev.dump_hierarchy(compressed=False)
                    root = _xml_parse_root(before_xml)
                candidates, qualified, rejected = _fb_visible_connectable_people(
                    before_xml,
                    common_keywords=common_keywords,
                    forbidden_keywords=forbidden_keywords,
                    min_score=min_score,
                    require_common=require_common,
                )
                total_candidates += len(candidates)
                total_qualified += len(qualified)
                for entry in rejected:
                    if len(rejected_sample) < 24:
                        rejected_sample.append(entry)
                next_candidate = next(
                    (
                        item
                        for item in qualified
                        if str(item.get("target_id") or "") not in seen_target_ids
                    ),
                    None,
                )
                if next_candidate is None:
                    if made_progress_on_screen:
                        # Reset, not accumulate: no_more_common_limit is meant to
                        # stop after N *consecutive* barren screens.
                        no_more_common_screens = 0
                    else:
                        no_more_common_screens += 1
                    break

                seen_target_ids.add(str(next_candidate.get("target_id") or ""))
                eligible.append(next_candidate)
                made_progress_on_screen = True
                if dry_run:
                    if len(eligible) >= target_count:
                        break
                    continue

                confirmed = (
                    _fb_confirm_candidate_bounds(dev, next_candidate)
                    if reused_xml
                    else next_candidate
                )
                if confirmed is None:
                    # The list moved between the dump and the tap — on a real
                    # device an incoming friend-request card can appear at the
                    # top after the surface renders and push every row down, so
                    # the stored coordinates now point at someone else. Re-scan
                    # instead of tapping blind.
                    skipped.append(
                        {
                            "reason": "row_moved_before_tap",
                            "target_id": next_candidate.get("target_id"),
                            "display_name": next_candidate.get("display_name"),
                            "action_bounds": next_candidate.get("action_bounds"),
                        }
                    )
                    seen_target_ids.discard(str(next_candidate.get("target_id") or ""))
                    if eligible and eligible[-1] is next_candidate:
                        eligible.pop()
                    if relocate_attempts >= _FB_MAX_RELOCATE_ATTEMPTS:
                        break
                    relocate_attempts += 1
                    continue

                next_candidate = confirmed
                left, top, right, bottom = next_candidate["action_bounds"]
                tap_x = (left + right) // 2
                tap_y = (top + bottom) // 2
                guard = _fb_guarded_click(dev, _xml_parse_root(before_xml), tap_x, tap_y)
                if not guard["tapped"]:
                    # Last line of defence: whatever picked these coordinates,
                    # the control sitting there is one that must never be
                    # pressed. On this surface the neighbour is "Gỡ", and the
                    # overflow sheet behind it can hide the suggestion feed for
                    # good.
                    skipped.append(
                        {
                            "reason": "blocked_destructive_control",
                            "blocked_label": guard["blocked_label"],
                            "target_id": next_candidate.get("target_id"),
                            "display_name": next_candidate.get("display_name"),
                            "action_bounds": next_candidate.get("action_bounds"),
                        }
                    )
                    break
                time.sleep(wait_s)

                after_xml = dev.dump_hierarchy(compressed=False)
                # Identity first: the row is gone or its button changed => sent.
                # Fall back to the positional read only when the name is unknown.
                candidate_id = str(next_candidate.get("target_id") or "")
                if candidate_id:
                    request_sent = not _fb_still_offering_add_friend(
                        after_xml, candidate_id
                    )
                else:
                    request_sent = _fb_pending_request_near(after_xml, tap_y)
                if not request_sent:
                    skipped.append(
                        {
                            "reason": "request_not_verified",
                            "target_id": next_candidate.get("target_id"),
                            "display_name": next_candidate.get("display_name"),
                            "action_bounds": next_candidate.get("action_bounds"),
                        }
                    )
                    last_xml = after_xml
                    if stop_on_unverified:
                        return {
                            "verified": False,
                            "batch": True,
                            "reason": "request_not_verified",
                            "message": (
                                "Add Friend tap did not verify as pending request; "
                                "stopped before tapping another candidate"
                            ),
                            "target_count": target_count,
                            "sent_count": len(sent),
                            "sent": sent,
                            "eligible_count": len(eligible),
                            "candidate_count": total_candidates,
                            "qualified_count": total_qualified,
                            "skipped": skipped,
                            "screens_scanned": screens_scanned + 1,
                            "scrolls": scrolls,
                            "surface": surface_result,
                        }
                    continue

                sent.append(
                    {
                        "verified": True,
                        "target_type": "person",
                        "source": "visible_people_surface",
                        "confidence": int(next_candidate["score"]),
                        "target_id": next_candidate["target_id"],
                        "display_name": next_candidate.get("display_name")
                        or next_candidate.get("row_text", "")[:120],
                        "matched_common": next_candidate["matched_common"],
                        "mutual_count": next_candidate.get("mutual_count", 0),
                        "row_text": next_candidate["row_text"],
                        "action_bounds": next_candidate["action_bounds"],
                        "selected_tap": [tap_x, tap_y],
                    }
                )
                last_xml = after_xml

            screens_scanned += 1
            if len(sent) >= target_count or (dry_run and len(eligible) >= target_count):
                break
            if no_more_common_screens >= no_more_common_limit:
                break
            if screen_index >= max_scrolls:
                break
            if not _fb_scroll_people_surface(dev, p):
                break
            scrolls += 1
            time.sleep(scroll_wait_s)

        action_count = len(sent)
        if dry_run:
            return {
                "verified": False,
                "batch": True,
                "dry_run": True,
                "reason": "dry_run",
                "message": "dry-run scanned visible friend suggestions without sending requests",
                "target_count": target_count,
                "eligible_count": len(eligible),
                "sent_count": 0,
                "sent": [],
                "eligible": eligible[:target_count],
                "candidate_count": total_candidates,
                "qualified_count": total_qualified,
                "rejected": rejected_sample,
                "skipped": skipped,
                "screens_scanned": screens_scanned,
                "scrolls": scrolls,
                "surface": surface_result,
            }

        if action_count <= 0:
            return {
                "verified": False,
                "batch": True,
                "reason": "no_common_connectable_people",
                "message": "no Add Friend row with common context was sent after batch scan",
                "target_count": target_count,
                "sent_count": 0,
                "sent": [],
                "eligible_count": len(eligible),
                "candidate_count": total_candidates,
                "qualified_count": total_qualified,
                "rejected": rejected_sample,
                "skipped": skipped,
                "screens_scanned": screens_scanned,
                "scrolls": scrolls,
                "surface": surface_result,
            }

        return {
            "verified": True,
            "batch": True,
            "target_type": "person",
            "source": "visible_people_surface",
            "target_count": target_count,
            "sent_count": action_count,
            "sent": sent,
            "eligible_count": len(eligible),
            "candidate_count": total_candidates,
            "qualified_count": total_qualified,
            "skipped": skipped,
            "screens_scanned": screens_scanned,
            "scrolls": scrolls,
            "surface": surface_result,
            "message": f"sent {action_count} visible friend requests with common context",
        }

    before_xml = dev.dump_hierarchy(compressed=False)
    candidates, qualified, rejected = _fb_visible_connectable_people(
        before_xml,
        common_keywords=common_keywords,
        forbidden_keywords=forbidden_keywords,
        min_score=min_score,
        require_common=require_common,
    )
    if not qualified:
        return {
            "verified": False,
            "reason": "no_common_connectable_people",
            "message": "no visible Add Friend row satisfied common-context score",
            "candidate_count": len(candidates),
            "rejected": rejected,
            "before_xml_chars": len(before_xml or ""),
        }

    selected = qualified[0]
    left, top, right, bottom = selected["action_bounds"]
    tap_x = (left + right) // 2
    tap_y = (top + bottom) // 2
    dev.click(tap_x, tap_y)
    time.sleep(wait_s)

    after_xml = dev.dump_hierarchy(compressed=False)
    if not _fb_pending_request_near(after_xml, tap_y):
        return {
            "verified": False,
            "reason": "request_not_verified",
            "message": "Add Friend tap did not verify as pending request",
            "candidate_count": len(candidates),
            "selected": selected,
            "selected_tap": [tap_x, tap_y],
            "before_xml_chars": len(before_xml or ""),
            "after_xml_chars": len(after_xml or ""),
        }

    return {
        "verified": True,
        "target_type": "person",
        "source": "visible_people_surface",
        "confidence": int(selected["score"]),
        "target_id": selected["target_id"],
        "display_name": selected.get("display_name")
        or selected["row_text"].split("  ")[0][:120],
        "matched_common": selected["matched_common"],
        "mutual_count": selected.get("mutual_count", 0),
        "row_text": selected["row_text"],
        "action_bounds": selected["action_bounds"],
        "selected_tap": [tap_x, tap_y],
        "candidate_count": len(candidates),
        "before_xml_chars": len(before_xml or ""),
        "after_xml_chars": len(after_xml or ""),
    }


def _flow_fb_select_post_target(dev: Any, p: dict) -> dict:
    """Open one verified Facebook post target before content interaction."""
    min_score = max(0, int(p.get("min_score", 80) or 80))
    require_unique = bool(p.get("require_unique", True))
    current_detail = bool(p.get("current_detail", False))
    search = str(p.get("search") or "")
    display_text = str(p.get("display_text") or p.get("row_text") or search)
    required = _fb_keyword_list(p.get("required_keywords"))
    optional = _fb_keyword_list(p.get("optional_keywords"))
    forbidden = _fb_keyword_list(p.get("forbidden_keywords"))
    if display_text and display_text not in required:
        required = [display_text, *required]
    primary_anchor = _fb_fold(display_text or (required[0] if required else search))

    search_xml = dev.dump_hierarchy(compressed=False)
    root = _xml_parse_root(search_xml)
    search_suggestion_bounds = (
        _fb_search_suggestion_bounds(
            root,
            display_text=display_text,
            search=search,
            required=required,
        )
        if _fb_search_input_focused(root)
        else None
    )
    if search_suggestion_bounds is not None:
        left, top, right, bottom = search_suggestion_bounds
        dev.click((left + right) // 2, (top + bottom) // 2)
        time.sleep(max(0.0, min(float(p.get("search_wait_s", 1.0) or 1.0), 10.0)))
        search_xml = dev.dump_hierarchy(compressed=False)
        root = _xml_parse_root(search_xml)

    candidates: list[dict[str, Any]] = []
    for node in root.iter("node"):
        label = _fb_node_label(node)
        bounds = _bounds_tuple_from_string(str(node.attrib.get("bounds", "") or ""))
        if not label or not bounds:
            continue
        if str(node.attrib.get("class", "") or "") == "android.widget.EditText":
            continue
        if _fb_is_post_search_chrome_label(label):
            continue
        context_labels = _fb_nearby_labels(root, bounds, y_padding=420)
        context_text = " ".join(dict.fromkeys(context_labels))
        direct_partial_score, direct_partial_matches = _fb_post_partial_score(
            label,
            display_text=display_text,
            search=search,
            required=required,
        )
        partial_score, partial_matches = _fb_post_partial_score(
            context_text,
            display_text=display_text,
            search=search,
            required=required,
        )
        if primary_anchor and primary_anchor not in _fb_fold(label):
            if direct_partial_score <= 0:
                continue
        if direct_partial_score > partial_score:
            partial_score = direct_partial_score
            partial_matches = direct_partial_matches
        score, matched, missing, forbidden_hit = _fb_score_text(
            context_text,
            display_name=display_text,
            search=search,
            required=required,
            optional=optional,
            forbidden=forbidden,
        )
        if forbidden_hit:
            continue
        if missing and partial_score <= 0:
            continue
        if partial_score > score:
            score = partial_score
            matched = [*matched, *partial_matches]
        candidates.append(
            {
                "score": score,
                "matched_keywords": list(dict.fromkeys(matched)),
                "text": label[:512],
                "bounds": list(bounds),
                "clickable": _fb_is_clickable(node),
            }
        )

    candidates = _fb_dedupe_post_candidates(candidates)
    qualified = [c for c in candidates if int(c["score"]) >= min_score]
    qualified.sort(key=lambda item: int(item["score"]), reverse=True)
    if not qualified:
        return {
            "verified": False,
            "reason": "target_not_found",
            "message": "no Facebook post candidate matched required keywords",
            "candidate_count": len(candidates),
            "search_xml_chars": len(search_xml or ""),
        }
    if require_unique and len(qualified) > 1:
        return {
            "verified": False,
            "reason": "ambiguous_target",
            "message": "multiple Facebook post candidates matched required keywords",
            "candidate_count": len(candidates),
            "ambiguous_count": len(qualified),
            "top_candidates": qualified[:3],
            "search_xml_chars": len(search_xml or ""),
        }

    selected = qualified[0]
    if current_detail:
        detail_text = " ".join(_fb_all_labels(root))
        detail_score, matched, missing, forbidden_hit = _fb_score_text(
            detail_text,
            display_name=display_text,
            search=search,
            required=required,
            optional=optional,
            forbidden=forbidden,
        )
        action_buttons: list[dict[str, Any]] = []
        for node in root.iter("node"):
            label = _fb_node_label(node)
            bounds = _bounds_tuple_from_string(str(node.attrib.get("bounds", "") or ""))
            if bounds and _fb_is_clickable(node) and _fb_is_content_action_label(label):
                action_buttons.append({"label": label, "bounds": list(bounds)})
        action_buttons = _fb_dedupe_action_buttons(action_buttons)
        partial_detail_score, partial_detail_matches = _fb_post_partial_score(
            detail_text,
            display_text=display_text,
            search=search,
            required=required,
        )
        if forbidden_hit or (
            (missing or detail_score < min_score)
            and partial_detail_score < min_score
        ):
            return {
                "verified": False,
                "reason": "post_not_verified",
                "message": "current post detail did not satisfy required keywords",
                "candidate_count": len(candidates),
                "missing_keywords": missing,
                "matched_keywords": list(dict.fromkeys([*matched, *partial_detail_matches])),
                "confidence": max(detail_score, partial_detail_score),
                "detail_xml_chars": len(search_xml or ""),
            }
        if not action_buttons:
            return {
                "verified": False,
                "reason": "post_action_unavailable",
                "message": "current post detail did not expose content interaction buttons",
                "candidate_count": len(candidates),
                "detail_xml_chars": len(search_xml or ""),
            }
        return {
            "verified": True,
            "target_type": "post",
            "source": "agent_boot",
            "confidence": max(int(selected["score"]), detail_score, partial_detail_score),
            "matched_keywords": list(
                dict.fromkeys(
                    [
                        *selected["matched_keywords"],
                        *matched,
                        *partial_detail_matches,
                    ]
                )
            ),
            "selected_bounds": selected["bounds"],
            "already_open": True,
            "action_count": len(action_buttons),
            "action_bounds": action_buttons[0]["bounds"],
            "candidate_count": len(candidates),
            "search_xml_chars": len(search_xml or ""),
            "detail_xml_chars": len(search_xml or ""),
        }

    left, top, right, bottom = selected["bounds"]
    expand_bounds = _fb_see_more_bounds_near(root, (left, top, right, bottom))
    if expand_bounds is not None:
        tap_left, tap_top, tap_right, tap_bottom = expand_bounds
        selected["expand_bounds"] = list(expand_bounds)
    else:
        tap_left, tap_top, tap_right, tap_bottom = left, top, right, bottom
    tap_x = (tap_left + tap_right) // 2
    tap_y = (tap_top + tap_bottom) // 2
    dev.click(tap_x, tap_y)
    time.sleep(max(0.0, min(float(p.get("detail_wait_s", 1.0) or 1.0), 10.0)))

    detail_xml = dev.dump_hierarchy(compressed=False)
    detail_root = _xml_parse_root(detail_xml)
    detail_text = " ".join(_fb_all_labels(detail_root))
    detail_score, matched, missing, forbidden_hit = _fb_score_text(
        detail_text,
        display_name=display_text,
        search=search,
        required=required,
        optional=optional,
        forbidden=forbidden,
    )
    action_buttons: list[dict[str, Any]] = []
    for node in detail_root.iter("node"):
        label = _fb_node_label(node)
        bounds = _bounds_tuple_from_string(str(node.attrib.get("bounds", "") or ""))
        if bounds and _fb_is_clickable(node) and _fb_is_content_action_label(label):
            action_buttons.append({"label": label, "bounds": list(bounds)})
    action_buttons = _fb_dedupe_action_buttons(action_buttons)

    partial_detail_score, partial_detail_matches = _fb_post_partial_score(
        detail_text,
        display_text=display_text,
        search=search,
        required=required,
    )
    if forbidden_hit or (
        (missing or detail_score < min_score)
        and partial_detail_score < min_score
    ):
        return {
            "verified": False,
            "reason": "post_not_verified",
            "message": "opened post did not satisfy required keywords",
            "candidate_count": len(candidates),
            "missing_keywords": missing,
            "matched_keywords": list(dict.fromkeys([*matched, *partial_detail_matches])),
            "confidence": max(detail_score, partial_detail_score),
            "selected_bounds": selected["bounds"],
            "detail_xml_chars": len(detail_xml or ""),
        }
    if not action_buttons:
        return {
            "verified": False,
            "reason": "post_action_unavailable",
            "message": "opened post did not expose content interaction buttons",
            "candidate_count": len(candidates),
            "selected_bounds": selected["bounds"],
            "detail_xml_chars": len(detail_xml or ""),
        }

    return {
        "verified": True,
        "target_type": "post",
        "source": "agent_boot",
        "confidence": max(int(selected["score"]), detail_score, partial_detail_score),
        "matched_keywords": list(
            dict.fromkeys(
                [
                    *selected["matched_keywords"],
                    *matched,
                    *partial_detail_matches,
                ]
            )
        ),
        "selected_bounds": selected["bounds"],
        "expand_bounds": selected.get("expand_bounds"),
        "expanded_more": expand_bounds is not None,
        "selected_tap": [tap_x, tap_y],
        "action_count": len(action_buttons),
        "action_bounds": action_buttons[0]["bounds"],
        "candidate_count": len(candidates),
        "search_xml_chars": len(search_xml or ""),
        "detail_xml_chars": len(detail_xml or ""),
    }


# (platform, target_type) → resolver. Adding a platform means adding rows here
# plus its `_flow_<platform>_*` implementations; device_farm is untouched.
_SELECT_TARGET_RESOLVERS: dict[tuple[str, str], Any] = {
    ("facebook", "person"): _flow_fb_select_people_profile,
    ("facebook", "post"): _flow_fb_select_post_target,
}


def _flow_social_select_target(dev: Any, p: dict) -> dict:
    """Resolve and open a verified person/post target for the requested platform."""
    platform = str(p.get("platform") or "facebook").strip().casefold()
    target_type = str(p.get("target_type") or "person").strip().casefold()
    resolver = _SELECT_TARGET_RESOLVERS.get((platform, target_type))
    if resolver is None:
        return {
            "verified": False,
            "reason": "unsupported_platform",
            "message": (
                f"select-target resolver is not implemented for {platform!r}/"
                f"{target_type!r}"
            ),
            "platform": platform,
            "target_type": target_type,
        }
    return resolver(dev, p)


# ── Connection count (the feedback signal) ───────────────────────────────────
#
# Everything upstream — which playbook an account runs, whether a candidate
# source is worth using, whether the account is healthy — depends on one number
# nobody was reading: how many friends the account actually has. Sending is easy
# to observe; growing is not, and only the second one matters.

# "1.234 bạn bè", "1,2K friends", "567 người theo dõi". Vietnamese uses "." as
# the thousands separator and "," as the decimal mark, which is the opposite of
# the English formatting Facebook also emits, so both have to be handled.
# Not a LabelSet: these are never matched on their own. They are only ever the
# tail of _FB_COUNT_RE, so a digit must immediately precede them — which is why
# bare "friend" and "ban be" are safe here and nowhere else.
_FB_COUNT_LABELS: dict[str, tuple[str, ...]] = {
    "friends": ("ban be", "friends", "friend"),
    "followers": ("nguoi theo doi", "followers", "follower"),
}
_FB_COUNT_RE = r"(\d[\d.,]*)\s*(?:tr|m|k|n)?\s*"

# An account with nobody gets an empty-state sentence instead of "0 bạn bè" —
# observed on a real cold account. Without this the one account that most needs
# classifying is the one that reads as "count not visible".
_FB_EMPTY_COUNT_MARKERS: dict[str, LabelSet] = {
    "friends": LabelSet(
        name="empty_count_friends",
        mode=MODE_PHRASE,
        why="Full empty-state sentences.",
        tokens=(
            "khong co ban be nao de hien thi",
            "khong co ban be nao",
            "no friends to show",
            "no friends yet",
        ),
    ),
    "followers": LabelSet(
        name="empty_count_followers",
        mode=MODE_PHRASE,
        why="Full empty-state sentences.",
        tokens=("khong co nguoi theo doi nao", "no followers yet"),
    ),
}


def _fb_parse_count(token: str, suffix: str) -> int | None:
    """Parse a Facebook count token, honouring both number formats."""
    cleaned = token.strip()
    if not cleaned:
        return None
    multiplier = {"k": 1_000, "n": 1_000, "m": 1_000_000, "tr": 1_000_000}.get(
        suffix.strip(), 1
    )
    if multiplier > 1:
        # Abbreviated counts carry a decimal mark: "1,2K" / "1.2K" are both 1200.
        normalized = cleaned.replace(".", ",").replace(",", ".", 1).replace(",", "")
        try:
            return int(float(normalized) * multiplier)
        except ValueError:
            return None
    # Exact counts use separators purely as grouping.
    digits = re.sub(r"[.,]", "", cleaned)
    return int(digits) if digits.isdigit() else None


def _fb_read_count(hierarchy_xml: str, metric: str = "friends") -> dict[str, Any]:
    """Read a follower/friend count off the profile screen.

    Returns the highest match rather than the first: the screen can also show a
    friend's count inside a suggestion row, and the account's own total is the
    larger number on its own profile.
    """
    labels = _FB_COUNT_LABELS.get(metric, ())
    if not labels:
        return {"found": False, "reason": "unsupported_metric", "metric": metric}
    root = _xml_parse_root(hierarchy_xml)
    all_labels = _fb_all_labels(root)
    empty_markers = _FB_EMPTY_COUNT_MARKERS.get(metric)
    for label in all_labels:
        folded = _fb_fold(label)
        if empty_markers is not None and empty_markers.matches_folded(folded):
            return {
                "found": True,
                "metric": metric,
                "value": 0,
                "evidence": label[:120],
                "source": "empty_state",
            }
    best: int | None = None
    evidence = ""
    for label in all_labels:
        folded = _fb_fold(label)
        for token in labels:
            for match in re.finditer(_FB_COUNT_RE + re.escape(token), folded):
                raw = match.group(1)
                suffix = folded[match.end(1) : match.start(0) + len(match.group(0))]
                suffix = suffix.replace(token, "").strip()
                value = _fb_parse_count(raw, suffix)
                if value is not None and (best is None or value > best):
                    best = value
                    evidence = label[:120]
    if best is None:
        return {"found": False, "reason": "count_not_visible", "metric": metric}
    return {
        "found": True,
        "metric": metric,
        "value": best,
        "evidence": evidence,
        "source": "count_label",
    }


def _flow_fb_read_connection_count(dev: Any, p: dict) -> dict:
    """Read the account's own friend count from the profile screen."""
    metric = str(p.get("metric") or "friends").strip().casefold()
    xml = dev.dump_hierarchy(compressed=False)
    result = _fb_read_count(xml, metric)
    result["xml_chars"] = len(xml or "")
    if not result.get("found"):
        result["message"] = (
            f"{metric} count is not visible on the current screen; "
            "open the account profile first"
        )
    return result


_READ_CONNECTION_COUNT_FLOWS: dict[str, Any] = {
    "facebook": _flow_fb_read_connection_count,
}


def _flow_social_sync_connections(dev: Any, p: dict) -> dict:
    platform = str(p.get("platform") or "facebook").strip().casefold()
    flow = _READ_CONNECTION_COUNT_FLOWS.get(platform)
    if flow is None:
        return {
            "found": False,
            "reason": "unsupported_platform",
            "message": f"connection-count read is not implemented for {platform!r}",
            "platform": platform,
        }
    return flow(dev, p)


_CONNECT_VISIBLE_PEOPLE_FLOWS: dict[str, Any] = {
    "facebook": _flow_fb_connect_visible_people,
}


def _flow_social_connect_visible_people(dev: Any, p: dict) -> dict:
    platform = str(p.get("platform") or "facebook").strip().casefold()
    flow = _CONNECT_VISIBLE_PEOPLE_FLOWS.get(platform)
    if flow is None:
        return {
            "verified": False,
            "reason": "unsupported_platform",
            "message": f"connect-visible-people is not implemented for {platform!r}",
            "platform": platform,
        }
    return flow(dev, p)


# Flow names are the platform-neutral contract with device_farm. Per-platform
# implementations stay named `_flow_<platform>_*` and are reached by dispatch.
_FLOW_TABLE: dict[str, Any] = {
    "find_click_wait":   _flow_find_click_wait,
    "wait_and_click":    _flow_wait_and_click,
    "wait_and_click_spec": _flow_wait_and_click_spec,
    "find_get_text":     _flow_find_get_text,
    "swipe_until_found": _flow_swipe_until_found,
    "input_and_confirm": _flow_input_and_confirm,
    "social_select_target": _flow_social_select_target,
    "social_connect_visible_people": _flow_social_connect_visible_people,
    "social_scan_posts_interact": _flow_social_scan_posts_interact,
    "social_open_author_from_post_match": _flow_social_open_author_from_post_match,
    "social_open_commenter_from_post_match": _flow_social_open_commenter_from_post_match,
    "social_sync_connections": _flow_social_sync_connections,
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
            settle_s = _swipe_settle_s(params)
            # Budget only the first probe: the screen may still be rendering,
            # and scrolling a target that is already there away is worse than
            # waiting for it. Later probes stay instant — the settle covers them.
            first_wait_s = _first_wait_s(params)
            for swipes in range(max_swipes + 1):
                probe_budget = first_wait_s if swipes == 0 else 0.0
                probe_deadline = time.monotonic() + probe_budget
                while True:
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
                            timeout_s=probe_budget,
                            compressed=compressed,
                            want_present=True,
                            priority=priority,
                            deadline_ms=deadline_ms,
                            batch_started=batch_started,
                            poll_stat="http_flow_polls",
                            bypass_first_cache=swipes > 0,
                        )
                        found = bool(xml_found["satisfied"])
                        break
                    if found or time.monotonic() >= probe_deadline:
                        break
                    await asyncio.sleep(0.2)
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
                if settle_s:
                    await asyncio.sleep(settle_s)

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
                action = dict(act)
                action["_serial"] = serial
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
                        value = self._run_u2_swipe_batch(serial, action)
                    elif op == "dump_hierarchy" and self._http_dump is not None:
                        timeout = float(action.get("timeout") or action.get("timeout_s") or 5.0)
                        compressed = bool(action.get("compressed", False))
                        value = self._http_dump(serial, timeout, compressed)
                        if value:
                            self._mark_direct_http_healthy(serial)
                        if not value:
                            logger.debug(
                                "u2_batch: atx-http dump empty serial=%s — "
                                "fallback to u2 dump_hierarchy",
                                serial,
                            )
                            value = fn(dev, action)
                    else:
                        value = fn(dev, action)
                    if (
                        op == "app_start"
                        and action.get("use_monkey")
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
