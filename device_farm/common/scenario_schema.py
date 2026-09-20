

from __future__ import annotations

import re
from typing import Any, Dict, List

from common.node_catalog import apply_node_catalog_metadata, build_node_catalog

# Optional per-field typing for STEP_SCHEMA entries.
#
# A node entry may carry a "fields" dict alongside required/optional:
#
#   "fields": {
#       "wait_after": {"type": "number", "default": 2, "min": 0, "max": 300},
#       "pos":        {"type": "enum", "values": ["top_center", ...]},
#   }
#
# Supported types: string | number | boolean | enum (with "values") | json.
# Supported attributes: default, min, max, pattern, label_key, placeholder_key.
#
# label_key / placeholder_key are dotted paths under the frontend namespace
# `campaignsFeature.stepEditor` (e.g. "appLifecycle.packageLabel"). They resolve
# against the ~215 labels the editor already ships, so migrating a node mostly
# means pointing at wording that exists rather than writing new wording. A field
# with no label_key falls back to a humanised field name — that is why the key
# is optional. scripts/check-schema-field-i18n.mjs asserts every declared key
# exists in both en.json and vi.json; next-intl renders the raw key otherwise.
# Kept deliberately small — 70 nodes of plain dicts do not need JSON Schema and
# a codegen build step.
#
# A node with no "fields" key validates exactly as it did before, so this is
# additive: validate_step is on the save path of every scenario, campaign and
# template, and must not start rejecting what it accepted yesterday.
STEP_FIELD_TYPES = ("string", "number", "boolean", "enum", "json")

# Any value that still contains a ${VAR} token is resolved at run time, so it
# cannot be type-checked at save time. Passing it through is the only option
# that does not break every scenario that parameterises a timeout.
_VAR_TOKEN = "${"


def _is_deferred(value: Any) -> bool:
    return isinstance(value, str) and _VAR_TOKEN in value


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _enum_value(entry: Any) -> str:
    """An enum choice is a bare string, or {"value", "label_key"} when the
    editor needs its own wording for that option."""
    if isinstance(entry, dict):
        return str(entry.get("value") or "")
    return str(entry)


def _field_errors(prefix: str, name: str, spec: Dict[str, Any], value: Any) -> List[str]:
    """Check one present field against its spec. Absent fields are `required`'s job."""
    kind = str(spec.get("type") or "string")
    if _is_deferred(value):
        return []

    if kind == "number":
        number = _as_number(value)
        if number is None:
            return [f"{prefix} field {name!r} must be a number, got {value!r}"]
        errors: List[str] = []
        minimum, maximum = spec.get("min"), spec.get("max")
        if minimum is not None and number < float(minimum):
            errors.append(f"{prefix} field {name!r} must be >= {minimum}, got {value!r}")
        if maximum is not None and number > float(maximum):
            errors.append(f"{prefix} field {name!r} must be <= {maximum}, got {value!r}")
        return errors

    if kind == "boolean":
        if isinstance(value, bool):
            return []
        if isinstance(value, str) and value.strip().lower() in ("true", "false"):
            return []
        return [f"{prefix} field {name!r} must be a boolean, got {value!r}"]

    if kind == "enum":
        values = [_enum_value(v) for v in (spec.get("values") or [])]
        if not isinstance(value, str):
            return [f"{prefix} field {name!r} must be one of {tuple(values)}, got {value!r}"]
        if value.strip().lower() not in {v.lower() for v in values}:
            return [f"{prefix} field {name!r} must be one of {tuple(values)}, got {value!r}"]
        return []

    if kind == "json":
        if isinstance(value, (dict, list)):
            return []
        return [f"{prefix} field {name!r} must be an object or array, got {value!r}"]

    # string
    if not isinstance(value, str):
        return [f"{prefix} field {name!r} must be a string, got {value!r}"]
    pattern = spec.get("pattern")
    # Case-insensitive on purpose: these are format checks (url scheme, id
    # shape), and the frontend mirrors this with new RegExp(pattern, 'i').
    if pattern and value.strip() and not re.match(pattern, value.strip(), re.IGNORECASE):
        return [f"{prefix} field {name!r} does not match {pattern!r}: {value!r}"]
    return []

SCENARIO_STEP_TYPES = [
    "launch_app",
    "stop_app",
    "clear_app",
    "wait_app",
    "push_file",
    "pull_file",
    "open_url",
    "install_apk",
    "wait",
    "tap_position",
    "tap_ratio",
    "tap_image",
    "swipe_ratio",
    "tap",
    "tap_selector",
    "tap_xml_match",
    "wait_element",
    "assert_element",
    "input_selector",
    "long_tap_selector",
    "scroll_to",
    "input_text",
    "login_if_needed",
    "platform_session_gate",
    "fill_form",
    "assert_app_state",
    "key",
    "adb_shell",
    "scroll_down",
    "wait_stable",
    "verify_screen",
    "dismiss_popup",
    "set_variable",
    "repeat",
    "repeat_until",
    "if_element",
    "if_variable",
    "social_open_comments",
    "social_find_comment_button",
    "social_tap_comment_target",
    "social_apply_comment_filter",
    "social_select_target",
    "social_connect_visible_people",
    "social_scan_posts_interact",
    "social_open_author_from_post_match",
    "social_open_commenter_from_post_match",
    "social_sync_connections",
    "content_interaction",
    "connection_request",
    "lease_connection_candidate",
    "lease_source_target",
    "community_membership",
    "random_pick",
    "run_scenario",
    "use_source_pool",
    "extract",
    "loop",
    "break_if",
    "extract_text_hierarchy",
    "extract_text_ocr",
    "extract_text_ai",
    "extract_screen_data",
    "save_extraction",
    "double_tap",
    "pinch",
    "drag",
    "take_screenshot",
    "set_clipboard",
]

