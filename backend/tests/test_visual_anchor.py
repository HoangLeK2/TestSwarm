"""
tests/test_visual_anchor.py — Unit tests for runtime/visual_anchor.py

Run: pytest tests/test_visual_anchor.py -v

Coverage strategy:
- All helper functions (_jpeg_to_cv2, _b64_to_bytes, _ensure_same_size,
  _extract_rect, _decode_pair) are tested with normal, edge, and error paths.
- compare_screens: real SSIM (identical/different/bad-input), resize path,
  semaphore acquisition.
- find_element_by_image / find_all_elements_by_image / find_element_center_by_image:
  aircv is mocked; threshold + rgb parameters, rotated rect, degenerate cases.
- wait_for_screen_match / wait_for_element_image: retry behaviour, timeout,
  best_ssim tracking, None screenshot, exception in callback.

Heavy CV calls (aircv.*, cv2.quality.QualitySSIM_compute) are mocked where
needed so the suite runs fast and without GPU dependencies.
"""
from __future__ import annotations

import base64
import threading
from unittest.mock import MagicMock, call, patch

import cv2
import numpy as np
import pytest

import runtime.visual_anchor as va


# ─────────────────────────────────────────────────────────────────────────────
# Image fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _make_jpeg(width: int, height: int, color: tuple = (128, 128, 128)) -> bytes:
    """Create a minimal solid-colour JPEG in memory."""
    img = np.full((height, width, 3), color, dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    assert ok, "cv2.imencode failed in fixture"
    return buf.tobytes()


# Standard fixtures used across many tests
SCREEN_JPEG    = _make_jpeg(400, 800, (200, 200, 200))   # 400×800 grey screen
TEMPLATE_JPEG  = _make_jpeg(40,  40,  (50,  50,  200))   # 40×40 blue square
SMALL_SCREEN   = _make_jpeg(30,  30,  (100, 100, 100))   # 30×30 tiny screen
LARGE_TEMPLATE = _make_jpeg(40,  40,  (50,  50,  200))   # 40×40 — bigger than 30×30

# Identical-colour JPEG for SSIM=1.0 tests
SCREEN_DARK    = _make_jpeg(400, 800, (10,  10,  10))


def _aircv_result(
    cx: int = 100, cy: int = 200,
    x1: int = 80, y1: int = 180, x2: int = 120, y2: int = 220,
    confidence: float = 0.9,
) -> dict:
    """Axis-aligned rectangle result mimicking aircv.find_template output."""
    return {
        "result": (cx, cy),
        "rectangle": [(x1, y1), (x2, y1), (x2, y2), (x1, y2)],
        "confidence": confidence,
    }


def _aircv_rotated_result(confidence: float = 0.85) -> dict:
    """Rotated rectangle — corners are NOT in standard top-left → clockwise order."""
    return {
        "result": (100, 200),
        # xs: 90,130,110,70  → min=70, max=130  w=60
        # ys: 170,180,230,220 → min=170, max=230 h=60
        "rectangle": [(90, 170), (130, 180), (110, 230), (70, 220)],
        "confidence": confidence,
    }


# ─────────────────────────────────────────────────────────────────────────────
# _jpeg_to_cv2
# ─────────────────────────────────────────────────────────────────────────────

class TestJpegToCv2:
    def test_returns_ndarray_with_correct_shape(self):
        img = va._jpeg_to_cv2(SCREEN_JPEG)
        assert isinstance(img, np.ndarray)
        # OpenCV: shape is (height, width, channels)
        assert img.shape == (800, 400, 3)

    def test_raises_value_error_on_invalid_bytes(self):
        with pytest.raises(ValueError, match="Failed to decode"):
            va._jpeg_to_cv2(b"not a jpeg")

    def test_raises_on_empty_bytes(self):
        # cv2.imdecode raises cv2.error for empty buffer before we can return None
        with pytest.raises(Exception):
            va._jpeg_to_cv2(b"")

    def test_small_image_decoded_correctly(self):
        small = _make_jpeg(10, 10, (255, 0, 0))
        img = va._jpeg_to_cv2(small)
        assert img.shape == (10, 10, 3)

    def test_dtype_is_uint8(self):
        img = va._jpeg_to_cv2(SCREEN_JPEG)
        assert img.dtype == np.uint8


# ─────────────────────────────────────────────────────────────────────────────
# _b64_to_bytes
# ─────────────────────────────────────────────────────────────────────────────

class TestB64ToBytes:
    def test_plain_base64(self):
        data = b"hello world"
        assert va._b64_to_bytes(base64.b64encode(data).decode()) == data

    def test_data_uri_with_jpeg_prefix(self):
        data = b"binary\x00\xFF"
        b64 = "data:image/jpeg;base64," + base64.b64encode(data).decode()
        assert va._b64_to_bytes(b64) == data

    def test_data_uri_with_png_prefix(self):
        data = b"\x89PNG"
        b64 = "data:image/png;base64," + base64.b64encode(data).decode()
        assert va._b64_to_bytes(b64) == data

    def test_multiple_commas_splits_on_first(self):
        """The prefix may itself contain commas (unlikely but defensive)."""
        data = b"test"
        # Manually build a string with a comma in the prefix
        b64_part = base64.b64encode(data).decode()
        crafted = "data:foo,bar;base64," + b64_part
        # Our impl splits on first comma, taking everything after
        result = va._b64_to_bytes(crafted)
        # "bar;base64,{b64_part}" → base64.b64decode("bar;base64,{b64_part}") would fail
        # So just verify the function doesn't crash; the exact result depends on split logic.
        assert isinstance(result, bytes)

    def test_empty_payload_returns_empty_bytes(self):
        assert va._b64_to_bytes(base64.b64encode(b"").decode()) == b""


# ─────────────────────────────────────────────────────────────────────────────
# _ensure_same_size
# ─────────────────────────────────────────────────────────────────────────────

class TestEnsureSameSize:
    def test_no_op_when_equal_shape(self):
        img1 = np.zeros((100, 200, 3), dtype=np.uint8)
        img2 = np.zeros((100, 200, 3), dtype=np.uint8)
        r1, r2 = va._ensure_same_size(img1, img2)
        assert r1 is img1
        assert r2 is img2  # same object — not resized

    def test_resizes_img2_to_match_img1(self):
        img1 = np.zeros((100, 200, 3), dtype=np.uint8)
        img2 = np.zeros((50, 80, 3), dtype=np.uint8)
        r1, r2 = va._ensure_same_size(img1, img2)
        assert r2.shape[:2] == (100, 200)

    def test_img1_is_not_modified(self):
        img1 = np.zeros((100, 200, 3), dtype=np.uint8)
        img2 = np.zeros((60, 90, 3), dtype=np.uint8)
        r1, r2 = va._ensure_same_size(img1, img2)
        assert r1 is img1
        assert r1.shape[:2] == (100, 200)

    def test_height_only_differs(self):
        img1 = np.zeros((100, 200, 3), dtype=np.uint8)
        img2 = np.zeros((50, 200, 3), dtype=np.uint8)  # same width, different height
        r1, r2 = va._ensure_same_size(img1, img2)
        assert r2.shape[:2] == (100, 200)

    def test_width_only_differs(self):
        img1 = np.zeros((100, 200, 3), dtype=np.uint8)
        img2 = np.zeros((100, 80, 3), dtype=np.uint8)  # same height, different width
        r1, r2 = va._ensure_same_size(img1, img2)
        assert r2.shape[:2] == (100, 200)

    def test_output_dtype_preserved(self):
        img1 = np.zeros((100, 100, 3), dtype=np.uint8)
        img2 = np.zeros((50, 50, 3), dtype=np.uint8)
        _, r2 = va._ensure_same_size(img1, img2)
        assert r2.dtype == np.uint8


# ─────────────────────────────────────────────────────────────────────────────
# _extract_rect
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractRect:
    def test_axis_aligned_rectangle(self):
        result = _aircv_result(x1=80, y1=180, x2=120, y2=220)
        x, y, w, h = va._extract_rect(result)
        assert x == 80
        assert y == 180
        assert w == 40   # 120 - 80
        assert h == 40   # 220 - 180

    def test_rotated_rectangle_uses_min_max(self):
        """Rotated corners must use min/max, not a fixed corner index."""
        result = _aircv_rotated_result()
        x, y, w, h = va._extract_rect(result)
        assert x == 70    # min of {90,130,110,70}
        assert y == 170   # min of {170,180,230,220}
        assert w == 60    # 130 - 70
        assert h == 60    # 230 - 170

    def test_non_zero_origin(self):
        result = _aircv_result(x1=300, y1=400, x2=360, y2=460)
        x, y, w, h = va._extract_rect(result)
        assert x == 300 and y == 400
        assert w == 60 and h == 60

    def test_returns_integers(self):
        result = _aircv_result()
        x, y, w, h = va._extract_rect(result)
        for v in (x, y, w, h):
            assert isinstance(v, int)

    def test_positive_dimensions_always(self):
        result = _aircv_result(x1=10, y1=20, x2=50, y2=80)
        x, y, w, h = va._extract_rect(result)
        assert w > 0
        assert h > 0

    def test_single_point_rectangle(self):
        """Degenerate case: all corners at same point → 0×0 box."""
        result = {
            "rectangle": [(5, 5), (5, 5), (5, 5), (5, 5)],
            "confidence": 1.0,
        }
        x, y, w, h = va._extract_rect(result)
        assert x == 5 and y == 5
        assert w == 0 and h == 0

    def test_float_corners_truncated_to_int(self):
        result = {
            "rectangle": [(80.9, 180.1), (120.7, 180.1), (120.7, 220.3), (80.9, 220.3)],
            "confidence": 0.9,
        }
        x, y, w, h = va._extract_rect(result)
        assert isinstance(x, int)
        assert isinstance(y, int)


# ─────────────────────────────────────────────────────────────────────────────
# _decode_pair
# ─────────────────────────────────────────────────────────────────────────────

class TestDecodePair:
    def test_returns_screen_and_template_arrays(self):
        pair = va._decode_pair(TEMPLATE_JPEG, SCREEN_JPEG)
        assert pair is not None
        screen, template = pair
        assert screen.shape[:2] == (800, 400)
        assert template.shape[:2] == (40, 40)

    def test_returns_none_when_template_height_equals_screen_height(self):
        """th >= sh should return None even when equal."""
        same_height = _make_jpeg(10, 40)   # 10w × 40h
        template    = _make_jpeg(5,  40)   # 5w  × 40h — th == sh → skip
        assert va._decode_pair(template, same_height) is None

    def test_returns_none_when_template_width_equals_screen_width(self):
        """tw >= sw should return None even when equal."""
        same_width = _make_jpeg(40, 50)    # 40w × 50h
        template   = _make_jpeg(40, 10)    # 40w × 10h — tw == sw → skip
        assert va._decode_pair(template, same_width) is None

    def test_returns_none_when_template_larger_than_screen(self):
        assert va._decode_pair(LARGE_TEMPLATE, SMALL_SCREEN) is None

    def test_returns_none_on_corrupt_template(self, caplog):
        pair = va._decode_pair(b"not jpeg", SCREEN_JPEG)
        assert pair is None
        assert "image decode failed" in caplog.text

    def test_returns_none_on_corrupt_screen(self, caplog):
        pair = va._decode_pair(TEMPLATE_JPEG, b"bad screen")
        assert pair is None
        assert "image decode failed" in caplog.text

    def test_returns_none_on_both_corrupt(self, caplog):
        pair = va._decode_pair(b"bad", b"bad")
        assert pair is None

    def test_template_just_smaller_than_screen(self):
        """Template 1px smaller than screen in each dimension → valid."""
        screen   = _make_jpeg(10, 10)
        template = _make_jpeg(9,  9)
        pair = va._decode_pair(template, screen)
        assert pair is not None


# ─────────────────────────────────────────────────────────────────────────────
# compare_screens
# ─────────────────────────────────────────────────────────────────────────────

class TestCompareScreens:
    def test_identical_images_score_near_one(self):
        score = va.compare_screens(SCREEN_JPEG, SCREEN_JPEG)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_different_images_score_lower(self):
        score = va.compare_screens(SCREEN_JPEG, SCREEN_DARK)
        assert score < 0.9

    def test_returns_zero_on_bad_recorded(self):
        score = va.compare_screens(b"bad", SCREEN_JPEG)
        assert score == 0.0

    def test_returns_zero_on_bad_current(self):
        score = va.compare_screens(SCREEN_JPEG, b"bad")
        assert score == 0.0

    def test_returns_zero_on_both_bad(self):
        assert va.compare_screens(b"x", b"y") == 0.0

    def test_score_in_valid_range(self):
        score = va.compare_screens(SCREEN_JPEG, SCREEN_DARK)
        assert 0.0 <= score <= 1.0

    def test_different_sizes_handled_without_raise(self):
        """Resize path must not raise."""
        small = _make_jpeg(200, 400)
        score = va.compare_screens(SCREEN_JPEG, small)
        assert 0.0 <= score <= 1.0

    def test_semaphore_is_acquired_and_released(self):
        """_CV_SEMAPHORE must be entered and exited exactly once per call.

        Python looks up dunder methods (__enter__/__exit__) on the *type*,
        not the instance, so we replace the module-level semaphore with a
        MagicMock that wraps the real one.
        """
        real_sem = va._CV_SEMAPHORE
        mock_sem = MagicMock(wraps=real_sem)

        with patch.object(va, "_CV_SEMAPHORE", mock_sem):
            va.compare_screens(SCREEN_JPEG, SCREEN_JPEG)

        mock_sem.__enter__.assert_called_once()
        mock_sem.__exit__.assert_called_once()

    def test_symmetry(self):
        """compare_screens(a, b) ≈ compare_screens(b, a) — SSIM is symmetric."""
        other = _make_jpeg(400, 800, (100, 150, 200))
        score_ab = va.compare_screens(SCREEN_JPEG, other)
        score_ba = va.compare_screens(other, SCREEN_JPEG)
        assert abs(score_ab - score_ba) < 0.05


# ─────────────────────────────────────────────────────────────────────────────
# find_element_by_image
# ─────────────────────────────────────────────────────────────────────────────

class TestFindElementByImage:
    @patch("runtime.visual_anchor.aircv.find_template")
    def test_returns_rect_and_confidence(self, mock_ft):
        mock_ft.return_value = _aircv_result(x1=80, y1=180, x2=120, y2=220, confidence=0.92)
        result = va.find_element_by_image(TEMPLATE_JPEG, SCREEN_JPEG)
        assert result is not None
        x, y, w, h, conf = result
        assert x == 80 and y == 180 and w == 40 and h == 40
        assert conf == pytest.approx(0.92)

    @patch("runtime.visual_anchor.aircv.find_template", return_value=None)
    def test_returns_none_on_no_match(self, mock_ft):
        assert va.find_element_by_image(TEMPLATE_JPEG, SCREEN_JPEG) is None

    def test_returns_none_when_template_too_large(self):
        assert va.find_element_by_image(LARGE_TEMPLATE, SMALL_SCREEN) is None

    @patch("runtime.visual_anchor.aircv.find_template")
    def test_rotated_rect_uses_min_max(self, mock_ft):
        mock_ft.return_value = _aircv_rotated_result(confidence=0.85)
        result = va.find_element_by_image(TEMPLATE_JPEG, SCREEN_JPEG)
        assert result is not None
        x, y, w, h, conf = result
        assert x == 70 and y == 170 and w == 60 and h == 60

    @patch("runtime.visual_anchor.aircv.find_template")
    def test_threshold_is_forwarded_to_aircv(self, mock_ft):
        mock_ft.return_value = _aircv_result()
        va.find_element_by_image(TEMPLATE_JPEG, SCREEN_JPEG, threshold=0.85)
        _, kwargs = mock_ft.call_args
        assert kwargs.get("threshold") == 0.85

    @patch("runtime.visual_anchor.aircv.find_template")
    def test_rgb_false_is_forwarded_to_aircv(self, mock_ft):
        mock_ft.return_value = _aircv_result()
        va.find_element_by_image(TEMPLATE_JPEG, SCREEN_JPEG, rgb=False)
        _, kwargs = mock_ft.call_args
        assert kwargs.get("rgb") is False

    @patch("runtime.visual_anchor.aircv.find_template")
    def test_rgb_true_is_default(self, mock_ft):
        mock_ft.return_value = _aircv_result()
        va.find_element_by_image(TEMPLATE_JPEG, SCREEN_JPEG)
        _, kwargs = mock_ft.call_args
        assert kwargs.get("rgb") is True

    @patch("runtime.visual_anchor.aircv.find_template")
    def test_semaphore_acquired_once(self, mock_ft):
        """Semaphore must be entered/exited exactly once per find call."""
        mock_ft.return_value = _aircv_result()
        real_sem = va._CV_SEMAPHORE
        mock_sem = MagicMock(wraps=real_sem)

        with patch.object(va, "_CV_SEMAPHORE", mock_sem):
            va.find_element_by_image(TEMPLATE_JPEG, SCREEN_JPEG)

        mock_sem.__enter__.assert_called_once()
        mock_sem.__exit__.assert_called_once()

    @patch("runtime.visual_anchor.aircv.find_template")
    def test_low_confidence_result_still_returned(self, mock_ft):
        """find_element_by_image returns whatever aircv gives — threshold is passed
        to aircv, not re-checked here."""
        mock_ft.return_value = _aircv_result(confidence=0.01)
        result = va.find_element_by_image(TEMPLATE_JPEG, SCREEN_JPEG, threshold=0.01)
        assert result is not None
        assert result[4] == pytest.approx(0.01)


# ─────────────────────────────────────────────────────────────────────────────
# find_all_elements_by_image
# ─────────────────────────────────────────────────────────────────────────────

class TestFindAllElementsByImage:
    @patch("runtime.visual_anchor.aircv.find_all_template")
    def test_returns_list_of_five_tuples(self, mock_fat):
        mock_fat.return_value = [
            _aircv_result(x1=0,   y1=0,   x2=40,  y2=40,  confidence=0.9),
            _aircv_result(x1=100, y1=100, x2=140, y2=140, confidence=0.8),
        ]
        results = va.find_all_elements_by_image(TEMPLATE_JPEG, SCREEN_JPEG)
        assert len(results) == 2
        assert all(len(r) == 5 for r in results)

    @patch("runtime.visual_anchor.aircv.find_all_template", return_value=[])
    def test_returns_empty_list_on_no_match(self, mock_fat):
        assert va.find_all_elements_by_image(TEMPLATE_JPEG, SCREEN_JPEG) == []

    def test_returns_empty_when_template_too_large(self):
        assert va.find_all_elements_by_image(LARGE_TEMPLATE, SMALL_SCREEN) == []

    @patch("runtime.visual_anchor.aircv.find_all_template")
    def test_confidence_values_match_aircv_output(self, mock_fat):
        mock_fat.return_value = [
            _aircv_result(x1=0, y1=0, x2=40, y2=40, confidence=0.95),
            _aircv_result(x1=100, y1=100, x2=140, y2=140, confidence=0.75),
        ]
        results = va.find_all_elements_by_image(TEMPLATE_JPEG, SCREEN_JPEG)
        assert results[0][4] == pytest.approx(0.95)
        assert results[1][4] == pytest.approx(0.75)

    @patch("runtime.visual_anchor.aircv.find_all_template")
    def test_threshold_forwarded(self, mock_fat):
        mock_fat.return_value = []
        va.find_all_elements_by_image(TEMPLATE_JPEG, SCREEN_JPEG, threshold=0.8)
        _, kwargs = mock_fat.call_args
        assert kwargs.get("threshold") == 0.8

    @patch("runtime.visual_anchor.aircv.find_all_template")
    def test_rgb_false_forwarded(self, mock_fat):
        mock_fat.return_value = []
        va.find_all_elements_by_image(TEMPLATE_JPEG, SCREEN_JPEG, rgb=False)
        _, kwargs = mock_fat.call_args
        assert kwargs.get("rgb") is False

    @patch("runtime.visual_anchor.aircv.find_all_template")
    def test_single_result(self, mock_fat):
        mock_fat.return_value = [_aircv_result(confidence=0.88)]
        results = va.find_all_elements_by_image(TEMPLATE_JPEG, SCREEN_JPEG)
        assert len(results) == 1
        assert results[0][4] == pytest.approx(0.88)


# ─────────────────────────────────────────────────────────────────────────────
# find_element_center_by_image
# ─────────────────────────────────────────────────────────────────────────────

class TestFindElementCenterByImage:
    @patch("runtime.visual_anchor.aircv.find_template")
    def test_returns_center_of_bounding_rect(self, mock_ft):
        mock_ft.return_value = _aircv_result(x1=80, y1=180, x2=120, y2=220, confidence=0.9)
        result = va.find_element_center_by_image(TEMPLATE_JPEG, SCREEN_JPEG)
        assert result is not None
        cx, cy, conf = result
        assert cx == 100   # 80 + 40 // 2
        assert cy == 200   # 180 + 40 // 2
        assert conf == pytest.approx(0.9)

    @patch("runtime.visual_anchor.aircv.find_template", return_value=None)
    def test_returns_none_on_no_match(self, mock_ft):
        assert va.find_element_center_by_image(TEMPLATE_JPEG, SCREEN_JPEG) is None

    def test_returns_none_when_template_too_large(self):
        assert va.find_element_center_by_image(LARGE_TEMPLATE, SMALL_SCREEN) is None

    @patch("runtime.visual_anchor.aircv.find_template")
    def test_delegates_to_find_element_by_image_not_direct_aircv(self, mock_ft):
        """find_element_center must call aircv exactly once (via find_element_by_image)."""
        mock_ft.return_value = _aircv_result()
        va.find_element_center_by_image(TEMPLATE_JPEG, SCREEN_JPEG)
        assert mock_ft.call_count == 1

    @patch("runtime.visual_anchor.aircv.find_template")
    def test_threshold_forwarded(self, mock_ft):
        mock_ft.return_value = _aircv_result()
        va.find_element_center_by_image(TEMPLATE_JPEG, SCREEN_JPEG, threshold=0.95)
        _, kwargs = mock_ft.call_args
        assert kwargs.get("threshold") == 0.95

    @patch("runtime.visual_anchor.aircv.find_template")
    def test_rgb_false_forwarded(self, mock_ft):
        mock_ft.return_value = _aircv_result()
        va.find_element_center_by_image(TEMPLATE_JPEG, SCREEN_JPEG, rgb=False)
        _, kwargs = mock_ft.call_args
        assert kwargs.get("rgb") is False

    @patch("runtime.visual_anchor.aircv.find_template")
    def test_non_square_rect_center_calculated_correctly(self, mock_ft):
        # rect: x1=10, y1=20, x2=50, y2=120  → w=40, h=100
        mock_ft.return_value = _aircv_result(x1=10, y1=20, x2=50, y2=120, confidence=0.9)
        result = va.find_element_center_by_image(TEMPLATE_JPEG, SCREEN_JPEG)
        cx, cy, _ = result
        assert cx == 30   # 10 + 40 // 2
        assert cy == 70   # 20 + 100 // 2


# ─────────────────────────────────────────────────────────────────────────────
# wait_for_screen_match
# ─────────────────────────────────────────────────────────────────────────────

class TestWaitForScreenMatch:
    def test_succeeds_immediately_on_identical_screen(self):
        matched, score = va.wait_for_screen_match(
            lambda: SCREEN_JPEG, SCREEN_JPEG,
            timeout=2.0, poll=0.05, ssim_threshold=0.9,
        )
        assert matched is True
        assert score > 0.9

    def test_returns_false_on_timeout_with_non_matching_screen(self):
        matched, score = va.wait_for_screen_match(
            lambda: SCREEN_DARK, SCREEN_JPEG,
            timeout=0.2, poll=0.05, ssim_threshold=0.99,
        )
        assert matched is False

    def test_returns_false_and_zero_score_on_none_screenshot(self):
        matched, score = va.wait_for_screen_match(
            lambda: None, SCREEN_JPEG,
            timeout=0.2, poll=0.05,
        )
        assert matched is False
        assert score == 0.0

    def test_best_ssim_tracks_maximum_across_all_polls(self):
        """When screen changes from non-match to match, best_ssim must reflect
        the final high score, not just the first poll."""
        calls = {"n": 0}

        def _get():
            calls["n"] += 1
            return SCREEN_DARK if calls["n"] < 3 else SCREEN_JPEG

        matched, score = va.wait_for_screen_match(
            _get, SCREEN_JPEG,
            timeout=5.0, poll=0.01, ssim_threshold=0.9,
        )
        assert matched is True
        assert score > 0.9

    def test_succeeds_on_second_poll(self):
        """First poll returns non-match, second returns match."""
        calls = {"n": 0}

        def _get():
            calls["n"] += 1
            return SCREEN_DARK if calls["n"] == 1 else SCREEN_JPEG

        matched, score = va.wait_for_screen_match(
            _get, SCREEN_JPEG,
            timeout=5.0, poll=0.01, ssim_threshold=0.9,
        )
        assert matched is True

    def test_swallows_exception_from_screenshot_fn(self):
        def _bad():
            raise RuntimeError("camera error")

        matched, score = va.wait_for_screen_match(
            _bad, SCREEN_JPEG,
            timeout=0.2, poll=0.05,
        )
        assert matched is False

    def test_default_ssim_threshold_is_075(self):
        """Default threshold is 0.75 — identical images must pass it."""
        matched, score = va.wait_for_screen_match(
            lambda: SCREEN_JPEG, SCREEN_JPEG,
            timeout=1.0, poll=0.05,
        )
        assert matched is True

    def test_returns_tuple_of_bool_and_float(self):
        result = va.wait_for_screen_match(
            lambda: SCREEN_JPEG, SCREEN_JPEG,
            timeout=1.0, poll=0.05,
        )
        assert isinstance(result, tuple) and len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], float)


