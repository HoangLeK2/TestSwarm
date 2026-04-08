# Node-Based Mobile Automation System — PRD v1.0

---

- **Product Name:** Device Farm Node Engine
- **Version:** 1.0
- **Author:** Mobile Automation Architect
- **Created:** 2026-03-28
- **Status:** Design Phase

---

## 1. Executive Summary

Thiết kế hệ thống automation dạng node-based cho thiết bị di động (Android & iOS), hỗ trợ thực thi workflow trực quan, có khả năng scale tới 1000+ thiết bị. Mỗi node là một đơn vị atomic, reusable, composable trong một workflow graph (DAG hoặc state machine).

### Tham chiếu từ hệ thống thực tế


| System                   | Đặc điểm tham khảo                        |
| ------------------------ | ----------------------------------------- |
| **Appium**               | Selector strategy, cross-platform API     |
| **Maestro**              | YAML flow, built-in wait/retry            |
| **Airtest/Poco**         | Image-based + UI-based hybrid             |
| **OpenSTF/DeviceFarmer** | Device management, minicap/minitouch      |
| **atxserver2**           | Provider-based architecture, uiautomator2 |
| **n8n/Node-RED**         | Visual node-based workflow engine         |
| **Prefect/Temporal**     | DAG orchestration, retry, timeout         |


---

## 2. Node Design Principles

```
┌─────────────────────────────────────────────┐
│              NODE CONTRACT                   │
├─────────────────────────────────────────────┤
│  id          : string (uuid)                │
│  type        : string (node type key)       │
│  category    : ControlFlow | Action | UI    │
│                | Data | Device | Network    │
│                | AI | Debug                  │
│  inputs      : Record<string, Port>         │
│  outputs     : Record<string, Port>         │
│  config      : Record<string, any>          │
│  timeout_ms  : number (default 30000)       │
│  retry       : { max: number, delay_ms }    │
│  on_error    : "fail" | "skip" | "fallback" │
└─────────────────────────────────────────────┘

Port := { type: "string"|"number"|"boolean"|"image"|"element"|"any", value: any }
```

**Quy tắc:**

- Mỗi node nhận input từ port, trả output qua port
- Node không giữ state ngoài execution context
- Timeout + retry là thuộc tính chung của mọi node
- Error handling: fail (dừng flow), skip (bỏ qua), fallback (chạy nhánh khác)

---

## 3. Complete Node Catalog

---

### 3.1 CONTROL FLOW NODES

#### 3.1.1 If / Else


| Field           | Detail                                                                                                          |
| --------------- | --------------------------------------------------------------------------------------------------------------- |
| **Node Name**   | `control.if_else`                                                                                               |
| **Category**    | Control Flow                                                                                                    |
| **Description** | Đánh giá biểu thức boolean, rẽ nhánh true/false. Hỗ trợ so sánh giá trị, kiểm tra tồn tại element, regex match. |
| **MVP**         | Yes — Core                                                                                                      |


```json
{
  "input": {
    "condition": "string (expression: $var > 10, element.exists, regex.match)"
  },
  "output": {
    "true_branch": "-> next node",
    "false_branch": "-> next node"
  },
  "config": {
    "expression_type": "value_compare | element_exists | regex | custom_js",
    "left_operand": "$variable or literal",
    "operator": "== | != | > | < | >= | <= | contains | matches | exists",
    "right_operand": "$variable or literal"
  }
}
```

**Example use case:** Nếu popup "Rate this app" xuất hiện → dismiss, nếu không → tiếp tục flow chính.

**Feasibility:**

- Android: uiautomator2 `d.exists()` + expression eval — **Full support**
- iOS: XCUITest `exists` property + WDA query — **Full support**

**Tham chiếu:** Maestro `runFlow.when`, Appium conditional execution, n8n IF node.

**Limitations:** Expression eval cần sandbox (không cho phép arbitrary code execution). Complex condition nên dùng Custom Script node thay vì nested if/else.

---

#### 3.1.2 Switch / Case


| Field           | Detail                                                                           |
| --------------- | -------------------------------------------------------------------------------- |
| **Node Name**   | `control.switch`                                                                 |
| **Category**    | Control Flow                                                                     |
| **Description** | Multi-branch routing dựa trên giá trị variable. Tương tự switch/case trong code. |
| **MVP**         | Yes — Core                                                                       |


```json
{
  "input": {
    "value": "any (variable to evaluate)"
  },
  "output": {
    "case_branches": "Map<string, -> next node>",
    "default_branch": "-> next node"
  },
  "config": {
    "variable": "$app_state",
    "cases": [
      { "value": "logged_in", "target": "node_dashboard" },
      { "value": "logged_out", "target": "node_login" },
      { "value": "onboarding", "target": "node_skip_onboard" }
    ],
    "default_target": "node_error_handler"
  }
}
```

**Example use case:** Sau khi launch app, kiểm tra trạng thái (logged_in / logged_out / onboarding) và route tới flow tương ứng.

**Feasibility:**

- Android/iOS: **Full support** — logic thuần, không phụ thuộc platform.

**Tham chiếu:** n8n Switch node, Node-RED switch, Prefect conditional tasks.

**Limitations:** Chỉ so sánh equality mặc định. Dùng If/Else cho range comparisons.

---

#### 3.1.3 Loop (For / While / For Each)


| Field           | Detail                                                                 |
| --------------- | ---------------------------------------------------------------------- |
| **Node Name**   | `control.loop`                                                         |
| **Category**    | Control Flow                                                           |
| **Description** | Lặp một nhóm nodes theo count, condition, hoặc iterate qua collection. |
| **MVP**         | Yes — Core                                                             |


```json
{
  "input": {
    "collection": "array (optional, for for_each mode)",
    "initial_value": "any (optional, for while mode)"
  },
  "output": {
    "current_item": "any (current iteration item)",
    "current_index": "number",
    "loop_body": "-> sub-flow",
    "on_complete": "-> next node"
  },
  "config": {
    "mode": "for_count | for_each | while",
    "count": 10,
    "condition": "$index < $max_scroll (for while mode)",
    "max_iterations": 100,
    "break_on_error": true
  }
}
```

**Example use case:**

- `for_count`: Scroll xuống 5 lần để load thêm content
- `for_each`: Iterate qua danh sách account để test login
- `while`: Scroll cho đến khi tìm thấy element target

**Feasibility:**

- Android/iOS: **Full support** — orchestration logic thuần.

**Tham chiếu:** Maestro `repeat`, Airtest loop patterns, n8n SplitInBatches.

**Limitations:** `while` loop cần `max_iterations` bắt buộc để tránh infinite loop. Với 1000+ devices chạy song song, mỗi loop nên có timeout tổng.

---

#### 3.1.4 Retry


| Field           | Detail                                                                           |
| --------------- | -------------------------------------------------------------------------------- |
| **Node Name**   | `control.retry`                                                                  |
| **Category**    | Control Flow                                                                     |
| **Description** | Wrap một node hoặc sub-flow, tự động retry khi fail. Hỗ trợ exponential backoff. |
| **MVP**         | Yes — Core                                                                       |


```json
{
  "input": {
    "target_flow": "-> sub-flow to retry"
  },
  "output": {
    "result": "any (output of successful execution)",
    "attempts": "number",
    "last_error": "string | null"
  },
  "config": {
    "max_retries": 3,
    "delay_ms": 1000,
    "backoff": "fixed | exponential | linear",
    "backoff_multiplier": 2,
    "retry_on": ["ElementNotFound", "Timeout", "AppCrash"],
    "recovery_action": "none | relaunch_app | clear_app_data"
  }
}
```

**Example use case:** Tap vào nút "Submit" — nếu fail do animation chưa xong, retry 3 lần với delay 1s. Nếu app crash, relaunch rồi retry.

**Feasibility:**

- Android: uiautomator2 auto-retry built-in cho `click()` — **Full support**
- iOS: WDA có implicit wait — **Full support**

**Tham chiếu:** Maestro built-in retry, Appium implicit/explicit wait, Temporal retry policy.

**Limitations:** Recovery action (relaunch, clear data) tốn thời gian 5-15s mỗi lần. Scale 1000 devices retry đồng thời có thể gây spike load trên provider.

---

#### 3.1.5 Timeout


| Field           | Detail                                                                           |
| --------------- | -------------------------------------------------------------------------------- |
| **Node Name**   | `control.timeout`                                                                |
| **Category**    | Control Flow                                                                     |
| **Description** | Wrap node/sub-flow với hard timeout. Khi hết thời gian → trigger timeout_branch. |
| **MVP**         | Yes — Core                                                                       |


```json
{
  "input": {
    "target_flow": "-> sub-flow to execute"
  },
  "output": {
    "result": "any | null",
    "timed_out": "boolean",
    "elapsed_ms": "number"
  },
  "config": {
    "timeout_ms": 30000,
    "on_timeout": "fail | skip | goto",
    "timeout_target": "node_id (if goto)"
  }
}
```

**Example use case:** Toàn bộ login flow phải hoàn thành trong 30s, nếu không → screenshot + báo fail.

**Feasibility:**

- Android/iOS: **Full support** — orchestration level.

**Tham chiếu:** Appium `newCommandTimeout`, Maestro step timeout, Temporal activity timeout.

**Limitations:** Kill sub-flow giữa chừng có thể để device ở trạng thái inconsistent. Nên kết hợp cleanup action.

---

#### 3.1.6 Parallel / Race


| Field           | Detail                                                                                                                        |
| --------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| **Node Name**   | `control.parallel`                                                                                                            |
| **Category**    | Control Flow                                                                                                                  |
| **Description** | Chạy nhiều sub-flow đồng thời trên cùng device hoặc cross-device. Mode `all` (chờ tất cả) hoặc `race` (lấy kết quả đầu tiên). |
| **MVP**         | No — Advanced                                                                                                                 |


```json
{
  "input": {
    "branches": ["-> sub-flow A", "-> sub-flow B", "-> sub-flow C"]
  },
  "output": {
    "results": "array (all mode) | any (race mode)",
    "winner_index": "number (race mode)",
    "errors": "array"
  },
  "config": {
    "mode": "all | race | allSettled",
    "max_concurrent": 5,
    "cancel_remaining_on_race_win": true,
    "scope": "same_device | cross_device"
  }
}
```

**Example use case:**

- `race` trên cùng device: Chờ element A hoặc element B xuất hiện trước (popup vs content loaded)
- `all` cross-device: Chạy cùng test trên 100 devices song song

**Feasibility:**

- Android: uiautomator2 hỗ trợ concurrent watchers — **Partial** (same device limited)
- iOS: WDA single session — **Limited** trên cùng device
- Cross-device: **Full support** — orchestration layer

**Tham chiếu:** Maestro không hỗ trợ, Appium parallel sessions, Temporal parallel activities.

**Limitations:** Trên cùng device, chỉ 1 UI interaction tại 1 thời điểm. `race` trên same device thực tế là polling + first-match. Cross-device parallel là strength chính cho device farm.

---

### 3.2 ACTION NODES (Mobile Interaction)

