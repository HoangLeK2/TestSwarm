from __future__ import annotations

"""
scenario_task.py — Generic scenario executor for campaigns.

AI/MCP sẽ tạo ra JSON `scenario`, ví dụ:

{
  "steps": [
    { "type": "launch_app", "package": "com.android.chrome" },
    { "type": "wait", "seconds": 3 },
    { "type": "tap_ratio", "x": 0.5, "y": 0.10 },
    { "type": "input_text", "via": "u2", "text": "tin tức mới hôm nay" },
    { "type": "key", "key": "enter" },
    { "type": "wait", "seconds": 4 },
    { "type": "tap_ratio", "x": 0.5, "y": 0.40 },
    { "type": "scroll_down", "repeats": 3 }
  ]
}

Executor này chỉ đọc từng step và gọi DeviceClient/u2 cho phù hợp.
"""

import base64
import asyncio
import concurrent.futures
import io
import json
import logging
import os
import random
import re
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple, TypedDict, Literal, Sequence

from tenacity import retry, stop_after_delay, wait_fixed, retry_if_result, before_sleep_log

# Useless container classes that appear in STF flat XML — skip as selectors,
# use ratio fallback instead (same logic as frontend CONTAINER_CLASSES).
_CONTAINER_CLASSES: frozenset[str] = frozenset({
    "android.widget.FrameLayout",
    "android.widget.LinearLayout",
    "android.widget.RelativeLayout",
    "android.view.View",
    "android.view.ViewGroup",
    "androidx.constraintlayout.widget.ConstraintLayout",
    "android.widget.ScrollView",
    "androidx.recyclerview.widget.RecyclerView",
    "android.widget.ListView",
    "android.widget.GridView",
})

# Shared executor for hierarchy_xml timeout guard (reused across calls).
_HASH_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="hash_xml")

from runtime.core import DeviceClient
from common.variable_resolver import VariableContext
from core.env import capture_pre_step_enabled
from services.extraction_usecase import (
    persist_data_items,
    resolve_comment_parent_hash,
)
from services.scenario_step_contract import (
    extract_data_var_for_strategy,
    normalize_extract_step,
    normalize_save_extraction_step,
)

# Re-export helpers from tasks.scenario.utils for backward compatibility.
# External callers (temporal/activities.py) import these from scenario_task —
# keep them importable here without duplicating logic.
from tasks.scenario.utils import (  # noqa: F401
    _CONTAINER_CLASSES,
    _HASH_EXECUTOR,
    _POPUP_DISMISS_PATTERNS,
    _normalize_xml,
    _hash_hierarchy,
    _xml_has_element,
    _wait_for_element,
    _retry_find_element,
    _IW_DEFAULT_TIMEOUT,
    _IW_DEFAULT_POLL,
    _IW_MAX_TIMEOUT,
    _get_implicit_wait_config,
    _decode_element_image,
    _wait_element_gone,
    _wait_ui_change,
    _wait_screen_stable,
    _auto_dismiss_popup,
    _tap_best_in_bounds,
    _make_bounds,
    _execute_tap,
    _evaluate_condition,
    _eval_ru_condition,
    _capture_step_screenshot,
    ScenarioCancelled,
)


log = logging.getLogger(__name__)


def _run_async_coro_sync(coro: Any, timeout: float = 120.0) -> Any:
    """Run async coroutine from sync code with minimal overhead.

    Fast path: when no running loop exists in this thread, use asyncio.run directly.
    Fallback: if already inside an event loop, offload to a dedicated thread.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        from db.database import run_activity_coro
        return run_activity_coro(coro)

    from db.database import run_activity_coro
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = pool.submit(run_activity_coro, coro)
    try:
        return fut.result(timeout=timeout)
    finally:
        # Timeout must not block the caller by waiting for running future.
        pool.shutdown(wait=False, cancel_futures=True)


class StepBase(TypedDict):
    type: str


class LaunchAppStep(StepBase):
    type: Literal["launch_app"]
    package: str


class OpenUrlStep(StepBase):
    type: Literal["open_url"]
    url: str


class WaitStep(StepBase):
    type: Literal["wait"]
    seconds: float


class TapRatioStep(StepBase):
    type: Literal["tap_ratio"]
    x: float  # 0..1
    y: float  # 0..1


class TapPositionStep(StepBase):
    type: Literal["tap_position"]
    pos: Literal["top_center", "middle_center", "bottom_center", "search_bar"]


class InputTextStep(StepBase):
    type: Literal["input_text"]
    text: str
    via: Literal["u2", "a11y_key"]


class KeyStep(StepBase):
    type: Literal["key"]
    key: str


class ScrollDownStep(StepBase):
    type: Literal["scroll_down"]
    repeats: int
    start_x_ratio: float = 0.5
    start_y_ratio: float = 0.65
    end_y_ratio: float = 0.47
    duration_ms: int = 520
    pause_seconds: float = 0.6


class SwipeRatioStep(StepBase):
    type: Literal["swipe_ratio"]
    x1: float
    y1: float
    x2: float
    y2: float
    duration_ms: int = 300


class TapSelectorStep(StepBase):
    """Tap by uiautomator2 selector (resource-id, text, xpath)."""
    type: Literal["tap_selector"]
    by: str   # "resource-id" | "text" | "xpath" | "class name"
    value: str


class WaitElementStep(StepBase):
    """Wait until element appears (smart wait — replaces fixed wait + blind tap)."""
    type: Literal["wait_element"]
    by: str    # "resource-id" | "text" | "xpath" | "class name"
    value: str
    timeout: float  # seconds to wait (default 10)


class AssertElementStep(StepBase):
    """Assert element exists. Fail scenario early if screen is wrong."""
    type: Literal["assert_element"]
    by: str
    value: str
    timeout: float  # default 5


class InputSelectorStep(StepBase):
    """Find input field by selector, clear it, then type text."""
    type: Literal["input_selector"]
    by: str
    value: str
    text: str
    clear_first: bool  # default True


class LongTapSelectorStep(StepBase):
    """Long-press element found by selector."""
    type: Literal["long_tap_selector"]
    by: str
    value: str
    duration_ms: int  # default 800


class ScrollToStep(StepBase):
    """Swipe-scroll until element is visible (max N swipes)."""
    type: Literal["scroll_to"]
    by: str
    value: str
    direction: str   # "down" | "up"  (default "down")
    max_swipes: int  # default 5


# ── DF-002 control flow step types ────────────────────────────────────────────

class RepeatStep(StepBase):
    """Loop sub-steps N times with optional delay between iterations."""
    type: Literal["repeat"]
    count: int
    steps: List[Dict[str, Any]]
    delay_between: float  # seconds between iterations (default 0)


class RepeatUntilStep(StepBase):
    """Loop sub-steps until condition is met (max_iterations safety cap)."""
    type: Literal["repeat_until"]
    condition: Dict[str, Any]
    steps: List[Dict[str, Any]]
    max_iterations: int  # default 100


class IfElementStep(StepBase):
    """Branch on element existence: run then-steps if found, else-steps if not."""
    type: Literal["if_element"]
    by: str
    value: str
    then: List[Dict[str, Any]]
    timeout: float  # seconds to wait for element (default 3)


class IfVariableStep(StepBase):
    """Branch based on variable value comparison."""
    type: Literal["if_variable"]
    name: str
    then: List[Dict[str, Any]]
    # optional comparison ops: equals, not_equals, contains, greater_than
    # optional else: list of steps when condition is False


class RandomPickStep(StepBase):
    """Randomly execute one branch from a weighted list."""
    type: Literal["random_pick"]
    branches: List[Dict[str, Any]]  # each: {weight?: int, steps: list}


# ── DF-003 flow composition step type ─────────────────────────────────────────

class RunScenarioStep(StepBase):
    """
    Execute a sub-scenario by ID or name.

    Resolution order:
      1. scenario_id  → direct lookup in _scenario_registry["by_id"]
      2. scenario_name → lookup in _scenario_registry["by_campaign_name"]
      3. scenario_name → lookup in _scenario_registry["by_template_name"]
    """
    type: Literal["run_scenario"]
    # exactly one of the two lookup keys is required at runtime
    scenario_id: Optional[str]
    scenario_name: Optional[str]
    variables: Dict[str, Any]   # override vars injected into child scope


ScenarioStep = (
    LaunchAppStep
    | OpenUrlStep
    | WaitStep
    | TapRatioStep
    | TapPositionStep
    | SwipeRatioStep
    | TapSelectorStep
    | WaitElementStep
    | AssertElementStep
    | InputSelectorStep
    | LongTapSelectorStep
    | ScrollToStep
    | InputTextStep
    | KeyStep
    | ScrollDownStep
    | RepeatStep
    | RepeatUntilStep
    | IfElementStep
    | IfVariableStep
    | RandomPickStep
    | RunScenarioStep
)


# ── Popup auto-dismiss patterns ───────────────────────────────────────────────
# Ordered: try most specific first. Each entry: (by, value, tap_or_dismiss)
# "dismiss" = just tap the element. Patterns cover Vietnamese + English apps.
_POPUP_DISMISS_PATTERNS: Sequence[Tuple[str, str]] = (
    # Android system permission dialogs (resource-id exact match = fast)
    ("resource-id", "com.android.permissioncontroller:id/permission_allow_button"),
    ("resource-id", "com.android.packageinstaller:id/permission_allow_button"),
    ("resource-id", "android:id/button1"),          # generic AlertDialog positive
    # Common text buttons (Vietnamese + English)
    ("text", "ALLOW"),   ("text", "Allow"),   ("text", "Allow all"),
    ("text", "Allow only while using the app"),
    ("text", "Cho phép"), ("text", "Đồng ý"), ("text", "OK"), ("text", "Xác nhận"),
    ("text", "Bỏ qua"), ("text", "Skip"),    ("text", "Not now"), ("text", "Later"),
    ("text", "No thanks"), ("text", "Không, cảm ơn"),
    ("text", "Dismiss"),  ("text", "Close"),  ("text", "Got it"),  ("text", "Understood"),
    ("text", "Continue"), ("text", "Tiếp tục"),
    # Close buttons by content-desc (accessibility label)
    ("content-desc", "Close"), ("content-desc", "Dismiss"), ("content-desc", "Đóng"),
)


# ── Smart-wait helpers ────────────────────────────────────────────────────────

_VOLATILE_ATTRS = re.compile(
    r'\s+(?:index|bounds|focused|selected|drawing-order|rotation)="[^"]*"'
)

def _normalize_xml(xml: str) -> str:
    """Strip volatile attributes so hash is stable across dumps."""
    return _VOLATILE_ATTRS.sub("", xml)


def _hash_hierarchy(device: "DeviceClient") -> Optional[int]:
    """Get current UI hierarchy hash (normalized). Uses cache (force_refresh=False)
    so repeated calls within the cache TTL don't trigger extra network round-trips.
    1.5s timeout guard prevents blocking the caller on a slow device."""
    try:
        # force_refresh=False: reuse cached XML — prevents N redundant dumps during
        # _wait_screen_stable / _wait_ui_change poll loops.
        fut = _HASH_EXECUTOR.submit(device.hierarchy_xml, False)
        try:
            xml = fut.result(timeout=1.5)
        except concurrent.futures.TimeoutError:
            fut.cancel()
            return None
        if not xml:
            return None
        norm = _normalize_xml(xml)
        h = 0x811c9dc5
        for ch in norm.encode():
            h ^= ch
            h = (h * 0x01000193) & 0xFFFFFFFF
        return h
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Tenacity-based retry-until-visible
# ---------------------------------------------------------------------------
# Wraps element lookup with automatic retries.  Used by _execute_tap,
# input_selector, long_tap_selector, etc. so that the script tolerates
# dynamic loading / slow app transitions without manual wait_element steps.
#
# Default: poll every 500 ms, give up after 10 s (configurable per step
# via ``implicit_wait`` or at scenario level via ``implicit_wait``).
# ---------------------------------------------------------------------------

def _retry_find_element(
    u2,
    by: str,
    value: str,
    timeout: float = 10.0,
    poll: float = 0.5,
) -> Optional[Any]:
    """
    Find element with Tenacity retry.  Returns element id/dict or None.

    Unlike _wait_for_element (which uses server-side waitForExists for
    non-xpath), this function retries the *entire* find_element call,
    handling transient u2 errors (connection hiccups, hierarchy not ready).
    """
    if u2 is None:
        return None

    @retry(
        stop=stop_after_delay(timeout),
        wait=wait_fixed(poll),
        retry=retry_if_result(lambda r: r is None),
        before_sleep=before_sleep_log(log, logging.DEBUG),
        reraise=False,
    )
    def _find():
        try:
            # Quick server-side check (timeout=0.5s per attempt)
            eid = u2.find_element(by, value, timeout=min(0.5, poll))
            if eid is None:
                return None   # triggers retry
            # Try to get bounds for accurate tap targeting
            if hasattr(u2, "find_element_with_bounds"):
                try:
                    result = u2.find_element_with_bounds(by, value)
                    if result:
                        return result
                except Exception:
                    pass
            return eid
        except Exception as exc:
            log.debug("_retry_find_element %s=%r attempt error: %s", by, value, exc)
            return None  # triggers retry

    try:
        return _find()
    except Exception:
        # Tenacity exhausted all retries — element not found
        return None


_IW_DEFAULT_TIMEOUT = 3.0
_IW_DEFAULT_POLL = 0.25
_IW_MAX_TIMEOUT = 60.0


def _get_implicit_wait_config(
    step: Dict[str, Any],
    scenario_config: Dict[str, Any],
) -> Tuple[float, float]:
    """
    Resolve implicit_wait timeout and poll interval.

    Priority: step.implicit_wait > scenario.implicit_wait > defaults (3s / 0.25s).
    Accepts either a number (timeout only) or a dict {timeout, poll}.
    Clamps timeout to [0.1, 60] to prevent runaway waits.
    """
    for source in (step, scenario_config):
        iw = source.get("implicit_wait")
        if iw is not None:
            if isinstance(iw, (int, float)):
                t = min(max(0.1, float(iw)), _IW_MAX_TIMEOUT)
                return t, _IW_DEFAULT_POLL
            if isinstance(iw, dict):
                t = min(max(0.1, float(iw.get("timeout", _IW_DEFAULT_TIMEOUT))), _IW_MAX_TIMEOUT)
                p = max(0.1, float(iw.get("poll", _IW_DEFAULT_POLL)))
                return t, p
    return _IW_DEFAULT_TIMEOUT, _IW_DEFAULT_POLL


def _decode_element_image(b64_or_none: Optional[str]) -> Optional[bytes]:
    """Decode base64 element image for visual anchoring. Returns None on failure."""
    if not b64_or_none:
        return None
    try:
        from runtime.visual_anchor import _b64_to_bytes
        return _b64_to_bytes(b64_or_none)
    except Exception as exc:
        log.warning("Failed to decode element_image: %s", exc)
        return None


def _wait_element_gone(
    u2,
    by: str,
    value: str,
    timeout: float = 8.0,
    poll: float = 0.3,
) -> bool:
    """Wait until element disappears. Uses native waitUntilGone when available."""
    if u2 is None:
        return True
    # Use native waitUntilGone (server-side blocking, single call)
    if hasattr(u2, "_wait_until_gone"):
        try:
            return u2._wait_until_gone(by, value, timeout)
        except Exception:
            pass
    # Fallback: poll with timeout=0 (instant check per iteration)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            eid = u2.find_element(by, value, timeout=0)
            if eid is None:
                return True
        except Exception:
            return True  # error = not found
        time.sleep(poll)
    return False


def _wait_ui_change(
    device: "DeviceClient",
    old_hash: Optional[int],
    timeout: float = 3.0,
    poll: float = 0.3,
) -> bool:
    """Poll until hierarchy hash changes. Returns True if changed, False on timeout.
    Default timeout reduced to 3s — ratio-only taps often don't trigger detectable XML changes."""
    if old_hash is None:
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(poll)
        new_hash = _hash_hierarchy(device)
        if new_hash is not None and new_hash != old_hash:
            return True
    return False


