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

_FACEBOOK_TEMPLATES: List[Dict[str, Any]] = [


    {
        "name": "Crawl bài viết + bình luận 1 nhóm Facebook",
        "is_builtin": False,
        "category": "facebook",
        "description": (
            "Crawl bài viết + bình luận 1 nhóm Facebook liên tục (mặc định MAX_SCROLLS=540 ≈ 3h). "
            "Chấp nhận bài trùng lặp — DB dedup qua content_hash, loop không dừng sớm. "
            "Navigation: tìm kiếm → tab Nhóm → tap nhóm qua text. "
            "Scroll neo trái (SCROLL_X_RATIO=0.18) tránh mở ảnh. "
            "Mỗi bài: extract posts → cuộn nhẹ lộ nút Bình luận → atomic tap + switch filter → extract comments → back.\n"
        ),
        "tags": "facebook,group,crawl",
        "variables": {
            "GROUP_NAME": "openclaw vn",
            "GROUP_TEXT": "OpenClaw VN · Truy cập",
            "MAX_SCROLLS": 540,
            "MAX_COMMENT_SCROLLS": 35,
            "MAX_COMMENTS_PER_POST": 500,
            "MIN_COMMENT_SCAN_PASSES": 4,
            "COMMENT_NO_NEW_THRESHOLD": 3,
            "SCROLL_X_RATIO": 0.18,
            "SAVE_COLLECTION": "fb_group_posts",
            "EXTRACT_PROFILE": "balanced",
            "FB_POSTS_STRATEGY_VERSION": "fb_posts:v1",
            "FB_COMMENTS_STRATEGY_VERSION": "fb_comments:v1",
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
                        "extract_profile": "${EXTRACT_PROFILE}",
                        "strategy_version": "${FB_POSTS_STRATEGY_VERSION}",
                        "expand_see_more": True,
                        "expand_see_more_max_passes": 2,
                        "expand_see_more_scroll": True,
                        "expand_see_more_scroll_distance": 0.25,
                        "expand_completion_retries": 2,
                        "stop_if_no_new": False,
                        "collection": "${SAVE_COLLECTION}",
                        "platform": "facebook",
                        "content_type": "group_post",
                        "dedupe_field": "post_key",
                        "tags": "group,crawl,${GROUP_NAME}",
                    },

                    # Atomic tap: resolve → ghi _pid → bấm Bình luận → switch filter
                    # pre_scroll=True: cuộn nhẹ lộ nút (thay scroll_down riêng)
                    {
                        "type": "tap_fb_comment_button",
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
                                "extract_profile": "${EXTRACT_PROFILE}",
                                "strategy_version": "${FB_COMMENTS_STRATEGY_VERSION}",
                                "parent_post_id_var": "_fb_comment_parent_pid",
                                "expand_see_more": True,
                                "expand_see_more_max_passes": 4,
                                "expand_see_more_scroll": True,
                                "expand_see_more_scroll_distance": 0.2,
                                "max_items": "${MAX_COMMENTS_PER_POST}",
                                "comment_scroll_passes": "${MAX_COMMENT_SCROLLS}",
                                "comment_scroll_distance": 0.22,
                                "comment_scroll_duration_ms": 340,
                                "comment_scroll_pause_s": 0.3,
                                "comment_no_growth_break": "${COMMENT_NO_NEW_THRESHOLD}",
                                "min_comment_scan_passes": "${MIN_COMMENT_SCAN_PASSES}",
                                "stop_if_no_new": False,
                                "no_new_threshold": 4,
                                "collection": "${SAVE_COLLECTION}",
                                "platform": "facebook",
                                "content_type": "comment",
                                "dedupe_field": "comment_key",
                                "tags": "group,comment,${GROUP_NAME}",
                                "save_parent_id_var": "_active_comment_parent_hash",
                                "item_level": 1,
                            },
                            {"type": "key", "key": "back"},
                            {"type": "wait", "seconds": 1},
                            {"type": "dismiss_popup", "retries": 1},
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
        "is_builtin": False,
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
            "MAX_COMMENT_SCROLLS": 35,
            "MAX_COMMENTS_PER_POST": 500,
            "MIN_COMMENT_SCAN_PASSES": 4,
            "COMMENT_NO_NEW_THRESHOLD": 3,
            "SCROLL_X_RATIO": 0.18,
            "SAVE_COLLECTION": "fb_profile_posts",
            "EXTRACT_PROFILE": "balanced",
            "FB_POSTS_STRATEGY_VERSION": "fb_posts:v1",
            "FB_COMMENTS_STRATEGY_VERSION": "fb_comments:v1",
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
                                "extract_profile": "${EXTRACT_PROFILE}",
                                "strategy_version": "${FB_POSTS_STRATEGY_VERSION}",
                                "expand_see_more": True,
                                "expand_see_more_max_passes": 2,
                                "expand_see_more_scroll": True,
                                "expand_see_more_scroll_distance": 0.25,
                                "expand_completion_retries": 2,
                                "stop_if_no_new": False,
                                "collection": "${SAVE_COLLECTION}",
                                "platform": "facebook",
                                "content_type": "profile_post",
                                "dedupe_field": "post_key",
                                "tags": "profile,crawl,${PROFILE_SEARCH}",
                            },
                            {
                                "type": "tap_fb_comment_button",
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
                                        "extract_profile": "${EXTRACT_PROFILE}",
                                        "strategy_version": "${FB_COMMENTS_STRATEGY_VERSION}",
                                        "parent_post_id_var": "_fb_comment_parent_pid",
                                        "expand_see_more": True,
                                        "expand_see_more_max_passes": 4,
                                        "expand_see_more_scroll": True,
                                        "expand_see_more_scroll_distance": 0.2,
                                        "max_items": "${MAX_COMMENTS_PER_POST}",
                                        "comment_scroll_passes": "${MAX_COMMENT_SCROLLS}",
                                        "comment_scroll_distance": 0.22,
                                        "comment_scroll_duration_ms": 340,
                                        "comment_scroll_pause_s": 0.3,
                                        "comment_no_growth_break": "${COMMENT_NO_NEW_THRESHOLD}",
                                        "min_comment_scan_passes": "${MIN_COMMENT_SCAN_PASSES}",
                                        "stop_if_no_new": False,
                                        "no_new_threshold": 4,
                                        "collection": "${SAVE_COLLECTION}",
                                        "platform": "facebook",
                                        "content_type": "comment",
                                        "dedupe_field": "comment_key",
                                        "tags": "profile,comment,${PROFILE_SEARCH}",
                                        "save_parent_id_var": "_active_comment_parent_hash",
                                        "item_level": 1,
                                    },
                                    {"type": "key", "key": "back"},
                                    {"type": "wait", "seconds": 1},
                                    {"type": "dismiss_popup", "retries": 1},
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
        "is_builtin": False,
        "category": "facebook",
        "description": (
            "Crawl bài viết + bình luận 1 nhóm Facebook liên tục (mặc định MAX_SCROLLS=540 ≈ 3h). "
            "Chấp nhận bài trùng lặp — DB dedup qua content_hash, loop không dừng sớm. "
            "Navigation: tìm kiếm → tab Nhóm → tap nhóm qua xpath. "
            "Scroll neo trái (SCROLL_X_RATIO=0.18) tránh mở ảnh. "
            "Mỗi bài: extract posts → cuộn nhẹ lộ nút Bình luận → atomic tap + switch filter → extract comments → back.\n"
            "\n"
            "Biến cấu hình:\n"
            "  GROUP_NAME: tên nhóm để tìm kiếm.\n"
            "  GROUP_XPATH: xpath hàng nhóm trong kết quả tìm kiếm.\n"
            "  MAX_SCROLLS: số vòng crawl (mặc định 540 ≈ 3h với ~20s/vòng).\n"
            "  MAX_COMMENT_SCROLLS: số lần cuộn tối đa trong sheet bình luận (mặc định 35).\n"
            "  MAX_COMMENTS_PER_POST: giới hạn số bình luận mỗi bài (mặc định 500).\n"
            "  MIN_COMMENT_SCAN_PASSES: số vòng cuộn tối thiểu dù đã đủ bình luận (mặc định 4).\n"
            "  COMMENT_NO_NEW_THRESHOLD: dừng cuộn bình luận sau N vòng không có thêm (mặc định 3).\n"
            "  SCROLL_X_RATIO: neo ngang khi scroll feed (mặc định 0.18).\n"
            "  SAVE_COLLECTION: collection lưu cả bài và bình luận."
        ),
        "tags": "facebook,group,crawl,feed,post,comment,duplicate-ok",
        "variables": {
            "GROUP_NAME": "openclaw vn",
            "GROUP_XPATH": "//*[@content-desc=\"OpenClaw VN · Truy cập\"]",
            "MAX_SCROLLS": 540,
            "MAX_COMMENT_SCROLLS": 35,
            "MAX_COMMENTS_PER_POST": 500,
            "MIN_COMMENT_SCAN_PASSES": 4,
            "COMMENT_NO_NEW_THRESHOLD": 3,
            "SCROLL_X_RATIO": 0.18,
            "SAVE_COLLECTION": "fb_group_posts",
            "EXTRACT_PROFILE": "balanced",
            "FB_POSTS_STRATEGY_VERSION": "fb_posts:v1",
            "FB_COMMENTS_STRATEGY_VERSION": "fb_comments:v1",
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
                        "extract_profile": "${EXTRACT_PROFILE}",
                        "strategy_version": "${FB_POSTS_STRATEGY_VERSION}",
                        "expand_see_more": True,
                        "expand_see_more_max_passes": 2,
                        "expand_see_more_scroll": True,
                        "expand_see_more_scroll_distance": 0.25,
                        "expand_completion_retries": 2,
                        "stop_if_no_new": False,
                        "collection": "${SAVE_COLLECTION}",
                        "platform": "facebook",
                        "content_type": "group_post",
                        "dedupe_field": "post_key",
                        "tags": "group,crawl,${GROUP_NAME}",
                    },

                    # Atomic tap: resolve → ghi _pid → bấm Bình luận → switch filter
                    # pre_scroll=True: cuộn nhẹ lộ nút (thay scroll_down riêng)
                    {
                        "type": "tap_fb_comment_button",
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
                                "extract_profile": "${EXTRACT_PROFILE}",
                                "strategy_version": "${FB_COMMENTS_STRATEGY_VERSION}",
                                "parent_post_id_var": "_fb_comment_parent_pid",
                                "expand_see_more": True,
                                "expand_see_more_max_passes": 4,
                                "expand_see_more_scroll": True,
                                "expand_see_more_scroll_distance": 0.2,
                                "max_items": "${MAX_COMMENTS_PER_POST}",
                                "comment_scroll_passes": "${MAX_COMMENT_SCROLLS}",
                                "comment_scroll_distance": 0.22,
                                "comment_scroll_duration_ms": 340,
                                "comment_scroll_pause_s": 0.3,
                                "comment_no_growth_break": "${COMMENT_NO_NEW_THRESHOLD}",
                                "min_comment_scan_passes": "${MIN_COMMENT_SCAN_PASSES}",
                                "stop_if_no_new": False,
                                "no_new_threshold": 4,
                                "collection": "${SAVE_COLLECTION}",
                                "platform": "facebook",
                                "content_type": "comment",
                                "dedupe_field": "comment_key",
                                "tags": "group,comment,${GROUP_NAME}",
                                "save_parent_id_var": "_active_comment_parent_hash",
                                "item_level": 1,
                            },
                            {"type": "key", "key": "back"},
                            {"type": "wait", "seconds": 1},
                            {"type": "dismiss_popup", "retries": 1},
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
        "is_builtin": False,
        "category": "facebook",
        "description": (
            "Crawl bài viết + bình luận 1 nhóm Facebook. Mặc định dùng biến global group_name. "
            "Nếu thiết bị có config group_name/search cùng tên thì giá trị thiết bị ghi đè global."
        ),
        "tags": "facebook,group,crawl,feed,post,comment,device-override",
        "variables": {
            "group_name": "openclaw vn",
            "MAX_SCROLLS": 540,
            "MAX_COMMENT_SCROLLS": 35,
            "MAX_COMMENTS_PER_POST": 500,
            "MIN_COMMENT_SCAN_PASSES": 4,
            "COMMENT_NO_NEW_THRESHOLD": 3,
            "SCROLL_X_RATIO": 0.18,
            "SAVE_COLLECTION": "fb_group_posts",
            "EXTRACT_PROFILE": "balanced",
            "FB_POSTS_STRATEGY_VERSION": "fb_posts:v1",
            "FB_COMMENTS_STRATEGY_VERSION": "fb_comments:v1",
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
                        "extract_profile": "${EXTRACT_PROFILE}",
                        "strategy_version": "${FB_POSTS_STRATEGY_VERSION}",
                        "expand_see_more": True,
                        "expand_see_more_max_passes": 2,
                        "expand_see_more_scroll": True,
                        "expand_see_more_scroll_distance": 0.25,
                        "expand_completion_retries": 2,
                        "stop_if_no_new": False,
                        "collection": "${SAVE_COLLECTION}",
                        "platform": "facebook",
                        "content_type": "group_post",
                        "dedupe_field": "post_key",
                        "tags": "group,crawl,${TARGET_GROUP_NAME}",
                    },
                    {
                        "type": "tap_fb_comment_button",
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
                                "extract_profile": "${EXTRACT_PROFILE}",
                                "strategy_version": "${FB_COMMENTS_STRATEGY_VERSION}",
                                "parent_post_id_var": "_fb_comment_parent_pid",
                                "expand_see_more": True,
                                "expand_see_more_max_passes": 4,
                                "expand_see_more_scroll": True,
                                "expand_see_more_scroll_distance": 0.2,
                                "max_items": "${MAX_COMMENTS_PER_POST}",
                                "comment_scroll_passes": "${MAX_COMMENT_SCROLLS}",
                                "comment_scroll_distance": 0.22,
                                "comment_scroll_duration_ms": 340,
                                "comment_scroll_pause_s": 0.3,
                                "comment_no_growth_break": "${COMMENT_NO_NEW_THRESHOLD}",
                                "min_comment_scan_passes": "${MIN_COMMENT_SCAN_PASSES}",
                                "stop_if_no_new": False,
                                "no_new_threshold": 4,
                                "collection": "${SAVE_COLLECTION}",
                                "platform": "facebook",
                                "content_type": "comment",
                                "dedupe_field": "comment_key",
                                "tags": "group,comment,${TARGET_GROUP_NAME}",
                                "save_parent_id_var": "_active_comment_parent_hash",
                                "item_level": 1,
                            },
                            {"type": "key", "key": "back"},
                            {"type": "wait", "seconds": 1},
                            {"type": "dismiss_popup", "retries": 1},
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


async def seed_builtin_templates(db) -> int:
    """
    Upsert BUILTIN_TEMPLATES: insert if not found, update steps/variables/description
    if already exists (so template fixes are applied on every restart).

    Returns the number of templates inserted or updated.
    """
    from db.crud.scenario_template import create_template, get_template_by_name, update_template
    from common.graph_compiler import steps_to_graph

    changed = 0
    for spec in BUILTIN_TEMPLATES:
        spec_is_builtin = spec.get("is_builtin", True)
        raw_steps = spec.get("steps", [])
        nodes, edges = steps_to_graph(raw_steps)
        existing = await get_template_by_name(db, spec["name"])
        if existing is None:
            await create_template(
                db,
                name=spec["name"],
                description=spec.get("description", ""),
                category=spec.get("category", "general"),
                steps=raw_steps,
                variables=spec.get("variables", {}),
                tags=spec.get("tags", ""),
                is_builtin=spec_is_builtin,
                user_id=None,
                nodes=nodes,
                edges=edges,
            )
            changed += 1
        else:
            # Always sync ALL code-managed templates from BUILTIN_TEMPLATES.
            # This includes is_builtin=False templates (like fb_group_1h) so step/variable
            # changes in code are reflected in DB on every restart.
            await update_template(
                db,
                existing.id,
                description=spec.get("description", ""),
                category=spec.get("category", "general"),
                steps=raw_steps,
                variables=spec.get("variables", {}),
                tags=spec.get("tags", ""),
                is_builtin=spec_is_builtin,
                nodes=nodes,
                edges=edges,
            )
            changed += 1

    if changed:
        await db.commit()

    return changed