#### 3.2.1 Tap


| Field           | Detail                                                                                        |
| --------------- | --------------------------------------------------------------------------------------------- |
| **Node Name**   | `action.tap`                                                                                  |
| **Category**    | Action                                                                                        |
| **Description** | Tap vào element bằng selector hoặc tọa độ tuyệt đối/tương đối. Hỗ trợ long press, double tap. |
| **MVP**         | Yes — Core                                                                                    |


```json
{
  "input": {
    "element": "ElementRef | null (if using coordinates)",
    "coordinates": "{ x: number, y: number } | null"
  },
  "output": {
    "success": "boolean",
    "actual_coordinates": "{ x: number, y: number }",
    "timestamp": "number"
  },
  "config": {
    "strategy": "element | coordinate | image_match",
    "selector": {
      "type": "xpath | accessibility_id | text | text_contains | class | resource_id | css",
      "value": "string",
      "index": 0
    },
    "coordinate_mode": "absolute | percent",
    "tap_type": "single | double | long_press",
    "long_press_duration_ms": 1000,
    "offset": { "x": 0, "y": 0 },
    "wait_before_ms": 0,
    "wait_after_ms": 300
  }
}
```

**Example use case:** Tap nút "Login" bằng accessibility_id, long press avatar để mở context menu.

**Feasibility:**

- Android uiautomator2: `d(resourceId="btn_login").click()` — **Full support**
- Android minitouch/scrcpy: coordinate-based tap — **Full support**
- iOS WDA: `element.tap()` — **Full support**
- iOS XCUITest: `element.tap()` — **Full support**

**Tham chiếu:** Appium `click()`, Maestro `tapOn`, Airtest `touch()`, STF minitouch protocol.

**Limitations:** Coordinate-based tap phụ thuộc resolution — cần normalize theo %. Element selector reliable hơn nhưng chậm hơn 50-200ms. Image-based tap cần template matching overhead.

---

#### 3.2.2 Swipe / Scroll


| Field           | Detail                                                                                            |
| --------------- | ------------------------------------------------------------------------------------------------- |
| **Node Name**   | `action.swipe`                                                                                    |
| **Category**    | Action                                                                                            |
| **Description** | Swipe từ điểm A đến điểm B, hoặc scroll trong element container. Hỗ trợ direction-based shortcut. |
| **MVP**         | Yes — Core                                                                                        |


```json
{
  "input": {
    "container": "ElementRef | null (full screen if null)"
  },
  "output": {
    "success": "boolean",
    "new_elements_visible": "boolean"
  },
  "config": {
    "mode": "direction | coordinates | to_element",
    "direction": "up | down | left | right",
    "from": { "x": "50%", "y": "80%" },
    "to": { "x": "50%", "y": "20%" },
    "target_element": "selector (for to_element mode)",
    "speed": "slow | normal | fast",
    "duration_ms": 300,
    "steps": 10
  }
}
```

**Example use case:** Scroll danh sách sản phẩm xuống cho đến khi tìm thấy item target. Swipe left trên Tinder-like card.

**Feasibility:**

- Android uiautomator2: `d.swipe()`, `d(scrollable=True).scroll.to()` — **Full support**
- Android minitouch: multi-step touch event — **Full support**
- Android scrcpy: inject motion event — **Full support**
- iOS WDA: `swipe()`, `scroll()` — **Full support**

**Tham chiếu:** Appium `swipe()`, Maestro `swipe`/`scrollUntilVisible`, Airtest `swipe()`.

**Limitations:** `scroll.to()` trên uiautomator2 có thể slow với list dài. scrcpy/minitouch nhanh hơn nhưng không verify scroll result. Cần kết hợp Wait Element để xác nhận.

---

#### 3.2.3 Input Text


| Field           | Detail                                                                                                        |
| --------------- | ------------------------------------------------------------------------------------------------------------- |
| **Node Name**   | `action.input_text`                                                                                           |
| **Category**    | Action                                                                                                        |
| **Description** | Nhập text vào field đang focus hoặc element cụ thể. Hỗ trợ clear trước khi nhập, character-by-character mode. |
| **MVP**         | Yes — Core                                                                                                    |


```json
{
  "input": {
    "element": "ElementRef | null (current focus)",
    "text": "string"
  },
  "output": {
    "success": "boolean",
    "actual_text": "string"
  },
  "config": {
    "clear_first": true,
    "method": "set_text | type_keys | clipboard_paste | ime",
    "typing_delay_ms": 0,
    "hide_keyboard_after": false,
    "use_variable": "$username (resolve from context)"
  }
}
```

**Example use case:** Nhập email và password vào form login. Paste verification code từ clipboard.

**Feasibility:**

- Android uiautomator2: `d(resourceId="email").set_text("...")` — **Full support**
- Android ADB: `adb shell input text` (ASCII only) — **Partial** (no Unicode)
- Android IME (WhatsInput/ADBKeyboard): Unicode support — **Full support**
- iOS WDA: `element.type_text()` — **Full support**

**Tham chiếu:** Appium `sendKeys()`, Maestro `inputText`, atxserver2 WhatsInput IME.

**Limitations:** `set_text` nhanh nhưng bypass IME events — một số app check IME input. `type_keys` chậm nhưng realistic hơn. Unicode trên ADB shell cần custom IME. Clipboard paste bị restrict trên Android 13+ (background clipboard access).

---

#### 3.2.4 Key Event


| Field           | Detail                                                                 |
| --------------- | ---------------------------------------------------------------------- |
| **Node Name**   | `action.key_event`                                                     |
| **Category**    | Action                                                                 |
| **Description** | Gửi hardware key event: BACK, HOME, RECENT, VOLUME, POWER, ENTER, v.v. |
| **MVP**         | Yes — Core                                                             |


```json
{
  "input": {},
  "output": {
    "success": "boolean"
  },
  "config": {
    "key": "back | home | recent | enter | delete | volume_up | volume_down | power | menu | tab | escape | keycode_number",
    "action": "press | long_press",
    "long_press_duration_ms": 1000,
    "repeat": 1
  }
}
```

**Example use case:** Nhấn BACK để quay lại screen trước. Long press HOME để trigger assistant. Nhấn ENTER sau khi nhập search query.

**Feasibility:**

- Android uiautomator2: `d.press("back")` — **Full support** (tất cả keycode)
- Android ADB: `adb shell input keyevent` — **Full support**
- Android scrcpy: inject key event — **Full support**
- iOS WDA: `pressButton("home")` — **Partial** (chỉ home, volumeUp, volumeDown)
- iOS XCUITest: `.buttons["Home"].tap()` — **Partial**

**Tham chiếu:** Appium `pressKeyCode()`, Maestro `pressKey`, STF minitouch/keyevent.

**Limitations:** iOS rất hạn chế keycode — không có BACK (iOS dùng swipe gesture), không có RECENT. Một số key (POWER) cần special permission trên Android 11+.

---

#### 3.2.5 Launch / Kill App


| Field           | Detail                                                               |
| --------------- | -------------------------------------------------------------------- |
| **Node Name**   | `action.app_lifecycle`                                               |
| **Category**    | Action                                                               |
| **Description** | Launch app bằng package name, kill app, clear data, hoặc force-stop. |
| **MVP**         | Yes — Core                                                           |


```json
{
  "input": {},
  "output": {
    "success": "boolean",
    "launch_time_ms": "number (for launch)",
    "app_state": "not_installed | not_running | background | foreground"
  },
  "config": {
    "action": "launch | kill | force_stop | clear_data | restart",
    "package_name": "com.example.app",
    "activity": ".MainActivity (Android only, optional)",
    "bundle_id": "com.example.app (iOS)",
    "wait_for_launch_ms": 10000,
    "use_deep_link": false
  }
}
```

**Example use case:** Force stop app → clear data → relaunch để test fresh install experience. Kill background app trước khi chạy performance test.

**Feasibility:**

- Android uiautomator2: `d.app_start()`, `d.app_stop()`, `d.app_clear()` — **Full support**
- Android ADB: `am start`, `am force-stop`, `pm clear` — **Full support**
- iOS WDA: `launch()`, `terminate()` — **Full support**
- iOS: clear data chỉ bằng uninstall/reinstall — **Partial**

**Tham chiếu:** Appium `activateApp()`, `terminateApp()`, Maestro `launchApp`, `clearState`.

**Limitations:** iOS không hỗ trợ clear app data mà không uninstall. Launch time measurement cần kết hợp Wait Element cho accuracy. `clear_data` trên Android xóa cả login state.

---

#### 3.2.6 Deep Link Open


| Field           | Detail                                                                               |
| --------------- | ------------------------------------------------------------------------------------ |
| **Node Name**   | `action.deep_link`                                                                   |
| **Category**    | Action                                                                               |
| **Description** | Mở URL scheme hoặc universal link để navigate trực tiếp vào screen cụ thể trong app. |
| **MVP**         | Yes — Core                                                                           |


```json
{
  "input": {},
  "output": {
    "success": "boolean",
    "resolved_activity": "string (Android)",
    "elapsed_ms": "number"
  },
  "config": {
    "url": "myapp://product/12345",
    "type": "scheme | universal_link | app_link",
    "package_name": "com.example.app (Android, optional)",
    "wait_for_element": "selector (optional, verify navigation)",
    "wait_timeout_ms": 5000
  }
}
```

**Example use case:** Mở `myapp://checkout?item=123` để test checkout flow trực tiếp, skip navigation steps.

**Feasibility:**

- Android ADB: `am start -a android.intent.action.VIEW -d "myapp://..."` — **Full support**
- Android uiautomator2: `d.open_url()` — **Full support**
- iOS WDA: `safari.open(url)` hoặc `XCUIApplication.open(url)` — **Full support**

**Tham chiếu:** Maestro `openLink`, Appium `driver.get(url)`, Airtest `start_app_with_url`.

**Limitations:** Universal links cần device đã verify domain (AASA). Scheme URL có thể bị block bởi app chooser dialog trên Android.

---

### 3.3 UI & DETECTION NODES

#### 3.3.1 Find Element


| Field           | Detail                                                                    |
| --------------- | ------------------------------------------------------------------------- |
| **Node Name**   | `ui.find_element`                                                         |
| **Category**    | UI & Detection                                                            |
| **Description** | Tìm element trên screen bằng nhiều strategy. Trả về ElementRef hoặc null. |
| **MVP**         | Yes — Core                                                                |


```json
{
  "input": {},
  "output": {
    "element": "ElementRef | null",
    "elements": "ElementRef[] (if find_all)",
    "found": "boolean",
    "count": "number",
    "bounds": "{ left, top, right, bottom }",
    "text": "string",
    "attributes": "Record<string, string>"
  },
  "config": {
    "strategy": "xpath | accessibility_id | text | text_contains | text_regex | resource_id | class_name | css_selector | image",
    "value": "string or image_path",
    "index": 0,
    "find_all": false,
    "timeout_ms": 0,
    "scroll_to_find": false,
    "max_scroll_attempts": 5
  }
}
```

