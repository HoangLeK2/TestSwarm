"""Unit tests for the verify_screen step handler."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_sc():
    from tasks.scenario.context import ScenarioContext

    device = MagicMock()
    device.serial = "test"
    device.screen_width = 1080
    device.screen_height = 1920
    device.take_screenshot.return_value = b"screen"
    return ScenarioContext.from_args(device, {"steps": []})


def test_verify_screen_template_key_uses_stored_image_template():
    from tasks.scenario.steps import wait as wait_steps

    wait_steps._VERIFY_TEMPLATE_CACHE.clear()
    result = {"ok": True}

    with patch(
        "services.minio_store.get_object_bytes",
        return_value=b"template-image",
    ) as get_template, patch(
        "runtime.visual_anchor.wait_for_element_image",
        return_value=(10, 20, 0.91),
    ) as wait_for_element, patch(
        "runtime.visual_anchor.wait_for_screen_match"
    ) as wait_for_screen:
        wait_steps.handle_verify_screen(
            _make_sc(),
            {
                "type": "verify_screen",
                "template_key": "org/scenario/template.png",
                "ssim_threshold": 0.8,
                "timeout": 3,
                "poll": 0.2,
            },
            0,
            result,
        )

    assert result["ok"] is True
    assert result["image_confidence"] == 0.91
    assert "image confidence=0.910" in result["message"]
    get_template.assert_called_once_with("org/scenario/template.png")
    wait_for_element.assert_called_once()
    wait_for_screen.assert_not_called()


def test_verify_screen_legacy_screenshot_still_uses_ssim():
    from tasks.scenario.steps import wait as wait_steps

    result = {"ok": True}

    with patch(
        "runtime.visual_anchor._b64_to_bytes",
        return_value=b"legacy-screenshot",
    ) as decode, patch(
        "runtime.visual_anchor.wait_for_screen_match",
        return_value=(True, 0.88),
    ) as wait_for_screen, patch(
        "runtime.visual_anchor.wait_for_element_image"
    ) as wait_for_element:
        wait_steps.handle_verify_screen(
            _make_sc(),
            {
                "type": "verify_screen",
                "screenshot": "data:image/jpeg;base64,legacy",
                "ssim_threshold": 0.75,
            },
            0,
            result,
        )

    assert result["ok"] is True
    assert result["ssim"] == 0.88
    assert "SSIM=0.880" in result["message"]
    decode.assert_called_once_with("data:image/jpeg;base64,legacy")
    wait_for_screen.assert_called_once()
    wait_for_element.assert_not_called()
