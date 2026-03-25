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

import concurrent.futures
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple, TypedDict, Literal, Sequence

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


log = logging.getLogger(__name__)


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


def _wait_for_element(
    u2,
    by: str,
    value: str,
    timeout: float = 8.0,
    poll: float = 0.3,
) -> Optional[Any]:
    """
    Wait until element appears (up to `timeout` seconds).

    Strategy:
    - Non-xpath: use native waitForExists (single server-side blocking call via
      find_element(timeout=...)). Faster than polling — fewer TCP connections.
      Then fetch bounds via find_element_with_bounds (objInfo, single call).
    - xpath: poll via find_element (each call dumps hierarchy XML), poll every `poll`s.

    IMPORTANT: always pass explicit timeout to find_element so we don't inherit
    the 10s _implicitly_wait default — that would conflict with the outer deadline.
    """
    if u2 is None:
        return None

    deadline = time.monotonic() + timeout

    if by != "xpath":
        # Single server-side waitForExists call — no polling needed
        try:
            remaining = max(0.5, deadline - time.monotonic())
            eid = u2.find_element(by, value, timeout=remaining)
            if eid is None:
                return None
            # Element found — fetch bounds for accurate tap targeting
            if hasattr(u2, "find_element_with_bounds"):
                try:
                    result = u2.find_element_with_bounds(by, value)
                    if result:
                        return result
                except Exception:
                    pass
            return eid
        except Exception as exc:
            log.debug("_wait_for_element %s=%r error: %s", by, value, exc)
            return None

    # xpath: poll — each call dumps hierarchy XML so we poll with a gap
    consecutive_errors = 0
    MAX_CONSECUTIVE_ERRORS = 3
    while time.monotonic() < deadline:
        try:
            # timeout=0 = instant check (no server-side wait)
            eid = u2.find_element(by, value, timeout=0)
            if eid is not None:
                consecutive_errors = 0
                return eid
            consecutive_errors = 0
        except Exception as exc:
            consecutive_errors += 1
            log.debug("_wait_for_element xpath %r error #%d: %s", value, consecutive_errors, exc)
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                log.warning("_wait_for_element: %d consecutive errors, aborting (xpath=%r)", consecutive_errors, value)
                return None
        time.sleep(poll)
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