**Example use case:** Tìm tất cả product card elements trong list, extract text và bounds cho subsequent taps.

**Feasibility:**

- Android uiautomator2: xpath, resourceId, text, className — **Full support**
- Android Accessibility: AccessibilityNodeInfo traversal — **Full support**
- iOS WDA: xpath, accessibilityId, predicate string, class chain — **Full support**
- Image-based: template matching qua OpenCV — **Full support** cả 2 platform

**Tham chiếu:** Appium `findElement()`, Maestro selector engine, Airtest `poco()`, Espresso `onView()`.

**Limitations:** XPath chậm trên UI tree lớn (500ms+). `accessibility_id` nhanh nhất (~50ms). Image matching cần maintain template library. `scroll_to_find` tốn thời gian.

---

#### 3.3.2 Wait For Element


| Field           | Detail                                                                                  |
| --------------- | --------------------------------------------------------------------------------------- |
| **Node Name**   | `ui.wait_element`                                                                       |
| **Category**    | UI & Detection                                                                          |
| **Description** | Block execution cho đến khi element xuất hiện, biến mất, hoặc đạt trạng thái mong muốn. |
| **MVP**         | Yes — Core                                                                              |


```json
{
  "input": {},
  "output": {
    "found": "boolean",
    "element": "ElementRef | null",
    "waited_ms": "number"
  },
  "config": {
    "selector": { "type": "text", "value": "Welcome" },
    "condition": "exists | not_exists | visible | enabled | text_equals | text_contains",
    "expected_text": "string (for text conditions)",
    "timeout_ms": 10000,
    "poll_interval_ms": 500,
    "on_timeout": "fail | return_false | screenshot_and_fail"
  }
}
```

**Example use case:** Sau tap Login, wait cho "Dashboard" text xuất hiện (max 10s) rồi mới tiếp tục flow.

**Feasibility:**

- Android uiautomator2: `d(text="Welcome").wait(timeout=10)` — **Full support**
- iOS WDA: `waitForExistence(timeout:)` — **Full support**

**Tham chiếu:** Appium explicit wait, Maestro built-in auto-wait, Selenium WebDriverWait.

**Limitations:** Poll interval quá nhỏ (<200ms) gây CPU overhead trên device. Trên farm 1000 devices, nên dùng event-based notification thay vì polling khi có thể.

---

#### 3.3.3 Assert UI State


| Field           | Detail                                                                    |
| --------------- | ------------------------------------------------------------------------- |
| **Node Name**   | `ui.assert`                                                               |
| **Category**    | UI & Detection                                                            |
| **Description** | Kiểm tra điều kiện UI và mark pass/fail. Core node cho test verification. |
| **MVP**         | Yes — Core                                                                |


```json
{
  "input": {
    "element": "ElementRef | null"
  },
  "output": {
    "passed": "boolean",
    "actual_value": "any",
    "expected_value": "any",
    "message": "string",
    "screenshot_on_fail": "base64 | path"
  },
  "config": {
    "assert_type": "element_exists | element_not_exists | text_equals | text_contains | text_regex | attribute_equals | element_count | screen_matches_image | custom_expression",
    "selector": { "type": "text", "value": "Order Confirmed" },
    "expected": "string | number | boolean | image_path",
    "tolerance": 0.9,
    "capture_on_fail": true,
    "soft_assert": false
  }
}
```

**Example use case:** Assert "Order Confirmed" text hiển thị sau checkout flow. Assert product count >= 10 trong list.

**Feasibility:**

- Android/iOS: **Full support** — combination of find_element + comparison logic

**Tham chiếu:** Appium assertions, Maestro `assertVisible`, pytest assert, Airtest `assert_exists`.

**Limitations:** `soft_assert` (không dừng flow khi fail) cần careful logging. Image comparison cần tuning `tolerance` per device density. Visual regression across 1000 devices cần normalize screenshots.

---

#### 3.3.4 Capture Screen


| Field           | Detail                                                                            |
| --------------- | --------------------------------------------------------------------------------- |
| **Node Name**   | `ui.screenshot`                                                                   |
| **Category**    | UI & Detection                                                                    |
| **Description** | Chụp screenshot hiện tại, lưu file hoặc pass qua pipeline (OCR, image match, AI). |
| **MVP**         | Yes — Core                                                                        |


```json
{
  "input": {},
  "output": {
    "image": "base64_string",
    "path": "string (file path)",
    "resolution": "{ width: number, height: number }",
    "timestamp": "number"
  },
  "config": {
    "format": "png | jpeg",
    "quality": 80,
    "scale": 1.0,
    "save_to": "/path/to/save (optional)",
    "method": "uiautomator | minicap | scrcpy | screencap",
    "region": "{ x, y, width, height } (optional crop)"
  }
}
```

**Example use case:** Chụp screenshot khi test fail để debug. Feed vào OCR node để extract text. So sánh visual regression.

**Feasibility:**

- Android minicap: ~30fps streaming, capture single frame — **Full support** (fastest)
- Android scrcpy: H.264 decode + frame capture — **Full support**
- Android uiautomator2: `d.screenshot()` — **Full support** (200-500ms)
- Android ADB: `screencap -p` — **Full support** (slow, 1-2s)
- iOS WDA: `screenshot()` — **Full support** (300-800ms)
- iOS XCUITest: `XCUIScreen.main.screenshot()` — **Full support**

**Tham chiếu:** Appium `getScreenshot()`, Maestro auto-screenshot, STF minicap streaming.

**Limitations:** minicap deprecated trên Android 12+ (dùng scrcpy thay thế). Scale lớn: 1000 devices × screenshot/step = storage heavy. Nên compress + lifecycle management.

---

#### 3.3.5 OCR / Text Detection


| Field           | Detail                                                                                                                         |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| **Node Name**   | `ui.ocr`                                                                                                                       |
| **Category**    | UI & Detection                                                                                                                 |
| **Description** | Extract text từ screenshot hoặc vùng screen bằng OCR engine. Dùng khi element không có text attribute (canvas, game, webview). |
| **MVP**         | No — Advanced (nhưng rất quan trọng cho social app)                                                                            |


```json
{
  "input": {
    "image": "base64_string | path (from screenshot node)"
  },
  "output": {
    "full_text": "string",
    "blocks": [
      {
        "text": "string",
        "confidence": "number (0-1)",
        "bounds": "{ x, y, width, height }",
        "language": "string"
      }
    ]
  },
  "config": {
    "engine": "tesseract | paddleocr | google_vision | apple_vision",
    "language": "eng | vie | chi_sim | multi",
    "region": "{ x, y, width, height } (optional crop)",
    "preprocess": "grayscale | threshold | denoise",
    "min_confidence": 0.7
  }
}
```

**Example use case:** Extract OTP code từ SMS notification. Đọc text trong game UI. Verify text trong image-based content (banner, poster).

**Feasibility:**

- Android: screenshot → OCR engine (server-side) — **Full support**
- iOS: Apple Vision framework (on-device) hoặc server-side — **Full support**
- PaddleOCR: best cho CJK/Vietnamese — **Full support**

**Tham chiếu:** Airtest OCR module, Appium OCR plugin, Maestro `copyTextFrom`, Google ML Kit.

**Limitations:** OCR accuracy phụ thuộc resolution, font, contrast. Tesseract kém với mobile UI fonts — PaddleOCR hoặc Google Vision tốt hơn. Server-side OCR thêm network latency. Trên 1000 devices, cần OCR service riêng (GPU).

---

#### 3.3.6 Image Matching


| Field           | Detail                                                                                                       |
| --------------- | ------------------------------------------------------------------------------------------------------------ |
| **Node Name**   | `ui.image_match`                                                                                             |
| **Category**    | UI & Detection                                                                                               |
| **Description** | Tìm vị trí của template image trên screen. Dùng cho UI không có accessible elements (game, canvas, webview). |
| **MVP**         | No — Advanced                                                                                                |


```json
{
  "input": {
    "screen_image": "base64 | path",
    "template_image": "base64 | path"
  },
  "output": {
    "found": "boolean",
    "matches": [
      {
        "center": "{ x: number, y: number }",
        "bounds": "{ x, y, width, height }",
        "confidence": "number (0-1)"
      }
    ],
    "best_match_confidence": "number"
  },
  "config": {
    "method": "template_match | feature_match | sift | orb",
    "threshold": 0.85,
    "multi_scale": true,
    "max_matches": 1,
    "region": "{ x, y, width, height } (search area)"
  }
}
```

**Example use case:** Tìm icon "heart" để tap like trong app game. Verify logo hiển thị đúng vị trí. Detect custom UI component không có accessibility info.

**Feasibility:**

- Android/iOS: screenshot → OpenCV template matching (server-side) — **Full support**
- Airtest: built-in image recognition — **Reference implementation**

**Tham chiếu:** Airtest `Template().match_in()`, SikuliX, OpenCV `matchTemplate`.

**Limitations:** Template phải match resolution/density. Multi-scale matching chậm hơn 3-5x. Trên dark mode vs light mode cần 2 bộ template. Không robust bằng element-based detection.

---

### 3.4 DATA NODES

#### 3.4.1 Variable Set / Get


| Field           | Detail                                                                             |
| --------------- | ---------------------------------------------------------------------------------- |
| **Node Name**   | `data.variable`                                                                    |
| **Category**    | Data                                                                               |
| **Description** | Set/get biến trong workflow execution context. Hỗ trợ scope: flow, global, device. |
| **MVP**         | Yes — Core                                                                         |


```json
{
  "input": {
    "value": "any (for set operation)"
  },
  "output": {
    "value": "any (for get operation)"
  },
  "config": {
    "operation": "set | get | increment | append | delete",
    "name": "$login_email",
    "scope": "flow | global | device",
    "default_value": "null (for get when not exists)",
    "ttl_ms": 0
  }
}
```

**Example use case:** Lưu OTP code extracted từ OCR → dùng lại ở Input Text node. Counter số lần retry. Lưu device-specific config.

**Feasibility:**

- Android/iOS: **Full support** — pure orchestration logic.

**Tham chiếu:** n8n Set node, Maestro `output`/`env`, Prefect task results.

**Limitations:** `global` scope trên 1000 devices cần distributed store (Redis). `device` scope bị mất khi device disconnect. Cần garbage collection cho expired variables.

---

#### 3.4.2 JSON Transform


| Field           | Detail                                                                    |
| --------------- | ------------------------------------------------------------------------- |
| **Node Name**   | `data.json_transform`                                                     |
| **Category**    | Data                                                                      |
| **Description** | Transform, filter, map JSON data. Dùng JSONPath hoặc JMESPath expression. |
| **MVP**         | No — Advanced                                                             |


```json
{
  "input": {
    "data": "any (JSON object or array)"
  },
  "output": {
    "result": "any"
  },
  "config": {
    "operation": "extract | filter | map | merge | flatten | sort | pick | omit",
    "expression": "$.users[?(@.active==true)].email (JSONPath)",
    "jmespath": "users[?active].email (JMESPath alternative)",
    "template": "{ name: $.first + ' ' + $.last } (for map)"
  }
}
```

