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
    # ── fb_scroll_feed ──────────────────────────────────────────────────────
    {
        "name": "fb_scroll_feed",
        "category": "facebook",
        "description": (
            "Cuộn Facebook News Feed với hành vi tự nhiên. "
            "Mỗi chu kỳ scroll 1-3 lần (ngẫu nhiên), dừng đọc 2-8 giây, "
            "thỉnh thoảng like bài (mặc định xác suất 25%). "
            "Phù hợp warm-up account và tăng organic engagement. "
            "APP_PACKAGE: com.facebook.katana (regular) hoặc com.facebook.lite (Lite). "
            "LIKE_WEIGHT: trọng số like so với tổng 100 (25 = ~25% xác suất)."
        ),
        "tags": "facebook,feed,scroll,like,engagement,behavior,natural",
        "variables": {
            "SCROLL_ROUNDS": 10,
            "APP_PACKAGE": "com.facebook.katana",
            "LIKE_WEIGHT": 25,
        },
        "steps": [
            {"type": "launch_app", "package": "${APP_PACKAGE}", "wait_after": 5},
            {"type": "dismiss_popup", "retries": 3},
            {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},
            {
                "type": "repeat",
                "count": "${SCROLL_ROUNDS}",
                "steps": [
                    # Random 1-3 scroll gestures for natural variation
                    {"type": "set_variable", "name": "_S", "from_list": [1, 1, 2, 2, 3]},
                    {"type": "scroll_down", "repeats": "${_S}"},
                    # Simulate reading time (2-8s)
                    {"type": "set_variable", "name": "_READ", "from_list": [2, 3, 4, 5, 6, 7, 8]},
                    {"type": "wait", "seconds": "${_READ}"},
                    # Like with LIKE_WEIGHT% probability
                    {
                        "type": "random_pick",
                        "branches": [
                            {
                                "weight": "${LIKE_WEIGHT}",
                                "steps": [
                                    {
                                        "type": "if_element",
                                        "by": "content-desc",
                                        "value": "Like",
                                        "timeout": 1,
                                        "then": [
                                            {
                                                "type": "tap_selector",
                                                "by": "content-desc",
                                                "value": "Like",
                                                "timeout": 2,
                                            }
                                        ],
                                    }
                                ],
                            },
                            {"weight": 75, "steps": []},
                        ],
                    },
                    # Dismiss any dialog that might pop up (notification request, etc.)
                    {"type": "dismiss_popup", "retries": 1},
                    # Short pause before next scroll cycle
                    {"type": "set_variable", "name": "_P", "from_list": [0.5, 1, 1.5]},
                    {"type": "wait", "seconds": "${_P}"},
                ],
            },
        ],
    },

    # ── fb_like_posts ───────────────────────────────────────────────────────
    {
        "name": "fb_like_posts",
        "category": "facebook",
        "description": (
            "Tự động like đúng LIKE_COUNT bài viết trên Facebook News Feed. "
            "Cuộn feed, tìm nút Like chưa nhấn, tap, đếm; lặp cho đến đủ số. "
            "Có delay ngẫu nhiên giữa mỗi lần like để tránh spam detection. "
            "LIKE_COUNT: số like mục tiêu (mặc định 5). "
            "MAX_SAFE_ITER: giới hạn scroll-không-tìm-thấy để tránh loop vô tận."
        ),
        "tags": "facebook,like,engagement,automation",
        "variables": {
            "LIKE_COUNT": 5,
            "APP_PACKAGE": "com.facebook.katana",
            "MAX_SAFE_ITER": 80,
        },
        "steps": [
            {"type": "launch_app", "package": "${APP_PACKAGE}", "wait_after": 5},
            {"type": "dismiss_popup", "retries": 3},
            {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},
            {"type": "set_variable", "name": "LIKED", "value": 0},
            {
                "type": "repeat_until",
                "condition": {"variable_equals": {"name": "LIKED", "value": "${LIKE_COUNT}"}},
                "max_iterations": "${MAX_SAFE_ITER}",
                "steps": [
                    # Scroll to expose next post
                    {"type": "set_variable", "name": "_S", "from_list": [1, 1, 2]},
                    {"type": "scroll_down", "repeats": "${_S}"},
                    {"type": "set_variable", "name": "_W", "from_list": [2, 2.5, 3, 4]},
                    {"type": "wait", "seconds": "${_W}"},
                    # Like if button is visible and not yet tapped
                    {
                        "type": "if_element",
                        "by": "content-desc",
                        "value": "Like",
                        "timeout": 2,
                        "then": [
                            {
                                "type": "tap_selector",
                                "by": "content-desc",
                                "value": "Like",
                                "timeout": 2,
                            },
                            {"type": "set_variable", "name": "LIKED", "increment": 1},
                            # Anti-spam: wait 30-90s between likes (adjust for account safety)
                            {
                                "type": "set_variable",
                                "name": "_PAUSE",
                                "from_list": [30, 45, 60, 75, 90],
                            },
                            {"type": "wait", "seconds": "${_PAUSE}"},
                            {"type": "dismiss_popup", "retries": 1},
                        ],
                    },
                ],
            },
        ],
    },

    # ── fb_watch_reels ──────────────────────────────────────────────────────
    {
        "name": "fb_watch_reels",
        "category": "facebook",
        "description": (
            "Xem Facebook Reels với hành vi tự nhiên. "
            "Dừng xem từng video VIEW_MIN_S–VIEW_MAX_S giây, "
            "thỉnh thoảng like (LIKE_WEIGHT%), sau đó swipe lên reel tiếp theo. "
            "REEL_COUNT: tổng số reel xem. "
            "Chạy trên Facebook app (không phải Lite vì Lite không có Reels tab đầy đủ)."
        ),
        "tags": "facebook,reels,video,watch,like,engagement,swipe",
        "variables": {
            "REEL_COUNT": 15,
            "LIKE_WEIGHT": 25,
            "VIEW_MIN_S": 5,
            "VIEW_MAX_S": 25,
        },
        "steps": [
            {"type": "launch_app", "package": "com.facebook.katana", "wait_after": 5},
            {"type": "dismiss_popup", "retries": 3},
            # Navigate to Reels tab (try content-desc first, fallback to text)
            {
                "type": "if_element",
                "by": "content-desc",
                "value": "Reels",
                "timeout": 6,
                "then": [
                    {"type": "tap_selector", "by": "content-desc", "value": "Reels", "timeout": 5}
                ],
                "else": [
                    {"type": "tap_selector", "by": "text", "value": "Reels", "timeout": 5}
                ],
            },
            {"type": "wait_stable", "timeout": 5, "stable_duration": 0.5},
            {
                "type": "repeat",
                "count": "${REEL_COUNT}",
                "steps": [
                    # Simulate watching (random duration within configured range)
                    {
                        "type": "set_variable",
                        "name": "_VIEW",
                        "from_list": [5, 7, 9, 12, 15, 18, 20, 25],
                    },
                    {"type": "wait", "seconds": "${_VIEW}"},
                    # Like with LIKE_WEIGHT% probability
                    {
                        "type": "random_pick",
                        "branches": [
                            {
                                "weight": "${LIKE_WEIGHT}",
                                "steps": [
                                    {
                                        "type": "if_element",
                                        "by": "content-desc",
                                        "value": "Like",
                                        "timeout": 1,
                                        "then": [
                                            {
                                                "type": "tap_selector",
                                                "by": "content-desc",
                                                "value": "Like",
                                                "timeout": 2,
                                            }
                                        ],
                                    }
                                ],
                            },
                            {"weight": 75, "steps": []},
                        ],
                    },
                    # Swipe up to next reel (ratio-based, reliable across screen sizes)
                    {
                        "type": "swipe_ratio",
                        "x1": 0.5,
                        "y1": 0.78,
                        "x2": 0.5,
                        "y2": 0.22,
                        "duration_ms": 280,
                    },
                    {"type": "wait_stable", "timeout": 3, "stable_duration": 0.3},
                    {"type": "dismiss_popup", "retries": 1},
                ],
            },
        ],
    },

    # ── fb_add_friends ──────────────────────────────────────────────────────
    {
        "name": "fb_add_friends",
        "category": "facebook",
        "description": (
            "Gửi MAX_REQUESTS lời mời kết bạn từ danh sách 'People You May Know'. "
            "Điều hướng đến tab Friends, cuộn tìm nút 'Add friend', tap, "
            "chờ ngẫu nhiên 60-120 giây giữa mỗi lần gửi (anti-spam). "
            "⚠ Dùng thận trọng: FB có thể tạm khóa tính năng kết bạn nếu gửi quá nhiều."
        ),
        "tags": "facebook,friend,add,request,engagement,social",
        "variables": {
            "MAX_REQUESTS": 5,
            "APP_PACKAGE": "com.facebook.katana",
        },
        "steps": [
            {"type": "launch_app", "package": "${APP_PACKAGE}", "wait_after": 5},
            {"type": "dismiss_popup", "retries": 3},
            # Navigate to Friends tab
            {
                "type": "if_element",
                "by": "content-desc",
                "value": "Friends",
                "timeout": 6,
                "then": [
                    {"type": "tap_selector", "by": "content-desc", "value": "Friends", "timeout": 5}
                ],
                "else": [
                    {"type": "tap_selector", "by": "text", "value": "Friends", "timeout": 5}
                ],
            },
            {"type": "wait_stable", "timeout": 5, "stable_duration": 0.5},
            {"type": "set_variable", "name": "SENT", "value": 0},
            {
                "type": "repeat_until",
                "condition": {"variable_equals": {"name": "SENT", "value": "${MAX_REQUESTS}"}},
                "max_iterations": 60,
                "steps": [
                    # Scroll to find an 'Add friend' button
                    {
                        "type": "scroll_to",
                        "by": "text",
                        "value": "Add friend",
                        "direction": "down",
                        "max_swipes": 4,
                    },
                    {
                        "type": "if_element",
                        "by": "text",
                        "value": "Add friend",
                        "timeout": 3,
                        "then": [
                            {
                                "type": "tap_selector",
                                "by": "text",
                                "value": "Add friend",
                                "timeout": 3,
                            },
                            {"type": "set_variable", "name": "SENT", "increment": 1},
                            # Anti-spam delay: 60-120s between requests
                            {
                                "type": "set_variable",
                                "name": "_D",
                                "from_list": [60, 70, 80, 90, 100, 110, 120],
                            },
                            {"type": "wait", "seconds": "${_D}"},
                            {"type": "dismiss_popup", "retries": 2},
                        ],
                        "else": [
                            # No button found — scroll further
                            {"type": "scroll_down", "repeats": 2},
                            {"type": "set_variable", "name": "_W", "from_list": [2, 3, 4]},
                            {"type": "wait", "seconds": "${_W}"},
                        ],
                    },
                ],
            },
        ],
    },

    # ── fb_crawl_feed ───────────────────────────────────────────────────────
    {
        "name": "fb_crawl_feed",
        "category": "facebook",
        "description": (
            "Crawl Facebook News Feed: cuộn feed, expand 'See more', "
            "extract bài viết (author, text, reactions, comments, shares, "
            "post_type, image_desc, comment_preview). "
            "Dữ liệu tích lũy trong context['posts'], tự động dừng khi 3 lần scroll "
            "không có bài mới (stop_if_no_new). "
            "Dùng bước save_extraction để lưu posts vào content DB. "
            "APP_PACKAGE: com.facebook.katana hoặc com.facebook.lite. "
            "MAX_SCROLLS: giới hạn tổng số scroll (default 30). "
            "SCROLL_PAUSE: giây chờ sau mỗi scroll để feed tải xong."
        ),
        "tags": "facebook,crawl,extract,data,scrape,feed,posts",
        "variables": {
            "APP_PACKAGE": "com.facebook.katana",
            "MAX_SCROLLS": 30,
            "SCROLL_PAUSE": 2.5,
        },
        "steps": [
            {"type": "launch_app", "package": "${APP_PACKAGE}", "wait_after": 5},
            {"type": "dismiss_popup", "retries": 3},
            {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},
            {
                "type": "loop",
                "count": "${MAX_SCROLLS}",
                "steps": [
                    # Extract: parse current screen, auto-expand See more, dedup
                    {
                        "type": "extract",
                        "strategy": "fb_posts",
                        "stop_if_no_new": True,
                        "no_new_threshold": 3,
                        "expand_see_more": True,
                    },
                    {"type": "scroll_down", "repeats": 1},
                    {"type": "wait", "seconds": "${SCROLL_PAUSE}"},
                    {"type": "dismiss_popup", "retries": 1},
                ],
            },
        ],
    },

    {
        "name": "fb_crawl_group",
        "category": "facebook",
        "description": (
            "Crawl bài viết từ một Facebook Group cụ thể qua Chrome browser "
            "(m.facebook.com/groups/{GROUP_ID}). "
            "Mở URL group, chờ load, expand 'See more', extract bài viết và cuộn. "
            "Tự động dừng sau 3 lần scroll không có bài mới. "
            "GROUP_ID: ID số hoặc slug của group (ví dụ: '123456789' hoặc 'my-group-slug'). "
            "APP_PACKAGE: mặc định Chrome (com.android.chrome), "
            "hoặc com.facebook.katana để mở bằng FB app. "
            "Yêu cầu: device đã đăng nhập FB trong Chrome/FB app. "
            "Dùng qua endpoint POST /api/devices/{serial}/crawl/jobs."
        ),
        "tags": "facebook,crawl,extract,data,group,scrape,posts,chrome",
        "variables": {
            "GROUP_ID": "",
            "APP_PACKAGE": "com.android.chrome",
            "WAIT_LOAD": 4,
            "MAX_SCROLLS": 40,
            "SCROLL_PAUSE": 2.5,
        },
        "steps": [
            # Open group URL via Chrome (more stable DOM structure vs native app)
            {
                "type": "open_url",
                "url": "https://m.facebook.com/groups/${GROUP_ID}",
                "package": "${APP_PACKAGE}",
            },
            {"type": "wait", "seconds": "${WAIT_LOAD}"},
            # Handle login wall if present
            {
                "type": "if_element",
                "by": "text",
                "value": "Not Now",
                "timeout": 3,
                "then": [{"type": "tap_selector", "by": "text", "value": "Not Now", "timeout": 3}],
            },
            {
                "type": "if_element",
                "by": "text",
                "value": "Không phải bây giờ",
                "timeout": 2,
                "then": [
                    {
                        "type": "tap_selector",
                        "by": "text",
                        "value": "Không phải bây giờ",
                        "timeout": 3,
                    }
                ],
            },
            {"type": "dismiss_popup", "retries": 2},
            # Crawl loop
            {
                "type": "loop",
                "count": "${MAX_SCROLLS}",
                "steps": [
                    {
                        "type": "extract",
                        "strategy": "fb_posts",
                        "stop_if_no_new": True,
                        "no_new_threshold": 3,
                        "expand_see_more": True,
                    },
                    {"type": "scroll_down", "repeats": 1},
                    {"type": "wait", "seconds": "${SCROLL_PAUSE}"},
                ],
            },
        ],
    },

    # ── fb_crawl_group_native ─────────────────────────────────────────────
    # Built from capture eae85582931e8222_2026-03-29_211008 (OpenClaw VN group).
    # Uses native FB app selectors observed in hierarchy XML.
    {
        "name": "fb_crawl_group_native",
        "category": "facebook",
        "description": (
            "Crawl bài viết từ một Facebook Group bằng app native (com.facebook.katana). "
            "Mở FB → Search → gõ tên group → tap group → cuộn và extract bài viết. "
            "Thu thập: tên tác giả, nội dung, thời gian, lượt like, comment, share, "
            "mô tả ảnh/video, preview comment. "
            "Tự động expand 'xem thêm' để lấy nội dung đầy đủ. "
            "Tự động dừng khi 3 lần scroll không có bài mới. "
            "Dữ liệu lưu vào content DB qua bước save_extraction. "
            "\n"
            "GROUP_NAME: tên group hiển thị trên FB (ví dụ: 'OpenClaw VN'). "
            "MAX_SCROLLS: giới hạn tổng số scroll (default 50). "
            "SCROLL_PAUSE: giây chờ giữa mỗi scroll để feed tải (default 2.5). "
            "LIKE_WHILE_CRAWL: xác suất like ngẫu nhiên khi crawl (0-100, default 0 = tắt). "
            "SAVE_COLLECTION: tên collection để lưu vào content DB."
        ),
        "tags": "facebook,crawl,extract,group,data,scrape,posts,native,like,comment,share",
        "variables": {
            "GROUP_NAME": "OpenClaw VN",
            "APP_PACKAGE": "com.facebook.katana",
            "MAX_SCROLLS": 50,
            "SCROLL_PAUSE": 2.5,
            "LIKE_WHILE_CRAWL": 0,
            "SAVE_COLLECTION": "fb_group_posts",
        },
        "steps": [
            # ── Phase 1: Launch & Navigate to Group ──────────────────────
            {"type": "launch_app", "package": "${APP_PACKAGE}", "wait_after": 5},
            {"type": "dismiss_popup", "retries": 3},
            {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},

            # Tap Search icon (top bar)
            {
                "type": "if_element",
                "by": "content-desc",
                "value": "Search Facebook",
                "timeout": 5,
                "then": [
                    {"type": "tap_selector", "by": "content-desc", "value": "Search Facebook", "timeout": 4},
                ],
                "else": [
                    # Fallback: tap search icon by resource-id (varies by version)
                    {
                        "type": "if_element",
                        "by": "content-desc",
                        "value": "Tìm kiếm",
                        "timeout": 3,
                        "then": [
                            {"type": "tap_selector", "by": "content-desc", "value": "Tìm kiếm", "timeout": 3},
                        ],
                        "else": [
                            # Last resort: tap the search position from recording
                            {"type": "tap_ratio", "x": 0.62, "y": 0.045},
                        ],
                    },
                ],
            },
            {"type": "wait_stable", "timeout": 4, "stable_duration": 0.4},

            # Type group name in search box
            {"type": "input_text", "text": "${GROUP_NAME}", "via": "u2"},
            {"type": "wait", "seconds": 2},

            # Tap the group from search results (match by content-desc or text)
            {
                "type": "if_element",
                "by": "content-desc",
                "value": "${GROUP_NAME}",
                "timeout": 5,
                "then": [
                    {"type": "tap_selector", "by": "content-desc", "value": "${GROUP_NAME}", "timeout": 4},
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
                    },
                ],
            },
            {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},

            # ── Phase 2: Scroll past group header to posts ──────────────
            # Group page has cover photo + info — scroll 2-3 times to reach posts
            {"type": "scroll_down", "repeats": 2},
            {"type": "wait_stable", "timeout": 3, "stable_duration": 0.4},

            # ── Phase 3: Crawl Loop ─────────────────────────────────────
            {
                "type": "loop",
                "count": "${MAX_SCROLLS}",
                "steps": [
                    # Extract posts from current screen
                    # strategy=fb_posts parses: author, text, timestamp, reactions,
                    # comments, shares, post_type, image_desc, comment_preview
                    {
                        "type": "extract",
                        "strategy": "fb_posts",
                        "stop_if_no_new": True,
                        "no_new_threshold": 3,
                        "expand_see_more": True,
                    },

                    # Optional: like while crawling (natural behavior)
                    {
                        "type": "random_pick",
                        "branches": [
                            {
                                "weight": "${LIKE_WHILE_CRAWL}",
                                "steps": [
                                    {
                                        "type": "if_element",
                                        "by": "text",
                                        "value": "Thích",
                                        "timeout": 1,
                                        "then": [
                                            {"type": "tap_selector", "by": "text", "value": "Thích", "timeout": 2},
                                            {"type": "wait", "seconds": 1},
                                        ],
                                    },
                                ],
                            },
                            {"weight": 100, "steps": []},
                        ],
                    },

                    # Scroll down to load more posts
                    {
                        "type": "set_variable",
                        "name": "_SCROLL_N",
                        "from_list": [1, 1, 2],
                    },
                    {"type": "scroll_down", "repeats": "${_SCROLL_N}"},
                    {"type": "wait", "seconds": "${SCROLL_PAUSE}"},
                    {"type": "dismiss_popup", "retries": 1},
                ],
            },

            # ── Phase 4: Save extracted data ────────────────────────────
            {
                "type": "save_extraction",
                "data_var": "posts",
                "collection": "${SAVE_COLLECTION}",
                "platform": "facebook",
                "content_type": "group_post",
                "dedupe_field": "content",
                "tags": "group,${GROUP_NAME}",
            },
        ],
    },

    # ── fb_crawl_group_deep ────────────────────────────────────────────────
    {
        "name": "fb_crawl_group_deep",
        "category": "facebook",
        "description": (
            "Crawl sâu bài viết Facebook Group: ngoài extract cơ bản (tác giả, nội dung, "
            "like/comment/share), template này còn TAP vào từng bài để lấy full nội dung + "
            "comment, rồi quay lại feed tiếp tục. "
            "Chậm hơn fb_crawl_group_native nhưng thu thập đầy đủ hơn. "
            "\n"
            "GROUP_NAME: tên group. "
            "MAX_POSTS: số bài muốn crawl sâu (default 20). "
            "SAVE_COLLECTION: collection name."
        ),
        "tags": "facebook,crawl,extract,group,deep,comments,full,scrape",
        "variables": {
            "GROUP_NAME": "OpenClaw VN",
            "APP_PACKAGE": "com.facebook.katana",
            "MAX_POSTS": 20,
            "SAVE_COLLECTION": "fb_group_deep",
        },
        "steps": [
            # ── Navigate to group (reuse same pattern) ──────────────────
            {"type": "launch_app", "package": "${APP_PACKAGE}", "wait_after": 5},
            {"type": "dismiss_popup", "retries": 3},
            {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},
            {
                "type": "if_element",
                "by": "content-desc",
                "value": "Search Facebook",
                "timeout": 5,
                "then": [
                    {"type": "tap_selector", "by": "content-desc", "value": "Search Facebook", "timeout": 4},
                ],
                "else": [
                    {
                        "type": "if_element",
                        "by": "content-desc",
                        "value": "Tìm kiếm",
                        "timeout": 3,
                        "then": [
                            {"type": "tap_selector", "by": "content-desc", "value": "Tìm kiếm", "timeout": 3},
                        ],
                        "else": [
                            {"type": "tap_ratio", "x": 0.62, "y": 0.045},
                        ],
                    },
                ],
            },
            {"type": "wait_stable", "timeout": 4, "stable_duration": 0.4},
            {"type": "input_text", "text": "${GROUP_NAME}", "via": "u2"},
            {"type": "wait", "seconds": 2},
            {
                "type": "if_element",
                "by": "content-desc",
                "value": "${GROUP_NAME}",
                "timeout": 5,
                "then": [
                    {"type": "tap_selector", "by": "content-desc", "value": "${GROUP_NAME}", "timeout": 4},
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
                    },
                ],
            },
            {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},
            {"type": "scroll_down", "repeats": 2},
            {"type": "wait_stable", "timeout": 3, "stable_duration": 0.4},

            # ── Deep crawl loop ─────────────────────────────────────────
            {"type": "set_variable", "name": "CRAWLED", "value": 0},
            {
                "type": "repeat_until",
                "condition": {"variable_equals": {"name": "CRAWLED", "value": "${MAX_POSTS}"}},
                "max_iterations": 200,
                "steps": [
                    # Quick extract from feed view first
                    {
                        "type": "extract",
                        "strategy": "fb_posts",
                        "expand_see_more": True,
                    },

                    # Tap into post detail — FB posts have content-desc
                    # "Lựa chọn khác cho bài viết của <Author>"
                    # The post body itself is clickable
                    {
                        "type": "if_element",
                        "by": "text",
                        "value": "Bình luận",
                        "timeout": 2,
                        "then": [
                            # Tap "Bình luận" to open post detail with comments
                            {"type": "tap_selector", "by": "text", "value": "Bình luận", "timeout": 3},
                            {"type": "wait_stable", "timeout": 5, "stable_duration": 0.5},

                            # Extract full post + comments in detail view
                            {
                                "type": "extract",
                                "strategy": "fb_posts",
                                "expand_see_more": True,
                            },

                            # Scroll to load more comments
                            {"type": "scroll_down", "repeats": 2},
                            {"type": "wait", "seconds": 1.5},
                            {
                                "type": "extract",
                                "strategy": "fb_posts",
                                "expand_see_more": False,
                            },

                            # Go back to feed
                            {"type": "key", "key": "back"},
                            {"type": "wait_stable", "timeout": 4, "stable_duration": 0.4},

                            {"type": "set_variable", "name": "CRAWLED", "increment": 1},
                        ],
                        "else": [
                            # No "Bình luận" visible — scroll to find next post
                            {"type": "scroll_down", "repeats": 1},
                            {"type": "wait", "seconds": 2},
                        ],
                    },

                    # Scroll to next post in feed
                    {"type": "scroll_down", "repeats": 1},
                    {
                        "type": "set_variable",
                        "name": "_PAUSE",
                        "from_list": [1.5, 2, 2.5, 3],
                    },
                    {"type": "wait", "seconds": "${_PAUSE}"},
                    {"type": "dismiss_popup", "retries": 1},
                    # Persist incrementally so data is not lost when device/u2 is unstable
                    # and the campaign task times out before exiting repeat_until.
                    {
                        "type": "save_extraction",
                        "data_var": "posts",
                        "collection": "${SAVE_COLLECTION}",
                        "platform": "facebook",
                        "content_type": "group_post_deep",
                        "dedupe_field": "content",
                        "tags": "group,deep,${GROUP_NAME}",
                    },
                ],
            },

            {
                "type": "save_extraction",
                "data_var": "posts",
                "collection": "${SAVE_COLLECTION}",
                "platform": "facebook",
                "content_type": "group_post_deep",
                "dedupe_field": "content",
                "tags": "group,deep,${GROUP_NAME}",
            },
        ],
    },

    # ── fb_group_engagement ────────────────────────────────────────────────
    {
        "name": "fb_group_engagement",
        "category": "facebook",
        "description": (
            "Tương tác tự nhiên trong Facebook Group: cuộn feed, "
            "like bài (LIKE_WEIGHT%), bình luận (COMMENT_WEIGHT%), "
            "xem ảnh/video. Dùng để warm-up account hoặc tăng organic engagement "
            "trong group. "
            "\n"
            "GROUP_NAME: tên group. "
            "ROUNDS: số vòng cuộn + tương tác. "
            "LIKE_WEIGHT: xác suất like (0-100). "
            "COMMENT_WEIGHT: xác suất bình luận (0-100). "
            "COMMENTS: danh sách comment ngẫu nhiên."
        ),
        "tags": "facebook,group,engagement,like,comment,interact,behavior,natural",
        "variables": {
            "GROUP_NAME": "OpenClaw VN",
            "APP_PACKAGE": "com.facebook.katana",
            "ROUNDS": 15,
            "LIKE_WEIGHT": 30,
            "COMMENT_WEIGHT": 10,
            "COMMENTS": [
                "Hay quá!", "Cảm ơn bạn!", "Thông tin hữu ích 👍",
                "Mình cũng quan tâm topic này", "Bookmark lại đã",
                "Thank you!", "Chia sẻ rất hay", "Noted 📝",
            ],
        },
        "steps": [
            # Navigate to group
            {"type": "launch_app", "package": "${APP_PACKAGE}", "wait_after": 5},
            {"type": "dismiss_popup", "retries": 3},
            {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},
            {
                "type": "if_element",
                "by": "content-desc",
                "value": "Search Facebook",
                "timeout": 5,
                "then": [
                    {"type": "tap_selector", "by": "content-desc", "value": "Search Facebook", "timeout": 4},
                ],
                "else": [
                    {
                        "type": "if_element",
                        "by": "content-desc",
                        "value": "Tìm kiếm",
                        "timeout": 3,
                        "then": [
                            {"type": "tap_selector", "by": "content-desc", "value": "Tìm kiếm", "timeout": 3},
                        ],
                        "else": [
                            {"type": "tap_ratio", "x": 0.62, "y": 0.045},
                        ],
                    },
                ],
            },
            {"type": "wait_stable", "timeout": 4, "stable_duration": 0.4},
            {"type": "input_text", "text": "${GROUP_NAME}", "via": "u2"},
            {"type": "wait", "seconds": 2},
            {
                "type": "if_element",
                "by": "content-desc",
                "value": "${GROUP_NAME}",
                "timeout": 5,
                "then": [
                    {"type": "tap_selector", "by": "content-desc", "value": "${GROUP_NAME}", "timeout": 4},
                ],
                "else": [
                    {"type": "tap_selector", "by": "text", "value": "${GROUP_NAME}", "timeout": 3},
                ],
            },
            {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},
            {"type": "scroll_down", "repeats": 2},
            {"type": "wait_stable", "timeout": 3, "stable_duration": 0.4},

            # Engagement loop
            {
                "type": "repeat",
                "count": "${ROUNDS}",
                "steps": [
                    # Scroll 1-3 times
                    {"type": "set_variable", "name": "_S", "from_list": [1, 1, 2, 2, 3]},
                    {"type": "scroll_down", "repeats": "${_S}"},

                    # Read time
                    {"type": "set_variable", "name": "_READ", "from_list": [3, 4, 5, 6, 8, 10]},
                    {"type": "wait", "seconds": "${_READ}"},

                    # Like with probability
                    {
                        "type": "random_pick",
                        "branches": [
                            {
                                "weight": "${LIKE_WEIGHT}",
                                "steps": [
                                    {
                                        "type": "if_element",
                                        "by": "text",
                                        "value": "Thích",
                                        "timeout": 1,
                                        "then": [
                                            {"type": "tap_selector", "by": "text", "value": "Thích", "timeout": 2},
                                            {"type": "wait", "seconds": 1},
                                        ],
                                    },
                                ],
                            },
                            {"weight": 70, "steps": []},
                        ],
                    },

                    # Comment with probability
                    {
                        "type": "random_pick",
                        "branches": [
                            {
                                "weight": "${COMMENT_WEIGHT}",
                                "steps": [
                                    {
                                        "type": "if_element",
                                        "by": "text",
                                        "value": "Bình luận",
                                        "timeout": 1,
                                        "then": [
                                            {"type": "tap_selector", "by": "text", "value": "Bình luận", "timeout": 2},
                                            {"type": "wait_stable", "timeout": 4, "stable_duration": 0.4},
                                            # Type random comment
                                            {
                                                "type": "set_variable",
                                                "name": "_CMT",
                                                "from_list": "${COMMENTS}",
                                            },
                                            {"type": "input_text", "text": "${_CMT}", "via": "u2"},
                                            {"type": "wait", "seconds": 1},
                                            # Submit comment (Enter key or tap Send)
                                            {
                                                "type": "if_element",
                                                "by": "content-desc",
                                                "value": "Send",
                                                "timeout": 2,
                                                "then": [
                                                    {"type": "tap_selector", "by": "content-desc", "value": "Send", "timeout": 2},
                                                ],
                                                "else": [
                                                    {
                                                        "type": "if_element",
                                                        "by": "content-desc",
                                                        "value": "Gửi",
                                                        "timeout": 2,
                                                        "then": [
                                                            {"type": "tap_selector", "by": "content-desc", "value": "Gửi", "timeout": 2},
                                                        ],
                                                        "else": [
                                                            {"type": "key", "key": "enter"},
                                                        ],
                                                    },
                                                ],
                                            },
                                            {"type": "wait", "seconds": 2},
                                            {"type": "key", "key": "back"},
                                            {"type": "wait_stable", "timeout": 3, "stable_duration": 0.4},
                                            # Anti-spam delay after comment
                                            {
                                                "type": "set_variable",
                                                "name": "_CDEL",
                                                "from_list": [30, 45, 60, 90],
                                            },
                                            {"type": "wait", "seconds": "${_CDEL}"},
                                        ],
                                    },
                                ],
                            },
                            {"weight": 90, "steps": []},
                        ],
                    },

                    {"type": "dismiss_popup", "retries": 1},
                    {"type": "set_variable", "name": "_P", "from_list": [1, 1.5, 2]},
                    {"type": "wait", "seconds": "${_P}"},
                ],
            },
        ],
    },
]