_STEP_SCHEMA_BASE: Dict[str, Dict[str, Any]] = {
    "launch_app": {
        "required": ["package"],
        "optional": [
            "wait_after",
            "activity",
            "component",
            "stop_before",
            "use_monkey",
            "package_fallbacks",
            "adb_fallback",
        ],
        "description": "Open app by package. Optional activity/component, stop_before, use_monkey. wait_after (default 2s).",
    },
    "stop_app": {
        "required": ["package"],
        "optional": [],
        "description": "Force-stop app (am force-stop / u2 stopPackage).",
    },
    "clear_app": {
        "required": ["package"],
        "optional": [],
        "description": "Clear app data (pm clear). Removes login state.",
    },
    "wait_app": {
        "required": ["package"],
        "optional": ["timeout", "front"],
        "description": "Wait until app is in foreground (default timeout 20s).",
    },
    "push_file": {
        "required": ["local_path", "remote_path"],
        "optional": ["mode"],
        "description": "Push local file to device path (requires agent-boot u2 session).",
    },
    "pull_file": {
        "required": ["local_path", "remote_path"],
        "optional": [],
        "description": "Pull device file to local path (requires agent-boot u2 session).",
    },
    "open_url": {
        "required": ["url"],
        "optional": ["package"],
        "description": "Mở URL. package (optional): e.g. com.android.chrome để ép mở bằng app đó.",
    },
    "install_apk": {
        "required": ["url"],
        "optional": ["timeout"],
        "description": (
            "Install APK on the device. url accepts http(s), absolute local path, "
            "or ${VARIABLE}. timeout defaults to 90s."
        ),
    },
    "wait": {
        "required": [],
        "optional": ["seconds"],
        "description": "Tạm dừng cố định (giây). Ưu tiên dùng wait_element thay thế.",
    },
    "tap_position": {
        "required": ["pos"],
        "optional": [],
        "description": "Tap tại vị trí logic: top_center | middle_center | bottom_center | search_bar.",
    },
    "tap": {
        "required": [],
        "optional": ["selector", "fallback", "screen", "timeout", "implicit_wait"],
        "description": (
            "⚡ Unified tap step (recorded by control-record-view). "
            "selector: {by, value} — uiautomator2 element find. "
            "fallback: {rx, ry} — ratio tap if selector fails. "
            "screen: {package, hash, texts, screenshot, element_image, screenshot_anchor} — "
            "context captured at record time. "
            "screen.screenshot_anchor: {image: base64, region: {rx, ry, rw, rh}} — "
            "ROI crop around tap point for faster image matching (optional). "
            "implicit_wait: number (timeout secs) or {timeout, poll} — "
            "Tenacity retry-until-visible before tapping (default 10s/0.5s poll). "
            "Executor: retry-find-element → image match (ROI→full) → fallback ratio → ok."
        ),
    },
    "tap_ratio": {
        "required": ["x", "y"],
        "optional": [],
        "description": "Tap tại tỷ lệ màn hình (0–1). Fallback khi không có selector.",
    },
    "tap_image": {
        "required": ["template_key"],
        "optional": [
            "threshold", "scale", "template_screen_w", "template_screen_h",
            "timeout", "poll",
        ],
        "description": (
            "Tap vào vị trí khớp ảnh mẫu trên màn hình. "
            "template_key: khoá ảnh trong object storage (cắt từ màn hình lúc thiết kế). "
            "threshold: ngưỡng khớp 0–1 (mặc định 0.8; khớp thật thường 0.96–1.00). "
            "scale: tỷ lệ thu nhỏ khi tìm (mặc định 0.25 — nhanh hơn ~70 lần mà không giảm độ chính xác). "
            "template_screen_w/h: kích thước màn lúc cắt, để hiệu chỉnh khi máy khác độ phân giải. "
            "Khớp chạy trên agent-boot; mỗi lần thử tốn 1 ảnh chụp + ~11ms so khớp."
        ),
    },
    "swipe_ratio": {
        "required": ["x1", "y1", "x2", "y2"],
        "optional": ["duration_ms"],
        "description": "Swipe giữa hai điểm tỷ lệ (0–1). duration_ms mặc định 300.",
    },
    "tap_selector": {
        "required": [],
        "required_any": [["selector", "by"], ["selector", "value"]],
        "optional": [
            "selector", "by", "value", "fallback", "fallback_rx", "fallback_ry",
            "timeout", "implicit_wait", "element_image",
        ],
        "description": (
            "Tap theo uiautomator2 selector. "
            "selector: {by, value, conditions?, instance?, chain?} (canonical) hoặc legacy by/value. "
            "conditions: AND fields (className, resourceId, clickable, …). "
            "chain: child | sibling | relative | child_by_text | child_by_description. "
            "fallback / fallback_rx/ry: tọa độ ratio khi không tìm thấy element."
        ),
    },
    "tap_xml_match": {
        "required": [],
        "required_any": [["contains", "equals", "value"]],
        "optional": ["attr", "by", "contains", "equals", "value", "clickable", "timeout", "poll"],
        "description": (
            "Dump UI XML fresh, find first node by attr contains/equals, then tap center from bounds. "
            "Useful for Facebook result rows whose u2 selector surface is unstable."
        ),
    },
    "content_interaction": {
        "required": [],
        "optional": [
            "platform", "action", "timeout", "poll", "verify_timeout",
            "settle_seconds", "save_as", "require_verified_target",
            "comment_text",
            "require_completion", "completion_steps", "completion_verify",
            "candidate_entity_id", "require_candidate_status",
            "candidate_lease_token", "account_action_id",
        ],
        "description": "Interact with content on the current screen through a platform adapter. Supported actions come from the provider capability registry.",
    },
    "connection_request": {
        "required": [],
        "optional": [
            "platform", "action", "timeout", "poll", "verify_timeout",
            "settle_seconds", "save_as", "require_verified_target",
            "require_completion", "completion_steps", "completion_verify",
            "candidate_entity_id", "require_candidate_status", "candidate_lease_token",
            "account_action_id",
        ],
        "description": "Send an idempotent connection request on the current profile screen; use require_verified_target to bind it to a resolver result.",
    },
    "lease_connection_candidate": {
        "required": [],
        "optional": ["platform"],
        "description": "Atomically lease the highest-ranked ready connection candidate for the bound account; request discovery when none is ready.",
    },
    "lease_source_target": {
        "required": [],
        "optional": [
            "platform", "entity_type", "action_type", "action",
            "statuses", "keywords", "search",
        ],
        "description": "Atomically reserve the next unused device target for the bound account and action.",
    },
    "social_select_target": {
        "required": [],
        "optional": [
            "platform", "target_type",
            "search", "display_name", "display_text", "row_text",
            "required_keywords", "optional_keywords",
            "forbidden_keywords", "min_score", "require_unique", "timeout",
            "profile_wait_s", "detail_wait_s", "current_detail",
            "save_as", "save_success_as", "skip_candidate_on_not_verified",
            "candidate_entity_id", "candidate_lease_token", "skip_candidate_defer_hours",
        ],
        "description": (
            "Agent-boot resolver: score search results for the platform, open one "
            "verified target, and save the target proof. target_type: 'person' "
            "(default, uses display_name/profile_wait_s) or 'post' (uses "
            "display_text/detail_wait_s/current_detail). platform defaults to facebook."
        ),
    },
    "social_connect_visible_people": {
        "required": [],
        "optional": [
            "platform", "min_score", "require_common", "common_keywords",
            "forbidden_keywords", "timeout", "verify_wait_s", "save_as",
            "account_action_id", "open_surface", "target_count", "batch_size",
            "max_scrolls", "no_more_common_limit", "dry_run", "scroll_wait_s",
            "surface_wait_s", "stop_on_unverified",
        ],
        "description": "Agent-boot flow: open the platform friend suggestions, scan visible Add Friend rows, require common-context score, send verified requests in a bounded batch, and ledger each request.",
    },
    "social_scan_posts_interact": {
        "required": [],
        "optional": [
            "platform", "keywords", "match_mode", "comment_text", "target_count",
            "batch_size", "max_scrolls", "timeout", "scroll_x_ratio",
            "scroll_y1_ratio", "scroll_y2_ratio", "scroll_duration_s",
            "scroll_wait_s", "comment_wait_s", "submit_wait_s",
            "require_comment", "like_post", "save_as",
        ],
        "description": (
            "Agent-boot flow: scan visible feed/group posts, match configured "
            "keywords, then optionally like and comment on matched posts."
        ),
    },
    "social_open_author_from_post_match": {
        "required": [],
        "optional": [
            "platform", "source_var", "action_index", "search", "display_name",
            "required_keywords", "optional_keywords", "forbidden_keywords",
            "required_keywords_var", "optional_keywords_var", "forbidden_keywords_var",
            "min_score", "timeout", "comment_wait_s", "profile_wait_s",
            "max_commenters", "save_as", "save_success_as", "save_opened_as",
            "save_sheet_opened_as",
        ],
        "description": (
            "Platform adapter flow: open the author profile from a previously matched "
            "post action, verify profile suitability, and save target proof."
        ),
    },
    "social_open_commenter_from_post_match": {
        "required": [],
        "optional": [
            "platform", "source_var", "action_index", "search", "display_name",
            "required_keywords", "optional_keywords", "forbidden_keywords",
            "required_keywords_var", "optional_keywords_var", "forbidden_keywords_var",
            "min_score", "timeout", "comment_wait_s", "profile_wait_s",
            "max_commenters", "save_as", "save_success_as", "save_opened_as",
            "save_sheet_opened_as",
        ],
        "description": (
            "Platform adapter flow: open comments for a previously matched feed post, "
            "open a commenter profile, verify suitability, and save target proof."
        ),
    },
    "social_sync_connections": {
        "required": [],
        "optional": ["platform", "metric", "timeout", "persist", "save_as"],
        "description": (
            "Read how many connections the account has from the screen it is on, "
            "publish ACCOUNT_FRIEND_COUNT/ACCOUNT_STAGE for branching, and record "
            "the observation so growth is measurable."
        ),
    },
    "community_membership": {
        "required": [],
        "optional": [
            "platform", "action", "timeout", "poll", "verify_timeout",
            "settle_seconds", "save_as", "require_verified_target",
            "require_completion", "completion_steps", "completion_verify",
            "candidate_entity_id", "require_candidate_status", "candidate_lease_token",
            "account_action_id",
        ],
        "description": "Join the community on the current screen and verify member or pending state.",
    },
    "wait_element": {
        "required": [],
        "required_any": [["selector", "by"], ["selector", "value"]],
        "optional": ["selector", "by", "value", "timeout", "poll"],
        "description": (
            "⚡ PREFERRED thay cho 'wait N giây'. "
            "Poll liên tục cho đến khi element xuất hiện (mặc định timeout=10s). "
            "Dùng sau launch_app, open_url, hay bất kỳ bước nào khiến màn hình thay đổi. "
            "by: text | resource-id | xpath."
        ),
    },
    "assert_element": {
        "required": [],
        "required_any": [["selector", "by"], ["selector", "value"]],
        "optional": ["selector", "by", "value", "timeout", "poll"],
        "description": (
            "✓ Xác nhận element đang hiển thị. Fail scenario ngay nếu không thấy element. "
            "Dùng để kiểm tra đang đúng màn hình trước khi thao tác tiếp. "
            "timeout mặc định 5s."
        ),
    },
    "input_selector": {
        "required": ["text"],
        "required_any": [["selector", "by"], ["selector", "value"]],
        "optional": ["selector", "by", "value", "clear_first", "implicit_wait"],
        "description": (
            "Tìm input field theo selector, xóa nội dung cũ (clear_first=true mặc định), "
            "rồi gõ text. implicit_wait: Tenacity retry-until-visible (default 10s/0.5s poll). "
            "by: resource-id (ưu tiên) | text | xpath."
        ),
    },
    "long_tap_selector": {
        "required": [],
        "required_any": [["selector", "by"], ["selector", "value"]],
        "optional": ["selector", "by", "value", "duration_ms", "implicit_wait"],
        "description": (
            "Long press element tìm theo selector. duration_ms mặc định 800ms. "
            "implicit_wait: Tenacity retry-until-visible (default 10s/0.5s poll)."
        ),
    },
    "scroll_to": {
        "required": [],
        "required_any": [["selector", "by"], ["selector", "value"]],
        "optional": [
            "selector",
            "by",
            "value",
            "direction",
            "max_swipes",
            "scroll_duration_s",
            "scroll_settle_s",
            "scroll_step_ratio",
            "scroll_to_timeout_s",
            "timeout",
        ],
        "description": (
            "Scroll (swipe) cho đến khi element xuất hiện. "
            "direction: down (mặc định) | up. max_swipes mặc định 5."
        ),
    },
    "input_text": {
        # `via` has a Pydantic default; requiring it here rejected steps the API
        # accepts.
        "required": ["text"],
        "optional": ["via", "clear_first"],
        "description": (
            "Gõ text vào element đang focused. via: u2. clear_first=true để xóa "
            "nội dung cũ trước khi gõ. Ưu tiên dùng input_selector khi có selector."
        ),
    },
    "login_if_needed": {
        "required": [],
        "optional": ["profile", "clear_first", "implicit_wait"],
        "description": (
            "Profile-driven login. Detects logged-in state first, fills login_recipe fields from "
            "account/scenario/variables/secret references, then submits. Optional "
            "login_recipe.post_submit_actions can navigate intermediate 2FA screens before "
            "post_submit_fields such as account.totp_code are entered."
        ),
    },
    "platform_session_gate": {
        "required": [],
        "optional": ["phase", "timeout", "poll_interval"],
        "description": (
            "Account-scoped platform session gate. preflight reuses only a matching trusted "
            "session or requests login; confirm establishes provenance after this run logged in."
        ),
    },
    "fill_form": {
        "required": [],
        "optional": ["profile", "recipe", "form", "clear_first", "implicit_wait"],
        "description": "Fill a named form recipe from an app automation profile.",
    },
    "assert_app_state": {
        "required": [],
        "optional": ["profile", "package", "any_text", "all_text", "not_text", "locator"],
        "description": "Assert current app state using package/text checks and optional semantic locator.",
    },
    "key": {
        "required": ["key"],
        "optional": [],
        "description": "Phím: enter, back, home, ...",
    },
    "adb_shell": {
        "required": ["command"],
        "optional": ["timeout", "fail_on_error", "save_as", "max_output_chars"],
        "description": (
            "Chạy lệnh `adb shell` trên phone thật thông qua agent-boot. "
            "command hỗ trợ biến ${VAR}; timeout được giới hạn để tránh treo worker. "
            "save_as lưu output vào biến runtime để dùng ở bước sau. "
            "max_output_chars giới hạn output giữ trong kết quả/context."
        ),
    },
    "scroll_down": {
        "required": [],
        "optional": [
            "repeats",
            "start_x_ratio",
            "start_y_ratio",
            "end_y_ratio",
            "duration_ms",
            "pause_seconds",
            "smart_scroll",
        ],
        "description": (
            "Vuốt xuống N lần (mặc định 1). "
            "start_x_ratio (0–1, mặc định 0.5): neo ngang — dùng ~0.15–0.25 để tránh vuốt xuyên ảnh full-width ở giữa feed Facebook. "
            "start_y_ratio/end_y_ratio/duration_ms/pause_seconds: tinh chỉnh gesture."
        ),
    },
    "wait_stable": {
        "required": [],
        "optional": ["timeout", "stable_duration"],
        "description": (
            "Chờ UI ngừng thay đổi (animation/transition xong). "
            "timeout: tối đa N giây chờ (mặc định 5.0). "
            "stable_duration: UI phải đứng yên bao lâu (mặc định 0.4s). "
            "Dùng sau swipe, mở tab mới, hay bất kỳ animation nào trước khi tap."
        ),
    },
    "verify_screen": {
        "required_any": [["template_key", "screenshot"]],
        "optional": [
            "template_key",
            "screenshot",
            "template_screen_w",
            "template_screen_h",
            "ssim_threshold",
            "platform",
            "timeout",
            "poll",
        ],
        "description": (
            "Visual Anchoring: so sánh SSIM giữa ảnh chụp lúc record và màn hình hiện tại. "
            "template_key: object-storage key của ảnh mẫu đã cắt/upload; screenshot: legacy base64 JPEG. "
            "ssim_threshold (0-1, default 0.75). "
            "timeout: chờ tối đa N giây cho màn hình khớp (default 8s). "
            "poll: tần suất kiểm tra (default 0.5s). Fail nếu SSIM dưới threshold."
        ),
    },
    "dismiss_popup": {
        "required": [],
        "optional": ["retries"],
        "description": (
            "Tự động đóng popup/dialog đang hiển thị (permission request, update prompt, quảng cáo). "
            "retries: thử tối đa N lần (mặc định 3). "
            "Dùng sau launch_app hoặc bất kỳ lúc nào có khả năng xuất hiện dialog bất ngờ."
        ),
    },
    "set_variable": {
        "required": ["name"],
        "optional": ["value", "from_list", "from_list_index", "increment"],
        "description": (
            "Đặt hoặc cập nhật một runtime variable để dùng trong các step sau với ${NAME}. "
            "value: giá trị cụ thể (hỗ trợ ${VAR} interpolation). "
            "from_list: chọn 1 phần tử từ danh sách; mặc định chọn ngẫu nhiên. "
            "from_list_index: nếu có, chọn phần tử theo index sau khi resolve (ví dụ ${_loop_iter}). "
            "increment: tăng counter thêm N (bắt đầu từ 0 nếu chưa có). "
            "Chỉ dùng 1 trong 3 tùy chọn trên; 'value' là mặc định."
        ),
    },
    "repeat": {
        "required": ["count", "steps"],
        "optional": ["delay_between"],
        "description": (
            "Lặp lại danh sách steps con N lần. "
            "count: số lần lặp (int). "
            "delay_between: thời gian chờ giữa các lần lặp (seconds, mặc định 0). "
            "${__LOOP_INDEX__} được set tự động (0-based) trong mỗi lần lặp."
        ),
    },
    "repeat_until": {
        "required": ["condition", "steps"],
        "optional": ["max_iterations"],
        "description": (
            "Lặp lại steps cho đến khi điều kiện thỏa mãn (dừng). "
            "max_iterations: giới hạn an toàn (mặc định 100). "
            "condition keys: element_exists | element_not_exists | variable_equals. "
            "Ví dụ: {\"element_exists\": {\"by\": \"text\", \"value\": \"End of feed\"}}."
        ),
    },
    "if_element": {
        "required": ["then"],
        "required_any": [["selector", "by"], ["selector", "value"]],
        "optional": ["selector", "by", "value", "timeout", "else"],
        "description": (
            "Rẽ nhánh theo sự tồn tại của element. "
            "selector hoặc by/value; chain/conditions hỗ trợ như tap_selector."
        ),
    },
    "if_variable": {
        "required": ["name", "then"],
        "optional": ["equals", "not_equals", "contains", "greater_than", "else"],
        "description": (
            "Re nhánh theo giá trị của variable. "
            "name: tên variable (không cần ${...}). "
            "Điều kiện: equals | not_equals | contains | greater_than. "
            "Nếu không có điều kiện → branch theo truthy (var có giá trị). "
            "then: steps chạy khi đúng. else: steps chạy khi sai (optional)."
        ),
    },
    "social_find_comment_button": {
        "required": [],
        "optional": [
            "platform",
            "timeout",
            "poll",
            "dedupe_field",
            "ignore_error",
            "switch_to_all_comments",
            "comment_filter",
        ],
        "description": (
            "Find the visible comment button for the current post and "
            "cache its target without tapping. Use before social_tap_comment_target."
        ),
    },
    "social_tap_comment_target": {
        "required": [],
        "optional": ["platform", "ignore_error", "post_tap_wait_s"],
        "description": (
            "Tap the cached comment target from social_find_comment_button, "
            "verify the comment sheet opened, and set parent context for following entity=comments extraction."
        ),
    },
    "social_apply_comment_filter": {
        "required": [],
        "optional": [
            "platform",
            "switch_to_all_comments",
            "comment_filter",
            "comment_filter_settle_s",
            "comment_filter_step_pause_s",
            "comment_filter_post_select_s",
        ],
        "description": (
            "Apply the comment sheet filter. "
            "comment_filter: most_relevant | newest | all_comments, or none to skip."
        ),
    },
    "social_open_comments": {
        "required": [],
        "optional": [
            "platform",
            "timeout",
            "poll",
            "dedupe_field",
            "ignore_error",
            "switch_to_all_comments",
            "comment_filter",
            "post_tap_wait_s",
            "comment_filter_settle_s",
            "require_post_before_comment",
            "pre_scroll",
            "pre_scroll_distance",
            "pre_scroll_duration_ms",
            "pre_scroll_x_ratio",
            "pre_scroll_start_y_ratio",
            "pre_scroll_end_y_ratio",
            "pre_scroll_pause_s",
            "then",
            "else",
        ],
        "description": (
            "Atomic step: tìm + tap nút 'Bình luận' topmost trong feed, "
            "tự set parent context cho extract entity=comments. "
            "platform: mặc định facebook. "
            "then: steps chạy khi tap thành công. else: chạy khi không tap được. "
            "comment_filter: most_relevant | newest | all_comments (hoặc none để giữ mặc định của app). "
            "Legacy switch_to_all_comments=false tắt đổi filter; true (default) = all_comments."
        ),
    },
    "random_pick": {
        "required": ["branches"],
        "optional": [],
        "description": (
            "Chọn ngẫu nhiên 1 nhánh để thực thi (weighted random). "
            "branches: list các nhánh, mỗi nhánh có steps (required) và weight (optional, mặc định 1). "
            "Weight cao hơn = xác suất được chọn cao hơn. "
            "Ví dụ: [{\"weight\": 3, \"steps\": [...]}, {\"weight\": 1, \"steps\": [...]}]."
        ),
    },
    "run_scenario": {
        "required": [],
        "required_any": [["scenario_id", "scenario_name"]],
        "optional": ["scenario_id", "scenario_name", "variables"],
        "description": (
            "Gọi một sub-scenario khác (flow composition). "
            "scenario_id: UUID của scenario trong cùng campaign. "
            "scenario_name: tên scenario (tìm trong campaign trước, rồi trong template library). "
            "variables: dict override variables cho sub-scenario (optional). "
            "Yêu cầu một trong hai: scenario_id hoặc scenario_name. "
            "Circular reference và max depth (10) được tự động bảo vệ."
        ),
    },
    "use_source_pool": {
        "required": [],
        "optional": [
            "platform",
            "entity_type",
            "search",
            "output_prefix",
            "statuses",
            "allocation_policy",
        ],
        "description": (
            "Khai báo nguồn dữ liệu dùng cho campaign dispatch. "
            "Mặc định dùng external_entities facebook/group đã cào; "
            "mỗi device nhận một nguồn qua biến TARGET_* và alias theo output_prefix."
        ),
    },
    "extract": {
        "required": ["entity"],
        "optional": [
            "stop_if_no_new",
            "no_new_threshold",
            "edge_extra_data",
            "expand_see_more",
            "expand_see_more_max_passes",
            "expand_see_more_scroll",
            "expand_see_more_scroll_distance",
            "expand_completion_retries",
            "extract_profile",
            "open_post_before_extract",
            "open_post_press_back_after_extract",
            "require_open_post_detail",
            "entity_version",
            "collection",
            "platform",
            "content_type",
            "dedupe_field",
            "tags",
            "extract_var",
            "save_parent_id_var",
            "parent_id_var",
            "parent_post_id_var",
            "item_level",
            "max_items",
            "comment_scroll_passes",
            "comment_swipes_per_dump",
            "comment_scroll_distance",
            "comment_scroll_duration_ms",
            "comment_scroll_pause_s",
            "comment_scroll_wall_s",
            "comment_require_complete",
            "comment_auto_coverage_target_max",
            "allow_partial_comments",
            "comment_no_growth_break",
            "min_comment_scan_passes",
            "comment_max_snapshots",
            "comment_stop_if_no_new",
            "comment_no_new_threshold",
        ],
        "description": (
            "Extract content data từ XML màn hình hiện tại qua agent-boot extra-data. "
            "entity: 'posts' — parse post card (author/text/timestamp/reactions/"
            "comments/shares/post_type/image_desc/comment_preview); "
            "'comments' — parse comment rows + stats trong comment view/feed preview; "
            "'groups'/'pages' — cào kết quả tìm kiếm và lưu vào external entity catalog; "
            "'text_nodes' — thu thập text node vào context['text_nodes']. "
            "platform: facebook|instagram|tiktok|linkedin, hoặc 'auto' (mặc định) để "
            "agent-boot tự nhận diện parser theo app đang mở. "
            "extract_profile: balanced|aggressive|safe hoặc ${VAR} (áp defaults scan params). "
            "entity_version: lock behavior parser/runtime (vd: comments:v1). "
            "stop_if_no_new (bool, default False): set ctx['_break']=True khi không có bài mới "
            "trong no_new_threshold (default 3) lần scroll liên tiếp — dùng bên trong step 'loop'. "
            "expand_see_more (bool, default True): tự tap nút 'See more'/'Xem thêm' trước khi parse. "
            "open_post_before_extract (entity=posts): mở màn chi tiết bài trước extract. "
            "open_post_press_back_after_extract: tự Back sau extract; với entity=comments chỉ back khi còn ở comment sheet. "
            "entity=comments supports bounded crawl tuning: max_items, comment_scroll_passes, "
            "comment_swipes_per_dump, comment_max_snapshots, comment_scroll_wall_s. "
            "Nếu set collection/platform/content_type/dedupe_field thì agent-boot sẽ ghi trực tiếp "
            "vào content DB. "
            "⚠ Dùng với step 'loop' (không phải 'repeat') để stop_if_no_new hoạt động."
        ),
    },
    "loop": {
        "required": ["steps"],
        "optional": [
            "count",
            "count_min",
            "count_max",
            "delay_between_min",
            "delay_between_max",
            "while",
            "max_iterations",
            "loop_var",
            "duration_seconds",
            "stall_after",
            "idle_delay_seconds",
        ],
        "description": (
            "Lặp lại steps theo count hoặc while-condition. "
            "count: số lần lặp cố định (chạy đúng N lần, không bị max_iterations cắt). "
            "count_min + count_max: số vòng ngẫu nhiên trong khoảng, bốc 1 lần mỗi lần "
            "vào loop — ĐÈ LÊN count (phải khai cả hai, nếu chỉ khai 1 thì step lỗi config). "
            "delay_between_min + delay_between_max: nghỉ ngẫu nhiên bấy nhiêu giây sau mỗi "
            "vòng (0–300, bốc lại mỗi vòng, không nghỉ sau vòng cuối). "
            "duration_seconds: nếu > 0, dừng loop khi hết thời lượng kể cả chưa hết count. "
            "while: condition dict (element_exists | variable_equals) — lặp khi condition đúng. "
            "max_iterations: giới hạn an toàn chỉ khi dùng while (không có count, default 100). "
            "loop_var: tên biến runtime nhận index hiện tại để nested loop không ghi đè nhau. "
            "stall_after: dừng sau N vòng liên tiếp không thao tác được gì (0 = tắt). "
            "idle_delay_seconds: chờ bấy nhiêu giây sau một vòng không thao tác (0–300). "
            "⚠ Vòng lặp dài có thể dừng sớm với reason_code=loop_history_limit khi run "
            "hết ngân sách event history — các vòng đã xong vẫn được giữ. "
            "Khác 'repeat': 'loop' kiểm tra ctx['_break'] sau mỗi vòng — cho phép step 'extract' "
            "với stop_if_no_new=True dừng sớm, hoặc step 'break_if' dừng khi đủ điều kiện. "
            "${__LOOP_INDEX__} = chỉ số vòng lặp hiện tại (0-based)."
        ),
    },
    "break_if": {
        "required": ["condition"],
        "optional": [],
        "description": (
            "Dừng vòng lặp 'loop' bao ngoài khi condition thỏa mãn. "
            "condition keys: "
            "{'type': 'posts_count_gte', 'count': N} — dừng khi ctx['posts'] đạt N bài. "
            "{'element_exists': {'by': ..., 'value': ...}} — dừng khi element xuất hiện. "
            "{'variable_equals': {'name': ..., 'value': ...}} — dừng khi variable đạt giá trị. "
            "⚠ Chỉ hoạt động bên trong step 'loop' (không phải 'repeat' hay 'repeat_until')."
        ),
    },
    "extract_text_hierarchy": {
        "required": ["save_as"],
        "optional": ["filter_class", "exclude_empty", "format"],
        "description": (
            "Extract text from UI Hierarchy XML (free, fastest, native views only). "
            "save_as: variable name to store result. "
            "format: 'text' (plain) or 'json' (structured with bounds/class/resource_id). "
            "filter_class: list of Android widget classes to include (null = all)."
        ),
    },
    "extract_text_ocr": {
        "required": ["save_as"],
        "optional": [
            "region",
            "language",
            "psm",
            "preprocess",
            "scale_factor",
            "confidence_threshold",
        ],
        "description": (
            "Extract text from screenshot using Tesseract OCR. "
            "Works on WebView, Canvas, images — anything visible on screen. "
            "save_as: variable name. "
            "region: {x1, y1, x2, y2} as ratios 0-1 to crop before OCR. "
            "language: Tesseract lang code (e.g. 'eng', 'vie+eng'). "
            "psm: Page Segmentation Mode (3=auto, 6=block, 7=line, 11=sparse)."
        ),
    },
    "extract_text_ai": {
        "required": ["save_as", "prompt"],
        "optional": ["provider", "format", "model", "region"],
        "description": (
            "Extract structured data from screenshot using AI Vision (OpenAI/Gemini). "
            "save_as: variable name. "
            "prompt: extraction instruction for the AI. "
            "provider: 'openai' or 'gemini'. "
            "format: 'json' (parsed dict) or 'text' (raw string). "
            "Requires OPENAI_API_KEY or GEMINI_API_KEY env var."
        ),
    },
    "extract_screen_data": {
        "required": ["save_as"],
        "optional": ["schema", "strategy", "language"],
        "description": (
            "Smart extraction: tries hierarchy → OCR → AI Vision (auto fallback). "
            "save_as: variable name. "
            "strategy: 'auto' (fallback chain), 'hierarchy', 'ocr', 'ai'. "
            "schema: expected output fields (used to validate extraction completeness)."
        ),
    },
    "save_extraction": {
        "required": ["data_var"],
        "optional": [
            "collection",
            "platform",
            "content_type",
            "dedupe_field",
            "tags",
            "parent_id_var",
            "save_parent_id_var",
            "item_level",
            "dedup_action",
            "save_batch_size",
        ],
        "description": (
            "Save extracted data to content database with deduplication (DF-010). "
            "data_var: name of runtime variable containing the data (from extract_text_* or set_variable). "
            "collection: name of content collection (default: 'default'). "
            "dedupe_field: field in data to use for dedup hash (e.g. 'content'). "
            "parent_id_var (alias: save_parent_id_var): link children rows to parent hash from context. "
            "item_level: hierarchy level (0 post, 1 comment/reply). "
            "Data is saved to content_items table with SHA256 hash-based dedup."
        ),
    },
    "double_tap": {
        "required": [],
        "optional": ["x", "y", "rx", "ry", "wait_after"],
        "description": (
            "Double-tap at coordinates. rx/ry (0.0-1.0 relative) or x/y (absolute pixels). "
            "wait_after (float, default 0.5s). "
            "Requires TouchAccessibilityService or uiautomator2."
        ),
    },
    "pinch": {
        "required": ["scale"],
        "optional": ["cx", "cy", "rx", "ry", "duration_ms"],
        "description": (
            "Pinch/zoom gesture. scale>1 = zoom in (spread), scale<1 = zoom out (pinch). "
            "Center: cx/cy (absolute) or rx/ry (relative, default 0.5/0.5). "
            "duration_ms (default 400). Requires TouchAccessibilityService."
        ),
    },
    "drag": {
        "required": [],
        "optional": ["x1", "y1", "x2", "y2", "rx1", "ry1", "rx2", "ry2", "duration_ms"],
        "description": (
            "Drag-and-drop from point A to point B. "
            "Use rx1/ry1/rx2/ry2 for relative coords (0.0-1.0) or x1/y1/x2/y2 for absolute pixels. "
            "duration_ms (default 1000) — longer = more reliable hold detection."
        ),
    },
    "take_screenshot": {
        "required": [],
        "optional": ["save_path"],
        "description": (
            "Capture device screenshot. Result stored as base64 in step_result['screenshot']. "
            "Optional save_path: write JPEG to disk at that absolute path."
        ),
    },
    "set_clipboard": {
        "required": ["text"],
        "optional": [],
        "description": (
            "Set device clipboard text. Uses STFService → uiautomator2 → ADB broadcast fallback. "
            "After this step, use input_text or key(paste) to paste clipboard content."
        ),
    },
}