def _wait_screen_stable(
    device: "DeviceClient",
    timeout: float = 3.0,
    stable_duration: float = 0.25,
    poll: float = 0.3,
) -> bool:
    """
    Wait until the UI hierarchy hash stops changing for `stable_duration` seconds.

    Typical use: call right before a tap/swipe so we don't act mid-animation.
    Returns True when stable, False when timeout reached (action should still proceed).

    Why: the #1 cause of campaign failures is tapping while screen is still
    transitioning — the touch lands on the wrong element or is lost entirely.
    """
    deadline = time.monotonic() + timeout
    last_hash: Optional[int] = None
    stable_since: Optional[float] = None

    while time.monotonic() < deadline:
        h = _hash_hierarchy(device)
        now = time.monotonic()
        if h is None:
            # Can't get hierarchy — don't block, proceed
            return False
        if h == last_hash:
            if stable_since is None:
                stable_since = now
            elif (now - stable_since) >= stable_duration:
                return True  # UI has been stable for long enough
        else:
            last_hash = h
            stable_since = None
        time.sleep(poll)

    return False  # timed out — proceed anyway


def _auto_dismiss_popup(device: "DeviceClient") -> bool:
    """
    Check for common popup/dialog patterns and dismiss the first one found.

    Runs a fast non-blocking scan: tries each pattern with a very short timeout.
    Returns True if a popup was dismissed, False if nothing found.

    Why: unexpected permission dialogs, update prompts, and ad overlays are the
    #2 cause of campaign failures — they appear at random, block the UI, and
    cause all subsequent selectors to fail silently.
    """
    u2 = device.u2
    if u2 is None:
        return False

    # Dump XML once (uses cache) — search all patterns in one pass, avoid 20 HTTP calls.
    xml = device.hierarchy_xml(force_refresh=False)
    if not xml:
        return False
    try:
        import xml.etree.ElementTree as _ET
        root = _ET.fromstring(xml)
    except Exception:
        return False

    for by, value in _POPUP_DISMISS_PATTERNS:
        try:
            if by == "text":
                nodes = root.findall(f'.//*[@text="{value}"]')
            elif by == "resource-id":
                nodes = root.findall(f'.//*[@resource-id="{value}"]')
            elif by in ("content-desc", "accessibility id"):
                nodes = root.findall(f'.//*[@content-desc="{value}"]')
            else:
                nodes = []
            if not nodes:
                continue
            # Pattern found in XML — now click it (single objInfo call, timeout=0)
            eid = u2.find_element(by, value, timeout=0)
            if eid is not None:
                u2.element_click(eid)
                log.info(f"[{device.serial}] popup dismissed: {by}={value!r}")
                time.sleep(0.3)
                return True
        except Exception:
            pass
    return False


def _tap_best_in_bounds(
    device: "DeviceClient",
    bounds: Dict[str, int],
    hint_rx: Optional[float] = None,
    hint_ry: Optional[float] = None,
    margin: int = 5,
) -> None:
    """
    Tap the best position inside element bounds.

    Priority:
      1. Recorded position (hint_rx/ry) if it falls inside the element bounds —
         reproduces the exact tap the user made during recording.
      2. Center of bounds — deterministic, works for any element.

    The old random-in-bounds approach caused "wrong position" complaints because
    tapping a random spot in a large element (e.g., list row, full-width card)
    landed far from the user's originally recorded tap point.
    """
    w = device.screen_width or 1080
    h = device.screen_height or 1920
    left   = bounds.get("left", 0)
    top    = bounds.get("top", 0)
    right  = bounds.get("right", w)
    bottom = bounds.get("bottom", h)

    # Use the recorded position if it's inside the element bounds.
    if hint_rx is not None and hint_ry is not None:
        hx = int(hint_rx * w)
        hy = int(hint_ry * h)
        if left <= hx <= right and top <= hy <= bottom:
            device.tap(hx, hy)
            return

    # Fallback: center of element.
    cx = (left + right) // 2
    cy = (top + bottom) // 2
    # Clamp to valid screen area.
    cx = max(margin, min(cx, w - margin))
    cy = max(margin, min(cy, h - margin))
    device.tap(cx, cy)


def _make_bounds(cx: int, cy: int, pad: int, w: int, h: int) -> Dict[str, int]:
    """Create a bounds dict centered on (cx, cy) with padding."""
    return {
        "left": max(0, cx - pad), "top": max(0, cy - pad),
        "right": min(w, cx + pad), "bottom": min(h, cy + pad),
    }


def _execute_tap(
    device: "DeviceClient",
    by: Optional[str],
    value: Optional[str],
    fallback_rx: Optional[float],
    fallback_ry: Optional[float],
    timeout: float = 4.0,
    retries: int = 2,
    implicit_wait_timeout: float = _IW_DEFAULT_TIMEOUT,
    implicit_wait_poll: float = _IW_DEFAULT_POLL,
    element_image: Optional[bytes] = None,
    image_threshold: float = 0.7,
    screenshot_anchor: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str, Optional[Dict[str, int]]]:
    """
    Full tap pipeline: selector → image match (ROI→full) → position fallback.

    Uses ElementResolver for phased resolution. Each phase is a pure "find"
    returning coordinates; the actual device.tap() happens here after resolution.

    Returns (ok, message, bounds_or_none).
    """
    from runtime.element_resolver import (
        ElementResolver, phase_selector, phase_image, phase_ratio, phase_healing,
    )

    serial = device.serial
    w = device.screen_width or 1080
    h = device.screen_height or 1920
    u2 = device.u2

    # Skip useless container class selectors
    effective_by = by
    effective_value = value
    if by == "class name" and value in _CONTAINER_CLASSES:
        log.debug(f"[{serial}] selector class={value!r} is container — skip to fallback")
        effective_by = None
        effective_value = None

    # Build ordered resolution phases
    phases = []

    # Phase 1: Selector
    has_selector = bool(u2 and effective_by and effective_value)
    if has_selector:
        phases.append(lambda: phase_selector(
            u2, effective_by, effective_value,
            fallback_rx, fallback_ry,
            implicit_wait_timeout, implicit_wait_poll,
            w, h,
            find_fn=_retry_find_element,
        ))

    # Phase 1.5: Self-healing (alternative selector when primary fails)
    if has_selector and fallback_rx is not None and fallback_ry is not None:
        phases.append(lambda: phase_healing(
            u2, device, effective_by, effective_value,
            fallback_rx, fallback_ry, w, h,
            implicit_wait_timeout=3.0,
        ))

    # Phase 2: Image match (ROI-optimized if screenshot_anchor available)
    if element_image is not None:
        phases.append(lambda: phase_image(
            device, element_image, image_threshold, w, h,
            screenshot_anchor=screenshot_anchor,
        ))

    # Phase 3: Ratio fallback
    if fallback_rx is not None and fallback_ry is not None:
        phases.append(lambda: phase_ratio(
            device, fallback_rx, fallback_ry, w, h,
            selector_tried=has_selector,
        ))

    resolver = ElementResolver(phases=phases)
    result = resolver.resolve()

    if not result.hit:
        return False, f"selector {by}={value!r} not found, no fallback position", None

    # Execute the tap
    if result.x == -1 and result.y == -1:
        # Special case: element_click (no bounds available from selector)
        try:
            eid_result = _retry_find_element(u2, effective_by, effective_value, timeout=1.0, poll=0.3)
            if eid_result is not None:
                eid = eid_result.get("eid", f"{effective_by}::{effective_value}") if isinstance(eid_result, dict) else eid_result
                u2.element_click(eid)
            else:
                return False, f"selector {by}={value!r} lost before click", None
        except Exception as exc:
            return False, f"element_click failed: {exc}", None
    else:
        try:
            device.tap(result.x, result.y)
        except Exception as exc:
            return False, f"tap ({result.x},{result.y}) failed: {exc}", None

    # For ratio fallback, add the brief wait that was in the original
    if result.method == "fallback_position":
        time.sleep(0.3)

    return True, result.message, result.bounds


