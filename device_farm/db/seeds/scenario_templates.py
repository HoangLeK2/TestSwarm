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
                    # Đóng bottom sheet còn sót (reactions/share panel) trước khi extract
                    {"type": "dismiss_popup", "retries": 1},
                    {"type": "extract", "strategy": "fb_posts", "expand_see_more": True,
                     "collection": "${SAVE_COLLECTION}", "platform": "facebook",
                     "content_type": "group_post", "dedupe_field": "text",
                     "tags": "group,crawl,${GROUP_1}"},
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
                ],
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
                    # Đóng bottom sheet còn sót (reactions/share panel) trước khi extract
                    {"type": "dismiss_popup", "retries": 1},
                    {"type": "extract", "strategy": "fb_posts", "expand_see_more": True,
                     "collection": "${SAVE_COLLECTION}", "platform": "facebook",
                     "content_type": "group_post", "dedupe_field": "text",
                     "tags": "group,crawl,${GROUP_2}"},
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
                ],
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
                    # Đóng bottom sheet còn sót (reactions/share panel) trước khi extract
                    {"type": "dismiss_popup", "retries": 1},
                    {"type": "extract", "strategy": "fb_posts", "expand_see_more": True,
                     "collection": "${SAVE_COLLECTION}", "platform": "facebook",
                     "content_type": "group_post", "dedupe_field": "text",
                     "tags": "group,crawl,${GROUP_3}"},
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
                ],
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
                    # Đóng bottom sheet còn sót (reactions/share panel) trước khi extract
                    {"type": "dismiss_popup", "retries": 1},
                    {"type": "extract", "strategy": "fb_posts", "expand_see_more": True,
                     "collection": "${SAVE_COLLECTION}", "platform": "facebook",
                     "content_type": "group_post", "dedupe_field": "text",
                     "tags": "group,crawl,${GROUP_4}"},
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

    # ── fb_groups_per_device ───────────────────────────────────────────────────
    {
        "name": "fb_groups_per_device",
        "is_builtin": False,
        "category": "facebook",
        "description": (
            "Crawl 1 group Facebook riêng cho từng thiết bị từ scenario_device_variables "
            "qua __DEVICE_GROUP__ và __DEVICE_SAVE_COLLECTION__."
        ),
        "tags": "facebook,group,multi-group,device-config,post,comment,crawl",
        "variables": {
            # Bắt buộc phải được inject từ scenario_device_variables (__DEVICE_*).
            "GROUP_NAME": "",
            "SAVE_COLLECTION": "",

            # Cấu hình crawl cho mỗi group.
            "MAX_SCROLLS_PER_GROUP": 180,
            "MAX_COMMENT_SCROLLS": 35,
            "MAX_COMMENTS_PER_POST": 500,
            "MIN_COMMENT_SCAN_PASSES": 4,
            "COMMENT_NO_NEW_THRESHOLD": 3,
            "SCROLL_X_RATIO": 0.18,
            "EXTRACT_PROFILE": "balanced",
            "FB_POSTS_STRATEGY_VERSION": "fb_posts:v1",
            "FB_COMMENTS_STRATEGY_VERSION": "fb_comments:v1",
        },
        "steps": [
            # ── Phase 1: Override từ scenario_device_variables (__DEVICE_*) ─
            # Keys nên set per device:
            #   group, save_collection
            {
                "type": "if_variable", "name": "__DEVICE_GROUP__", "not_equals": "${__DEVICE_GROUP__}",
                "then": [
                    {"type": "set_variable", "name": "GROUP_NAME", "value": "${__DEVICE_GROUP__}"},
                ],
                "else": [],
            },
            {
                "type": "if_variable", "name": "__DEVICE_SAVE_COLLECTION__", "not_equals": "${__DEVICE_SAVE_COLLECTION__}",
                "then": [
                    {"type": "set_variable", "name": "SAVE_COLLECTION", "value": "${__DEVICE_SAVE_COLLECTION__}"},
                ],
                "else": [],
            },

            # ── Phase 2: Khởi động app ──────────────────────────────────────
            {"type": "launch_app", "package": "com.facebook.katana", "title": "mở fb"},
            {"type": "dismiss_popup", "retries": 3},
            {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},

            # ── Phase 3: Crawl group riêng của thiết bị hiện tại ────────────
            {
                "type": "if_variable",
                "name": "GROUP_NAME",
                "then": [

                    # Tìm nhóm
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

                    # Chuyển tab Nhóm
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
                    {"type": "wait_stable", "timeout": 2, "stable_duration": 0.5},

                    # Vào group đầu tiên trong kết quả
                    {
                        "type": "if_element", "by": "text", "value": "${GROUP_NAME}", "timeout": 4,
                        "then": [{"type": "tap_selector", "by": "text", "value": "${GROUP_NAME}", "timeout": 4}],
                        "else": [{"type": "tap_ratio", "x": 0.5, "y": 0.24}],
                    },
                    {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},
                    {"type": "dismiss_popup", "retries": 2},
                    {"type": "scroll_down", "repeats": 2, "start_x_ratio": "${SCROLL_X_RATIO}", "start_y_ratio": 0.65, "end_y_ratio": 0.47},
                    {"type": "wait", "seconds": 2},

                    # Crawl feed + comment trong group hiện tại
                    {
                        "type": "loop",
                        "count": "${MAX_SCROLLS_PER_GROUP}",
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
                                "tags": "group,crawl,${GROUP_NAME}",
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
                            {"type": "scroll_down", "repeats": 1, "start_x_ratio": "${SCROLL_X_RATIO}", "start_y_ratio": 0.65, "end_y_ratio": 0.47},
                            {"type": "set_variable", "name": "_W", "from_list": [0.5, 0.5, 1, 1, 1.5, 2]},
                            {"type": "wait", "seconds": "${_W}"},
                        ],
                    },

                    # Quay về trước khi xử lý group kế tiếp
                    {"type": "key", "key": "back"},
                    {"type": "wait", "seconds": 1},
                    {"type": "key", "key": "back"},
                    {"type": "wait", "seconds": 1},
                    {"type": "dismiss_popup", "retries": 1},
                ],
                "else": [],
            },

            # ── Phase 4: Kết thúc ────────────────────────────────────────────
            {"type": "key", "key": "home"},
        ],
    },

    # ── fb_multi_account_groups ───────────────────────────────────────────────
    {
        "name": "fb_multi_account_groups",
        "category": "facebook",
        "is_builtin": False,
        "description": (
            "Nhiều tài khoản (thiết bị) vào nhiều nhóm FB — mỗi tài khoản xử lý "
            "tập nhóm riêng, không trùng nhau giữa các tài khoản.\n"
            "\n"
            "DEVICE_INDEX được tự động inject (0, 1, 2…) theo thứ tự thiết bị trong campaign "
            "— không cần override thủ công.\n"
            "\n"
            "Cách cấu hình:\n"
            "  1. Thêm thiết bị vào campaign theo thứ tự muốn đánh số.\n"
            "  2. Điền nhóm cho từng thiết bị:\n"
            "       GROUP_0 = ['Nhóm A', 'Nhóm B']   (device đầu tiên)\n"
            "       GROUP_1 = ['Nhóm C', 'Nhóm D']   (device thứ hai)\n"
            "       ...\n"
            "     và GROUP_COUNT_0, GROUP_COUNT_1, ... = số nhóm tương ứng.\n"
            "  3. Thêm thiết bị thứ N: thêm if_variable DEVICE_INDEX equals 'N' "
            "     + biến GROUP_N và GROUP_COUNT_N.\n"
            "\n"
            "Variables:\n"
            "  DEVICE_INDEX    : tự inject — chỉ số slot thiết bị trong campaign\n"
            "  GROUP_{N}       : list tên nhóm của thiết bị N\n"
            "  GROUP_COUNT_{N} : số phần tử trong GROUP_{N}\n"
            "  MAX_SCROLLS     : số lần scroll mỗi nhóm (default 8)\n"
            "\n"
            "Mở rộng số nhóm/device > 5: thêm if_variable GROUP_IDX equals 'K' "
            "trong loop."
        ),
        "tags": "facebook,group,multi-account,crawl,distribute",
        "variables": {
            # DEVICE_INDEX được inject tự động — giá trị default ở đây chỉ cho preview
            "DEVICE_INDEX": "0",

            # ── Nhóm cho từng thiết bị ──────────────────────────────────────
            # Thêm thiết bị: copy cặp GROUP_N + GROUP_COUNT_N, tăng N
            "GROUP_0":       ["Nhóm A1", "Nhóm A2", "Nhóm A3"],
            "GROUP_COUNT_0": 3,

            "GROUP_1":       ["Nhóm B1", "Nhóm B2", "Nhóm B3"],
            "GROUP_COUNT_1": 3,

            "GROUP_2":       ["Nhóm C1", "Nhóm C2", "Nhóm C3"],
            "GROUP_COUNT_2": 3,

            "GROUP_3":       ["Nhóm D1", "Nhóm D2", "Nhóm D3"],
            "GROUP_COUNT_3": 3,

            "GROUP_4":       ["Nhóm E1", "Nhóm E2", "Nhóm E3"],
            "GROUP_COUNT_4": 3,

            "GROUP_5":       ["Nhóm F1", "Nhóm F2", "Nhóm F3"],
            "GROUP_COUNT_5": 3,

            "MAX_SCROLLS":  8,
        },
        "steps": [
            # ── Phase 1: Gán MY_GROUPS và GROUP_COUNT theo DEVICE_INDEX ─────
            # DEVICE_INDEX inject tự động = 0/1/2… theo thứ tự thiết bị trong campaign.
            # Mỗi block dưới đây chỉ chạy trên đúng thiết bị tương ứng.
            # Thêm thiết bị thứ N: copy block, đổi equals → "N", GROUP_N, GROUP_COUNT_N.
            {
                "type": "if_variable", "name": "DEVICE_INDEX", "equals": "0",
                "then": [
                    {"type": "set_variable", "name": "MY_GROUPS",   "value": "${GROUP_0}"},
                    {"type": "set_variable", "name": "GROUP_COUNT", "value": "${GROUP_COUNT_0}"},
                ],
            },
            {
                "type": "if_variable", "name": "DEVICE_INDEX", "equals": "1",
                "then": [
                    {"type": "set_variable", "name": "MY_GROUPS",   "value": "${GROUP_1}"},
                    {"type": "set_variable", "name": "GROUP_COUNT", "value": "${GROUP_COUNT_1}"},
                ],
            },
            {
                "type": "if_variable", "name": "DEVICE_INDEX", "equals": "2",
                "then": [
                    {"type": "set_variable", "name": "MY_GROUPS",   "value": "${GROUP_2}"},
                    {"type": "set_variable", "name": "GROUP_COUNT", "value": "${GROUP_COUNT_2}"},
                ],
            },
            {
                "type": "if_variable", "name": "DEVICE_INDEX", "equals": "3",
                "then": [
                    {"type": "set_variable", "name": "MY_GROUPS",   "value": "${GROUP_3}"},
                    {"type": "set_variable", "name": "GROUP_COUNT", "value": "${GROUP_COUNT_3}"},
                ],
            },
            {
                "type": "if_variable", "name": "DEVICE_INDEX", "equals": "4",
                "then": [
                    {"type": "set_variable", "name": "MY_GROUPS",   "value": "${GROUP_4}"},
                    {"type": "set_variable", "name": "GROUP_COUNT", "value": "${GROUP_COUNT_4}"},
                ],
            },
            {
                "type": "if_variable", "name": "DEVICE_INDEX", "equals": "5",
                "then": [
                    {"type": "set_variable", "name": "MY_GROUPS",   "value": "${GROUP_5}"},
                    {"type": "set_variable", "name": "GROUP_COUNT", "value": "${GROUP_COUNT_5}"},
                ],
            },

            # ── Phase 2: Mở Facebook ─────────────────────────────────────────
            {"type": "open_url", "url": "https://www.facebook.com"},
            {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},
            {"type": "dismiss_popup", "retries": 2},

            # ── Phase 3: Khởi tạo bộ đếm nhóm (tăng trước dùng → bắt đầu từ 0) ──
            {"type": "set_variable", "name": "GROUP_IDX", "value": 0},

            # ── Phase 4: Loop lần lượt qua từng nhóm của thiết bị này ───────
            {
                "type": "loop",
                "count": "${GROUP_COUNT}",
                "steps": [

                    # Tăng chỉ số trước: GROUP_IDX = 1, 2, 3 …
                    {"type": "set_variable", "name": "GROUP_IDX", "increment": 1},

                    # Chọn tên nhóm theo vị trí tuần tự trong MY_GROUPS.
                    # MY_GROUPS là list → resolve ${MY_GROUPS} sẽ random, nên
                    # ta dùng GROUP_IDX để lấy đúng phần tử tuần tự qua if_variable.
                    # Mỗi if_variable chỉ active khi GROUP_IDX khớp đúng.
                    # Thêm nhóm thứ 6+: copy block, tăng equals và index tương ứng.
                    {
                        "type": "if_variable", "name": "GROUP_IDX", "equals": "1",
                        "then": [{"type": "set_variable", "name": "GROUP_NAME",
                                  "from_list": "${MY_GROUPS}"}],
                    },
                    {
                        "type": "if_variable", "name": "GROUP_IDX", "equals": "2",
                        "then": [{"type": "set_variable", "name": "GROUP_NAME",
                                  "from_list": "${MY_GROUPS}"}],
                    },
                    {
                        "type": "if_variable", "name": "GROUP_IDX", "equals": "3",
                        "then": [{"type": "set_variable", "name": "GROUP_NAME",
                                  "from_list": "${MY_GROUPS}"}],
                    },
                    {
                        "type": "if_variable", "name": "GROUP_IDX", "equals": "4",
                        "then": [{"type": "set_variable", "name": "GROUP_NAME",
                                  "from_list": "${MY_GROUPS}"}],
                    },
                    {
                        "type": "if_variable", "name": "GROUP_IDX", "equals": "5",
                        "then": [{"type": "set_variable", "name": "GROUP_NAME",
                                  "from_list": "${MY_GROUPS}"}],
                    },

                    # ── Vào nhóm ──────────────────────────────────────────────
                    {
                        "type": "if_element",
                        "by": "content-desc",
                        "value": "Tìm kiếm",
                        "timeout": 4,
                        "then": [
                            {"type": "tap_selector", "by": "content-desc",
                             "value": "Tìm kiếm", "timeout": 4},
                        ],
                        "else": [
                            {"type": "tap_ratio", "x": 0.87, "y": 0.035},
                        ],
                    },
                    {"type": "wait_stable", "timeout": 4, "stable_duration": 0.4},
                    {"type": "input_text", "text": "${GROUP_NAME}", "via": "u2"},
                    {"type": "wait", "seconds": 2},

                    # Lọc tab Nhóm
                    {
                        "type": "if_element",
                        "by": "text",
                        "value": "Nhóm",
                        "timeout": 4,
                        "then": [
                            {"type": "tap_selector", "by": "text", "value": "Nhóm", "timeout": 3},
                            {"type": "wait_stable", "timeout": 3, "stable_duration": 0.4},
                        ],
                    },

                    # Tap kết quả
                    {
                        "type": "if_element",
                        "by": "text",
                        "value": "${GROUP_NAME}",
                        "timeout": 5,
                        "then": [
                            {"type": "tap_selector", "by": "text",
                             "value": "${GROUP_NAME}", "timeout": 4},
                        ],
                        "else": [
                            {"type": "tap_ratio", "x": 0.5, "y": 0.25},
                        ],
                    },
                    {"type": "wait_stable", "timeout": 5, "stable_duration": 0.5},
                    {"type": "dismiss_popup", "retries": 2},

                    # ── Cuộn feed ─────────────────────────────────────────────
                    {
                        "type": "repeat",
                        "count": "${MAX_SCROLLS}",
                        "steps": [
                            {"type": "scroll_down",
                             "start_x_ratio": 0.3,
                             "start_y_ratio": 0.65,
                             "end_y_ratio": 0.35},
                            {"type": "set_variable", "name": "_W",
                             "from_list": [1, 1.5, 2, 2, 2.5]},
                            {"type": "wait", "seconds": "${_W}"},
                        ],
                    },

                    # ── Quay về ───────────────────────────────────────────────
                    {"type": "key", "key": "back"},
                    {"type": "wait", "seconds": 1},
                    {"type": "key", "key": "back"},
                    {"type": "wait", "seconds": 1},
                    {"type": "dismiss_popup", "retries": 1},
                ],
            },

            # ── Phase 5: Kết thúc ────────────────────────────────────────────
            {"type": "key", "key": "home"},
        ],
    },

    # ── fb_account_random_groups ──────────────────────────────────────────────
    {
        "name": "fb_account_random_groups",
        "category": "facebook",
        "is_builtin": False,
        "description": (
            "Mỗi thiết bị nhận 1 account từ account group (round-robin), login vào "
            "Facebook, rồi chọn ngẫu nhiên GROUPS_PER_RUN nhóm từ danh sách GROUPS "
            "và cuộn đọc mỗi nhóm.\n"
            "\n"
            "Credentials inject tự động qua account group:\n"
            "  __ACCOUNT_USERNAME__ : email / số điện thoại\n"
            "  __ACCOUNT_PASSWORD__ : mật khẩu (giải mã lúc runtime)\n"
            "\n"
            "Variables cần điền:\n"
            "  GROUPS         : danh sách tên nhóm (list string)\n"
            "  GROUPS_PER_RUN : số nhóm ghé mỗi lần chạy (default 3)\n"
            "  MAX_SCROLLS    : số lần scroll trong mỗi nhóm (default 8)\n"
            "  APP_PACKAGE    : com.facebook.katana hoặc com.facebook.lite\n"
            "\n"
            "Vận hành nhiều account:\n"
            "  Thêm tất cả account vào 1 account group → gắn group vào scenario.\n"
            "  Mỗi lần chạy campaign: 3 phone × 1 account (round-robin).\n"
            "  Chạy lại để dùng tiếp các account còn lại."
        ),
        "tags": "facebook,group,login,account,random,crawl,multi-account",
        "variables": {
            "APP_PACKAGE": "com.facebook.katana",
            "GROUPS": [
                "Hội mua bán đồ cũ Hà Nội",
                "Review sản phẩm chính hãng",
                "Du lịch Việt Nam",
                "Nuôi chó mèo Việt Nam",
                "Học tiếng Anh giao tiếp",
                "Đầu tư chứng khoán F0",
                "Lập trình viên Việt Nam",
                "Mẹ bỉm sữa chia sẻ kinh nghiệm",
            ],
            "GROUPS_PER_RUN": 3,
            "MAX_SCROLLS": 8,
        },
        "steps": [
            # ── Phase 1: Khởi động app + kiểm tra login ─────────────────────
            {"type": "launch_app", "package": "${APP_PACKAGE}", "wait_after": 4},
            {"type": "dismiss_popup", "retries": 2},
            {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},

            # Nếu có màn hình login (chưa đăng nhập / bị đăng xuất) → login
            {
                "type": "if_element",
                "by": "text",
                "value": "Đăng nhập",
                "timeout": 4,
                "then": [
                    # Nhập username
                    {
                        "type": "if_element",
                        "by": "text",
                        "value": "Email hoặc số điện thoại",
                        "timeout": 3,
                        "then": [
                            {"type": "tap_selector", "by": "text",
                             "value": "Email hoặc số điện thoại", "timeout": 3},
                        ],
                        "else": [
                            {"type": "tap_ratio", "x": 0.5, "y": 0.42},
                        ],
                    },
                    {"type": "input_text", "text": "${__ACCOUNT_USERNAME__}", "via": "u2"},
                    {"type": "wait", "seconds": 0.5},

                    # Nhập password
                    {
                        "type": "if_element",
                        "by": "text",
                        "value": "Mật khẩu",
                        "timeout": 3,
                        "then": [
                            {"type": "tap_selector", "by": "text",
                             "value": "Mật khẩu", "timeout": 3},
                        ],
                        "else": [
                            {"type": "tap_ratio", "x": 0.5, "y": 0.52},
                        ],
                    },
                    {"type": "input_text", "text": "${__ACCOUNT_PASSWORD__}", "via": "u2"},
                    {"type": "wait", "seconds": 0.5},

                    # Submit
                    {"type": "tap_selector", "by": "text", "value": "Đăng nhập", "timeout": 3},
                    {"type": "wait_stable", "timeout": 10, "stable_duration": 0.8},
                    {"type": "dismiss_popup", "retries": 3},
                ],
            },

            # ── Phase 2: Vào ngẫu nhiên GROUPS_PER_RUN nhóm ─────────────────
            {
                "type": "repeat",
                "count": "${GROUPS_PER_RUN}",
                "steps": [

                    # Chọn ngẫu nhiên 1 nhóm từ danh sách
                    {"type": "set_variable", "name": "GROUP_NAME", "from_list": "${GROUPS}"},

                    # Mở tìm kiếm
                    {
                        "type": "if_element",
                        "by": "content-desc",
                        "value": "Tìm kiếm",
                        "timeout": 4,
                        "then": [
                            {"type": "tap_selector", "by": "content-desc",
                             "value": "Tìm kiếm", "timeout": 4},
                        ],
                        "else": [
                            {"type": "tap_ratio", "x": 0.87, "y": 0.035},
                        ],
                    },
                    {"type": "wait_stable", "timeout": 4, "stable_duration": 0.4},

                    # Tìm tên nhóm
                    {"type": "input_text", "text": "${GROUP_NAME}", "via": "u2"},
                    {"type": "wait", "seconds": 2},

                    # Lọc tab Nhóm
                    {
                        "type": "if_element",
                        "by": "text",
                        "value": "Nhóm",
                        "timeout": 4,
                        "then": [
                            {"type": "tap_selector", "by": "text", "value": "Nhóm", "timeout": 3},
                            {"type": "wait_stable", "timeout": 3, "stable_duration": 0.4},
                        ],
                    },

                    # Tap kết quả
                    {
                        "type": "if_element",
                        "by": "text",
                        "value": "${GROUP_NAME}",
                        "timeout": 5,
                        "then": [
                            {"type": "tap_selector", "by": "text",
                             "value": "${GROUP_NAME}", "timeout": 4},
                        ],
                        "else": [
                            {"type": "tap_ratio", "x": 0.5, "y": 0.25},
                        ],
                    },
                    {"type": "wait_stable", "timeout": 5, "stable_duration": 0.5},
                    {"type": "dismiss_popup", "retries": 2},

                    # Cuộn đọc feed
                    {
                        "type": "repeat",
                        "count": "${MAX_SCROLLS}",
                        "steps": [
                            {"type": "scroll_down",
                             "start_x_ratio": 0.3,
                             "start_y_ratio": 0.65,
                             "end_y_ratio": 0.35},
                            {"type": "set_variable", "name": "_W",
                             "from_list": [1, 1.5, 2, 2, 2.5]},
                            {"type": "wait", "seconds": "${_W}"},
                        ],
                    },

                    # Quay về trước khi vào nhóm tiếp
                    {"type": "key", "key": "back"},
                    {"type": "wait", "seconds": 1},
                    {"type": "key", "key": "back"},
                    {"type": "wait", "seconds": 1},
                    {"type": "dismiss_popup", "retries": 1},

                    # Delay tự nhiên giữa các nhóm
                    {"type": "set_variable", "name": "_GAP",
                     "from_list": [3, 5, 7, 10]},
                    {"type": "wait", "seconds": "${_GAP}"},
                ],
            },

            # ── Phase 3: Kết thúc ────────────────────────────────────────────
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
