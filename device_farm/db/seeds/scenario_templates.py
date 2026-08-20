from __future__ import annotations

"""
db/seeds/scenario_templates.py — Builtin scenario template seed data.

Called once on startup (idempotent: skipped if builtins already exist).
Templates use:
  - DF-001 variable interpolation  (${VAR})
  - DF-002 control flow            (repeat, repeat_until, if_element, if_variable, random_pick)
  - DF-006 data extraction         (extract entity=posts/comments; optional inline save via collection=…)

Template step types used:
  launch_app, open_url, wait, wait_stable, wait_element, dismiss_popup, key,
  scroll_down, swipe_ratio, tap_selector, input_selector, input_text,
  set_variable, repeat, repeat_until, if_element, if_variable, random_pick,
  login_if_needed, platform_session_gate, fill_form, assert_app_state,
  extract (optional collection → inline save), save_extraction (advanced), loop, break_if

Design rules:
  - Use wait_stable / wait_element instead of fixed waits wherever possible
  - Use set_variable + from_list for random delays/counts (natural behavior)
  - Use random_pick for probability-based actions (like, comment, follow)
  - Engagement templates use `repeat` (fixed count, no early-break needed)
  - Crawl templates use `loop` (supports ctx['_break'] from extract step)
  - Anti-spam delays are built-in and should be respected in production
  - Selectors may need updating per app version (see Maintenance Notes in DF-006 spec)
"""

from copy import deepcopy
from typing import Any, Dict, List

# entity=posts: mở chi tiết bài trước extract; back do kịch bản điều khiển (không auto trong agent).
_FB_POST_OPEN_EXTRACT: Dict[str, Any] = {
    "open_post_before_extract": True,
    "open_post_press_back_after_extract": False,
    "post_open_verify_retries": 1,
    "post_open_verify_retry_pause_s": 0.18,
}

# Sau extract comments — đóng sheet/detail để quay lại feed trước vòng kế tiếp.
_FB_RETURN_TO_FEED_AFTER_COMMENTS_STEPS: List[Dict[str, Any]] = [
    {"type": "key", "key": "back"},
    {"type": "wait", "seconds": 0.5},
    {
        "type": "if_element",
        "by": "text",
        "value": "Bài viết",
        "timeout": 1,
        "then": [
            {"type": "key", "key": "back"},
            {"type": "wait", "seconds": 1},
        ],
        "else": [],
    },
    {"type": "dismiss_popup", "retries": 1},
]


def _fb_open_comments_steps(
    *,
    comment_filter: str = "all_comments",
    timeout: int = 5,
    post_tap_wait_s: float = 0.35,
) -> List[Dict[str, Any]]:
    """Open Facebook comments as explicit sequential nodes."""
    return [
        {
            "type": "scroll_down",
            "repeats": 1,
            "start_x_ratio": 0.68,
            "start_y_ratio": 0.65,
            "end_y_ratio": 0.47,
            "ignore_error": True,
        },
        {
            "type": "social_find_comment_button", "platform": "facebook",
            "timeout": timeout,
            "require_post_before_comment": True,
            "comment_filter": comment_filter,
            "switch_to_all_comments": comment_filter == "all_comments",
            "ignore_error": True,
        },
        {
            "type": "social_tap_comment_target", "platform": "facebook",
            "post_tap_wait_s": post_tap_wait_s,
            "ignore_error": True,
        },
        {
            "type": "social_apply_comment_filter", "platform": "facebook",
            "comment_filter": comment_filter,
            "switch_to_all_comments": comment_filter == "all_comments",
            "comment_filter_settle_s": 0.45,
            "comment_filter_step_pause_s": 0.35,
            "comment_filter_post_select_s": 0.85,
        },
    ]


def _fb_open_search_result_steps(
    *,
    search_var: str,
    tab_vi: str,
    tab_en: str,
    tab_description_contains: str,
    row_text_var: str,
) -> List[Dict[str, Any]]:
    """Search Facebook, switch to a result tab, then open a configured row."""
    return [
        *_fb_open_search_tab_steps(
            search_var=search_var,
            tab_vi=tab_vi,
            tab_en=tab_en,
            tab_description_contains=tab_description_contains,
        ),
        {
            "type": "tap_selector",
            "by": "text",
            "value": f"${{{row_text_var}}}",
            "timeout": 10,
        },
        {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},
    ]


def _fb_open_search_tab_steps(
    *,
    search_var: str,
    tab_vi: str,
    tab_en: str,
    tab_description_contains: str,
) -> List[Dict[str, Any]]:
    """Search Facebook and switch to a result tab without selecting a row."""
    return [
        {
            "type": "if_element",
            "by": "content-desc",
            "value": "Tìm kiếm",
            "timeout": 5,
            "then": [
                {
                    "type": "tap_selector",
                    "by": "content-desc",
                    "value": "Tìm kiếm",
                    "timeout": 4,
                },
            ],
            "else": [{"type": "tap_ratio", "x": 0.87, "y": 0.035}],
        },
        {"type": "wait_stable", "timeout": 4, "stable_duration": 0.4},
        {
            "type": "input_text",
            "text": f"${{{search_var}}}",
            "via": "u2",
            "clear_first": True,
        },
        {"type": "wait", "seconds": 1},
        {"type": "key", "key": "enter"},
        {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},
        {
            "type": "if_element",
            "by": "descriptionContains",
            "value": tab_description_contains,
            "timeout": 5,
            "then": [
                {
                    "type": "tap_selector",
                    "by": "descriptionContains",
                    "value": tab_description_contains,
                    "timeout": 4,
                    "ignore_error": True,
                },
            ],
            "else": [
                {
                    "type": "if_element",
                    "by": "content-desc",
                    "value": tab_vi,
                    "timeout": 3,
                    "then": [
                        {
                            "type": "tap_selector",
                            "by": "text",
                            "value": tab_vi,
                            "timeout": 3,
                            "ignore_error": True,
                        },
                    ],
                    "else": [
                        {
                            "type": "tap_selector",
                            "by": "text",
                            "value": tab_en,
                            "timeout": 3,
                            "ignore_error": True,
                        }
                    ],
                }
            ],
        },
        {
            "type": "if_element",
            "by": "text",
            "value": tab_vi,
            "timeout": 1,
            "then": [{"type": "wait", "seconds": 0.1}],
            "else": [
                # Facebook search tabs are horizontally scrollable; Page/Trang
                # can sit off-screen after All/Posts/Groups/Events.
                {"type": "swipe_ratio", "x1": 0.86, "y1": 0.16, "x2": 0.22, "y2": 0.16, "duration_ms": 260},
                {"type": "wait", "seconds": 0.35},
                {
                    "type": "if_element",
                    "by": "descriptionContains",
                    "value": tab_description_contains,
                    "timeout": 2,
                    "then": [
                        {
                            "type": "tap_selector",
                            "by": "descriptionContains",
                            "value": tab_description_contains,
                            "timeout": 2,
                            "ignore_error": True,
                        }
                    ],
                    "else": [
                        {
                            "type": "if_element",
                            "by": "text",
                            "value": tab_vi,
                            "timeout": 2,
                            "then": [
                                {
                                    "type": "tap_selector",
                                    "by": "text",
                                    "value": tab_vi,
                                    "timeout": 2,
                                    "ignore_error": True,
                                }
                            ],
                            "else": [
                                {
                                    "type": "tap_selector",
                                    "by": "text",
                                    "value": tab_en,
                                    "timeout": 2,
                                    "ignore_error": True,
                                }
                            ],
                        }
                    ],
                },
            ],
        },
        {"type": "wait_stable", "timeout": 2, "stable_duration": 0.45},
    ]


def _fb_return_to_feed_steps(prefix: str) -> List[Dict[str, Any]]:
    """Back out of whatever Facebook was left showing, until the feed is up.

    `launch_app` resumes Facebook on its last screen, so a run inherits wherever
    the previous one stopped — a photo viewer, a profile, a comment sheet. Every
    selector afterwards then misses, and the failure reads as "group not found"
    rather than "we were never on the search screen". Observed on a real device:
    a tap during search navigation opened a group photo fullscreen and the whole
    run unwound from there.

    Bounded, and it never presses Back once the feed is visible, so it cannot
    walk the account out of the app.
    """
    # Guarded Backs rather than repeat_until: that step's stop condition only
    # supports exact text / resource-id / content-desc, and the home tab carries
    # "Trang chủ, Tab 1/6" — an index that shifts between builds. if_element
    # does support descriptionContains, so each Back is skipped once the tab bar
    # is back in view.
    step: List[Dict[str, Any]] = []
    for attempt in range(3):
        step.append(
            {
                "id": f"{prefix}_return_to_feed_{attempt}",
                "type": "if_element",
                "by": "descriptionContains",
                "value": "Trang chủ",
                "timeout": 2,
                "then": [],
                "else": [
                    {"type": "key", "key": "back"},
                    {"type": "wait_stable", "timeout": 4, "stable_duration": 0.4},
                ],
            }
        )
    step.append({"type": "dismiss_popup", "retries": 1})
    return step


def _fb_commenter_connect_steps(
    *,
    prefix: str,
    action_index: int,
    source_var: str = "_post_scan",
) -> List[Dict[str, Any]]:
    """Open one commenter's profile, send the request there, then unwind.

    The friend request is issued on the person's own profile rather than from a
    suggestion list: the profile shows the shared context before acting, and the
    button's own state (Add friend → Request sent) is what verifies the send. A
    list row cannot offer either, which is why this is the path a cold account
    uses — it needs no mutual friends to work.
    """
    return [
        {
            "id": f"{prefix}_open_{action_index}",
            "type": "social_open_commenter_from_post_match",
            "platform": "facebook",
            "source_var": source_var,
            "action_index": action_index,
            "required_keywords": "${PROFILE_REQUIRED_KEYWORDS}",
            "optional_keywords": "${PROFILE_OPTIONAL_KEYWORDS}",
            "forbidden_keywords": "${PROFILE_FORBIDDEN_KEYWORDS}",
            "min_score": "${PROFILE_MIN_SCORE}",
            "max_commenters": "${COMMENTER_SCAN_LIMIT}",
            # Opening a profile costs a tap, a settle and a hierarchy read, so
            # trying several runs well past the 12s step default and the flow is
            # killed mid-way through a profile it had already opened.
            "timeout": "${COMMENTER_STEP_TIMEOUT}",
            "save_as": "_people_target",
            "save_success_as": "PEOPLE_PROFILE_SELECTED",
            "save_opened_as": "COMMENTER_PROFILE_OPENED",
            "save_sheet_opened_as": "COMMENT_SHEET_OPENED",
        },
        {
            "id": f"{prefix}_connect_{action_index}",
            "type": "if_variable",
            "name": "PEOPLE_PROFILE_SELECTED",
            "equals": True,
            "then": [
                {
                    "type": "if_variable",
                    "name": "ENABLE_CONNECTION_REQUEST",
                    "equals": True,
                    "then": [
                        {
                            # The durable ledger keys an action by step id; without
                            # one it refuses the claim and the request never goes
                            # out. Unique per index so two sends in one cycle stay
                            # distinguishable.
                            "id": f"{prefix}_connection_request_{action_index}",
                            "type": "connection_request",
                            "platform": "facebook",
                            "action": "request",
                            "timeout": 5,
                            "verify_timeout": 5,
                            "settle_seconds": 0.4,
                            "require_verified_target": "_people_target",
                            "save_as": "_people_connection_action",
                            "ignore_error": True,
                        }
                    ],
                    "else": [],
                }
            ],
            "else": [],
        },
        {
            "id": f"{prefix}_back_{action_index}",
            "type": "if_variable",
            "name": "COMMENTER_PROFILE_OPENED",
            "equals": True,
            "then": [
                {"type": "key", "key": "back"},
                {"type": "wait_stable", "timeout": 4, "stable_duration": 0.4},
            ],
            "else": [],
        },
        {
            "id": f"{prefix}_close_comments_{action_index}",
            "type": "if_variable",
            "name": "COMMENT_SHEET_OPENED",
            "equals": True,
            "then": [
                {"type": "key", "key": "back"},
                {"type": "wait_stable", "timeout": 4, "stable_duration": 0.4},
            ],
            "else": [],
        },
    ]


def _fb_nurture_feed_steps(
    *,
    tag: str,
    context_var: str,
    require_verified_target: str | None = None,
    id_prefix: str | None = None,
) -> List[Dict[str, Any]]:
    """Lightweight interaction loop for the current Facebook target screen."""
    step_prefix = id_prefix or tag
    like_step: Dict[str, Any] = {
        "id": f"{step_prefix}_nurture_like_${{_TOUCH_INDEX}}",
        "type": "content_interaction",
        "platform": "facebook",
        "action": "like",
        "timeout": 4,
        "verify_timeout": 4,
        "settle_seconds": 0.35,
        "save_as": "_last_nurture_action",
        "ignore_error": True,
    }
    if tag == "fanpage":
        like_step["post_capture"] = True
    if require_verified_target:
        like_step["require_verified_target"] = require_verified_target
    return [
        {
            "type": "loop",
            "count": "${MAX_TOUCHES}",
            "loop_var": "_TOUCH_INDEX",
            "steps": [
                {"type": "dismiss_popup", "retries": 1},
                {
                    "type": "random_pick",
                    "branches": [
                        {
                            "weight": 3,
                            "steps": [like_step],
                        },
                        {
                            "weight": 1,
                            "steps": [
                                {"type": "wait", "seconds": "${ACTION_WAIT_SECONDS}"},
                            ],
                        },
                    ],
                },
                {
                    "type": "scroll_down",
                    "repeats": 1,
                    "start_x_ratio": "${SCROLL_X_RATIO}",
                    "start_y_ratio": 0.65,
                    "end_y_ratio": 0.47,
                },
                {
                    "type": "set_variable",
                    "name": "_W",
                    "from_list": [1, 1.5, 2, 2.5, 3],
                },
                {"type": "wait", "seconds": "${_W}"},
            ],
        },
        {
            "type": "set_variable",
            "name": "_nurture_target",
            "value": f"{tag}:${{{context_var}}}",
        },
    ]