**Example use case:** Extract danh sách email từ API response → feed vào Loop node. Merge device info + test result.

**Feasibility:**

- Android/iOS: **Full support** — server-side logic.

**Tham chiếu:** n8n Set/Function node, jq, JSONPath.

**Limitations:** Complex transform nên dùng Custom Script node. JSONPath expression lỗi khó debug.

---

#### 3.4.3 Random Data Generator


| Field           | Detail                                                                |
| --------------- | --------------------------------------------------------------------- |
| **Node Name**   | `data.random`                                                         |
| **Category**    | Data                                                                  |
| **Description** | Generate random data cho test: email, phone, name, number, UUID, v.v. |
| **MVP**         | Yes — Core                                                            |


```json
{
  "input": {},
  "output": {
    "value": "any (generated data)"
  },
  "config": {
    "type": "email | phone | name | number | uuid | string | date | address | paragraph | custom_pattern",
    "locale": "en | vi | zh",
    "pattern": "user_####@test.com (# = random digit)",
    "min": 0,
    "max": 100,
    "length": 10,
    "prefix": "test_",
    "unique": true,
    "seed": null
  }
}
```

**Example use case:** Generate unique email cho mỗi test run. Random phone number cho registration flow. Random content cho social media post test.

**Feasibility:**

- Android/iOS: **Full support** — server-side Faker library.

**Tham chiếu:** Faker.js/Faker.py, Maestro `${random}`, data-driven testing.

**Limitations:** `unique` trên 1000 devices cần centralized uniqueness check. Locale-specific data (Vietnamese name, phone format) cần proper locale config.

---

#### 3.4.4 Extract From UI XML


| Field           | Detail                                                                                               |
| --------------- | ---------------------------------------------------------------------------------------------------- |
| **Node Name**   | `data.extract_ui`                                                                                    |
| **Category**    | Data                                                                                                 |
| **Description** | Dump UI hierarchy (XML) và extract data bằng XPath. Bulk extraction nhanh hơn multiple Find Element. |
| **MVP**         | No — Advanced                                                                                        |


```json
{
  "input": {},
  "output": {
    "xml": "string (raw UI hierarchy XML)",
    "extracted": "any (result of xpath query)",
    "elements_count": "number"
  },
  "config": {
    "xpath_queries": {
      "all_texts": "//node[@text!='']/@text",
      "button_labels": "//node[@class='android.widget.Button']/@text",
      "list_items": "//node[@resource-id='item_list']/node/@text"
    },
    "include_invisible": false,
    "compressed": true
  }
}
```

**Example use case:** Extract tất cả text trên screen để verify content. Đếm số items trong list. Dump full UI tree cho debugging.

**Feasibility:**

- Android uiautomator2: `d.dump_hierarchy()` — **Full support**
- Android ADB: `uiautomator dump` — **Full support** (slower)
- iOS WDA: `source()` — **Full support**

**Tham chiếu:** Appium `getPageSource()`, uiautomator2 `dump_hierarchy`, WDA `source`.

**Limitations:** UI dump chậm (500ms-2s) trên complex screens. XML size lớn (100KB+) cho deep hierarchies. Không nên gọi mỗi step — chỉ khi cần bulk extraction.

---

### 3.5 DEVICE NODES

#### 3.5.1 Install / Uninstall App


| Field           | Detail                                         |
| --------------- | ---------------------------------------------- |
| **Node Name**   | `device.app_install`                           |
| **Category**    | Device                                         |
| **Description** | Install APK/IPA lên device hoặc uninstall app. |
| **MVP**         | Yes — Core                                     |


```json
{
  "input": {},
  "output": {
    "success": "boolean",
    "install_time_ms": "number",
    "version_installed": "string"
  },
  "config": {
    "action": "install | uninstall | reinstall",
    "source": "url | local_path | provider_upload",
    "path": "/path/to/app.apk or https://...",
    "package_name": "com.example.app (for uninstall)",
    "grant_permissions": true,
    "replace_existing": true,
    "downgrade": false,
    "timeout_ms": 120000
  }
}
```

**Example use case:** Install APK mới trước khi chạy test suite. Reinstall để reset app state (iOS workaround).

**Feasibility:**

- Android ADB: `adb install -r -g app.apk` — **Full support**
- Android uiautomator2: `d.app_install(url)` — **Full support**
- iOS: `ideviceinstaller`, `ios-deploy`, `tidevice` — **Full support** (cần signing)
- iOS WDA: không hỗ trợ install trực tiếp — **Cần provider API**

**Tham chiếu:** atxserver2 provider `/app/install`, Appium `installApp()`, Maestro `--app`.

**Limitations:** iOS install cần enterprise cert hoặc developer provisioning. Large APK (>100MB) tốn thời gian trên WiFi. 1000 devices install đồng thời cần CDN/cache cho APK distribution.

---

#### 3.5.2 Get Device Info


| Field           | Detail                                                             |
| --------------- | ------------------------------------------------------------------ |
| **Node Name**   | `device.info`                                                      |
| **Category**    | Device                                                             |
| **Description** | Query thông tin device: model, OS version, screen size, IMEI, v.v. |
| **MVP**         | Yes — Core                                                         |


```json
{
  "input": {},
  "output": {
    "device_id": "string",
    "platform": "android | ios",
    "model": "string",
    "brand": "string",
    "os_version": "string",
    "sdk_version": "number (Android)",
    "screen": "{ width, height, density }",
    "ip_address": "string",
    "battery": "{ level, charging, temperature }",
    "storage": "{ total_gb, free_gb }",
    "network": "{ type: wifi|cellular, ssid, signal_strength }",
    "imei": "string",
    "serial": "string"
  },
  "config": {
    "fields": ["all"] | ["model", "os_version", "battery"],
    "refresh": true
  }
}
```

**Example use case:** Log device info trước test run. Conditional logic dựa trên OS version. Filter test cases theo screen size.

**Feasibility:**

- Android uiautomator2: `d.info`, `d.device_info` — **Full support**
- Android ADB: `getprop`, `dumpsys` — **Full support**
- iOS WDA: `status()`, device capabilities — **Partial** (limited fields)
- iOS libimobiledevice: `ideviceinfo` — **Full support**

**Tham chiếu:** atxserver2 device properties, Appium `getDeviceInfo()`, STF device object.

**Limitations:** Một số field (IMEI) cần special permission trên Android 10+. Battery temperature cần `dumpsys battery` parsing. iOS không expose IMEI qua WDA.

---

#### 3.5.3 Battery / Network State


| Field           | Detail                                                                                               |
| --------------- | ---------------------------------------------------------------------------------------------------- |
| **Node Name**   | `device.state`                                                                                       |
| **Category**    | Device                                                                                               |
| **Description** | Monitor device state: battery, network, memory, CPU. Dùng cho health check và conditional execution. |
| **MVP**         | No — Advanced                                                                                        |


```json
{
  "input": {},
  "output": {
    "battery_level": "number (0-100)",
    "battery_charging": "boolean",
    "battery_temperature": "number (Celsius)",
    "network_type": "wifi | cellular | none",
    "wifi_ssid": "string",
    "memory_used_mb": "number",
    "cpu_usage_percent": "number"
  },
  "config": {
    "monitor_fields": ["battery", "network", "memory", "cpu"],
    "alert_thresholds": {
      "battery_min": 20,
      "temperature_max": 45,
      "memory_max_percent": 90
    }
  }
}
```

**Example use case:** Không chạy test nếu battery < 20%. Alert khi device overheating (>45°C). Monitor memory leak during long test.

**Feasibility:**

- Android ADB: `dumpsys battery`, `dumpsys wifi`, `dumpsys meminfo` — **Full support**
- Android uiautomator2: battery info via atx-agent — **Full support**
- iOS: `ideviceinfo`, `idevicediagnostics` — **Partial** (battery ok, CPU limited)

**Tham chiếu:** STF battery monitoring, atxserver2 device state, DeviceFarmer watchdog.

**Limitations:** `dumpsys` parsing brittle across Android versions. CPU monitoring cần continuous sampling. iOS battery temperature không always available.

---

#### 3.5.4 Rotate Screen


| Field           | Detail                                                            |
| --------------- | ----------------------------------------------------------------- |
| **Node Name**   | `device.rotate`                                                   |
| **Category**    | Device                                                            |
| **Description** | Xoay screen orientation: portrait, landscape, auto-rotate toggle. |
| **MVP**         | No — Advanced                                                     |


```json
{
  "input": {},
  "output": {
    "orientation": "portrait | landscape | reverse_portrait | reverse_landscape",
    "rotation": "number (0, 90, 180, 270)"
  },
  "config": {
    "target": "portrait | landscape | reverse_portrait | reverse_landscape | natural | toggle",
    "freeze_rotation": true
  }
}
```

**Example use case:** Test landscape mode cho video player. Verify UI responsive khi rotate.

**Feasibility:**

- Android uiautomator2: `d.set_orientation("l")` — **Full support**
- Android ADB: `settings put system accelerometer_rotation 0` + `content insert` — **Full support**
- iOS WDA: `setRotation()` — **Full support**

**Tham chiếu:** Appium `setOrientation()`, Maestro không hỗ trợ rotate.

**Limitations:** Một số app override rotation settings. Physical sensor-based rotation không thể simulate. Sau rotate, element coordinates thay đổi — cần re-query.

---

### 3.6 NETWORK NODES

#### 3.6.1 HTTP Request


| Field           | Detail                                                                                                 |
| --------------- | ------------------------------------------------------------------------------------------------------ |
| **Node Name**   | `network.http`                                                                                         |
| **Category**    | Network                                                                                                |
| **Description** | Gửi HTTP request từ server (không phải từ device). Dùng để call API, fetch test data, trigger backend. |
| **MVP**         | Yes — Core                                                                                             |


```json
{
  "input": {
    "dynamic_body": "any (merged with config.body)"
  },
  "output": {
    "status_code": "number",
    "headers": "Record<string, string>",
    "body": "any (parsed JSON or raw string)",
    "elapsed_ms": "number"
  },
  "config": {
    "method": "GET | POST | PUT | DELETE | PATCH",
    "url": "https://api.example.com/users",
    "headers": { "Authorization": "Bearer $token" },
    "body": { "email": "$generated_email" },
    "timeout_ms": 30000,
    "follow_redirects": true,
    "verify_ssl": true,
    "retry_on_status": [500, 502, 503],
    "parse_response": "json | text | binary"
  }
}
```

**Example use case:** Tạo test account qua API trước khi chạy UI test. Fetch OTP từ test email service. Verify backend state sau UI action.

**Feasibility:**

- Android/iOS: **Full support** — server-side execution, không phụ thuộc platform.

**Tham chiếu:** n8n HTTP Request node, Postman, Maestro `evalScript` with fetch.

**Limitations:** Không phải request từ device network — nếu cần test từ device perspective, dùng proxy node. SSL pinning trên device không ảnh hưởng. Rate limiting cần attention khi 1000 devices gọi cùng endpoint.

---

#### 3.6.2 Webhook Trigger


