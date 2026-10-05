"""
visual_anchor.py — Visual Anchoring for scenario playback (powered by Airtest).

Uses Airtest's aircv engine (by NetEase) for:
  1. **Screen Verification (SSIM)**: compare current screen with the screenshot
     captured during recording to confirm we're on the right screen.
  2. **Image-based Element Finding (Template Matching)**: when selectors fail
     (e.g. resource-id changed after app update), locate the element on screen
     by matching the cropped element image from recording.

Airtest's aircv is used standalone (no device connection) — we only import
the pure CV functions, not the device layer.

Dependencies: airtest (which bundles opencv-contrib internally).

NOTE: DEVICE_FARM_CV_CONCURRENCY must be set before first import if a
non-default value is required; the semaphore is created at import time.
"""

from __future__ import annotations

import base64
import logging
import threading
from typing import Callable, Optional

import cv2
import numpy as np
from airtest import aircv
from tenacity import retry, stop_after_delay, wait_fixed, retry_if_result

from core.env import device_farm_cv_concurrency

log = logging.getLogger(__name__)


_CV_MAX_CONCURRENT = device_farm_cv_concurrency()
_CV_SEMAPHORE = threading.Semaphore(value=_CV_MAX_CONCURRENT)


# ---------------------------------------------------------------------------
# Image conversion helpers
# ---------------------------------------------------------------------------

def _jpeg_to_cv2(jpeg_bytes: bytes) -> np.ndarray:
    """Decode JPEG bytes to BGR numpy array (OpenCV format)."""
    arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Failed to decode JPEG image")
    return img


def _b64_to_bytes(b64_str: str) -> bytes:
    """Decode base64 string (with or without data URI prefix) to bytes."""
    if "," in b64_str:
        b64_str = b64_str.split(",", 1)[1]
    return base64.b64decode(b64_str)