def _fb_post_like_and_comment_steps(
    *,
    require_verified_target: str,
    account_action_id: str | None = None,
    save_prefix: str = "_post",
) -> List[Dict[str, Any]]:
    like_step: Dict[str, Any] = {
        "type": "content_interaction",
        "platform": "facebook",
        "action": "like",
        "timeout": 5,
        "verify_timeout": 5,
        "settle_seconds": 0.35,
        "require_verified_target": require_verified_target,
        "save_as": f"{save_prefix}_like_action",
    }
    if account_action_id:
        like_step["account_action_id"] = account_action_id
    return [
        like_step,
        {
            "type": "content_interaction",
            "platform": "facebook",
            "action": "comment",
            "timeout": 5,
            "verify_timeout": 5,
            "settle_seconds": 0.35,
            "require_verified_target": require_verified_target,
            "require_completion": True,
            "completion_steps": [
                {
                    "type": "input_selector",
                    "by": "descriptionContains",
                    "value": "${COMMENT_INPUT_LABEL}",
                    "text": "${COMMENT_TEXT}",
                    "clear_first": False,
                },
                {
                    "type": "tap_selector",
                    "by": "descriptionContains",
                    "value": "${COMMENT_SUBMIT_LABEL}",
                    "timeout": 5,
                },
            ],
            "completion_verify": {
                "type": "wait_element",
                "by": "text",
                "value": "${COMMENT_TEXT}",
                "timeout": 6,
            },
            "save_as": f"{save_prefix}_comment_action",
        },
    ]


def _fb_publish_post_steps() -> List[Dict[str, Any]]:
    """Create a Facebook post from the current logged-in home surface."""
    return [
        {
            "id": "publish_post_open_composer_primary",
            "type": "if_element",
            "by": "text",
            "value": "${POST_COMPOSER_LABEL}",
            "timeout": 5,
            "then": [
                {
                    "type": "tap_selector",
                    "by": "text",
                    "value": "${POST_COMPOSER_LABEL}",
                    "timeout": 3,
                }
            ],
            "else": [
                {
                    "type": "if_element",
                    "by": "descriptionContains",
                    "value": "${POST_COMPOSER_LABEL_FALLBACK}",
                    "timeout": 2,
                    "then": [
                        {
                            "type": "tap_selector",
                            "by": "descriptionContains",
                            "value": "${POST_COMPOSER_LABEL_FALLBACK}",
                            "timeout": 3,
                        }
                    ],
                    "else": [
                        {
                            "type": "tap_ratio",
                            "x": 0.5,
                            "y": 0.225,
                        }
                    ],
                }
            ],
        },
        {
            "id": "publish_post_composer_ready",
            "type": "wait_stable",
            "timeout": 5,
            "stable_duration": 0.45,
        },
        {
            "id": "publish_post_focus_textarea",
            "type": "tap_ratio",
            "x": 0.45,
            "y": 0.34,
        },
        {
            "id": "publish_post_input_text",
            "type": "input_text",
            "via": "u2",
            "text": "${POST_TEXT}",
            "clear_first": False,
        },
        {"id": "publish_post_text_settle", "type": "wait", "seconds": 0.5},
        {
            "id": "publish_post_next",
            "type": "if_element",
            "by": "text",
            "value": "${POST_NEXT_LABEL}",
            "timeout": 4,
            "then": [
                {
                    "type": "tap_selector",
                    "by": "text",
                    "value": "${POST_NEXT_LABEL}",
                    "timeout": 4,
                }
            ],
            "else": [
                {
                    "type": "tap_ratio",
                    "x": 0.85,
                    "y": 0.955,
                }
            ],
        },
        {
            "id": "publish_post_preview_ready",
            "type": "wait_stable",
            "timeout": 6,
            "stable_duration": 0.5,
        },
        {
            "id": "publish_post_submit",
            "type": "if_element",
            "by": "text",
            "value": "${POST_SUBMIT_LABEL}",
            "timeout": 4,
            "then": [
                {
                    "type": "tap_selector",
                    "by": "text",
                    "value": "${POST_SUBMIT_LABEL}",
                    "timeout": 4,
                }
            ],
            "else": [
                {
                    "type": "tap_ratio",
                    "x": 0.5,
                    "y": 0.955,
                }
            ],
        },
        {
            "id": "publish_post_wait_uploaded",
            "type": "wait_stable",
            "timeout": 12,
            "stable_duration": 0.8,
        },
        {"id": "publish_post_dismiss_after_post", "type": "dismiss_popup", "retries": 2},
    ]


def _fb_set_page_context_steps() -> List[Dict[str, Any]]:
    return [
        {
            "type": "if_variable",
            "name": "TARGET_NAME",
            "then": [
                {
                    "type": "set_variable",
                    "name": "PAGE_CONTEXT",
                    "value": "${TARGET_NAME}",
                }
            ],
            "else": [
                {
                    "type": "set_variable",
                    "name": "PAGE_CONTEXT",
                    "value": "${PAGE_SEARCH}",
                }
            ],
        }
    ]


def _fb_open_page_target_steps(
    *,
    search_var: str,
    row_text_var: str,
) -> List[Dict[str, Any]]:
    return [
        {
            "id": "open_assigned_page_or_configured_page",
            "type": "if_variable",
            "name": "TARGET_SELECTOR_VALUE",
            "then": [
                *_fb_open_search_tab_steps(
                    search_var="TARGET_SEARCH_QUERY",
                    tab_vi="Trang",
                    tab_en="Pages",
                    tab_description_contains="tab Trang",
                ),
                {"type": "tap_ratio", "x": 0.5, "y": 0.22},
                {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},
            ],
            "else": [
                *_fb_open_search_result_steps(
                    search_var=search_var,
                    tab_vi="Trang",
                    tab_en="Pages",
                    tab_description_contains="tab Trang",
                    row_text_var=row_text_var,
                )
            ],
        }
    ]


def _fb_open_page_first_result_steps(*, search_var: str) -> List[Dict[str, Any]]:
    return [
        *_fb_open_search_tab_steps(
            search_var=search_var,
            tab_vi="Trang",
            tab_en="Pages",
            tab_description_contains="tab Trang",
        ),
        {"type": "tap_ratio", "x": 0.5, "y": 0.22},
        {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},
    ]


def _fb_open_page_exact_result_steps(
    *,
    search_var: str,
    row_text_var: str,
) -> List[Dict[str, Any]]:
    """Search the exact page and open the matching clickable result row."""
    return [
        {
            "type": "tap_selector",
            "by": "content-desc",
            "value": "Tìm kiếm",
            "timeout": 5,
        },
        {"type": "wait_stable", "timeout": 4, "stable_duration": 0.4},
        {
            "type": "input_text",
            "text": f"${{{search_var}}}",
            "via": "u2",
            "clear_first": True,
        },
        {"type": "wait", "seconds": 1},
        {"type": "key", "key": "enter"},
        {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},
        {
            "type": "tap_xml_match",
            "attr": "content-desc",
            "contains": f"${{{row_text_var}}}",
            "clickable": True,
            "timeout": 10,
        },
        {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},
    ]


def _fb_follow_current_page_steps() -> List[Dict[str, Any]]:
    return [
        {
            "type": "if_variable",
            "name": "FOLLOW_PAGE",
            "equals": "true",
            "then": [
                {
                    "type": "if_element",
                    "by": "content-desc",
                    "value": "Theo dõi",
                    "timeout": 2,
                    "then": [
                        {
                            "type": "tap_selector",
                            "by": "content-desc",
                            "value": "Theo dõi",
                            "timeout": 2,
                            "ignore_error": True,
                        }
                    ],
                    "else": [
                        {
                            "type": "tap_selector",
                            "by": "content-desc",
                            "value": "Follow",
                            "timeout": 2,
                            "ignore_error": True,
                        }
                    ],
                },
                {"type": "wait", "seconds": 0.8},
            ],
            "else": [{"type": "wait", "seconds": 0.1}],
        }
    ]


def _fb_back_to_page_search_before_next_page_steps() -> List[Dict[str, Any]]:
    return [
        {
            "id": "back_to_page_search_before_next_page",
            "type": "key",
            "key": "back",
        },
        {"type": "wait_stable", "timeout": 4, "stable_duration": 0.5},
        {"type": "dismiss_popup", "retries": 1},
    ]


def _fb_open_page_posts_area_steps() -> List[Dict[str, Any]]:
    return [
        {
            "type": "scroll_down",
            "repeats": 2,
            "start_x_ratio": "${SCROLL_X_RATIO}",
            "start_y_ratio": 0.72,
            "end_y_ratio": 0.42,
        },
        {"type": "wait", "seconds": 1},
    ]


def _fb_crawl_page_search_results_steps() -> List[Dict[str, Any]]:
    return [
        {
            "type": "set_variable",
            "name": "_PAGE_SEARCH_QUERY",
            "from_list": "${PAGE_KEYWORDS}",
            "from_list_index": "${_PAGE_KEYWORD_INDEX}",
        },
        {
            "type": "if_variable",
            "name": "_PAGE_SEARCH_QUERY",
            "then": [
                *_fb_open_search_tab_steps(
                    search_var="_PAGE_SEARCH_QUERY",
                    tab_vi="Trang",
                    tab_en="Pages",
                    tab_description_contains="tab Trang",
                ),
                {
                    "type": "if_element",
                    "by": "text",
                    "value": "Xem tất cả",
                    "timeout": 2,
                    "then": [
                        {
                            "type": "tap_selector",
                            "by": "text",
                            "value": "Xem tất cả",
                            "timeout": 2,
                            "ignore_error": True,
                        }
                    ],
                    "else": [
                        {
                            "type": "tap_selector",
                            "by": "text",
                            "value": "See all",
                            "timeout": 2,
                            "ignore_error": True,
                        }
                    ],
                },
                {"type": "wait_stable", "timeout": 3, "stable_duration": 0.45},
                {
                    "type": "extract",
                    "entity": "pages", "platform": "facebook",
                    "edge_extra_data": True,
                    "search_query": "${_PAGE_SEARCH_QUERY}",
                    "max_pages": "${MAX_PAGES}",
                    "max_items": "${MAX_ITEMS_PER_KEYWORD}",
                    "stop_if_no_new": True,
                    "no_new_threshold": 2,
                    "entity_scroll_pause_s": 0.5,
                    "edge_extra_timeout_s": 180,
                },
                {"type": "key", "key": "home"},
                {"type": "wait_stable", "timeout": 3, "stable_duration": 0.4},
            ],
            "else": [{"type": "wait", "seconds": 0.1}],
        },
    ]


def _fb_nurture_page_by_search_steps(
    *,
    search_var: str,
    row_text_var: str,
    id_prefix: str,
) -> List[Dict[str, Any]]:
    return [
        {"type": "set_variable", "name": "PAGE_CONTEXT", "value": f"${{{row_text_var}}}"},
        *_fb_open_page_exact_result_steps(
            search_var=search_var,
            row_text_var=row_text_var,
        ),
        *_fb_follow_current_page_steps(),
        *_fb_open_page_posts_area_steps(),
        *_fb_nurture_feed_steps(
            tag="fanpage",
            context_var="PAGE_CONTEXT",
            id_prefix=id_prefix,
        ),
    ]


def _fb_crawl_current_target_feed_steps(
    *,
    context_var: str,
    collection_var: str,
    tag_prefix: str,
    max_scroll_var: str = "MAX_SCROLLS",
) -> List[Dict[str, Any]]:
    return [
        {
            "type": "scroll_down",
            "repeats": 2,
            "start_x_ratio": "${SCROLL_X_RATIO}",
            "start_y_ratio": 0.65,
            "end_y_ratio": 0.47,
        },
        {"type": "wait", "seconds": 2},
        {
            "type": "loop",
            "count": f"${{{max_scroll_var}}}",
            "steps": [
                {"type": "dismiss_popup", "retries": 1},
                {
                    "type": "extract",
                    "entity": "posts", "platform": "facebook",
                    "edge_extra_data": True,
                    "extract_profile": "balanced",
                    "entity_version": "posts:v1",
                    **_FB_POST_OPEN_EXTRACT,
                    "expand_see_more": True,
                    "expand_see_more_max_passes": 2,
                    "expand_see_more_scroll": True,
                    "expand_see_more_scroll_distance": 0.25,
                    "expand_completion_retries": 2,
                    "stop_if_no_new": False,
                    "collection": f"${{{collection_var}}}",
                    "platform": "facebook",
                    "content_type": "fb_post",
                    "dedupe_field": "post_key",
                    "tags": f"{tag_prefix},crawl,${{{context_var}}}",
                },
                *_fb_open_comments_steps(),
                {"type": "wait", "seconds": 0.3},
                {
                    "type": "extract",
                    "entity": "comments", "platform": "facebook",
                    "edge_extra_data": True,
                    "extract_profile": "balanced",
                    "entity_version": "comments:v1",
                    "parent_post_id_var": "_comment_parent_pid",
                    "require_verified_parent": True,
                    "max_items": 220,
                    "comment_scroll_passes": 16,
                    "comment_swipes_per_dump": 4,
                    "comment_scroll_distance": 0.52,
                    "comment_scroll_duration_ms": 120,
                    "comment_scroll_pause_s": 0.03,
                    "comment_no_growth_break": 0,
                    "min_comment_scan_passes": 2,
                    "comment_max_snapshots": 12,
                    "comment_scroll_wall_s": 25,
                    "comment_stop_if_no_new": False,
                    "stop_if_no_new": False,
                    "no_new_threshold": 3,
                    "collection": f"${{{collection_var}}}",
                    "platform": "facebook",
                    "content_type": "fb_comment",
                    "dedupe_field": "comment_key",
                    "tags": f"{tag_prefix},comment,${{{context_var}}}",
                    "save_parent_id_var": "_active_comment_parent_hash",
                    "item_level": 1,
                },
                *_FB_RETURN_TO_FEED_AFTER_COMMENTS_STEPS,
                {
                    "type": "scroll_down",
                    "repeats": 1,
                    "start_x_ratio": "${SCROLL_X_RATIO}",
                    "start_y_ratio": 0.65,
                    "end_y_ratio": 0.47,
                },
                {
                    "type": "set_variable",
                    "name": "_W",
                    "from_list": [0.5, 0.5, 1, 1, 1.5, 2],
                },
                {"type": "wait", "seconds": "${_W}"},
            ],
        },
        {"type": "key", "key": "home"},
    ]