| Field           | Detail                                                                                                 |
| --------------- | ------------------------------------------------------------------------------------------------------ |
| **Node Name**   | `network.webhook`                                                                                      |
| **Category**    | Network                                                                                                |
| **Description** | Chờ incoming webhook call (push notification, SMS callback, payment callback) trước khi tiếp tục flow. |
| **MVP**         | No — Advanced                                                                                          |


```json
{
  "input": {},
  "output": {
    "payload": "any (webhook request body)",
    "headers": "Record<string, string>",
    "received_at": "number"
  },
  "config": {
    "path": "/webhook/$flow_id/$device_id",
    "method": "POST",
    "timeout_ms": 60000,
    "filter": { "event": "sms_received", "to": "$phone_number" },
    "on_timeout": "fail | skip"
  }
}
```

**Example use case:** Chờ SMS verification callback sau khi app gửi OTP. Wait for payment gateway callback.

**Feasibility:**

- Android/iOS: **Full support** — server-side webhook listener.

**Tham chiếu:** n8n Webhook node, Zapier webhook trigger.

**Limitations:** Cần expose public URL cho external webhook sources. Timeout management trên 1000 concurrent waiting flows cần efficient event system. Security: validate webhook source.

---

#### 3.6.3 Proxy Control


| Field           | Detail                                                                                                |
| --------------- | ----------------------------------------------------------------------------------------------------- |
| **Node Name**   | `network.proxy`                                                                                       |
| **Category**    | Network                                                                                               |
| **Description** | Configure proxy trên device để intercept/modify traffic, simulate network conditions, hoặc rotate IP. |
| **MVP**         | No — Advanced                                                                                         |


```json
{
  "input": {},
  "output": {
    "proxy_active": "boolean",
    "proxy_address": "string",
    "assigned_ip": "string"
  },
  "config": {
    "action": "set | clear | rotate_ip",
    "proxy_host": "192.168.1.100",
    "proxy_port": 8080,
    "proxy_type": "http | socks5",
    "auth": { "username": "...", "password": "..." },
    "network_condition": {
      "preset": "3g | 4g | wifi_slow | offline | packet_loss_10",
      "download_kbps": 1500,
      "upload_kbps": 750,
      "latency_ms": 100
    },
    "ssl_intercept": false
  }
}
```

**Example use case:** Rotate proxy IP cho mỗi device (anti-ban). Simulate slow network cho performance test. Intercept API calls cho debugging.

**Feasibility:**

- Android WiFi proxy: `settings put global http_proxy` — **Full support** (cần root cho some apps)
- Android VPN-based: tun2socks, local VPN — **Full support** (no root)
- iOS proxy: WiFi settings proxy — **Partial** (cần MDM hoặc manual config)

**Tham chiếu:** mitmproxy, Charles Proxy, DeviceFarmer proxy config.

**Limitations:** SSL intercept cần install CA cert trên device (Android 7+ cần system cert, cần root). VPN-based proxy tốn battery. iOS proxy config khó automate mà không có MDM.

---

### 3.7 AI NODES

#### 3.7.1 Screen Understanding (LLM/VLM)


| Field           | Detail                                                                                                      |
| --------------- | ----------------------------------------------------------------------------------------------------------- |
| **Node Name**   | `ai.screen_understand`                                                                                      |
| **Category**    | AI                                                                                                          |
| **Description** | Gửi screenshot tới Vision Language Model (VLM) để hiểu context screen, identify elements, answer questions. |
| **MVP**         | No — Advanced (but high-value)                                                                              |


```json
{
  "input": {
    "screenshot": "base64 (from ui.screenshot)"
  },
  "output": {
    "description": "string (screen summary)",
    "elements": [
      {
        "label": "Login button",
        "type": "button",
        "bounds": "{ x, y, width, height }",
        "actionable": true
      }
    ],
    "current_screen": "string (screen name/state)",
    "suggested_action": "string",
    "raw_response": "string"
  },
  "config": {
    "model": "gpt-4o | claude-sonnet-4-20250514 | gemini-pro-vision | local_vllm",
    "prompt": "Describe the current screen state. Identify all interactive elements.",
    "structured_output": true,
    "max_tokens": 1000,
    "temperature": 0.1,
    "cache_similar_screens": true
  }
}
```

**Example use case:** VLM xác định app đang ở screen nào (login, home, error) mà không cần selector. Tìm element "Add to cart" trên UI phức tạp. Verify visual correctness mà assert truyền thống không cover.

**Feasibility:**

- Android/iOS: screenshot → API call to VLM — **Full support**
- On-device: MLC-LLM / MediaPipe — **Experimental** (slow, limited)
- Server-side: GPT-4o, Claude, Gemini — **Full support**

**Tham chiếu:** AppAgent (Microsoft), CogAgent, SeeClick, Anthropic computer use.

**Limitations:** Latency 1-5s per API call. Cost: $0.01-0.05 per screenshot analysis. Trên 1000 devices, cần caching strategy (hash similar screens). Accuracy varies — nên dùng kết hợp với traditional selectors, không thay thế hoàn toàn. Rate limiting từ LLM providers.

---

#### 3.7.2 Auto-Healing Selector


| Field           | Detail                                                                                           |
| --------------- | ------------------------------------------------------------------------------------------------ |
| **Node Name**   | `ai.auto_heal`                                                                                   |
| **Category**    | AI                                                                                               |
| **Description** | Khi selector fail, tự động tìm alternative selector bằng heuristics + AI. Giảm test maintenance. |
| **MVP**         | No — Advanced (high-value for maintenance)                                                       |


```json
{
  "input": {
    "failed_selector": "{ type, value }",
    "ui_hierarchy": "string (XML from extract_ui)",
    "screenshot": "base64",
    "historical_selectors": "array (previously working selectors)"
  },
  "output": {
    "healed_selector": "{ type, value }",
    "confidence": "number (0-1)",
    "method": "heuristic | embedding_similarity | vlm",
    "suggestion_type": "auto_apply | needs_review"
  },
  "config": {
    "strategies": [
      "text_similarity",
      "structural_position",
      "attribute_fuzzy_match",
      "visual_similarity",
      "llm_reasoning"
    ],
    "auto_apply_threshold": 0.9,
    "notify_on_heal": true,
    "update_original": false,
    "max_candidates": 5
  }
}
```

**Example use case:** Button "Login" đổi thành "Sign in" sau app update — auto-heal tìm button mới bằng text similarity + position. Resource ID thay đổi nhưng element cùng vị trí — structural match.

**Feasibility:**

- Android/iOS: UI hierarchy + screenshot → matching engine — **Full support**
- Heuristic: text similarity, position, class matching — **Full support**
- LLM-based: send context to VLM — **Full support** (expensive)

**Tham chiếu:** Healenium, Appium AI plugin, testRigor, Mabl auto-healing.

**Limitations:** Auto-healing có thể chọn sai element → false positive test pass (nguy hiểm). Cần review mechanism. LLM-based healing chậm (2-5s). Nên chỉ dùng khi heuristic fail.

---

#### 3.7.3 Scenario Generation from Instruction


| Field           | Detail                                                                                                |
| --------------- | ----------------------------------------------------------------------------------------------------- |
| **Node Name**   | `ai.generate_flow`                                                                                    |
| **Category**    | AI                                                                                                    |
| **Description** | Generate workflow nodes từ natural language instruction. LLM produce node graph dựa trên app context. |
| **MVP**         | No — Advanced                                                                                         |


```json
{
  "input": {
    "instruction": "string (natural language)",
    "app_context": {
      "package_name": "string",
      "current_screen": "string (from ai.screen_understand)",
      "available_screens": ["login", "home", "profile", "settings"],
      "previous_flows": "array (reference flows)"
    }
  },
  "output": {
    "flow": {
      "nodes": "array (generated node definitions)",
      "edges": "array (connections)",
      "variables": "array"
    },
    "confidence": "number",
    "warnings": "string[]",
    "requires_review": "boolean"
  },
  "config": {
    "model": "claude-sonnet-4-20250514 | gpt-4o",
    "output_format": "node_graph | yaml | python",
    "validate_selectors": true,
    "include_assertions": true,
    "include_error_handling": true,
    "max_steps": 20
  }
}
```

**Example use case:** Input: "Test đăng ký tài khoản mới với email random, verify hiện Welcome screen" → Output: workflow graph với Random Data → Deep Link → Input Text × 3 → Tap Register → Wait Element → Assert.

**Feasibility:**

- Server-side LLM: GPT-4, Claude — **Feasible** (needs fine-tuning)
- Accuracy: ~70-80% cho simple flows, ~40-50% cho complex flows

**Tham chiếu:** Copilot for testing, Testim AI, Katalon AI.

**Limitations:** Generated flows luôn cần human review. LLM không biết exact selectors — cần explore phase. Complex business logic flows khó generate chính xác. Cost cao cho generation + validation.

---

#### 3.7.4 Decision Making (LLM-based)


| Field           | Detail                                                                                                 |
| --------------- | ------------------------------------------------------------------------------------------------------ |
| **Node Name**   | `ai.decide`                                                                                            |
| **Category**    | AI                                                                                                     |
| **Description** | LLM đánh giá tình huống runtime và chọn action. Useful cho dynamic flows mà không thể hard-code logic. |
| **MVP**         | No — Advanced                                                                                          |


```json
{
  "input": {
    "context": {
      "current_screen": "string | base64 (screenshot)",
      "goal": "string (what we want to achieve)",
      "history": "array (previous actions + results)",
      "available_actions": ["tap_login", "scroll_down", "go_back", "skip"]
    }
  },
  "output": {
    "decision": "string (chosen action key)",
    "reasoning": "string",
    "confidence": "number",
    "parameters": "Record<string, any>"
  },
  "config": {
    "model": "claude-sonnet-4-20250514 | gpt-4o",
    "system_prompt": "You are a mobile app tester...",
    "max_history_steps": 10,
    "fallback_action": "screenshot_and_fail",
    "max_consecutive_ai_decisions": 5
  }
}
```

**Example use case:** Gặp unexpected dialog → AI quyết định dismiss hay interact. Dynamic navigation trong app phức tạp mà route thay đổi theo user state.

**Feasibility:**

- Server-side LLM: **Full support**
- On-device: **Not practical** (latency + model size)

**Tham chiếu:** Anthropic computer use, AppAgent, AutoDroid.

**Limitations:** Mỗi decision = 1 API call (1-3s + cost). `max_consecutive_ai_decisions` bắt buộc để tránh infinite AI loop. Cần logging chi tiết cho debugging AI decisions. Không suitable cho time-sensitive actions.

---

### 3.8 DEBUG / OBSERVABILITY NODES

#### 3.8.1 Log Node


| Field           | Detail                                                                              |
| --------------- | ----------------------------------------------------------------------------------- |
| **Node Name**   | `debug.log`                                                                         |
| **Category**    | Debug                                                                               |
| **Description** | Ghi log message vào execution trace. Hỗ trợ structured logging với severity levels. |
| **MVP**         | Yes — Core                                                                          |


