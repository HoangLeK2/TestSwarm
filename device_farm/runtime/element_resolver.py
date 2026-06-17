"""
element_resolver.py — Phased element resolution pipeline for tap steps.

Extracted from _execute_tap() in scenario_task.py to make the tap pipeline
testable, reorderable, and extensible without duplicating behavior.

Pipeline order (same as original _execute_tap):
  Phase 1: Selector (u2 find_element with Tenacity retry)
  Phase 2: Image match (Airtest aircv template matching)
  Phase 3: Ratio fallback (recorded rx/ry × screen dims)

Each phase is a pure "find" operation returning coordinates — the actual
device.tap() call happens in the caller after resolution succeeds.

Performance:
  - Lazy evaluation: phases run sequentially, first hit wins
  - No unnecessary imports (airtest/PIL imported only in image phase)
  - Phases are plain functions wrapped in lambdas — zero class overhead
"""
from __future__ import annotations

import io
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from runtime.core.device_client import DeviceClient

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Resolution result
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ResolveResult:
    """Result of a single resolution phase or the full pipeline."""
    hit: bool
    x: int = 0
    y: int = 0
    confidence: float = 1.0
    bounds: Optional[Dict[str, int]] = None
    method: str = ""           # "selector" | "image_match" | "fallback_position"
    message: str = ""


# Type alias for a resolution phase function
PhaseFunc = Callable[[], Optional[ResolveResult]]


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ElementResolver:
    """
    Ordered pipeline of resolution phases. First successful hit wins.

    Usage:
        resolver = ElementResolver(phases=[
            lambda: phase_selector(u2, by, value, ...),
            lambda: phase_image(device, element_image, ...),
            lambda: phase_ratio(fallback_rx, fallback_ry, w, h),
        ])
        result = resolver.resolve()
        if result.hit:
            device.tap(result.x, result.y)
    """
    phases: List[PhaseFunc] = field(default_factory=list)

    def resolve(self) -> ResolveResult:
        for phase in self.phases:
            try:
                result = phase()
                if result is not None and result.hit:
                    return result
            except Exception as exc:
                log.warning("element_resolver phase error: %s", exc)
        return ResolveResult(hit=False, message="all phases exhausted")


# ---------------------------------------------------------------------------
# Phase 1: Selector (u2 find_element with Tenacity retry)
# ---------------------------------------------------------------------------

