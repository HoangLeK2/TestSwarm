"""tasks/scenario/utils.py — Helper functions for scenario step execution.

Extracted from scenario_task.py to break circular imports.
All step modules import from here instead of from scenario_task.
"""
from __future__ import annotations

import base64
import concurrent.futures
import io
import json
import logging
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple, TYPE_CHECKING


if TYPE_CHECKING:
    from runtime.core.device_client import DeviceClient
    from common.variable_resolver import VariableContext

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

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

_HASH_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="hash_xml")

_POPUP_DISMISS_PATTERNS: Sequence[Tuple[str, str]] = (
    ("resource-id", "com.android.permissioncontroller:id/permission_allow_button"),
    ("resource-id", "com.android.packageinstaller:id/permission_allow_button"),
    ("resource-id", "android:id/button1"),
    ("text", "ALLOW"),   ("text", "Allow"),   ("text", "Allow all"),
    ("text", "Allow only while using the app"),
    ("text", "Cho phép"), ("text", "Đồng ý"), ("text", "OK"), ("text", "Xác nhận"),
    ("text", "Bỏ qua"), ("text", "BỎ QUA"), ("text", "Skip"),    ("text", "Not now"), ("text", "Later"),
    ("text", "No thanks"), ("text", "Không, cảm ơn"),
    # Vietnamese "maybe later" wording. Facebook uses these on the popups it
    # stacks right after a login; every entry here is matched as an exact text
    # attribute, never as a substring, so a short label cannot land inside a
    # person's name.
    ("text", "Để sau"), ("text", "Chưa phải bây giờ"),
    ("text", "Không phải bây giờ"), ("text", "Lúc khác"),
    ("text", "Dismiss"),  ("text", "Close"),  ("text", "Got it"),  ("text", "Understood"),
    ("text", "Continue"), ("text", "Tiếp tục"),
    ("text", "Đóng"),
    ("content-desc", "Close"), ("content-desc", "Dismiss"), ("content-desc", "Đóng"),
)

_VOLATILE_ATTRS = re.compile(
    r'\s+(?:index|bounds|focused|selected|drawing-order|rotation)="[^"]*"'
)

_IW_DEFAULT_TIMEOUT = 3.0
_IW_DEFAULT_POLL = 0.25
_IW_MAX_TIMEOUT = 60.0


# ── XML / hierarchy helpers ───────────────────────────────────────────────────

def _normalize_xml(xml: str) -> str:
    """Strip volatile attributes so hash is stable across dumps."""
    return _VOLATILE_ATTRS.sub("", xml)


def _hash_hierarchy(device: "DeviceClient") -> Optional[int]:
    """Get current UI hierarchy hash (normalized). 1.5s timeout guard."""
    try:
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


def _xml_has_element(xml: str, by: str, value: str) -> bool:
    """Check if XML hierarchy contains an element matching (by, value)."""
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


_VOLATILE_SELECTOR_BY = frozenset({
    "xpath",
    "class name",
    "classname",
    "textcontains",
    "textstartswith",
    "textmatches",
    "descriptioncontains",
    "descriptionstartswith",
    "content-desc-contains",
    "content_desc_contains",
    "content-desc-starts-with",
    "content_desc_starts_with",
})

_COMMON_ACTION_TEXTS = frozenset({
    "add",
    "allow",
    "cancel",
    "close",
    "continue",
    "dismiss",
    "follow",
    "following",
    "join",
    "joined",
    "like",
    "message",
    "next",
    "ok",
    "open",
    "save",
    "share",
    "skip",
    "tham gia",
    "theo dõi",
    "tiếp tục",
})


def _selector_primary_by_value(
    by: Optional[str],
    value: Optional[str],
    spec: Optional[Any],
) -> Tuple[str, str]:
    if spec is not None:
        xpath = str(getattr(spec, "xpath", "") or "").strip()
        if xpath:
            return "xpath", xpath
        spec_by = str(getattr(spec, "by", "") or "").strip()
        spec_value = str(getattr(spec, "value", "") or "").strip()
        if spec_by and spec_value:
            return spec_by, spec_value
    return str(by or "").strip(), str(value or "").strip()


