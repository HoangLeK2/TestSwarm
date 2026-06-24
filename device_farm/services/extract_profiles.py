from __future__ import annotations

from copy import deepcopy
from typing import Any, Final

EXTRACT_STRATEGY_VERSION_DEFAULTS: dict[str, str] = {
    "fb_posts": "fb_posts:v1",
    "fb_comments": "fb_comments:v1",
    "text_nodes": "text_nodes:v1",
    "ig_posts": "ig_posts:v1",
    "tiktok_posts": "tiktok_posts:v1",
    "linkedin_posts": "linkedin_posts:v1",
    "auto_posts": "auto_posts:v1",
    "ig_comments": "ig_comments:v1",
    "tiktok_comments": "tiktok_comments:v1",
    "linkedin_comments": "linkedin_comments:v1",
    "auto_comments": "auto_comments:v1",
}

DEFAULT_EXTRACT_PROFILE: Final[str] = "balanced"
SUPPORTED_EXTRACT_PROFILES: Final[tuple[str, ...]] = ("balanced", "aggressive", "safe")
SUPPORTED_EXTRACT_STRATEGIES: Final[tuple[str, ...]] = tuple(EXTRACT_STRATEGY_VERSION_DEFAULTS)

_FB_POSTS_BALANCED: Final[dict[str, Any]] = {
    "open_post_before_extract": True,
    "open_post_press_back_after_extract": False,
    "open_post_tap_settle_s": 0.65,
    "expand_see_more": True,
    "expand_see_more_fast": True,
    "expand_see_more_max_passes": 3,
    "expand_completion_retries": 1,
    "expand_see_more_scroll_distance": 0.25,
    "expand_see_more_wall_s": 18,
}
_FB_POSTS_AGGRESSIVE: Final[dict[str, Any]] = {
    "open_post_before_extract": True,
    "open_post_press_back_after_extract": False,
    "open_post_tap_settle_s": 0.55,
    "expand_see_more": True,
    "expand_see_more_fast": True,
    "expand_see_more_max_passes": 5,
    "expand_completion_retries": 2,
    "expand_see_more_scroll": True,
    "expand_see_more_scroll_distance": 0.3,
    "expand_see_more_wall_s": 28,
}
_FB_POSTS_SAFE: Final[dict[str, Any]] = {
    "open_post_before_extract": True,
    "open_post_press_back_after_extract": False,
    "open_post_max_attempts": 1,
    "open_post_tap_settle_s": 0.75,
    "expand_see_more": True,
    "expand_see_more_fast": True,
    "expand_see_more_max_passes": 2,
    "expand_completion_retries": 1,
    "expand_see_more_scroll_distance": 0.2,
    "expand_see_more_wall_s": 12,
}

_FB_COMMENTS_BALANCED: Final[dict[str, Any]] = {
    "expand_see_more": False,
    "hierarchy_compressed": True,
    "hierarchy_dump_timeout_s": 1.5,
    "max_items": 220,
    "comment_scroll_passes": 16,
    "comment_swipes_per_dump": 6,
    "comment_scroll_distance": 0.60,
    "comment_scroll_duration_ms": 90,
    "comment_scroll_pause_s": 0.0,
    "comment_scroll_settle_s": 0.02,
    "comment_scroll_wall_s": 16,
    "comment_recover_chrome": True,
    "comment_no_growth_break": 2,
    "min_comment_scan_passes": 1,
    "comment_max_snapshots": 10,
    "comment_stop_if_no_new": True,
    "stop_if_no_new": True,
    "no_new_threshold": 2,
}
_FB_COMMENTS_AGGRESSIVE: Final[dict[str, Any]] = {
    "expand_see_more": False,
    "hierarchy_compressed": True,
    "hierarchy_dump_timeout_s": 1.8,
    "max_items": 700,
    "comment_scroll_passes": 60,
    "comment_swipes_per_dump": 6,
    "comment_scroll_distance": 0.58,
    "comment_scroll_duration_ms": 100,
    "comment_scroll_pause_s": 0.02,
    "comment_scroll_wall_s": 45,
    "comment_no_growth_break": 3,
    "min_comment_scan_passes": 2,
    "comment_max_snapshots": 32,
    "comment_stop_if_no_new": False,
    "stop_if_no_new": False,
    "no_new_threshold": 5,
}
_FB_COMMENTS_SAFE: Final[dict[str, Any]] = {
    "expand_see_more": False,
    "hierarchy_compressed": True,
    "max_items": 160,
    "comment_scroll_passes": 12,
    "comment_swipes_per_dump": 2,
    "comment_scroll_distance": 0.24,
    "comment_scroll_duration_ms": 360,
    "comment_scroll_pause_s": 0.26,
    "comment_scroll_wall_s": 20,
    "comment_no_growth_break": 3,
    "min_comment_scan_passes": 2,
    "comment_max_snapshots": 8,
    "comment_stop_if_no_new": True,
    "stop_if_no_new": True,
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
