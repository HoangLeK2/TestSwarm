"""Migration 111 rewrite rules + the regression guard for platform-neutral nodes."""

from __future__ import annotations

import copy
import re

import pytest

from common.scenario_schema import SCENARIO_STEP_TYPES
from services.scenario_migrations.social_node_rename import (
    migrate_graph_nodes,
    migrate_scenario_blob,
    migrate_step_types,
)
from services.social_ext import supports_step
from services.social_ext.contract import SOCIAL_STEP_TYPES

_PLATFORM_NAMED = re.compile(r"(^|_)(fb|facebook|ig|instagram|tiktok|linkedin|threads)(_|$)")


# ── The actual goal: no node names a platform ────────────────────────────────

def test_no_scenario_step_type_names_a_platform() -> None:
    offenders = [t for t in SCENARIO_STEP_TYPES if _PLATFORM_NAMED.search(t)]
    assert offenders == [], (
        "step types are public API and must stay platform-neutral; "
        f"offenders: {offenders}"
    )


def test_registered_handlers_match_neutral_vocabulary() -> None:
    import tasks.scenario.steps as steps_mod

    offenders = [t for t in steps_mod._STEP_HANDLERS if _PLATFORM_NAMED.search(t)]
    assert offenders == []


def test_social_vocabulary_is_declared_in_schema() -> None:
    missing = sorted(SOCIAL_STEP_TYPES - set(SCENARIO_STEP_TYPES))
    assert missing == [], f"social_ext declares steps the schema rejects: {missing}"


def test_retired_types_are_not_dispatchable_but_explain_themselves() -> None:
    import tasks.scenario.steps as steps_mod

    for retired in steps_mod._RETIRED_STEP_TYPES:
        assert retired not in steps_mod._STEP_HANDLERS


# ── Step tree rewrites ───────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "old_type,new_type",
    [
        ("facebook_session_gate", "platform_session_gate"),
        ("fb_connect_visible_people", "social_connect_visible_people"),
        ("fb_find_comment_button", "social_find_comment_button"),
        ("fb_tap_comment_target", "social_tap_comment_target"),
        ("fb_apply_comment_filter", "social_apply_comment_filter"),
        ("fb_tap_comment_button", "social_open_comments"),
        ("tap_fb_comment_button", "social_open_comments"),
        ("fb_scan_posts_interact", "social_scan_posts_interact"),
    ],
)
def test_step_type_renames(old_type: str, new_type: str) -> None:
    steps = [{"type": old_type}]
    assert migrate_step_types(steps) is True
    assert steps[0]["type"] == new_type
    assert steps[0]["platform"] == "facebook"


def test_select_target_merge_keeps_variant() -> None:
    steps = [
        {"type": "fb_select_people_profile", "display_name": "A"},
        {"type": "fb_select_post_target", "display_text": "B"},
    ]
    assert migrate_step_types(steps) is True
    assert steps[0]["type"] == "social_select_target"
    assert steps[0]["target_type"] == "person"
    assert steps[0]["display_name"] == "A"
    assert steps[1]["type"] == "social_select_target"
    assert steps[1]["target_type"] == "post"
    assert steps[1]["display_text"] == "B"


def test_extract_strategy_becomes_entity_and_platform() -> None:
    steps = [
        {"type": "extract", "strategy": "fb_comments", "strategy_version": "fb_comments:v1"},
        {"type": "extract", "strategy": "ig_posts"},
        {"type": "extract", "strategy": "auto_comments"},
        {"type": "extract", "strategy": "text_nodes"},
    ]
    assert migrate_step_types(steps) is True
    assert steps[0] == {
        "type": "extract",
        "entity": "comments",
        "platform": "facebook",
        "entity_version": "comments:v1",
    }
    assert (steps[1]["entity"], steps[1]["platform"]) == ("posts", "instagram")
    assert (steps[2]["entity"], steps[2]["platform"]) == ("comments", "auto")
    assert (steps[3]["entity"], steps[3]["platform"]) == ("text_nodes", "ui")


def test_explicit_platform_is_never_overwritten() -> None:
    steps = [{"type": "extract", "strategy": "fb_posts", "platform": "instagram"}]
    migrate_step_types(steps)
    assert steps[0]["platform"] == "instagram"


def test_nested_branches_and_random_pick_are_rewritten() -> None:
    steps = [
        {
            "type": "loop",
            "steps": [
                {
                    "type": "tap_fb_comment_button",
                    "then": [{"type": "extract", "strategy": "fb_comments"}],
                    "else": [{"type": "fb_apply_comment_filter"}],
                }
            ],
        },
        {
            "type": "random_pick",
            "branches": [{"steps": [{"type": "fb_scan_posts_interact"}]}],
        },
    ]
    assert migrate_step_types(steps) is True
    inner = steps[0]["steps"][0]
    assert inner["type"] == "social_open_comments"
    assert inner["then"][0]["entity"] == "comments"
    assert inner["else"][0]["type"] == "social_apply_comment_filter"
    assert steps[1]["branches"][0]["steps"][0]["type"] == "social_scan_posts_interact"


