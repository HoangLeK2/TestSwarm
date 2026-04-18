from __future__ import annotations

from copy import deepcopy
from typing import Any, Final

EXTRACT_STRATEGY_VERSION_DEFAULTS: dict[str, str] = {
    "fb_posts": "fb_posts:v1",
    "fb_comments": "fb_comments:v1",
}

DEFAULT_EXTRACT_PROFILE: Final[str] = "balanced"
SUPPORTED_EXTRACT_PROFILES: Final[tuple[str, ...]] = ("balanced", "aggressive", "safe")
SUPPORTED_EXTRACT_STRATEGIES: Final[tuple[str, ...]] = ("fb_posts", "fb_comments")

_FB_POSTS_BALANCED: Final[dict[str, Any]] = {
    "expand_see_more": True,
    "expand_see_more_max_passes": 4,
    "expand_completion_retries": 4,
    "expand_see_more_scroll_distance": 0.25,
}
_FB_POSTS_AGGRESSIVE: Final[dict[str, Any]] = {
    "expand_see_more": True,
    "expand_see_more_max_passes": 6,
    "expand_completion_retries": 6,
    "expand_see_more_scroll_distance": 0.3,
}
_FB_POSTS_SAFE: Final[dict[str, Any]] = {
    "expand_see_more": True,
    "expand_see_more_max_passes": 3,
    "expand_completion_retries": 2,
    "expand_see_more_scroll_distance": 0.2,
}

_FB_COMMENTS_BALANCED: Final[dict[str, Any]] = {
    "max_items": 400,
    "comment_scroll_passes": 20,
    "comment_scroll_distance": 0.7,
    "comment_scroll_pause_s": 0.8,
    "comment_no_growth_break": 5,
    "min_comment_scan_passes": 6,
    "stop_if_no_new": False,
    "no_new_threshold": 4,
}
_FB_COMMENTS_AGGRESSIVE: Final[dict[str, Any]] = {
    "max_items": 700,
    "comment_scroll_passes": 35,
    "comment_scroll_distance": 0.75,
    "comment_scroll_pause_s": 0.9,
    "comment_no_growth_break": 7,
    "min_comment_scan_passes": 8,
    "stop_if_no_new": False,
    "no_new_threshold": 5,
}
_FB_COMMENTS_SAFE: Final[dict[str, Any]] = {
    "max_items": 220,
    "comment_scroll_passes": 10,
    "comment_scroll_distance": 0.55,
    "comment_scroll_pause_s": 0.7,
    "comment_no_growth_break": 4,
    "min_comment_scan_passes": 4,
    "stop_if_no_new": False,
    "no_new_threshold": 3,
}


EXTRACT_PROFILES: dict[str, dict[str, dict[str, Any]]] = {
    "balanced": {
        "fb_posts": _FB_POSTS_BALANCED,
        "fb_comments": _FB_COMMENTS_BALANCED,
    },
    "aggressive": {
        "fb_posts": _FB_POSTS_AGGRESSIVE,
        "fb_comments": _FB_COMMENTS_AGGRESSIVE,
    },
    "safe": {
        "fb_posts": _FB_POSTS_SAFE,
        "fb_comments": _FB_COMMENTS_SAFE,
    },
}


def is_supported_profile(profile: str) -> bool:
    return profile in SUPPORTED_EXTRACT_PROFILES


def is_supported_strategy(strategy: str) -> bool:
    return strategy in SUPPORTED_EXTRACT_STRATEGIES


def get_profile_defaults(profile: str, strategy: str) -> dict[str, Any]:
    return deepcopy(EXTRACT_PROFILES.get(profile, {}).get(strategy, {}))
