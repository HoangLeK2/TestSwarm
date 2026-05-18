# Airtest + Poco — Product Requirements Document (Research)

---

- **Product Name:** Airtest (image-based) + Poco (UI hierarchy-based)
- **Developer:** NetEase Games (Guangzhou, China)
- **License:** Apache License 2.0
- **GitHub:** [Airtest](https://github.com/AirtestProject/Airtest) (9,242★) | [Poco](https://github.com/AirtestProject/Poco) (1,917★)
- **Version:** Airtest 1.4.3 | Poco (pocoui) 1.0.94
- **PyPI:** `pip install airtest` | `pip install pocoui`
- **Last Updated:** 2026-03-28
- **Status:** Active (maintained by NetEase)

---

## 1. Executive Summary

### Airtest + Poco là gì?

**Airtest** và **Poco** là cặp framework automation của NetEase, thiết kế để **bổ sung cho nhau**:

| | Airtest | Poco |
|---|---------|------|
| **Phương pháp** | Image recognition (OpenCV) | UI hierarchy traversal |
| **Detect element** | Screenshot → template matching | Query render tree / accessibility tree |
| **Khi nào dùng** | Animation, splash screen, game UI, visual verification | Native app buttons, text fields, đọc text |
| **Cần inject SDK?** | Không (screenshot-based) | Game engines: Có. Native apps: Không |
| **Speed** | Chậm hơn (CV processing 50-500ms) | Nhanh hơn (direct API ~200ms) |

```python
# Hybrid: dùng cả 2 trong cùng 1 script
from airtest.core.api import *
from poco.drivers.android.uiautomation import AndroidUiautomationPoco

# Airtest: image-based (khi UI tree không available)
wait(Template("splash_done.png"))

# Poco: hierarchy-based (khi cần interact với native elements)
poco = AndroidUiautomationPoco()
poco("login_button").click()
poco("email_field").set_text("test@mail.com")
```

### Tại sao quan trọng cho Device Farm

| Capability | Ứng dụng |
|-----------|----------|
| Image matching (7 algorithms) | Visual assertion, detect custom UI, game automation |
| UI hierarchy parsing | Đọc text, find element, stable selectors |
| Cross-platform (Android + iOS + Game engines) | Unified automation API |
| Built-in HTML reports | Test result reporting không cần external tool |
| Multi-device support | Process-per-device model |
| AirtestIDE | Record test bằng click trên screen |
| `.air` test format | Portable test case (code + images + logs) |

---

## 2. Architecture

### 2.1 Airtest Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    airtest.core.api                       │
│  touch() swipe() wait() exists() assert_exists()        │
│  text() keyevent() snapshot() install() start_app()     │
└──────────────────────┬──────────────────────────────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
┌──────────────┐ ┌──────────┐ ┌──────────┐
│ airtest.cv   │ │ Android  │ │ iOS      │
│              │ │ Driver   │ │ Driver   │
│ Template     │ │          │ │          │
│ TemplateMatch│ │ ADB      │ │ WDA      │
│ MultiScale   │ │ Minicap  │ │ tidevice │
│ SIFT/BRISK   │ │ Minitouch│ │          │
│ KAZE/ORB     │ │ Maxtouch │ │          │
│ (OpenCV)     │ │ JavaCap  │ │          │
└──────────────┘ └──────────┘ └──────────┘
                       │
              ┌────────▼────────┐
              │  Android Device  │
              │  • minicap       │
              │  • minitouch     │
              │  • maxtouch.jar  │
              │  • Yosemite IME  │
              └─────────────────┘
```

### 2.2 Poco Architecture

```
┌─────────────────────────────────────────────┐
│              Poco (Python client)             │
│                                               │
│  poco("name", type="Button").click()         │
│  poco("list").child("item")[0].get_text()    │
│                                               │
│  ┌─────────────────────────────────────────┐ │
│  │           UIObjectProxy                  │ │
│  │  (lazy-evaluated element reference)      │ │
│  │  .click() .swipe() .get_text() .exists() │ │
│  │  .child() .sibling() .offspring()        │ │
│  └────────────────┬────────────────────────┘ │
│                   │                           │
│  ┌────────────────▼────────────────────────┐ │
│  │           PocoAgent                      │ │
│  │  hierarchy + input + screen interfaces   │ │
│  └────────────────┬────────────────────────┘ │
└───────────────────┼───────────────────────────┘
                    │
     ┌──────────────┼──────────────────┐
     ▼              ▼                  ▼
┌──────────┐  ┌───────────┐  ┌──────────────┐
│ Android  │  │   iOS     │  │  Game Engine │
│ UIAutom. │  │   WDA     │  │  (Unity,     │
│ Poco     │  │   Poco    │  │   Cocos,     │
│          │  │           │  │   UE4)       │
│ pocoserv │  │ WDA JSON  │  │              │
│ ice APK  │  │ source    │  │  Poco SDK    │
│ (port    │  │ dump      │  │  (TCP :5001) │
│ 10080)   │  │           │  │              │
└──────────┘  └───────────┘  └──────────────┘
```

### 2.3 Poco Driver cho từng Platform

| Platform | Driver | Communication | Cần SDK? |
|----------|--------|--------------|----------|
| **Android native** | `AndroidUiautomationPoco` | pocoservice APK → ADB forward :10080 | Không |
| **iOS native** | `iosPoco` | WDA → JSON/XML source dump | Không |
| **Unity3D** | `UnityPoco` | TCP socket :5001 → RPC | **Có** (C# SDK) |
| **Cocos2dx** | `StdPoco` | TCP socket → RPC | **Có** (Lua/JS SDK) |
| **UE4** | UE4 driver | TCP → RPC | **Có** |
| **Windows** | `WindowsUIPoco` | pywinauto | Không |

---

## 3. Airtest — Image Recognition Deep Dive

### 3.1 Template Matching Algorithms

Airtest có **7+ algorithms**, thử theo thứ tự (configurable):

```python
# Default strategy chain
Settings.CVSTRATEGY = ["mstpl", "tpl", "sift", "brisk"]
```

| Algorithm | Class | Mô tả | Speed | Accuracy |
|-----------|-------|-------|-------|----------|
| **mstpl** | `MultiScaleTemplateMatchingPre` | Multi-scale + position hint (PRIMARY) | 50-200ms | Cao nhất |
| **tpl** | `TemplateMatching` | Standard `cv2.matchTemplate(TM_CCOEFF_NORMED)` | 10-50ms | Tốt |
| **gmstpl** | `MultiScaleTemplateMatching` | Global multi-scale (no hint) | 100-300ms | Cao |
| **sift** | `SIFTMatching` | Keypoint SIFT (cần opencv-contrib) | 100-500ms | Rất cao |
| **brisk** | `BRISKMatching` | Keypoint BRISK + BFMatcher(HAMMING) | 100-300ms | Tốt |
| **kaze** | `KAZEMatching` | Keypoint KAZE | 200-500ms | Cao |
| **orb** | `ORBMatching` | Keypoint ORB (fastest keypoint) | 50-200ms | Trung bình |
| **akaze** | `AKAZEMatching` | Keypoint AKAZE | 100-300ms | Tốt |

### 3.2 Matching Process

```
1. Screenshot từ device (minicap/javacap/adbcap)
2. Load template image (.png từ .air directory)
3. Resize template dựa trên record_resolution vs current_resolution
4. Thử algorithm đầu tiên trong chain:
   ├─ tpl: grayscale → cv2.matchTemplate → find max location
   │       → if rgb=True: verify BGR 3-channel confidence
   │       → if confidence >= threshold (0.7): MATCH
   ├─ mstpl: predict position + multi-scale search
   │         → iterate scales (step=0.005, max=800px)
   │         → if match: FOUND
   ├─ sift/brisk/kaze: detect keypoints → match descriptors
   │                    → compute homography → verify
   └─ Nếu fail → thử algorithm tiếp theo
5. Return: { result: (x,y), rectangle: [...], confidence: 0.95 }
   Hoặc: TargetNotFoundError (sau 20s timeout)
```

### 3.3 Key Settings

```python
from airtest.core.settings import Settings

Settings.THRESHOLD = 0.7           # Match confidence (0-1)
Settings.FIND_TIMEOUT = 20         # Max wait time (seconds)
Settings.FIND_TIMEOUT_TMP = 3      # Quick check timeout (exists())
Settings.SNAPSHOT_QUALITY = 10     # JPEG quality (1-99)
Settings.OPDELAY = 0.1            # Delay between operations
Settings.CVSTRATEGY = ["mstpl", "tpl", "sift", "brisk"]
Settings.IMAGE_MAXSIZE = 1200      # Max screenshot dimension
```

### 3.4 Template Class

```python
from airtest.core.cv import Template

# Basic template
btn = Template("login_button.png")

# With parameters
btn = Template(
    "login_button.png",
    threshold=0.8,           # Override global threshold
    target_pos=5,            # 1-9 numpad position (5=center)
    record_pos=(0.5, 0.3),  # Position hint (where it was on screen during recording)
    resolution=(1080, 1920), # Recording resolution
    rgb=True,                # Match colors (not just shape)
)

# Usage
touch(btn)                    # Tap on matched location
pos = exists(btn)            # Quick check, returns (x,y) or False
wait(btn, timeout=10)        # Wait until visible
assert_exists(btn)           # Assert visible
results = find_all(btn)      # Find all occurrences
```

---

## 4. Poco — UI Hierarchy Deep Dive

### 4.1 Selector Engine

```python
from poco.drivers.android.uiautomation import AndroidUiautomationPoco
poco = AndroidUiautomationPoco()

# === Basic Selection ===
poco("Login")                           # by name
poco("Login", type="Button")           # by name + type
poco(text="Submit")                     # by text attribute
poco(textMatches="^Login.*$")          # by regex
poco(text="OK", enable=True)           # by text + property

# === Relative Selection ===
poco("parent").child("child_name")     # direct child
poco("parent").offspring("deep_child") # any descendant
poco("node").sibling("sibling_name")   # sibling
poco("node").parent()                   # parent

# === Indexing ===
items = poco("list_item")
items[0].click()                        # first match
items[-1].click()                       # last match
len(items)                              # count
for item in items:                      # iterate (L→R, U→D order)
    print(item.get_text())
```

**Important:** Selection is **lazy** — query chỉ execute khi gọi action/attribute.

### 4.2 Complete Poco API

**Actions:**

```python
# Tap
poco("btn").click()
poco("btn").click(focus=(0.5, 0.5))    # click at specific point within element
poco("btn").double_click()
poco("btn").long_click(duration=2.0)

# Swipe
poco("list").swipe("up")               # swipe up
poco("list").swipe([0.2, -0.2])        # swipe by vector
poco("card").swipe("left", duration=0.5)

# Drag
poco("item").drag_to(poco("target"))

# Scroll
poco("scrollview").scroll(direction="vertical", percent=0.6, duration=2.0)

# Pinch
poco("map").pinch("in", percent=0.6)   # zoom in
poco("map").pinch("out", percent=0.6)  # zoom out

# Text input
poco("input_field").set_text("Hello World")
poco("input_field").click()             # focus first, then type

# Focus point (for operations relative to element)
poco("btn").focus([0.1, 0.1]).click()  # click top-left corner
```

**Attribute Access:**

```python
# Read attributes
text = poco("label").get_text()
name = poco("node").get_name()
size = poco("box").get_size()           # [width, height] as % of screen
pos = poco("btn").get_position()        # [x, y] as % of screen (0-1)
bounds = poco("btn").get_bounds()       # bounding box

# Check existence
if poco("popup").exists():
    poco("popup").child("dismiss").click()

# Any attribute
value = poco("node").attr("enabled")
visible = poco("node").attr("visible")
```

**Waiting:**

```python
# Wait for element
poco("loading").wait_for_disappearance(timeout=30)
poco("content").wait_for_appearance(timeout=20)

# Wait for any of multiple elements
result = poco.wait_for_any([
    poco("success_dialog"),
    poco("error_dialog"),
], timeout=15)

# Wait for all
poco.wait_for_all([
    poco("image_loaded"),
    poco("text_loaded"),
], timeout=20)
```

**Optimization:**

```python
# Freeze UI hierarchy (snapshot — avoid repeated dumps)
frozen = poco.freeze()
frozen("btn1").click()     # fast: uses cached hierarchy
frozen("btn2").get_text()  # fast: no re-dump
# Caveat: frozen state may be stale if UI changed
```

### 4.3 Coordinate System

```
Poco dùng normalized coordinates [0, 1]:
  (0, 0) = top-left
  (1, 1) = bottom-right
  (0.5, 0.5) = center

# Raw coordinate operations
poco.click([0.5, 0.5])           # tap center of screen
poco.swipe([0.5, 0.8], [0.5, 0.2])  # swipe up
poco.swipe([0.5, 0.5], direction=[0, -0.5])  # swipe up by vector
```

---

## 5. Device Connection

### 5.1 Android Connection Methods

```python
from airtest.core.api import connect_device, auto_setup

# === Local USB ===
connect_device("Android:///")                    # auto-detect single device
connect_device("Android:///SERIAL_NUMBER")       # specific device

# === Remote ADB (Device Farm) ===
connect_device("Android://192.168.1.100:5037/SERIAL")  # remote ADB server

# === WiFi ADB ===
connect_device("Android:///10.0.0.5:5555")      # wireless ADB

# === With specific methods ===
connect_device("Android:///SERIAL?cap_method=JAVACAP&touch_method=MAXTOUCH")
connect_device("Android:///SERIAL?cap_method=MINICAP&ori_method=MINICAPORT")

# === auto_setup (recommended for scripts) ===
auto_setup(
    __file__,
    devices=["Android:///device1", "Android:///device2"],
    logdir=True,          # enable logging
    project_root=".",     # template image search path
    compress=12,          # screenshot compression
)
```

### 5.2 Screen Capture Methods

| Method | Class | Speed | Compatibility | Notes |
|--------|-------|-------|--------------|-------|
| **MINICAP** | `Minicap` | ~30-60 FPS | Android ≤11 (issues on 12+) | Binary push, socket streaming. Default |
| **JAVACAP** | `Javacap` | ~5-15 FPS | Broad (MIUI 11+ recommended) | Yosemite APK, `app_process` |
| **ADBCAP** | `AdbCap` | ~1-3 FPS | Universal | `adb shell screencap`. Slowest, always works |

**Auto-fallback:** Airtest thử MINICAP → JAVACAP → ADBCAP. Nếu method fail thì tự chuyển sang method tiếp.

### 5.3 Touch Methods

| Method | Class | Speed | Android Version | Notes |
|--------|-------|-------|----------------|-------|
| **MINITOUCH** | `Minitouch` | ~10-50ms | ≤ Android 9 | STF binary, multitouch |
| **MAXTOUCH** | `Maxtouch` | ~10-50ms | Android 10+ | Java-based (`app_process`), multitouch |
| **ADBTOUCH** | ADB | ~200-500ms | Universal | `adb shell input tap`. Last resort |

**Auto-upgrade:** Android 10+ tự động chuyển từ MINITOUCH → MAXTOUCH.

### 5.4 iOS Connection

```python
# iOS via WDA (WebDriverAgent / iOS-Tagent)
connect_device("iOS:///http://localhost:8100")

# With MJPEG streaming + specific UDID
connect_device("iOS:///http://localhost:8100?mjpeg_port=9100&udid=DEVICE_UDID")

# Dependencies: tidevice + WDA (iOS-Tagent recommended)
```

### 5.5 Multi-Device

```python
from airtest.core.api import connect_device, set_current, device

# Connect multiple devices
dev1 = connect_device("Android:///serial1")
dev2 = connect_device("Android:///serial2")
dev3 = connect_device("Android:///serial3")

# Switch active device
set_current(0)  # → dev1
touch(Template("button.png"))

set_current(1)  # → dev2
touch(Template("button.png"))

# Get current device
d = device()
print(d.serialno)
```

**WARNING:** Airtest dùng **global state** (`G.DEVICE`). `set_current()` switch global context. Chạy parallel → **phải dùng separate processes** (không phải threads).

---

## 6. Airtest Complete API

### 6.1 Device Operations

```python
from airtest.core.api import *

# App management
start_app("com.example.app")              # Launch app
start_app("com.example.app", ".MainActivity")  # Launch specific activity
stop_app("com.example.app")               # Force stop
clear_app("com.example.app")              # Clear data
install("/path/to/app.apk")               # Install (supports -r -t flags)
uninstall("com.example.app")              # Uninstall

# Device control
wake()                                     # Wake + unlock screen
home()                                     # Press HOME
snapshot("screenshot.png", quality=80)    # Take screenshot
shell("dumpsys battery")                   # Execute shell command

# File operations
push("/local/file.txt", "/sdcard/file.txt")   # Push to device
pull("/sdcard/file.txt", "/local/file.txt")   # Pull from device

# Clipboard
set_clipboard("Hello")
text = get_clipboard()
paste()
```

### 6.2 Input Operations

```python
# Tap (image-based)
touch(Template("login_btn.png"))
touch(Template("btn.png"), times=2)       # Double tap
touch((500, 800))                          # Tap coordinates

# Long press
touch(Template("item.png"), duration=2)

# Swipe
swipe(Template("start.png"), Template("end.png"))
swipe((300, 800), (300, 200))             # Swipe by coordinates
swipe((500, 500), vector=(0, -0.5))       # Swipe by vector

# Pinch (requires minitouch/maxtouch)
pinch("in", center=(500, 500), percent=0.5)
pinch("out")

# Key events
keyevent("BACK")
keyevent("HOME")
keyevent("ENTER")
keyevent("VOLUME_UP")

# Text input
text("Hello World")
text("Hello", enter=True)                 # Type + press Enter
```

### 6.3 Wait / Find / Assert

```python
# Wait for image (default 20s timeout)
wait(Template("element.png"))
wait(Template("element.png"), timeout=10, interval=0.5)

# Check existence (quick, 3s timeout)
pos = exists(Template("popup.png"))
if pos:
    touch(pos)

# Find all occurrences
results = find_all(Template("star_icon.png"))
for r in results:
    print(r["result"])      # (x, y) center
    print(r["confidence"])  # match confidence
    print(r["rectangle"])   # bounding box

# Assertions
assert_exists(Template("success.png"), "Login should succeed")
assert_not_exists(Template("error.png"), "No error should appear")
assert_equal(actual, expected, "Values should match")
assert_true(condition, "Condition should be true")
```

---

## 7. Reporting & CI/CD

### 7.1 HTML Report

```bash
# Generate report from CLI
airtest report "path/to/test.air" --log_root log/ --outfile report.html

# Report includes:
# • Screenshot at each step (touch, swipe, assert)
# • Step description + timestamp
# • Pass/fail status
# • Image matching details (confidence, matched region)
# • Total execution time
```

```python
# Generate report programmatically
from airtest.report.report import LogToHtml

h = LogToHtml(
    script_root="test.air",
    log_root="test.air/log",
    export_dir="report/",
    logfile="log.txt",
)
h.report()
```

### 7.2 Log Format

Airtest logs JSON lines to `log.txt`:

```json
{"tag": "touch", "depth": 0, "time": "2026-03-28 10:00:01",
 "data": {"target_pos": [540, 960], "confidence": 0.95}}
{"tag": "assert_exists", "depth": 0, "time": "2026-03-28 10:00:03",
 "data": {"args": ["success.png"], "ret": true}}
```

### 7.3 CI/CD Integration

```bash
# Run test
airtest run "test.air" \
    --device "Android://farmhost:5037/serial" \
    --log log/

# Check exit code
echo $?  # 0 = pass, non-zero = fail

# Generate report
airtest report "test.air" --log_root log/ --outfile report.html

# Example: Jenkins / GitHub Actions
# 1. airtest run → exit code
# 2. airtest report → HTML artifact
# 3. Upload report to S3/artifact storage
```

### 7.4 Recording (Video)

```python
from airtest.core.android.recorder import Recorder

# Device screen recording
rec = Recorder(device.adb)
rec.start_recording(max_time=180)  # max 180s (Android screenrecord limit)
# ... test execution ...
rec.stop_recording(output="test_recording.mp4")

# Alternative: ffmpeg from screenshots
from airtest.aircv.screen_recorder import FfmpegVidWriter
writer = FfmpegVidWriter("output.mp4", fps=10)
# ... capture frames ...
writer.finish()
```

---

## 8. So sánh chi tiết

### 8.1 Airtest/Poco vs uiautomator2

| Aspect | Airtest/Poco | uiautomator2 (python-u2) |
|--------|-------------|--------------------------|
| Image recognition | **Built-in** (7 algorithms) | Không có |
| UI hierarchy | Poco (AndroidUiautomationPoco) | Native |
| Game engine support | **Unity, Cocos, UE4, Egret** | Không |
| iOS support | **Có** (via WDA) | Không |
| Windows support | **Có** (pywinauto) | Không |
| IDE | **AirtestIDE** (visual) | weditor (basic) |
| HTML reports | **Built-in** | Không |
| API style | `poco("name").click()` | `d(text="name").click()` |
| **Conflict** | ⚠️ Poco kills u2 server | ⚠️ Cannot coexist with Poco |
| Community | Chinese + international | Primarily Chinese (openatx) |
| Dependencies | OpenCV, numpy (heavy) | Lighter |
| Performance (UI ops) | Tương đương | Slightly faster (direct) |

**Critical:** `AndroidUiautomationPoco` và `uiautomator2` **KHÔNG thể chạy đồng thời** — cả 2 dùng Android Instrumentation (chỉ 1 tại 1 thời điểm). Poco tự kill u2 process.

### 8.2 Airtest/Poco vs Appium

| Aspect | Airtest/Poco | Appium |
|--------|-------------|--------|
| Architecture | Python library trực tiếp | Client-server (WebDriver protocol) |
| Language | Python only | Multi-language (Java, JS, Python, ...) |
| Setup | `pip install` + connect | Appium server + client + drivers |
| Image matching | **Built-in CV engine** | Plugin (limited) |
| Game engines | **Native support** | Rất hạn chế |
| Performance | Nhanh hơn (no HTTP overhead) | Chậm hơn (WebDriver protocol) |
| Enterprise adoption | China / gaming | Global / enterprise |
| Reporting | **Built-in HTML** | External (Allure, etc.) |
| Parallel execution | Process-per-device | Selenium Grid |

### 8.3 Airtest/Poco vs Maestro

| Aspect | Airtest/Poco | Maestro |
|--------|-------------|---------|
| Script language | Python (full power) | YAML (declarative) |
| Image matching | **Full CV engine** | Basic screenshot compare |
| Game support | **Excellent** | Không |
| Flexibility | Rất cao (Python) | Hạn chế bởi YAML commands |
| Learning curve | Medium | Low |
| CI/CD | Manual setup | Built for CI/CD |
| Cloud | AirLab (commercial) | Maestro Cloud |

---

## 9. Device Farm Integration

### 9.1 Architecture Pattern

```
┌─────────────────────────────────────────────────────────┐
│                  Device Farm Server                      │
│                  (FastAPI + Temporal/Celery)              │
└──────────────────────┬──────────────────────────────────┘
                       │ dispatch
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│  Worker 1    │ │  Worker 2    │ │  Worker N    │
│  (Process)   │ │  (Process)   │ │  (Process)   │
│              │ │              │ │              │
│  Airtest     │ │  Airtest     │ │  Airtest     │
│  + Poco      │ │  + Poco      │ │  + Poco      │
│              │ │              │ │              │
│  Device A    │ │  Device B    │ │  Device N    │
│  (ADB fwd)   │ │  (ADB fwd)   │ │  (ADB fwd)   │
└──────────────┘ └──────────────┘ └──────────────┘

⚠️ Mỗi device PHẢI có process riêng (global state)
⚠️ Port management: Poco dùng 10080/10081 per device
```

### 9.2 Integration với Node Engine

Airtest/Poco có thể là **backend driver** cho các nodes:

```python
# Node: action.tap (image strategy)
from airtest.core.api import touch, exists
from airtest.core.cv import Template

class AirtestImageTapNode(BaseNode):
    async def execute(self, ctx, inputs):
        template = Template(
            self.config["image_path"],
            threshold=self.config.get("threshold", 0.7),
        )
        pos = exists(template)
        if pos:
            touch(pos)
            return NodeResult(status="success", outputs={"position": pos})
        return NodeResult(status="failed", error="Image not found")

# Node: ui.find_element (Poco strategy)
class PocoFindElementNode(BaseNode):
    async def execute(self, ctx, inputs):
        selector = self.config["selector"]
        el = ctx.poco(selector["value"], **selector.get("attrs", {}))
        if el.exists():
            return NodeResult(status="success", outputs={
                "text": el.get_text(),
                "position": el.get_position(),
                "bounds": el.get_bounds(),
            })
        return NodeResult(status="failed", error="Element not found")
```

### 9.3 Airtest vs u2 trong Node Engine

| Node | Dùng Airtest/Poco khi | Dùng u2 khi |
|------|----------------------|-------------|
| `action.tap` | Image-based tap, game UI | Element selector tap (faster) |
| `ui.find_element` | Visual verification | Text/ID/XPath lookup |
| `ui.image_match` | **Built-in** (7 algorithms) | Không có, phải dùng OpenCV riêng |
| `ui.assert` | Visual assertion | Text/attribute assertion |
| `ui.ocr` | Không có OCR | Không có OCR |
| `action.input_text` | Yosemite IME | u2 `set_text()` |
| Game automation | **Poco SDK** | Không support |

### 9.4 Hybrid Strategy (Recommended)

```python
# Quyết định runtime: dùng u2 hay Airtest/Poco

class HybridDriver:
    def __init__(self, device_serial: str):
        # Primary: u2 (fast, lightweight)
        self.u2 = uiautomator2.connect(device_serial)

        # Secondary: Airtest (image matching khi cần)
        connect_device(f"Android:///{device_serial}")
        self.airtest_available = True

    def tap_by_selector(self, selector):
        """Fast path: u2"""
        self.u2(**selector).click()

    def tap_by_image(self, image_path, threshold=0.7):
        """Fallback: Airtest image matching"""
        from airtest.core.api import touch, exists
        from airtest.core.cv import Template
        template = Template(image_path, threshold=threshold)
        pos = exists(template)
        if pos:
            touch(pos)
            return pos
        return None

    def find_element_or_image(self, selector=None, image=None):
        """Try selector first, fallback to image"""
        if selector:
            el = self.u2(**selector)
            if el.exists(timeout=2):
                return el
        if image:
            return self.tap_by_image(image)
        return None
```

**⚠️ KHÔNG dùng Poco + u2 đồng thời** — chọn 1:
- **u2** cho device farm (đã tích hợp, lightweight)
- **Airtest image matching** như thư viện bổ sung (không conflict với u2)
- **Poco** chỉ khi cần game engine support (sẽ kill u2)

---

## 10. Performance Characteristics

### 10.1 Benchmarks

| Operation | Airtest | Poco | u2 (reference) |
|-----------|---------|------|----------------|
| Screenshot (minicap) | ~30ms | N/A | ~30ms |
| Screenshot (javacap) | ~100ms | N/A | N/A |
| Screenshot (adbcap) | ~500ms | N/A | ~500ms |
| Template match (tpl) | 10-50ms | N/A | N/A |
| Template match (mstpl) | 50-200ms | N/A | N/A |
| Keypoint match (sift) | 100-500ms | N/A | N/A |
| UI hierarchy dump | N/A | 200-500ms | 200-500ms |
| Tap (minitouch) | ~10-50ms | ~10-50ms | ~10-50ms |
| Tap (adb) | ~200-500ms | ~200-500ms | ~200-500ms |
| Text input (IME) | ~100ms | ~100ms | ~100ms |
| `exists()` check | ~3s (timeout) | ~instant | ~instant |
| `wait()` | Up to 20s | Up to 120s | Configurable |

### 10.2 Resource Usage per Device

| Resource | Airtest | Poco | Combined |
|----------|---------|------|----------|
| RAM | ~50-200MB (OpenCV) | ~30-50MB | ~100-250MB |
| CPU | Medium (CV processing) | Low | Medium |
| ADB ports | 0 extra | 2 (10080, 10081) | 2 |
| Device binaries | minicap + minitouch/maxtouch + Yosemite | pocoservice APK | All |
| Bandwidth | 1-5 MB/s (minicap stream) | Minimal | 1-5 MB/s |

---

## 11. Limitations

### 11.1 Airtest

| Limitation | Impact | Mitigation |
|-----------|--------|------------|
| **Image matching resolution-dependent** | Template ở resolution A fail ở resolution B | Multi-scale matching (mstpl) + record at target resolution |
| **OpenCV version pinned (4.4-4.6)** | Conflict với newer OpenCV | Isolate environment (venv/docker) |
| **numpy < 2.0** | Conflict với ML/data packages | Separate environment |
| **Global state (`G.DEVICE`)** | Không thread-safe | Process-per-device |
| **Minicap issues Android 12+** | Screen capture fail | Dùng JAVACAP fallback |
| **No scrcpy support** | Không dùng được scrcpy streaming | Custom integration needed |
| **FIND_TIMEOUT = 20s** | Chậm khi element không tồn tại | Dùng `exists()` (3s) thay `wait()` |
| **No OCR** | Không đọc text từ image | Dùng Poco hoặc PaddleOCR |

### 11.2 Poco

| Limitation | Impact | Mitigation |
|-----------|--------|------------|
| **Conflict với u2** | Không thể dùng cùng lúc | Chọn 1: Poco hoặc u2 |
| **Game SDK required** | Dev phải integrate Poco SDK vào game | Dùng Airtest image cho game nếu không có SDK |
| **Hierarchy dump overhead** | Chậm trên complex UI (1000+ nodes) | `freeze()` để cache |
| **pocoservice stability** | Service có thể crash | `KeepRunningInstrumentationThread` |
| **Port management** | 2 ports per device (10080, 10081) | Dynamic port allocation |
| **iOS limited** | Frozen hierarchy, không real-time | Acceptable for most use cases |

### 11.3 Cả hai

| Limitation | Impact |
|-----------|--------|
| **472 + 349 open issues** | Nhiều bug chưa fix |
| **Chinese-first documentation** | Docs chính bằng tiếng Trung, English docs ít hơn |
| **AirtestIDE không fully open-source** | Binary distribution only |
| **NetEase internal priorities** | Development focus theo nhu cầu NetEase |

---

## 12. Key Takeaways cho Device Farm

### Nên áp dụng

1. **Airtest Image Matching** — Tích hợp như thư viện CV cho `ui.image_match` node. 7 algorithms > OpenCV `matchTemplate` đơn thuần
2. **Multi-scale matching (mstpl)** — Giải quyết cross-resolution matching trên farm (nhiều loại device)
3. **HTML Report engine** — Tham khảo format cho farm reporting
4. **`.air` format** — Portable test case (code + images) concept cho node-based flows
5. **Screen capture fallback chain** — minicap → javacap → adbcap pattern rất robust
6. **Touch method auto-upgrade** — minitouch → maxtouch on Android 10+ pattern

### Không nên

1. **Dùng Poco thay u2** — Bạn đã dùng u2, Poco conflict. Không đáng switch
2. **Depend vào minicap** — Deprecated, nên migrate sang scrcpy
3. **Dùng global state model** — Farm cần per-device isolation. Dùng Airtest như library, không dùng global `G`
4. **Full Airtest framework** — Quá heavy cho farm. Lấy `airtest.aircv` (CV engine) làm library thôi

### Integration Recommendation

```
Device Farm Node Engine
├── Device Driver: uiautomator2 (primary, đã có)
├── Image Matching: airtest.aircv (thêm mới — CV algorithms)
├── Screen Capture: scrcpy (thay minicap)
├── Touch: u2 tap/swipe (đã có)
├── Text Input: u2 set_text (đã có)
├── Game Automation: Poco SDK (nếu cần game testing)
└── Reporting: Custom (tham khảo Airtest report format)
```

---

## 13. Change Log

| Date | Version | Changes | Author |
|------|---------|---------|--------|
| 2026-03-28 | 1.0 | Initial PRD — Airtest CV engine, Poco UI hierarchy, device farm integration | Architect |