def _execute_tap(
    device: "DeviceClient",
    by: Optional[str],
    value: Optional[str],
    fallback_rx: Optional[float],
    fallback_ry: Optional[float],
    timeout: float = 8.0,
    retries: int = 2,
) -> Tuple[bool, str]:
    """
    Full tap pipeline:
      1. wait_for_element (poll 300ms, up to `timeout`)
      2. tap at recorded position (fallback_rx/ry) if within bounds, else center of bounds
      3. on fail → retry up to `retries` times
      4. final fallback → ratio tap
    Returns (ok, message).
    """
    serial = device.serial
    w = device.screen_width or 1080
    h = device.screen_height or 1920
    u2 = device.u2

    # Skip useless container class selectors (same list as frontend CONTAINER_CLASSES).
    # STF flat XML returns only window-container nodes, so these selectors always
    # match the wrong element (whole-screen FrameLayout). Treat as no selector.
    if by == "class name" and value in _CONTAINER_CLASSES:
        log.debug(f"[{serial}] selector class={value!r} is a container — skipping to ratio fallback")
        by = None
        value = None

    if u2 and by and value:
        for attempt in range(retries):
            # _wait_for_element: uses native waitForExists (non-xpath) or polling (xpath)
            result = _wait_for_element(u2, by, value, timeout=timeout)
            if result is not None:
                try:
                    # Extract bounds — either from find_element_with_bounds result dict
                    # or by calling find_element_with_bounds directly as fallback
                    bounds = None
                    if isinstance(result, dict):
                        bounds = result.get("bounds")
                        eid = result.get("eid", f"{by}::{value}")
                    else:
                        eid = result
                        # Get bounds via find_element_with_bounds (parses both dict + string format)
                        try:
                            r2 = u2.find_element_with_bounds(by, value)
                            bounds = r2.get("bounds") if r2 else None
                        except Exception:
                            pass

                    if bounds:
                        # Sanity check: recorded position must be near element bounds.
                        # If not → selector matched a WRONG element (different screen state).
                        # Skip to ratio fallback.
                        if fallback_rx is not None and fallback_ry is not None:
                            hx = int(fallback_rx * w)
                            hy = int(fallback_ry * h)
                            TOLERANCE = 120  # px
                            wrong_element = not (
                                bounds.get("left", 0) - TOLERANCE <= hx <= bounds.get("right", w) + TOLERANCE
                                and bounds.get("top", 0) - TOLERANCE <= hy <= bounds.get("bottom", h) + TOLERANCE
                            )
                            if wrong_element:
                                log.warning(
                                    f"[{serial}] selector {by}={value!r} bounds {bounds} "
                                    f"don't match recorded position ({hx},{hy}) → ratio fallback"
                                )
                                break  # → ratio fallback below

                            # Element confirmed in expected area → tap at RECORDED position (always).
                            # Never use element center: the recording stores the exact tap point
                            # the user intended; that is more accurate than the element's centroid.
                            log.debug(f"[{serial}] {by}={value!r} OK → tap recorded ({hx},{hy})")
                            device.tap(hx, hy)
                        else:
                            # No recorded position: tap element center as best effort
                            cx = (bounds.get("left", 0) + bounds.get("right", w)) // 2
                            cy = (bounds.get("top", 0) + bounds.get("bottom", h)) // 2
                            device.tap(cx, cy)
                    else:
                        # No bounds from u2 — tap at recorded ratio position.
                        # Never fall through to element_click(): it would re-find the element
                        # and tap its center, which for a large container equals mid-screen.
                        if fallback_rx is not None and fallback_ry is not None:
                            fx = max(0, min(w - 1, int(fallback_rx * w)))
                            fy = max(0, min(h - 1, int(fallback_ry * h)))
                            log.debug(f"[{serial}] no bounds for {by}={value!r} → ratio ({fx},{fy})")
                            device.tap(fx, fy)
                        else:
                            u2.element_click(eid)
                    return True, f"selector {by}={value!r} tapped (attempt {attempt + 1})"
                except Exception as exc:
                    log.warning(f"[{serial}] tap click err (attempt {attempt + 1}): {exc}")
            else:
                log.warning(f"[{serial}] selector {by}={value!r} not found (attempt {attempt + 1}/{retries})")

    # Fallback: ratio tap
    if fallback_rx is not None and fallback_ry is not None:
        fx = max(0, min(w - 1, int(fallback_rx * w)))
        fy = max(0, min(h - 1, int(fallback_ry * h)))
        if by and value:
            log.warning(f"[{serial}] selector not found → fallback ratio ({fallback_rx:.3f},{fallback_ry:.3f})")
        try:
            device.tap(fx, fy)
            time.sleep(0.3)  # brief buffer for app to react before next step
            return True, f"fallback ratio ({fallback_rx:.3f},{fallback_ry:.3f})"
        except Exception as exc:
            return False, f"fallback tap failed: {exc}"

    return False, f"selector {by}={value!r} not found, no fallback"


