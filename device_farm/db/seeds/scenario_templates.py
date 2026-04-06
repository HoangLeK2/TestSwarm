from __future__ import annotations

"""
db/seeds/scenario_templates.py — Builtin scenario template seed data.

Called once on startup (idempotent: skipped if builtins already exist).
Templates use:
  - DF-001 variable interpolation  (${VAR})
  - DF-002 control flow            (repeat, repeat_until, if_element, if_variable, random_pick)
  - DF-006 data extraction         (extract strategy=fb_posts, loop, break_if)

Template step types used:
  launch_app, open_url, wait, wait_stable, wait_element, dismiss_popup, key,
  scroll_down, swipe_ratio, tap_selector, input_selector, input_text,
  set_variable, repeat, repeat_until, if_element, random_pick,
  extract, loop, break_if

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

_GENERIC_TEMPLATES: List[Dict[str, Any]] = [
    {
        "name": "scroll_feed_generic",
        "category": "general",
        "description": "Scroll down N times with randomized delays between scrolls.",
        "tags": "scroll,feed,utility",
        "variables": {"SCROLL_COUNT": 5, "MIN_DELAY": 1, "MAX_DELAY": 3},
        "steps": [
            {
                "type": "repeat",
                "count": "${SCROLL_COUNT}",
                "steps": [
                    {"type": "scroll_down"},
                    {
                        "type": "set_variable",
                        "name": "_DELAY",
                        "from_list": [1, 1.5, 2, 2.5, 3],
                    },
                    {"type": "wait", "seconds": "${_DELAY}"},
                ],
            }
        ],
    },
    {
        "name": "dismiss_all_popups",
        "category": "utility",
        "description": "Dismiss popups 3 times with waits between attempts.",
        "tags": "popup,utility,cleanup",
        "variables": {},
        "steps": [
            {
                "type": "repeat",
                "count": 3,
                "steps": [
                    {"type": "dismiss_popup"},
                    {"type": "wait", "seconds": 1},
                ],
            }
        ],
    },
    {
        "name": "warm_up_device",
        "category": "utility",
        "description": "Open home screen, dismiss popups, then wait for UI to settle.",
        "tags": "warmup,utility,startup",
        "variables": {},
        "steps": [
            {"type": "key", "key": "home"},
            {"type": "wait_stable", "timeout": 3.0, "stable_duration": 0.4},
            {"type": "dismiss_popup", "retries": 2},
        ],
    },
    {
        "name": "scroll_and_like_feed",
        "category": "general",
        "description": "Scroll feed N times, optionally tapping a like button by selector.",
        "tags": "scroll,like,feed,social",
        "variables": {
            "SCROLL_COUNT": 5,
            "LIKE_BTN_TEXT": "Like",
        },
        "steps": [
            {
                "type": "repeat",
                "count": "${SCROLL_COUNT}",
                "steps": [
                    {"type": "scroll_down"},
                    {"type": "wait_stable", "timeout": 2.0, "stable_duration": 0.3},
                    {
                        "type": "if_element",
                        "by": "text",
                        "value": "${LIKE_BTN_TEXT}",
                        "timeout": 1.5,
                        "then": [
                            {"type": "tap_selector", "by": "text", "value": "${LIKE_BTN_TEXT}"},
                        ],
                    },
                ],
            }
        ],
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# DF-006: Facebook Templates
# ─────────────────────────────────────────────────────────────────────────────

_FACEBOOK_TEMPLATES: List[Dict[str, Any]] = [


    # ── fb_group_crawl_engage ──────────────────────────────────────────────
    {
        "name": "fb_group_crawl_engage",
        "category": "facebook",
        "description": (
            "Crawl + tương tác Facebook Group trong một lượt: "
            "cuộn feed, extract bài viết (tác giả, nội dung, lượt thích/bình luận/chia sẻ, "
            "timestamp), đồng thời like (LIKE_WEIGHT%) và share (SHARE_WEIGHT%) ngẫu nhiên. "
            "Selector dựa trên content-desc thực của app (kiểm tra từ UIAutomator XML). "
            "\n"
            "GROUP_NAME: tên group Facebook. "
            "MAX_SCROLLS: số lần scroll tối đa (default 40). "
            "LIKE_WEIGHT: xác suất like mỗi bài (0-100, default 30). "
            "SHARE_WEIGHT: xác suất chia sẻ mỗi bài (0-100, default 0). "
            "SAVE_COLLECTION: collection lưu kết quả."
        ),
        "tags": "facebook,crawl,extract,group,like,share,engage,author,content",
        "variables": {
            "GROUP_NAME": "OpenClaw VN",
            "APP_PACKAGE": "com.facebook.katana",
            "MAX_SCROLLS": 40,
            "LIKE_WEIGHT": 30,
            "SHARE_WEIGHT": 0,
            "SAVE_COLLECTION": "fb_group_posts",
        },
        "steps": [
            # ── Phase 1: Launch & warm-up ────────────────────────────────
            {"type": "launch_app", "package": "${APP_PACKAGE}", "wait_after": 5},
            {"type": "dismiss_popup", "retries": 3},
            {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},

            # ── Phase 2: Navigate to group ───────────────────────────────
            # Tap search button (content-desc xác nhận từ UIAutomator XML thực tế)
            {
                "type": "if_element",
                "by": "content-desc",
                "value": "Tìm kiếm",
                "timeout": 5,
                "then": [
                    {"type": "tap_selector", "by": "content-desc", "value": "Tìm kiếm", "timeout": 4},
                ],
                "else": [
                    # Fallback: vị trí tương đối của nút search trên top bar
                    {"type": "tap_ratio", "x": 0.87, "y": 0.035},
                ],
            },
            {"type": "wait_stable", "timeout": 4, "stable_duration": 0.4},

            # Gõ tên group
            {"type": "input_text", "text": "${GROUP_NAME}", "via": "u2"},
            {"type": "wait", "seconds": 2},

            # Tap gợi ý autocomplete (content-desc hoặc text)
            {
                "type": "if_element",
                "by": "content-desc",
                "value": "${GROUP_NAME}",
                "timeout": 3,
                "then": [
                    {"type": "tap_selector", "by": "content-desc", "value": "${GROUP_NAME}", "timeout": 3},
                ],
                "else": [
                    {
                        "type": "if_element",
                        "by": "text",
                        "value": "${GROUP_NAME}",
                        "timeout": 3,
                        "then": [
                            {"type": "tap_selector", "by": "text", "value": "${GROUP_NAME}", "timeout": 3},
                        ],
                        "else": [
                            # Không có autocomplete → Enter → search results → tab Nhóm
                            {"type": "key", "key": "enter"},
                            {"type": "wait", "seconds": 2},
                            {
                                "type": "if_element",
                                "by": "text", "value": "Nhóm", "timeout": 3,
                                "then": [{"type": "tap_selector", "by": "text", "value": "Nhóm", "timeout": 3}],
                                "else": [
                                    {
                                        "type": "if_element",
                                        "by": "text", "value": "Groups", "timeout": 3,
                                        "then": [{"type": "tap_selector", "by": "text", "value": "Groups", "timeout": 3}],
                                    },
                                ],
                            },
                            {"type": "wait", "seconds": 2},
                            {
                                "type": "if_element",
                                "by": "text", "value": "${GROUP_NAME}", "timeout": 5,
                                "then": [{"type": "tap_selector", "by": "text", "value": "${GROUP_NAME}", "timeout": 4}],
                                "else": [
                                    {
                                        "type": "if_element",
                                        "by": "content-desc", "value": "${GROUP_NAME}", "timeout": 3,
                                        "then": [{"type": "tap_selector", "by": "content-desc", "value": "${GROUP_NAME}", "timeout": 3}],
                                    },
                                ],
                            },
                        ],
                    },
                ],
            },
            {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},
            {"type": "scroll_down", "repeats": 2, "start_y_ratio": 0.65, "end_y_ratio": 0.47},
            {"type": "wait_stable", "timeout": 3, "stable_duration": 0.4},

            # ── Phase 3: Crawl + engage loop ─────────────────────────────
            {
                "type": "repeat",
                "count": "${MAX_SCROLLS}",
                "steps": [
                    # Extract bài viết đang hiển thị (author, text, timestamp,
                    # reactions, comments, shares — xử lý bởi fb_extract.py)
                    {
                        "type": "extract",
                        "strategy": "fb_posts",
                        "expand_see_more": True,
                    },

                    {
                        "type": "random_pick",
                        "branches": [
                            {
                                "weight": "${LIKE_WEIGHT}",
                                "steps": [
                                    {
                                        "type": "if_element",
                                        "by": "descriptionStartsWith",
                                        "value": "Nút Thích.",
                                        "timeout": 2,
                                        "then": [
                                            {
                                                "type": "tap_selector",
                                                "by": "descriptionStartsWith",
                                                "value": "Nút Thích.",
                                                "timeout": 3,
                                            },
                                            {"type": "wait", "seconds": 1},
                                        ],
                                    },
                                ],
                            },
                            {"weight": 100, "steps": []},
                        ],
                    },

                    # Share ngẫu nhiên theo SHARE_WEIGHT%
                    # Selector: content-desc="Nút Chia sẻ. ..." (xác nhận từ XML thực)
                    {
                        "type": "random_pick",
                        "branches": [
                            {
                                "weight": "${SHARE_WEIGHT}",
                                "steps": [
                                    {
                                        "type": "if_element",
                                        "by": "descriptionStartsWith",
                                        "value": "Nút Chia sẻ.",
                                        "timeout": 2,
                                        "then": [
                                            {
                                                "type": "tap_selector",
                                                "by": "descriptionStartsWith",
                                                "value": "Nút Chia sẻ.",
                                                "timeout": 3,
                                            },
                                            {"type": "wait_stable", "timeout": 4, "stable_duration": 0.4},
                                            # Tap "Chia sẻ ngay" / "Share now" trong dialog
                                            {
                                                "type": "if_element",
                                                "by": "text", "value": "Chia sẻ ngay", "timeout": 3,
                                                "then": [
                                                    {"type": "tap_selector", "by": "text", "value": "Chia sẻ ngay", "timeout": 3},
                                                ],
                                                "else": [
                                                    {
                                                        "type": "if_element",
                                                        "by": "text", "value": "Share now", "timeout": 2,
                                                        "then": [
                                                            {"type": "tap_selector", "by": "text", "value": "Share now", "timeout": 2},
                                                        ],
                                                        "else": [
                                                            {"type": "key", "key": "back"},
                                                        ],
                                                    },
                                                ],
                                            },
                                            {"type": "wait", "seconds": 2},
                                        ],
                                    },
                                ],
                            },
                            {"weight": 100, "steps": []},
                        ],
                    },

                    # Scroll + đọc tự nhiên
                    {"type": "set_variable", "name": "_S", "from_list": [1, 1, 2, 2, 3]},
                    {"type": "scroll_down", "repeats": "${_S}", "start_y_ratio": 0.65, "end_y_ratio": 0.47},
                    {"type": "set_variable", "name": "_READ", "from_list": [2, 2.5, 3, 4, 5]},
                    {"type": "wait", "seconds": "${_READ}"},
                    {"type": "dismiss_popup", "retries": 1},

                    # Lưu incremental sau mỗi round
                    {
                        "type": "save_extraction",
                        "data_var": "posts",
                        "collection": "${SAVE_COLLECTION}",
                        "platform": "facebook",
                        "content_type": "group_post",
                        "dedupe_field": "text",
                        "tags": "group,crawl,${GROUP_NAME}",
                    },
                ],
            },

            # ── Phase 4: Final save ──────────────────────────────────────
            {
                "type": "save_extraction",
                "data_var": "posts",
                "collection": "${SAVE_COLLECTION}",
                "platform": "facebook",
                "content_type": "group_post",
                "dedupe_field": "text",
                "tags": "group,crawl,${GROUP_NAME}",
            },
        ],
    },

    # ── fb_single_group ───────────────────────────────────────────────────
    # Kịch bản 1 nhóm: vào 1 nhóm, scroll + like + share + save.
    # is_builtin=False → user có thể update qua API/UI.
    {
        "name": "fb_single_group",
        "is_builtin": False,
        "category": "facebook",
        "description": (
            "Vào 1 nhóm Facebook, cuộn feed, like (LIKE_WEIGHT%) và share (SHARE_WEIGHT%) "
            "ngẫu nhiên, lưu bài viết vào collection. "
            "Navigation 3-tier: autocomplete → text → enter+filter Nhóm/Groups. "
            "\n"
            "GROUP_NAME: tên nhóm cần vào. "
            "SCROLLS: số vòng lặp (default 20 ≈ 15 phút). "
            "LIKE_WEIGHT: xác suất like (0-100). "
            "SHARE_WEIGHT: xác suất share (0-100). "
            "SAVE_COLLECTION: collection lưu data."
        ),
        "tags": "facebook,group,single,crawl,like,share,engage",
        "variables": {
            "GROUP_NAME": "openclaw vn",
            "SCROLLS": 20,
            "LIKE_WEIGHT": 60,
            "SHARE_WEIGHT": 20,
            "SAVE_COLLECTION": "fb_group_posts",
        },
        "steps": [
            {"type": "tap_selector", "by": "text", "value": "Facebook"},
            {"type": "wait_stable", "timeout": 8, "stable_duration": 0.5},
            {"type": "dismiss_popup", "retries": 3},
            {"type": "wait_stable", "timeout": 5, "stable_duration": 0.5},

            # Mở thanh tìm kiếm
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

            # Chuyển sang tab Nhóm / Groups
            {
                "type": "if_element", "by": "text", "value": "Nhóm", "timeout": 5,
                "then": [{"type": "tap_selector", "by": "text", "value": "Nhóm", "timeout": 4}],
                "else": [
                    {
                        "type": "if_element", "by": "text", "value": "Groups", "timeout": 3,
                        "then": [{"type": "tap_selector", "by": "text", "value": "Groups", "timeout": 3}],
                        "else": [],
                    },
                ],
            },
            {"type": "wait", "seconds": 2},

            # Tap vào tên nhóm trong kết quả
            {
                "type": "if_element", "by": "text", "value": "${GROUP_NAME}", "timeout": 5,
                "then": [{"type": "tap_selector", "by": "text", "value": "${GROUP_NAME}", "timeout": 4}],
                "else": [
                    {
                        "type": "if_element", "by": "content-desc", "value": "${GROUP_NAME}", "timeout": 3,
                        "then": [{"type": "tap_selector", "by": "content-desc", "value": "${GROUP_NAME}", "timeout": 3}],
                        "else": [],
                    },
                ],
            },
            {"type": "wait", "seconds": 2},

            # Nhấn Truy cập / Visit để vào nhóm
            {
                "type": "if_element", "by": "text", "value": "Truy cập", "timeout": 4,
                "then": [{"type": "tap_selector", "by": "text", "value": "Truy cập", "timeout": 3}],
                "else": [
                    {
                        "type": "if_element", "by": "text", "value": "Visit", "timeout": 3,
                        "then": [{"type": "tap_selector", "by": "text", "value": "Visit", "timeout": 3}],
                        "else": [],
                    },
                ],
            },
            {"type": "wait", "seconds": 3},
            {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},

            # Cuộn qua phần header nhóm để vào feed bài viết
            {"type": "scroll_down", "repeats": 2, "start_y_ratio": 0.65, "end_y_ratio": 0.47},
            {"type": "wait", "seconds": 3},
            {"type": "wait_stable", "timeout": 4, "stable_duration": 0.5},

            # Vòng lặp chính: scroll chậm, capture đầy đủ
            {
                "type": "repeat", "count": "${SCROLLS}",
                "steps": [
                    # Đợi content render xong trước khi extract
                    {"type": "wait_stable", "timeout": 4, "stable_duration": 0.5},
                    {"type": "extract", "strategy": "fb_posts", "expand_see_more": True},
                    # Đợi sau expand see_more để nội dung đầy đủ được parse
                    {"type": "wait", "seconds": 2},
                    {"type": "extract", "strategy": "fb_posts", "expand_see_more": False},
                    {
                        "type": "random_pick",
                        "branches": [
                            {
                                "weight": "${LIKE_WEIGHT}",
                                "steps": [
                                    {
                                        "type": "if_element", "by": "descriptionStartsWith", "value": "Nút Thích.", "timeout": 2,
                                        "then": [
                                            {"type": "tap_selector", "by": "descriptionStartsWith", "value": "Nút Thích.", "timeout": 3},
                                            {"type": "wait", "seconds": 1},
                                        ],
                                        "else": [],
                                    },
                                ],
                            },
                            {"weight": 100, "steps": []},
                        ],
                    },
                    {
                        "type": "random_pick",
                        "branches": [
                            {
                                "weight": "${SHARE_WEIGHT}",
                                "steps": [
                                    {
                                        "type": "if_element", "by": "descriptionStartsWith", "value": "Nút Chia sẻ.", "timeout": 2,
                                        "then": [
                                            {"type": "tap_selector", "by": "descriptionStartsWith", "value": "Nút Chia sẻ.", "timeout": 3},
                                            {"type": "wait_stable", "timeout": 4, "stable_duration": 0.4},
                                            {
                                                "type": "if_element", "by": "text", "value": "Chia sẻ ngay", "timeout": 3,
                                                "then": [{"type": "tap_selector", "by": "text", "value": "Chia sẻ ngay", "timeout": 3}],
                                                "else": [
                                                    {
                                                        "type": "if_element", "by": "text", "value": "Share now", "timeout": 2,
                                                        "then": [{"type": "tap_selector", "by": "text", "value": "Share now", "timeout": 2}],
                                                        "else": [{"type": "key", "key": "back"}],
                                                    },
                                                ],
                                            },
                                            {"type": "wait", "seconds": 2},
                                        ],
                                        "else": [],
                                    },
                                ],
                            },
                            {"weight": 100, "steps": []},
                        ],
                    },
                    # Scroll chậm: 1-2 lần để không bỏ sót bài
                    {"type": "set_variable", "name": "_S", "from_list": [1, 1, 1, 2, 2]},
                    {"type": "scroll_down", "repeats": "${_S}", "start_y_ratio": 0.65, "end_y_ratio": 0.47},
                    # Đọc lâu hơn để content mới load kịp
                    {"type": "set_variable", "name": "_READ", "from_list": [3, 4, 4, 5, 6]},
                    {"type": "wait", "seconds": "${_READ}"},
                    {"type": "dismiss_popup", "retries": 1},
                    {
                        "type": "save_extraction",
                        "data_var": "posts", "collection": "${SAVE_COLLECTION}",
                        "platform": "facebook", "content_type": "group_post",
                        "dedupe_field": "text", "tags": "group,crawl,${GROUP_NAME}",
                    },
                ],
            },

            # Final save + về home
            {
                "type": "save_extraction",
                "data_var": "posts", "collection": "${SAVE_COLLECTION}",
                "platform": "facebook", "content_type": "group_post",
                "dedupe_field": "text", "tags": "group,crawl,${GROUP_NAME}",
            },
            {"type": "key", "key": "home"},
        ],
    },

    # ── fb_group_deep_1k ──────────────────────────────────────────────────
    # Deep crawl 1 nhóm - expand 'Xem thêm' tại feed, không vào detail.
    # Target: 1000 bài. is_builtin=False → user có thể update.
    {
        "name": "fb_group_deep_1k",
        "is_builtin": False,
        "category": "facebook",
        "description": (
            "Deep crawl 1 nhóm Facebook: expand 'Xem thêm' trực tiếp tại feed "
            "(không vào detail), extract author + full text + reactions. "
            "Scroll neo trái (SCROLL_X_RATIO) để giảm mở nhầm viewer ảnh do vuốt xuyên giữa màn hình; "
            "mỗi vòng gọi dismiss_popup sau scroll (đóng dialog/overlay có nút Close/OK…). "
            "Loop tự dừng theo stop_if_no_new (no_new_threshold). "
            "\n"
            "GROUP_NAME: tên nhóm cần tìm kiếm. "
            "GROUP_XPATH: xpath chính xác vào nhóm (đổi theo nhóm thực tế). "
            "MAX_SCROLLS: số vòng lặp tối đa (default 1000). "
            "SCROLL_X_RATIO: neo ngang khi scroll (0.12–0.28 khuyến nghị; mặc định 0.18). "
            "SAVE_COLLECTION: collection lưu data."
        ),
        "tags": "facebook,group,deep,crawl,1000,full-content,author,single,feed",
        "variables": {
            "GROUP_NAME": "openclaw vn",
            "GROUP_XPATH": "//*[@content-desc=\"OpenClaw VN,Công khai · 123K thành viên\"]",
            "MAX_SCROLLS": 3600,
            "SCROLL_X_RATIO": 0.18,
            "SAVE_COLLECTION": "fb_group_posts",
        },
        "steps": [
            {"type": "tap_selector", "by": "text", "value": "Facebook"},
            {"type": "wait_stable", "timeout": 8, "stable_duration": 0.5},
            {"type": "dismiss_popup", "retries": 3},
            {"type": "wait_stable", "timeout": 5, "stable_duration": 0.5},

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

            {"type": "tap_selector", "by": "xpath", "value": "${GROUP_XPATH}", "timeout": 6},
            {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},

            {
                "type": "scroll_down",
                "repeats": 2,
                "start_x_ratio": "${SCROLL_X_RATIO}",
                "start_y_ratio": 0.65,
                "end_y_ratio": 0.47,
            },
            {"type": "wait", "seconds": 3},
            {"type": "wait_stable", "timeout": 4, "stable_duration": 0.5},

            {
                "type": "loop",
                "count": "${MAX_SCROLLS}",
                "steps": [
                    {
                        "type": "extract",
                        "strategy": "fb_posts",
                        "expand_see_more": True,
                        "stop_if_no_new": True,
                        "no_new_threshold": 100,
                    },
                    {
                        "type": "save_extraction",
                        "data_var": "posts", "collection": "${SAVE_COLLECTION}",
                        "platform": "facebook", "content_type": "group_post",
                        "dedupe_field": "text", "tags": "group,crawl,${GROUP_NAME}",
                    },
                    {
                        "type": "scroll_down",
                        "repeats": 1,
                        "start_x_ratio": "${SCROLL_X_RATIO}",
                        "start_y_ratio": 0.65,
                        "end_y_ratio": 0.47,
                    },
                    {"type": "wait", "seconds": 1},
                    {"type": "dismiss_popup", "retries": 2},
                ],
            },
            {"type": "key", "key": "home"},
        ],
    },

    # ── fb_multi_group_1h ─────────────────────────────────────────────────
    # Kịch bản 1 tiếng: vào 4 nhóm liên tiếp, mỗi nhóm ~15 phút.
    # is_builtin=False → user có thể update qua API/UI, seed sẽ không overwrite.
    {
        "name": "fb_multi_group_1h",
        "is_builtin": False,
        "category": "facebook",
        "description": (
            "Kịch bản 1 tiếng: vào 4 nhóm Facebook liên tiếp, mỗi nhóm ~15 phút. "
            "Mỗi vòng trong nhóm: extract bài viết, like ngẫu nhiên (LIKE_WEIGHT%), "
            "share ngẫu nhiên (SHARE_WEIGHT%), scroll + đọc tự nhiên, lưu data. "
            "Sau khi hết lượt mỗi nhóm, tự động chuyển sang nhóm tiếp theo. "
            "\n"
            "GROUP_1..GROUP_4: tên 4 nhóm cần vào. "
            "SCROLLS_PER_GROUP: số vòng lặp mỗi nhóm (default 20 ≈ 15 phút). "
            "LIKE_WEIGHT: xác suất like (0-100, default 60). "
            "SHARE_WEIGHT: xác suất share (0-100, default 20). "
            "SAVE_COLLECTION: collection lưu data (default fb_group_posts)."
        ),
        "tags": "facebook,group,multi,1h,crawl,like,share,engage,60min,schedule",
        "variables": {
            "GROUP_1": "openclaw vn",
            "GROUP_2": "Tìm kiếm việc làm",
            "GROUP_3": "công nghệ thông tin",
            "GROUP_4": "lập trình viên",
            "SCROLLS_PER_GROUP": 20,
            "LIKE_WEIGHT": 60,
            "SHARE_WEIGHT": 20,
            "SAVE_COLLECTION": "fb_group_posts",
        },
        "steps": [
            # ── Khởi động Facebook ───────────────────────────────────────
            {"type": "tap_selector", "by": "text", "value": "Facebook"},
            {"type": "dismiss_popup", "retries": 3},
            {"type": "wait_stable", "timeout": 8, "stable_duration": 0.5},

            # ── NHÓM 1 (~15 phút) ────────────────────────────────────────
            {
                "type": "if_element", "by": "content-desc", "value": "Tìm kiếm", "timeout": 5,
                "then": [{"type": "tap_selector", "by": "content-desc", "value": "Tìm kiếm", "timeout": 4}],
                "else": [{"type": "tap_ratio", "x": 0.87, "y": 0.035}],
            },
            {"type": "wait_stable", "timeout": 4, "stable_duration": 0.4},
            {"type": "input_text", "text": "${GROUP_1}", "via": "u2"},
            {"type": "wait", "seconds": 2},
            {
                "type": "if_element", "by": "content-desc", "value": "${GROUP_1}", "timeout": 3,
                "then": [{"type": "tap_selector", "by": "content-desc", "value": "${GROUP_1}", "timeout": 3}],
                "else": [
                    {
                        "type": "if_element", "by": "text", "value": "${GROUP_1}", "timeout": 3,
                        "then": [{"type": "tap_selector", "by": "text", "value": "${GROUP_1}", "timeout": 3}],
                        "else": [
                            {"type": "key", "key": "enter"},
                            {"type": "wait", "seconds": 2},
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
                            {"type": "wait", "seconds": 2},
                            {
                                "type": "if_element", "by": "text", "value": "${GROUP_1}", "timeout": 5,
                                "then": [{"type": "tap_selector", "by": "text", "value": "${GROUP_1}", "timeout": 4}],
                                "else": [
                                    {
                                        "type": "if_element", "by": "content-desc", "value": "${GROUP_1}", "timeout": 3,
                                        "then": [{"type": "tap_selector", "by": "content-desc", "value": "${GROUP_1}", "timeout": 3}],
                                        "else": [],
                                    },
                                ],
                            },
                        ],
                    },
                ],
            },
            {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},
            {"type": "scroll_down", "repeats": 2, "start_y_ratio": 0.65, "end_y_ratio": 0.47},
            {"type": "wait_stable", "timeout": 3, "stable_duration": 0.4},
            {
                "type": "repeat", "count": "${SCROLLS_PER_GROUP}",
                "steps": [
                    {"type": "extract", "strategy": "fb_posts", "expand_see_more": True},
                    {
                        "type": "random_pick",
                        "branches": [
                            {
                                "weight": "${LIKE_WEIGHT}",
                                "steps": [
                                    {
                                        "type": "if_element", "by": "descriptionStartsWith", "value": "Nút Thích.", "timeout": 2,
                                        "then": [
                                            {"type": "tap_selector", "by": "descriptionStartsWith", "value": "Nút Thích.", "timeout": 3},
                                            {"type": "wait", "seconds": 1},
                                        ],
                                        "else": [],
                                    },
                                ],
                            },
                            {"weight": 100, "steps": []},
                        ],
                    },
                    {
                        "type": "random_pick",
                        "branches": [
                            {
                                "weight": "${SHARE_WEIGHT}",
                                "steps": [
                                    {
                                        "type": "if_element", "by": "descriptionStartsWith", "value": "Nút Chia sẻ.", "timeout": 2,
                                        "then": [
                                            {"type": "tap_selector", "by": "descriptionStartsWith", "value": "Nút Chia sẻ.", "timeout": 3},
                                            {"type": "wait_stable", "timeout": 4, "stable_duration": 0.4},
                                            {
                                                "type": "if_element", "by": "text", "value": "Chia sẻ ngay", "timeout": 3,
                                                "then": [{"type": "tap_selector", "by": "text", "value": "Chia sẻ ngay", "timeout": 3}],
                                                "else": [
                                                    {
                                                        "type": "if_element", "by": "text", "value": "Share now", "timeout": 2,
                                                        "then": [{"type": "tap_selector", "by": "text", "value": "Share now", "timeout": 2}],
                                                        "else": [{"type": "key", "key": "back"}],
                                                    },
                                                ],
                                            },
                                            {"type": "wait", "seconds": 2},
                                        ],
                                        "else": [],
                                    },
                                ],
                            },
                            {"weight": 100, "steps": []},
                        ],
                    },
                    {"type": "set_variable", "name": "_S", "from_list": [1, 1, 2, 2, 3]},
                    {"type": "scroll_down", "repeats": "${_S}", "start_y_ratio": 0.65, "end_y_ratio": 0.47},
                    {"type": "set_variable", "name": "_READ", "from_list": [2, 2.5, 3, 4, 5]},
                    {"type": "wait", "seconds": "${_READ}"},
                    {"type": "dismiss_popup", "retries": 1},
                    {
                        "type": "save_extraction",
                        "data_var": "posts", "collection": "${SAVE_COLLECTION}",
                        "platform": "facebook", "content_type": "group_post",
                        "dedupe_field": "text", "tags": "group,crawl,${GROUP_1}",
                    },
                ],
            },
            {
                "type": "save_extraction",
                "data_var": "posts", "collection": "${SAVE_COLLECTION}",
                "platform": "facebook", "content_type": "group_post",
                "dedupe_field": "text", "tags": "group,crawl,${GROUP_1}",
            },
            {"type": "key", "key": "back"},
            {"type": "key", "key": "back"},
            {"type": "wait", "seconds": 2},
            {"type": "wait_stable", "timeout": 5, "stable_duration": 0.5},

            # ── NHÓM 2 (~15 phút) ────────────────────────────────────────
            {
                "type": "if_element", "by": "content-desc", "value": "Tìm kiếm", "timeout": 5,
                "then": [{"type": "tap_selector", "by": "content-desc", "value": "Tìm kiếm", "timeout": 4}],
                "else": [{"type": "tap_ratio", "x": 0.87, "y": 0.035}],
            },
            {"type": "wait_stable", "timeout": 4, "stable_duration": 0.4},
            {"type": "input_text", "text": "${GROUP_2}", "via": "u2"},
            {"type": "wait", "seconds": 2},
            {
                "type": "if_element", "by": "content-desc", "value": "${GROUP_2}", "timeout": 3,
                "then": [{"type": "tap_selector", "by": "content-desc", "value": "${GROUP_2}", "timeout": 3}],
                "else": [
                    {
                        "type": "if_element", "by": "text", "value": "${GROUP_2}", "timeout": 3,
                        "then": [{"type": "tap_selector", "by": "text", "value": "${GROUP_2}", "timeout": 3}],
                        "else": [
                            {"type": "key", "key": "enter"},
                            {"type": "wait", "seconds": 2},
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
                            {"type": "wait", "seconds": 2},
                            {
                                "type": "if_element", "by": "text", "value": "${GROUP_2}", "timeout": 5,
                                "then": [{"type": "tap_selector", "by": "text", "value": "${GROUP_2}", "timeout": 4}],
                                "else": [
                                    {
                                        "type": "if_element", "by": "content-desc", "value": "${GROUP_2}", "timeout": 3,
                                        "then": [{"type": "tap_selector", "by": "content-desc", "value": "${GROUP_2}", "timeout": 3}],
                                        "else": [],
                                    },
                                ],
                            },
                        ],
                    },
                ],
            },
            {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},
            {"type": "scroll_down", "repeats": 2, "start_y_ratio": 0.65, "end_y_ratio": 0.47},
            {"type": "wait_stable", "timeout": 3, "stable_duration": 0.4},
            {
                "type": "repeat", "count": "${SCROLLS_PER_GROUP}",
                "steps": [
                    {"type": "extract", "strategy": "fb_posts", "expand_see_more": True},
                    {
                        "type": "random_pick",
                        "branches": [
                            {
                                "weight": "${LIKE_WEIGHT}",
                                "steps": [
                                    {
                                        "type": "if_element", "by": "descriptionStartsWith", "value": "Nút Thích.", "timeout": 2,
                                        "then": [
                                            {"type": "tap_selector", "by": "descriptionStartsWith", "value": "Nút Thích.", "timeout": 3},
                                            {"type": "wait", "seconds": 1},
                                        ],
                                        "else": [],
                                    },
                                ],
                            },
                            {"weight": 100, "steps": []},
                        ],
                    },
                    {
                        "type": "random_pick",
                        "branches": [
                            {
                                "weight": "${SHARE_WEIGHT}",
                                "steps": [
                                    {
                                        "type": "if_element", "by": "descriptionStartsWith", "value": "Nút Chia sẻ.", "timeout": 2,
                                        "then": [
                                            {"type": "tap_selector", "by": "descriptionStartsWith", "value": "Nút Chia sẻ.", "timeout": 3},
                                            {"type": "wait_stable", "timeout": 4, "stable_duration": 0.4},
                                            {
                                                "type": "if_element", "by": "text", "value": "Chia sẻ ngay", "timeout": 3,
                                                "then": [{"type": "tap_selector", "by": "text", "value": "Chia sẻ ngay", "timeout": 3}],
                                                "else": [
                                                    {
                                                        "type": "if_element", "by": "text", "value": "Share now", "timeout": 2,
                                                        "then": [{"type": "tap_selector", "by": "text", "value": "Share now", "timeout": 2}],
                                                        "else": [{"type": "key", "key": "back"}],
                                                    },
                                                ],
                                            },
                                            {"type": "wait", "seconds": 2},
                                        ],
                                        "else": [],
                                    },
                                ],
                            },
                            {"weight": 100, "steps": []},
                        ],
                    },
                    {"type": "set_variable", "name": "_S", "from_list": [1, 1, 2, 2, 3]},
                    {"type": "scroll_down", "repeats": "${_S}", "start_y_ratio": 0.65, "end_y_ratio": 0.47},
                    {"type": "set_variable", "name": "_READ", "from_list": [2, 2.5, 3, 4, 5]},
                    {"type": "wait", "seconds": "${_READ}"},
                    {"type": "dismiss_popup", "retries": 1},
                    {
                        "type": "save_extraction",
                        "data_var": "posts", "collection": "${SAVE_COLLECTION}",
                        "platform": "facebook", "content_type": "group_post",
                        "dedupe_field": "text", "tags": "group,crawl,${GROUP_2}",
                    },
                ],
            },
            {
                "type": "save_extraction",
                "data_var": "posts", "collection": "${SAVE_COLLECTION}",
                "platform": "facebook", "content_type": "group_post",
                "dedupe_field": "text", "tags": "group,crawl,${GROUP_2}",
            },
            {"type": "key", "key": "back"},
            {"type": "key", "key": "back"},
            {"type": "wait", "seconds": 2},
            {"type": "wait_stable", "timeout": 5, "stable_duration": 0.5},

            # ── NHÓM 3 (~15 phút) ────────────────────────────────────────
            {
                "type": "if_element", "by": "content-desc", "value": "Tìm kiếm", "timeout": 5,
                "then": [{"type": "tap_selector", "by": "content-desc", "value": "Tìm kiếm", "timeout": 4}],
                "else": [{"type": "tap_ratio", "x": 0.87, "y": 0.035}],
            },
            {"type": "wait_stable", "timeout": 4, "stable_duration": 0.4},
            {"type": "input_text", "text": "${GROUP_3}", "via": "u2"},
            {"type": "wait", "seconds": 2},
            {
                "type": "if_element", "by": "content-desc", "value": "${GROUP_3}", "timeout": 3,
                "then": [{"type": "tap_selector", "by": "content-desc", "value": "${GROUP_3}", "timeout": 3}],
                "else": [
                    {
                        "type": "if_element", "by": "text", "value": "${GROUP_3}", "timeout": 3,
                        "then": [{"type": "tap_selector", "by": "text", "value": "${GROUP_3}", "timeout": 3}],
                        "else": [
                            {"type": "key", "key": "enter"},
                            {"type": "wait", "seconds": 2},
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
                            {"type": "wait", "seconds": 2},
                            {
                                "type": "if_element", "by": "text", "value": "${GROUP_3}", "timeout": 5,
                                "then": [{"type": "tap_selector", "by": "text", "value": "${GROUP_3}", "timeout": 4}],
                                "else": [
                                    {
                                        "type": "if_element", "by": "content-desc", "value": "${GROUP_3}", "timeout": 3,
                                        "then": [{"type": "tap_selector", "by": "content-desc", "value": "${GROUP_3}", "timeout": 3}],
                                        "else": [],
                                    },
                                ],
                            },
                        ],
                    },
                ],
            },
            {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},
            {"type": "scroll_down", "repeats": 2, "start_y_ratio": 0.65, "end_y_ratio": 0.47},
            {"type": "wait_stable", "timeout": 3, "stable_duration": 0.4},
            {
                "type": "repeat", "count": "${SCROLLS_PER_GROUP}",
                "steps": [
                    {"type": "extract", "strategy": "fb_posts", "expand_see_more": True},
                    {
                        "type": "random_pick",
                        "branches": [
                            {
                                "weight": "${LIKE_WEIGHT}",
                                "steps": [
                                    {
                                        "type": "if_element", "by": "descriptionStartsWith", "value": "Nút Thích.", "timeout": 2,
                                        "then": [
                                            {"type": "tap_selector", "by": "descriptionStartsWith", "value": "Nút Thích.", "timeout": 3},
                                            {"type": "wait", "seconds": 1},
                                        ],
                                        "else": [],
                                    },
                                ],
                            },
                            {"weight": 100, "steps": []},
                        ],
                    },
                    {
                        "type": "random_pick",
                        "branches": [
                            {
                                "weight": "${SHARE_WEIGHT}",
                                "steps": [
                                    {
                                        "type": "if_element", "by": "descriptionStartsWith", "value": "Nút Chia sẻ.", "timeout": 2,
                                        "then": [
                                            {"type": "tap_selector", "by": "descriptionStartsWith", "value": "Nút Chia sẻ.", "timeout": 3},
                                            {"type": "wait_stable", "timeout": 4, "stable_duration": 0.4},
                                            {
                                                "type": "if_element", "by": "text", "value": "Chia sẻ ngay", "timeout": 3,
                                                "then": [{"type": "tap_selector", "by": "text", "value": "Chia sẻ ngay", "timeout": 3}],
                                                "else": [
                                                    {
                                                        "type": "if_element", "by": "text", "value": "Share now", "timeout": 2,
                                                        "then": [{"type": "tap_selector", "by": "text", "value": "Share now", "timeout": 2}],
                                                        "else": [{"type": "key", "key": "back"}],
                                                    },
                                                ],
                                            },
                                            {"type": "wait", "seconds": 2},
                                        ],
                                        "else": [],
                                    },
                                ],
                            },
                            {"weight": 100, "steps": []},
                        ],
                    },
                    {"type": "set_variable", "name": "_S", "from_list": [1, 1, 2, 2, 3]},
                    {"type": "scroll_down", "repeats": "${_S}", "start_y_ratio": 0.65, "end_y_ratio": 0.47},
                    {"type": "set_variable", "name": "_READ", "from_list": [2, 2.5, 3, 4, 5]},
                    {"type": "wait", "seconds": "${_READ}"},
                    {"type": "dismiss_popup", "retries": 1},
                    {
                        "type": "save_extraction",
                        "data_var": "posts", "collection": "${SAVE_COLLECTION}",
                        "platform": "facebook", "content_type": "group_post",
                        "dedupe_field": "text", "tags": "group,crawl,${GROUP_3}",
                    },
                ],
            },
            {
                "type": "save_extraction",
                "data_var": "posts", "collection": "${SAVE_COLLECTION}",
                "platform": "facebook", "content_type": "group_post",
                "dedupe_field": "text", "tags": "group,crawl,${GROUP_3}",
            },
            {"type": "key", "key": "back"},
            {"type": "key", "key": "back"},
            {"type": "wait", "seconds": 2},
            {"type": "wait_stable", "timeout": 5, "stable_duration": 0.5},

            # ── NHÓM 4 (~15 phút) ────────────────────────────────────────
            {
                "type": "if_element", "by": "content-desc", "value": "Tìm kiếm", "timeout": 5,
                "then": [{"type": "tap_selector", "by": "content-desc", "value": "Tìm kiếm", "timeout": 4}],
                "else": [{"type": "tap_ratio", "x": 0.87, "y": 0.035}],
            },
            {"type": "wait_stable", "timeout": 4, "stable_duration": 0.4},
            {"type": "input_text", "text": "${GROUP_4}", "via": "u2"},
            {"type": "wait", "seconds": 2},
            {
                "type": "if_element", "by": "content-desc", "value": "${GROUP_4}", "timeout": 3,
                "then": [{"type": "tap_selector", "by": "content-desc", "value": "${GROUP_4}", "timeout": 3}],
                "else": [
                    {
                        "type": "if_element", "by": "text", "value": "${GROUP_4}", "timeout": 3,
                        "then": [{"type": "tap_selector", "by": "text", "value": "${GROUP_4}", "timeout": 3}],
                        "else": [
                            {"type": "key", "key": "enter"},
                            {"type": "wait", "seconds": 2},
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
                            {"type": "wait", "seconds": 2},
                            {
                                "type": "if_element", "by": "text", "value": "${GROUP_4}", "timeout": 5,
                                "then": [{"type": "tap_selector", "by": "text", "value": "${GROUP_4}", "timeout": 4}],
                                "else": [
                                    {
                                        "type": "if_element", "by": "content-desc", "value": "${GROUP_4}", "timeout": 3,
                                        "then": [{"type": "tap_selector", "by": "content-desc", "value": "${GROUP_4}", "timeout": 3}],
                                        "else": [],
                                    },
                                ],
                            },
                        ],
                    },
                ],
            },
            {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},
            {"type": "scroll_down", "repeats": 2, "start_y_ratio": 0.65, "end_y_ratio": 0.47},
            {"type": "wait_stable", "timeout": 3, "stable_duration": 0.4},
            {
                "type": "repeat", "count": "${SCROLLS_PER_GROUP}",
                "steps": [
                    {"type": "extract", "strategy": "fb_posts", "expand_see_more": True},
                    {
                        "type": "random_pick",
                        "branches": [
                            {
                                "weight": "${LIKE_WEIGHT}",
                                "steps": [
                                    {
                                        "type": "if_element", "by": "descriptionStartsWith", "value": "Nút Thích.", "timeout": 2,
                                        "then": [
                                            {"type": "tap_selector", "by": "descriptionStartsWith", "value": "Nút Thích.", "timeout": 3},
                                            {"type": "wait", "seconds": 1},
                                        ],
                                        "else": [],
                                    },
                                ],
                            },
                            {"weight": 100, "steps": []},
                        ],
                    },
                    {
                        "type": "random_pick",
                        "branches": [
                            {
                                "weight": "${SHARE_WEIGHT}",
                                "steps": [
                                    {
                                        "type": "if_element", "by": "descriptionStartsWith", "value": "Nút Chia sẻ.", "timeout": 2,
                                        "then": [
                                            {"type": "tap_selector", "by": "descriptionStartsWith", "value": "Nút Chia sẻ.", "timeout": 3},
                                            {"type": "wait_stable", "timeout": 4, "stable_duration": 0.4},
                                            {
                                                "type": "if_element", "by": "text", "value": "Chia sẻ ngay", "timeout": 3,
                                                "then": [{"type": "tap_selector", "by": "text", "value": "Chia sẻ ngay", "timeout": 3}],
                                                "else": [
                                                    {
                                                        "type": "if_element", "by": "text", "value": "Share now", "timeout": 2,
                                                        "then": [{"type": "tap_selector", "by": "text", "value": "Share now", "timeout": 2}],
                                                        "else": [{"type": "key", "key": "back"}],
                                                    },
                                                ],
                                            },
                                            {"type": "wait", "seconds": 2},
                                        ],
                                        "else": [],
                                    },
                                ],
                            },
                            {"weight": 100, "steps": []},
                        ],
                    },
                    {"type": "set_variable", "name": "_S", "from_list": [1, 1, 2, 2, 3]},
                    {"type": "scroll_down", "repeats": "${_S}", "start_y_ratio": 0.65, "end_y_ratio": 0.47},
                    {"type": "set_variable", "name": "_READ", "from_list": [2, 2.5, 3, 4, 5]},
                    {"type": "wait", "seconds": "${_READ}"},
                    {"type": "dismiss_popup", "retries": 1},
                    {
                        "type": "save_extraction",
                        "data_var": "posts", "collection": "${SAVE_COLLECTION}",
                        "platform": "facebook", "content_type": "group_post",
                        "dedupe_field": "text", "tags": "group,crawl,${GROUP_4}",
                    },
                ],
            },
            {
                "type": "save_extraction",
                "data_var": "posts", "collection": "${SAVE_COLLECTION}",
                "platform": "facebook", "content_type": "group_post",
                "dedupe_field": "text", "tags": "group,crawl,${GROUP_4}",
            },
            {"type": "key", "key": "home"},
        ],
    },



    # ── fb_scan_posts_1h ──────────────────────────────────────────────────────
    # Quét bài viết Facebook 1 nhóm trong ~1 tiếng, lưu kết quả vào collection.
    # Dừng sớm khi feed hết bài mới (stop_if_no_new). Không crawl comment.
    # Phù hợp để khởi động, thống kê bài đăng hoặc warm-up thiết bị.
    {
        "name": "fb_scan_posts_1h",
        "is_builtin": True,
        "category": "facebook",
        "description": (
            "Quét bài viết trong 1 nhóm Facebook trong ~1 tiếng (MAX_SCROLLS=180, ~20s/vòng). "
            "Tự dừng khi feed hết bài mới liên tiếp (no_new_threshold=5). "
            "Lưu toàn bộ bài viết (author, text, reactions, comments_count, shares) vào SAVE_COLLECTION. "
            "Không crawl comment — chỉ thu thập bài viết để thống kê nhanh. "
            "Sau khi chạy xong, xem kết quả tại tab Dữ liệu → lọc theo Campaign ID.\n"
            "GROUP_NAME: tên nhóm để tìm kiếm. "
            "GROUP_XPATH: xpath chính xác của nhóm trong kết quả tìm kiếm. "
            "MAX_SCROLLS: số vòng lặp tối đa (default 180 ≈ 1 tiếng). "
            "SCROLL_X_RATIO: neo ngang khi scroll (default 0.18, tránh tap vào ảnh). "
            "SAVE_COLLECTION: tên collection lưu kết quả (default fb_posts_1h)."
        ),
        "tags": "facebook,group,post,scan,1h,crawl,feed,statistics",
        "variables": {
            "GROUP_NAME": "openclaw vn",
            "GROUP_XPATH": "//*[@content-desc=\"OpenClaw VN,Công khai · 123K thành viên\"]",
            "MAX_SCROLLS": 180,
            "SCROLL_X_RATIO": 0.18,
            "SAVE_COLLECTION": "fb_posts_1h",
        },
        "steps": [
            # ── Phase 1: Khởi động Facebook ──────────────────────────────────
            {"type": "tap_selector", "by": "text", "value": "Facebook"},
            {"type": "wait_stable", "timeout": 8, "stable_duration": 0.5},
            {"type": "dismiss_popup", "retries": 3},
            {"type": "wait_stable", "timeout": 5, "stable_duration": 0.5},

            # ── Phase 2: Tìm và vào nhóm ─────────────────────────────────────
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

            {"type": "tap_selector", "by": "xpath", "value": "${GROUP_XPATH}", "timeout": 6},
            {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},

            # Scroll qua header nhóm để vào feed bài viết
            {"type": "scroll_down", "repeats": 2, "start_x_ratio": "${SCROLL_X_RATIO}", "start_y_ratio": 0.65, "end_y_ratio": 0.47},
            {"type": "wait", "seconds": 3},
            {"type": "wait_stable", "timeout": 4, "stable_duration": 0.5},

            # ── Phase 3: Loop chính — quét feed ──────────────────────────────
            {
                "type": "loop",
                "count": "${MAX_SCROLLS}",
                "steps": [
                    # Bước 1: Extract bài viết
                    {
                        "type": "extract",
                        "strategy": "fb_posts",
                        "expand_see_more": True,
                        "stop_if_no_new": True,
                        "no_new_threshold": 5,
                    },

                    # Bước 2: Lưu kết quả (dedup theo nội dung text)
                    {
                        "type": "save_extraction",
                        "data_var": "posts",
                        "collection": "${SAVE_COLLECTION}",
                        "platform": "facebook",
                        "content_type": "group_post",
                        "dedupe_field": "text",
                        "tags": "group,scan,${GROUP_NAME}",
                    },

                    # Bước 3: Scroll xuống bài tiếp theo
                    {
                        "type": "scroll_down",
                        "repeats": 1,
                        "start_x_ratio": "${SCROLL_X_RATIO}",
                        "start_y_ratio": 0.65,
                        "end_y_ratio": 0.47,
                    },
                    {"type": "wait", "seconds": 2},

                    {"type": "dismiss_popup", "retries": 1},
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
            "Crawl bài viết 1 nhóm Facebook trong ~1 tiếng (MAX_SCROLLS=180, ~20s/vòng). "
            "Chấp nhận bài trùng lặp — không dừng sớm khi feed lặp lại. "
            "Navigation 3 bước: tìm kiếm → tab Nhóm (descriptionContains) → tap nhóm qua xpath. "
            "Scroll neo trái (SCROLL_X_RATIO=0.18) tránh mở ảnh. "
            "Lưu toàn bộ vào SAVE_COLLECTION.\n"
            "GROUP_NAME: tên nhóm để tìm kiếm. "
            "GROUP_XPATH: xpath chính xác của nhóm trong kết quả. "
            "MAX_SCROLLS: số vòng lặp (default 180 ≈ 1 tiếng). "
            "SCROLL_X_RATIO: neo ngang (default 0.18). "
            "SAVE_COLLECTION: collection lưu kết quả."
        ),
        "tags": "facebook,group,1h,crawl,feed,post,duplicate-ok",
        "variables": {
            "GROUP_NAME": "openclaw vn",
            "GROUP_XPATH": "//*[@content-desc=\"OpenClaw VN · Truy cập\"]",
            "MAX_SCROLLS": 9000,
            "MAX_COMMENT_SCROLLS": 20,
            "SCROLL_X_RATIO": 0.18,
            "SAVE_COLLECTION": "fb_group_posts",
        },
        "steps": [
            # ── Phase 1: Khởi động ────────────────────────────────────────────
            {"type": "tap_selector", "by": "text", "value": "Facebook"},

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

            # ── Phase 3: Chọn tab Nhóm trong kết quả tìm kiếm ───────────────
            # Dùng descriptionContains "tab Nhóm" (chuẩn nhất từ UIAutomator XML).
            # Fallback lần lượt: text "Nhóm" → text "Groups".
            {
                "type": "if_element", "by": "descriptionContains", "value": "tab Nhóm", "timeout": 5,
                "then": [{"type": "tap_selector", "by": "descriptionContains", "value": "tab Nhóm", "timeout": 4}],
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

            # ── Phase 4: Tap vào nhóm theo xpath ────────────────────────────
            {"type": "tap_selector", "by": "xpath", "value": "${GROUP_XPATH}", "timeout": 6},
            {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},

            {"type": "scroll_down", "repeats": 2, "start_x_ratio": "${SCROLL_X_RATIO}", "start_y_ratio": 0.65, "end_y_ratio": 0.47},
            {"type": "wait", "seconds": 3},
            {"type": "wait_stable", "timeout": 4, "stable_duration": 0.5},

            # ── Phase 5: Loop crawl ~1 tiếng ────────────────────────────────
            # stop_if_no_new=False (mặc định) → chạy đủ MAX_SCROLLS, không dừng sớm.
            # Chấp nhận bài trùng: DB dedup qua content_hash nhưng loop không break.
            # ~20s/vòng × 180 vòng ≈ 60 phút.
            {
                "type": "loop",
                "count": "${MAX_SCROLLS}",
                "steps": [
                    # Chờ nội dung load xong (đặc biệt quan trọng cho bài viết dài)
                    {"type": "wait", "seconds": 1},

                    # Extract bài viết đang hiển thị, expand "Xem thêm" 2 lần để lấy full text
                    {
                        "type": "extract",
                        "strategy": "fb_posts",
                        "expand_see_more": True,
                        "stop_if_no_new": False,
                    },
                    # Lưu ngay — DB tự dedup qua content_hash, không cần lo trùng
                    {
                        "type": "save_extraction",
                        "data_var": "posts",
                        "collection": "${SAVE_COLLECTION}",
                        "platform": "facebook",
                        "content_type": "group_post",
                        "dedupe_field": "text",
                        "tags": "group,crawl,${GROUP_NAME}",
                    },

                    # Vào comment bài viết đầu tiên → extract comment + cập nhật like count
                    {
                        "type": "if_element", "by": "text", "value": "Bình luận", "timeout": 1,
                        "ignore_error": True,
                        "then": [
                            {"type": "tap_selector", "by": "text", "value": "Bình luận", "timeout": 1},
                            {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},

                            # Loop cuộn hết comment — thoát sớm khi không còn comment mới (no_new_threshold=2)
                            {
                                "type": "loop",
                                "count": "${MAX_COMMENT_SCROLLS}",
                                "steps": [
                                    {"type": "extract", "strategy": "fb_comments",
                                     "stop_if_no_new": True, "no_new_threshold": 2},
                                    {
                                        "type": "save_extraction",
                                        "data_var": "comments",
                                        "collection": "${SAVE_COLLECTION}",
                                        "platform": "facebook",
                                        "content_type": "comment",
                                        "dedupe_field": "text",
                                        "tags": "group,comment,${GROUP_NAME}",
                                        "parent_id_var": "_first_new_post_hash",
                                        "item_level": 1,
                                    },
                                    {"type": "scroll_down", "repeats": 1, "start_x_ratio": 0.5, "start_y_ratio": 0.65, "end_y_ratio": 0.47},
                                    {"type": "wait", "seconds": 1},
                                ],
                            },

                            {"type": "key", "key": "back"},
                            {"type": "wait_stable", "timeout": 5, "stable_duration": 0.5},
                        ],
                    },

                    # Scroll neo trái 1 lần
                    {"type": "scroll_down", "repeats": 1, "start_x_ratio": "${SCROLL_X_RATIO}", "start_y_ratio": 0.65, "end_y_ratio": 0.47},
                    # Đọc tự nhiên 1–3 giây
                    {"type": "set_variable", "name": "_W", "from_list": [1, 1, 1.5, 2, 2, 3]},
                    {"type": "wait", "seconds": "${_W}"},
                    # Đóng popup nếu xuất hiện
                    {"type": "dismiss_popup", "retries": 2},
                ],
            },

            # ── Phase 6: Kết thúc ────────────────────────────────────────────
            {
                "type": "save_extraction",
                "data_var": "posts",
                "collection": "${SAVE_COLLECTION}",
                "platform": "facebook",
                "content_type": "group_post",
                "dedupe_field": "text",
                "tags": "group,crawl,${GROUP_NAME}",
            },
            {"type": "key", "key": "home"},
        ],
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# Aggregate list
# ─────────────────────────────────────────────────────────────────────────────

BUILTIN_TEMPLATES: List[Dict[str, Any]] = (
    _GENERIC_TEMPLATES
    + _FACEBOOK_TEMPLATES
)


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
        existing = await get_template_by_name(db, spec["name"])
        if existing is None:
            await create_template(
                db,
                name=spec["name"],
                description=spec.get("description", ""),
                category=spec.get("category", "general"),
                steps=spec.get("steps", []),
                variables=spec.get("variables", {}),
                tags=spec.get("tags", ""),
                is_builtin=spec_is_builtin,
                user_id=None,
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
                steps=spec.get("steps", []),
                variables=spec.get("variables", {}),
                tags=spec.get("tags", ""),
                is_builtin=spec_is_builtin,
            )
            changed += 1

    if changed:
        await db.commit()

    return changed