def _selector_is_volatile(
    by: Optional[str],
    value: Optional[str],
    spec: Optional[Any] = None,
) -> bool:
    sel_by, sel_value = _selector_primary_by_value(by, value, spec)
    norm_by = sel_by.replace("_", "-").strip().lower()
    if norm_by in _VOLATILE_SELECTOR_BY:
        return True
    if norm_by == "xpath" and "@bounds=" in sel_value:
        return True
    if norm_by == "text" and sel_value.strip().lower() in _COMMON_ACTION_TEXTS:
        return True
    conditions = getattr(spec, "conditions", {}) if spec is not None else {}
    if isinstance(conditions, dict) and conditions.get("volatile") is True:
        return True
    return False


def _selector_fallback_wait_timeout(
    by: Optional[str],
    value: Optional[str],
    fallback_rx: Optional[float],
    fallback_ry: Optional[float],
    implicit_wait_timeout: float,
) -> float:
    """Shorten wait for known high-churn metadata selectors with explicit fallback."""
    if fallback_rx is None or fallback_ry is None:
        return implicit_wait_timeout
    norm_by = str(by or "").replace("_", "-").strip().lower()
    if norm_by not in {"description", "content-desc", "accessibility id", "text"}:
        return implicit_wait_timeout
    lowered = str(value or "").strip().lower()
    high_churn_group_metadata = (
        ("công khai" in lowered or "public" in lowered)
        and (
            "thành viên" in lowered
            or "member" in lowered
            or "bài viết/ngày" in lowered
            or "posts/day" in lowered
        )
    )
    if high_churn_group_metadata:
        return min(implicit_wait_timeout, 0.35)
    return implicit_wait_timeout


def _node_matches_selector(node: Any, by: str, value: str) -> bool:
    if by == "text":
        return (node.get("text") or "") == value
    if by in ("resource-id", "id", "resourceId"):
        return (node.get("resource-id") or "") == value
    if by in ("description", "content-desc", "accessibility id"):
        return (node.get("content-desc") or "") == value
    if by == "descriptionContains":
        return value in (node.get("content-desc") or "")
    if by in ("descriptionStartsWith", "descriptionStartswith"):
        return (node.get("content-desc") or "").startswith(value)
    if by in ("class name", "className"):
        return (node.get("class") or "") == value
    if by in ("package", "packageName"):
        return (node.get("package") or "") == value
    return False


def _current_selector_match_count(
    device: "DeviceClient",
    by: Optional[str],
    value: Optional[str],
    spec: Optional[Any] = None,
) -> int:
    sel_by, sel_value = _selector_primary_by_value(by, value, spec)
    if not sel_by or not sel_value or _selector_is_volatile(sel_by, sel_value, spec):
        return 0
    try:
        xml = device.hierarchy_xml(force_refresh=True)
        if not xml:
            return 0
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml)
    except Exception:
        return 0
    return sum(1 for node in root.iter() if _node_matches_selector(node, sel_by, sel_value))


# ── Element find helpers ──────────────────────────────────────────────────────

def _wait_for_element(
    u2,
    by: str,
    value: str,
    timeout: float = 8.0,
    poll: float = 0.3,
    cancel_event: Optional[threading.Event] = None,
) -> Optional[Any]:
    """
    Wait until element appears (up to `timeout` seconds).

    Non-xpath: polls in short chunks so cooperative cancel can stop quickly.
    xpath: polls via find_element every `poll`s.
    """
    if u2 is None:
        return None

    deadline = time.monotonic() + timeout
    probe_timeout = min(max(0.1, poll), 1.0)

    def _cancelled() -> bool:
        return cancel_event is not None and cancel_event.is_set()

    def _wait_gap() -> None:
        gap = min(poll, max(0.0, deadline - time.monotonic()))
        if gap <= 0:
            return
        if cancel_event is not None:
            cancel_event.wait(gap)
        else:
            time.sleep(gap)

    if by != "xpath":
        while time.monotonic() < deadline:
            if _cancelled():
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            chunk = min(probe_timeout, remaining)
            try:
                eid = u2.find_element(by, value, timeout=max(0.1, chunk))
                if eid is None:
                    _wait_gap()
                    continue
                if hasattr(u2, "find_element_with_bounds"):
                    try:
                        result = u2.find_element_with_bounds(by, value)
                        if result:
                            return result
                    except Exception as exc:
                        log.debug("find_element_with_bounds failed (%s=%r): %s", by, value, exc)
                return eid
            except Exception as exc:
                log.debug("_wait_for_element %s=%r error: %s", by, value, exc)
                return None
        return None

    consecutive_errors = 0
    MAX_CONSECUTIVE_ERRORS = 3
    while time.monotonic() < deadline:
        if _cancelled():
            return None
        try:
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
        _wait_gap()
    return None