STEP_SCHEMA = apply_node_catalog_metadata(_STEP_SCHEMA_BASE)


def get_scenario_schema() -> Dict[str, Any]:
    from common.node_capabilities import build_node_capability_registry

    return {
        "description": "Scenario JSON dùng bởi device_farm MCP và run_scenario_task. AI phải output đúng format này.",
        "scenario": {
            "instructions": "string — câu lệnh gốc (giữ nguyên)",
            "steps": "array of step objects — thứ tự thực thi",
        },
        "step_types": SCENARIO_STEP_TYPES,
        "steps_schema": STEP_SCHEMA,
        "node_catalog": build_node_catalog(
            step_types=SCENARIO_STEP_TYPES,
            step_schema=STEP_SCHEMA,
        ),
        "node_capabilities": build_node_capability_registry(SCENARIO_STEP_TYPES, STEP_SCHEMA),
        "example_bad": {
            "instructions": "BAD: dùng wait cố định — fragile, không biết app đã load chưa",
            "steps": [
                {"type": "launch_app", "package": "com.example.app"},
                {"type": "wait", "seconds": 5},
                {"type": "tap_ratio", "x": 0.5, "y": 0.2},
                {"type": "wait", "seconds": 2},
            ],
        },
        "example_good": {
            "instructions": "GOOD: dùng u2 — chờ đúng element, gõ vào đúng field, tự động xử lý popup",
            "steps": [
                {"type": "launch_app", "package": "com.example.app", "wait_after": 3.0},
                # Dismiss permission/update dialogs that appear on first launch
                {"type": "dismiss_popup", "retries": 3},
                {"type": "wait_element", "by": "text", "value": "Đăng nhập", "timeout": 10},
                {"type": "assert_element", "by": "text", "value": "Chào mừng", "timeout": 5},
                {"type": "input_selector", "by": "resource-id", "value": "com.example.app:id/edit_email", "text": "user@email.com"},
                {"type": "input_selector", "by": "resource-id", "value": "com.example.app:id/edit_password", "text": "password123"},
                {"type": "tap_selector", "by": "text", "value": "Đăng nhập", "timeout": 5},
                # Wait for UI to fully settle after login (no fixed sleep needed)
                {"type": "wait_stable", "timeout": 5.0, "stable_duration": 0.4},
                {"type": "wait_element", "by": "text", "value": "Trang chủ", "timeout": 10},
            ],
        },
    }


