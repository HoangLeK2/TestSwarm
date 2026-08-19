"""On-device template matching for the relay — find a cropped image on screen.

Runs where the pixels already are, for the same reason OCR does: media goes
media-adapter -> go2rtc without passing through the farm, so the backend has no
frame to search. Sending the screen back instead would cost ~800 KB per step;
this returns a coordinate.

Performance notes (measured on real 1260x2800 screenshots):
  - Matching at scale 0.25 costs ~5-9 ms versus 115-265 ms at full resolution,
    a 20-30x saving, and confidence does not drop: verified both self-match and
    cross-screen (template cut on one screen, found on a later one). Hence
    DEFAULT_SCALE = 0.25 rather than a "safe" 1.0.
  - JPEG q70 screens against a PNG template still score 0.998-1.000, so the
    device's native frame format is fine as-is.

Two failure modes worth knowing about, both measured:
  - A template cut from blank or uniform background scores 1.000 *anywhere*,
    including on a completely different screen. No threshold can catch that;
    it has to be flagged when the template is created. `looks_ambiguous` exists
    for the backend to call at crop time.
  - A template cut on a 1260px-wide device, searched on a 1440px screen, scores
    0.986 uncorrected versus 0.998 corrected — hence `template_screen_w`.
"""
from __future__ import annotations

import io
import logging
from typing import Any

logger = logging.getLogger("relay.image_match")

# See module docstring: 20-30x faster with no measured accuracy cost.
DEFAULT_SCALE = 0.25
DEFAULT_THRESHOLD = 0.8
# Below this the downscaled template loses too much structure to match on.
_MIN_TEMPLATE_PX = 8

_available: bool | None = None


def available() -> bool:
    """True when OpenCV is importable. Cached after the first probe."""
    global _available
    if _available is None:
        try:
            import cv2  # noqa: F401
            import numpy  # noqa: F401

            _available = True
        except Exception as exc:
            logger.info("OpenCV unavailable (%s); image matching capability off", exc)
            _available = False
    return _available


def _decode(data: bytes):
    import cv2
    import numpy as np

    img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("could not decode image")
    return img


def _resize(img, fx: float):
    import cv2

    if fx == 1.0:
        return img
    h, w = img.shape[:2]
    nw, nh = max(1, int(round(w * fx))), max(1, int(round(h * fx)))
    # INTER_AREA is the right filter for shrinking; bilinear leaves aliasing
    # that costs confidence on text-heavy UI.
    return cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)


def match_template(
    screen: bytes,
    template: bytes,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    scale: float = DEFAULT_SCALE,
    template_screen_w: int | None = None,
) -> dict[str, Any] | None:
    """Locate ``template`` on ``screen``.

    Returns ``{x, y, w, h, cx, cy, conf}`` in **original screen pixels**, or
    None when nothing scores above ``threshold``. Coordinates are what the
    caller taps, so they must never be left in the downscaled space.

    ``template_screen_w`` is the screen width the template was cropped on; when
    it differs from the current screen the template is rescaled to match.
    """
    if not screen or not template or not available():
        return None

    import cv2

    try:
        scr = _decode(screen)
        tpl = _decode(template)
    except Exception as exc:
        logger.warning("image match could not decode input: %s", exc)
        return None

    sh, sw = scr.shape[:2]

    # Device-resolution correction, before any downscaling.
    if template_screen_w and template_screen_w > 0 and template_screen_w != sw:
        tpl = _resize(tpl, sw / float(template_screen_w))

    eff = max(0.05, min(1.0, float(scale)))
    th, tw = tpl.shape[:2]
    # Keep the template usable: shrinking a small icon to a few pixels destroys
    # the structure the match depends on.
    if min(th, tw) * eff < _MIN_TEMPLATE_PX:
        eff = min(1.0, _MIN_TEMPLATE_PX / max(1, min(th, tw)))

    s_small, t_small = _resize(scr, eff), _resize(tpl, eff)
    if t_small.shape[0] > s_small.shape[0] or t_small.shape[1] > s_small.shape[1]:
        logger.debug("template %sx%s larger than screen %sx%s",
                     t_small.shape[1], t_small.shape[0], s_small.shape[1], s_small.shape[0])
        return None

    result = cv2.matchTemplate(s_small, t_small, cv2.TM_CCOEFF_NORMED)
    _, conf, _, loc = cv2.minMaxLoc(result)
    if conf < threshold:
        return None

    # Back to original screen pixels.
    x, y = int(round(loc[0] / eff)), int(round(loc[1] / eff))
    w, h = int(round(t_small.shape[1] / eff)), int(round(t_small.shape[0] / eff))
    x, y = max(0, min(sw - 1, x)), max(0, min(sh - 1, y))
    return {
        "x": x, "y": y, "w": w, "h": h,
        "cx": max(0, min(sw - 1, x + w // 2)),
        "cy": max(0, min(sh - 1, y + h // 2)),
        "conf": round(float(conf), 4),
    }


def looks_ambiguous(
    template: bytes,
    screen: bytes | None = None,
    *,
    threshold: float = 0.95,
) -> tuple[bool, str]:
    """Whether this template is too featureless to identify one spot.

    A flat crop matches everywhere at confidence 1.000, so it will tap the wrong
    place while looking perfectly confident. Called when the user crops, not at
    run time.

    Returns ``(ambiguous, reason)``; reason is empty when it looks fine.
    """
    if not template or not available():
        return False, ""

    import cv2
    import numpy as np

    try:
        tpl = _decode(template)
    except Exception:
        return False, ""

    gray = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
    if float(gray.std()) < 8.0:
        return True, "vùng ảnh gần như phẳng, sẽ khớp với nhiều nơi trên màn hình"

    h, w = gray.shape[:2]
    if h < 16 or w < 16:
        return True, f"vùng ảnh quá nhỏ ({w}x{h}px), dễ khớp nhầm"

    if screen:
        # Count distinct places on the source screen that score near-perfectly.
        try:
            scr = _decode(screen)
        except Exception:
            return False, ""
        s_small, t_small = _resize(scr, DEFAULT_SCALE), _resize(tpl, DEFAULT_SCALE)
        if (t_small.shape[0] <= s_small.shape[0]
                and t_small.shape[1] <= s_small.shape[1]):
            res = cv2.matchTemplate(s_small, t_small, cv2.TM_CCOEFF_NORMED)
            hits = np.argwhere(res >= threshold)
            # Pixels adjacent to a single true match also clear the bar;
            # collapse them so only genuinely separate locations count.
            separate = _count_separate(hits, min_dist=max(t_small.shape[:2]))
            if separate > 1:
                return True, f"khớp {separate} vị trí khác nhau trên chính màn hình này"
    return False, ""


def _count_separate(points, *, min_dist: int) -> int:
    """Number of hit clusters at least ``min_dist`` apart."""
    kept: list[tuple[int, int]] = []
    for y, x in points:
        if all(abs(x - kx) >= min_dist or abs(y - ky) >= min_dist for ky, kx in kept):
            kept.append((int(y), int(x)))
            if len(kept) > 8:
                break
    return len(kept)
