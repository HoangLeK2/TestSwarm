from __future__ import annotations

from api.schemas.scenario import ScenarioModel
from services.scenario_step_contract import (
    extract_data_var_for_strategy,
    normalize_extract_step,
    normalize_fb_tap_comment_step,
    normalize_save_extraction_step,
)


def test_normalize_fb_tap_comment_step_applies_crawl_defaults() -> None:
    step = normalize_fb_tap_comment_step(
        {
            "type": "fb_tap_comment_button",
            "pre_scroll": True,
            "then": [{"type": "extract", "strategy": "fb_comments"}],
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
            "strategy": "fb_comments",
            "extract_profile": "balanced",
        }
    )
    assert step["extract_profile"] == "balanced"
    assert step["strategy_version"] == "fb_comments:v1"
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
            "strategy": "fb_comments",
            "extract_profile": "safe",
            "max_items": 123,
        }
    )
    assert step["max_items"] == 123
    assert step["extract_profile"] == "safe"


def test_normalize_extract_step_without_profile_applies_fb_comments_edge_defaults() -> None:
    step = normalize_extract_step({"type": "extract", "strategy": "fb_comments"})
    assert "extract_profile" not in step
    assert step["comment_scroll_passes"] >= 1
    assert step["max_items"] >= 50
    assert step["min_comment_scan_passes"] >= 1


def test_normalize_extract_step_applies_fb_posts_open_post_default() -> None:
    step = normalize_extract_step(
        {"type": "extract", "strategy": "fb_posts", "extract_profile": "balanced"}
    )
    assert step.get("open_post_before_extract") is True
    assert step.get("open_post_press_back_after_extract") is False


def test_normalize_alias_for_parent_id_var() -> None:
    step = normalize_extract_step(
        {
            "type": "extract",
            "strategy": "fb_comments",
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


def test_extract_data_var_for_strategy() -> None:
    assert extract_data_var_for_strategy({"strategy": "fb_posts"}) == "posts"
    assert extract_data_var_for_strategy({"strategy": "fb_comments"}) == "comments"
    assert extract_data_var_for_strategy({"strategy": "text_nodes"}) == "text_nodes"


def test_scenario_model_accepts_extract_profile_variable() -> None:
    scenario = {
        "steps": [
            {
                "type": "loop",
                "count": 2,
                "steps": [
                    {
                        "type": "extract",
                        "strategy": "fb_posts",
                        "extract_profile": "${EXTRACT_PROFILE}",
                    },
                    {
                        "type": "tap_fb_comment_button",
                        "then": [
                            {
                                "type": "extract",
                                "strategy": "fb_comments",
                                "extract_profile": "${EXTRACT_PROFILE}",
                            }
                        ],
                    },
                ],
            }
        ],
        "variables": {"EXTRACT_PROFILE": "balanced"},
    }
    assert ScenarioModel.validate_dict(scenario) == []


def test_scenario_model_accepts_split_fb_comment_steps() -> None:
    scenario = {
        "steps": [
            {
                "type": "loop",
                "count": 1,
                "steps": [
                    {"type": "fb_find_comment_button", "timeout": 6},
                    {"type": "fb_tap_comment_target", "post_tap_wait_s": 0.35},
                    {
                        "type": "fb_apply_comment_filter",
                        "comment_filter": "all_comments",
                    },
                    {"type": "extract", "strategy": "fb_comments"},
                ],
            }
        ],
    }

    assert ScenarioModel.validate_dict(scenario) == []


def test_scenario_model_rejects_invalid_extract_profile() -> None:
    errors = ScenarioModel.validate_dict(
        {
            "steps": [
                {
                    "type": "extract",
                    "strategy": "fb_posts",
                    "extract_profile": "turbo",
                }
            ]
        }
    )
    assert errors
    assert "extract_profile" in errors[0]