def test_variable_and_ctx_key_renames() -> None:
    steps = [
        {"type": "set_variable", "name": "FACEBOOK_SESSION_READY", "value": True},
        {"type": "extract", "strategy": "fb_comments", "parent_post_id_var": "_fb_comment_parent_pid"},
        {"type": "set_var", "name": "MSG", "value": "ready=${FACEBOOK_SESSION_READY}"},
    ]
    assert migrate_step_types(steps) is True
    assert steps[0]["name"] == "PLATFORM_SESSION_READY"
    assert steps[1]["parent_post_id_var"] == "_comment_parent_pid"
    assert steps[2]["value"] == "ready=${PLATFORM_SESSION_READY}"


def test_untouched_steps_report_no_change() -> None:
    steps = [{"type": "tap", "x": 1}, {"type": "wait", "seconds": 2}]
    before = copy.deepcopy(steps)
    assert migrate_step_types(steps) is False
    assert steps == before


# ── Graph node rewrites (the column migration 078 missed) ────────────────────

def test_graph_nodes_rewrite_type_and_config() -> None:
    nodes = [
        {"id": "n1", "type": "fb_tap_comment_button", "config": {"timeout": 6}, "order": "a0"},
        {"id": "n2", "type": "extract", "config": {"strategy": "fb_posts"}, "order": "a1"},
        {"id": "n3", "type": "tap", "config": {"x": 1}, "order": "a2"},
    ]
    assert migrate_graph_nodes(nodes) is True
    assert nodes[0]["type"] == "social_open_comments"
    assert nodes[0]["config"]["timeout"] == 6
    assert nodes[1]["config"]["entity"] == "posts"
    assert "strategy" not in nodes[1]["config"]
    assert nodes[2] == {"id": "n3", "type": "tap", "config": {"x": 1}, "order": "a2"}


def test_scenario_blob_covers_steps_nodes_and_variables() -> None:
    blob = {
        "name": "s",
        "steps": [{"type": "fb_scan_posts_interact"}],
        "nodes": [{"id": "x", "type": "facebook_session_gate", "config": {}}],
        "variables": {"FACEBOOK_SESSION_READY": True},
    }
    assert migrate_scenario_blob(blob) is True
    assert blob["steps"][0]["type"] == "social_scan_posts_interact"
    assert blob["nodes"][0]["type"] == "platform_session_gate"
    assert blob["variables"] == {"PLATFORM_SESSION_READY": True}


# ── Idempotency: the migration may be re-run safely ──────────────────────────

def test_all_rewrites_are_idempotent() -> None:
    blob = {
        "steps": [
            {"type": "facebook_session_gate"},
            {"type": "fb_select_people_profile"},
            {
                "type": "tap_fb_comment_button",
                "then": [{"type": "extract", "strategy": "fb_comments"}],
            },
        ],
        "nodes": [{"id": "n", "type": "fb_select_post_target", "config": {}}],
        "variables": {"FACEBOOK_SESSION_READY": True},
    }
    assert migrate_scenario_blob(blob) is True
    once = copy.deepcopy(blob)
    assert migrate_scenario_blob(blob) is False
    assert blob == once


def test_migrated_seed_templates_need_no_further_migration() -> None:
    import db.seeds.scenario_templates as seeds

    checked = 0
    for name in dir(seeds):
        value = getattr(seeds, name)
        for blob in value if isinstance(value, list) else [value]:
            if isinstance(blob, dict) and isinstance(blob.get("steps"), list):
                checked += 1
                assert migrate_step_types(copy.deepcopy(blob["steps"])) is False, (
                    f"seed template {name} is not on the neutral vocabulary"
                )
    assert checked > 0


# ── Platform support gating replaces the hardcoded facebook checks ───────────

def test_facebook_supports_the_neutral_steps() -> None:
    for step_type in SOCIAL_STEP_TYPES:
        assert supports_step("facebook", step_type) is True


@pytest.mark.parametrize("platform", ["instagram", "tiktok", "threads"])
def test_draft_platforms_do_not_claim_social_steps(platform: str) -> None:
    assert supports_step(platform, "social_open_comments") is False
    assert supports_step(platform, "social_select_target") is False


def test_unknown_platform_is_unsupported() -> None:
    assert supports_step("myspace", "social_open_comments") is False
    assert supports_step("", "social_open_comments") is False
