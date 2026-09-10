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
            "then": [{"type": "extract", "entity": "comments", "platform": "facebook"}],
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
            "entity": "comments", "platform": "facebook",
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
            "entity": "comments", "platform": "facebook",
            "extract_profile": "safe",
            "max_items": 123,
        }
    )
    assert step["max_items"] == 123
    assert step["extract_profile"] == "safe"


def test_normalize_extract_step_without_profile_applies_fb_comments_edge_defaults() -> None:
    step = normalize_extract_step({"type": "extract", "entity": "comments", "platform": "facebook"})
    assert "extract_profile" not in step
    assert step["comment_scroll_passes"] >= 1
    assert step["max_items"] >= 50
    assert step["min_comment_scan_passes"] >= 1


def test_normalize_extract_step_applies_fb_posts_open_post_default() -> None:
    step = normalize_extract_step(
        {"type": "extract", "entity": "posts", "platform": "facebook", "extract_profile": "balanced"}
    )
    assert step.get("open_post_before_extract") is True
    assert step.get("open_post_press_back_after_extract") is False
    assert step.get("post_open_verify_retries") == 3
    assert step.get("post_open_verify_retry_pause_s") == 0.8


def test_normalize_alias_for_parent_id_var() -> None:
    step = normalize_extract_step(
        {
            "type": "extract",
            "entity": "comments", "platform": "facebook",
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
    assert extract_data_var_for_entity({"entity": "posts", "platform": "facebook"}) == "posts"
    assert extract_data_var_for_entity({"entity": "comments", "platform": "facebook"}) == "comments"
    assert extract_data_var_for_entity({"entity": "text_nodes", "platform": "ui"}) == "text_nodes"


def test_scenario_model_accepts_extract_profile_variable() -> None:
    scenario = {
        "steps": [
            {
                "type": "loop",
                "count": 2,
                "steps": [
                    {
                        "type": "extract",
                        "entity": "posts", "platform": "facebook",
                        "extract_profile": "${EXTRACT_PROFILE}",
                    },
                    {
                        "type": "social_open_comments",
                        "then": [
                            {
                                "type": "extract",
                                "entity": "comments", "platform": "facebook",
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
                    {"type": "social_find_comment_button", "timeout": 6},
                    {"type": "social_tap_comment_target", "post_tap_wait_s": 0.35},
                    {
                        "type": "social_apply_comment_filter",
                        "comment_filter": "all_comments",
                    },
                    {"type": "extract", "entity": "comments", "platform": "facebook"},
                ],
            }
        ],
    }

    assert ScenarioModel.validate_dict(scenario) == []


def test_scenario_model_accepts_use_source_pool_step() -> None:
    scenario = {
        "steps": [
            {
                "type": "use_source_pool",
                "platform": "facebook",
                "entity_type": "group",
                "search": "OpenClaw",
                "output_prefix": "GROUP",
                "statuses": ["candidate", "active"],
            },
            {"type": "extract", "entity": "posts", "platform": "facebook"},
        ],
    }

    assert ScenarioModel.validate_dict(scenario) == []


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
                    "entity": "posts", "platform": "facebook",
                    "extract_profile": "turbo",
                }
            ]
        }
    )
    assert errors
    assert "extract_profile" in errors[0]


def test_fb_feed_keyword_like_comment_scenario_uses_existing_nodes_and_1_5s_timeouts() -> None:
    path = Path(__file__).resolve().parents[1] / "scenarios" / "fb_feed_keyword_like_comment.json"
    scenario = json.loads(path.read_text(encoding="utf-8"))

    assert ScenarioModel.validate_dict(scenario) == []

    steps = _walk_steps(scenario["steps"])
    assert {step["type"] for step in steps} <= set(SCENARIO_STEP_TYPES)
    assert [step["type"] for step in steps].count("social_scan_posts_interact") == 3
    assert [step.get("comment_text") for step in steps if step["type"] == "social_scan_posts_interact"] == [
        "Chúc các bé chăm ngoan học giỏi",
        "Tuyệt",
        "Rất vui được giao lưu ạ",
    ]
    assert all(step["timeout"] == 1.5 for step in steps if "timeout" in step)


def test_fb_feed_keyword_like_comment_template_matches_timeout_contract() -> None:
    from db.seeds.scenario_templates import _FACEBOOK_TEMPLATES

    template = next(
        item
        for item in _FACEBOOK_TEMPLATES
        if item["name"] == "Nuôi Facebook - Like/comment Feed theo keyword"
    )

    steps = _walk_steps(template["steps"])
    assert ScenarioModel.validate_dict({"steps": template["steps"], "variables": template["variables"]}) == []
    assert [step["type"] for step in steps].count("social_scan_posts_interact") == 3
    assert all(step["timeout"] == 1.5 for step in steps if "timeout" in step)


def test_facebook_social_scan_templates_use_short_scan_timeouts() -> None:
    from db.seeds.scenario_templates import _FACEBOOK_TEMPLATES

    templates = [
        template
        for template in _FACEBOOK_TEMPLATES
        if any(step["type"] == "social_scan_posts_interact" for step in _walk_steps(template["steps"]))
    ]

    assert templates
    for template in templates:
        variables = template.get("variables") or {}
        if "POST_SCAN_TIMEOUT_SECONDS" in variables:
            assert variables["POST_SCAN_TIMEOUT_SECONDS"] <= 1.5, template["name"]
        if "COMMENTER_STEP_TIMEOUT" in variables:
            assert variables["COMMENTER_STEP_TIMEOUT"] <= 1.5, template["name"]
        if "MAX_SCROLLS" in variables:
            assert variables["MAX_SCROLLS"] <= 1, template["name"]
