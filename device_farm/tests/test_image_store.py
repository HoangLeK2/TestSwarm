"""
tests/test_image_store.py — Unit tests for services/image_store.py

Run: pytest tests/test_image_store.py -v
"""
from __future__ import annotations

import base64
import importlib
from unittest.mock import patch

import pytest

import services.image_store as image_store
from services import minio_store


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_module(tmp_path):
    """Each test gets a fresh captures dir and a clean module state.

    The quality gate (minio_store.is_quality_ok) is bypassed here so that the
    minimal 1×1 JPEG test fixture passes through — tests cover save logic, not
    quality validation.
    """
    image_store._CAPTURES_DIR = None
    image_store.init(tmp_path)
    with patch.object(minio_store, "is_quality_ok", return_value=True):
        yield
    image_store._CAPTURES_DIR = None


# Minimal valid JPEG bytes (1×1 white pixel)
_JPEG_BYTES = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
    b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
    b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\x1eB"
    b"\xeb\xf1\xff\xd9"
)
_B64 = base64.b64encode(_JPEG_BYTES).decode()


# ── init() ────────────────────────────────────────────────────────────────────

def test_init_creates_screenshots_dir(tmp_path):
    image_store._CAPTURES_DIR = None
    image_store.init(tmp_path / "caps")
    assert (tmp_path / "caps" / "screenshots").is_dir()


def test_dir_raises_if_not_initialised():
    image_store._CAPTURES_DIR = None
    with pytest.raises(RuntimeError, match="not initialised"):
        image_store._dir()


# ── _is_base64() ──────────────────────────────────────────────────────────────

def test_is_base64_true_for_base64_string():
    assert image_store._is_base64(_B64) is True


def test_is_base64_false_for_url_path():
    assert image_store._is_base64("/captures/screenshots/abc/step_0_screenshot.jpg") is False


def test_is_base64_false_for_empty():
    assert image_store._is_base64("") is False


# ── save_step_images() — screen.screenshot ───────────────────────────────────

def test_saves_screenshot_to_disk(tmp_path):
    steps = [{"type": "tap", "screen": {"screenshot": _B64}}]
    result = image_store.save_step_images(steps, "scen1")

    path = tmp_path / "screenshots" / "scen1" / "step_0_screenshot.jpg"
    assert path.exists()
    assert path.read_bytes() == _JPEG_BYTES


def test_replaces_screenshot_with_url_path():
    steps = [{"type": "tap", "screen": {"screenshot": _B64}}]
    result = image_store.save_step_images(steps, "scen1")

    assert result[0]["screen"]["screenshot"] == "/captures/screenshots/scen1/step_0_screenshot.jpg"


def test_saves_element_image_in_screen(tmp_path):
    steps = [{"type": "tap", "screen": {"element_image": _B64}}]
    result = image_store.save_step_images(steps, "scen2")

    path = tmp_path / "screenshots" / "scen2" / "step_0_element.jpg"
    assert path.exists()
    assert result[0]["screen"]["element_image"] == "/captures/screenshots/scen2/step_0_element.jpg"


def test_saves_both_screenshot_and_element_image(tmp_path):
    steps = [{"type": "tap", "screen": {"screenshot": _B64, "element_image": _B64}}]
    result = image_store.save_step_images(steps, "scen3")

    sc = result[0]["screen"]
    assert sc["screenshot"].endswith("step_0_screenshot.jpg")
    assert sc["element_image"].endswith("step_0_element.jpg")
    assert (tmp_path / "screenshots" / "scen3" / "step_0_screenshot.jpg").exists()
    assert (tmp_path / "screenshots" / "scen3" / "step_0_element.jpg").exists()


# ── save_step_images() — top-level element_image ─────────────────────────────

def test_saves_top_level_element_image(tmp_path):
    steps = [{"type": "tap_selector", "element_image": _B64}]
    result = image_store.save_step_images(steps, "scen4")

    path = tmp_path / "screenshots" / "scen4" / "step_0_element.jpg"
    assert path.exists()
    assert result[0]["element_image"] == "/captures/screenshots/scen4/step_0_element.jpg"


# ── save_step_images() — idempotency ─────────────────────────────────────────

def test_already_saved_path_is_not_re_saved(tmp_path):
    url = "/captures/screenshots/scen5/step_0_screenshot.jpg"
    steps = [{"type": "tap", "screen": {"screenshot": url}}]
    result = image_store.save_step_images(steps, "scen5")

    # Path unchanged
    assert result[0]["screen"]["screenshot"] == url
    # No file written (path starts with /, treated as URL)
    assert not (tmp_path / "screenshots" / "scen5" / "step_0_screenshot.jpg").exists()


# ── save_step_images() — multiple steps ──────────────────────────────────────

def test_multiple_steps_indexed_correctly(tmp_path):
    steps = [
        {"type": "tap", "screen": {"screenshot": _B64}},
        {"type": "tap", "screen": {"screenshot": _B64}},
        {"type": "swipe"},  # no images
    ]
    result = image_store.save_step_images(steps, "scen6")

    assert result[0]["screen"]["screenshot"].endswith("step_0_screenshot.jpg")
    assert result[1]["screen"]["screenshot"].endswith("step_1_screenshot.jpg")
    assert "screen" not in result[2] or "screenshot" not in result[2].get("screen", {})


# ── save_step_images() — does not mutate original ────────────────────────────

def test_does_not_mutate_original_steps():
    steps = [{"type": "tap", "screen": {"screenshot": _B64}}]
    original_val = steps[0]["screen"]["screenshot"]
    image_store.save_step_images(steps, "scen7")

    assert steps[0]["screen"]["screenshot"] == original_val


# ── save_step_images() — non-dict steps ──────────────────────────────────────

def test_non_dict_step_passed_through():
    steps = ["invalid", None, 42]
    result = image_store.save_step_images(steps, "scen8")
    assert result == steps


# ── save_step_images() — invalid base64 ──────────────────────────────────────

def test_invalid_base64_kept_in_place(caplog):
    steps = [{"type": "tap", "screen": {"screenshot": "not_valid_base64!!!"}}]
    result = image_store.save_step_images(steps, "scen9")

    # Should not raise; original value kept
    assert result[0]["screen"]["screenshot"] == "not_valid_base64!!!"


# ── delete_scenario_images() ─────────────────────────────────────────────────

def test_delete_removes_folder(tmp_path):
    steps = [{"type": "tap", "screen": {"screenshot": _B64}}]
    image_store.save_step_images(steps, "del1")
    assert (tmp_path / "screenshots" / "del1").exists()

    image_store.delete_scenario_images("del1")
    assert not (tmp_path / "screenshots" / "del1").exists()


def test_delete_nonexistent_scenario_does_not_raise():
    # Should be a no-op
    image_store.delete_scenario_images("does_not_exist")


def test_delete_only_removes_target_scenario(tmp_path):
    steps = [{"type": "tap", "screen": {"screenshot": _B64}}]
    image_store.save_step_images(steps, "keep")
    image_store.save_step_images(steps, "remove")

    image_store.delete_scenario_images("remove")

    assert (tmp_path / "screenshots" / "keep").exists()
    assert not (tmp_path / "screenshots" / "remove").exists()
