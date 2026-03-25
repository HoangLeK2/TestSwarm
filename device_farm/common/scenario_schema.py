

from __future__ import annotations

from typing import Any, Dict, List

SCENARIO_STEP_TYPES = [
    "launch_app",
    "open_url",
    "wait",
    "tap_position",
    "tap_ratio",
    "swipe_ratio",
    "tap",
    "tap_selector",
    "wait_element",
    "assert_element",
    "input_selector",
    "long_tap_selector",
    "scroll_to",
    "input_text",
    "key",
    "scroll_down",
    "wait_stable",
    "dismiss_popup",
]

STEP_SCHEMA: Dict[str, Dict[str, Any]] = {
    "launch_app": {
        "required": ["package"],
        "optional": ["wait_after"],
        "description": "Open app by package name. wait_after (float, default 2.5s) — wait for app to load before next step.",
    },
    "open_url": {
        "required": ["url"],
        "optional": ["package"],
        "description": "Mở URL. package (optional): e.g. com.android.chrome để ép mở bằng app đó.",
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
        "optional": ["selector", "fallback", "screen", "timeout"],
        "description": (
            "⚡ Unified tap step (recorded by control-record-view). "
            "selector: {by, value} — uiautomator2 element find. "
            "fallback: {rx, ry} — ratio tap if selector fails. "
            "screen: {package, hash, texts} — context captured at record time. "
            "Executor: try selector → fallback ratio → ok."
        ),
    },
    "tap_ratio": {
        "required": ["x", "y"],
        "optional": [],
        "description": "Tap tại tỷ lệ màn hình (0–1). Fallback khi không có selector.",
    },
    "swipe_ratio": {
        "required": ["x1", "y1", "x2", "y2"],
        "optional": ["duration_ms"],
        "description": "Swipe giữa hai điểm tỷ lệ (0–1). duration_ms mặc định 300.",
    },
    "tap_selector": {
        "required": ["by", "value"],
        "optional": ["fallback_rx", "fallback_ry", "timeout"],
        "description": (
            "Tap theo uiautomator2 selector. by: resource-id | text | xpath | class name. "
            "timeout (float, mặc định 5s): đợi element tối đa N giây trước khi fail. "
            "fallback_rx/ry: tọa độ ratio fallback nếu không tìm thấy element."
        ),
    },
    "wait_element": {
        "required": ["by", "value"],
        "optional": ["timeout"],
        "description": (
            "⚡ PREFERRED thay cho 'wait N giây'. "
            "Poll liên tục cho đến khi element xuất hiện (mặc định timeout=10s). "
            "Dùng sau launch_app, open_url, hay bất kỳ bước nào khiến màn hình thay đổi. "
            "by: text | resource-id | xpath."
        ),
    },
    "assert_element": {
        "required": ["by", "value"],
        "optional": ["timeout"],
        "description": (
            "✓ Xác nhận element đang hiển thị. Fail scenario ngay nếu không thấy element. "
            "Dùng để kiểm tra đang đúng màn hình trước khi thao tác tiếp. "
            "timeout mặc định 5s."
        ),
    },
    "input_selector": {
        "required": ["by", "value", "text"],
        "optional": ["clear_first"],
        "description": (
            "Tìm input field theo selector, xóa nội dung cũ (clear_first=true mặc định), "
            "rồi gõ text. Đáng tin cậy hơn tap_ratio + input_text. "
            "by: resource-id (ưu tiên) | text | xpath."
        ),
    },
    "long_tap_selector": {
        "required": ["by", "value"],
        "optional": ["duration_ms"],
        "description": "Long press element tìm theo selector. duration_ms mặc định 800ms.",
    },
    "scroll_to": {
        "required": ["by", "value"],
        "optional": ["direction", "max_swipes"],
        "description": (
            "Scroll (swipe) cho đến khi element xuất hiện. "
            "direction: down (mặc định) | up. max_swipes mặc định 5."
        ),
    },
    "input_text": {
        "required": ["text", "via"],
        "optional": [],
        "description": "Gõ text vào element đang focused. via: u2. Ưu tiên dùng input_selector.",
    },
    "key": {
        "required": ["key"],
        "optional": [],
        "description": "Phím: enter, back, home, ...",
    },
    "scroll_down": {
        "required": [],
        "optional": ["repeats"],
        "description": "Vuốt xuống N lần (mặc định 1). Dùng scroll_to nếu biết element cần tìm.",
    },
    "wait_stable": {
        "required": [],
        "optional": ["timeout", "stable_duration"],
        "description": (
            "⚡ Chờ UI ngừng thay đổi (animation/transition xong). "
            "timeout: tối đa N giây chờ (mặc định 5.0). "
            "stable_duration: UI phải đứng yên bao lâu (mặc định 0.4s). "
            "Dùng sau swipe, mở tab mới, hay bất kỳ animation nào trước khi tap."
        ),
    },
    "dismiss_popup": {
        "required": [],
        "optional": ["retries"],
        "description": (
            "🛡 Tự động đóng popup/dialog đang hiển thị (permission request, update prompt, quảng cáo). "
            "retries: thử tối đa N lần (mặc định 3). "
            "Dùng sau launch_app hoặc bất kỳ lúc nào có khả năng xuất hiện dialog bất ngờ."
        ),
    },
}


def get_scenario_schema() -> Dict[str, Any]:
    return {
        "description": "Scenario JSON dùng bởi device_farm MCP và run_scenario_task. AI phải output đúng format này.",
        "scenario": {
            "instructions": "string — câu lệnh gốc (giữ nguyên)",
            "steps": "array of step objects — thứ tự thực thi",
        },
        "step_types": SCENARIO_STEP_TYPES,
        "steps_schema": STEP_SCHEMA,
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
    if t == "open_url":
        url = step.get("url") or ""
        if isinstance(url, str) and url.strip():
            u = url.strip().lower()
            if not (u.startswith("http://") or u.startswith("https://")):
                errors.append(f"step[{index}]: open_url url must start with http:// or https://")
        # package optional; empty string = use default (Chrome) — no error
    if t == "tap_position":
        pos = step.get("pos")
        if pos is not None and isinstance(pos, str):
            valid = ("top_center", "middle_center", "bottom_center", "search_bar")
            if pos.strip().lower() not in valid:
                errors.append(f"step[{index}]: tap_position pos must be one of {valid}")
    return errors


def validate_scenario(scenario: Dict[str, Any]) -> List[str]:
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