_FB_DETECT_LOGGED_IN: Dict[str, Any] = {
    "any_text": ["Trang chủ", "Home", "Tìm kiếm", "Bạn đang nghĩ gì?"],
}

_FB_LOGIN_PROFILE_NATIVE: Dict[str, Any] = {
    "package": "com.facebook.katana",
    "semantic_locators": {
        "username_field": {
            "candidates": [
                {"by": "description", "value": "Số di động hoặc email,"},
                {
                    "text_near": ["Số di động hoặc email"],
                    "target_class": "android.widget.EditText",
                    "allow_coordinate_fallback": True,
                },
            ]
        },
        "password_field": {
            "candidates": [
                {"by": "description", "value": "Mật khẩu,"},
                {
                    "text_near": ["Mật khẩu"],
                    "target_class": "android.widget.EditText",
                    "allow_coordinate_fallback": True,
                },
            ]
        },
        "login_button": {
            "candidates": [
                {"by": "text", "value": "Đăng nhập"},
                {"description_contains": "Đăng nhập", "class_name": "android.widget.Button"},
            ]
        },
        "auth_code_field": {
            "candidates": [
                {"by": "description", "value": "Mã,"},
                {"by": "description", "value": "Code,"},
                {
                    "text_near": ["Mã", "Authentication code", "Code"],
                    "target_class": "android.widget.EditText",
                    "allow_coordinate_fallback": True,
                },
            ]
        },
    },
    "login_recipe": {
        "detect_logged_in": _FB_DETECT_LOGGED_IN,
        "fields": {
            "username": {"locator": "username_field", "value_from": "account.username"},
            "password": {"locator": "password_field", "value_from": "account.password"},
        },
        "submit": {"locator": "login_button"},
        "post_submit_actions": [
            {
                "when_text_any": [
                    "Kiểm tra thông báo trên thiết bị khác",
                    "Đang chờ phê duyệt",
                    "Check notifications on another device",
                    "Waiting for approval",
                ],
                "tap_text_any": ["Thử cách khác", "Try another way"],
                "timeout_s": 8,
                "poll_s": 0.5,
                "wait_after_s": 1,
            },
            {
                "when_text_any": [
                    "Chọn một cách để xác nhận đó là bạn",
                    "Choose a way to confirm",
                    "Ứng dụng xác thực",
                    "Authentication app",
                ],
                "tap_text_any": ["Ứng dụng xác thực", "Authentication app"],
                "timeout_s": 6,
                "poll_s": 0.5,
                "wait_after_s": 0.5,
            },
            {
                "when_text_any": [
                    "Chọn một cách để xác nhận đó là bạn",
                    "Choose a way to confirm",
                    "Ứng dụng xác thực",
                    "Authentication app",
                ],
                "tap_text_any": ["Tiếp tục", "Continue", "Next"],
                "timeout_s": 4,
                "poll_s": 0.5,
                "wait_after_s": 2,
            },
        ],
        "post_submit_fields": {
            "auth_code": {
                "locator": "auth_code_field",
                "value_from": "account.totp_code",
                "required": False,
            },
        },
        "post_submit": {"tap_text_any": ["Tiếp tục", "Continue", "Next"]},
    },
}


def _fb_session_guard_steps(
    prefix: str,
    *,
    allow_login_recovery: bool = True,
) -> List[Dict[str, Any]]:
    steps: List[Dict[str, Any]] = [
        {
            "id": f"{prefix}_launch",
            "type": "launch_app",
            "package": "com.facebook.katana",
            "title": "Mở Facebook",
        },
        {
            "id": f"{prefix}_wait_stable",
            "type": "wait_stable",
            "timeout": 5,
            "stable_duration": 0.5,
        },
        {
            "id": f"{prefix}_dismiss_popups",
            "type": "dismiss_popup",
            "retries": 2,
        },
        {
            "id": f"{prefix}_session_preflight",
            "type": "platform_session_gate", "platform": "facebook",
            "phase": "preflight",
            "timeout": 0,
        },
    ]
    if not allow_login_recovery:
        return steps
    return [
        *steps,
        {
            "id": f"{prefix}_login_when_needed",
            "type": "if_variable",
            "name": "PLATFORM_SESSION_READY",
            "equals": True,
            "then": [{"type": "wait", "seconds": 0.1}],
            "else": [
                {
                    "type": "if_element",
                    "by": "content-desc",
                    "value": "Dùng trang cá nhân khác",
                    "timeout": 2,
                    "then": [
                        {
                            "type": "tap_selector",
                            "by": "content-desc",
                            "value": "Dùng trang cá nhân khác",
                            "timeout": 4,
                        },
                        {
                            "type": "wait_stable",
                            "timeout": 5,
                            "stable_duration": 0.4,
                        },
                    ],
                    "else": [],
                },
                {
                    "type": "login_if_needed",
                    "profile": deepcopy(_FB_LOGIN_PROFILE_NATIVE),
                    "clear_first": True,
                },
                {
                    "id": f"{prefix}_session_confirm",
                    "type": "platform_session_gate", "platform": "facebook",
                    "phase": "confirm",
                    "timeout": 20,
                    "poll_interval": 0.5,
                },
            ],
        },
    ]