```json
{
  "input": {
    "data": "any (optional, data to log)"
  },
  "output": {},
  "config": {
    "level": "debug | info | warn | error",
    "message": "Step completed: login with $email",
    "include_screenshot": false,
    "include_ui_hierarchy": false,
    "tags": ["login", "smoke_test"],
    "structured_data": { "step": "$current_step", "device": "$device_id" }
  }
}
```

**Example use case:** Log giá trị variable trước assert. Mark milestone steps cho reporting. Error context logging.

**Feasibility:**

- Android/iOS: **Full support** — pure orchestration.

**Tham chiếu:** n8n log node, Allure report steps, Maestro verbose mode.

**Limitations:** Excessive logging trên 1000 devices = storage explosion. Cần log level filtering + rotation. Structured logging format cần chuẩn hóa cho log aggregation (ELK, Datadog).

---

#### 3.8.2 Screenshot on Fail


| Field           | Detail                                                                                         |
| --------------- | ---------------------------------------------------------------------------------------------- |
| **Node Name**   | `debug.screenshot_on_fail`                                                                     |
| **Category**    | Debug                                                                                          |
| **Description** | Decorator node: wrap bất kỳ node nào, tự động chụp screenshot + UI hierarchy khi node đó fail. |
| **MVP**         | Yes — Core                                                                                     |


```json
{
  "input": {
    "target_node": "-> node to wrap"
  },
  "output": {
    "original_output": "any",
    "failure_screenshot": "base64 | null",
    "failure_ui_xml": "string | null",
    "failure_device_log": "string | null"
  },
  "config": {
    "capture_screenshot": true,
    "capture_ui_hierarchy": true,
    "capture_logcat": true,
    "logcat_lines": 50,
    "save_artifacts_to": "/reports/$flow_id/$device_id/",
    "apply_to": "single_node | all_nodes_in_flow"
  }
}
```

**Example use case:** Mọi test step tự động capture evidence khi fail, attach vào test report.

**Feasibility:**

- Android/iOS: **Full support**

**Tham chiếu:** Appium `afterTest` hooks, Allure screenshot attachment, pytest-screenshot.

**Limitations:** Capture 3 artifacts (screenshot + XML + logcat) mỗi failure = 1-3s overhead. Trên 1000 devices, artifact storage cần S3/MinIO. Logcat capture cần filter relevant lines.

---

#### 3.8.3 Record Video


| Field           | Detail                                                                                |
| --------------- | ------------------------------------------------------------------------------------- |
| **Node Name**   | `debug.record_video`                                                                  |
| **Category**    | Debug                                                                                 |
| **Description** | Record screen video trong suốt execution. Start/stop recording hoặc record full flow. |
| **MVP**         | No — Advanced                                                                         |


```json
{
  "input": {},
  "output": {
    "video_path": "string",
    "duration_ms": "number",
    "size_bytes": "number"
  },
  "config": {
    "action": "start | stop",
    "method": "screenrecord | scrcpy_record | minicap_stream",
    "format": "mp4 | webm",
    "quality": "low | medium | high",
    "max_duration_s": 180,
    "fps": 15,
    "save_to": "/recordings/$flow_id/"
  }
}
```

**Example use case:** Record toàn bộ test execution cho CI report. Record chỉ khi test fail (start → catch error → stop + save).

**Feasibility:**

- Android ADB: `screenrecord` — **Full support** (max 180s per recording)
- Android scrcpy: `--record` — **Full support** (no time limit)
- Android minicap: frame-to-video encoding — **Full support** (custom)
- iOS: `idevice_id` + QuickTime/xrecord — **Partial** (needs special tools)
- iOS WDA: không built-in record — **Partial** (cần third-party)

**Tham chiếu:** Appium `startRecordingScreen()`, Maestro video record, Allure video attachment.

**Limitations:** Video recording tốn CPU/memory trên device. 1000 devices recording = massive storage (1 min ≈ 5-15MB). Nên chỉ record khi fail hoặc specific flows. `screenrecord` giới hạn 180s trên Android.

---

#### 3.8.4 Trace Step Execution


| Field           | Detail                                                                                             |
| --------------- | -------------------------------------------------------------------------------------------------- |
| **Node Name**   | `debug.trace`                                                                                      |
| **Category**    | Debug                                                                                              |
| **Description** | Distributed tracing cho mỗi node execution. Track timing, input/output, device state tại mỗi step. |
| **MVP**         | No — Advanced (nhưng critical cho production farm)                                                 |


```json
{
  "input": {},
  "output": {
    "trace_id": "string (OpenTelemetry trace ID)",
    "span_id": "string"
  },
  "config": {
    "enabled": true,
    "exporter": "jaeger | zipkin | otlp | console",
    "service_name": "device-farm-executor",
    "include_inputs": true,
    "include_outputs": false,
    "sample_rate": 1.0,
    "custom_attributes": {
      "device_id": "$device_id",
      "flow_name": "$flow_name",
      "build_version": "$app_version"
    }
  }
}
```

**Example use case:** Trace toàn bộ test execution qua Jaeger UI. Identify bottleneck nodes. Correlate failures across devices.

**Feasibility:**

- Android/iOS: **Full support** — server-side OpenTelemetry integration.

**Tham chiếu:** OpenTelemetry, Jaeger, Datadog APM, Temporal workflow traces.

**Limitations:** High-cardinality traces (1000 devices × 50 steps) cần proper sampling. Storage cost cho full traces. `include_outputs` gồm screenshots = massive trace data.

---

## 4. Summary Tables

### 4.1 MVP Core Nodes (Must-Have — Phase 1)


| #   | Node                       | Category     | Priority | Complexity |
| --- | -------------------------- | ------------ | -------- | ---------- |
| 1   | `control.if_else`          | Control Flow | P0       | Low        |
| 2   | `control.switch`           | Control Flow | P0       | Low        |
| 3   | `control.loop`             | Control Flow | P0       | Medium     |
| 4   | `control.retry`            | Control Flow | P0       | Medium     |
| 5   | `control.timeout`          | Control Flow | P0       | Low        |
| 6   | `action.tap`               | Action       | P0       | Medium     |
| 7   | `action.swipe`             | Action       | P0       | Medium     |
| 8   | `action.input_text`        | Action       | P0       | Medium     |
| 9   | `action.key_event`         | Action       | P0       | Low        |
| 10  | `action.app_lifecycle`     | Action       | P0       | Low        |
| 11  | `action.deep_link`         | Action       | P1       | Low        |
| 12  | `ui.find_element`          | UI           | P0       | Medium     |
| 13  | `ui.wait_element`          | UI           | P0       | Medium     |
| 14  | `ui.assert`                | UI           | P0       | Medium     |
| 15  | `ui.screenshot`            | UI           | P0       | Low        |
| 16  | `data.variable`            | Data         | P0       | Low        |
| 17  | `data.random`              | Data         | P1       | Low        |
| 18  | `device.app_install`       | Device       | P1       | Medium     |
| 19  | `device.info`              | Device       | P1       | Low        |
| 20  | `network.http`             | Network      | P1       | Medium     |
| 21  | `debug.log`                | Debug        | P0       | Low        |
| 22  | `debug.screenshot_on_fail` | Debug        | P0       | Medium     |


**Total MVP nodes: 22**

---

### 4.2 Advanced Nodes (Phase 2+)


| #   | Node                   | Category     | Value                    | Complexity |
| --- | ---------------------- | ------------ | ------------------------ | ---------- |
| 23  | `control.parallel`     | Control Flow | High (farm scale)        | High       |
| 24  | `ui.ocr`               | UI           | High (social apps)       | Medium     |
| 25  | `ui.image_match`       | UI           | Medium (games, canvas)   | Medium     |
| 26  | `data.json_transform`  | Data         | Medium                   | Low        |
| 27  | `data.extract_ui`      | Data         | Medium                   | Low        |
| 28  | `device.state`         | Device       | High (health monitoring) | Medium     |
| 29  | `device.rotate`        | Device       | Low                      | Low        |
| 30  | `network.webhook`      | Network      | Medium                   | Medium     |
| 31  | `network.proxy`        | Network      | High (anti-ban)          | High       |
| 32  | `ai.screen_understand` | AI           | Very High                | Medium     |
| 33  | `ai.auto_heal`         | AI           | Very High                | High       |
| 34  | `ai.generate_flow`     | AI           | High                     | Very High  |
| 35  | `ai.decide`            | AI           | High                     | High       |
| 36  | `debug.record_video`   | Debug        | Medium                   | Medium     |
| 37  | `debug.trace`          | Debug        | High (production)        | Medium     |


**Total advanced nodes: 15**
**Grand total: 37 nodes**

---

### 4.3 Cross-Platform Feasibility Matrix


| Node          | Android u2  | Android ADB | Android scrcpy | iOS WDA       | iOS XCUITest |
| ------------- | ----------- | ----------- | -------------- | ------------- | ------------ |
| Tap           | Full        | N/A         | Full           | Full          | Full         |
| Swipe         | Full        | Full        | Full           | Full          | Full         |
| Input Text    | Full        | Partial*    | N/A            | Full          | Full         |
| Key Event     | Full        | Full        | Full           | Partial**     | Partial**    |
| App Lifecycle | Full        | Full        | N/A            | Full          | Full         |
| Deep Link     | Full        | Full        | N/A            | Full          | N/A          |
| Find Element  | Full        | N/A         | N/A            | Full          | Full         |
| Screenshot    | Full (slow) | Full (slow) | Full (fast)    | Full          | Full         |
| OCR           | Server      | Server      | Server         | Server+Native | Server       |
| Image Match   | Server      | Server      | Server         | Server        | Server       |
| App Install   | Full        | Full        | N/A            | Partial***    | N/A          |
| Video Record  | Full        | Full        | Full           | Partial       | Partial      |


>  ADB `input text` chỉ hỗ trợ ASCII
> * iOS không có BACK key, hạn chế keycode
> ** iOS cần signing/provisioning

---

## 5. Gaps & Challenges in Real-World Implementation

### 5.1 Technical Challenges


| Challenge                            | Impact                                      | Mitigation                                                  |
| ------------------------------------ | ------------------------------------------- | ----------------------------------------------------------- |
| **minicap deprecated (Android 12+)** | Screen capture path broken                  | Migrate to scrcpy/WebRTC streaming                          |
| **iOS automation restrictions**      | WDA session instability, signing complexity | tidevice + auto-resign pipeline                             |
| **Selector fragility**               | Tests break on UI changes                   | Auto-healing + accessibility-first selector strategy        |
| **1000 device concurrent execution** | Resource bottleneck (CPU, network, storage) | Queue-based dispatch, artifact streaming, CDN for APK       |
| **AI node latency**                  | 1-5s per VLM call                           | Cache similar screens, batch requests, local model fallback |
| **Cross-device consistency**         | Same flow, different results per device     | Normalize coordinates (%), device-specific config profiles  |
| **Network reliability**              | WiFi ADB drops, USB hub failures            | Auto-reconnect watchdog, redundant connection paths         |


