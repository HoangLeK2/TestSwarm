"""Materialize Epic 04 DSL steps for legacy scenario executor / Temporal activities."""
from __future__ import annotations

from typing import Any

_DSL_TO_LEGACY_TYPE: dict[str, str] = {
    "input_wait.wait": "wait",
    "input_wait.wait_element": "wait_element",
    "input_wait.input_text": "input_text",
    "input_wait.key": "key",
    "interaction.tap": "tap_selector",
    "interaction.swipe": "swipe_ratio",
    "interaction.long_tap": "long_tap_selector",
    "interaction.double_tap": "double_tap",
    "interaction.scroll": "scroll_down",
    "interaction.drag": "drag",
    "interaction.pinch": "pinch",
    "navigation.open_app": "launch_app",
    "navigation.open_url": "open_url",
    "navigation.stop_app": "stop_app",
    "navigation.clear_app": "clear_app",
    "navigation.wait_app": "wait_app",
    "verification.verify_screen": "verify_screen",
    "verification.assert_element": "assert_element",
    "variables_control.set_variable": "set_variable",
    "variables_control.if_variable": "if_variable",
    "variables_control.repeat": "repeat",
    "variables_control.loop": "loop",
    "variables_control.break_if": "break_if",
    "composition.run_scenario": "run_scenario",
    "extraction_content.extract": "extract",
    "extraction_content.extract_text_hierarchy": "extract_text_hierarchy",
    "extraction_content.extract_text_ocr": "extract_text_ocr",
    "extraction_content.save_extraction": "save_extraction",
}


def materialize_legacy_step(step: dict[str, Any]) -> dict[str, Any]:
    """Flatten org-scenario DSL (`type` + `config`) into executor leaf step shape."""
    if not isinstance(step, dict):
        return step

    out = dict(step)
    config = out.get("config")
    if isinstance(config, dict):
        for key, value in config.items():
            if key not in out:
                out[key] = value

    step_type = str(out.get("type") or "")
    legacy_type = _DSL_TO_LEGACY_TYPE.get(step_type)
    if legacy_type:
        out["type"] = legacy_type

    for key in ("pre_capture", "post_capture", "require_capture"):
        if key in step and key not in out:
            out[key] = step[key]

    if step_type == "composition.run_scenario":
        if not out.get("scenario_id") and isinstance(config, dict):
            ref = config.get("scenario_id") or config.get("scenario_name")
            if ref:
                out["scenario_id"] = ref
        if not out.get("scenario_name") and isinstance(config, dict):
            name = config.get("scenario_name")
            if name:
                out["scenario_name"] = name

    return out