# ─────────────────────────────────────────────────────────────────────────────
# wait_for_element_image
# ─────────────────────────────────────────────────────────────────────────────

class TestWaitForElementImage:
    @patch("runtime.visual_anchor.aircv.find_template")
    def test_found_immediately(self, mock_ft):
        mock_ft.return_value = _aircv_result()
        result = va.wait_for_element_image(
            lambda: SCREEN_JPEG, TEMPLATE_JPEG,
            timeout=2.0, poll=0.05,
        )
        assert result is not None
        cx, cy, conf = result
        assert conf > 0

    @patch("runtime.visual_anchor.aircv.find_template", return_value=None)
    def test_returns_none_on_timeout(self, mock_ft):
        result = va.wait_for_element_image(
            lambda: SCREEN_JPEG, TEMPLATE_JPEG,
            timeout=0.2, poll=0.05,
        )
        assert result is None

    def test_returns_none_on_none_screenshot(self):
        result = va.wait_for_element_image(
            lambda: None, TEMPLATE_JPEG,
            timeout=0.2, poll=0.05,
        )
        assert result is None

    @patch("runtime.visual_anchor.aircv.find_template")
    def test_retries_until_found(self, mock_ft):
        """First two calls: no match. Third call: hit. Result must be non-None."""
        mock_ft.side_effect = [None, None, _aircv_result()]
        result = va.wait_for_element_image(
            lambda: SCREEN_JPEG, TEMPLATE_JPEG,
            timeout=5.0, poll=0.01,
        )
        assert result is not None
        assert mock_ft.call_count == 3

    def test_swallows_exception_from_screenshot_fn(self):
        def _bad():
            raise RuntimeError("device offline")

        result = va.wait_for_element_image(
            _bad, TEMPLATE_JPEG,
            timeout=0.2, poll=0.05,
        )
        assert result is None

    @patch("runtime.visual_anchor.aircv.find_template")
    def test_threshold_forwarded_to_find(self, mock_ft):
        mock_ft.return_value = _aircv_result()
        va.wait_for_element_image(
            lambda: SCREEN_JPEG, TEMPLATE_JPEG,
            timeout=1.0, poll=0.05, threshold=0.88,
        )
        _, kwargs = mock_ft.call_args
        assert kwargs.get("threshold") == pytest.approx(0.88)

    @patch("runtime.visual_anchor.aircv.find_template")
    def test_rgb_false_forwarded(self, mock_ft):
        mock_ft.return_value = _aircv_result()
        va.wait_for_element_image(
            lambda: SCREEN_JPEG, TEMPLATE_JPEG,
            timeout=1.0, poll=0.05, rgb=False,
        )
        _, kwargs = mock_ft.call_args
        assert kwargs.get("rgb") is False

    @patch("runtime.visual_anchor.aircv.find_template")
    def test_returns_cx_cy_conf_tuple(self, mock_ft):
        mock_ft.return_value = _aircv_result(x1=80, y1=180, x2=120, y2=220, confidence=0.9)
        result = va.wait_for_element_image(
            lambda: SCREEN_JPEG, TEMPLATE_JPEG,
            timeout=2.0, poll=0.05,
        )
        assert result is not None
        assert len(result) == 3
        cx, cy, conf = result
        assert cx == 100 and cy == 200
        assert conf == pytest.approx(0.9)

    @patch("runtime.visual_anchor.aircv.find_template")
    def test_does_not_call_aircv_when_screenshot_is_none(self, mock_ft):
        va.wait_for_element_image(
            lambda: None, TEMPLATE_JPEG,
            timeout=0.1, poll=0.05,
        )
        mock_ft.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Semaphore concurrency