def run_scenario_task(device: "DeviceClient", scenario: Dict[str, Any]) -> Dict[str, Any]:
    """
    Thực thi 1 scenario JSON trên 1 device.

    Đây là lớp "thực thi" thuần deterministic. AI/MCP chỉ cần sinh ra `scenario`
    đúng schema; mọi thao tác cụ thể đều do code này handle.
    """
    serial = device.serial
    steps: List[ScenarioStep] = scenario.get("steps", []) or []  # type: ignore[assignment]
    log.info(f"[{serial}] run_scenario_task: {len(steps)} steps")

    w = device.screen_width or 1080
    h = device.screen_height or 1920

    step_results: List[Dict[str, Any]] = []
    # Rate-limit popup checks: at most once every 5 seconds.
    # _auto_dismiss_popup dumps the full XML hierarchy — expensive (0.5-1.5s network call).
    # Popups don't appear on every single tap, so checking every 5s is protective enough.
    _last_popup_t: float = 0.0

    for idx, step in enumerate(steps):
        t = step.get("type")
        log.info(f"[{serial}] step#{idx + 1}: {t} {step}")
        step_result: Dict[str, Any] = {"index": idx, "type": t, "ok": True}

        if t == "launch_app":
            pkg = str(step.get("package") or "")
            if not pkg:
                msg = "launch_app: empty package"
                log.warning(f"[{serial}] {msg}")
                step_result["ok"] = False
                step_result["message"] = msg
            else:
                try:
                    device.launch_app(pkg)
                    # Fixed wait — app startup is variable; scenario should include an
                    # explicit wait_element step after launch_app for reliable sync.
                    launch_wait = float(step.get("wait_after", 2.0) or 2.0)
                    time.sleep(launch_wait)
                    log.info(f"[{serial}] launch_app {pkg}: waited {launch_wait}s")
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
                time.sleep(secs)

        elif t == "tap":
            # Full pipeline:
            # dismiss_popup? → wait_stable → wait_for_selector → tap_random_in_bounds → wait_ui_change
            selector    = step.get("selector") or {}
            fallback    = step.get("fallback") or {}
            screen_ctx  = step.get("screen") or {}
            sel_by      = str(selector.get("by") or "") or None
            sel_value   = str(selector.get("value") or "").strip() or None
            fallback_rx = fallback.get("rx")
            fallback_ry = fallback.get("ry")
            tap_timeout = float(step.get("timeout", 8.0) or 8.0)
            wait_after  = bool(step.get("wait_after", True))

            # Skip container class selectors upfront — avoid useless pre_hash fetch
            has_real_selector = (
                sel_by and sel_value
                and not (sel_by == "class name" and sel_value in _CONTAINER_CLASSES)
            )

            # Layer 1: auto-dismiss popup — rate-limited to once every 5s.
            # Dumping XML hierarchy is expensive (0.5-1.5s); popups don't appear on every tap.
            now_t = time.monotonic()
            if now_t - _last_popup_t >= 5.0:
                dismissed = _auto_dismiss_popup(device)
                _last_popup_t = time.monotonic()
                if dismissed:
                    step_result["popup_dismissed"] = True

            ok, msg = _execute_tap(
                device,
                by=sel_by,
                value=sel_value,
                fallback_rx=fallback_rx,
                fallback_ry=fallback_ry,
                timeout=tap_timeout,
                retries=1,
            )
            step_result["ok"] = ok
            if msg:
                step_result["message"] = msg
            if screen_ctx:
                step_result["screen_context"] = screen_ctx

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
            # Rate-limited popup check
            now_t = time.monotonic()
            if now_t - _last_popup_t >= 5.0:
                _auto_dismiss_popup(device)
                _last_popup_t = time.monotonic()
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
                # Rate-limited popup check (max once per 5s)
                now_t = time.monotonic()
                if now_t - _last_popup_t >= 5.0:
                    dismissed = _auto_dismiss_popup(device)
                    _last_popup_t = time.monotonic()
                    if dismissed:
                        step_result["popup_dismissed"] = True

                ok, msg = _execute_tap(
                    device, by=by, value=value,
                    fallback_rx=fallback_rx, fallback_ry=fallback_ry,
                    timeout=sel_timeout, retries=1,
                )
                step_result["ok"] = ok
                if msg:
                    step_result["message"] = msg
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
                eid = _wait_for_element(u2, by, value, timeout=timeout) if u2 else None
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
                eid = _wait_for_element(u2, by, value, timeout=timeout) if u2 else None
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
                    eid = u2.find_element(by, value)
                    if eid is None:
                        raise RuntimeError(f"element not found {by}={value!r}")
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
                    # Get element bounds, then long-tap at center
                    selector = u2._build_selector(by, value)
                    info = u2._rpc("objInfo", selector)
                    if not info:
                        raise RuntimeError(f"element not found {by}={value!r}")
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
            elif via == "u2":
                d = device.u2  # per-step: dùng client mới sau reconnect
                if d is None:
                    device.ensure_u2_healthy()
                    d = device.u2
                if d is None:
                    msg = "input_text via=u2 but u2 client not available"
                    log.warning(f"[{serial}] {msg}")
                    step_result["ok"] = False
                    step_result["message"] = msg
                else:
                    try:
                        d.send_keys(text)  # type: ignore[union-attr]
                    except Exception as exc:
                        # Fallback 1: tap vùng search rồi thử send_keys lại
                        log.warning(f"[{serial}] u2 send_keys failed: {exc}, trying tap_ratio + retry")
                        u2_ok = False
                        try:
                            tx = max(0, min(w - 1, int(0.5 * w)))
                            ty = max(0, min(h - 1, int(0.2 * h)))
                            device.tap(tx, ty)
                            time.sleep(1.0)
                            d2 = device.u2
                            if d2 is not None:
                                d2.send_keys(text)  # type: ignore[union-attr]
                                u2_ok = True
                        except Exception as retry_exc:
                            log.warning(f"[{serial}] u2 send_keys retry failed: {retry_exc}")
                        if not u2_ok:
                            # Fallback 2: adb input text (gửi keyevent vào focus — hoạt động với WebView/Chrome)
                            try:
                                escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
                                device.shell(f'input text "{escaped}"')
                                time.sleep(0.3)
                                step_result["ok"] = True
                                step_result["message"] = "input_text via shell (u2 NPE fallback)"
                            except Exception as shell_exc:
                                msg = f"u2 send_keys({text!r}) failed, shell fallback failed: {shell_exc}"
                                log.warning(f"[{serial}] {msg}")
                                step_result["ok"] = False
                                step_result["message"] = msg
            elif via == "a11y_key":
                # Chỗ này tuỳ bạn sau này nối vào IME riêng / input text khác.
                msg = "input_text via=a11y_key not implemented"
                log.warning(f"[{serial}] {msg}")
                step_result["ok"] = False
                step_result["message"] = msg
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

        elif t == "scroll_down":
            try:
                repeats = int(step.get("repeats", 1) or 1)
            except Exception:
                repeats = 1
            sx = w // 2
            sy1 = int(h * 0.8)
            sy2 = int(h * 0.2)
            failed = False
            for i in range(max(1, repeats)):
                log.info(f"[{serial}] scroll swipe #{i + 1}: ({sx},{sy1})→({sx},{sy2})")
                try:
                    device.swipe(sx, sy1, sx, sy2, duration_ms=600)
                except Exception as exc:
                    msg = f"swipe scroll #{i + 1} failed: {exc}"
                    log.warning(f"[{serial}] {msg}")
                    step_result["ok"] = False
                    step_result["message"] = msg
                    failed = True
                    break
                time.sleep(0.8)
            if not failed:
                step_result["ok"] = True

        elif t == "wait_stable":
            # stable_duration: how long UI must be unchanged (default 0.4s)
            ws_timeout = float(step.get("timeout", 5.0) or 5.0)
            ws_stable = float(step.get("stable_duration", 0.4) or 0.4)
            stable = _wait_screen_stable(device, timeout=ws_timeout, stable_duration=ws_stable)
            step_result["ok"] = True
            step_result["message"] = f"wait_stable: {'stable' if stable else 'timed_out'}"

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

        else:
            msg = f"unknown step type: {t!r}"
            log.warning(f"[{serial}] {msg}")
            step_result["ok"] = False
            step_result["message"] = msg

        step_results.append(step_result)

    all_ok = all(r.get("ok", True) for r in step_results)
    failed_steps = [r for r in step_results if not r.get("ok", True)]
    first_fail_msg = failed_steps[0].get("message", "step failed") if failed_steps else ""

    return {
        "serial": serial,
        "success": all_ok,
        "steps_executed": len(steps),
        "step_results": step_results,
        "failed_message": first_fail_msg if not all_ok else None,
    }


def make_scenario_task(scenario: Dict[str, Any]):
    """
    Factory trả về hàm task(device) để dùng với TaskQueue.
    """

    def _task(device: "DeviceClient") -> Dict[str, Any]:
        return run_scenario_task(device, scenario)

    _task.__name__ = "run_scenario"
    return _task