### 5.2 Architecture Gaps


| Gap                          | Description                                       | Suggested Solution                                       |
| ---------------------------- | ------------------------------------------------- | -------------------------------------------------------- |
| **Flow versioning**          | Không có version control cho workflow definitions | Git-based flow storage + migration system                |
| **Partial execution**        | Resume flow từ giữa chừng sau failure             | Checkpoint system với serialized state                   |
| **Cross-flow communication** | Flow A trigger Flow B trên device khác            | Event bus (Redis pub/sub, NATS)                          |
| **Secret management**        | Credentials trong flow definitions                | Vault integration (HashiCorp Vault, AWS Secrets Manager) |
| **Multi-tenant isolation**   | Nhiều team share farm                             | Namespace-based isolation, RBAC per device group         |


---

## 6. AI Workflow Generation from Natural Language

### 6.1 Architecture

```
┌──────────────────────────┐
│  Natural Language Input   │
│  "Test login with email   │
│   and verify dashboard"   │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│  Step 1: Intent Parser    │
│  (LLM: extract actions,  │
│   screens, assertions)    │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│  Step 2: App Knowledge    │
│  - Screen map (crawled)   │
│  - Element database       │
│  - Previous flows         │
│  - API schema             │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│  Step 3: Flow Generator   │
│  (LLM: map intent →      │
│   node graph + selectors) │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│  Step 4: Validator        │
│  - Dry run on real device │
│  - Selector verification  │
│  - Error detection        │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│  Step 5: Human Review     │
│  - Visual flow editor     │
│  - Approve / Edit / Reject│
└──────────────────────────┘
```

### 6.2 Prompt Pattern

```
System: You are a mobile test automation expert. Given an app description
and a test instruction, generate a workflow as a JSON node graph.

Available nodes: [list of 37 nodes with schemas]
App context: { screens, selectors, previous_flows }

User: "Test đăng ký tài khoản mới → nhập email random → nhập password
→ verify Welcome screen → logout"

Output: {
  "nodes": [...],
  "edges": [...],
  "variables": [...],
  "estimated_duration_s": 45
}
```

### 6.3 Key Challenges

- **Selector inference**: LLM không biết exact selector → cần app exploration database
- **Ambiguity resolution**: "login" có thể là email login, social login, phone login
- **Assertion quality**: LLM tend to under-specify assertions
- **Recommendation**: Dùng AI để generate ~80% flow, human polish 20%

---

## 7. Node Execution Engine Architecture (Python-Centric)

> **Design choice:** Toàn bộ stack dùng Python — phù hợp với ecosystem hiện tại
> (FastAPI, uiautomator2, facebook-wda, asyncio). Không pha Go/Node.

### 7.1 High-Level Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                 API Server (FastAPI + uvicorn)                │
│              /api/flows, /api/devices, /api/runs             │
│              WebSocket: /ws/runs/{id}/live                    │
└──────────┬────────────────────────────────┬──────────────────┘
           │                                │
           ▼                                ▼
┌──────────────────────┐        ┌──────────────────────────┐
│   Flow Store (DB)    │        │   Task Queue             │
│   SQLite (dev) /     │        │   Celery + Redis         │
│   PostgreSQL (prod)  │        │   (or Dramatiq/arq)      │
│   - flow definitions │        │                          │
│   - run history      │        │   Queues:                │
│   - device registry  │        │   - flow.dispatch        │
└──────────────────────┘        │   - node.execute         │
                                │   - result.collect       │
        ┌───────────────┐       └──────────┬───────────────┘
        │  Redis         │                  │
        │  - var store   │     ┌────────────┼────────────┐
        │  - pub/sub     │     │            │            │
        │  - device lock │     ▼            ▼            ▼
        └───────────────┘  ┌──────────┐ ┌──────────┐ ┌──────────┐
                           │ Worker 1 │ │ Worker 2 │ │ Worker N │
                           │ (Python) │ │ (Python) │ │ (Python) │
                           │          │ │          │ │          │
                           │ ┌──────┐ │ │          │ │          │
                           │ │ Node │ │ │          │ │          │
                           │ │Engine│ │ │          │ │          │
                           │ │      │ │ │          │ │          │
                           │ │ DAG  │ │ │          │ │          │
                           │ │ Walk │ │ │          │ │          │
                           │ └──┬───┘ │ │          │ │          │
                           │    │     │ │          │ │          │
                           │ ┌──▼───┐ │ │          │ │          │
                           │ │Driver│ │ │          │ │          │
                           │ │- u2  │ │ │          │ │          │
                           │ │- wda │ │ │          │ │          │
                           │ │- adb │ │ │          │ │          │
                           │ │-scrcpy│ │ │          │ │          │
                           │ └──────┘ │ │          │ │          │
                           └────┬─────┘ └────┬─────┘ └────┬─────┘
                                │            │            │
                                ▼            ▼            ▼
┌──────────────────────────────────────────────────────────────┐
│                     Device Pool (1000+)                       │
│   ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐   │
│   │Phone 1 │ │Phone 2 │ │Phone 3 │ │  ...   │ │Phone N │   │
│   └────────┘ └────────┘ └────────┘ └────────┘ └────────┘   │
└──────────────────────────────────────────────────────────────┘
```

### 7.2 Component Responsibilities


| Component            | Technology (Python)                                  | Responsibility                                                                   |
| -------------------- | ---------------------------------------------------- | -------------------------------------------------------------------------------- |
| **API Server**       | FastAPI + uvicorn                                    | REST API, WebSocket live feed, auth (JWT), rate limiting                         |
| **Flow Store**       | SQLAlchemy + PostgreSQL (prod) / SQLite (dev)        | Flow definitions (JSON DAG), run history, artifact refs                          |
| **Task Queue**       | Celery + Redis (hoặc Dramatiq / arq cho lightweight) | Async dispatch, node execution, result collection                                |
| **Variable Store**   | Redis                                                | Workflow variables (flow/global/device scope), pub/sub events, distributed locks |
| **Executor Worker**  | Celery worker (Python process)                       | Interpret DAG, execute nodes, manage device session                              |
| **Node Engine**      | Custom Python module (`engine/`)                     | DAG walker, condition evaluator, retry/timeout logic                             |
| **Device Driver**    | uiautomator2, facebook-wda, adb-shell, scrcpy-client | Abstract layer — unified interface per platform                                  |
| **Result Collector** | Celery task / FastAPI background task                | Aggregate results, generate reports, trigger webhooks                            |
| **Artifact Storage** | MinIO / local filesystem (dev)                       | Screenshots, videos, logs, UI dumps                                              |


### 7.3 Key Python Libraries

```
# requirements.txt (node engine)

# API
fastapi>=0.110
uvicorn[standard]
python-jose[cryptography]   # JWT auth

# Task Queue (chọn 1)
celery[redis]>=5.3           # Option A: battle-tested, feature-rich
# dramatiq[redis]            # Option B: simpler, lighter
# arq                        # Option C: asyncio-native, minimal

# Database
sqlalchemy>=2.0
alembic                      # migrations
asyncpg                      # PostgreSQL async driver
aiosqlite                    # SQLite async (dev)

# Device Interaction
uiautomator2>=3.0            # Android automation
facebook-wda>=1.4            # iOS automation (WDA)
adb-shell[usb]               # ADB direct (no binary needed)
# scrcpy-client              # Screen streaming (optional)

# Redis
redis[hiredis]>=5.0          # Variable store + pub/sub + Celery broker

# AI & Vision
httpx                        # Async HTTP (for AI API calls)
paddleocr                    # OCR (Vietnamese/CJK)
opencv-python-headless       # Image matching
Pillow                       # Screenshot processing

# Data & Utils
faker                        # Random data generation
jmespath                     # JSON transform
pydantic>=2.0                # Node schema validation
networkx                     # DAG graph operations

# Observability
opentelemetry-api            # Distributed tracing
opentelemetry-sdk
prometheus-client            # Metrics export
loguru                       # Structured logging
```

### 7.4 Node Engine Core (Python Implementation Sketch)

```python
# engine/node_base.py
from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import Any

class NodeContext(BaseModel):
    """Shared execution context passed through DAG"""
    flow_id: str
    run_id: str
    device_id: str
    variables: dict[str, Any]     # flow-scope vars
    device_driver: Any            # u2.Device | wda.Client
    artifacts_dir: str

class NodeResult(BaseModel):
    status: str                   # "success" | "failed" | "skipped"
    outputs: dict[str, Any]
    elapsed_ms: float
    error: str | None = None
    artifacts: list[str] = []     # paths to screenshots, etc.

class BaseNode(ABC):
    """Base class for all automation nodes"""
    node_type: str
    category: str

    def __init__(self, config: dict):
        self.config = config
        self.timeout_ms = config.get("timeout_ms", 30000)
        self.retry = config.get("retry", {"max": 0, "delay_ms": 1000})

    @abstractmethod
    async def execute(self, ctx: NodeContext, inputs: dict) -> NodeResult:
        ...
```

```python
# engine/nodes/action_tap.py
import uiautomator2 as u2
from engine.node_base import BaseNode, NodeContext, NodeResult

class TapNode(BaseNode):
    node_type = "action.tap"
    category = "Action"

    async def execute(self, ctx: NodeContext, inputs: dict) -> NodeResult:
        d: u2.Device = ctx.device_driver
        cfg = self.config

        if cfg.get("strategy") == "element":
            selector = cfg["selector"]
            el = d(**{selector["type"]: selector["value"]})
            if cfg.get("tap_type") == "long_press":
                el.long_click(duration=cfg.get("long_press_duration_ms", 1000) / 1000)
            else:
                el.click()
            bounds = el.info.get("bounds", {})
        elif cfg.get("strategy") == "coordinate":
            x, y = cfg["coordinates"]["x"], cfg["coordinates"]["y"]
            d.click(x, y)
            bounds = {"x": x, "y": y}
        else:
            raise ValueError(f"Unknown tap strategy: {cfg.get('strategy')}")

        return NodeResult(
            status="success",
            outputs={"success": True, "actual_coordinates": bounds},
            elapsed_ms=0  # filled by engine wrapper
        )
```

```python
# engine/dag_executor.py
import asyncio
import networkx as nx
from engine.node_base import NodeContext, NodeResult
from engine.node_registry import get_node_class