# ─────────────────────────────────────────────────────────────────────────────

class TestSemaphoreConcurrency:
    @patch("runtime.visual_anchor.aircv.find_template")
    def test_find_element_semaphore_limits_concurrency(self, mock_ft):
        """At most _CV_MAX_CONCURRENT threads inside semaphore at any time."""
        mock_ft.return_value = _aircv_result()
        max_seen = [0]
        inside   = [0]
        lock = threading.Lock()

        real_acquire = va._CV_SEMAPHORE.acquire
        real_release = va._CV_SEMAPHORE.release

        def _acq(*args, **kwargs):
            result = real_acquire(*args, **kwargs)
            with lock:
                inside[0] += 1
                max_seen[0] = max(max_seen[0], inside[0])
            return result

        def _rel():
            with lock:
                inside[0] -= 1
            real_release()

        with (
            patch.object(va._CV_SEMAPHORE, "acquire", _acq),
            patch.object(va._CV_SEMAPHORE, "release", _rel),
        ):
            n_threads = va._CV_MAX_CONCURRENT * 2
            threads = [
                threading.Thread(
                    target=va.find_element_by_image,
                    args=(TEMPLATE_JPEG, SCREEN_JPEG),
                )
                for _ in range(n_threads)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        assert max_seen[0] <= va._CV_MAX_CONCURRENT

    def test_compare_screens_semaphore_limits_concurrency(self):
        """compare_screens respects the same semaphore limit."""
        max_seen = [0]
        inside   = [0]
        lock = threading.Lock()

        real_acquire = va._CV_SEMAPHORE.acquire
        real_release = va._CV_SEMAPHORE.release

        def _acq(*args, **kwargs):
            result = real_acquire(*args, **kwargs)
            with lock:
                inside[0] += 1
                max_seen[0] = max(max_seen[0], inside[0])
            return result

        def _rel():
            with lock:
                inside[0] -= 1
            real_release()

        with (
            patch.object(va._CV_SEMAPHORE, "acquire", _acq),
            patch.object(va._CV_SEMAPHORE, "release", _rel),
        ):
            n_threads = va._CV_MAX_CONCURRENT * 2
            threads = [
                threading.Thread(
                    target=va.compare_screens,
                    args=(SCREEN_JPEG, SCREEN_JPEG),
                )
                for _ in range(n_threads)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        assert max_seen[0] <= va._CV_MAX_CONCURRENT