_FACEBOOK_TEMPLATES: List[Dict[str, Any]] = [

    {
        "name": "Đăng nhập Facebook",
        "display_name": "Đăng nhập Facebook",
        "category": "facebook",
        "description": (
            "Xác nhận session đúng account rồi mới đăng nhập khi cần. "
            "Dùng số điện thoại hoặc email và mật khẩu Facebook của account đã gắn."
        ),
        "tags": "facebook,login,app-automation",
        "variables": {},
        "steps": [
            *_fb_session_guard_steps("facebook"),
        ],
    },

    {
        "name": "Đăng bài Facebook rồi like/comment",
        "display_name": "Đăng bài Facebook rồi like/comment",
        "category": "facebook",
        "description": (
            "Mở Facebook bằng account đã gắn với thiết bị, tạo bài viết từ POST_TEXT, "
            "tìm lại bài vừa đăng theo chính nội dung đó rồi chạy like và comment bằng "
            "social-action node có sẵn. POST_TEXT để trống mặc định để tránh lỡ publish."
        ),
        "tags": "facebook,post,publish,like,comment,app-automation",
        "variables": {
            "POST_TEXT": "",
            "COMMENT_TEXT": "Bài viết rất hữu ích, cảm ơn bạn đã chia sẻ.",
            "POST_COMPOSER_LABEL": "Bạn đang nghĩ gì",
            "POST_COMPOSER_LABEL_FALLBACK": "What's on your mind",
            "POST_NEXT_LABEL": "Tiếp",
            "POST_SUBMIT_LABEL": "Đăng",
            "COMMENT_INPUT_LABEL": "Viết bình luận",
            "COMMENT_SUBMIT_LABEL": "Đăng",
        },
        "steps": [
            *_fb_session_guard_steps("publish_post"),
            {
                "id": "publish_post_requires_ready_session",
                "type": "if_variable",
                "name": "PLATFORM_SESSION_READY",
                "equals": True,
                "then": [
                    *_fb_publish_post_steps(),
                    *_fb_open_search_tab_steps(
                        search_var="POST_TEXT",
                        tab_vi="Bài viết",
                        tab_en="Posts",
                        tab_description_contains="tab Bài viết",
                    ),
                    {
                        "id": "publish_post_select_created_post",
                        "type": "social_select_target", "target_type": "post", "platform": "facebook",
                        "search": "${POST_TEXT}",
                        "display_text": "${POST_TEXT}",
                        "required_keywords": ["${POST_TEXT}"],
                        "min_score": 80,
                        "require_unique": False,
                        "timeout": 12,
                        "save_as": "_published_post_target",
                    },
                    *_fb_post_like_and_comment_steps(
                        require_verified_target="_published_post_target",
                        save_prefix="_published_post",
                    ),
                    {"id": "publish_post_finish", "type": "key", "key": "home"},
                ],
                "else": [{"type": "wait", "seconds": 0.1}],
            },
        ],
    },

    {
        "name": "Khám phá nguồn từ Facebook Groups",
        "category": "facebook",
        "description": (
            "Tìm theo từ khóa, mở tab Nhóm/Xem tất cả và lưu các group tìm thấy "
            "vào kho nguồn dùng chung của organization. Mỗi lần chạy tạo observation "
            "mới để theo dõi dữ liệu thay đổi mà vẫn tái sử dụng cùng một nguồn."
        ),
        "tags": "facebook,group,discovery,external-entity",
        "variables": {
            "SEARCH_QUERY": "openclaw",
            "MAX_PAGES": 20,
        },
        "steps": [
            {
                "type": "launch_app",
                "package": "com.facebook.katana",
                "title": "Mở Facebook",
            },
            {"type": "wait_stable", "timeout": 5, "stable_duration": 0.5},
            {"type": "dismiss_popup", "retries": 2},
            {
                "type": "if_element",
                "by": "content-desc",
                "value": "Tìm kiếm",
                "timeout": 5,
                "then": [
                    {
                        "type": "tap_selector",
                        "by": "content-desc",
                        "value": "Tìm kiếm",
                        "timeout": 4,
                    }
                ],
                "else": [{"type": "tap_ratio", "x": 0.87, "y": 0.035}],
            },
            {"type": "wait_stable", "timeout": 4, "stable_duration": 0.4},
            {"type": "input_text", "text": "${SEARCH_QUERY}", "via": "u2"},
            {"type": "key", "key": "enter"},
            {
                "type": "if_element",
                "by": "text",
                "value": "Nhóm",
                "timeout": 4,
                "then": [
                    {
                        "type": "tap_selector",
                        "by": "text",
                        "value": "Nhóm",
                        "timeout": 3,
                    }
                ],
                "else": [
                    {
                        "type": "tap_selector",
                        "by": "text",
                        "value": "Groups",
                        "timeout": 3,
                        "ignore_error": True,
                    }
                ],
            },
            {"type": "wait_stable", "timeout": 4, "stable_duration": 0.5},
            {
                "type": "if_element",
                "by": "text",
                "value": "Xem tất cả",
                "timeout": 2,
                "then": [
                    {
                        "type": "tap_selector",
                        "by": "text",
                        "value": "Xem tất cả",
                        "timeout": 2,
                    }
                ],
                "else": [
                    {
                        "type": "tap_selector",
                        "by": "text",
                        "value": "See all",
                        "timeout": 2,
                        "ignore_error": True,
                    }
                ],
            },
            {
                "type": "extract",
                "entity": "groups", "platform": "facebook",
                "edge_extra_data": True,
                "search_query": "${SEARCH_QUERY}",
                "max_pages": "${MAX_PAGES}",
                "max_items": 500,
                "stop_if_no_new": True,
                "no_new_threshold": 2,
                "entity_scroll_pause_s": 0.6,
                "edge_extra_timeout_s": 180,
            },
            {"type": "key", "key": "home"},
        ],
    },

    {
        "name": "Khám phá Page Facebook theo keyword",
        "display_name": "Khám phá Page Facebook theo keyword",
        "category": "facebook",
        "description": (
            "Tìm Facebook Page bằng nhiều keyword, chuyển sang tab Trang/Pages "
            "(có vuốt ngang tab nếu Trang đang nằm ngoài màn hình), cào các page "
            "đang thấy và lưu vào catalog Page để phân công cho phone."
        ),
        "tags": "facebook,page,fanpage,discovery,catalog,keyword",
        "variables": {
            "PAGE_KEYWORDS": [
                "Go2Joy Vietnam",
                "khách sạn Việt Nam",
                "du lịch Việt Nam",
            ],
            "PAGE_KEYWORD_COUNT": 3,
            "MAX_PAGES": 8,
            "MAX_ITEMS_PER_KEYWORD": 120,
        },
        "steps": [
            *_fb_session_guard_steps("page_discovery", allow_login_recovery=False),
            {
                "id": "page_discovery_requires_ready_session",
                "type": "if_variable",
                "name": "PLATFORM_SESSION_READY",
                "equals": True,
                "then": [
                    {
                        "type": "loop",
                        "count": "${PAGE_KEYWORD_COUNT}",
                        "loop_var": "_PAGE_KEYWORD_INDEX",
                        "steps": _fb_crawl_page_search_results_steps(),
                    }
                ],
                "else": [{"type": "wait", "seconds": 0.1}],
            },
        ],
    },

    {
        "name": "Crawl bài viết + bình luận 1 nhóm Facebook",
        "category": "facebook",
        "description": (
            "Crawl bài viết + bình luận 1 nhóm Facebook liên tục (mặc định MAX_SCROLLS=540 ≈ 3h). "
            "Chấp nhận bài trùng lặp — DB dedup qua content_hash, loop không dừng sớm. "
            "Navigation: tìm kiếm → tab Nhóm → tap nhóm qua text. "
            "Scroll neo trái (SCROLL_X_RATIO=0.18) tránh mở ảnh. "
            "Mỗi bài: mở chi tiết → extract posts → atomic tap/filter comments trên detail → extract comments → quay feed.\n"
        ),
        "tags": "facebook,group,crawl",
        "variables": {
            "GROUP_NAME": "openclaw vn",
            "GROUP_TEXT": "OpenClaw VN · Truy cập",
            "MAX_SCROLLS": 540,
            "SCROLL_X_RATIO": 0.18,
            "SAVE_COLLECTION": "fb_group_posts",
        },
        "steps": [
            # ── Phase 1: Khởi động ────────────────────────────────────────────
            {"type": "launch_app", "package": "com.facebook.katana", "title": "mở fb"},

            # ── Phase 2: Tìm kiếm nhóm ───────────────────────────────────────
            {
                "type": "if_element", "by": "content-desc", "value": "Tìm kiếm", "timeout": 5,
                "then": [{"type": "tap_selector", "by": "content-desc", "value": "Tìm kiếm", "timeout": 4}],
                "else": [{"type": "tap_ratio", "x": 0.87, "y": 0.035}],
            },
            {"type": "wait_stable", "timeout": 4, "stable_duration": 0.4},
            {"type": "input_text", "text": "${GROUP_NAME}", "via": "u2"},
            {"type": "key", "key": "enter"},
            # ── Phase 3: Chọn tab Nhóm ───────────────────────────────────────
            {
                "type": "if_element", "by": "description", "value": "Kết quả tìm kiếm trong tab Nhóm, 3 trong số 7", "timeout": 5,
                "then": [{"type": "tap_selector", "by": "description", "value": "Kết quả tìm kiếm trong tab Nhóm, 3 trong số 7", "timeout": 4}],
                "else": [
                    {
                        "type": "if_element", "by": "text", "value": "Nhóm", "timeout": 3,
                        "then": [{"type": "tap_selector", "by": "text", "value": "Nhóm", "timeout": 3}],
                        "else": [
                            {
                                "type": "if_element", "by": "text", "value": "Groups", "timeout": 3,
                                "then": [{"type": "tap_selector", "by": "text", "value": "Groups", "timeout": 3}],
                                "else": [],
                            },
                        ],
                    },
                ],
            },
            {"type": "wait_stable", "timeout": 1, "stable_duration": 0.5},

            # ── Phase 4: Tap vào nhóm ───────────────────────────────────────
            {
                "type": "if_variable",
                "name": "TARGET_SELECTOR_VALUE",
                "then": [
                    {
                        "type": "if_element",
                        "by": "${TARGET_SELECTOR_BY}",
                        "value": "${TARGET_SELECTOR_VALUE}",
                        "timeout": 8,
                        "then": [
                            {
                                "type": "tap_selector",
                                "by": "${TARGET_SELECTOR_BY}",
                                "value": "${TARGET_SELECTOR_VALUE}",
                                "timeout": 8,
                            }
                        ],
                        "else": [
                            {
                                "type": "tap_selector",
                                "by": "${TARGET_FALLBACK_SELECTOR_BY}",
                                "value": "${TARGET_FALLBACK_SELECTOR_VALUE}",
                                "timeout": 8,
                            }
                        ],
                    }
                ],
                "else": [
                    {
                        "type": "tap_selector",
                        "by": "text",
                        "value": "${GROUP_TEXT}",
                        "timeout": 8,
                    }
                ],
            },
            {"type": "scroll_down", "repeats": 2, "start_x_ratio": "${SCROLL_X_RATIO}", "start_y_ratio": 0.65, "end_y_ratio": 0.47},
            {"type": "wait", "seconds": 3},

            # ── Phase 5: Loop crawl ──────────────────────────────────────────
            # ~20s/vòng × 540 ≈ 3h. Tăng MAX_SCROLLS tuỳ ý.
            {
                "type": "loop",
                "count": "${MAX_SCROLLS}",
                "steps": [
                    # Dọn popup nhanh mỗi đầu vòng
                    {"type": "dismiss_popup", "retries": 1},

                    # Extract bài viết (expand "Xem thêm" tối đa 2 lần — đủ cho hầu hết bài)
                    {
                        "type": "extract",
                        "entity": "posts", "platform": "facebook",
                        "edge_extra_data": True,
                        "extract_profile": "balanced",
                        "entity_version": "posts:v1",
                        **_FB_POST_OPEN_EXTRACT,
                        "expand_see_more": True,
                        "expand_see_more_max_passes": 2,
                        "expand_see_more_scroll": True,
                        "expand_see_more_scroll_distance": 0.25,
                        "expand_completion_retries": 2,
                        "stop_if_no_new": False,
                        "collection": "${SAVE_COLLECTION}",
                        "platform": "facebook",
                        "content_type": "fb_post",
                        "dedupe_field": "post_key",
                        "tags": "group,crawl,${GROUP_NAME}",
                    },
                    # Mở comments bằng node tuần tự để preview/runtime highlight từng hành động.
                    *_fb_open_comments_steps(),
                    {"type": "wait", "seconds": 0.3},
                    {
                        "type": "extract",
                        "entity": "comments", "platform": "facebook",
                        "edge_extra_data": True,
                        "extract_profile": "balanced",
                        "entity_version": "comments:v1",
                        "parent_post_id_var": "_comment_parent_pid",
                        "require_verified_parent": True,
                        "max_items": 220,
                        "comment_scroll_passes": 16,
                        "comment_swipes_per_dump": 4,
                        "comment_scroll_distance": 0.52,
                        "comment_scroll_duration_ms": 120,
                        "comment_scroll_pause_s": 0.03,
                        "comment_no_growth_break": 0,
                        "min_comment_scan_passes": 2,
                        "comment_max_snapshots": 12,
                        "comment_scroll_wall_s": 25,
                        "comment_stop_if_no_new": False,
                        "stop_if_no_new": False,
                        "no_new_threshold": 3,
                        "collection": "${SAVE_COLLECTION}",
                        "platform": "facebook",
                        "content_type": "fb_comment",
                        "dedupe_field": "comment_key",
                        "tags": "group,comment,${GROUP_NAME}",
                        "save_parent_id_var": "_active_comment_parent_hash",
                        "item_level": 1,
                    },
                    *_FB_RETURN_TO_FEED_AFTER_COMMENTS_STEPS,

                    # Scroll feed (neo trái tránh mở ảnh) + delay tự nhiên
                    {"type": "scroll_down", "repeats": 1, "start_x_ratio": "${SCROLL_X_RATIO}", "start_y_ratio": 0.65, "end_y_ratio": 0.47},
                    {"type": "set_variable", "name": "_W", "from_list": [0.5, 0.5, 1, 1, 1.5, 2]},
                    {"type": "wait", "seconds": "${_W}"},
                ],
            },

            # ── Phase 6: Kết thúc ────────────────────────────────────────────
            {"type": "key", "key": "home"},
        ],
    },

    {
        "name": "Crawl bài viết + bình luận Fanpage Facebook",
        "display_name": "Crawl bài viết + bình luận Fanpage Facebook",
        "category": "facebook",
        "description": (
            "Mở Fanpage đã gắn cho phone hoặc fallback theo PAGE_SEARCH/PAGE_ROW_TEXT, "
            "crawl bài viết và bình luận để tạo kho post/page evidence dùng cho nuôi account."
        ),
        "tags": "facebook,page,fanpage,crawl,feed,post,comment",
        "variables": {
            "PAGE_SEARCH": "ten fanpage",
            "PAGE_ROW_TEXT": "Tên Fanpage",
            "PAGE_CONTEXT": "ten fanpage",
            "MAX_SCROLLS": 180,
            "SCROLL_X_RATIO": 0.18,
            "SAVE_COLLECTION": "fb_page_posts",
        },
        "steps": [
            *_fb_session_guard_steps("fanpage_crawl", allow_login_recovery=False),
            {
                "id": "fanpage_crawl_requires_ready_session",
                "type": "if_variable",
                "name": "PLATFORM_SESSION_READY",
                "equals": True,
                "then": [
                    *_fb_set_page_context_steps(),
                    *_fb_open_page_target_steps(
                        search_var="PAGE_SEARCH",
                        row_text_var="PAGE_ROW_TEXT",
                    ),
                    *_fb_crawl_current_target_feed_steps(
                        context_var="PAGE_CONTEXT",
                        collection_var="SAVE_COLLECTION",
                        tag_prefix="page",
                    ),
                ],
                "else": [{"type": "wait", "seconds": 0.1}],
            },
        ],
    },

    {
        "name": "Nuôi Facebook - Tương tác Fanpage",
        "display_name": "Nuôi Facebook - Tương tác Fanpage",
        "category": "facebook",
        "description": (
            "Đi tuần tự từng Fanpage trong PAGE_TARGETS: search đúng page, mở đúng row, "
            "follow nếu còn nút theo dõi, tương tác đủ vòng rồi back để sang page kế tiếp."
        ),
        "tags": "facebook,page,fanpage,nurture,interaction",
        "variables": {
            "PAGE_SEARCH": "ten fanpage",
            "PAGE_ROW_TEXT": "Tên Fanpage",
            "PAGE_CONTEXT": "ten fanpage",
            "PAGE_TARGETS": ["ten fanpage"],
            "PAGE_ROW_TEXTS": ["Tên Fanpage"],
            "PAGE_COUNT": 1,
            "MAX_TOUCHES": 20,
            "SCROLL_X_RATIO": 0.22,
            "ACTION_WAIT_SECONDS": 2,
            "FOLLOW_PAGE": "true",
            "TARGET_NAME": "",
            "TARGET_SEARCH_QUERY": "",
        },
        "steps": [
            *_fb_session_guard_steps("fanpage_nurture", allow_login_recovery=False),
            {
                "id": "fanpage_nurture_requires_ready_session",
                "type": "if_variable",
                "name": "PLATFORM_SESSION_READY",
                "equals": True,
                "then": [
                    {
                        "type": "loop",
                        "count": "${PAGE_COUNT}",
                        "loop_var": "PAGE_INDEX",
                        "steps": [
                            {
                                "type": "set_variable",
                                "name": "PAGE_SEARCH_CURRENT",
                                "from_list": "${PAGE_TARGETS}",
                                "from_list_index": "${PAGE_INDEX}",
                            },
                            {
                                "type": "set_variable",
                                "name": "PAGE_ROW_TEXT_CURRENT",
                                "from_list": "${PAGE_ROW_TEXTS}",
                                "from_list_index": "${PAGE_INDEX}",
                            },
                            *_fb_nurture_page_by_search_steps(
                                search_var="PAGE_SEARCH_CURRENT",
                                row_text_var="PAGE_ROW_TEXT_CURRENT",
                                id_prefix="fanpage_page_${PAGE_INDEX}",
                            ),
                            *_fb_back_to_page_search_before_next_page_steps(),
                        ],
                    },
                    {"id": "fanpage_nurture_finish", "type": "key", "key": "home"},
                ],
                "else": [{"type": "wait", "seconds": 0.1}],
            },
        ],
    },

    {
        "name": "Chiến lược nuôi Facebook theo đối tượng",
        "display_name": "Chiến lược nuôi Facebook theo đối tượng",
        "category": "facebook",
        "description": (
            "Template nuôi tương tác theo TARGET_OBJECT_TYPE: fanpage, post hoặc people. "
            "Mỗi nhánh tự tìm đúng tab Facebook, mở đúng đối tượng rồi chạy tương tác nhẹ "
            "có delay tự nhiên. Social-action node chỉ thao tác trên màn hình hiện tại; "
            "các hành động tuỳ chọn được ignore_error để campaign không dừng khi target đã được xử lý "
            "hoặc nút không xuất hiện."
        ),
        "tags": "facebook,nurture,fanpage,post,people,engagement",
        "variables": {
            "TARGET_OBJECT_TYPE": "fanpage",
            "FANPAGE_SEARCH": "ten fanpage",
            "FANPAGE_ROW_TEXT": "Tên Fanpage",
            "POST_SEARCH": "noi dung bai viet",
            "POST_ROW_TEXT": "Đoạn text bài viết",
            "PEOPLE_SEARCH": "ten profile",
            "PEOPLE_ROW_TEXT": "Tên Profile",
            "MAX_TOUCHES": 20,
            "SCROLL_X_RATIO": 0.22,
            "ACTION_WAIT_SECONDS": 2,
            "COMMENT_TEXT": "Bài viết rất hữu ích, cảm ơn bạn đã chia sẻ.",
            "COMMENT_INPUT_LABEL": "Viết bình luận",
            "COMMENT_SUBMIT_LABEL": "Đăng",
            "ENABLE_CONNECTION_REQUEST": "true",
        },
        "steps": [
            {
                "id": "open_facebook",
                "type": "launch_app",
                "package": "com.facebook.katana",
                "title": "mở fb",
            },
            {"id": "dismiss_popups", "type": "dismiss_popup", "retries": 2},
            {
                "id": "wait_home_stable",
                "type": "wait_stable",
                "timeout": 5,
                "stable_duration": 0.45,
            },
            {
                "id": "branch_by_target_object",
                "type": "if_variable",
                "name": "TARGET_OBJECT_TYPE",
                "equals": "fanpage",
                "then": [
                    *_fb_open_search_result_steps(
                        search_var="FANPAGE_SEARCH",
                        tab_vi="Trang",
                        tab_en="Pages",
                        tab_description_contains="tab Trang",
                        row_text_var="FANPAGE_ROW_TEXT",
                    ),
                    {
                        "type": "if_element",
                        "by": "text",
                        "value": "Theo dõi",
                        "timeout": 2,
                        "then": [
                            {
                                "type": "tap_selector",
                                "by": "text",
                                "value": "Theo dõi",
                                "timeout": 2,
                                "ignore_error": True,
                            },
                        ],
                        "else": [
                            {
                                "type": "tap_selector",
                                "by": "text",
                                "value": "Follow",
                                "timeout": 2,
                                "ignore_error": True,
                            },
                        ],
                    },
                    *_fb_nurture_feed_steps(tag="fanpage", context_var="FANPAGE_SEARCH"),
                ],
                "else": [
                    {
                        "type": "if_variable",
                        "name": "TARGET_OBJECT_TYPE",
                        "equals": "post",
                        "then": [
                            *_fb_open_search_tab_steps(
                                search_var="POST_SEARCH",
                                tab_vi="Bài viết",
                                tab_en="Posts",
                                tab_description_contains="tab Bài viết",
                            ),
                            {
                                "type": "social_select_target", "target_type": "post", "platform": "facebook",
                                "search": "${POST_SEARCH}",
                                "display_text": "${POST_ROW_TEXT}",
                                "required_keywords": ["${POST_ROW_TEXT}"],
                                "min_score": 80,
                                "require_unique": True,
                                "timeout": 12,
                                "save_as": "_post_target",
                            },
                            *_fb_post_like_and_comment_steps(
                                require_verified_target="_post_target",
                                save_prefix="_post_nurture",
                            ),
                            *_fb_nurture_feed_steps(
                                tag="post",
                                context_var="POST_SEARCH",
                                require_verified_target="_post_target",
                            ),
                        ],
                        "else": [
                            *_fb_open_search_tab_steps(
                                search_var="PEOPLE_SEARCH",
                                tab_vi="Mọi người",
                                tab_en="People",
                                tab_description_contains="tab Mọi người",
                            ),
                            {
                                "type": "social_select_target", "target_type": "person", "platform": "facebook",
                                "search": "${PEOPLE_SEARCH}",
                                "display_name": "${PEOPLE_ROW_TEXT}",
                                "required_keywords": ["${PEOPLE_ROW_TEXT}"],
                                "min_score": 80,
                                "require_unique": True,
                                "timeout": 12,
                                "save_as": "_people_target",
                            },
                            {
                                "type": "if_variable",
                                "name": "ENABLE_CONNECTION_REQUEST",
                                "equals": "true",
                                "then": [
                                    {
                                        "type": "connection_request",
                                        "platform": "facebook",
                                        "action": "request",
                                        "timeout": 5,
                                        "verify_timeout": 5,
                                        "settle_seconds": 0.4,
                                        "require_verified_target": "_people_target",
                                        "save_as": "_people_connection_action",
                                        "ignore_error": True,
                                    }
                                ],
                                "else": [],
                            },
                            *_fb_nurture_feed_steps(
                                tag="people",
                                context_var="PEOPLE_SEARCH",
                                require_verified_target="_people_target",
                            ),
                        ],
                    }
                ],
            },
            {"id": "finish_home", "type": "key", "key": "home"},
        ],
    },

    {
        "name": "Nuôi Facebook - Tương tác bài viết trên Feed",
        "display_name": "Nuôi Facebook - Tương tác bài viết trên Feed",
        "category": "facebook",
        "description": (
            "Mở Facebook rồi scan feed theo nhiều cycle để treo dài. Mỗi bài post "
            "được mở 'xem thêm' trước, chỉ khi nội dung đầy đủ khớp keyword mới "
            "like thật và comment thật."
        ),
        "tags": "facebook,nurture,post,feed,keyword,interaction",
        "variables": {
            "POST_RUN_HOURS": 8,
            "POST_RUN_SECONDS": 28800,
            "POST_SCAN_CYCLES": 9999,
            "POST_KEYWORDS": ["AI", "tuyển dụng", "công nghệ"],
            "COMMENT_TEXT": "Bài viết rất hữu ích, cảm ơn bạn đã chia sẻ.",
            "POST_TARGET_COUNT": 5,
            "MAX_SCROLLS": 40,
            "SCROLL_X_RATIO": 0.5,
            "POST_MATCH_MODE": "any",
            "POST_SCAN_TIMEOUT_SECONDS": 300,
        },
        "steps": [
            *_fb_session_guard_steps("feed_post_nurture", allow_login_recovery=False),
            {
                "id": "feed_post_requires_ready_session",
                "type": "if_variable",
                "name": "PLATFORM_SESSION_READY",
                "equals": True,
                "then": [
                    {
                        "id": "feed_post_scan_8h_loop",
                        "type": "loop",
                        "count": "${POST_SCAN_CYCLES}",
                        "duration_seconds": "${POST_RUN_SECONDS}",
                        "loop_var": "POST_SCAN_CYCLE",
                        "steps": [
                            {
                                "id": "feed_post_scan_and_interact",
                                "type": "social_scan_posts_interact",
                                "platform": "facebook",
                                "keywords": "${POST_KEYWORDS}",
                                "keywords_var": "POST_KEYWORDS",
                                "match_mode": "${POST_MATCH_MODE}",
                                "comment_text": "${COMMENT_TEXT}",
                                "target_count": "${POST_TARGET_COUNT}",
                                "max_scrolls": "${MAX_SCROLLS}",
                                "scroll_x_ratio": "${SCROLL_X_RATIO}",
                                "timeout": "${POST_SCAN_TIMEOUT_SECONDS}",
                                "require_comment": True,
                                "save_as": "_post_scan",
                            }
                        ],
                    },
                    {"id": "feed_post_finish", "type": "key", "key": "home"},
                ],
                "else": [{"type": "wait", "seconds": 0.1}],
            },
        ],
    },

    {
        "name": "Nuôi Facebook - Kết bạn từ người bình luận post Home đúng keyword",
        "display_name": "Nuôi Facebook - Kết bạn từ người bình luận post Home đúng keyword",
        "category": "facebook",
        "description": (
            "Treo Home feed theo cycle: scan vùng đang thấy, tìm bài post khớp "
            "keyword, bấm Bình luận để mở comment sheet, mở profile commenter phù "
            "hợp rồi mới gửi lời mời kết bạn. Back về feed rồi mới cuộn tiếp."
        ),
        "tags": "facebook,nurture,home-feed,post,commenter,profile,connection,keyword",
        "variables": {
            "POST_RUN_SECONDS": 28800,
            "FEED_ITERATIONS": 9999,
            "POST_KEYWORDS": ["AI", "tuyển dụng", "công nghệ"],
            "POSTS_PER_BATCH": 2,
            "POST_MATCH_MODE": "any",
            "POST_SCAN_TIMEOUT_SECONDS": 60,
            "COMMENTER_SCAN_LIMIT": 3,
            "COMMENTER_STEP_TIMEOUT": 60,
            "PROFILE_REQUIRED_KEYWORDS": ["AI", "công nghệ"],
            "PROFILE_OPTIONAL_KEYWORDS": ["tuyển dụng", "startup", "automation"],
            "PROFILE_FORBIDDEN_KEYWORDS": [
                "trang",
                "page",
                "nhóm",
                "group",
                "ẩn danh",
                "anonymous",
                "sponsored",
                "được tài trợ",
            ],
            "PROFILE_MIN_SCORE": 80,
            "ENABLE_CONNECTION_REQUEST": True,
        },
        "steps": [
            *_fb_session_guard_steps("home_post_author_connect", allow_login_recovery=False),
            {
                "id": "home_post_author_requires_ready_session",
                "type": "if_variable",
                "name": "PLATFORM_SESSION_READY",
                "equals": True,
                "then": [
                    {
                        "id": "home_post_author_cycle",
                        "type": "loop",
                        "count": "${FEED_ITERATIONS}",
                        "duration_seconds": "${POST_RUN_SECONDS}",
                        "loop_var": "FEED_CYCLE",
                        "steps": [
                            {
                                "id": "home_post_author_scan",
                                "type": "social_scan_posts_interact",
                                "platform": "facebook",
                                "keywords": "${POST_KEYWORDS}",
                                "keywords_var": "POST_KEYWORDS",
                                "match_mode": "${POST_MATCH_MODE}",
                                "comment_text": "",
                                "target_count": "${POSTS_PER_BATCH}",
                                "max_scrolls": 0,
                                "timeout": "${POST_SCAN_TIMEOUT_SECONDS}",
                                "require_comment": False,
                                "like_post": False,
                                "save_as": "_post_scan",
                            },
                            *_fb_commenter_connect_steps(
                                prefix="home_post_author",
                                action_index=0,
                            ),
                            *_fb_commenter_connect_steps(
                                prefix="home_post_author",
                                action_index=1,
                            ),
                            {
                                "id": "home_post_author_scroll_next",
                                "type": "scroll_down",
                                "repeats": 1,
                                "start_y_ratio": 0.72,
                                "end_y_ratio": 0.34,
                                "duration_ms": 520,
                                "pause_seconds": 0.7,
                            },
                        ],
                    },
                    {"id": "home_post_author_finish", "type": "key", "key": "home"},
                ],
                "else": [{"type": "wait", "seconds": 0.1}],
            },
        ],
    },

    {
        "name": "Nuôi Facebook - Gieo mầm bạn bè từ Group (account mới)",
        "display_name": "Nuôi Facebook - Gieo mầm bạn bè từ Group (account mới)",
        "category": "facebook",
        "description": (
            "Dành cho account chưa có bạn. Gợi ý 'Những người bạn có thể biết' của "
            "một account 0 bạn là người lạ hoàn toàn vì Facebook chưa có tín hiệu "
            "đồ thị nào, nên kịch bản này không dùng gợi ý. Thay vào đó: vào group "
            "cùng chủ đề, like và comment thật để có mặt trong group, rồi kết bạn "
            "với chính những người đang bình luận ở đó. Lời mời được gửi trên trang "
            "cá nhân của họ — nơi nhìn thấy ngữ cảnh chung trước khi gửi, và nơi "
            "trạng thái nút tự xác nhận đã gửi hay chưa."
        ),
        "tags": "facebook,nurture,cold-start,group,commenter,profile,connection,seed",
        "variables": {
            "POST_RUN_SECONDS": 5400,
            "GROUP_SCAN_SECONDS": 2400,
            "SEED_CYCLES": 9999,
            "GROUP_SEARCHES": ["ten group 1", "ten group 2"],
            "GROUP_ROW_TEXTS": ["Tên group 1", "Tên group 2"],
            "GROUP_COUNT": 2,
            "POST_KEYWORDS": ["AI", "công nghệ", "chia sẻ"],
            "POST_MATCH_MODE": "any",
            "POST_SCAN_TIMEOUT_SECONDS": 180,
            # Comment thật trước khi kết bạn: người trong group thấy mặt mình
            # trước khi nhận lời mời, nên tỉ lệ đồng ý cao hơn hẳn người lạ.
            "COMMENT_TEXT": "Bài viết hữu ích, cảm ơn bạn đã chia sẻ.",
            "POSTS_PER_BATCH": 2,
            "MAX_SCROLLS": 6,
            "SCROLL_X_RATIO": 0.5,
            "COMMENTER_SCAN_LIMIT": 3,
            "COMMENTER_STEP_TIMEOUT": 60,
            # Account mới chưa có gì để so khớp, nên đừng đòi hồ sơ phải chứa
            # keyword — ngữ cảnh ở đây là "cùng group", không phải nội dung profile.
            "PROFILE_REQUIRED_KEYWORDS": [],
            "PROFILE_OPTIONAL_KEYWORDS": ["AI", "công nghệ", "chia sẻ"],
            # KHÔNG đưa "trang"/"page"/"nhóm"/"group" vào đây: forbidden khớp theo
            # chuỗi con trên toàn bộ text trang cá nhân, nên "trang" loại sạch
            # người tên Trang, còn "nhóm" loại đúng những người có dấu hiệu cùng
            # group — tức là loại chính tín hiệu kịch bản này dựa vào.
            "PROFILE_FORBIDDEN_KEYWORDS": [
                "được tài trợ",
                "sponsored",
                "ẩn danh",
                "anonymous",
            ],
            "PROFILE_MIN_SCORE": 0,
            # Nhịp rất thấp: account mới gửi nhiều lời mời không ai đồng ý là
            # cách nhanh nhất để tự huỷ.
            "CONNECTS_PER_CYCLE": 2,
            "ENABLE_CONNECTION_REQUEST": True,
        },
        "steps": [
            *_fb_session_guard_steps("seed_friends", allow_login_recovery=False),
            {
                "id": "seed_friends_requires_ready_session",
                "type": "if_variable",
                "name": "PLATFORM_SESSION_READY",
                "equals": True,
                "then": [
                    {
                        "id": "seed_friends_group_loop",
                        "type": "loop",
                        "count": "${GROUP_COUNT}",
                        "loop_var": "GROUP_INDEX",
                        "duration_seconds": "${POST_RUN_SECONDS}",
                        "steps": [
                            # Start every group from the feed, not from wherever
                            # the previous iteration happened to stop.
                            *_fb_return_to_feed_steps("seed_friends"),
                            {
                                "type": "set_variable",
                                "name": "GROUP_SEARCH_CURRENT",
                                "from_list": "${GROUP_SEARCHES}",
                                "from_list_index": "${GROUP_INDEX}",
                            },
                            {
                                "type": "set_variable",
                                "name": "GROUP_ROW_TEXT_CURRENT",
                                "from_list": "${GROUP_ROW_TEXTS}",
                                "from_list_index": "${GROUP_INDEX}",
                            },
                            *_fb_open_search_tab_steps(
                                search_var="GROUP_SEARCH_CURRENT",
                                tab_vi="Nhóm",
                                tab_en="Groups",
                                tab_description_contains="tab Nhóm",
                            ),
                            {
                                "type": "tap_xml_match",
                                "attr": "content-desc",
                                "contains": "${GROUP_ROW_TEXT_CURRENT}",
                                "clickable": True,
                                "timeout": 10,
                            },
                            {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},
                            # Tham gia nếu chưa là thành viên. Đã vào rồi thì
                            # community_membership tự nhận trạng thái và bỏ qua.
                            {
                                "id": "seed_friends_join_group",
                                "type": "community_membership",
                                "platform": "facebook",
                                "action": "join",
                                "timeout": 6,
                                "verify_timeout": 6,
                                "settle_seconds": 0.4,
                                "ignore_error": True,
                                "save_as": "_group_join_action",
                            },
                            {
                                "id": "seed_friends_cycle",
                                "type": "loop",
                                "count": "${SEED_CYCLES}",
                                "duration_seconds": "${GROUP_SCAN_SECONDS}",
                                "loop_var": "SEED_CYCLE",
                                "steps": [
                                    # Bước này làm hai việc cùng lúc: tạo sự hiện
                                    # diện thật trong group, và sinh ra chính kho
                                    # người bình luận để kết bạn ngay bên dưới.
                                    {
                                        "id": "seed_friends_scan_and_interact",
                                        "type": "social_scan_posts_interact",
                                        "platform": "facebook",
                                        "keywords": "${POST_KEYWORDS}",
                                        "keywords_var": "POST_KEYWORDS",
                                        "match_mode": "${POST_MATCH_MODE}",
                                        "comment_text": "${COMMENT_TEXT}",
                                        "like_post": True,
                                        "require_comment": True,
                                        "target_count": "${POSTS_PER_BATCH}",
                                        "max_scrolls": "${MAX_SCROLLS}",
                                        "scroll_x_ratio": "${SCROLL_X_RATIO}",
                                        "timeout": "${POST_SCAN_TIMEOUT_SECONDS}",
                                        "save_as": "_post_scan",
                                    },
                                    *_fb_commenter_connect_steps(
                                        prefix="seed_friends",
                                        action_index=0,
                                    ),
                                    {
                                        "id": "seed_friends_second_connect",
                                        "type": "if_variable",
                                        "name": "CONNECTS_PER_CYCLE",
                                        "greater_than": 1,
                                        "then": [
                                            *_fb_commenter_connect_steps(
                                                prefix="seed_friends",
                                                action_index=1,
                                            )
                                        ],
                                        "else": [],
                                    },
                                    {
                                        "type": "scroll_down",
                                        "repeats": 1,
                                        "start_x_ratio": "${SCROLL_X_RATIO}",
                                        "start_y_ratio": 0.65,
                                        "end_y_ratio": 0.45,
                                    },
                                ],
                            },
                            *_fb_back_to_page_search_before_next_page_steps(),
                        ],
                    },
                    {"id": "seed_friends_finish", "type": "key", "key": "home"},
                ],
                "else": [{"type": "wait", "seconds": 0.1}],
            },
        ],
    },

    {
        "name": "Nuôi Facebook - Tương tác bài viết trong Group",
        "display_name": "Nuôi Facebook - Tương tác bài viết trong Group",
        "category": "facebook",
        "description": (
            "Đi tuần tự từng group trong GROUP_SEARCHES: search đúng group, mở đúng "
            "row, treo scan trong group theo nhiều cycle rồi back để sang group tiếp "
            "theo. Mỗi bài được mở 'xem thêm' trước, chỉ nội dung đầy đủ khớp keyword "
            "mới được like thật và comment thật."
        ),
        "tags": "facebook,nurture,post,group,multi-group,keyword,interaction",
        "variables": {
            "POST_RUN_HOURS": 8,
            "POST_RUN_SECONDS": 28800,
            "GROUP_SCAN_SECONDS": 28800,
            "POST_SCAN_CYCLES": 9999,
            "GROUP_SEARCH": "ten group 1",
            "GROUP_ROW_TEXT": "Tên group 1",
            "GROUP_SEARCHES": ["ten group 1", "ten group 2"],
            "GROUP_ROW_TEXTS": ["Tên group 1", "Tên group 2"],
            "GROUP_COUNT": 2,
            "POST_KEYWORDS": ["AI", "tuyển dụng", "công nghệ"],
            "COMMENT_TEXT": "Bài viết rất hữu ích, cảm ơn bạn đã chia sẻ.",
            "POST_TARGET_COUNT": 5,
            "MAX_SCROLLS": 40,
            "SCROLL_X_RATIO": 0.5,
            "POST_MATCH_MODE": "any",
            "POST_SCAN_TIMEOUT_SECONDS": 300,
        },
        "steps": [
            *_fb_session_guard_steps("group_post_nurture", allow_login_recovery=False),
            {
                "id": "group_post_requires_ready_session",
                "type": "if_variable",
                "name": "PLATFORM_SESSION_READY",
                "equals": True,
                "then": [
                    {
                        "id": "group_post_multi_group_loop",
                        "type": "loop",
                        "count": "${GROUP_COUNT}",
                        "loop_var": "GROUP_INDEX",
                        "steps": [
                            {
                                "type": "set_variable",
                                "name": "GROUP_SEARCH_CURRENT",
                                "from_list": "${GROUP_SEARCHES}",
                                "from_list_index": "${GROUP_INDEX}",
                            },
                            {
                                "type": "set_variable",
                                "name": "GROUP_ROW_TEXT_CURRENT",
                                "from_list": "${GROUP_ROW_TEXTS}",
                                "from_list_index": "${GROUP_INDEX}",
                            },
                            *_fb_open_search_tab_steps(
                                search_var="GROUP_SEARCH_CURRENT",
                                tab_vi="Nhóm",
                                tab_en="Groups",
                                tab_description_contains="tab Nhóm",
                            ),
                            {
                                "type": "tap_xml_match",
                                "attr": "content-desc",
                                "contains": "${GROUP_ROW_TEXT_CURRENT}",
                                "clickable": True,
                                "timeout": 10,
                            },
                            {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},
                            {
                                "id": "group_post_scan_8h_loop",
                                "type": "loop",
                                "count": "${POST_SCAN_CYCLES}",
                                "duration_seconds": "${GROUP_SCAN_SECONDS}",
                                "loop_var": "POST_SCAN_CYCLE",
                                "steps": [
                                    {
                                        "id": "group_post_scan_and_interact",
                                        "type": "social_scan_posts_interact",
                                        "platform": "facebook",
                                        "keywords": "${POST_KEYWORDS}",
                                        "keywords_var": "POST_KEYWORDS",
                                        "match_mode": "${POST_MATCH_MODE}",
                                        "comment_text": "${COMMENT_TEXT}",
                                        "target_count": "${POST_TARGET_COUNT}",
                                        "max_scrolls": "${MAX_SCROLLS}",
                                        "scroll_x_ratio": "${SCROLL_X_RATIO}",
                                        "timeout": "${POST_SCAN_TIMEOUT_SECONDS}",
                                        "require_comment": True,
                                        "save_as": "_group_post_scan",
                                    }
                                ],
                            },
                            *_fb_back_to_page_search_before_next_page_steps(),
                        ],
                    },
                    {"id": "group_post_finish", "type": "key", "key": "home"},
                ],
                "else": [{"type": "wait", "seconds": 0.1}],
            },
        ],
    },

    {
        "name": "Nuôi Facebook - Kết bạn theo ứng viên đã duyệt",
        "display_name": "Nuôi Facebook - Kết bạn theo ứng viên đã duyệt",
        "category": "facebook",
        "description": (
            "Mở bề mặt bạn bè/gợi ý trong app Facebook, scan trực tiếp các row/card có "
            "nút Thêm bạn bè, chỉ gửi lời mời khi UI có điểm chung như bạn chung, cùng "
            "nhóm hoặc keyword ngữ cảnh. Không search tên từng người."
        ),
        "tags": "facebook,nurture,profile,connection,common-context,visible-scan",
        "variables": {
            "CONNECTION_TARGET_COUNT": 20,
            "CONNECTION_MAX_SCROLLS": 30,
            "CONNECTION_MIN_COMMON_SCORE": 40,
            "CONNECTION_COMMON_KEYWORDS": ["bạn chung", "mutual friends", "cùng nhóm"],
        },
        "steps": [
            *_fb_session_guard_steps("candidate_profile", allow_login_recovery=False),
            {
                "id": "candidate_profile_requires_ready_session",
                "type": "if_variable",
                "name": "PLATFORM_SESSION_READY",
                "equals": True,
                "then": [
                    {
                        "id": "candidate_profile_connect_visible_common_batch",
                        "type": "social_connect_visible_people",
                        "platform": "facebook",
                        "open_surface": True,
                        "target_count": "${CONNECTION_TARGET_COUNT}",
                        "max_scrolls": "${CONNECTION_MAX_SCROLLS}",
                        "no_more_common_limit": 4,
                        "min_score": "${CONNECTION_MIN_COMMON_SCORE}",
                        "require_common": True,
                        "common_keywords": "${CONNECTION_COMMON_KEYWORDS}",
                        "forbidden_keywords": [
                            "trang",
                            "page",
                            "người tham gia ẩn danh",
                            "anonymous",
                        ],
                        "timeout": 150,
                        "verify_wait_s": 0.8,
                        "scroll_wait_s": 0.7,
                        "stop_on_unverified": True,
                        "save_as": "_visible_connection_action",
                    },
                    {"id": "candidate_profile_finish", "type": "key", "key": "home"},
                ],
                "else": [{"type": "wait", "seconds": 0.1}],
            },
        ],
    },

    {
        "name": "Crawl bài viết + bình luận 5 profile Facebook (cá nhân)",
        "category": "facebook",
        "description": (
            "Lần lượt crawl timeline 5 profile cá nhân: mỗi vòng lặp tìm kiếm → tab Mọi người/People → "
            "chạm dòng kết quả (theo text hàng) → cuộn timeline giống nhóm (SCROLL_X_RATIO). "
            "Sau mỗi profile: back nhiều lần để về gần feed rồi profile tiếp theo. "
            "Điền PROFILE_n_SEARCH (chuỗi gõ ô tìm kiếm) và PROFILE_n_ROW_TEXT (text hiển thị trên hàng "
            "kết quả, ví dụ 'Tên · Bạn bè'). MAX_SCROLLS_PER_PROFILE mặc định 120 — chỉnh nếu cần sâu hơn.\n"
        ),
        "tags": "facebook,profile,crawl,people,multi",
        "variables": {
            "PROFILE_1_SEARCH": "tên profile 1",
            "PROFILE_1_ROW_TEXT": "Tên Profile 1 · Bạn bè",
            "PROFILE_2_SEARCH": "tên profile 2",
            "PROFILE_2_ROW_TEXT": "Tên Profile 2 · Theo dõi",
            "PROFILE_3_SEARCH": "tên profile 3",
            "PROFILE_3_ROW_TEXT": "Tên Profile 3 · Bạn bè",
            "PROFILE_4_SEARCH": "tên profile 4",
            "PROFILE_4_ROW_TEXT": "Tên Profile 4 · Bạn bè",
            "PROFILE_5_SEARCH": "tên profile 5",
            "PROFILE_5_ROW_TEXT": "Tên Profile 5 · Bạn bè",
            "MAX_SCROLLS_PER_PROFILE": 120,
            "SCROLL_X_RATIO": 0.18,
            "SAVE_COLLECTION": "fb_profile_posts",
        },
        "steps": [
            {"type": "launch_app", "package": "com.facebook.katana", "title": "mở fb"},
            {"type": "dismiss_popup", "retries": 2},
            {"type": "wait_stable", "timeout": 5, "stable_duration": 0.45},
            {
                "type": "repeat",
                "count": 5,
                "delay_between": 2.0,
                "steps": [
                    # Gán PROFILE_SEARCH + PROFILE_ROW_TEXT theo __LOOP_INDEX__ (0..4)
                    {
                        "type": "if_variable",
                        "name": "__LOOP_INDEX__",
                        "equals": 0,
                        "then": [
                            {"type": "set_variable", "name": "PROFILE_SEARCH", "value": "${PROFILE_1_SEARCH}"},
                            {"type": "set_variable", "name": "PROFILE_ROW_TEXT", "value": "${PROFILE_1_ROW_TEXT}"},
                        ],
                        "else": [
                            {
                                "type": "if_variable",
                                "name": "__LOOP_INDEX__",
                                "equals": 1,
                                "then": [
                                    {"type": "set_variable", "name": "PROFILE_SEARCH", "value": "${PROFILE_2_SEARCH}"},
                                    {"type": "set_variable", "name": "PROFILE_ROW_TEXT", "value": "${PROFILE_2_ROW_TEXT}"},
                                ],
                                "else": [
                                    {
                                        "type": "if_variable",
                                        "name": "__LOOP_INDEX__",
                                        "equals": 2,
                                        "then": [
                                            {"type": "set_variable", "name": "PROFILE_SEARCH", "value": "${PROFILE_3_SEARCH}"},
                                            {"type": "set_variable", "name": "PROFILE_ROW_TEXT", "value": "${PROFILE_3_ROW_TEXT}"},
                                        ],
                                        "else": [
                                            {
                                                "type": "if_variable",
                                                "name": "__LOOP_INDEX__",
                                                "equals": 3,
                                                "then": [
                                                    {"type": "set_variable", "name": "PROFILE_SEARCH", "value": "${PROFILE_4_SEARCH}"},
                                                    {"type": "set_variable", "name": "PROFILE_ROW_TEXT", "value": "${PROFILE_4_ROW_TEXT}"},
                                                ],
                                                "else": [
                                                    {"type": "set_variable", "name": "PROFILE_SEARCH", "value": "${PROFILE_5_SEARCH}"},
                                                    {"type": "set_variable", "name": "PROFILE_ROW_TEXT", "value": "${PROFILE_5_ROW_TEXT}"},
                                                ],
                                            },
                                        ],
                                    },
                                ],
                            },
                        ],
                    },
                    # Profile 2+: thoát stack trước khi tìm lại
                    {
                        "type": "if_variable",
                        "name": "__LOOP_INDEX__",
                        "greater_than": 0,
                        "then": [
                            {"type": "key", "key": "back"},
                            {"type": "wait", "seconds": 0.5},
                            {"type": "key", "key": "back"},
                            {"type": "wait", "seconds": 0.5},
                            {"type": "key", "key": "back"},
                            {"type": "wait", "seconds": 0.6},
                            {"type": "key", "key": "back"},
                            {"type": "wait", "seconds": 0.6},
                            {"type": "dismiss_popup", "retries": 2},
                            {"type": "wait_stable", "timeout": 4, "stable_duration": 0.4},
                        ],
                        "else": [],
                    },
                    {
                        "type": "if_element",
                        "by": "content-desc",
                        "value": "Tìm kiếm",
                        "timeout": 5,
                        "then": [{"type": "tap_selector", "by": "content-desc", "value": "Tìm kiếm", "timeout": 4}],
                        "else": [{"type": "tap_ratio", "x": 0.87, "y": 0.035}],
                    },
                    {"type": "wait_stable", "timeout": 4, "stable_duration": 0.4},
                    {"type": "input_text", "text": "${PROFILE_SEARCH}", "via": "u2"},
                    {"type": "key", "key": "enter"},
                    {
                        "type": "if_element",
                        "by": "description",
                        "value": "Kết quả tìm kiếm trong tab Mọi người, 2 trong số 7",
                        "timeout": 5,
                        "then": [
                            {
                                "type": "tap_selector",
                                "by": "description",
                                "value": "Kết quả tìm kiếm trong tab Mọi người, 2 trong số 7",
                                "timeout": 4,
                            },
                        ],
                        "else": [
                            {
                                "type": "if_element",
                                "by": "text",
                                "value": "Mọi người",
                                "timeout": 3,
                                "then": [{"type": "tap_selector", "by": "text", "value": "Mọi người", "timeout": 3}],
                                "else": [
                                    {
                                        "type": "if_element",
                                        "by": "text",
                                        "value": "People",
                                        "timeout": 3,
                                        "then": [{"type": "tap_selector", "by": "text", "value": "People", "timeout": 3}],
                                        "else": [],
                                    },
                                ],
                            },
                        ],
                    },
                    {"type": "wait_stable", "timeout": 2, "stable_duration": 0.45},
                    {"type": "tap_selector", "by": "text", "value": "${PROFILE_ROW_TEXT}", "timeout": 10},
                    {
                        "type": "scroll_down",
                        "repeats": 2,
                        "start_x_ratio": "${SCROLL_X_RATIO}",
                        "start_y_ratio": 0.65,
                        "end_y_ratio": 0.47,
                    },
                    {"type": "wait", "seconds": 2},
                    {
                        "type": "loop",
                        "count": "${MAX_SCROLLS_PER_PROFILE}",
                        "steps": [
                            {"type": "dismiss_popup", "retries": 1},
                            {
                                "type": "extract",
                                "entity": "posts", "platform": "facebook",
                                "edge_extra_data": True,
                                "extract_profile": "balanced",
                                "entity_version": "posts:v1",
                                **_FB_POST_OPEN_EXTRACT,
                                "expand_see_more": True,
                                "expand_see_more_max_passes": 2,
                                "expand_see_more_scroll": True,
                                "expand_see_more_scroll_distance": 0.25,
                                "expand_completion_retries": 2,
                                "stop_if_no_new": False,
                                "collection": "${SAVE_COLLECTION}",
                                "platform": "facebook",
                                "content_type": "fb_post",
                                "dedupe_field": "post_key",
                                "tags": "profile,crawl,${PROFILE_SEARCH}",
                            },
                            *_fb_open_comments_steps(),
                            {"type": "wait", "seconds": 0.3},
                            {
                                "type": "extract",
                                "entity": "comments", "platform": "facebook",
                                "edge_extra_data": True,
                                "extract_profile": "balanced",
                                "entity_version": "comments:v1",
                                "parent_post_id_var": "_comment_parent_pid",
                                "require_verified_parent": True,
                                "max_items": 220,
                                "comment_scroll_passes": 16,
                                "comment_swipes_per_dump": 4,
                                "comment_scroll_distance": 0.52,
                                "comment_scroll_duration_ms": 120,
                                "comment_scroll_pause_s": 0.03,
                                "comment_no_growth_break": 0,
                                "min_comment_scan_passes": 2,
                                "comment_max_snapshots": 12,
                                "comment_scroll_wall_s": 25,
                                "comment_stop_if_no_new": False,
                                "stop_if_no_new": False,
                                "no_new_threshold": 3,
                                "collection": "${SAVE_COLLECTION}",
                                "platform": "facebook",
                                "content_type": "fb_comment",
                                "dedupe_field": "comment_key",
                                "tags": "profile,comment,${PROFILE_SEARCH}",
                                "save_parent_id_var": "_active_comment_parent_hash",
                                "item_level": 1,
                            },
                            *_FB_RETURN_TO_FEED_AFTER_COMMENTS_STEPS,
                            {
                                "type": "scroll_down",
                                "repeats": 1,
                                "start_x_ratio": "${SCROLL_X_RATIO}",
                                "start_y_ratio": 0.65,
                                "end_y_ratio": 0.47,
                            },
                            {"type": "set_variable", "name": "_W", "from_list": [0.5, 0.5, 1, 1, 1.5, 2]},
                            {"type": "wait", "seconds": "${_W}"},
                        ],
                    },
                ],
            },
            {"type": "key", "key": "home"},
        ],
    },

    {
        "name": "fb_group_1h",
        "display_name": "Crawl nhóm Facebook (~1 giờ)",
        "category": "facebook",
        "description": (
            "Crawl bài viết + bình luận 1 nhóm Facebook liên tục (mặc định MAX_SCROLLS=540 ≈ 3h). "
            "Chấp nhận bài trùng lặp — DB dedup qua content_hash, loop không dừng sớm. "
            "Navigation: tìm kiếm → tab Nhóm → tap nhóm qua xpath. "
            "Scroll neo trái (SCROLL_X_RATIO=0.18) tránh mở ảnh. "
            "Mỗi bài: mở chi tiết → extract posts → atomic tap/filter comments trên detail → extract comments → quay feed.\n"
            "\n"
            "Biến cấu hình:\n"
            "  GROUP_NAME: tên nhóm để tìm kiếm.\n"
            "  GROUP_XPATH: xpath hàng nhóm trong kết quả tìm kiếm.\n"
            "  MAX_SCROLLS: số vòng crawl (mặc định 540 ≈ 3h với ~20s/vòng).\n"
            "  SCROLL_X_RATIO: neo ngang khi scroll feed (mặc định 0.18).\n"
            "  SAVE_COLLECTION: collection lưu cả bài và bình luận.\n"
            "Các tham số extra-data Facebook nằm trong từng node extract để chỉnh trên frontend."
        ),
        "tags": "facebook,group,crawl,feed,post,comment,duplicate-ok",
        "variables": {
            "GROUP_NAME": "openclaw vn",
            "GROUP_XPATH": "//*[@content-desc=\"OpenClaw VN · Truy cập\"]",
            "MAX_SCROLLS": 540,
            "SCROLL_X_RATIO": 0.18,
            "SAVE_COLLECTION": "fb_group_posts",
        },
        "steps": [
            # ── Phase 1: Khởi động ────────────────────────────────────────────
            {"type": "launch_app", "package": "com.facebook.katana", "title": "mở fb"},
            {"type": "dismiss_popup", "retries": 3},
            {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},

            # ── Phase 2: Tìm kiếm nhóm ───────────────────────────────────────
            {
                "type": "if_element", "by": "content-desc", "value": "Tìm kiếm", "timeout": 5,
                "then": [{"type": "tap_selector", "by": "content-desc", "value": "Tìm kiếm", "timeout": 4}],
                "else": [{"type": "tap_ratio", "x": 0.87, "y": 0.035}],
            },
            {"type": "wait_stable", "timeout": 4, "stable_duration": 0.4},
            {"type": "input_text", "text": "${GROUP_NAME}", "via": "u2"},
            {"type": "wait", "seconds": 2},
            {"type": "key", "key": "enter"},
            {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},

            # ── Phase 3: Chọn tab Nhóm ───────────────────────────────────────
            {
                "type": "if_element", "by": "description", "value": "Kết quả tìm kiếm trong tab Nhóm, 3 trong số 7", "timeout": 5,
                "then": [{"type": "tap_selector", "by": "description", "value": "Kết quả tìm kiếm trong tab Nhóm, 3 trong số 7", "timeout": 4}],
                "else": [
                    {
                        "type": "if_element", "by": "text", "value": "Nhóm", "timeout": 3,
                        "then": [{"type": "tap_selector", "by": "text", "value": "Nhóm", "timeout": 3}],
                        "else": [
                            {
                                "type": "if_element", "by": "text", "value": "Groups", "timeout": 3,
                                "then": [{"type": "tap_selector", "by": "text", "value": "Groups", "timeout": 3}],
                                "else": [],
                            },
                        ],
                    },
                ],
            },
            {"type": "wait_stable", "timeout": 1, "stable_duration": 0.5},

            # ── Phase 4: Tap vào nhóm ───────────────────────────────────────
            {
                "type": "if_variable",
                "name": "TARGET_SELECTOR_VALUE",
                "then": [
                    {
                        "type": "if_element",
                        "by": "${TARGET_SELECTOR_BY}",
                        "value": "${TARGET_SELECTOR_VALUE}",
                        "timeout": 8,
                        "then": [
                            {
                                "type": "tap_selector",
                                "by": "${TARGET_SELECTOR_BY}",
                                "value": "${TARGET_SELECTOR_VALUE}",
                                "timeout": 8,
                            }
                        ],
                        "else": [
                            {
                                "type": "tap_selector",
                                "by": "${TARGET_FALLBACK_SELECTOR_BY}",
                                "value": "${TARGET_FALLBACK_SELECTOR_VALUE}",
                                "timeout": 8,
                            }
                        ],
                    }
                ],
                "else": [
                    {
                        "type": "tap_selector",
                        "by": "xpath",
                        "value": "${GROUP_XPATH}",
                        "timeout": 8,
                    }
                ],
            },
            {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},
            {"type": "scroll_down", "repeats": 2, "start_x_ratio": "${SCROLL_X_RATIO}", "start_y_ratio": 0.65, "end_y_ratio": 0.47},
            {"type": "wait", "seconds": 3},

            # ── Phase 5: Loop crawl ──────────────────────────────────────────
            # ~20s/vòng × 540 ≈ 3h. Tăng MAX_SCROLLS tuỳ ý.
            {
                "type": "loop",
                "count": "${MAX_SCROLLS}",
                "steps": [
                    # Dọn popup nhanh mỗi đầu vòng
                    {"type": "dismiss_popup", "retries": 1},

                    # Extract bài viết (expand "Xem thêm" tối đa 2 lần — đủ cho hầu hết bài)
                    {
                        "type": "extract",
                        "entity": "posts", "platform": "facebook",
                        "edge_extra_data": True,
                        "extract_profile": "balanced",
                        "entity_version": "posts:v1",
                        **_FB_POST_OPEN_EXTRACT,
                        "expand_see_more": True,
                        "expand_see_more_max_passes": 2,
                        "expand_see_more_scroll": True,
                        "expand_see_more_scroll_distance": 0.25,
                        "expand_completion_retries": 2,
                        "stop_if_no_new": False,
                        "collection": "${SAVE_COLLECTION}",
                        "platform": "facebook",
                        "content_type": "fb_post",
                        "dedupe_field": "post_key",
                        "tags": "group,crawl,${GROUP_NAME}",
                    },
                    # Mở comments bằng node tuần tự để preview/runtime highlight từng hành động.
                    *_fb_open_comments_steps(),
                    {"type": "wait", "seconds": 0.3},
                    {
                        "type": "extract",
                        "entity": "comments", "platform": "facebook",
                        "edge_extra_data": True,
                        "extract_profile": "balanced",
                        "entity_version": "comments:v1",
                        "parent_post_id_var": "_comment_parent_pid",
                        "require_verified_parent": True,
                        "max_items": 220,
                        "comment_scroll_passes": 16,
                        "comment_swipes_per_dump": 4,
                        "comment_scroll_distance": 0.52,
                        "comment_scroll_duration_ms": 120,
                        "comment_scroll_pause_s": 0.03,
                        "comment_no_growth_break": 0,
                        "min_comment_scan_passes": 2,
                        "comment_max_snapshots": 12,
                        "comment_scroll_wall_s": 25,
                        "comment_stop_if_no_new": False,
                        "stop_if_no_new": False,
                        "no_new_threshold": 3,
                        "collection": "${SAVE_COLLECTION}",
                        "platform": "facebook",
                        "content_type": "fb_comment",
                        "dedupe_field": "comment_key",
                        "tags": "group,comment,${GROUP_NAME}",
                        "save_parent_id_var": "_active_comment_parent_hash",
                        "item_level": 1,
                    },
                    *_FB_RETURN_TO_FEED_AFTER_COMMENTS_STEPS,

                    # Scroll feed (neo trái tránh mở ảnh) + delay tự nhiên
                    {"type": "scroll_down", "repeats": 1, "start_x_ratio": "${SCROLL_X_RATIO}", "start_y_ratio": 0.65, "end_y_ratio": 0.47},
                    {"type": "set_variable", "name": "_W", "from_list": [0.5, 0.5, 1, 1, 1.5, 2]},
                    {"type": "wait", "seconds": "${_W}"},
                ],
            },

            # ── Phase 6: Kết thúc ────────────────────────────────────────────
            {"type": "key", "key": "home"},
        ],
    },

    {
        "name": "craw fb",
        "category": "facebook",
        "description": (
            "Crawl bài viết + bình luận 1 nhóm Facebook. Mặc định dùng biến global group_name. "
            "Nếu thiết bị có config group_name/search cùng tên thì giá trị thiết bị ghi đè global."
        ),
        "tags": "facebook,group,crawl,feed,post,comment,device-override",
        "variables": {
            "group_name": "openclaw vn",
            "MAX_SCROLLS": 540,
            "SCROLL_X_RATIO": 0.18,
            "SAVE_COLLECTION": "fb_group_posts",
        },
        "steps": [
            {
                "type": "if_variable",
                "name": "TARGET_GROUP_NAME",
                "then": [],
                "else": [
                    {
                        "type": "set_variable",
                        "name": "TARGET_GROUP_NAME",
                        "value": "${group_name}",
                    }
                ],
            },
            {
                "type": "set_variable",
                "name": "SEARCH_TEXT",
                "value": "${TARGET_GROUP_NAME}",
            },
            {
                "type": "if_variable",
                "name": "TARGET_SEARCH_QUERY",
                "then": [
                    {
                        "type": "set_variable",
                        "name": "SEARCH_TEXT",
                        "value": "${TARGET_SEARCH_QUERY}",
                    }
                ],
                "else": [],
            },
            {
                "type": "if_variable",
                "name": "search",
                "then": [
                    {"type": "set_variable", "name": "SEARCH_TEXT", "value": "${search}"},
                ],
                "else": [],
            },
            {"type": "launch_app", "package": "com.facebook.katana", "title": "mở fb"},
            {
                "type": "if_element",
                "by": "description",
                "value": "Tìm kiếm",
                "timeout": 5,
                "then": [
                    {"type": "tap_selector", "by": "description", "value": "Tìm kiếm", "timeout": 4},
                ],
                "else": [
                    {"type": "tap_ratio", "x": 0.87, "y": 0.035},
                ],
            },
            {"type": "wait_stable", "timeout": 4, "stable_duration": 0.4},
            {"type": "input_text", "text": "${SEARCH_TEXT}", "via": "u2"},
            {"type": "wait", "seconds": 2},
            {"type": "key", "key": "enter"},
            {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},
            {
                "type": "if_element",
                "by": "descriptionContains",
                "value": "tab Nhóm",
                "timeout": 5,
                "then": [
                    {
                        "type": "tap_selector",
                        "by": "descriptionContains",
                        "value": "tab Nhóm",
                        "timeout": 4,
                    },
                ],
                "else": [
                    {
                        "type": "if_element",
                        "by": "text",
                        "value": "Nhóm",
                        "timeout": 3,
                        "then": [
                            {
                                "type": "tap_selector",
                                "by": "text",
                                "value": "Nhóm",
                                "timeout": 3,
                            }
                        ],
                        "else": [
                            {
                                "type": "tap_selector",
                                "by": "text",
                                "value": "Groups",
                                "timeout": 3,
                                "ignore_error": True,
                            }
                        ],
                    }
                ],
            },
            {"type": "wait_stable", "timeout": 1, "stable_duration": 0.5},
            {
                "type": "if_variable",
                "name": "TARGET_SELECTOR_VALUE",
                "then": [
                    {
                        "type": "if_element",
                        "by": "${TARGET_SELECTOR_BY}",
                        "value": "${TARGET_SELECTOR_VALUE}",
                        "timeout": 8,
                        "then": [
                            {
                                "type": "tap_selector",
                                "by": "${TARGET_SELECTOR_BY}",
                                "value": "${TARGET_SELECTOR_VALUE}",
                                "timeout": 8,
                            }
                        ],
                        "else": [
                            {
                                "type": "tap_selector",
                                "by": "${TARGET_FALLBACK_SELECTOR_BY}",
                                "value": "${TARGET_FALLBACK_SELECTOR_VALUE}",
                                "timeout": 8,
                            }
                        ],
                    }
                ],
                "else": [
                    {
                        "type": "tap_selector",
                        "by": "text",
                        "value": "${TARGET_GROUP_NAME}",
                        "timeout": 8,
                    }
                ],
            },
            {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},
            {
                "type": "scroll_down",
                "repeats": 2,
                "start_x_ratio": "${SCROLL_X_RATIO}",
                "start_y_ratio": 0.65,
                "end_y_ratio": 0.47,
            },
            {"type": "wait", "seconds": 3},
            {
                "type": "loop",
                "count": "${MAX_SCROLLS}",
                "steps": [
                    {"type": "dismiss_popup", "retries": 1},
                    {
                        "type": "extract",
                        "entity": "posts", "platform": "facebook",
                        "edge_extra_data": True,
                        "extract_profile": "balanced",
                        "entity_version": "posts:v1",
                        **_FB_POST_OPEN_EXTRACT,
                        "expand_see_more": True,
                        "expand_see_more_max_passes": 2,
                        "expand_see_more_scroll": True,
                        "expand_see_more_scroll_distance": 0.25,
                        "expand_completion_retries": 2,
                        "stop_if_no_new": False,
                        "collection": "${SAVE_COLLECTION}",
                        "platform": "facebook",
                        "content_type": "fb_post",
                        "dedupe_field": "post_key",
                        "tags": "group,crawl,${TARGET_GROUP_NAME}",
                    },
                    *_fb_open_comments_steps(),
                    {"type": "wait", "seconds": 0.3},
                    {
                        "type": "extract",
                        "entity": "comments", "platform": "facebook",
                        "edge_extra_data": True,
                        "extract_profile": "balanced",
                        "entity_version": "comments:v1",
                        "parent_post_id_var": "_comment_parent_pid",
                        "require_verified_parent": True,
                        "max_items": 220,
                        "comment_scroll_passes": 16,
                        "comment_swipes_per_dump": 4,
                        "comment_scroll_distance": 0.52,
                        "comment_scroll_duration_ms": 120,
                        "comment_scroll_pause_s": 0.03,
                        "comment_no_growth_break": 0,
                        "min_comment_scan_passes": 2,
                        "comment_max_snapshots": 12,
                        "comment_scroll_wall_s": 25,
                        "comment_stop_if_no_new": False,
                        "stop_if_no_new": False,
                        "no_new_threshold": 3,
                        "collection": "${SAVE_COLLECTION}",
                        "platform": "facebook",
                        "content_type": "fb_comment",
                        "dedupe_field": "comment_key",
                        "tags": "group,comment,${TARGET_GROUP_NAME}",
                        "save_parent_id_var": "_active_comment_parent_hash",
                        "item_level": 1,
                    },
                    *_FB_RETURN_TO_FEED_AFTER_COMMENTS_STEPS,
                    {
                        "type": "scroll_down",
                        "repeats": 1,
                        "start_x_ratio": "${SCROLL_X_RATIO}",
                        "start_y_ratio": 0.65,
                        "end_y_ratio": 0.47,
                    },
                    {"type": "set_variable", "name": "_W", "from_list": [0.5, 0.5, 1, 1, 1.5, 2]},
                    {"type": "wait", "seconds": "${_W}"},
                ],
            },
            {"type": "key", "key": "home"},
        ],
    },


]