class DAGExecutor:
    """Walk a DAG of nodes, executing each in topological order"""

    def __init__(self, flow_def: dict, ctx: NodeContext):
        self.ctx = ctx
        self.graph = nx.DiGraph()
        self.node_instances = {}
        self.results: dict[str, NodeResult] = {}
        self._build_graph(flow_def)

    def _build_graph(self, flow_def: dict):
        for node_def in flow_def["nodes"]:
            nid = node_def["id"]
            cls = get_node_class(node_def["type"])
            self.node_instances[nid] = cls(node_def.get("config", {}))
            self.graph.add_node(nid)
        for edge in flow_def["edges"]:
            self.graph.add_edge(edge["from"], edge["to"], port=edge.get("port"))

    async def run(self) -> dict[str, NodeResult]:
        for nid in nx.topological_sort(self.graph):
            node = self.node_instances[nid]
            inputs = self._resolve_inputs(nid)

            # Retry + timeout wrapper
            result = await self._execute_with_retry(node, inputs)
            self.results[nid] = result

            if result.status == "failed" and node.config.get("on_error") == "fail":
                break  # stop flow

            # Control flow: evaluate branches
            if node.category == "ControlFlow":
                self._prune_branches(nid, result)

        return self.results

    async def _execute_with_retry(self, node, inputs) -> NodeResult:
        max_retries = node.retry.get("max", 0)
        for attempt in range(max_retries + 1):
            try:
                result = await asyncio.wait_for(
                    node.execute(self.ctx, inputs),
                    timeout=node.timeout_ms / 1000
                )
                if result.status == "success":
                    return result
            except asyncio.TimeoutError:
                result = NodeResult(status="failed", outputs={},
                                    elapsed_ms=node.timeout_ms, error="Timeout")
            except Exception as e:
                result = NodeResult(status="failed", outputs={},
                                    elapsed_ms=0, error=str(e))

            if attempt < max_retries:
                await asyncio.sleep(node.retry.get("delay_ms", 1000) / 1000)

        return result

    def _resolve_inputs(self, nid: str) -> dict:
        """Collect outputs from predecessor nodes"""
        inputs = {}
        for pred in self.graph.predecessors(nid):
            edge_data = self.graph.edges[pred, nid]
            port = edge_data.get("port", "default")
            if pred in self.results:
                inputs[port] = self.results[pred].outputs
        return inputs

    def _prune_branches(self, nid: str, result: NodeResult):
        """For if/else, switch — remove edges to non-taken branches"""
        # Implementation depends on control flow node type
        pass
```

```python
# engine/celery_tasks.py
from celery import Celery
import uiautomator2 as u2
from engine.dag_executor import DAGExecutor
from engine.node_base import NodeContext

app = Celery("device_farm", broker="redis://localhost:6379/0")

@app.task(bind=True, max_retries=1)
def execute_flow(self, flow_def: dict, device_serial: str, run_id: str):
    """Celery task: execute a full flow on a device"""
    # Connect to device
    d = u2.connect(device_serial)

    ctx = NodeContext(
        flow_id=flow_def["id"],
        run_id=run_id,
        device_id=device_serial,
        variables={},
        device_driver=d,
        artifacts_dir=f"/data/artifacts/{run_id}/"
    )

    # Run DAG
    import asyncio
    executor = DAGExecutor(flow_def, ctx)
    results = asyncio.run(executor.run())

    # Collect and return summary
    return {
        "run_id": run_id,
        "device": device_serial,
        "total_nodes": len(results),
        "passed": sum(1 for r in results.values() if r.status == "success"),
        "failed": sum(1 for r in results.values() if r.status == "failed"),
        "results": {k: v.model_dump() for k, v in results.items()}
    }
```

```python
# web/server.py (FastAPI endpoints for flow execution)
from fastapi import FastAPI, WebSocket
from engine.celery_tasks import execute_flow

app = FastAPI(title="Device Farm Node Engine")

@app.post("/api/flows/{flow_id}/run")
async def run_flow(flow_id: str, body: dict):
    """Dispatch flow execution to Celery worker"""
    flow_def = await get_flow_from_db(flow_id)
    device = await find_available_device(body.get("device_filter", {}))

    run_id = generate_run_id()
    task = execute_flow.delay(flow_def, device.serial, run_id)

    return {"run_id": run_id, "task_id": task.id, "device": device.serial}

@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    """Get run status and results"""
    return await get_run_from_db(run_id)

@app.websocket("/ws/runs/{run_id}/live")
async def run_live(websocket: WebSocket, run_id: str):
    """Stream live execution updates via WebSocket"""
    await websocket.accept()
    async for event in subscribe_run_events(run_id):
        await websocket.send_json(event)
```

### 7.5 Execution Flow

```
1. Client POST /api/flows/{flow_id}/run {"device_filter": {"platform": "android"}}
   → FastAPI validates flow, finds available device
   → Creates Run record in DB (status: "pending")
   → Dispatches Celery task: execute_flow.delay(flow_def, device, run_id)

2. Celery Worker picks up task
   → Connects to device: u2.connect(serial) or wda.Client(url)
   → Builds DAG (networkx graph) from flow definition
   → Walks nodes in topological order

3. Per-node execution:
   → Resolve inputs from predecessor outputs + variables (Redis)
   → Execute with asyncio.wait_for (timeout) + retry loop
   → Store result in context
   → Publish progress event → Redis pub/sub → WebSocket to client
   → If control flow node: evaluate condition, prune branches

4. On completion:
   → Upload artifacts (screenshots, logs) to MinIO / local storage
   → Update Run record in DB (status: "passed" | "failed")
   → Trigger webhook notification if configured
   → Release device back to pool
```

### 7.6 Scaling Strategy


| Scale             | Strategy                                                      | Python Config                                |
| ----------------- | ------------------------------------------------------------- | -------------------------------------------- |
| **10 devices**    | Single Celery worker, Redis local                             | `celery -A engine worker -c 10`              |
| **100 devices**   | 5-10 worker processes, Redis cluster                          | `celery -A engine worker -c 20` × 5 machines |
| **500 devices**   | Celery multi + priority queues, dedicated AI workers          | Separate queue cho AI nodes (GPU machine)    |
| **1000+ devices** | Multi-region, Celery + Redis Cluster, sharded by device group | Edge workers co-located with device racks    |


### 7.7 Technology Stack (100% Python)


| Concern               | Technology                          | Why                                                                |
| --------------------- | ----------------------------------- | ------------------------------------------------------------------ |
| **API Server**        | FastAPI + uvicorn                   | Async, WebSocket native, OpenAPI docs, Python ecosystem            |
| **Task Queue**        | Celery + Redis                      | Battle-tested, 1M+ tasks/day, priority queues, monitoring (Flower) |
| **Database**          | PostgreSQL + SQLAlchemy 2.0         | Async support, reliable, JSON columns cho flow defs                |
| **Cache / Pub-sub**   | Redis                               | Variable store, device locks, real-time events                     |
| **Android driver**    | uiautomator2                        | Direct HTTP to atx-agent, no Appium overhead                       |
| **iOS driver**        | facebook-wda                        | Direct HTTP to WebDriverAgent                                      |
| **ADB transport**     | adb-shell                           | Pure Python, no adb binary needed                                  |
| **DAG engine**        | networkx                            | Graph operations, topological sort, cycle detection                |
| **Schema validation** | Pydantic v2                         | Node config/input/output validation, serialization                 |
| **OCR**               | PaddleOCR                           | Best Vietnamese/CJK support, Python native                         |
| **Image matching**    | OpenCV (headless)                   | Template matching, feature detection                               |
| **AI/LLM**            | httpx + anthropic/openai SDK        | Async API calls to Claude/GPT                                      |
| **Artifact storage**  | MinIO (S3-compatible) / boto3       | Self-hosted, lifecycle policies                                    |
| **Monitoring**        | prometheus-client + Grafana         | Executor metrics, queue depth, device health                       |
| **Logging**           | loguru + OpenTelemetry              | Structured logging + distributed tracing                           |
| **Real-time UI**      | FastAPI WebSocket + htmx/vanilla JS | Live execution status, no React dependency                         |


### 7.8 Project Structure

```
device_farm/
├── main.py                          # uvicorn entry point
├── config.yaml                      # configuration
├── requirements.txt
│
├── web/
│   ├── server.py                    # FastAPI app
│   ├── routes/
│   │   ├── flows.py                 # CRUD flows
│   │   ├── runs.py                  # Execute + monitor runs
│   │   ├── devices.py               # Device management
│   │   └── auth.py                  # JWT auth
│   ├── websocket.py                 # Live execution feed
│   └── templates/
│       ├── dashboard.html           # Device grid
│       └── flow_editor.html         # Visual node editor
│
├── engine/
│   ├── node_base.py                 # BaseNode ABC, NodeContext, NodeResult
│   ├── node_registry.py             # Auto-discover + register node classes
│   ├── dag_executor.py              # DAG walker (networkx)
│   ├── expression_eval.py           # Safe expression evaluator (for if/else)
│   ├── variable_store.py            # Redis-backed variable get/set
│   │
│   ├── nodes/                       # One file per node
│   │   ├── __init__.py
│   │   ├── control_if_else.py
│   │   ├── control_loop.py
│   │   ├── control_retry.py
│   │   ├── control_switch.py
│   │   ├── control_timeout.py
│   │   ├── action_tap.py
│   │   ├── action_swipe.py
│   │   ├── action_input_text.py
│   │   ├── action_key_event.py
│   │   ├── action_app_lifecycle.py
│   │   ├── action_deep_link.py
│   │   ├── ui_find_element.py
│   │   ├── ui_wait_element.py
│   │   ├── ui_assert.py
│   │   ├── ui_screenshot.py
│   │   ├── ui_ocr.py
│   │   ├── ui_image_match.py
│   │   ├── data_variable.py
│   │   ├── data_random.py
│   │   ├── data_json_transform.py
│   │   ├── data_extract_ui.py
│   │   ├── device_app_install.py
│   │   ├── device_info.py
│   │   ├── device_state.py
│   │   ├── device_rotate.py
│   │   ├── network_http.py
│   │   ├── network_webhook.py
│   │   ├── network_proxy.py
│   │   ├── ai_screen_understand.py
│   │   ├── ai_auto_heal.py
│   │   ├── ai_generate_flow.py
│   │   ├── ai_decide.py
│   │   ├── debug_log.py
│   │   ├── debug_screenshot_on_fail.py
│   │   ├── debug_record_video.py
│   │   └── debug_trace.py
│   │
│   └── drivers/
│       ├── base_driver.py           # Abstract device driver interface
│       ├── android_u2_driver.py     # uiautomator2 wrapper
│       ├── android_adb_driver.py    # adb-shell wrapper
│       ├── ios_wda_driver.py        # facebook-wda wrapper
│       └── scrcpy_driver.py         # Screen streaming driver
│
├── farm/
│   ├── device_manager.py            # Device registry + pool
│   ├── device_client.py             # Per-device state machine
│   ├── task_queue.py                # Celery task definitions
│   ├── dispatcher.py                # Assign devices to runs
│   └── watchdog.py                  # Health checks + auto-reconnect
│
├── storage/
│   ├── db.py                        # SQLAlchemy models + engine
│   ├── models.py                    # Flow, Run, Device, Artifact models
│   └── artifact_store.py            # MinIO / local file storage
│
└── tests/
    ├── test_nodes/                  # Unit tests per node
    ├── test_engine/                 # DAG executor tests
    └── test_api/                    # FastAPI endpoint tests
```

---

## 8. Change Log


| Date       | Version | Changes                                    | Author                      |
| ---------- | ------- | ------------------------------------------ | --------------------------- |
| 2026-03-28 | 1.0     | Initial node catalog + architecture design | Mobile Automation Architect |