def _retry_find_element(
    u2,
    by: Optional[str] = None,
    value: Optional[str] = None,
    timeout: float = 10.0,
    poll: float = 0.5,
    cancel_event: Optional["threading.Event"] = None,
    *,
    spec: Optional[Any] = None,
    device: Optional["DeviceClient"] = None,
) -> Optional[Any]:
    """Find element with a polling retry loop. Returns element id/dict or None.

    Accepts legacy ``by``/``value`` or a ``ScenarioSelectorSpec`` via ``spec``.
    Chain selectors route through agent-boot batch when available.
    """
    from services.scenario_selector import (
        ScenarioSelectorSpec,
        compile_chain_to_xpath,
        spec_eid,
        spec_has_chain,
        spec_to_agent_payload,
    )

    if spec is None and by and value:
        spec = ScenarioSelectorSpec(by=str(by), value=str(value))
    if u2 is None or spec is None or spec.is_empty():
        return None

    deadline = time.monotonic() + max(0.0, float(timeout))
    probe_timeout = min(0.5, max(0.05, float(poll)))
    summary = f"{spec.by}={spec.value!r}"

    def _probe() -> Optional[Any]:
        try:
            if spec_has_chain(spec):
                if device is not None and device._batch_enabled():
                    payload = spec_to_agent_payload(spec)
                    results = device.u2_batch(
                        [{"op": "exists_spec", "spec": payload, "timeout": probe_timeout}],
                        timeout=probe_timeout + 10.0,
                    )
                    if results and results[0]:
                        return {"eid": spec_eid(spec), "bounds": None}
                elif device is not None and not device._batch_enabled():
                    log.warning(
                        "chain selector %s requires agent-boot batch; trying xpath/json-rpc fallback",
                        summary,
                    )
                if hasattr(u2, "find_element_spec"):
                    eid = u2.find_element_spec(spec, timeout=probe_timeout)
                    if eid is not None:
                        return eid
                return None
            if hasattr(u2, "find_element_with_bounds_spec"):
                try:
                    result = u2.find_element_with_bounds_spec(spec, timeout=probe_timeout)
                    if result:
                        return result
                except Exception:
                    pass
            if hasattr(u2, "find_element_spec"):
                eid = u2.find_element_spec(spec, timeout=probe_timeout)
            else:
                pby, pval = spec.primary_by_value()
                eid = u2.find_element(pby, pval, timeout=probe_timeout)
            if eid is None:
                return None
            elif hasattr(u2, "find_element_with_bounds"):
                pby, pval = spec.primary_by_value()
                try:
                    result = u2.find_element_with_bounds(pby, pval)
                    if result:
                        return result
                except Exception:
                    pass
            return eid
        except Exception as exc:
            log.debug("_retry_find_element %s probe error: %s", summary, exc)
            return None

    while True:
        if cancel_event is not None and cancel_event.is_set():
            log.info("_retry_find_element cancelled by user (%s)", summary)
            return None
        found = _probe()
        if found is not None:
            return found
        if time.monotonic() >= deadline:
            return None
        chunk = min(poll, max(0.0, deadline - time.monotonic()))
        if chunk <= 0:
            return None
        if cancel_event is not None:
            cancel_event.wait(chunk)
        else:
            time.sleep(chunk)


def resolve_step_selector_fields(
    step: Dict[str, Any],
) -> Tuple[Optional[Any], Optional[str], Optional[str], Tuple[Optional[float], Optional[float]]]:
    """Return (spec, by, value, (fallback_rx, fallback_ry)) from a scenario step."""
    from services.scenario_selector import normalize_step_selector, get_step_fallback

    spec = normalize_step_selector(step)
    fb = get_step_fallback(step)
    if spec is None or spec.is_empty():
        return None, None, None, fb
    by, value = spec.primary_by_value()
    return spec, by, value, fb


# ── Implicit wait config ──────────────────────────────────────────────────────