# Envelope keys every step may carry regardless of node type: StepBase identity
# (api/schemas/scenario.py:74) plus the DSL contract fields normalize_step adds.
_STEP_ENVELOPE_KEYS = frozenset({
    "type",
    "id",
    "order",
    "title",
    "description",
    "config",
    "error_policy",
    "on_error",
    "retry",
    "pre_capture",
    "post_capture",
})


def unknown_step_fields(step: Dict[str, Any]) -> List[str]:
    """Keys this node's contract does not declare.

    A warning, never an error: both validators default to ``extra="ignore"``, so
    an unknown key has always been accepted and silently dropped. Telling the
    user beats failing a save that worked yesterday.

    Only raw runtime step types are checked. Dotted DSL family types
    ("interaction.tap") have no STEP_SCHEMA entry and are skipped rather than
    reported as one big unknown-field list.
    """
    if not isinstance(step, dict):
        return []
    schema = STEP_SCHEMA.get(str(step.get("type") or ""))
    if schema is None:
        return []
    declared = (
        set(schema.get("required") or ())
        | set(schema.get("optional") or ())
        | set(schema.get("fields") or ())
        | {name for group in schema.get("required_any") or () for name in group}
        | _STEP_ENVELOPE_KEYS
    )
    # "else" is a Python keyword, so the Pydantic models expose it as
    # `else_steps` with an alias. Both spellings reach here.
    if "else" in declared:
        declared.add("else_steps")
    return sorted(key for key in step if key not in declared)