# ─────────────────────────────────────────────────────────────────────────────
# Aggregate list
# ─────────────────────────────────────────────────────────────────────────────

BUILTIN_TEMPLATES: List[Dict[str, Any]] = (
    _FACEBOOK_TEMPLATES
)

BUILTIN_TEMPLATE_BY_NAME: Dict[str, Dict[str, Any]] = {
    spec["name"]: spec for spec in BUILTIN_TEMPLATES
}


def _spec_for_template_row(tmpl) -> Dict[str, Any] | None:
    """Match DB row to code-managed builtin spec (by technical name)."""
    if tmpl.name in BUILTIN_TEMPLATE_BY_NAME:
        return BUILTIN_TEMPLATE_BY_NAME[tmpl.name]
    key = str(tmpl.name or "").strip().lower()
    for spec in BUILTIN_TEMPLATES:
        if str(spec.get("name", "")).strip().lower() == key:
            return spec
    return None


def _graph_mirror_from_steps(steps: list) -> tuple[list, list]:
    """
    Derive nodes/edges from steps for a future flow editor (not used at runtime today).
    Canonical execution format remains flat steps[] (sequence).
    """
    if not steps:
        return [], []
    from common.graph_compiler import steps_to_graph

    nodes, edges = steps_to_graph(steps)
    return nodes, edges