_TIKTOK_TEMPLATES: List[Dict[str, Any]] = [
    # ── tt_scroll_fyp ───────────────────────────────────────────────────────
    {
        "name": "tt_scroll_fyp",
        "category": "tiktok",
        "description": (
            "Xem TikTok For You Page (FYP) với hành vi tự nhiên. "
            "Dừng xem từng video VIEW_MIN_S–VIEW_MAX_S giây, "
            "thỉnh thoảng like (LIKE_WEIGHT%), thỉnh thoảng follow creator (FOLLOW_WEIGHT%), "
            "sau đó swipe lên video tiếp theo. "
            "VIDEO_COUNT: tổng số video xem. "
            "APP_PACKAGE: com.zhiliaoapp.musically (global) "
            "hoặc com.ss.android.ugc.trill (một số vùng). "
            "LIKE_WEIGHT + FOLLOW_WEIGHT phải < 100 để branch 'bỏ qua' có weight > 0."
        ),
        "tags": "tiktok,fyp,scroll,watch,like,follow,engagement,behavior",
        "variables": {
            "VIDEO_COUNT": 20,
            "LIKE_WEIGHT": 20,
            "FOLLOW_WEIGHT": 5,
            "VIEW_MIN_S": 5,
            "VIEW_MAX_S": 30,
            "APP_PACKAGE": "com.zhiliaoapp.musically",
        },
        "steps": [
            {"type": "launch_app", "package": "${APP_PACKAGE}", "wait_after": 5},
            {"type": "dismiss_popup", "retries": 3},
            {"type": "wait_stable", "timeout": 6, "stable_duration": 0.5},
            {
                "type": "repeat",
                "count": "${VIDEO_COUNT}",
                "steps": [
                    # Watch video for random duration
                    {
                        "type": "set_variable",
                        "name": "_VIEW",
                        "from_list": [5, 7, 9, 12, 15, 18, 22, 28, 30],
                    },
                    {"type": "wait", "seconds": "${_VIEW}"},
                    # Like with LIKE_WEIGHT% probability
                    {
                        "type": "random_pick",
                        "branches": [
                            {
                                "weight": "${LIKE_WEIGHT}",
                                "steps": [
                                    {
                                        "type": "if_element",
                                        "by": "content-desc",
                                        "value": "Like",
                                        "timeout": 1,
                                        "then": [
                                            {
                                                "type": "tap_selector",
                                                "by": "content-desc",
                                                "value": "Like",
                                                "timeout": 2,
                                            }
                                        ],
                                    }
                                ],
                            },
                            {"weight": 80, "steps": []},
                        ],
                    },
                    # Follow creator with FOLLOW_WEIGHT% probability
                    {
                        "type": "random_pick",
                        "branches": [
                            {
                                "weight": "${FOLLOW_WEIGHT}",
                                "steps": [
                                    {
                                        "type": "if_element",
                                        "by": "text",
                                        "value": "Follow",
                                        "timeout": 1,
                                        "then": [
                                            {
                                                "type": "tap_selector",
                                                "by": "text",
                                                "value": "Follow",
                                                "timeout": 2,
                                            },
                                            {"type": "wait", "seconds": 1},
                                        ],
                                    }
                                ],
                            },
                            {"weight": 95, "steps": []},
                        ],
                    },
                    # Swipe up to next video
                    {
                        "type": "swipe_ratio",
                        "x1": 0.5,
                        "y1": 0.78,
                        "x2": 0.5,
                        "y2": 0.22,
                        "duration_ms": 250,
                    },
                    {"type": "wait_stable", "timeout": 3, "stable_duration": 0.3},
                    {"type": "dismiss_popup", "retries": 1},
                ],
            },
        ],
    },

    # ── tt_search_hashtag ───────────────────────────────────────────────────
    {
        "name": "tt_search_hashtag",
        "category": "tiktok",
        "description": (
            "Tìm kiếm TikTok theo hashtag và xem kết quả. "
            "Mở TikTok, tap icon Search, gõ '#HASHTAG', nhấn Enter, "
            "chọn tab Videos, tap video đầu tiên, xem BROWSE_COUNT video "
            "bằng cách swipe lên. Thỉnh thoảng like (LIKE_WEIGHT%). "
            "HASHTAG: không cần dấu # (template tự thêm). "
            "BROWSE_COUNT: số video xem sau khi tìm kiếm. "
            "⚠ Selector cho tab Videos có thể thay đổi giữa các phiên bản TikTok."
        ),
        "tags": "tiktok,search,hashtag,browse,like,engagement",
        "variables": {
            "HASHTAG": "trending",
            "BROWSE_COUNT": 10,
            "LIKE_WEIGHT": 30,
            "APP_PACKAGE": "com.zhiliaoapp.musically",
        },
        "steps": [
            {"type": "launch_app", "package": "${APP_PACKAGE}", "wait_after": 5},
            {"type": "dismiss_popup", "retries": 3},
            {"type": "wait_stable", "timeout": 5, "stable_duration": 0.5},
            # Open search (try content-desc "Search" → fallback to tap_position search_bar)
            {
                "type": "if_element",
                "by": "content-desc",
                "value": "Search",
                "timeout": 5,
                "then": [
                    {
                        "type": "tap_selector",
                        "by": "content-desc",
                        "value": "Search",
                        "timeout": 4,
                    }
                ],
                "else": [{"type": "tap_position", "pos": "search_bar"}],
            },
            {"type": "wait_stable", "timeout": 4, "stable_duration": 0.4},
            # Type hashtag (assumes search input is focused after tap)
            {"type": "input_text", "text": "#${HASHTAG}", "via": "u2"},
            {"type": "key", "key": "enter"},
            {"type": "wait_stable", "timeout": 5, "stable_duration": 0.5},
            # Select Videos tab
            {
                "type": "if_element",
                "by": "text",
                "value": "Videos",
                "timeout": 5,
                "then": [
                    {"type": "tap_selector", "by": "text", "value": "Videos", "timeout": 4}
                ],
            },
            {"type": "wait_stable", "timeout": 3, "stable_duration": 0.4},
            # Tap first video to enter full-screen player
            {"type": "tap_ratio", "x": 0.25, "y": 0.45},
            {"type": "wait_stable", "timeout": 4, "stable_duration": 0.4},
            # Browse videos
            {
                "type": "repeat",
                "count": "${BROWSE_COUNT}",
                "steps": [
                    # Watch for random duration
                    {
                        "type": "set_variable",
                        "name": "_VIEW",
                        "from_list": [5, 8, 10, 14, 18, 22],
                    },
                    {"type": "wait", "seconds": "${_VIEW}"},
                    # Like with probability
                    {
                        "type": "random_pick",
                        "branches": [
                            {
                                "weight": "${LIKE_WEIGHT}",
                                "steps": [
                                    {
                                        "type": "if_element",
                                        "by": "content-desc",
                                        "value": "Like",
                                        "timeout": 1,
                                        "then": [
                                            {
                                                "type": "tap_selector",
                                                "by": "content-desc",
                                                "value": "Like",
                                                "timeout": 2,
                                            }
                                        ],
                                    }
                                ],
                            },
                            {"weight": 70, "steps": []},
                        ],
                    },
                    # Swipe up to next
                    {
                        "type": "swipe_ratio",
                        "x1": 0.5,
                        "y1": 0.78,
                        "x2": 0.5,
                        "y2": 0.22,
                        "duration_ms": 250,
                    },
                    {"type": "wait_stable", "timeout": 3, "stable_duration": 0.3},
                ],
            },
        ],
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# DF-006: Utility Templates
# ─────────────────────────────────────────────────────────────────────────────

_UTILITY_TEMPLATES: List[Dict[str, Any]] = [
    # ── dismiss_all_setup ───────────────────────────────────────────────────
    {
        "name": "dismiss_all_setup",
        "category": "utility",
        "description": (
            "Đóng tất cả popup, dialog setup, permission request khi mới mở app. "
            "Lặp 5 lần: dismiss_popup + tap Skip/Not now/Maybe later/Allow/Close nếu có. "
            "Chạy ngay sau launch_app trên device mới hoặc sau update app. "
            "Sau khi xong, màn hình sẽ ở trạng thái ổn định (wait_stable)."
        ),
        "tags": "utility,popup,setup,cleanup,startup,permission",
        "variables": {},
        "steps": [
            {
                "type": "repeat",
                "count": 5,
                "delay_between": 1.5,
                "steps": [
                    {"type": "dismiss_popup"},
                    {
                        "type": "if_element",
                        "by": "text",
                        "value": "Skip",
                        "timeout": 1,
                        "then": [{"type": "tap_selector", "by": "text", "value": "Skip"}],
                    },
                    {
                        "type": "if_element",
                        "by": "text",
                        "value": "Not now",
                        "timeout": 1,
                        "then": [{"type": "tap_selector", "by": "text", "value": "Not now"}],
                    },
                    {
                        "type": "if_element",
                        "by": "text",
                        "value": "Maybe later",
                        "timeout": 1,
                        "then": [
                            {"type": "tap_selector", "by": "text", "value": "Maybe later"}
                        ],
                    },
                    {
                        "type": "if_element",
                        "by": "text",
                        "value": "Allow",
                        "timeout": 1,
                        "then": [{"type": "tap_selector", "by": "text", "value": "Allow"}],
                    },
                    {
                        "type": "if_element",
                        "by": "text",
                        "value": "Close",
                        "timeout": 1,
                        "then": [{"type": "tap_selector", "by": "text", "value": "Close"}],
                    },
                ],
            },
            {"type": "wait_stable", "timeout": 4, "stable_duration": 0.5},
        ],
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# Aggregate list
# ─────────────────────────────────────────────────────────────────────────────

BUILTIN_TEMPLATES: List[Dict[str, Any]] = (
    _GENERIC_TEMPLATES
    + _FACEBOOK_TEMPLATES
    + _TIKTOK_TEMPLATES
    + _UTILITY_TEMPLATES
)


async def seed_builtin_templates(db) -> int:
    """
    Insert BUILTIN_TEMPLATES that don't already exist.

    Returns the number of templates inserted (0 if all already exist).
    Idempotent: uses get_template_by_name to skip existing entries.
    """
    from db.crud.scenario_template import create_template, get_template_by_name

    inserted = 0
    for spec in BUILTIN_TEMPLATES:
        existing = await get_template_by_name(db, spec["name"])
        if existing is not None:
            continue
        await create_template(
            db,
            name=spec["name"],
            description=spec.get("description", ""),
            category=spec.get("category", "general"),
            steps=spec.get("steps", []),
            variables=spec.get("variables", {}),
            tags=spec.get("tags", ""),
            is_builtin=True,
            user_id=None,
        )
        inserted += 1

    if inserted:
        await db.commit()

    return inserted