def phase_selector(
    u2,
    by: str,
    value: str,
    fallback_rx: Optional[float],
    fallback_ry: Optional[float],
    implicit_wait_timeout: float,
    implicit_wait_poll: float,
    screen_w: int,
    screen_h: int,
    find_fn: Optional[Callable] = None,
) -> Optional[ResolveResult]:
    """
    Find element via uiautomator2 selector with retry-until-visible.

    Args:
        find_fn: Callable(u2, by, value, timeout, poll) → element result or None.
                 Injected by the caller to avoid cross-module coupling.
                 Defaults to u2.find_element if not provided.

    If element is found with bounds AND a recorded hint position (fallback_rx/ry)
    falls inside the bounds (with tolerance), returns the recorded position for
    exact tap replay. Otherwise returns element center.

    Returns None if element not found (triggers next phase).
    """
    if u2 is None or not by or not value:
        return None

    if find_fn is not None:
        result = find_fn(u2, by, value, timeout=implicit_wait_timeout, poll=implicit_wait_poll)
    else:
        # Minimal fallback: single find_element call (no retry)
        try:
            result = u2.find_element(by, value, timeout=implicit_wait_timeout)
        except Exception:
            result = None
    if result is None:
        log.warning("[resolver] selector %s=%r not visible after %.0fs",
                    by, value, implicit_wait_timeout)
        return None

    # Extract bounds and element id
    bounds: Optional[Dict[str, int]] = None
    eid = result
    if isinstance(result, dict):
        bounds = result.get("bounds")
        eid = result.get("eid", f"{by}::{value}")
    else:
        # Try to fetch bounds via objInfo
        try:
            if hasattr(u2, "find_element_with_bounds"):
                r2 = u2.find_element_with_bounds(by, value)
                bounds = r2.get("bounds") if r2 else None
        except Exception:
            pass

    w, h = screen_w, screen_h

    # Case A: Have bounds + recorded position → prefer exact replay when inside
    if bounds and fallback_rx is not None and fallback_ry is not None:
        hx = int(fallback_rx * w)
        hy = int(fallback_ry * h)
        # Dynamic tolerance: ~8% of screen diagonal
        tolerance = max(int(max(w, h) * 0.08), 60)
        left = bounds.get("left", 0)
        top = bounds.get("top", 0)
        right = bounds.get("right", w)
        bottom = bounds.get("bottom", h)
        in_bounds = (
            left - tolerance <= hx <= right + tolerance
            and top - tolerance <= hy <= bottom + tolerance
        )
        if in_bounds:
            return ResolveResult(
                hit=True, x=hx, y=hy, bounds=bounds,
                method="selector",
                message=f"selector {by}={value!r} tapped",
            )
        log.info(
            "[resolver] selector %s=%r matched; recorded (%d,%d) outside bounds "
            "%s → tap element center (avoid raw fallback coords)",
            by, value, hx, hy, bounds,
        )

    # Case B: Have bounds → center (also used when recorded point drifted after scroll)
    if bounds:
        cx = (bounds.get("left", 0) + bounds.get("right", w)) // 2
        cy = (bounds.get("top", 0) + bounds.get("bottom", h)) // 2
        return ResolveResult(
            hit=True, x=cx, y=cy, bounds=bounds,
            method="selector",
            message=f"selector {by}={value!r} tapped (center)",
        )

    # Case C: Found element, no bounds, have recorded position
    if fallback_rx is not None and fallback_ry is not None:
        fx = max(0, min(w - 1, int(fallback_rx * w)))
        fy = max(0, min(h - 1, int(fallback_ry * h)))
        return ResolveResult(
            hit=True, x=fx, y=fy,
            method="selector",
            message=f"selector {by}={value!r} found, no bounds → tap position",
        )

    # Case D: Found element, no bounds, no position → element_click fallback
    # Return a special result; caller should use u2.element_click(eid)
    return ResolveResult(
        hit=True, x=-1, y=-1,  # signal: use element_click
        method="selector",
        message=f"selector {by}={value!r} tapped (element_click)",
        bounds=None,
    )


# ---------------------------------------------------------------------------
# Phase 2: Image match (Airtest aircv template matching)
# ---------------------------------------------------------------------------

def phase_image(
    device: "DeviceClient",
    element_image: bytes,
    image_threshold: float,
    screen_w: int,
    screen_h: int,
    screenshot_anchor: Optional[Dict[str, Any]] = None,
) -> Optional[ResolveResult]:
    """
    Find element via Airtest template matching on current screenshot.

    Performance optimizations:
    - If screenshot_anchor.region is provided, crops search area (ROI) before
      running template match → 3-5× faster for small elements on large screens.
    - Uses CV semaphore (in visual_anchor) to bound concurrent CPU usage.

    Returns None if no match above threshold.
    """
    from runtime.visual_anchor import find_element_center_by_image

    screen_jpeg = device.take_screenshot()
    if not screen_jpeg:
        return None

    # Try ROI-optimized match first if screenshot_anchor is available
    if screenshot_anchor and screenshot_anchor.get("region"):
        roi_result = _try_roi_match(
            element_image, screen_jpeg, screenshot_anchor,
            image_threshold, screen_w, screen_h,
        )
        if roi_result is not None:
            return roi_result

    # Full-screen template match
    match = find_element_center_by_image(
        element_image, screen_jpeg, threshold=image_threshold,
    )
    if match is None:
        log.debug("[resolver] image match below threshold %.2f", image_threshold)
        return None

    cx, cy, conf = match

    # Scale from screenshot pixel coords to device logical coords
    cx, cy = _scale_to_device(cx, cy, screen_jpeg, screen_w, screen_h)

    dx = max(0, min(screen_w - 1, cx))
    dy = max(0, min(screen_h - 1, cy))

    return ResolveResult(
        hit=True, x=dx, y=dy, confidence=conf,
        bounds=_make_bounds(dx, dy, 50, screen_w, screen_h),
        method="image_match",
        message=f"image match ({conf:.2f}) → tap ({dx},{dy})",
    )