def validate_step(step: Dict[str, Any], index: int) -> List[str]:
    errors: List[str] = []
    t = step.get("type")
    if not t:
        errors.append(f"step[{index}]: missing 'type'")
        return errors
    if t not in SCENARIO_STEP_TYPES:
        errors.append(f"step[{index}]: unknown type {t!r}. Allowed: {SCENARIO_STEP_TYPES}")
        return errors
    schema = STEP_SCHEMA.get(t, {})
    required = schema.get("required", [])
    for key in required:
        if key not in step or step[key] is None or (isinstance(step[key], str) and not step[key].strip()):
            errors.append(f"step[{index}]: type={t} missing required field {key!r}")
    for group in schema.get("required_any", []):
        if not any(
            key in step
            and step[key] is not None
            and not (isinstance(step[key], str) and not step[key].strip())
            for key in group
        ):
            errors.append(
                f"step[{index}]: type={t} requires one of {tuple(group)!r}"
            )
    # Typed field checks. Nodes with no "fields" entry are unaffected. This
    # replaced the two hardcoded per-type branches (open_url's url scheme,
    # tap_position's pos values) that were the only field typing there was.
    for name, spec in (schema.get("fields") or {}).items():
        if name not in step:
            continue
        value = step[name]
        if value is None:
            continue
        errors.extend(_field_errors(f"step[{index}]: type={t}", name, spec, value))
    return errors


def validate_scenario(scenario: Dict[str, Any]) -> List[str]:
    """
    Validate a scenario dict.

    Uses Pydantic models (api.schemas.scenario.ScenarioModel) for deep
    type checking of steps, variables, and nested structures.
    Falls back to the lightweight dict-based check if Pydantic import fails.
    """
    try:
        from api.schemas.scenario import ScenarioModel
        return ScenarioModel.validate_dict(scenario)
    except ImportError:
        pass

    # Fallback: lightweight validation (no Pydantic)
    errors: List[str] = []
    steps = scenario.get("steps")
    if not isinstance(steps, list):
        errors.append("scenario must have 'steps' as a non-empty array")
        return errors
    if not steps:
        errors.append("scenario.steps must not be empty")
        return errors
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            errors.append(f"step[{i}] must be an object")
            continue
        errors.extend(validate_step(step, i))
    return errors
