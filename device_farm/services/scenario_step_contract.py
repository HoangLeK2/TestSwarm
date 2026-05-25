from __future__ import annotations

from copy import deepcopy
from typing import Any

from services.extract_profiles import (
    DEFAULT_EXTRACT_PROFILE,
    EXTRACT_STRATEGY_VERSION_DEFAULTS,
    get_profile_defaults,
    is_supported_profile,
)


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
    step.setdefault("content_type", "post")
    step.setdefault("collection", "default")
    step.setdefault("item_level", 0)
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
