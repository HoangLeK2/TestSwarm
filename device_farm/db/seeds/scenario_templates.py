from __future__ import annotations

"""
db/seeds/scenario_templates.py — Builtin scenario template seed data.

Called once on startup (idempotent: skipped if builtins already exist).
Templates use:
  - DF-001 variable interpolation  (${VAR})
  - DF-002 control flow            (repeat, repeat_until, if_element, if_variable, random_pick)
  - DF-006 data extraction         (extract strategy=fb_posts/fb_comments; optional inline save via collection=…)

Template step types used:
  launch_app, open_url, wait, wait_stable, wait_element, dismiss_popup, key,
  scroll_down, swipe_ratio, tap_selector, input_selector, input_text,
  set_variable, repeat, repeat_until, if_element, if_variable, random_pick,
  login_if_needed, fill_form, assert_app_state,
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

from typing import Any, Dict, List

# fb_posts: mở chi tiết bài trước extract; back do kịch bản điều khiển (không auto trong agent).
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
            "type": "fb_find_comment_button",
            "timeout": timeout,
            "require_post_before_comment": True,
            "comment_filter": comment_filter,
            "switch_to_all_comments": comment_filter == "all_comments",
            "ignore_error": True,
        },
        {
            "type": "fb_tap_comment_target",
            "post_tap_wait_s": post_tap_wait_s,
            "ignore_error": True,
        },
        {
            "type": "fb_apply_comment_filter",
            "comment_filter": comment_filter,
            "switch_to_all_comments": comment_filter == "all_comments",
            "comment_filter_settle_s": 0.45,
            "comment_filter_step_pause_s": 0.35,
            "comment_filter_post_select_s": 0.85,
        },
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
    },
    "login_recipe": {
        "detect_logged_in": _FB_DETECT_LOGGED_IN,
        "fields": {
            "username": {"locator": "username_field", "value_from": "account.username"},
            "password": {"locator": "password_field", "value_from": "secret.login_password"},
        },
        "submit": {"locator": "login_button"},
    },
}

_FB_LOGIN_PROFILE_GOOGLE: Dict[str, Any] = {
    "package": "com.facebook.katana",
    "semantic_locators": {
        "fb_google_button": {
            "candidates": [
                {"by": "text", "value": "Continue with Google"},
                {"by": "text", "value": "Tiếp tục với Google"},
                {"description_contains": "Google"},
            ]
        },
        "google_email_field": {
            "candidates": [{"by": "resource-id", "value": "identifierId"}]
        },
        "google_next_button": {
            "candidates": [
                {"by": "text", "value": "NEXT"},
                {"by": "text", "value": "Tiếp theo"},
                {"by": "text", "value": "Tiếp tục"},
            ]
        },
        "google_password_field": {
            "candidates": [
                {"by": "resource-id", "value": "password"},
                {"by": "resource-id", "value": "Passwd"},
            ]
        },
        "google_signin_button": {
            "candidates": [
                {"by": "text", "value": "Next"},
                {"by": "text", "value": "NEXT"},
                {"by": "text", "value": "Sign in"},
                {"by": "text", "value": "Đăng nhập"},
            ]
        },
    },
    "login_recipe": {
        "detect_logged_in": _FB_DETECT_LOGGED_IN,
        "fields": {
            "email": {"locator": "google_email_field", "value_from": "account.username"},
        },
        "submit": {"locator": "google_next_button"},
    },
    "form_recipes": {
        "google_password": {
            "fields": {
                "password": {
                    "locator": "google_password_field",
                    "value_from": "secret.login_password",
                }
            },
            "submit": {"locator": "google_signin_button"},
        }
    },
    "popup_watchers": [
        {
            "name": "google_oauth_terms_en",
            "when": {"text": "I agree"},
            "action": {"tap_text": "I agree"},
            "scope": {"package": "com.google.android.gms"},
        },
        {
            "name": "google_oauth_terms_vi",
            "when": {"text": "Tôi đồng ý"},
            "action": {"tap_text": "Tôi đồng ý"},
            "scope": {"package": "com.google.android.gms"},
        },
    ],
}

_FB_TAP_GOOGLE_BUTTON_STEPS: List[Dict[str, Any]] = [
    {
        "type": "if_element",
        "by": "text",
        "value": "Tiếp tục với Google",
        "timeout": 4,
        "then": [
            {"type": "tap_selector", "by": "text", "value": "Tiếp tục với Google", "timeout": 4},
        ],
        "else": [
            {
                "type": "if_element",
                "by": "text",
                "value": "Continue with Google",
                "timeout": 3,
                "then": [
                    {"type": "tap_selector", "by": "text", "value": "Continue with Google", "timeout": 4},
                ],
                "else": [],
            },
        ],
    },
    {"type": "wait_stable", "timeout": 4, "stable_duration": 0.4},
]

_FB_GOOGLE_LOGIN_STEPS: List[Dict[str, Any]] = [
    *_FB_TAP_GOOGLE_BUTTON_STEPS,
    {"type": "login_if_needed", "profile": _FB_LOGIN_PROFILE_GOOGLE, "clear_first": True},
    {
        "type": "fill_form",
        "recipe": "google_password",
        "profile": _FB_LOGIN_PROFILE_GOOGLE,
        "clear_first": True,
    },
    {"type": "wait", "seconds": 8, "profile": _FB_LOGIN_PROFILE_GOOGLE},
    {"type": "launch_app", "package": "com.facebook.katana"},
    {"type": "wait_stable", "timeout": 5, "stable_duration": 0.5},
]

_FB_NATIVE_LOGIN_STEPS: List[Dict[str, Any]] = [
    {"type": "login_if_needed", "profile": _FB_LOGIN_PROFILE_NATIVE, "clear_first": True},
]

_FB_LOGIN_METHOD_BRANCH: List[Dict[str, Any]] = [
    {
        "type": "if_variable",
        "name": "LOGIN_METHOD",
        "equals": "google",
        "then": _FB_GOOGLE_LOGIN_STEPS,
        "else": [
            {
                "type": "if_variable",
                "name": "LOGIN_METHOD",
                "equals": "native",
                "then": _FB_NATIVE_LOGIN_STEPS,
                "else": [
                    {
                        "type": "if_element",
                        "by": "text",
                        "value": "Tiếp tục với Google",
                        "timeout": 3,
                        "then": _FB_GOOGLE_LOGIN_STEPS,
                        "else": [
                            {
                                "type": "if_element",
                                "by": "text",
                                "value": "Continue with Google",
                                "timeout": 2,
                                "then": _FB_GOOGLE_LOGIN_STEPS,
                                "else": _FB_NATIVE_LOGIN_STEPS,
                            },
                        ],
                    },
                ],
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
            "Mở Facebook và đăng nhập khi chưa có session. Hỗ trợ native (SĐT/email + mật khẩu FB) "
            "và Google SSO (Gmail + mật khẩu Google). Account platform vẫn là facebook.\n"
            "Biến LOGIN_METHOD: auto (mặc định — ưu tiên nút Google nếu thấy), native, google.\n"
            "Account Google SSO: username = Gmail, tag google, mật khẩu Google qua secret.login_password."
        ),
        "tags": "facebook,login,app-automation,native,google",
        "variables": {
            "LOGIN_METHOD": "auto",
        },
        "steps": [
            {"type": "launch_app", "package": "com.facebook.katana", "title": "Mở Facebook"},
            {"type": "wait_stable", "timeout": 5, "stable_duration": 0.5},
            {"type": "dismiss_popup", "retries": 2},
            {
                "type": "if_element",
                "by": "text",
                "value": "Bạn đang nghĩ gì?",
                "timeout": 4,
                "then": [],
                "else": [
                    {
                        "type": "if_element",
                        "by": "text",
                        "value": "Trang chủ",
                        "timeout": 2,
                        "then": [],
                        "else": _FB_LOGIN_METHOD_BRANCH,
                    },
                ],
            },
            {"type": "login_if_needed", "profile": _FB_LOGIN_PROFILE_NATIVE},
            {
                "type": "assert_app_state",
                "profile": _FB_LOGIN_PROFILE_NATIVE,
                "any_text": ["Trang chủ", "Tìm kiếm", "Bạn đang nghĩ gì?"],
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
                "strategy": "fb_groups",
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
                        "strategy": "fb_posts",
                        "edge_extra_data": True,
                        "extract_profile": "balanced",
                        "strategy_version": "fb_posts:v1",
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
                        "strategy": "fb_comments",
                        "edge_extra_data": True,
                        "extract_profile": "balanced",
                        "strategy_version": "fb_comments:v1",
                        "parent_post_id_var": "_fb_comment_parent_pid",
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
                                "strategy": "fb_posts",
                                "edge_extra_data": True,
                                "extract_profile": "balanced",
                                "strategy_version": "fb_posts:v1",
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
                                "strategy": "fb_comments",
                                "edge_extra_data": True,
                                "extract_profile": "balanced",
                                "strategy_version": "fb_comments:v1",
                                "parent_post_id_var": "_fb_comment_parent_pid",
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
                        "strategy": "fb_posts",
                        "edge_extra_data": True,
                        "extract_profile": "balanced",
                        "strategy_version": "fb_posts:v1",
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
                        "strategy": "fb_comments",
                        "edge_extra_data": True,
                        "extract_profile": "balanced",
                        "strategy_version": "fb_comments:v1",
                        "parent_post_id_var": "_fb_comment_parent_pid",
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
                        "strategy": "fb_posts",
                        "edge_extra_data": True,
                        "extract_profile": "balanced",
                        "strategy_version": "fb_posts:v1",
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
                        "strategy": "fb_comments",
                        "edge_extra_data": True,
                        "extract_profile": "balanced",
                        "strategy_version": "fb_comments:v1",
                        "parent_post_id_var": "_fb_comment_parent_pid",
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