def _try_roi_match(
    element_image: bytes,
    screen_jpeg: bytes,
    screenshot_anchor: Dict[str, Any],
    image_threshold: float,
    screen_w: int,
    screen_h: int,
) -> Optional[ResolveResult]:
    """
    ROI-optimized template match: crop search area to recorded region + margin.

    Returns ResolveResult if found within ROI, None to fall through to full-screen.
    """
    try:
        import cv2
        import numpy as np
        from runtime.visual_anchor import _jpeg_to_cv2, _CV_SEMAPHORE
        from airtest import aircv

        region = screenshot_anchor["region"]
        rx = float(region.get("rx", 0))
        ry = float(region.get("ry", 0))
        rw = float(region.get("rw", 1))
        rh = float(region.get("rh", 1))

        screen_img = _jpeg_to_cv2(screen_jpeg)
        sh, sw = screen_img.shape[:2]

        # Add 20% margin to handle slight layout shifts
        margin_x = int(rw * sw * 0.2)
        margin_y = int(rh * sh * 0.2)

        x1 = max(0, int(rx * sw) - margin_x)
        y1 = max(0, int(ry * sh) - margin_y)
        x2 = min(sw, int((rx + rw) * sw) + margin_x)
        y2 = min(sh, int((ry + rh) * sh) + margin_y)

        if x2 <= x1 or y2 <= y1:
            return None

        roi_img = screen_img[y1:y2, x1:x2]
        template_img = _jpeg_to_cv2(element_image)
        th, tw = template_img.shape[:2]
        rh_px, rw_px = roi_img.shape[:2]

        if th >= rh_px or tw >= rw_px:
            return None  # Template bigger than ROI — fall through to full

        with _CV_SEMAPHORE:
            result = aircv.find_template(
                roi_img, template_img, threshold=image_threshold, rgb=True,
            )

        if result is None:
            return None

        # Translate ROI-local coords back to full-screen coords
        cx_local, cy_local = result["result"]
        cx_full = int(cx_local) + x1
        cy_full = int(cy_local) + y1
        conf = result["confidence"]

        # Scale from screenshot pixels to device logical coords
        dx = int(cx_full * screen_w / sw) if sw > 0 else cx_full
        dy = int(cy_full * screen_h / sh) if sh > 0 else cy_full
        dx = max(0, min(screen_w - 1, dx))
        dy = max(0, min(screen_h - 1, dy))

        log.info("[resolver] ROI image match → (%d,%d) conf=%.3f", dx, dy, conf)
        return ResolveResult(
            hit=True, x=dx, y=dy, confidence=conf,
            bounds=_make_bounds(dx, dy, 50, screen_w, screen_h),
            method="image_match",
            message=f"image match ROI ({conf:.2f}) → tap ({dx},{dy})",
        )
    except ImportError:
        return None
    except Exception as exc:
        log.debug("[resolver] ROI match error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Phase 1.5: Self-healing (alternative selector from XML at recorded position)
# ---------------------------------------------------------------------------

def phase_healing(
    u2,
    device: "DeviceClient",
    by: str,
    value: str,
    fallback_rx: Optional[float],
    fallback_ry: Optional[float],
    screen_w: int,
    screen_h: int,
    implicit_wait_timeout: float = 3.0,
) -> Optional[ResolveResult]:
    """
    Self-healing phase: when original selector fails, dump XML hierarchy,
    locate the node at the recorded position, and try alternative selectors.

    Only runs when DEVICE_FARM_HEALING_ENABLED=1 and fallback_rx/ry are set.
    Uses cached XML (no extra screenshot needed).

    Returns ResolveResult with method="healed_selector" on success, None otherwise.
    """
    from runtime.selector_healer import try_heal_proactive, HEALING_ENABLED
    if not HEALING_ENABLED:
        return None

    if fallback_rx is None or fallback_ry is None:
        return None

    # Get cached XML hierarchy (no force_refresh — avoid extra round-trip)
    xml = device.hierarchy_xml(force_refresh=False)
    if not xml:
        return None

    healed = try_heal_proactive(
        u2, xml, by, value,
        fallback_rx, fallback_ry,
        screen_w, screen_h,
        implicit_wait_timeout=implicit_wait_timeout,
    )
    if healed is None:
        return None

    # Found a working alternative selector — now get its bounds and tap coords
    healed_by = healed["by"]
    healed_value = healed["value"]
    try:
        r2 = u2.find_element_with_bounds(healed_by, healed_value) if hasattr(u2, "find_element_with_bounds") else None
        bounds: Optional[Dict[str, int]] = r2.get("bounds") if r2 else None
    except Exception:
        bounds = None

    if bounds:
        cx = (bounds.get("left", 0) + bounds.get("right", screen_w)) // 2
        cy = (bounds.get("top", 0) + bounds.get("bottom", screen_h)) // 2
        return ResolveResult(
            hit=True, x=cx, y=cy, bounds=bounds,
            method="healed_selector",
            message=f"healed {healed_by}={healed_value!r} (was {by}={value!r})",
        )

    # Fallback to recorded position when bounds not available
    fx = max(0, min(screen_w - 1, int(fallback_rx * screen_w)))
    fy = max(0, min(screen_h - 1, int(fallback_ry * screen_h)))
    return ResolveResult(
        hit=True, x=fx, y=fy,
        bounds=_make_bounds(fx, fy, 50, screen_w, screen_h),
        method="healed_selector",
        message=f"healed {healed_by}={healed_value!r} → tap recorded pos",
    )


# ---------------------------------------------------------------------------
# Phase 3: Ratio fallback (recorded position × screen dims)
# ---------------------------------------------------------------------------

def phase_ratio(
    device: "DeviceClient",
    fallback_rx: float,
    fallback_ry: float,
    screen_w: int,
    screen_h: int,
    selector_tried: bool = False,
) -> Optional[ResolveResult]:
    """
    Fallback: tap at recorded ratio position.

    Always succeeds (returns hit=True) since we have valid coordinates.
    """
    fx = max(0, min(screen_w - 1, int(fallback_rx * screen_w)))
    fy = max(0, min(screen_h - 1, int(fallback_ry * screen_h)))
    reason = "selector failed → " if selector_tried else ""
    return ResolveResult(
        hit=True, x=fx, y=fy,
        bounds=_make_bounds(fx, fy, 50, screen_w, screen_h),
        method="fallback_position",
        message=f"{reason}fallback position ({fallback_rx:.3f},{fallback_ry:.3f})",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scale_to_device(
    cx: int, cy: int,
    screen_jpeg: bytes,
    screen_w: int, screen_h: int,
) -> Tuple[int, int]:
    """Scale pixel coords from screenshot to device logical coords."""
    try:
        from PIL import Image as _PILImage
        img = _PILImage.open(io.BytesIO(screen_jpeg))
        iw, ih = img.size
        cx = int(cx * screen_w / iw) if iw > 0 else cx
        cy = int(cy * screen_h / ih) if ih > 0 else cy
    except Exception as exc:
        log.debug("[resolver] screenshot scale failed, using raw coords: %s", exc)
    return cx, cy


def _make_bounds(cx: int, cy: int, pad: int, w: int, h: int) -> Dict[str, int]:
    """Create a bounds dict centered on (cx, cy) with padding."""
    return {
        "left": max(0, cx - pad), "top": max(0, cy - pad),
        "right": min(w, cx + pad), "bottom": min(h, cy + pad),
    }
