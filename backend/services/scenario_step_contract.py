from __future__ import annotations

from copy import deepcopy
from typing import Any

from services.extract_profiles import (
    DEFAULT_EXTRACT_PROFILE,
    EXTRACT_ENTITY_VERSION_DEFAULTS,
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


def normalize_social_comment_step(raw_step: dict[str, Any]) -> dict[str, Any]:
    step = deepcopy(raw_step)
    step_type = str(step.get("type") or "")
    if step_type not in {
        "social_open_comments",
        "social_find_comment_button",
        "social_tap_comment_target",
        "social_apply_comment_filter",
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
        "social_open_comments",
        "social_find_comment_button",
        "social_tap_comment_target",
        "social_apply_comment_filter",
    }:
        return normalize_social_comment_step(step)
    _normalize_nested_steps(step, normalize_scenario_step)
    return step


def normalize_extract_step(raw_step: dict[str, Any]) -> dict[str, Any]:
    from tasks.scenario.steps.extraction import (
        EDGE_CONTENT_ENTITIES,
        resolve_extract_target,
    )

    step = deepcopy(raw_step)
    entity, platform = resolve_extract_target(step)
    profile = str(step.get("extract_profile") or step.get("profile") or "")

    resolved_profile = profile if profile and is_supported_profile(profile) else DEFAULT_EXTRACT_PROFILE
    defaults = get_profile_defaults(resolved_profile, entity)
    if defaults:
        for key, val in defaults.items():
            step.setdefault(key, val)
    elif entity == "posts":
        step.setdefault("expand_see_more", True)
        step.setdefault("expand_see_more_max_passes", 4)
        step.setdefault("expand_completion_retries", 4)

    step.setdefault("entity", entity)
    step.setdefault("platform", platform)
    if profile:
        step.setdefault("extract_profile", profile)
    step.setdefault(
        "entity_version",
        EXTRACT_ENTITY_VERSION_DEFAULTS.get(entity, f"{entity}:v1"),
    )
    if entity in EDGE_CONTENT_ENTITIES and entity != "groups":
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


def extract_data_var_for_entity(step: dict[str, Any]) -> str:
    override = str(step.get("extract_var") or "").strip()
    if override:
        return override
    entity = str(step.get("entity") or "posts").strip().casefold()
    if entity in {"comments", "text_nodes", "groups", "pages"}:
        return entity
    return "posts"