def _get_implicit_wait_config(
    step: Dict[str, Any],
    scenario_config: Dict[str, Any],
) -> Tuple[float, float]:
    """
    Resolve implicit_wait timeout and poll interval.

    Priority: step.implicit_wait > scenario.implicit_wait > defaults (3s / 0.25s).
    Accepts either a number (timeout only) or a dict {timeout, poll}.
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


# ── Image / visual helpers ────────────────────────────────────────────────────

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


# ── Wait helpers ──────────────────────────────────────────────────────────────

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
    if hasattr(u2, "_wait_until_gone"):
        try:
            return u2._wait_until_gone(by, value, timeout)
        except Exception:
            pass
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            eid = u2.find_element(by, value, timeout=0)
            if eid is None:
                return True
        except Exception:
            return True
        time.sleep(poll)
    return False


def _wait_ui_change(
    device: "DeviceClient",
    old_hash: Optional[int],
    timeout: float = 3.0,
    poll: float = 0.3,
) -> bool:
    """Poll until hierarchy hash changes. Returns True if changed, False on timeout."""
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
    cancel_event: Optional[threading.Event] = None,
) -> bool:
    """Wait until UI hierarchy hash stops changing for `stable_duration` seconds."""
    deadline = time.monotonic() + timeout
    last_hash: Optional[int] = None
    stable_since: Optional[float] = None

    while time.monotonic() < deadline:
        if cancel_event is not None and cancel_event.is_set():
            return False
        h = _hash_hierarchy(device)
        now = time.monotonic()
        if h is None:
            return False
        if h == last_hash:
            if stable_since is None:
                stable_since = now
            elif (now - stable_since) >= stable_duration:
                return True
        else:
            last_hash = h
            stable_since = None
        if cancel_event is not None:
            cancel_event.wait(poll)
        else:
            time.sleep(poll)

    return False


# ── Popup / tap helpers ───────────────────────────────────────────────────────

def _auto_dismiss_popup(device: "DeviceClient") -> bool:
    """Check for common popup/dialog patterns and dismiss the first one found."""
    u2 = device.u2
    if u2 is None:
        return False

    # Must be a fresh dump. The cache is 2s and popups queue about a second
    # apart, so a cached dump answers "is a popup on screen" for a screen that
    # is already gone: the stale XML still lists the label, find_element below
    # returns None because it was dismissed, the scan falls through every
    # pattern and reports "no popup" while the next one is on screen.
    xml = device.hierarchy_xml(force_refresh=True)
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
            eid = u2.find_element(by, value, timeout=0)
            if eid is not None:
                u2.element_click(eid)
                # Clicking through the raw u2 handle skips DeviceClient.tap*,
                # which is what normally drops the cache. Without this every
                # later reader — wait_stable's hash, the readiness gate — keeps
                # scoring the pre-dismiss screen for up to 2s.
                device.hierarchy_invalidate_cache()
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
    """Tap the best position inside element bounds (recorded position or center)."""
    w = device.screen_width or 1080
    h = device.screen_height or 1920
    left   = bounds.get("left", 0)
    top    = bounds.get("top", 0)
    right  = bounds.get("right", w)
    bottom = bounds.get("bottom", h)

    if hint_rx is not None and hint_ry is not None:
        hx = int(hint_rx * w)
        hy = int(hint_ry * h)
        if left <= hx <= right and top <= hy <= bottom:
            device.tap(hx, hy)
            return

    cx = (left + right) // 2
    cy = (top + bottom) // 2
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
    spec: Optional[Any] = None,
    cancel_event: Optional[threading.Event] = None,
) -> Tuple[bool, str, Optional[Dict[str, int]]]:
    """
    Full tap pipeline: selector → image match (ROI→full) → position fallback.

    Returns (ok, message, bounds_or_none).
    """
    from runtime.element_resolver import (
        ElementResolver, phase_selector, phase_image, phase_ratio, phase_healing,
        phase_text_normalized,
    )
    from services.scenario_selector import (
        ScenarioSelectorSpec,
        normalize_step_selector,
        selector_summary,
        spec_has_chain,
        spec_to_agent_payload,
    )

    serial = device.serial
    w = device.screen_width or 1080
    h = device.screen_height or 1920
    u2 = device.u2

    if cancel_event is not None and cancel_event.is_set():
        return False, "cancelled", None

    if spec is None and by and value:
        spec = ScenarioSelectorSpec(by=str(by), value=str(value))

    if spec and spec_has_chain(spec) and device._batch_enabled():
        try:
            flow_result = device._u2_batch.flow(
                "wait_and_click_spec",
                {
                    "spec": spec_to_agent_payload(spec),
                    "wait_timeout": min(float(timeout), 60.0),
                },
                timeout=float(timeout) + 15.0,
            )
            if flow_result.get("clicked"):
                bounds = flow_result.get("bounds")
                if isinstance(bounds, dict):
                    pass
                elif isinstance(bounds, str):
                    nums = [int(n) for n in re.findall(r"-?\d+", bounds)]
                    if len(nums) == 4:
                        bounds = {"left": nums[0], "top": nums[1], "right": nums[2], "bottom": nums[3]}
                    else:
                        bounds = None
                else:
                    bounds = None
                return True, f"chain selector {selector_summary(spec)}", bounds
        except Exception as exc:
            log.warning("[%s] wait_and_click_spec failed: %s", serial, exc)

    effective_by = spec.by if spec else by
    effective_value = spec.value if spec else value
    if effective_by == "class name" and effective_value in _CONTAINER_CLASSES:
        log.debug(f"[{serial}] selector class={effective_value!r} is container — skip to fallback")
        effective_by = None
        effective_value = None
        spec = None

    phases = []

    has_selector = bool(u2 and spec and not spec.is_empty()) or bool(u2 and effective_by and effective_value)
    selector_volatile = _selector_is_volatile(effective_by, effective_value, spec) if has_selector else False
    allow_moved_selector = (
        has_selector
        and not selector_volatile
        and _current_selector_match_count(device, effective_by, effective_value, spec) == 1
    )
    use_selector_phase = has_selector and not selector_volatile
    selector_wait_timeout = _selector_fallback_wait_timeout(
        effective_by,
        effective_value,
        fallback_rx,
        fallback_ry,
        implicit_wait_timeout,
    )
    if use_selector_phase and spec:
        def _phase_spec():
            return phase_selector(
                u2, effective_by, effective_value,
                fallback_rx, fallback_ry,
                selector_wait_timeout, implicit_wait_poll,
                w, h,
                find_fn=lambda u, b, v, timeout=10.0, poll=0.5, cancel_event=None, _ce=cancel_event, **kw: _retry_find_element(
                    u, timeout=timeout, poll=poll, cancel_event=cancel_event or _ce, spec=spec, device=device,
                ),
                allow_moved_selector=allow_moved_selector,
            )
        phases.append(_phase_spec)
    elif use_selector_phase:
        phases.append(lambda: phase_selector(
            u2, effective_by, effective_value,
            fallback_rx, fallback_ry,
            selector_wait_timeout, implicit_wait_poll,
            w, h,
            find_fn=lambda u, b, v, timeout=10.0, poll=0.5, cancel_event=None, _ce=cancel_event, **kw: _retry_find_element(
                u, b, v, timeout=timeout, poll=poll, cancel_event=cancel_event or _ce, device=device,
            ),
            allow_moved_selector=allow_moved_selector,
        ))

    # Whitespace-tolerant rescue before healing: a NBSP on either side makes
    # UiSelector miss and burn the full implicit wait for nothing.
    if use_selector_phase and effective_by and effective_value:
        phases.append(lambda: phase_text_normalized(
            device, effective_by, effective_value, w, h,
        ))

    if (
        has_selector
        and not selector_volatile
        and fallback_rx is not None
        and fallback_ry is not None
    ):
        phases.append(lambda: phase_healing(
            u2, device, effective_by, effective_value,
            fallback_rx, fallback_ry, w, h,
            implicit_wait_timeout=3.0,
        ))

    if element_image is not None:
        phases.append(lambda: phase_image(
            device, element_image, image_threshold, w, h,
            screenshot_anchor=screenshot_anchor,
        ))

    if (
        fallback_rx is not None
        and fallback_ry is not None
        and not selector_volatile
    ):
        phases.append(lambda: phase_ratio(
            device, fallback_rx, fallback_ry, w, h,
            selector_tried=has_selector,
        ))

    resolver = ElementResolver(phases=phases)
    if cancel_event is not None and cancel_event.is_set():
        return False, "cancelled", None
    result = resolver.resolve()

    # F1.6 — if resolver missed AND the selector was real, force a fresh
    # hierarchy dump and retry once. Handles the case where FB re-rendered
    # between capture and tap, so the previous cached tree no longer has the
    # target. Cheap (~200ms per retry), only fires on miss.
    if not result.hit and has_selector:
        if cancel_event is not None and cancel_event.is_set():
            return False, "cancelled", None
        try:
            device.hierarchy_xml(force_refresh=True)
        except Exception as exc:
            log.debug(f"[{serial}] tap-retry force_refresh failed: {exc}")
        if cancel_event is not None and cancel_event.is_set():
            return False, "cancelled", None
        result = resolver.resolve()
        if result.hit:
            log.info(f"[{serial}] tap: recovered after hierarchy refresh")

    if not result.hit:
        if cancel_event is not None and cancel_event.is_set():
            return False, "cancelled", None
        lbl = selector_summary(spec) if spec else f"{by}={value!r}"
        return False, f"selector {lbl} not found, no fallback position", None

    if result.x == -1 and result.y == -1:
        try:
            eid_result = _retry_find_element(
                u2, effective_by, effective_value, timeout=1.0, poll=0.3,
                cancel_event=cancel_event, spec=spec, device=device,
            )
            if eid_result is not None:
                from services.scenario_selector import spec_eid
                eid = eid_result.get("eid", spec_eid(spec) if spec else f"{effective_by}::{effective_value}") if isinstance(eid_result, dict) else eid_result
                u2.element_click(eid)
            else:
                lbl = selector_summary(spec) if spec else f"{by}={value!r}"
                return False, f"selector {lbl} lost before click", None
        except Exception as exc:
            return False, f"element_click failed: {exc}", None
    else:
        try:
            device.tap(result.x, result.y)
        except Exception as exc:
            return False, f"tap ({result.x},{result.y}) failed: {exc}", None

    if result.method == "fallback_position":
        if cancel_event is not None:
            cancel_event.wait(0.3)
        else:
            time.sleep(0.3)

    details = [result.message, f"method={result.method}"]
    if result.x >= 0 and result.y >= 0:
        details.append(f"tap=({result.x},{result.y})")
    if result.bounds:
        left = result.bounds.get("left")
        top = result.bounds.get("top")
        right = result.bounds.get("right")
        bottom = result.bounds.get("bottom")
        details.append(f"bounds=[{left},{top}][{right},{bottom}]")

    return True, " ".join(details), result.bounds


# ── Condition evaluators ──────────────────────────────────────────────────────

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
        return _xml_has_element(xml, by, value)

    elif ctype == "element_not_exists":
        return not _evaluate_condition(device, {**condition, "type": "element_exists"}, ctx)

    elif ctype == "posts_count_gte":
        count = int(condition.get("count", 0))
        return len(ctx.get("posts", [])) >= count

    elif ctype == "posts_count_lt":
        count = int(condition.get("count", 0))
        return len(ctx.get("posts", [])) < count

    elif ctype == "no_new_posts":
        threshold = int(condition.get("threshold", 3))
        posts_streak = int(ctx.get("_no_new_posts_streak", 0) or 0)
        legacy_streak = int(ctx.get("_no_new_streak", 0) or 0)
        return max(posts_streak, legacy_streak) >= threshold

    elif ctype == "variable_equals" or "variable_equals" in condition:
        spec = condition.get("variable_equals") or condition
        name = str(spec.get("name") or "").strip()
        if not name:
            return False
        variables = ctx.get("vars") if isinstance(ctx.get("vars"), dict) else {}
        actual = variables.get(name, ctx.get(name))
        expected = spec.get("value")
        if isinstance(expected, bool):
            if isinstance(actual, str):
                actual = actual.strip().casefold() in {"1", "true", "yes", "on"}
            return actual is expected
        return str(actual) == str(expected)

    return False


def _eval_ru_condition(
    device: "DeviceClient",
    condition: Dict[str, Any],
    var_ctx: "VariableContext",
) -> bool:
    """
    Evaluate a repeat_until stop condition (DF-002 format).

    Returns True when the loop SHOULD STOP (condition satisfied).
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
        expected = str(var_ctx.resolve(spec.get("value", ""), step_index=0))
        actual = str(var_ctx.resolve(f"${{{name}}}", step_index=0))
        return actual == expected

    log.warning("repeat_until: unknown condition keys: %r", list(condition.keys()))
    return False


# ── Screenshot capture ────────────────────────────────────────────────────────

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
    session_name = os.path.basename(capture_dir)
    minio_prefix = f"captures/{session_name}"

    full_local = os.path.join(capture_dir, f"{prefix}_full.jpg")
    full_key = f"{minio_prefix}/{prefix}_full.jpg"
    full_url = capture_store.save_capture(jpeg, full_local, full_key, "image/jpeg", skip_quality=True)
    if not full_url:
        return {}
    result: Dict[str, Any] = {"full": full_url}

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


# ── Exception ─────────────────────────────────────────────────────────────────

class ScenarioCancelled(Exception):
    """Raised when scenario is cancelled via cancel_event."""
    pass
