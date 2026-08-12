from __future__ import annotations

from copy import deepcopy
from typing import Any

from services.extract_profiles import (
    DEFAULT_EXTRACT_PROFILE,
    EXTRACT_STRATEGY_VERSION_DEFAULTS,
    get_profile_defaults,
    is_supported_profile,
)


_FB_TAP_COMMENT_DEFAULTS: dict[str, Any] = {
    "comment_filter": "all_comments",
    "switch_to_all_comments": True,
    "comment_filter_settle_s": 0.45,
    "comment_filter_step_pause_s": 0.35,
    "comment_filter_post_select_s": 0.85,
    "post_tap_wait_s": 0.35,
}

_NESTED_STEP_BRANCHES: tuple[str, ...] = ("then", "else", "steps")


def _normalize_nested_steps(step: dict[str, Any], normalizer) -> None:
    for branch in _NESTED_STEP_BRANCHES:
        nested = step.get(branch)
        if isinstance(nested, list):
            step[branch] = [normalizer(item) for item in nested if isinstance(item, dict)]


def normalize_fb_tap_comment_step(raw_step: dict[str, Any]) -> dict[str, Any]:
    step = deepcopy(raw_step)
    step_type = str(step.get("type") or "")
    if step_type not in {
        "fb_tap_comment_button",
        "tap_fb_comment_button",
        "fb_find_comment_button",
        "fb_tap_comment_target",
        "fb_apply_comment_filter",
    }:
        return step
    for key, val in _FB_TAP_COMMENT_DEFAULTS.items():
        step.setdefault(key, val)
    if step.get("require_post_before_comment") is None and step.get("pre_scroll"):
        step["require_post_before_comment"] = True
    _normalize_nested_steps(step, normalize_scenario_step)
    return step


def normalize_scenario_step(raw_step: dict[str, Any]) -> dict[str, Any]:
    step = deepcopy(raw_step)
    step_type = str(step.get("type") or "")
    if step_type == "extract":
        return normalize_extract_step(step)
    if step_type in {
        "fb_tap_comment_button",
        "tap_fb_comment_button",
        "fb_find_comment_button",
        "fb_tap_comment_target",
        "fb_apply_comment_filter",
    }:
        return normalize_fb_tap_comment_step(step)
    _normalize_nested_steps(step, normalize_scenario_step)
    return step


def normalize_extract_step(raw_step: dict[str, Any]) -> dict[str, Any]:
    step = deepcopy(raw_step)
    strategy = str(step.get("strategy") or "fb_posts")
    profile = str(step.get("extract_profile") or step.get("profile") or "")

    resolved_profile = profile if profile and is_supported_profile(profile) else DEFAULT_EXTRACT_PROFILE
    defaults = get_profile_defaults(resolved_profile, strategy)
    if not defaults and strategy.endswith("_posts"):
        # ig_posts / tiktok_posts / … reuse fb_posts expand defaults when no profile slice exists.
        defaults = get_profile_defaults(resolved_profile, "fb_posts")
    if defaults:
        for key, val in defaults.items():
            step.setdefault(key, val)
    elif strategy.endswith("_posts"):
        step.setdefault("expand_see_more", True)
        step.setdefault("expand_see_more_max_passes", 4)
        step.setdefault("expand_completion_retries", 4)

    step.setdefault("strategy", strategy)
    if profile:
        step.setdefault("extract_profile", profile)
    step.setdefault(
        "strategy_version",
        EXTRACT_STRATEGY_VERSION_DEFAULTS.get(strategy, f"{strategy}:v1"),
    )
    if strategy in {
        "fb_posts",
        "fb_comments",
        "fb_pages",
        "text_nodes",
        "ig_posts",
        "tiktok_posts",
        "linkedin_posts",
        "auto_posts",
        "ig_comments",
        "tiktok_comments",
        "linkedin_comments",
        "auto_comments",
    }:
        if step.get("edge_extra_data") is None:
            step.pop("edge_extra_data", None)
        step.setdefault("edge_extra_data", True)

    # Alias used by extract inline-save templates.
    if not step.get("parent_id_var") and step.get("save_parent_id_var"):
        step["parent_id_var"] = step["save_parent_id_var"]

    return step


def resolve_extract_profile(step: dict[str, Any], fallback: str = DEFAULT_EXTRACT_PROFILE) -> str:
    profile = str(step.get("extract_profile") or step.get("profile") or "").strip()
    if profile and is_supported_profile(profile):
        return profile
    return fallback


def normalize_save_extraction_step(raw_step: dict[str, Any]) -> dict[str, Any]:
    step = deepcopy(raw_step)
    if not step.get("parent_id_var") and step.get("save_parent_id_var"):
        step["parent_id_var"] = step["save_parent_id_var"]
    # Epic 06: no generic default — caller must declare platform-qualified type.
    step.setdefault("collection", "default")
    step.setdefault("dedup_action", "skip")
    return step


def extract_data_var_for_strategy(step: dict[str, Any]) -> str:
    strategy = str(step.get("strategy") or "fb_posts")
    override = str(step.get("extract_var") or "").strip()
    if override:
        return override
    if strategy.endswith("_comments"):
        return "comments"
    if strategy == "text_nodes":
        return "text_nodes"
    return "posts"
