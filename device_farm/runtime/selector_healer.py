"""
selector_healer.py — Self-healing selectors (Phase 2).

After a successful image-match tap (meaning L1 selector FAILED but L2 image
found the element), scan the XML hierarchy at the tapped coordinates to
discover a new, working selector. This updated selector can be persisted
back to the scenario for future runs.

Design:
  - Feature-flagged OFF by default (HEALING_ENABLED = False)
  - Runs AFTER a successful tap (non-blocking to the step pipeline)
  - Only on activity side (Temporal-safe — no workflow I/O)
  - Idempotent: same image match on same screen → same XML → same selector
  - No LLM calls in the hot path

Selector priority (most stable first):
  1. resource-id containing "id/" (app-defined, survives across sessions)
  2. content-desc (accessibility label, relatively stable)
  3. text (visible text, may change with locale/A-B tests)

Usage:
    from runtime.selector_healer import try_heal_selector, HEALING_ENABLED
    if HEALING_ENABLED and step_result.method == "image_match":
        new_sel = try_heal_selector(device, step, tapped_bounds)
        if new_sel:
            await persist_healed_selector(campaign_id, step_id, new_sel)
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from runtime.xml_utils import parse_xml, XML_PARSE_ERRORS

if TYPE_CHECKING:
    from runtime.core.device_client import DeviceClient

log = logging.getLogger(__name__)

# Feature flag — controlled via DEVICE_FARM_HEALING_ENABLED=1 env var.
def _read_healing_flag() -> bool:
    from core.env import healing_enabled
    return healing_enabled()

HEALING_ENABLED: bool = _read_healing_flag()

# Bounds format: [left,top][right,bottom]
_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")

# Resource IDs that are auto-generated or useless for healing
_IGNORE_RID_PATTERNS = frozenset({
    "android:id/content",
    "android:id/statusBarBackground",
    "android:id/navigationBarBackground",
})

# Container classes — too generic to be useful selectors
_CONTAINER_CLASSES = frozenset({
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


def _parse_bounds(bounds_str: str) -> Optional[tuple[int, int, int, int]]:
    """Parse Android bounds string '[left,top][right,bottom]' → (l, t, r, b)."""
    m = _BOUNDS_RE.match(bounds_str)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))


def _bounds_overlap(
    node_bounds: tuple[int, int, int, int],
    tap_bounds: Dict[str, int],
    tolerance: int = 30,
) -> bool:
    """Check if node bounds overlap with tapped area (expanded by tolerance)."""
    nl, nt, nr, nb = node_bounds
    # Expand the tap area by tolerance in all directions before comparing
    tap_left_exp = tap_bounds.get("left", 0) - tolerance
    tap_top_exp = tap_bounds.get("top", 0) - tolerance
    tap_right_exp = tap_bounds.get("right", 0) + tolerance
    tap_bottom_exp = tap_bounds.get("bottom", 0) + tolerance
    # Standard AABB non-overlap test on the expanded rect
    return not (nr < tap_left_exp or nl > tap_right_exp
                or nb < tap_top_exp or nt > tap_bottom_exp)


def _score_selector(by: str, value: str, node_class: str) -> int:
    """
    Score a candidate selector. Higher = more stable across app updates.

    resource-id with app package prefix → most stable
    content-desc → stable (accessibility label)
    text (short) → less stable but usable
    """
    if by == "resource-id":
        if "id/" in value and value not in _IGNORE_RID_PATTERNS:
            return 100
        return 20
    if by == "content-desc":
        return 70
    if by == "text":
        # Short text is more likely to be a button label (stable)
        return 50 if len(value) < 30 else 10
    return 0


def try_heal_selector(
    device: "DeviceClient",
    step: Dict[str, Any],
    tapped_bounds: Optional[Dict[str, int]],
) -> Optional[Dict[str, str]]:
    """
    After image-match tap: re-scan XML around tapped_bounds to find a
    new working selector.

    Returns new {"by": ..., "value": ...} if found, None otherwise.
    Does NOT persist — caller decides whether to save.

    Performance: ~2-5ms for XML parse + scan (XML already cached in most cases).
    The force_refresh=True ensures we see the post-tap state.
    """
    if not HEALING_ENABLED:
        return None

    if not tapped_bounds:
        return None

    xml = device.hierarchy_xml(force_refresh=True)
    if not xml:
        return None

    try:
        root = parse_xml(xml)
    except XML_PARSE_ERRORS:
        return None

    best_selector: Optional[Dict[str, str]] = None
    best_score = 0

    for node in root.iter():
        # Parse node bounds
        bounds_str = node.get("bounds", "")
        node_bounds = _parse_bounds(bounds_str)
        if node_bounds is None:
            continue

        # Check overlap with tapped area
        if not _bounds_overlap(node_bounds, tapped_bounds):
            continue

        # Skip container classes
        node_class = node.get("class", "")
        if node_class in _CONTAINER_CLASSES:
            continue

        # Evaluate candidate selectors from this node
        candidates = []

        rid = (node.get("resource-id") or "").strip()
        if rid:
            candidates.append(("resource-id", rid))

        cdesc = (node.get("content-desc") or "").strip()
        if cdesc and len(cdesc) < 100:
            candidates.append(("content-desc", cdesc))

        text = (node.get("text") or "").strip()
        if text and len(text) < 50:
            candidates.append(("text", text))

        for by, value in candidates:
            score = _score_selector(by, value, node_class)
            if score > best_score:
                best_score = score
                best_selector = {"by": by, "value": value}

    if best_selector:
        old_sel = step.get("selector") or {}
        old_desc = f"{old_sel.get('by')}={old_sel.get('value')!r}" if old_sel else "none"
        log.info(
            "[healer] found new selector %s=%r (score=%d) "
            "replacing stale %s",
            best_selector["by"], best_selector["value"],
            best_score, old_desc,
        )

    return best_selector


# ---------------------------------------------------------------------------
# Proactive healing: find alternative selector from XML at recorded position
# ---------------------------------------------------------------------------

def _find_node_at_position(
    root: ET.Element,
    px: int,
    py: int,
    tolerance: int = 30,
) -> Optional[ET.Element]:
    """Return the smallest (most specific) node that contains (px, py)."""
    best_node: Optional[ET.Element] = None
    best_area = float("inf")
    for node in root.iter():
        nb = _parse_bounds(node.get("bounds", ""))
        if nb is None:
            continue
        nl, nt, nr, nbo = nb
        if (nl - tolerance <= px <= nr + tolerance
                and nt - tolerance <= py <= nbo + tolerance):
            area = (nr - nl) * (nbo - nt)
            if area < best_area:
                best_area = area
                best_node = node
    return best_node


def _extract_candidate_selectors(node: ET.Element) -> List[Tuple[str, str]]:
    """Extract all candidate (by, value) pairs from a node, sorted best-first."""
    candidates: List[Tuple[int, str, str]] = []

    rid = (node.get("resource-id") or "").strip()
    if rid and rid not in _IGNORE_RID_PATTERNS:
        candidates.append((_score_selector("resource-id", rid, node.get("class", "")), "resource-id", rid))

    cdesc = (node.get("content-desc") or "").strip()
    if cdesc and len(cdesc) < 100:
        candidates.append((_score_selector("content-desc", cdesc, node.get("class", "")), "content-desc", cdesc))

    text = (node.get("text") or "").strip()
    if text and len(text) < 50:
        candidates.append((_score_selector("text", text, node.get("class", "")), "text", text))

    candidates.sort(key=lambda t: t[0], reverse=True)
    return [(by, val) for _, by, val in candidates]


def try_heal_proactive(
    u2,
    xml: str,
    original_by: str,
    original_value: str,
    fallback_rx: float,
    fallback_ry: float,
    screen_w: int,
    screen_h: int,
    implicit_wait_timeout: float = 3.0,
) -> Optional[Dict[str, str]]:
    """
    Proactive self-healing: when the original selector fails, try to find the
    element at the recorded position (fallback_rx/ry) in the XML hierarchy and
    try alternative selectors on u2.

    Called BEFORE image-match fallback — fast path using cached XML.

    Returns a new working {"by": ..., "value": ...} dict, or None.
    """
    if not HEALING_ENABLED:
        return None

    if not xml or fallback_rx is None or fallback_ry is None:
        return None

    try:
        root = parse_xml(xml)
    except XML_PARSE_ERRORS:
        return None

    px = int(fallback_rx * screen_w)
    py = int(fallback_ry * screen_h)

    # Walk up: try the node at position and its ancestors for a usable selector
    node = _find_node_at_position(root, px, py)
    if node is None:
        log.debug("[healer-proactive] no node at (%d,%d)", px, py)
        return None

    node_class = node.get("class", "")
    if node_class in _CONTAINER_CLASSES:
        log.debug("[healer-proactive] node at (%d,%d) is container %s — skip", px, py, node_class)
        return None

    candidates = _extract_candidate_selectors(node)

    # Skip if candidate is identical to the original (it already failed)
    candidates = [
        (by, val) for by, val in candidates
        if not (by == original_by and val == original_value)
    ]

    if not candidates:
        log.debug("[healer-proactive] no alternative selectors for %s=%r", original_by, original_value)
        return None

    # Try each candidate on u2 with a short timeout
    for by, value in candidates:
        try:
            eid = u2.find_element(by, value, timeout=implicit_wait_timeout)
            if eid is not None:
                log.info(
                    "[healer-proactive] healed %s=%r → %s=%r",
                    original_by, original_value, by, value,
                )
                return {"by": by, "value": value}
        except Exception as exc:
            log.debug("[healer-proactive] candidate %s=%r failed: %s", by, value, exc)

    log.debug(
        "[healer-proactive] all %d candidates failed for %s=%r at (%d,%d)",
        len(candidates), original_by, original_value, px, py,
    )
    return None
