

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
    "verify_screen",
    "dismiss_popup",
    "set_variable",
    "repeat",
    "repeat_until",
    "if_element",
    "if_variable",
    "random_pick",
    "run_scenario",
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
    "swipe_ratio": {
        "required": ["x1", "y1", "x2", "y2"],
        "optional": ["duration_ms"],
        "description": "Swipe giữa hai điểm tỷ lệ (0–1). duration_ms mặc định 300.",
    },
    "tap_selector": {
        "required": ["by", "value"],
        "optional": ["fallback_rx", "fallback_ry", "timeout", "implicit_wait"],
        "description": (
            "Tap theo uiautomator2 selector. by: resource-id | text | xpath | class name. "
            "timeout (float, mặc định 5s): đợi element tối đa N giây trước khi fail. "
            "implicit_wait: Tenacity retry-until-visible (default 10s/0.5s poll). "
            "fallback_rx/ry: tọa độ ratio fallback nếu không tìm thấy element."
        ),
    },
    "wait_element": {
        "required": ["by", "value"],
        "optional": ["timeout", "poll"],
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
        "optional": ["clear_first", "implicit_wait"],
        "description": (
            "Tìm input field theo selector, xóa nội dung cũ (clear_first=true mặc định), "
            "rồi gõ text. implicit_wait: Tenacity retry-until-visible (default 10s/0.5s poll). "
            "by: resource-id (ưu tiên) | text | xpath."
        ),
    },
    "long_tap_selector": {
        "required": ["by", "value"],
        "optional": ["duration_ms", "implicit_wait"],
        "description": (
            "Long press element tìm theo selector. duration_ms mặc định 800ms. "
            "implicit_wait: Tenacity retry-until-visible (default 10s/0.5s poll)."
        ),
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
            "Chờ UI ngừng thay đổi (animation/transition xong). "
            "timeout: tối đa N giây chờ (mặc định 5.0). "
            "stable_duration: UI phải đứng yên bao lâu (mặc định 0.4s). "
            "Dùng sau swipe, mở tab mới, hay bất kỳ animation nào trước khi tap."
        ),
    },
    "verify_screen": {
        "required": ["screenshot"],
        "optional": ["ssim_threshold", "timeout", "poll"],
        "description": (
            "Visual Anchoring: so sánh SSIM giữa ảnh chụp lúc record và màn hình hiện tại. "
            "screenshot: base64 JPEG từ lúc record. ssim_threshold (0-1, default 0.75). "
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
        "optional": ["value", "from_list", "increment"],
        "description": (
            "Đặt hoặc cập nhật một runtime variable để dùng trong các step sau với ${NAME}. "
            "value: giá trị cụ thể (hỗ trợ ${VAR} interpolation). "
            "from_list: chọn ngẫu nhiên 1 phần tử từ danh sách. "
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
        "required": ["by", "value", "then"],
        "optional": ["timeout", "else"],
        "description": (
            "Re nhánh theo sự tồn tại của element. "
            "Nếu element tìm thấy trong timeout giây → chạy then. Nếu không → chạy else (nếu có). "
            "timeout: thời gian tối đa chờ element (mặc định 3s). "
            "by: text | resource-id | xpath."
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
    "extract": {
        "required": ["strategy"],
        "optional": ["stop_if_no_new", "no_new_threshold", "expand_see_more"],
        "description": (
            "Extract UI data từ màn hình hiện tại vào context['posts']. "
            "strategy: 'fb_posts' — parse FB post cards (author/text/timestamp/reactions/"
            "comments/shares/post_type/image_desc/comment_preview); "
            "'text_nodes' — thu thập tất cả text node vào context['text_nodes']. "
            "stop_if_no_new (bool, default False): set ctx['_break']=True khi không có bài mới "
            "trong no_new_threshold (default 3) lần scroll liên tiếp — dùng bên trong step 'loop'. "
            "expand_see_more (bool, default True): tự tap nút 'See more'/'Xem thêm' trước khi parse. "
            "⚠ Dùng với step 'loop' (không phải 'repeat') để stop_if_no_new hoạt động."
        ),
    },
    "loop": {
        "required": ["steps"],
        "optional": ["count", "while", "max_iterations"],
        "description": (
            "Lặp lại steps theo count hoặc while-condition. "
            "count: số lần lặp cố định. "
            "while: condition dict (element_exists | variable_equals) — lặp khi condition đúng. "
            "max_iterations: giới hạn an toàn (default 100). "
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
        "optional": ["region", "language", "psm", "preprocess", "scale_factor"],
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
        "optional": ["collection", "platform", "content_type", "dedupe_field", "tags"],
        "description": (
            "Save extracted data to content database with deduplication (DF-010). "
            "data_var: name of runtime variable containing the data (from extract_text_* or set_variable). "
            "collection: name of content collection (default: 'default'). "
            "dedupe_field: field in data to use for dedup hash (e.g. 'content'). "
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
