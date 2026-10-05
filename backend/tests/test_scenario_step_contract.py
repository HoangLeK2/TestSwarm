from __future__ import annotations

import json
from pathlib import Path

from api.schemas.scenario import ScenarioModel
from common.scenario_schema import SCENARIO_STEP_TYPES
from services.scenario_step_contract import (
    extract_data_var_for_entity,
    normalize_extract_step,
    normalize_social_comment_step,
    normalize_save_extraction_step,
)


def _walk_steps(steps: list[dict]) -> list[dict]:
    found: list[dict] = []
    for step in steps:
        found.append(step)
        if isinstance(step.get("steps"), list):
            found.extend(_walk_steps(step["steps"]))
        if isinstance(step.get("then"), list):
            found.extend(_walk_steps(step["then"]))
        if isinstance(step.get("else"), list):
            found.extend(_walk_steps(step["else"]))
        for branch in step.get("branches") or []:
            if isinstance(branch, dict) and isinstance(branch.get("steps"), list):
                found.extend(_walk_steps(branch["steps"]))
    return found


def test_normalize_social_comment_step_applies_crawl_defaults() -> None:
    step = normalize_social_comment_step(
        {
            "type": "social_open_comments",
            "pre_scroll": True,
            "then": [{"type": "extract", "entity": "comments", "platform": "instagram"}],
        }
    )
    assert step["comment_filter"] == "all_comments"
    assert step["require_post_before_comment"] is True
    assert step["comment_filter_settle_s"] == 0.45
    assert step["then"][0]["comment_scroll_passes"] == 16


def test_normalize_extract_step_applies_profile_defaults_and_version() -> None:
    step = normalize_extract_step(
        {
            "type": "extract",
            "entity": "comments", "platform": "instagram",
            "extract_profile": "balanced",
        }
    )
    assert step["extract_profile"] == "balanced"
    assert step["entity_version"] == "comments:v1"
    assert step["max_items"] <= 220
    assert step["comment_scroll_passes"] == 16
    assert step["comment_swipes_per_dump"] == 6
    assert step["comment_scroll_wall_s"] == 16
    assert step["comment_scroll_pause_s"] == 0.0
    assert step["comment_scroll_settle_s"] == 0.02
    assert step["comment_stop_if_no_new"] is False
    assert step["stop_if_no_new"] is False
    assert step["comment_no_growth_break"] == 0
    assert step["min_comment_scan_passes"] == 1


def test_normalize_extract_step_keeps_explicit_values() -> None:
    step = normalize_extract_step(
        {
            "type": "extract",
            "entity": "comments", "platform": "instagram",
            "extract_profile": "safe",
            "max_items": 123,
        }
    )
    assert step["max_items"] == 123
    assert step["extract_profile"] == "safe"


def test_normalize_extract_step_without_profile_applies_comments_edge_defaults() -> None:
    step = normalize_extract_step({"type": "extract", "entity": "comments", "platform": "instagram"})
    assert "extract_profile" not in step
    assert step["comment_scroll_passes"] >= 1
    assert step["max_items"] >= 50
    assert step["min_comment_scan_passes"] >= 1


def test_normalize_extract_step_applies_posts_open_post_default() -> None:
    step = normalize_extract_step(
        {"type": "extract", "entity": "posts", "platform": "instagram", "extract_profile": "balanced"}
    )
    assert step.get("open_post_before_extract") is True
    assert step.get("open_post_press_back_after_extract") is False
    assert step.get("post_open_verify_retries") == 3
    assert step.get("post_open_verify_retry_pause_s") == 0.8


def test_normalize_alias_for_parent_id_var() -> None:
    step = normalize_extract_step(
        {
            "type": "extract",
            "entity": "comments", "platform": "instagram",
            "save_parent_id_var": "_active_comment_parent_hash",
        }
    )
    assert step["parent_id_var"] == "_active_comment_parent_hash"


def test_normalize_save_extraction_alias() -> None:
    step = normalize_save_extraction_step(
        {
            "type": "save_extraction",
            "data_var": "comments",
            "save_parent_id_var": "_active_comment_parent_hash",
        }
    )
    assert step["parent_id_var"] == "_active_comment_parent_hash"
    assert step["collection"] == "default"
    assert step.get("dedup_action") == "skip"


def test_extract_data_var_for_entity() -> None:
    assert extract_data_var_for_entity({"entity": "posts", "platform": "instagram"}) == "posts"
    assert extract_data_var_for_entity({"entity": "comments", "platform": "instagram"}) == "comments"
    assert extract_data_var_for_entity({"entity": "text_nodes", "platform": "ui"}) == "text_nodes"


def test_scenario_model_accepts_verify_screen_template_key() -> None:
    from api.schemas.scenario import ScenarioModel

    assert (
        ScenarioModel.validate_dict(
            {
                "steps": [
                    {
                        "type": "verify_screen",
                        "template_key": "org/scenario/template.png",
                        "ssim_threshold": 0.8,
                    }
                ]
            }
        )
        == []
    )


def test_scenario_model_rejects_verify_screen_without_reference_image() -> None:
    from api.schemas.scenario import ScenarioModel

    errors = ScenarioModel.validate_dict({"steps": [{"type": "verify_screen"}]})

    assert errors
    assert "template_key or screenshot" in errors[0]


def test_scenario_model_rejects_invalid_extract_profile() -> None:
    errors = ScenarioModel.validate_dict(
        {
            "steps": [
                {
                    "type": "extract",
                    "entity": "posts", "platform": "instagram",
                    "extract_profile": "turbo",
                }
            ]
        }
    )
    assert errors
    assert "extract_profile" in errors[0]


