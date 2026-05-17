from __future__ import annotations

from services.scenario_step_contract import (
    extract_data_var_for_strategy,
    normalize_extract_step,
    normalize_save_extraction_step,
)


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
    assert step["max_items"] >= 200
    assert step["comment_scroll_passes"] >= 1


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
    assert step["content_type"] == "post"
    assert step["collection"] == "default"


def test_extract_data_var_for_strategy() -> None:
    assert extract_data_var_for_strategy({"strategy": "fb_posts"}) == "posts"
    assert extract_data_var_for_strategy({"strategy": "fb_comments"}) == "comments"
    assert extract_data_var_for_strategy({"strategy": "text_nodes"}) == "text_nodes"