async def repair_builtin_templates_to_sequence(db) -> int:
    """
    Sync builtin templates: steps are canonical; nodes/edges are a derived graph mirror.

    - Code specs win when the row name matches BUILTIN_TEMPLATES.
    - If only graph exists, compile → steps then refresh the graph mirror from steps.
    - Never wipe nodes/edges without regenerating them from steps.
    """
    import logging

    from sqlalchemy import select

    from common.graph_compiler import compile_graph_to_steps
    from db.crud.scenario_template import update_template
    from db.models.scenario_template import ScenarioTemplate

    log = logging.getLogger(__name__)
    changed = 0
    result = await db.execute(
        select(ScenarioTemplate).where(ScenarioTemplate.is_builtin.is_(True))
    )
    for tmpl in result.scalars().all():
        spec = _spec_for_template_row(tmpl)
        steps = list(tmpl.steps) if isinstance(tmpl.steps, list) else []
        nodes = list(tmpl.nodes) if isinstance(tmpl.nodes, list) else []
        edges = list(tmpl.edges) if isinstance(tmpl.edges, list) else []

        new_steps: list = []
        if spec and spec.get("steps"):
            new_steps = list(spec["steps"])
        elif steps:
            new_steps = steps
        elif nodes or edges:
            try:
                new_steps = compile_graph_to_steps(nodes, edges)
            except Exception as exc:
                log.warning(
                    "Could not compile graph for builtin template %r: %s",
                    tmpl.name,
                    exc,
                )
                new_steps = []

        if not new_steps:
            if nodes or edges:
                log.warning(
                    "Builtin template %r still graph-only with no steps — "
                    "add to BUILTIN_TEMPLATES or restore from code spec",
                    tmpl.name,
                )
            continue

        graph_nodes, graph_edges = _graph_mirror_from_steps(new_steps)
        updates: Dict[str, Any] = {
            "steps": new_steps,
            "nodes": graph_nodes,
            "edges": graph_edges,
        }
        if spec:
            if spec.get("display_name") is not None:
                updates["display_name"] = spec.get("display_name", "")
            if spec.get("description") is not None:
                updates["description"] = spec.get("description", "")
            if spec.get("category") is not None:
                updates["category"] = spec.get("category", "general")
            if spec.get("variables") is not None:
                updates["variables"] = spec.get("variables", {})
            if spec.get("tags") is not None:
                updates["tags"] = spec.get("tags", "")
            updates["is_builtin"] = spec.get("is_builtin", True)

        await update_template(db, tmpl.id, **updates)
        changed += 1

    return changed