def _evaluate_condition(device: "DeviceClient", condition: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    """Evaluate a condition dict for if/loop steps."""
    ctype = str(condition.get("type", ""))

    if ctype == "element_exists":
        by = str(condition.get("by", "text"))
        value = str(condition.get("value", ""))
        if not value:
            return False
        xml = device.hierarchy_xml(force_refresh=False)
        if not xml:
            return False
        import xml.etree.ElementTree as ET
        try:
            root = ET.fromstring(xml)
            for node in root.iter():
                t = (node.get("text") or node.get("content-desc") or "").strip()
                rid = (node.get("resource-id") or "").strip()
                if by in ("text",) and t == value:
                    return True
                if by in ("resource-id",) and rid == value:
                    return True
                if by == "xpath":
                    # Simple xpath: check if any node matches text contains
                    pass
            return False
        except Exception:
            return False

    elif ctype == "element_not_exists":
        return not _evaluate_condition(device, {**condition, "type": "element_exists"}, ctx)

    elif ctype == "posts_count_gte":
        count = int(condition.get("count", 0))
        return len(ctx.get("posts", [])) >= count

    elif ctype == "posts_count_lt":
        count = int(condition.get("count", 0))
        return len(ctx.get("posts", [])) < count

    elif ctype == "no_new_posts":
        # True if no_new_streak >= threshold
        threshold = int(condition.get("threshold", 3))
        posts_streak = int(ctx.get("_no_new_posts_streak", 0) or 0)
        legacy_streak = int(ctx.get("_no_new_streak", 0) or 0)
        return max(posts_streak, legacy_streak) >= threshold

    return False


def _capture_step_screenshot(
    device: "DeviceClient",
    capture_dir: str,
    idx: int,
    step_type: str,
    bounds: Optional[Dict[str, int]],
    screen_w: int,
    screen_h: int,
    selector: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Save full-screen screenshot + XML hierarchy + selector info (no element crops)."""
    from services import capture_store

    jpeg = device.take_screenshot()
    if not jpeg:
        return {}

    prefix = f"step_{idx:03d}_{step_type}"
    # MinIO key mirrors local dir structure: captures/{session}/step_XXX_*.ext
    session_name = os.path.basename(capture_dir)
    minio_prefix = f"captures/{session_name}"

    # Full screenshot — skip quality gate (step captures are intentional, not minicap stream)
    full_local = os.path.join(capture_dir, f"{prefix}_full.jpg")
    full_key = f"{minio_prefix}/{prefix}_full.jpg"
    full_url = capture_store.save_capture(jpeg, full_local, full_key, "image/jpeg", skip_quality=True)
    if not full_url:
        return {}
    result: Dict[str, Any] = {"full": full_url}

    # XML hierarchy
    try:
        xml = device.hierarchy_xml(force_refresh=False)
        if xml:
            xml_local = os.path.join(capture_dir, f"{prefix}_hierarchy.xml")
            xml_key = f"{minio_prefix}/{prefix}_hierarchy.xml"
            xml_url = capture_store.save_capture(
                xml.encode("utf-8"), xml_local, xml_key, "application/xml",
            )
            if xml_url:
                result["hierarchy"] = xml_url
    except Exception:
        pass

    # Selector info
    if selector:
        sel_local = os.path.join(capture_dir, f"{prefix}_selector.json")
        sel_key = f"{minio_prefix}/{prefix}_selector.json"
        sel_bytes = json.dumps(selector, ensure_ascii=False, indent=2).encode("utf-8")
        sel_url = capture_store.save_capture(sel_bytes, sel_local, sel_key, "application/json")
        if sel_url:
            result["selector"] = sel_url

    if bounds:
        result["bounds"] = [bounds["left"], bounds["top"], bounds["right"], bounds["bottom"]]

    return result
def _xml_has_element(xml: str, by: str, value: str) -> bool:
    """
    Check if the XML hierarchy contains an element matching (by, value).

    Uses findall with attribute predicates for text/resource-id/content-desc —
    faster than iterating every node. Falls back to iteration for other selectors.
    Called in hot loops (repeat_until), so avoids re-parsing on every call.
    """
    if not xml or not value:
        return False
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml)
        if by == "text":
            return bool(root.findall(f'.//*[@text="{value}"]'))
        if by == "resource-id":
            return bool(root.findall(f'.//*[@resource-id="{value}"]'))
        if by in ("content-desc", "accessibility id"):
            return bool(root.findall(f'.//*[@content-desc="{value}"]'))
        if by == "class name":
            return bool(root.findall(f'.//*[@class="{value}"]'))
        for node in root.iter():
            if node.get("text") == value or node.get("resource-id") == value:
                return True
        return False
    except Exception:
        return False


def _eval_ru_condition(
    device: "DeviceClient",
    condition: Dict[str, Any],
    var_ctx: VariableContext,
) -> bool:
    """
    Evaluate a repeat_until stop condition (DF-002 format).

    Returns True when the loop SHOULD STOP (condition satisfied).

    Supported keys:
      element_exists:     {"by": ..., "value": ...}  — stop when element appears
      element_not_exists: {"by": ..., "value": ...}  — stop when element disappears
      variable_equals:    {"name": ..., "value": ...} — stop when variable matches

    Uses force_refresh=True so each iteration gets a fresh hierarchy dump, not
    cached state from the previous step.
    """
    if "element_exists" in condition:
        spec = condition["element_exists"]
        by = str(spec.get("by", "text"))
        value = str(var_ctx.resolve(spec.get("value", ""), step_index=0))
        xml = device.hierarchy_xml(force_refresh=True) or ""
        return _xml_has_element(xml, by, value)

    if "element_not_exists" in condition:
        spec = condition["element_not_exists"]
        by = str(spec.get("by", "text"))
        value = str(var_ctx.resolve(spec.get("value", ""), step_index=0))
        xml = device.hierarchy_xml(force_refresh=True) or ""
        return not _xml_has_element(xml, by, value)

    if "variable_equals" in condition:
        spec = condition["variable_equals"]
        name = str(spec.get("name", ""))
        if not name:
            return False
        # Resolve templated expected value, e.g. "${MAX_POSTS}".
        expected = str(var_ctx.resolve(spec.get("value", ""), step_index=0))
        actual = str(var_ctx.resolve(f"${{{name}}}", step_index=0))
        return actual == expected

    log.warning("repeat_until: unknown condition keys: %r", list(condition.keys()))
    return False


class ScenarioCancelled(Exception):
    """Raised when scenario is cancelled via cancel_event."""
    pass


def _try_publish_status(device: "DeviceClient") -> None:
    """Best-effort: push a status update so frontend sees scenario_active change."""
    try:
        fn = getattr(device, "_publish_status", None)
        if fn is not None:
            fn()
    except Exception:
        pass


def force_clear_scenario_busy(device: "DeviceClient") -> None:
    """Reset scenario-active gates immediately (preview cancel / interrupt).

    The scenario thread may still be winding down on a long step; clearing the
    counter and publishing status lets manual control resume without waiting.
    """
    lock = getattr(device, "_scenario_active_lock", None)
    if lock is not None:
        with lock:
            device._scenario_active = 0
    else:
        device._scenario_active = 0
    _try_publish_status(device)
    _try_publish_scenario_active_redis(device)


def _try_publish_scenario_active_redis(device: "DeviceClient") -> None:
    """Best-effort: publish scenario_active to Redis for cross-process WS/API gates.

    This is needed when Temporal activities run in a separate worker process:
    in-memory ``device._scenario_active`` is process-local, so the web process
    must consult Redis to know the device is still under automation.
    """
    try:
        from services import redis_store

        if not redis_store.enabled():
            return
        r = redis_store.client()
        if r is None:
            return
        serial = getattr(device, "serial", "")
        if not serial:
            return
        n = int(getattr(device, "_scenario_active", 0) or 0)
        key = redis_store.key(f"device:{serial}:scenario_active")
        loop = getattr(device, "_loop", None)
        if loop is None:
            return

        async def _set() -> None:
            if n > 0:
                # TTL prevents stale locks if the worker crashes mid-run.
                await r.setex(key, 300, str(n))
            else:
                await r.delete(key)

        import asyncio as _aio

        _aio.run_coroutine_threadsafe(_set(), loop)
    except Exception:
        pass


def run_scenario_task(
    device: "DeviceClient",
    scenario: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
    on_step_done: Optional[Callable[[Dict[str, Any]], None]] = None,
    _var_ctx: Optional[VariableContext] = None,
    _depth: int = 0,
    _call_stack: frozenset[str] = frozenset(),
    cancel_event: Optional["threading.Event"] = None,
) -> Dict[str, Any]:
    """
    Thực thi 1 scenario JSON trên 1 device.

    Đây là lớp "thực thi" thuần deterministic. AI/MCP chỉ cần sinh ra `scenario`
    đúng schema; mọi thao tác cụ thể đều do code này handle.

    cancel_event: threading.Event — nếu set(), scenario dừng graceful ở step tiếp theo.
    """
    from tasks.scenario.context import ScenarioContext
    from tasks.scenario.executor import ScenarioExecutor

    serial = device.serial
    trace_id = str(scenario.get("_trace_id") or "-")
    trace_source = str(scenario.get("_trace_source") or "scenario_task")
    log.info(
        "[SCENARIO][trace=%s][serial=%s][source=%s] DISPATCH steps=%s",
        trace_id,
        serial,
        trace_source,
        len(scenario.get("steps", []) or []),
    )

    sc = ScenarioContext.from_args(
        device, scenario,
        context=context, on_step_done=on_step_done,
        _var_ctx=_var_ctx, _depth=_depth, _call_stack=_call_stack,
        cancel_event=cancel_event,
    )
    # Mark the device "scenario-active" so the frontend WS gate drops manual
    # touch/swipe frames that would otherwise interleave with the script.
    # Ref-counted (nested scenarios stack). The increment/decrement is NOT
    # atomic in CPython (LOAD/ADD/STORE happens across bytecodes) so we
    # serialize via a per-device threading.Lock created on first use.
    _mark = _depth == 0
    if _mark:
        lock = getattr(device, "_scenario_active_lock", None)
        if lock is None:
            import threading as _th
            lock = _th.Lock()
            # Best-effort install; if another thread raced us, keep theirs.
            if not hasattr(device, "_scenario_active_lock"):
                device._scenario_active_lock = lock
            lock = device._scenario_active_lock
        with lock:
            device._scenario_active = int(getattr(device, "_scenario_active", 0)) + 1
        _try_publish_status(device)
        _try_publish_scenario_active_redis(device)
    try:
        return ScenarioExecutor(sc).run()
    finally:
        if _mark:
            lock = getattr(device, "_scenario_active_lock", None)
            if lock is not None:
                with lock:
                    n = int(getattr(device, "_scenario_active", 1)) - 1
                    device._scenario_active = max(0, n)
            else:
                # Lock disappeared somehow — best-effort reset
                device._scenario_active = 0
            _try_publish_status(device)
            _try_publish_scenario_active_redis(device)


def _run_scenario_task_legacy(
    device: "DeviceClient",
    scenario: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
    on_step_done: Optional[Callable[[Dict[str, Any]], None]] = None,
    _var_ctx: Optional[VariableContext] = None,
    _depth: int = 0,
    _call_stack: frozenset[str] = frozenset(),
    cancel_event: Optional["threading.Event"] = None,
) -> Dict[str, Any]:
    """Legacy monolith implementation — kept for reference, not called."""
    serial = device.serial
    steps: List[ScenarioStep] = scenario.get("steps", []) or []  # type: ignore[assignment]
    log.info(f"[{serial}] run_scenario_task: {len(steps)} steps")

    ctx = context if context is not None else {}
    ctx.setdefault("posts", [])
    ctx.setdefault("vars", {})

    _MAX_NESTING_DEPTH = 10
    if _depth > _MAX_NESTING_DEPTH:
        log.warning(f"[{serial}] run_scenario_task: max nesting depth {_MAX_NESTING_DEPTH} exceeded")
        return {
            "serial": serial,
            "success": False,
            "steps_executed": 0,
            "step_results": [{"type": "error", "ok": False, "message": f"Max nesting depth {_MAX_NESTING_DEPTH} exceeded"}],
            "failed_message": f"Max nesting depth {_MAX_NESTING_DEPTH} exceeded",
            "context": context or {},
        }

    # Khởi tạo VariableContext nếu chưa có (chỉ tạo 1 lần ở root call,
    # các lệnh loop/if lồng nhau nhận _var_ctx từ caller để runtime vars persist).
    if _var_ctx is None:
        _var_ctx = VariableContext(
            scenario_vars=scenario.get("variables", {}),
            campaign_vars=scenario.get("_campaign_vars", {}),
            device_serial=device.serial,
            device_model=getattr(device, "model", ""),
        )

    w = device.screen_width or 1080
    h = device.screen_height or 1920

    # ── Implicit wait config (Tenacity retry-until-visible) ──────────
    # Scenario-level default: { "implicit_wait": 10 } or { "implicit_wait": { "timeout": 10, "poll": 0.5 } }
    # Step-level override: each step can set its own "implicit_wait".
    _scenario_iw_config: Dict[str, Any] = {}
    _raw_iw = scenario.get("implicit_wait")
    if _raw_iw is not None:
        if isinstance(_raw_iw, (int, float)):
            _scenario_iw_config["implicit_wait"] = _raw_iw
        elif isinstance(_raw_iw, dict):
            _scenario_iw_config["implicit_wait"] = _raw_iw

    # ── Visual Anchoring config ─────────────────────────────────────
    _va_raw = scenario.get("visual_anchor")
    _va_ssim_threshold = 0.65  # lenient: status bar (time/battery) changes ~5-10% of pixels
    _va_image_threshold = 0.7
    _va_screen_timeout = 3.0   # only used when no selector — short timeout avoids blocking
    _va_screen_poll = 0.5

    if isinstance(_va_raw, bool):
        _visual_anchor_enabled = _va_raw
    elif isinstance(_va_raw, dict):
        _visual_anchor_enabled = bool(_va_raw.get("enabled", True))
        _va_ssim_threshold = max(0.0, min(1.0, float(_va_raw.get("ssim_threshold", 0.75))))
        _va_image_threshold = max(0.0, min(1.0, float(_va_raw.get("image_threshold", 0.7))))
        _va_screen_timeout = min(float(_va_raw.get("screen_timeout", 8.0)), _IW_MAX_TIMEOUT)
        _va_screen_poll = max(0.1, float(_va_raw.get("screen_poll", 0.5)))
    else:
        # Auto-enable if any step has visual anchor data
        _visual_anchor_enabled = any(
            (s.get("screen") or {}).get("screenshot") or (s.get("screen") or {}).get("element_image")
            for s in steps if isinstance(s, dict)
        )

    if _visual_anchor_enabled:
        log.info(f"[{serial}] Visual Anchoring ON (SSIM≥{_va_ssim_threshold}, image≥{_va_image_threshold})")

    # Step screenshot capture (debug mode)
    capture_enabled = (
        scenario.get("capture_steps", False)
        or os.environ.get("CAPTURE_STEPS", "").lower() in {"1", "true", "yes"}
        or os.environ.get("DEBUG_AUTO", "").lower() in {"1", "true", "yes"}
    )
    capture_dir: Optional[str] = None
    capture_pre_step = capture_pre_step_enabled()
    _capture_settle_ms: int = int(scenario.get("settle_timeout_ms") or os.environ.get("SETTLE_TIMEOUT_MS", "800"))
    _capture_stale_wait_s: float = float(os.environ.get("CAPTURE_STALE_WAIT_MS", "1000")) / 1000.0
    _CAPTURE_SKIP_SETTLE: frozenset[str] = frozenset({
        "wait", "wait_stable", "wait_screen_stable",
        "set_variable", "assert_variable",
        "run_scenario",  # sub-steps handle their own captures
    })
    if capture_enabled:
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        base = os.path.join(os.path.dirname(os.path.dirname(__file__)), "captures")
        capture_dir = os.path.join(base, f"{serial}_{ts}")
        os.makedirs(capture_dir, exist_ok=True)
        log.info(f"[{serial}] Step capture enabled → {capture_dir} settle={_capture_settle_ms}ms")
        if capture_pre_step:
            log.info(f"[{serial}] Step pre-capture enabled (CAPTURE_PRE_STEP=1)")

    step_results: List[Dict[str, Any]] = []
    # Rate-limit popup checks: at most once every 5 seconds.
    # _auto_dismiss_popup dumps the full XML hierarchy — expensive (0.5-1.5s network call).
    # Popups don't appear on every single tap, so checking every 5s is protective enough.
    _last_popup_t: float = 0.0

    for idx, raw_step in enumerate(steps):
        # ── Cancellation checkpoint ──────────────────────────────────────
        if cancel_event is not None and cancel_event.is_set():
            log.info(f"[{serial}] scenario CANCELLED at step#{idx + 1}")
            step_results.append({"index": idx, "type": "cancelled", "ok": False, "message": "Cancelled by user"})
            return {
                "serial": serial,
                "success": False,
                "steps_executed": idx,
                "step_results": step_results,
                "failed_message": f"Cancelled at step {idx + 1}",
                "context": ctx,
            }

        step: Dict[str, Any] = _var_ctx.resolve(raw_step, step_index=idx)
        t = step.get("type")
        log.info(f"[{serial}] step#{idx + 1}: {t} {step}")
        step_result: Dict[str, Any] = {"index": idx, "type": t, "ok": True}

        if capture_dir and capture_pre_step:
            try:
                pre_cap = _capture_step_screenshot(
                    device,
                    capture_dir,
                    idx,
                    f"{t or 'unknown'}_pre",
                    None,
                    w,
                    h,
                    selector=None,
                )
                if pre_cap:
                    step_result["screenshot_pre"] = pre_cap
                last_frame_t = float(getattr(device, "_last_frame_time", 0.0) or 0.0)
                if last_frame_t > 0:
                    age_ms = int((time.monotonic() - last_frame_t) * 1000)
                    log.info(f"[{serial}] capture PRE step#{idx + 1} ({t}) frame_age={age_ms}ms")
                else:
                    log.info(f"[{serial}] capture PRE step#{idx + 1} ({t}) frame_age=unknown")
            except Exception as exc:
                log.debug(f"[{serial}] pre-step capture failed: {exc}")

        # Record timestamp immediately before the action so POST-capture can
        # detect whether the device has pushed a new frame since action started.
        step_start_t: float = time.monotonic()

        if t == "launch_app":
            app_field = step.get("app")
            app_pkg = ""
            app_component = ""
            if isinstance(app_field, dict):
                app_pkg = str(app_field.get("package") or app_field.get("app_package") or "").strip()
                app_component = str(app_field.get("component") or app_field.get("activity") or "").strip()
            elif isinstance(app_field, str):
                app_pkg = app_field.strip()

            raw_pkg = str(
                step.get("package")
                or step.get("app_package")
                or step.get("appPackage")
                or app_pkg
                or ""
            ).strip()
            raw_component = str(
                step.get("component")
                or step.get("activity")
                or step.get("title")
                or app_component
                or ""
            ).strip()
            pkg = raw_pkg
            component = ""
            
            if pkg and "/" in pkg:
                component = pkg
                pkg = pkg.split("/", 1)[0].strip()
            if raw_component and "/" in raw_component:
                component = raw_component
                if not pkg:
                    pkg = raw_component.split("/", 1)[0].strip()
            elif raw_component and not pkg:
                # Legacy payloads sometimes put package into "title"/"activity" directly.
                pkg = raw_component
            if not pkg:
                msg = "launch_app: empty package/component"
                log.warning(f"[{serial}] {msg}")
                step_result["ok"] = False
                step_result["message"] = msg
            else:
                try:
                    raw_fallbacks = (
                        step.get("package_fallbacks")
                        or step.get("packageFallbacks")
                        or []
                    )
                    if isinstance(raw_fallbacks, str):
                        package_fallbacks = [raw_fallbacks]
                    elif isinstance(raw_fallbacks, (list, tuple, set)):
                        package_fallbacks = [str(value) for value in raw_fallbacks]
                    else:
                        package_fallbacks = []
                    raw_adb_fallback = step.get(
                        "adb_fallback",
                        step.get("adbFallback", True),
                    )
                    adb_fallback = str(raw_adb_fallback).strip().lower() not in {
                        "0",
                        "false",
                        "no",
                        "off",
                    }
                    device.launch_app(
                        pkg,
                        component=component or None,
                        package_fallbacks=package_fallbacks,
                        adb_fallback=adb_fallback,
                    )
                    # Fixed wait — app startup is variable; scenario should include an
                    # explicit wait_element step after launch_app for reliable sync.
                    launch_wait = float(step.get("wait_after", 2.0) or 2.0)
                    time.sleep(launch_wait)
                    log.info(f"[{serial}] launch_app {pkg}: waited {launch_wait}s")
                    # After app launch the u2 tunnel often disconnects briefly while
                    # UIAutomator restarts.  Poll up to 8 s so subsequent steps that
                    # need u2 don't start before it is ready.
                    _u2_poll_start = time.monotonic()
                    while time.monotonic() - _u2_poll_start < 8.0:
                        if getattr(device, "_u2", None) is not None:
                            break
                        time.sleep(0.5)
                    if getattr(device, "_u2", None) is None:
                        log.warning(f"[{serial}] launch_app {pkg}: u2 not ready after 8s poll")
                except Exception as exc:
                    msg = f"launch_app({pkg}) failed: {exc}"
                    log.warning(f"[{serial}] {msg}")
                    step_result["ok"] = False
                    step_result["message"] = msg

        elif t == "open_url":
            url = str(step.get("url") or "").strip()
            if not url:
                msg = "open_url: empty url"
                log.warning(f"[{serial}] {msg}")
                step_result["ok"] = False
                step_result["message"] = msg
            else:
                pkg = (step.get("package") or "").strip() or "com.android.chrome"
                try:
                    device.open_url(url, package=pkg)
                except Exception as exc:
                    msg = f"open_url failed: {exc}"
                    log.warning(f"[{serial}] {msg}")
                    step_result["ok"] = False
                    step_result["message"] = msg

        elif t == "wait":
            try:
                secs = float(step.get("seconds", 0.0) or 0.0)
            except Exception:
                secs = 0.0
            if secs <= 0:
                step_result["ok"] = True
                step_result["message"] = "wait 0s (skipped sleep)"
            else:
                # Interruptible sleep: check cancel_event every 200ms
                deadline = time.monotonic() + secs
                _CHUNK = 0.2
                while time.monotonic() < deadline:
                    if cancel_event is not None and cancel_event.is_set():
                        break
                    time.sleep(min(_CHUNK, max(0.0, deadline - time.monotonic())))

        elif t == "tap":
            # Full pipeline:
            # dismiss_popup? → wait_for_selector → image_match → fallback_position
            selector    = step.get("selector") or {}
            fallback    = step.get("fallback") or {}
            screen_ctx  = step.get("screen") or {}
            sel_by      = str(selector.get("by") or "") or None
            sel_value   = str(selector.get("value") or "").strip() or None
            fallback_rx = fallback.get("rx")
            fallback_ry = fallback.get("ry")
            tap_timeout = float(step.get("timeout", 4.0) or 4.0)
            wait_after  = bool(step.get("wait_after", True))

            # Skip container class selectors upfront — avoid useless pre_hash fetch
            has_real_selector = (
                sel_by and sel_value
                and not (sel_by == "class name" and sel_value in _CONTAINER_CLASSES)
            )

            # ── Visual Anchoring: verify screen state before tapping ──
            # Skip when a reliable selector exists — finding the element already
            # proves we're on the correct screen. SSIM is only useful when we
            # have to rely on recorded coordinates (no selector / fallback-only).
            screen_screenshot_b64 = screen_ctx.get("screenshot")
            if _visual_anchor_enabled and screen_screenshot_b64 and not has_real_selector:
                try:
                    from runtime.visual_anchor import wait_for_screen_match, _b64_to_bytes
                    recorded_jpeg = _b64_to_bytes(screen_screenshot_b64)
                    matched, ssim = wait_for_screen_match(
                        device.take_screenshot, recorded_jpeg,
                        timeout=_va_screen_timeout, poll=_va_screen_poll,
                        ssim_threshold=_va_ssim_threshold,
                    )
                    step_result["screen_ssim"] = round(ssim, 3)
                    if not matched:
                        # Info-level only — SSIM mismatch is non-blocking (execution continues).
                        # Use verify_screen step for intentional hard checks.
                        log.info(f"[{serial}] step#{idx+1} screen SSIM={ssim:.3f} < {_va_ssim_threshold} (proceeding)")
                        step_result["screen_mismatch"] = True
                except ImportError:
                    pass
                except Exception as exc:
                    log.debug(f"[{serial}] screen verify error: {exc}")

            elem_img_bytes = _decode_element_image(screen_ctx.get("element_image"))
            ss_anchor = screen_ctx.get("screenshot_anchor")

            iw_timeout, iw_poll = _get_implicit_wait_config(step, _scenario_iw_config)
            ok, msg, tap_bounds = _execute_tap(
                device,
                by=sel_by,
                value=sel_value,
                fallback_rx=fallback_rx,
                fallback_ry=fallback_ry,
                timeout=tap_timeout,
                retries=1,
                implicit_wait_timeout=iw_timeout,
                implicit_wait_poll=iw_poll,
                element_image=elem_img_bytes,
                image_threshold=_va_image_threshold,
                screenshot_anchor=ss_anchor,
            )

            # Auto-dismiss popup only when tap failed — avoids dismissing the
            # intended target element whose text happens to match a popup pattern.
            if not ok:
                now_t = time.monotonic()
                if now_t - _last_popup_t >= 5.0:
                    dismissed = _auto_dismiss_popup(device)
                    _last_popup_t = time.monotonic()
                    if dismissed:
                        step_result["popup_dismissed"] = True
                        # Retry tap once after popup cleared
                        ok, msg, tap_bounds = _execute_tap(
                            device,
                            by=sel_by,
                            value=sel_value,
                            fallback_rx=fallback_rx,
                            fallback_ry=fallback_ry,
                            timeout=tap_timeout,
                            retries=1,
                            implicit_wait_timeout=iw_timeout,
                            implicit_wait_poll=iw_poll,
                            element_image=elem_img_bytes,
                            image_threshold=_va_image_threshold,
                            screenshot_anchor=ss_anchor,
                        )
            step_result["ok"] = ok
            if msg:
                step_result["message"] = msg
                # Tag method for frontend display
                if "image match" in msg:
                    step_result["method"] = "image_match"
                elif "fallback position" in msg:
                    step_result["method"] = "fallback_position"
                elif msg.startswith("healed "):
                    step_result["method"] = "healed_selector"
                elif "selector" in msg:
                    step_result["method"] = "selector"
            if screen_ctx:
                step_result["screen_context"] = screen_ctx
            if tap_bounds:
                step_result["_bounds"] = tap_bounds

            # Self-healing hook:
            # (A) Proactive: healed_selector was found in Phase 1.5 — extract from message.
            # (B) Reactive: image_match succeeded (selector stale) — scan XML post-tap.
            if ok:
                try:
                    from runtime.selector_healer import try_heal_selector, HEALING_ENABLED
                    if HEALING_ENABLED:
                        method = step_result.get("method", "")
                        if method == "healed_selector":
                            # Phase 1.5 already found the healed selector — parse from message
                            # e.g. "healed text='Đăng nhập' (was resource-id='com.app:id/btn')"
                            msg_val = step_result.get("message", "")
                            import re as _re
                            m = _re.match(r"healed (\S+)=(.+?) \(was", msg_val)
                            if m:
                                step_result["healed_selector"] = {"by": m.group(1), "value": m.group(2).strip("'")}
                        elif method == "image_match" and tap_bounds:
                            healed = try_heal_selector(device, step, tap_bounds)
                            if healed:
                                step_result["healed_selector"] = healed
                except Exception as exc:
                    log.debug("[%s] selector healing failed: %s", serial, exc)

            # Brief fixed wait after tap
            if ok:
                time.sleep(0.3)

        elif t == "tap_ratio":
            try:
                rx = float(step.get("x", 0.5) or 0.5)
                ry = float(step.get("y", 0.5) or 0.5)
            except Exception:
                rx, ry = 0.5, 0.5
            x = max(0, min(w - 1, int(rx * w)))
            y = max(0, min(h - 1, int(ry * h)))
            try:
                device.tap(x, y)
                time.sleep(0.3)  # fixed brief wait — ratio taps don't need XML change detection
            except Exception as exc:
                msg = f"tap_ratio at ({x},{y}) failed: {exc}"
                log.warning(f"[{serial}] {msg}")
                step_result["ok"] = False
                step_result["message"] = msg

        elif t == "tap_position":
            pos = str(step.get("pos") or "middle_center")
            if pos == "top_center":
                rx, ry = 0.5, 0.1
            elif pos == "search_bar":
                rx, ry = 0.5, 0.18
            elif pos == "bottom_center":
                rx, ry = 0.5, 0.9
            else:  # middle_center hoặc bất kỳ giá trị nào khác
                rx, ry = 0.5, 0.5
            x = max(0, min(w - 1, int(rx * w)))
            y = max(0, min(h - 1, int(ry * h)))
            try:
                device.tap(x, y)
            except Exception as exc:
                msg = f"tap_position {pos} at ({x},{y}) failed: {exc}"
                log.warning(f"[{serial}] {msg}")
                step_result["ok"] = False
                step_result["message"] = msg

        elif t == "swipe_ratio":
            try:
                rx1 = float(step.get("x1", 0.5)); ry1 = float(step.get("y1", 0.5))
                rx2 = float(step.get("x2", 0.5)); ry2 = float(step.get("y2", 0.5))
                duration_ms = int(step.get("duration_ms", 300) or 300)
            except Exception:
                rx1, ry1, rx2, ry2, duration_ms = 0.5, 0.5, 0.5, 0.5, 300
            x1 = max(0, min(w - 1, int(rx1 * w)))
            y1 = max(0, min(h - 1, int(ry1 * h)))
            x2 = max(0, min(w - 1, int(rx2 * w)))
            y2 = max(0, min(h - 1, int(ry2 * h)))
            try:
                device.swipe(x1, y1, x2, y2, duration_ms=duration_ms)
            except Exception as exc:
                msg = f"swipe_ratio failed: {exc}"
                log.warning(f"[{serial}] {msg}")
                step_result["ok"] = False
                step_result["message"] = msg

        elif t == "tap_selector":
            # Legacy format — delegate to same _execute_tap pipeline
            by = str(step.get("by") or "text")
            value = str(step.get("value") or "").strip()
            fallback_rx = step.get("fallback_rx")
            fallback_ry = step.get("fallback_ry")
            sel_timeout = float(step.get("timeout", 8.0) or 8.0)
            if not value:
                step_result["ok"] = False
                step_result["message"] = "tap_selector: empty value"
            else:
                elem_img_bytes = _decode_element_image(step.get("element_image"))

                iw_timeout, iw_poll = _get_implicit_wait_config(step, _scenario_iw_config)
                ok, msg, tap_bounds = _execute_tap(
                    device, by=by, value=value,
                    fallback_rx=fallback_rx, fallback_ry=fallback_ry,
                    timeout=sel_timeout, retries=1,
                    implicit_wait_timeout=iw_timeout,
                    implicit_wait_poll=iw_poll,
                    element_image=elem_img_bytes,
                    image_threshold=_va_image_threshold,
                )

                # Auto-dismiss popup only on failure — never before the tap.
                if not ok:
                    now_t = time.monotonic()
                    if now_t - _last_popup_t >= 5.0:
                        dismissed = _auto_dismiss_popup(device)
                        _last_popup_t = time.monotonic()
                        if dismissed:
                            step_result["popup_dismissed"] = True
                            ok, msg, tap_bounds = _execute_tap(
                                device, by=by, value=value,
                                fallback_rx=fallback_rx, fallback_ry=fallback_ry,
                                timeout=sel_timeout, retries=1,
                                implicit_wait_timeout=iw_timeout,
                                implicit_wait_poll=iw_poll,
                                element_image=elem_img_bytes,
                                image_threshold=_va_image_threshold,
                            )
                step_result["ok"] = ok
                if msg:
                    step_result["message"] = msg
                    if "image match" in msg:
                        step_result["method"] = "image_match"
                if tap_bounds:
                    step_result["_bounds"] = tap_bounds
                if ok:
                    time.sleep(0.3)

        elif t == "wait_element":
            # Smart wait: poll until element appears. Far better than fixed wait N seconds.
            by = str(step.get("by") or "text")
            value = str(step.get("value") or "").strip()
            timeout = float(step.get("timeout", 10.0) or 10.0)
            if not value:
                step_result["ok"] = False; step_result["message"] = "wait_element: empty value"
            else:
                u2 = device.u2
                # Use Tenacity retry for robust element waiting
                iw_poll = float(step.get("poll", 0.5) or 0.5)
                eid = _retry_find_element(u2, by, value, timeout=timeout, poll=iw_poll) if u2 else None
                if eid is None:
                    msg = f"wait_element {by}={value!r} not found after {timeout:.0f}s"
                    log.warning(f"[{serial}] {msg}")
                    step_result["ok"] = False
                    step_result["message"] = msg
                else:
                    step_result["message"] = f"wait_element found {by}={value!r}"

        elif t == "assert_element":
            by = str(step.get("by") or "text")
            value = str(step.get("value") or "").strip()
            timeout = float(step.get("timeout", 5.0) or 5.0)
            if not value:
                step_result["ok"] = False; step_result["message"] = "assert_element: empty value"
            else:
                u2 = device.u2
                iw_poll = float(step.get("poll", 0.5) or 0.5)
                eid = _retry_find_element(u2, by, value, timeout=timeout, poll=iw_poll) if u2 else None
                if eid is None:
                    msg = f"assert_element FAILED: {by}={value!r} not visible after {timeout:.0f}s"
                    log.warning(f"[{serial}] {msg}")
                    step_result["ok"] = False
                    step_result["message"] = msg

        elif t == "input_selector":
            # Find input field by selector, clear it, then type. More reliable than tap + input_text.
            by = str(step.get("by") or "resource-id")
            value = str(step.get("value") or "").strip()
            text = str(step.get("text") or "")
            clear_first = bool(step.get("clear_first", True))
            if not value or not text:
                step_result["ok"] = False
                step_result["message"] = "input_selector: by/value/text required"
            else:
                try:
                    u2 = device.u2
                    if u2 is None:
                        device.ensure_u2_healthy(); u2 = device.u2
                    if u2 is None:
                        raise RuntimeError("u2 not available")
                    # Retry-until-visible: wait for the input field to appear
                    iw_timeout, iw_poll = _get_implicit_wait_config(step, _scenario_iw_config)
                    eid = _retry_find_element(u2, by, value, timeout=iw_timeout, poll=iw_poll)
                    if eid is None:
                        raise RuntimeError(f"element not visible after {iw_timeout:.0f}s: {by}={value!r}")
                    # Extract element id from dict result
                    if isinstance(eid, dict):
                        eid = eid.get("eid", f"{by}::{value}")
                    # Click the field to focus it
                    u2.element_click(eid)
                    time.sleep(0.3)
                    if clear_first:
                        u2.clear_text()
                        time.sleep(0.3)
                    u2.send_keys(text)
                    step_result["message"] = f"input_selector {by}={value!r} → {text!r}"
                except Exception as exc:
                    msg = f"input_selector failed: {exc}"
                    log.warning(f"[{serial}] {msg}")
                    step_result["ok"] = False
                    step_result["message"] = msg

        elif t == "long_tap_selector":
            by = str(step.get("by") or "text")
            value = str(step.get("value") or "").strip()
            duration_ms = int(step.get("duration_ms", 800) or 800)
            if not value:
                step_result["ok"] = False; step_result["message"] = "long_tap_selector: empty value"
            else:
                try:
                    u2 = device.u2
                    if u2 is None:
                        device.ensure_u2_healthy(); u2 = device.u2
                    if u2 is None:
                        raise RuntimeError("u2 not available")
                    # Retry-until-visible: wait for element before long-tapping
                    iw_timeout, iw_poll = _get_implicit_wait_config(step, _scenario_iw_config)
                    result = _retry_find_element(u2, by, value, timeout=iw_timeout, poll=iw_poll)
                    if result is None:
                        raise RuntimeError(f"element not visible after {iw_timeout:.0f}s: {by}={value!r}")
                    # Extract bounds from retry result or fetch via objInfo
                    bounds = None
                    if isinstance(result, dict):
                        bounds = result.get("bounds")
                    if not bounds:
                        selector = u2._build_selector(by, value)
                        info = u2._rpc("objInfo", selector)
                        if not info:
                            raise RuntimeError(f"element bounds not found {by}={value!r}")
                        bounds = info.get("bounds") or {}
                    cx = (bounds.get("left", 0) + bounds.get("right", 0)) // 2
                    cy = (bounds.get("top", 0) + bounds.get("bottom", 0)) // 2
                    u2.long_click(cx, cy, duration_ms / 1000.0)
                except Exception as exc:
                    msg = f"long_tap_selector failed: {exc}"
                    log.warning(f"[{serial}] {msg}")
                    step_result["ok"] = False
                    step_result["message"] = msg

        elif t == "scroll_to":
            # Scroll until element becomes visible (max N swipes).
            by = str(step.get("by") or "text")
            value = str(step.get("value") or "").strip()
            direction = str(step.get("direction", "down") or "down")
            max_swipes = int(step.get("max_swipes", 5) or 5)
            if not value:
                step_result["ok"] = False; step_result["message"] = "scroll_to: empty value"
            else:
                sx = w // 2
                # Swipe coords: down = finger swipes up (content moves down = scroll down)
                if direction == "up":
                    sy1, sy2 = int(h * 0.3), int(h * 0.7)
                else:
                    sy1, sy2 = int(h * 0.7), int(h * 0.3)
                found = False
                for i in range(max_swipes):
                    try:
                        u2 = device.u2
                        # timeout=0: quick check per-swipe, don't wait 10s per iteration
                        if u2 is not None and u2.find_element(by, value, timeout=0) is not None:
                            found = True
                            break
                    except Exception:
                        pass
                    try:
                        device.swipe(sx, sy1, sx, sy2, duration_ms=500)
                    except Exception:
                        pass
                    time.sleep(0.3)
                if not found:
                    msg = f"scroll_to {by}={value!r} not found after {max_swipes} swipes"
                    log.warning(f"[{serial}] {msg}")
                    step_result["ok"] = False
                    step_result["message"] = msg
                else:
                    step_result["message"] = f"scroll_to found {by}={value!r} after {i+1} swipe(s)"

        elif t == "input_text":
            text = str(step.get("text") or "")
            via = str(step.get("via") or "u2")
            if not text:
                msg = "input_text: empty text"
                log.warning(f"[{serial}] {msg}")
                step_result["ok"] = False
                step_result["message"] = msg
            elif via in ("u2", "a11y_key"):
                d = device.u2
                if d is None:
                    device.ensure_u2_healthy()
                    d = device.u2

                typed = False

                # Strategy 1: u2 send_keys — setText on focused field, then IME (Unicode OK on Android 14).
                if d is not None:
                    try:
                        d.send_keys(text)  # type: ignore[union-attr]
                        typed = True
                        step_result["message"] = "input_text via u2 send_keys"
                        log.info(f"[{serial}] input_text: strategy 1 (send_keys) OK")
                    except Exception as u2_exc:
                        log.info(f"[{serial}] input_text: strategy 1 failed: {u2_exc}")

                # Strategy 2: a11y ACTION_SET_TEXT (Unicode OK; no shell INJECT_EVENTS on Android 14+).
                if not typed:
                    try:
                        if device._a11y_mutate("type", {"text": text}, timeout=6.0):  # type: ignore[attr-defined]
                            typed = True
                            step_result["message"] = "input_text via a11y type"
                            log.info(f"[{serial}] input_text: strategy 2 (a11y type) OK")
                    except Exception as a11y_exc:
                        log.info(f"[{serial}] input_text: strategy 2 failed: {a11y_exc}")

                # Strategy 3: adb shell input text via relay (ASCII only).
                # This executes as shell UID on the relay side, avoiding app-UID
                # INJECT_EVENTS restrictions seen in WsAgentService shell fallback.
                if not typed:
                    is_ascii = all(ord(c) < 128 for c in text)
                    if is_ascii:
                        escaped = (
                            text
                            .replace("\\", "\\\\")
                            .replace('"', '\\"')
                            .replace(" ", "%s")
                            .replace("\n", "%n")
                        )
                        try:
                            from runtime.transports.adb_relay_server import get_relay_manager
                            relay = get_relay_manager()
                            loop = getattr(device, "_loop", None)
                            resolver = getattr(device, "_resolve_relay_serial", None)
                            target_serial = (
                                resolver() if callable(resolver)
                                else getattr(device, "_adb_serial", None)
                                or getattr(device, "serial", None)
                                or serial
                            )
                            if relay and loop and target_serial and relay.relay_for_serial(target_serial):
                                actual_serial = relay.resolve_serial(str(target_serial))
                                fut = asyncio.run_coroutine_threadsafe(
                                    relay.adb_shell(actual_serial, f'input text "{escaped}"', timeout=20.0),
                                    loop,
                                )
                                out = fut.result(timeout=25.0) or ""
                                low = out.lower()
                                if any(m in low for m in ("error:", "exception", "securityexception")):
                                    raise RuntimeError(out.strip() or "adb shell input text failed")
                                typed = True
                                step_result["message"] = "input_text via adb relay shell input text"
                                log.info(
                                    f"[{serial}] input_text: strategy 3 (adb relay shell) OK "
                                    f"serial={actual_serial}"
                                )
                            else:
                                log.info(f"[{serial}] input_text: strategy 3 skipped (no adb relay/loop)")
                        except Exception as shell_exc:
                            log.info(f"[{serial}] input_text: strategy 3 failed: {shell_exc}")

                # Strategy 4: agent type (a11y; avoids paste→shell Unicode path on Android 14+).
                if not typed and getattr(device, "_agent_send", None) is not None:
                    log.info(f"[{serial}] input_text: trying strategy 4 (agent type)")
                    device._send_to_agent({"type": "type", "text": text})  # type: ignore[attr-defined]
                    time.sleep(0.7)
                    typed = True
                    step_result["message"] = "input_text via agent type"

                if not typed:
                    log.warning(f"[{serial}] input_text: all strategies failed for {text!r}")

                if not typed:
                    step_result["ok"] = False
                    step_result["message"] = f"input_text: all strategies failed for {text!r}"
            else:
                msg = f"input_text: unknown via={via!r}"
                log.warning(f"[{serial}] {msg}")
                step_result["ok"] = False
                step_result["message"] = msg

        elif t == "key":
            key = str(step.get("key") or "")
            if not key:
                msg = "key: empty key"
                log.warning(f"[{serial}] {msg}")
                step_result["ok"] = False
                step_result["message"] = msg
            else:
                try:
                    device.key(key)
                except Exception as exc:
                    msg = f"key({key}) failed: {exc}"
                    log.warning(f"[{serial}] {msg}")
                    step_result["ok"] = False
                    step_result["message"] = msg

        elif t == "double_tap":
            # Supports rx/ry (relative 0-1) or absolute x/y
            try:
                rx = step.get("rx")
                ry = step.get("ry")
                if rx is not None and ry is not None:
                    px = int(float(rx) * w)
                    py = int(float(ry) * h)
                else:
                    px = int(step.get("x", w // 2))
                    py = int(step.get("y", h // 2))
                device.double_tap(px, py)
                wait_after = float(step.get("wait_after", 0.5) or 0.5)
                if wait_after > 0:
                    time.sleep(wait_after)
                log.info(f"[{serial}] double_tap ({px},{py})")
            except Exception as exc:
                msg = f"double_tap failed: {exc}"
                log.warning(f"[{serial}] {msg}")
                step_result["ok"] = False
                step_result["message"] = msg

        elif t == "pinch":
            # cx/cy: absolute coords; or rx/ry relative. scale>1=zoom in, <1=zoom out
            try:
                rx = step.get("rx")
                ry = step.get("ry")
                if rx is not None and ry is not None:
                    cx = int(float(rx) * w)
                    cy = int(float(ry) * h)
                else:
                    cx = int(step.get("cx", w // 2))
                    cy = int(step.get("cy", h // 2))
                scale = float(step.get("scale", 0.5) or 0.5)
                duration_ms = int(step.get("duration_ms", 400) or 400)
                device.pinch(cx, cy, scale, duration_ms)
                time.sleep(0.4)
                log.info(f"[{serial}] pinch ({cx},{cy}) scale={scale}")
            except Exception as exc:
                msg = f"pinch failed: {exc}"
                log.warning(f"[{serial}] {msg}")
                step_result["ok"] = False
                step_result["message"] = msg

        elif t == "drag":
            # rx1/ry1/rx2/ry2 (relative) or x1/y1/x2/y2 (absolute)
            try:
                if step.get("rx1") is not None:
                    x1 = int(float(step.get("rx1", 0)) * w)
                    y1 = int(float(step.get("ry1", 0)) * h)
                    x2 = int(float(step.get("rx2", 0)) * w)
                    y2 = int(float(step.get("ry2", 0)) * h)
                else:
                    x1 = int(step.get("x1", 0))
                    y1 = int(step.get("y1", 0))
                    x2 = int(step.get("x2", 0))
                    y2 = int(step.get("y2", 0))
                duration_ms = int(step.get("duration_ms", 1000) or 1000)
                device.drag(x1, y1, x2, y2, duration_ms)
                time.sleep(0.4)
                log.info(f"[{serial}] drag ({x1},{y1})→({x2},{y2})")
            except Exception as exc:
                msg = f"drag failed: {exc}"
                log.warning(f"[{serial}] {msg}")
                step_result["ok"] = False
                step_result["message"] = msg

        elif t == "take_screenshot":
            # Capture a screenshot. Result stored in step_result["screenshot"] (base64).
            # Optional: save_path to write JPEG to disk.
            try:
                frame = device.capture_screenshot()
                if frame is None:
                    step_result["ok"] = False
                    step_result["message"] = "take_screenshot: no frame available"
                else:
                    save_path = step.get("save_path")
                    if save_path:
                        import os as _os
                        _os.makedirs(_os.path.dirname(_os.path.abspath(save_path)), exist_ok=True)
                        with open(save_path, "wb") as _f:
                            _f.write(frame)
                    step_result["screenshot"] = base64.b64encode(frame).decode()
                    log.info(f"[{serial}] take_screenshot: {len(frame)} bytes")
            except Exception as exc:
                msg = f"take_screenshot failed: {exc}"
                log.warning(f"[{serial}] {msg}")
                step_result["ok"] = False
                step_result["message"] = msg

        elif t == "set_clipboard":
            text = str(step.get("text") or "")
            try:
                device.set_clipboard(text)
                time.sleep(0.3)
                log.info(f"[{serial}] set_clipboard: {len(text)} chars")
            except Exception as exc:
                msg = f"set_clipboard failed: {exc}"
                log.warning(f"[{serial}] {msg}")
                step_result["ok"] = False
                step_result["message"] = msg

        elif t == "scroll_down":
            try:
                repeats = int(step.get("repeats", 1) or 1)
            except Exception:
                repeats = 1
            try:
                start_y_ratio = float(step.get("start_y_ratio", 0.65))
            except Exception:
                start_y_ratio = 0.65
            try:
                end_y_ratio = float(step.get("end_y_ratio", 0.47))
            except Exception:
                end_y_ratio = 0.47
            try:
                duration_ms = int(step.get("duration_ms", 520) or 520)
            except Exception:
                duration_ms = 520
            try:
                pause_seconds = float(step.get("pause_seconds", 0.6) or 0.6)
            except Exception:
                pause_seconds = 0.6
            try:
                start_x_ratio = float(step.get("start_x_ratio", 0.5) or 0.5)
            except Exception:
                start_x_ratio = 0.5

            # Keep scroll gesture in safe viewport range and ensure downward move.
            start_y_ratio = min(0.95, max(0.55, start_y_ratio))
            end_y_ratio = min(0.75, max(0.1, end_y_ratio))
            if end_y_ratio >= start_y_ratio:
                end_y_ratio = max(0.1, start_y_ratio - 0.22)

            start_x_ratio = min(0.95, max(0.05, start_x_ratio))
            sx = int(w * start_x_ratio)
            sy1 = int(h * start_y_ratio)
            sy2 = int(h * end_y_ratio)
            failed = False
            for i in range(max(1, repeats)):
                log.info(f"[{serial}] scroll swipe #{i + 1}: ({sx},{sy1})→({sx},{sy2})")
                try:
                    device.swipe(sx, sy1, sx, sy2, duration_ms=duration_ms)
                except Exception as exc:
                    msg = f"swipe scroll #{i + 1} failed: {exc}"
                    log.warning(f"[{serial}] {msg}")
                    step_result["ok"] = False
                    step_result["message"] = msg
                    failed = True
                    break
                time.sleep(max(0.1, pause_seconds))
            if not failed:
                step_result["ok"] = True

        elif t == "wait_stable":
            # stable_duration: how long UI must be unchanged (default 0.4s)
            ws_timeout = float(step.get("timeout", 5.0) or 5.0)
            ws_stable = float(step.get("stable_duration", 0.4) or 0.4)
            stable = _wait_screen_stable(device, timeout=ws_timeout, stable_duration=ws_stable)
            step_result["ok"] = True
            step_result["message"] = f"wait_stable: {'stable' if stable else 'timed_out'}"

        elif t == "verify_screen":
            # Visual Anchoring: compare current screen with recorded screenshot.
            # Fails if SSIM is below threshold. Use after navigation to ensure
            # the playback is on the correct screen before proceeding.
            screenshot_b64 = str(step.get("screenshot") or "").strip()
            vs_threshold = float(step.get("ssim_threshold", 0.75) or 0.75)
            vs_timeout = float(step.get("timeout", 8.0) or 8.0)
            vs_poll = float(step.get("poll", 0.5) or 0.5)
            if not screenshot_b64:
                step_result["ok"] = False
                step_result["message"] = "verify_screen: no screenshot provided"
            else:
                try:
                    from runtime.visual_anchor import wait_for_screen_match, _b64_to_bytes
                    recorded_jpeg = _b64_to_bytes(screenshot_b64)
                    matched, ssim = wait_for_screen_match(
                        device.take_screenshot, recorded_jpeg,
                        timeout=vs_timeout, poll=vs_poll,
                        ssim_threshold=vs_threshold,
                    )
                    step_result["ssim"] = round(ssim, 3)
                    if matched:
                        step_result["message"] = f"verify_screen: SSIM={ssim:.3f} ≥ {vs_threshold}"
                    else:
                        step_result["ok"] = False
                        step_result["message"] = f"verify_screen FAILED: SSIM={ssim:.3f} < {vs_threshold}"
                        log.warning(f"[{serial}] {step_result['message']}")
                except ImportError:
                    step_result["ok"] = False
                    step_result["message"] = "verify_screen: opencv-python-headless not installed"
                except Exception as exc:
                    step_result["ok"] = False
                    step_result["message"] = f"verify_screen error: {exc}"

        elif t == "dismiss_popup":
            # Explicitly try to dismiss any visible popup/dialog.
            # retries: how many times to attempt (default 3, 0.5s apart)
            retries = int(step.get("retries", 3) or 3)
            dismissed_count = 0
            for _ in range(retries):
                if _auto_dismiss_popup(device):
                    dismissed_count += 1
                    time.sleep(0.3)
                else:
                    break
            step_result["ok"] = True
            step_result["message"] = f"dismiss_popup: dismissed {dismissed_count} popup(s)"
            if dismissed_count > 0:
                step_result["dismissed_count"] = dismissed_count

        elif t == "extract":
            """Extract UI data (posts, text nodes) from current screen into context."""
            step = normalize_extract_step(step)
            strategy = str(step.get("strategy", "fb_posts"))
            from tasks.scenario.steps.extraction import EDGE_CONTENT_STRATEGIES

            if strategy in EDGE_CONTENT_STRATEGIES:
                from tasks.scenario.steps.extraction import request_edge_extra_data

                if request_edge_extra_data(
                    device=device,
                    serial=serial,
                    ctx=ctx,
                    scenario=scenario,
                    step=step,
                    strategy=strategy,
                    result=step_result,
                    cancel_event=cancel_event,
                ):
                    results.append(step_result)
                    continue
                step_result["ok"] = False
                step_result["message"] = (
                    f"extract {strategy}: device_farm content XML parser was removed; "
                    "enable edge_extra_data so phone/APK sends XML to agent-boot"
                )
                results.append(step_result)
                continue

            step_result["ok"] = False
            step_result["message"] = f"extract: unknown strategy {strategy!r}"

        # ── DF-009: OCR & Screen Text Extraction ──────────────────────────
        elif t == "extract_text_hierarchy":
            save_as = step.get("save_as", "")
            if not save_as:
                step_result["ok"] = False
                step_result["message"] = "extract_text_hierarchy: missing save_as"
            else:
                try:
                    from runtime.extraction.hierarchy_extractor import HierarchyExtractor
                    xml = device.hierarchy_xml(force_refresh=True)
                    if not xml:
                        step_result["ok"] = False
                        step_result["message"] = "No hierarchy XML available"
                    else:
                        fmt = step.get("format", "text")
                        items = HierarchyExtractor.extract_texts(
                            xml,
                            filter_class=step.get("filter_class"),
                            exclude_empty=step.get("exclude_empty", True),
                        )
                        if fmt == "json":
                            _var_ctx.set(save_as, items)
                        else:
                            _var_ctx.set(save_as, "\n".join(i["text"] for i in items if i.get("text")))
                        step_result["message"] = f"Extracted {len(items)} text elements"
                except Exception as exc:
                    step_result["ok"] = False
                    step_result["message"] = f"extract_text_hierarchy failed: {exc}"

        elif t == "extract_text_ocr":
            save_as = step.get("save_as", "")
            if not save_as:
                step_result["ok"] = False
                step_result["message"] = "extract_text_ocr: missing save_as"
            else:
                try:
                    from runtime.extraction.ocr_engine import OCREngine
                    frame = device.take_screenshot()
                    if not frame:
                        step_result["ok"] = False
                        step_result["message"] = "No screenshot available for OCR"
                    else:
                        ocr = OCREngine()
                        text = ocr.extract_text(
                            frame,
                            language=step.get("language", "eng"),
                            region=step.get("region"),
                            psm=int(step.get("psm", 11)),
                            preprocess=step.get("preprocess", True),
                            scale_factor=float(step.get("scale_factor", 2.0)),
                        )
                        _var_ctx.set(save_as, text)
                        step_result["message"] = f"OCR extracted {len(text)} chars"
                except Exception as exc:
                    step_result["ok"] = False
                    step_result["message"] = f"extract_text_ocr failed: {exc}"

        elif t == "extract_text_ai":
            save_as = step.get("save_as", "")
            prompt = step.get("prompt", "")
            if not save_as or not prompt:
                step_result["ok"] = False
                step_result["message"] = "extract_text_ai: missing save_as or prompt"
            else:
                try:
                    from runtime.extraction.ai_vision import AIVisionExtractor
                    frame = device.take_screenshot()
                    if not frame:
                        step_result["ok"] = False
                        step_result["message"] = "No screenshot available for AI extraction"
                    else:
                        ai = AIVisionExtractor()
                        result = ai.extract(
                            frame,
                            prompt=prompt,
                            provider=step.get("provider", "openai"),
                            output_format=step.get("format", "json"),
                            model=step.get("model"),
                            region=step.get("region"),
                        )
                        _var_ctx.set(save_as, result)
                        step_result["message"] = f"AI extracted {type(result).__name__}"
                except Exception as exc:
                    step_result["ok"] = False
                    step_result["message"] = f"extract_text_ai failed: {exc}"

        elif t == "extract_screen_data":
            save_as = step.get("save_as", "")
            if not save_as:
                step_result["ok"] = False
                step_result["message"] = "extract_screen_data: missing save_as"
            else:
                strategy = step.get("strategy", "auto")
                extracted = None
                source = ""
                try:
                    # Strategy 1: Hierarchy (free, fastest)
                    if strategy in ("auto", "hierarchy"):
                        from runtime.extraction.hierarchy_extractor import HierarchyExtractor
                        xml = device.hierarchy_xml(force_refresh=True)
                        if xml:
                            items = HierarchyExtractor.extract_texts(xml, exclude_empty=True)
                            if items:
                                extracted = "\n".join(i["text"] for i in items if i.get("text"))
                                source = "hierarchy"

                    # Strategy 2: OCR (free, handles WebView/Canvas)
                    if extracted is None and strategy in ("auto", "ocr"):
                        from runtime.extraction.ocr_engine import OCREngine
                        frame = device.take_screenshot()
                        if frame:
                            ocr = OCREngine()
                            if ocr.available:
                                text = ocr.extract_text(
                                    frame,
                                    language=step.get("language", "eng"),
                                    psm=11,
                                )
                                if text and len(text) > 3:
                                    extracted = text
                                    source = "ocr"

                    # Strategy 3: AI Vision (paid, best for structured data)
                    if extracted is None and strategy in ("auto", "ai"):
                        from runtime.extraction.ai_vision import AIVisionExtractor
                        frame = device.take_screenshot()
                        if frame:
                            schema = step.get("schema")
                            prompt = "Extract all visible text from this mobile screenshot."
                            if schema:
                                prompt = (
                                    f"Extract the following fields from this screenshot: "
                                    f"{json.dumps(schema)}. Return as JSON."
                                )
                            ai = AIVisionExtractor()
                            extracted = ai.extract(
                                frame, prompt=prompt,
                                output_format="json" if schema else "text",
                            )
                            source = "ai"

                    if extracted is not None:
                        _var_ctx.set(save_as, extracted)
                        step_result["message"] = f"Extracted via {source}"
                        step_result["source"] = source
                    else:
                        step_result["ok"] = False
                        step_result["message"] = "extract_screen_data: no data extracted"
                except Exception as exc:
                    step_result["ok"] = False
                    step_result["message"] = f"extract_screen_data failed: {exc}"

        elif t == "save_extraction":
            step = normalize_save_extraction_step(step)
            data_var = step.get("data_var", "")
            if not data_var:
                step_result["ok"] = False
                step_result["message"] = "save_extraction: missing data_var"
            else:
                try:
                    data = _var_ctx._runtime_vars.get(data_var)
                    # Fallback to scenario context for extract strategies that store in ctx.
                    if data is None:
                        data = ctx.get(data_var)
                    if data is None:
                        step_result["ok"] = False
                        step_result["message"] = f"save_extraction: variable '{data_var}' not found"
                    else:
                        if not isinstance(data, (str, dict, list)):
                            step_result["ok"] = False
                            step_result["message"] = (
                                f"save_extraction: unsupported type for '{data_var}': {type(data).__name__}"
                            )
                            continue
                        if isinstance(data, list) and data and not any(isinstance(item, dict) for item in data):
                            step_result["ok"] = False
                            step_result["message"] = (
                                f"save_extraction: variable '{data_var}' is a list but has no object items"
                            )
                            continue

                        offsets = ctx.setdefault("__save_extraction_offsets__", {})
                        _parent_id_var = step.get("parent_id_var")
                        _parent_id = ctx.get(_parent_id_var) if _parent_id_var else None
                        _campaign_vars = scenario.get("_campaign_vars") or {}
                        _scenario_cfg = {
                            k: scenario.get(k)
                            for k in ("capture_steps", "preview_collection")
                            if scenario.get(k) is not None
                        }
                        from services.execution.preview_collection import resolve_content_collection

                        _collection = resolve_content_collection(
                            step,
                            campaign_vars=_campaign_vars,
                            scenario_config=_scenario_cfg,
                        )
                        _platform = step.get("platform")
                        _ctype = step.get("content_type")
                        if not _ctype:
                            step_result["ok"] = False
                            step_result["message"] = (
                                "save_extraction: content_type is required (platform-qualified, e.g. fb_post)"
                            )
                            continue
                        from services.content.legacy_type_map import qualify_content_type

                        _ctype = qualify_content_type(_ctype, platform=_platform) or _ctype
                        report, updated_offsets = _run_async_coro_sync(
                            persist_data_items(
                                data=data,
                                data_var=data_var,
                                offsets=offsets,
                                collection=_collection,
                                platform=_platform,
                                content_type=_ctype,
                                dedupe_field=step.get("dedupe_field"),
                                tags=step.get("tags", ""),
                                device_serial=device.serial,
                                campaign_id=(scenario.get("campaign_id")),
                                execution_id=(scenario.get("execution_id") or scenario.get("run_id")),
                                parent_id=_parent_id,
                                item_level=int(step.get("item_level") or 0),
                                user_id=(scenario.get("_campaign_vars") or {}).get("__USER_ID__"),
                            )
                        )
                        ctx["__save_extraction_offsets__"] = updated_offsets
                        step_result["saved"] = report.saved_count > 0
                        step_result["saved_count"] = report.saved_count
                        step_result["duplicate_count"] = report.duplicate_count
                        step_result["error_count"] = report.error_count
                        step_result["last_result"] = report.last_result or {}
                        if (
                            report.error_count > 0
                            and report.saved_count == 0
                            and report.duplicate_count == 0
                        ):
                            step_result["ok"] = False
                            step_result["message"] = "save_extraction: all items failed"
                        else:
                            step_result["message"] = (
                                f"save_extraction: saved={report.saved_count}, "
                                f"duplicate={report.duplicate_count}, errors={report.error_count}"
                            )
                except Exception as exc:
                    step_result["ok"] = False
                    step_result["message"] = f"save_extraction failed: {exc}"

        elif t == "loop":
            """Repeat nested steps N times (count) or while condition is true."""
            count = step.get("count")
            while_cond = step.get("while")  # condition dict
            max_iterations = int(step.get("max_iterations", 100))
            nested_steps = step.get("steps") or []

            if not nested_steps:
                step_result["ok"] = False
                step_result["message"] = "loop: no nested steps"
            else:
                # Determine iteration count
                if count is not None:
                    # count is explicit — max_iterations applies to while-only loops.
                    iterations = int(count)
                    use_while = False
                elif while_cond:
                    iterations = max_iterations
                    use_while = True
                else:
                    step_result["ok"] = False
                    step_result["message"] = "loop: must specify either 'count' or 'while'"
                    iterations = 0
                    use_while = False

                sub_results = []
                actual_iters = 0
                for i in range(iterations):
                    # Evaluate while condition if present
                    if use_while and not _evaluate_condition(device, while_cond, ctx):
                        break

                    ctx["_loop_iter"] = i
                    # Run nested steps (reuse run_scenario_task recursively)
                    nested_result = run_scenario_task(device, {"steps": nested_steps}, context=ctx, _var_ctx=_var_ctx, _depth=_depth + 1)
                    sub_results.append({"iteration": i, "result": nested_result})
                    actual_iters += 1

                    # Check break signal from extract step or break_if step
                    if ctx.pop("_break", False):
                        log.info(f"[{serial}] loop: break at iteration {i}")
                        break

                ctx.pop("_loop_iter", None)
                step_result["iterations"] = actual_iters
                step_result["sub_results"] = sub_results
                step_result["message"] = f"loop: {actual_iters} iteration(s)"

        elif t == "if":
            """Conditional: run 'then' steps if condition is true, else 'else' steps."""
            condition = step.get("condition") or {}
            then_steps = step.get("then") or []
            else_steps = step.get("else") or []

            if not condition:
                step_result["ok"] = False
                step_result["message"] = "if: missing condition"
            else:
                cond_met = _evaluate_condition(device, condition, ctx)
                branch_steps = then_steps if cond_met else else_steps
                branch_name = "then" if cond_met else "else"

                if branch_steps:
                    branch_result = run_scenario_task(device, {"steps": branch_steps}, context=ctx, _var_ctx=_var_ctx, _depth=_depth + 1)
                    step_result["branch"] = branch_name
                    step_result["condition_met"] = cond_met
                    step_result["sub_result"] = branch_result
                    step_result["message"] = f"if: took {branch_name} branch"
                else:
                    step_result["message"] = f"if: condition={cond_met}, no steps for {branch_name} branch"

        elif t == "break_if":
            """Break the current loop if condition is true."""
            condition = step.get("condition") or {}
            if not condition:
                step_result["ok"] = False
                step_result["message"] = "break_if: missing condition"
            else:
                if _evaluate_condition(device, condition, ctx):
                    ctx["_break"] = True
                    step_result["message"] = "break_if: condition met — breaking loop"
                else:
                    step_result["message"] = "break_if: condition not met — continuing"

        # ── DF-002: Control Flow ──────────────────────────────────────────────

        elif t == "repeat":
            count = step.get("count")
            delay = float(step.get("delay_between", 0.0) or 0.0)
            sub_steps = step.get("steps") or []

            if count is None:
                step_result["ok"] = False
                step_result["message"] = "repeat: missing count"
            elif not sub_steps:
                step_result["ok"] = False
                step_result["message"] = "repeat: no nested steps"
            else:
                try:
                    n = int(count)
                except (TypeError, ValueError):
                    step_result["ok"] = False
                    step_result["message"] = f"repeat: invalid count={count!r}"
                    n = 0

                sub_results: List[Dict[str, Any]] = []
                for i in range(n):
                    _var_ctx.set("__LOOP_INDEX__", i)
                    iter_res = run_scenario_task(
                        device,
                        {"steps": sub_steps},
                        context=ctx,
                        _var_ctx=_var_ctx,
                        _depth=_depth + 1,
                    )
                    sub_results.append({"iteration": i, "result": iter_res})
                    if not iter_res.get("success"):
                        step_result["ok"] = False
                        step_result["message"] = f"repeat: iteration {i} failed — {iter_res.get('failed_message', '')}"
                        break
                    if delay > 0 and i < n - 1:
                        time.sleep(delay)
                else:
                    step_result["message"] = f"repeat: {n} iteration(s) completed"
                step_result["iterations"] = len(sub_results)
                step_result["sub_results"] = sub_results

        elif t == "repeat_until":
            condition = step.get("condition") or {}
            max_iter = max(1, int(step.get("max_iterations", 100) or 100))
            sub_steps = step.get("steps") or []

            if not condition:
                step_result["ok"] = False
                step_result["message"] = "repeat_until: missing condition"
            elif not sub_steps:
                step_result["ok"] = False
                step_result["message"] = "repeat_until: no nested steps"
            else:
                actual_iters = 0
                condition_met = False
                for i in range(max_iter):
                    _var_ctx.set("__LOOP_INDEX__", i)
                    if _eval_ru_condition(device, condition, _var_ctx):
                        condition_met = True
                        break
                    iter_res = run_scenario_task(
                        device,
                        {"steps": sub_steps},
                        context=ctx,
                        _var_ctx=_var_ctx,
                        _depth=_depth + 1,
                    )
                    actual_iters += 1
                    if not iter_res.get("success"):
                        step_result["ok"] = False
                        step_result["message"] = f"repeat_until: iteration {i} failed — {iter_res.get('failed_message', '')}"
                        break
                else:
                    # Exhausted iterations without condition met
                    if not condition_met:
                        step_result["ok"] = False
                        step_result["message"] = f"repeat_until: max_iterations ({max_iter}) reached without condition"

                step_result["iterations"] = actual_iters
                if condition_met:
                    step_result["message"] = f"repeat_until: condition met after {actual_iters} iteration(s)"

        elif t == "if_element":
            by = str(step.get("by") or "")
            value = str(step.get("value") or "").strip()
            timeout = float(step.get("timeout", 3.0) or 3.0)
            then_steps = step.get("then") or []
            else_steps = step.get("else") or []

            if not by or not value:
                step_result["ok"] = False
                step_result["message"] = "if_element: missing by/value"
            else:
                element_found = False
                try:
                    device.ensure_u2_healthy()
                    u2 = device.u2
                    if u2 is not None:
                        eid = _wait_for_element(u2, by, value, timeout=timeout)
                        element_found = eid is not None
                except Exception as exc:
                    log.debug(f"[{serial}] if_element u2 check error: {exc}")

                branch_steps = then_steps if element_found else else_steps
                branch_name = "then" if element_found else "else"
                step_result["element_found"] = element_found
                step_result["branch"] = branch_name

                if branch_steps:
                    sub = run_scenario_task(
                        device,
                        {"steps": branch_steps},
                        context=ctx,
                        _var_ctx=_var_ctx,
                        _depth=_depth + 1,
                    )
                    step_result["sub_result"] = sub
                    if not sub.get("success"):
                        step_result["ok"] = False
                        step_result["message"] = f"if_element: {branch_name} branch failed"
                    else:
                        step_result["message"] = f"if_element(element_found={element_found}): took {branch_name}"
                else:
                    step_result["message"] = f"if_element(element_found={element_found}): no steps for {branch_name}, skip"

        elif t == "if_variable":
            name = str(step.get("name") or "")
            then_steps = step.get("then") or []
            else_steps = step.get("else") or []

            if not name:
                step_result["ok"] = False
                step_result["message"] = "if_variable: missing name"
            elif not then_steps and not else_steps:
                step_result["message"] = "if_variable: no then/else steps, skip"
            else:
                # Resolve variable — full-match preserves raw type for numeric comparisons
                raw_val = _var_ctx.resolve(f"${{{name}}}", step_index=idx)
                str_val = str(raw_val)

                condition_met = False
                if "equals" in step:
                    condition_met = str_val == str(step["equals"])
                elif "not_equals" in step:
                    condition_met = str_val != str(step["not_equals"])
                elif "contains" in step:
                    condition_met = str(step["contains"]) in str_val
                elif "greater_than" in step:
                    try:
                        condition_met = float(raw_val) > float(step["greater_than"])
                    except (TypeError, ValueError):
                        condition_met = False
                else:
                    # No comparison op — truthy: var is set and non-empty
                    condition_met = (
                        bool(raw_val)
                        and str_val not in ("None", "", "0")
                        and str_val != f"${{{name}}}"
                    )

                branch_steps = then_steps if condition_met else else_steps
                branch_name = "then" if condition_met else "else"
                step_result["condition_met"] = condition_met
                step_result["branch"] = branch_name

                if branch_steps:
                    sub = run_scenario_task(
                        device,
                        {"steps": branch_steps},
                        context=ctx,
                        _var_ctx=_var_ctx,
                        _depth=_depth + 1,
                    )
                    step_result["sub_result"] = sub
                    if not sub.get("success"):
                        step_result["ok"] = False
                        step_result["message"] = f"if_variable: {branch_name} branch failed"
                    else:
                        step_result["message"] = f"if_variable({name}={str_val!r}): took {branch_name}"
                else:
                    step_result["message"] = f"if_variable({name}={str_val!r}): no steps for {branch_name}, skip"

        elif t == "random_pick":
            branches = step.get("branches") or []
            if not branches:
                step_result["ok"] = False
                step_result["message"] = "random_pick: no branches"
            else:
                weights = [max(1, int(b.get("weight", 1))) for b in branches]
                # Use index-based selection to handle duplicate branch dicts correctly
                chosen_idx = random.choices(range(len(branches)), weights=weights, k=1)[0]
                chosen = branches[chosen_idx]
                branch_steps = chosen.get("steps") or []

                step_result["chosen_branch"] = chosen_idx
                if not branch_steps:
                    step_result["message"] = f"random_pick: branch {chosen_idx} has no steps, skip"
                else:
                    sub = run_scenario_task(
                        device,
                        {"steps": branch_steps},
                        context=ctx,
                        _var_ctx=_var_ctx,
                        _depth=_depth + 1,
                    )
                    step_result["sub_result"] = sub
                    if not sub.get("success"):
                        step_result["ok"] = False
                        step_result["message"] = f"random_pick: branch {chosen_idx} failed"
                    else:
                        step_result["message"] = f"random_pick: executed branch {chosen_idx}"

        elif t == "set_variable":
            name = str(step.get("name") or "")
            if not name:
                step_result["ok"] = False
                step_result["message"] = "set_variable: missing name"
            elif "from_list" in raw_step:
                vals = raw_step.get("from_list")
                if isinstance(vals, str):
                    resolved_list = _var_ctx.resolve(vals, step_index=idx)
                    vals = resolved_list if isinstance(resolved_list, list) else []
                if not isinstance(vals, list) or not vals:
                    step_result["ok"] = False
                    step_result["message"] = "set_variable: from_list phải là list không rỗng"
                else:
                    resolved_vals = [_var_ctx.resolve(v, step_index=idx) for v in vals]
                    chosen = _var_ctx.set_from_list(name, resolved_vals)
                    step_result["message"] = f"set_variable: {name} = {chosen!r} (from_list)"
            elif "increment" in step:
                try:
                    inc = int(step["increment"])
                except (TypeError, ValueError):
                    inc = 1
                result = _var_ctx.increment(name, inc)
                step_result["message"] = f"set_variable: {name} += {inc} → {result}"
            else:
                value = step.get("value")
                _var_ctx.set(name, value)
                step_result["message"] = f"set_variable: {name} = {value!r}"

        elif t == "set_var":
            """Set a variable in context.vars for use in conditions."""
            key = str(step.get("key") or "")
            value = step.get("value")
            if not key:
                step_result["ok"] = False
                step_result["message"] = "set_var: missing key"
            else:
                ctx["vars"][key] = value
                step_result["message"] = f"set_var: {key}={value!r}"

        # ── DF-003: Flow Composition ──────────────────────────────────────────

        elif t == "run_scenario":
            scenario_id = str(step.get("scenario_id") or "").strip()
            scenario_name = str(step.get("scenario_name") or "").strip()
            scenario_ref = scenario_id or scenario_name

            if not scenario_ref:
                step_result["ok"] = False
                step_result["message"] = "run_scenario: missing scenario_id or scenario_name"
            elif scenario_ref in _call_stack:
                step_result["ok"] = False
                step_result["message"] = f"run_scenario: circular reference detected: {scenario_ref!r}"
            else:
                registry = scenario.get("_scenario_registry") or {}
                sub_def: Optional[Dict[str, Any]] = None

                # Resolution order: by_id → by_campaign_name → by_template_name
                if scenario_id:
                    sub_def = (registry.get("by_id") or {}).get(scenario_id)
                if sub_def is None and scenario_name:
                    sub_def = (registry.get("by_campaign_name") or {}).get(scenario_name)
                if sub_def is None and scenario_name:
                    sub_def = (registry.get("by_template_name") or {}).get(scenario_name)

                if sub_def is None:
                    step_result["ok"] = False
                    step_result["message"] = f"run_scenario: sub-scenario not found: {scenario_ref!r}"
                    log.warning(f"[{serial}] run_scenario: sub-scenario not found: {scenario_ref!r}")
                else:
                    # Merge variables: sub-scenario defaults < step overrides
                    override_vars: Dict[str, Any] = step.get("variables") or {}
                    merged_vars = {**(sub_def.get("variables") or {}), **override_vars}
                    child_ctx = _var_ctx.child_scope(merged_vars)

                    # Pass registry down so nested run_scenario steps work
                    sub_scenario: Dict[str, Any] = {
                        "steps": sub_def.get("steps") or [],
                        "variables": merged_vars,
                        "_scenario_registry": registry,
                    }
                    new_call_stack = _call_stack | {scenario_ref}

                    sub = run_scenario_task(
                        device,
                        sub_scenario,
                        context=ctx,
                        _var_ctx=child_ctx,
                        _depth=_depth + 1,
                        _call_stack=new_call_stack,
                    )
                    step_result["sub_result"] = sub
                    if not sub.get("success"):
                        step_result["ok"] = False
                        step_result["message"] = (
                            f"run_scenario: sub-scenario {scenario_ref!r} failed — "
                            f"{sub.get('failed_message', '')}"
                        )
                    else:
                        step_result["message"] = (
                            f"run_scenario: {scenario_ref!r} completed "
                            f"({sub.get('steps_executed', 0)} steps)"
                        )

        else:
            msg = f"unknown step type: {t!r}"
            log.warning(f"[{serial}] {msg}")
            step_result["ok"] = False
            step_result["message"] = msg

        # Capture screenshot after step (debug mode) — Maestro-style:
        #   1. settle wait  (skip for pure-wait steps where no frame change is expected)
        #   2. stale-frame guard  (poll until device pushes a frame newer than step_start_t)
        #   3. capture
        if capture_dir:
            try:
                need_settle = t not in _CAPTURE_SKIP_SETTLE and _capture_settle_ms > 0
                if need_settle:
                    time.sleep(_capture_settle_ms / 1000.0)

                # Poll for fresh frame (frame_time > step_start_t).
                # Avoids saving the exact same frame captured as PRE (cache hit from
                # minicap's periodic 3-second push or stale JPEG buffer).
                if need_settle and _capture_stale_wait_s > 0:
                    _poll_deadline = time.monotonic() + _capture_stale_wait_s
                    _poll_interval = 0.05  # 50 ms
                    while time.monotonic() < _poll_deadline:
                        _ft = float(getattr(device, "_last_frame_time", 0.0) or 0.0)
                        if _ft > step_start_t:
                            break
                        time.sleep(_poll_interval)
                    else:
                        _ft = float(getattr(device, "_last_frame_time", 0.0) or 0.0)
                        if _ft <= step_start_t:
                            log.warning(
                                f"[{serial}] POST step#{idx + 1} ({t}): "
                                f"frame stale after {int(_capture_stale_wait_s * 1000)}ms wait "
                                f"— capturing anyway (frame may duplicate PRE)"
                            )

                # Build selector dict from step for debug context
                step_selector: Optional[Dict[str, str]] = None
                if t in ("tap", "tap_selector", "wait_element", "assert_element",
                         "input_selector", "long_tap_selector", "scroll_to"):
                    sel = step.get("selector") or {}
                    s_by = str(sel.get("by") or step.get("by") or "").strip()
                    s_val = str(sel.get("value") or step.get("value") or "").strip()
                    if s_by and s_val:
                        step_selector = {"by": s_by, "value": s_val}

                cap = _capture_step_screenshot(
                    device, capture_dir, idx, t or "unknown",
                    step_result.pop("_bounds", None), w, h,
                    selector=step_selector,
                )
                if cap:
                    step_result["screenshot"] = cap

                last_frame_t = float(getattr(device, "_last_frame_time", 0.0) or 0.0)
                if last_frame_t > 0:
                    age_ms = int((time.monotonic() - last_frame_t) * 1000)
                    fresh = last_frame_t > step_start_t
                    log.info(
                        f"[{serial}] capture POST step#{idx + 1} ({t}) "
                        f"frame_age={age_ms}ms fresh={fresh}"
                    )
                else:
                    log.info(f"[{serial}] capture POST step#{idx + 1} ({t}) frame_age=unknown")
            except Exception as exc:
                log.debug(f"[{serial}] step capture failed: {exc}")

        step_results.append(step_result)
        # Notify caller of step completion (used for SSE streaming)
        if on_step_done is not None:
            try:
                on_step_done(step_result)
            except Exception:
                pass

    all_ok = all(r.get("ok", True) for r in step_results)
    failed_steps = [r for r in step_results if not r.get("ok", True)]
    first_fail_msg = failed_steps[0].get("message", "step failed") if failed_steps else ""

    result = {
        "serial": serial,
        "success": all_ok,
        "steps_executed": len(steps),
        "step_results": step_results,
        "failed_message": first_fail_msg if not all_ok else None,
        "context": ctx,
    }
    if capture_dir:
        result["capture_dir"] = capture_dir
    return result


def make_scenario_task(
    scenario: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
    cancel_event: Optional["threading.Event"] = None,
):
 
    def _task(device: "DeviceClient") -> Dict[str, Any]:
        return run_scenario_task(device, scenario, context=context, cancel_event=cancel_event)

    _task.__name__ = "run_scenario"
    return _task
