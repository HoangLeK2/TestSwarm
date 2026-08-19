"""Is this crop usable as a match template? (mirrors agent-boot relay/image_match)

Matching itself runs on agent-boot — that is where the screen is. This module
exists only for the moment the user crops a template in the editor, so the API
can warn before the crop is ever used in a run.

Why it has to be checked at crop time: a template cut from blank or uniform
background scores confidence 1.000 *anywhere*, including on a completely
different screen. No run-time threshold can catch that — the step will tap the
wrong place and report a perfect match. The only useful moment to say so is
while the user is still looking at what they cropped.

agent-boot is a separate deployment unit with no import path to device_farm, so
the same rules live in `agent-boot/relay/image_match.py::looks_ambiguous`. Keep
the two in step; this is the established convention here (see
`agent-boot/relay/u2_xpath_util.py`, which mirrors `runtime.u2_xpath`).
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Below this standard deviation a crop carries almost no structure to match on.
_MIN_STDDEV = 8.0
_MIN_SIDE_PX = 16
# Scale used for the repeat check; matches the agent's default match scale.
_CHECK_SCALE = 0.25


def looks_ambiguous(template: bytes, screen: bytes | None = None) -> tuple[bool, str]:
    """Return ``(ambiguous, reason)``; reason is empty when the crop looks fine."""
    if not template:
        return False, ""
    try:
        import cv2
        import numpy as np
    except Exception as exc:  # pragma: no cover - advisory check only
        log.debug("ambiguity check skipped, OpenCV unavailable: %s", exc)
        return False, ""

    def _decode(data: bytes):
        img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("undecodable image")
        return img

    try:
        tpl = _decode(template)
    except Exception:
        return False, ""

    gray = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
    if float(gray.std()) < _MIN_STDDEV:
        return True, "Vùng ảnh gần như phẳng — sẽ khớp với nhiều nơi trên màn hình."

    h, w = gray.shape[:2]
    if h < _MIN_SIDE_PX or w < _MIN_SIDE_PX:
        return True, f"Vùng ảnh quá nhỏ ({w}x{h}px) nên dễ khớp nhầm."

    if not screen:
        return False, ""

    try:
        scr = _decode(screen)
    except Exception:
        return False, ""

    def _shrink(img):
        return cv2.resize(
            img, None, fx=_CHECK_SCALE, fy=_CHECK_SCALE, interpolation=cv2.INTER_AREA
        )

    s_small, t_small = _shrink(scr), _shrink(tpl)
    if t_small.shape[0] > s_small.shape[0] or t_small.shape[1] > s_small.shape[1]:
        return False, ""

    res = cv2.matchTemplate(s_small, t_small, cv2.TM_CCOEFF_NORMED)
    hits = np.argwhere(res >= 0.95)
    # Pixels next to one true match also clear the bar; collapse them so only
    # genuinely separate locations count.
    min_dist = max(t_small.shape[:2])
    kept: list[tuple[int, int]] = []
    for y, x in hits:
        if all(abs(x - kx) >= min_dist or abs(y - ky) >= min_dist for ky, kx in kept):
            kept.append((int(y), int(x)))
            if len(kept) > 8:
                break
    if len(kept) > 1:
        return True, (
            f"Vùng ảnh này khớp {len(kept)} vị trí khác nhau trên chính màn hình "
            "đang xem — hãy cắt vùng có nhiều chi tiết riêng hơn."
        )
    return False, ""