async def seed_builtin_templates(db) -> int:
    """
    Upsert BUILTIN_TEMPLATES: insert if not found, update steps/variables/description
    if already exists (so template fixes are applied on every restart).

    Returns the number of templates inserted or updated.
    """
    from db.crud.scenario_template import create_template, get_template_by_name, update_template

    changed = 0
    for spec in BUILTIN_TEMPLATES:
        spec_is_builtin = spec.get("is_builtin", True)
        raw_steps = spec.get("steps", [])
        if not raw_steps:
            continue
        graph_nodes, graph_edges = _graph_mirror_from_steps(raw_steps)
        existing = await get_template_by_name(db, spec["name"])
        if existing is None:
            await create_template(
                db,
                name=spec["name"],
                display_name=spec.get("display_name", ""),
                description=spec.get("description", ""),
                category=spec.get("category", "general"),
                steps=raw_steps,
                variables=spec.get("variables", {}),
                tags=spec.get("tags", ""),
                is_builtin=spec_is_builtin,
                user_id=None,
                nodes=graph_nodes,
                edges=graph_edges,
            )
            changed += 1
        else:
            # Sync steps from code; refresh graph mirror from steps (future flow editor).
            await update_template(
                db,
                existing.id,
                display_name=spec.get("display_name", ""),
                description=spec.get("description", ""),
                category=spec.get("category", "general"),
                steps=raw_steps,
                variables=spec.get("variables", {}),
                tags=spec.get("tags", ""),
                is_builtin=spec_is_builtin,
                nodes=graph_nodes,
                edges=graph_edges,
            )
            changed += 1

    changed += await repair_builtin_templates_to_sequence(db)

    if changed:
        await db.commit()

    return changed