def _ensure_same_size(
    img1: np.ndarray, img2: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Resize img2 to match img1 dimensions if they differ."""
    h1, w1 = img1.shape[:2]
    h2, w2 = img2.shape[:2]
    if h1 != h2 or w1 != w2:
        img2 = cv2.resize(img2, (w1, h1), interpolation=cv2.INTER_AREA)
    return img1, img2


def _extract_rect(result: dict) -> tuple[int, int, int, int]:
    """Extract (x, y, w, h) from an aircv match result's rectangle.

    Uses min/max across all four corners to handle rotated match results
    correctly instead of assuming a fixed corner ordering.
    """
    rect = result["rectangle"]  # four (x, y) corner points
    xs = [int(p[0]) for p in rect]
    ys = [int(p[1]) for p in rect]
    x1, y1 = min(xs), min(ys)
    x2, y2 = max(xs), max(ys)
    return x1, y1, x2 - x1, y2 - y1


def _decode_pair(
    template_jpeg: bytes, screen_jpeg: bytes,
) -> Optional[tuple[np.ndarray, np.ndarray]]:
    """Decode template+screen JPEG pair. Returns None if template >= screen."""
    try:
        screen = _jpeg_to_cv2(screen_jpeg)
        template = _jpeg_to_cv2(template_jpeg)
    except Exception as exc:
        log.warning("image decode failed: %s", exc)
        return None
    th, tw = template.shape[:2]
    sh, sw = screen.shape[:2]
    if th >= sh or tw >= sw:
        log.debug("template (%dx%d) >= screen (%dx%d), skipping", tw, th, sw, sh)
        return None
    return screen, template


# ---------------------------------------------------------------------------
# SSIM — Screen State Verification
# ---------------------------------------------------------------------------

def compare_screens(recorded_jpeg: bytes, current_jpeg: bytes) -> float:
    """
    Compare recorded screenshot with current device screen using SSIM.

    Uses OpenCV's built-in QualitySSIM (opencv-contrib quality module).
    Bounded by _CV_SEMAPHORE to limit concurrent CPU usage, including the
    resize allocation that precedes the SSIM computation.

    Returns SSIM score in [0, 1]:
      - >= 0.85: same screen (proceed)
      - 0.60–0.85: similar (might be scrolled or slightly changed)
      - < 0.60: different screen (wrong state)
    """
    try:
        img1 = _jpeg_to_cv2(recorded_jpeg)
        img2 = _jpeg_to_cv2(current_jpeg)
        with _CV_SEMAPHORE:
            img1, img2 = _ensure_same_size(img1, img2)
            scores, _ = cv2.quality.QualitySSIM_compute(img1, img2)
        return float(np.mean(scores[:3]))
    except Exception as exc:
        log.warning("compare_screens failed: %s", exc)
        return 0.0



def find_element_by_image(
    template_jpeg: bytes,
    screen_jpeg: bytes,
    threshold: float = 0.7,
    rgb: bool = True,
) -> Optional[tuple[int, int, int, int, float]]:
    """
    Find an element on screen using Airtest's template matching engine.

    Returns (x, y, w, h, confidence), or None if below threshold.
    """
    pair = _decode_pair(template_jpeg, screen_jpeg)
    if pair is None:
        return None
    screen, template = pair

    with _CV_SEMAPHORE:
        result = aircv.find_template(screen, template, threshold=threshold, rgb=rgb)
    if result is None:
        log.debug("find_element_by_image: no match above threshold %.3f", threshold)
        return None

    x, y, w, h = _extract_rect(result)
    conf = result["confidence"]
    log.info("find_element_by_image: (%d,%d) %dx%d conf=%.3f", x, y, w, h, conf)
    return (x, y, w, h, conf)


def find_all_elements_by_image(
    template_jpeg: bytes,
    screen_jpeg: bytes,
    threshold: float = 0.7,
    rgb: bool = True,
) -> list[tuple[int, int, int, int, float]]:
    """Find ALL occurrences of an element on screen."""
    pair = _decode_pair(template_jpeg, screen_jpeg)
    if pair is None:
        return []
    screen, template = pair

    with _CV_SEMAPHORE:
        results = aircv.find_all_template(screen, template, threshold=threshold, rgb=rgb)
    return [
        (*_extract_rect(r), r["confidence"])
        for r in results
    ]


def find_element_center_by_image(
    template_jpeg: bytes,
    screen_jpeg: bytes,
    threshold: float = 0.7,
    rgb: bool = True,
) -> Optional[tuple[int, int, float]]:
    """Find element and return its center point: (cx, cy, confidence) or None.

    Delegates to find_element_by_image to avoid decoding the JPEG pair twice.
    """
    hit = find_element_by_image(template_jpeg, screen_jpeg, threshold=threshold, rgb=rgb)
    if hit is None:
        return None
    x, y, w, h, conf = hit
    return (x + w // 2, y + h // 2, conf)


# ---------------------------------------------------------------------------
# Retry wrappers (Tenacity)
# ---------------------------------------------------------------------------

def wait_for_screen_match(
    get_screenshot_fn: Callable[[], Optional[bytes]],
    recorded_jpeg: bytes,
    timeout: float = 10.0,
    poll: float = 0.5,
    ssim_threshold: float = 0.75,
) -> tuple[bool, float]:
    """
    Wait until SSIM(current, recorded) >= threshold.

    Returns (matched, best_ssim_score).
    """
    best_ssim = 0.0

    @retry(
        stop=stop_after_delay(timeout),
        wait=wait_fixed(poll),
        retry=retry_if_result(lambda r: r is False),
        reraise=False,
    )
    def _check():
        nonlocal best_ssim
        current = get_screenshot_fn()
        if current is None:
            return False
        score = compare_screens(recorded_jpeg, current)
        best_ssim = max(best_ssim, score)
        if score >= ssim_threshold:
            return True
        log.debug("wait_for_screen_match: SSIM=%.3f < %.3f", score, ssim_threshold)
        return False

    try:
        return (_check() is True, best_ssim)
    except Exception as exc:
        log.warning("wait_for_screen_match: unexpected error: %s", exc)
        return (False, best_ssim)


def wait_for_element_image(
    get_screenshot_fn: Callable[[], Optional[bytes]],
    template_jpeg: bytes,
    timeout: float = 10.0,
    poll: float = 0.5,
    threshold: float = 0.7,
    rgb: bool = True,
) -> Optional[tuple[int, int, float]]:
    """Wait until element image appears on screen. Returns (cx, cy, conf) or None."""

    @retry(
        stop=stop_after_delay(timeout),
        wait=wait_fixed(poll),
        retry=retry_if_result(lambda r: r is None),
        reraise=False,
    )
    def _find():
        current = get_screenshot_fn()
        if current is None:
            log.debug("wait_for_element_image: no screenshot available")
            return None
        result = find_element_center_by_image(
            template_jpeg, current, threshold=threshold, rgb=rgb,
        )
        if result is None:
            log.debug("wait_for_element_image: no match yet (threshold=%.2f)", threshold)
        return result

    try:
        return _find()
    except Exception as exc:
        log.warning("wait_for_element_image: unexpected error: %s", exc)
        return None
