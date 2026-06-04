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
  set_variable, repeat, repeat_until, if_element, random_pick,
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

_FACEBOOK_TEMPLATES: List[Dict[str, Any]] = [


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
            {"type": "tap_selector", "by": "text", "value": "${GROUP_TEXT}", "timeout": 8},
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
                    # Atomic tap trên chính detail vừa mở: giữ parent context chính xác cho comments.
                    # pre_scroll=True: cuộn nhẹ lộ nút/filter nếu cần.
                    {
                        "type": "fb_tap_comment_button",
                        "timeout": 5,
                        "pre_scroll": True,
                        "pre_scroll_distance": 0.24,
                        "post_tap_wait_s": 0.6,
                        "enter_comment_sheet_timeout": 2.0,
                        "switch_to_all_comments": True,
                        "then": [
                            {"type": "wait", "seconds": 0.6},
                            {
                                "type": "extract",
                                "strategy": "fb_comments",
                                "edge_extra_data": True,
                                "extract_profile": "balanced",
                                "strategy_version": "fb_comments:v1",
                                "parent_post_id_var": "_fb_comment_parent_pid",
                                "max_items": 500,
                                "comment_scroll_passes": 48,
                                "comment_swipes_per_dump": 3,
                                "comment_scroll_distance": 0.30,
                                "comment_scroll_duration_ms": 300,
                                "comment_scroll_pause_s": 0.12,
                                "comment_no_growth_break": 3,
                                "min_comment_scan_passes": 2,
                                "stop_if_no_new": False,
                                "no_new_threshold": 4,
                                "collection": "${SAVE_COLLECTION}",
                                "platform": "facebook",
                                "content_type": "fb_comment",
                                "dedupe_field": "comment_key",
                                "tags": "group,comment,${GROUP_NAME}",
                                "save_parent_id_var": "_active_comment_parent_hash",
                                "item_level": 1,
                            },
                            *_FB_RETURN_TO_FEED_AFTER_COMMENTS_STEPS,
                        ],
                        "else": [],
                    },

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
                            {
                                "type": "fb_tap_comment_button",
                                "timeout": 5,
                                "pre_scroll": True,
                                "pre_scroll_distance": 0.24,
                                "post_tap_wait_s": 0.6,
                                "enter_comment_sheet_timeout": 2.0,
                                "switch_to_all_comments": True,
                                "then": [
                                    {"type": "wait", "seconds": 0.6},
                                    {
                                        "type": "extract",
                                        "strategy": "fb_comments",
                                        "edge_extra_data": True,
                                        "extract_profile": "balanced",
                                        "strategy_version": "fb_comments:v1",
                                        "parent_post_id_var": "_fb_comment_parent_pid",
                                        "max_items": 500,
                                        "comment_scroll_passes": 48,
                                        "comment_swipes_per_dump": 3,
                                        "comment_scroll_distance": 0.30,
                                        "comment_scroll_duration_ms": 300,
                                        "comment_scroll_pause_s": 0.12,
                                        "comment_no_growth_break": 3,
                                        "min_comment_scan_passes": 2,
                                        "stop_if_no_new": False,
                                        "no_new_threshold": 4,
                                        "collection": "${SAVE_COLLECTION}",
                                        "platform": "facebook",
                                        "content_type": "fb_comment",
                                        "dedupe_field": "comment_key",
                                        "tags": "profile,comment,${PROFILE_SEARCH}",
                                        "save_parent_id_var": "_active_comment_parent_hash",
                                        "item_level": 1,
                                    },
                                    *_FB_RETURN_TO_FEED_AFTER_COMMENTS_STEPS,
                                ],
                                "else": [],
                            },
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
            {"type": "tap_selector", "by": "xpath", "value": "${GROUP_XPATH}", "timeout": 8},
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
                    # Atomic tap trên chính detail vừa mở: giữ parent context chính xác cho comments.
                    # pre_scroll=True: cuộn nhẹ lộ nút/filter nếu cần.
                    {
                        "type": "fb_tap_comment_button",
                        "timeout": 5,
                        "pre_scroll": True,
                        "pre_scroll_distance": 0.24,
                        "post_tap_wait_s": 0.6,
                        "enter_comment_sheet_timeout": 2.0,
                        "switch_to_all_comments": True,
                        "then": [
                            {"type": "wait", "seconds": 0.6},
                            {
                                "type": "extract",
                                "strategy": "fb_comments",
                                "edge_extra_data": True,
                                "extract_profile": "balanced",
                                "strategy_version": "fb_comments:v1",
                                "parent_post_id_var": "_fb_comment_parent_pid",
                                "max_items": 500,
                                "comment_scroll_passes": 48,
                                "comment_swipes_per_dump": 3,
                                "comment_scroll_distance": 0.30,
                                "comment_scroll_duration_ms": 300,
                                "comment_scroll_pause_s": 0.12,
                                "comment_no_growth_break": 3,
                                "min_comment_scan_passes": 2,
                                "stop_if_no_new": False,
                                "no_new_threshold": 4,
                                "collection": "${SAVE_COLLECTION}",
                                "platform": "facebook",
                                "content_type": "fb_comment",
                                "dedupe_field": "comment_key",
                                "tags": "group,comment,${GROUP_NAME}",
                                "save_parent_id_var": "_active_comment_parent_hash",
                                "item_level": 1,
                            },
                            *_FB_RETURN_TO_FEED_AFTER_COMMENTS_STEPS,
                        ],
                        "else": [],
                    },

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
            {"type": "set_variable", "name": "SEARCH_TEXT", "value": "${group_name}"},
            {"type": "set_variable", "name": "TARGET_GROUP_NAME", "value": "${group_name}"},
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
                "by": "description",
                "value": "Kết quả tìm kiếm trong tab Nhóm, 3 trong số 7",
                "timeout": 5,
                "then": [
                    {
                        "type": "tap_selector",
                        "by": "description",
                        "value": "Kết quả tìm kiếm trong tab Nhóm, 3 trong số 7",
                        "timeout": 4,
                    },
                ],
                "else": [],
            },
            {"type": "wait_stable", "timeout": 1, "stable_duration": 0.5},
            {"type": "tap_selector", "by": "text", "value": "${TARGET_GROUP_NAME}", "timeout": 8},
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
                    {
                        "type": "fb_tap_comment_button",
                        "timeout": 5,
                        "pre_scroll": True,
                        "pre_scroll_distance": 0.24,
                        "post_tap_wait_s": 0.6,
                        "enter_comment_sheet_timeout": 2,
                        "switch_to_all_comments": True,
                        "then": [
                            {"type": "wait", "seconds": 0.6},
                            {
                                "type": "extract",
                                "strategy": "fb_comments",
                                "edge_extra_data": True,
                                "extract_profile": "balanced",
                                "strategy_version": "fb_comments:v1",
                                "parent_post_id_var": "_fb_comment_parent_pid",
                                "max_items": 500,
                                "comment_scroll_passes": 48,
                                "comment_swipes_per_dump": 3,
                                "comment_scroll_distance": 0.30,
                                "comment_scroll_duration_ms": 300,
                                "comment_scroll_pause_s": 0.12,
                                "comment_no_growth_break": 3,
                                "min_comment_scan_passes": 2,
                                "stop_if_no_new": False,
                                "no_new_threshold": 4,
                                "collection": "${SAVE_COLLECTION}",
                                "platform": "facebook",
                                "content_type": "fb_comment",
                                "dedupe_field": "comment_key",
                                "tags": "group,comment,${TARGET_GROUP_NAME}",
                                "save_parent_id_var": "_active_comment_parent_hash",
                                "item_level": 1,
                            },
                            *_FB_RETURN_TO_FEED_AFTER_COMMENTS_STEPS,
                        ],
                        "else": [],
                    },
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
