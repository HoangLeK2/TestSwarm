# Droidrun — Product Requirements Document (Research)

---

- **Product Name:** Droidrun
- **Version:** 0.5.2 (Beta)
- **Author:** Niels Schmidt / droidrun.ai
- **GitHub:** https://github.com/droidrun/droidrun
- **Stars:** 8,050+ | Forks: 825+
- **License:** MIT
- **Last Updated:** 2026-03-28
- **Status:** Active development (Beta — API thay đổi giữa các version)

---

## 1. Executive Summary

### Droidrun là gì?

**Droidrun** là framework Python mã nguồn mở cho phép đi���u khiển thiết bị Android (và iOS early-stage) thông qua **LLM agent** bằng **natural language**. Thay vì viết script step-by-step như Appium/Maestro, bạn mô tả mục tiêu bằng ngôn ngữ tự nhiên và AI agent tự động navigate device để hoàn thành task.

```
Traditional:  Viết code → d(text="Login").click() → d(resourceId="email").set_text("...")
Droidrun:     "Đăng nhập app bằng email test@example.com và password 123456"
              → AI tự tìm nút Login, tìm input field, nhập text, tap Submit
```

### Benchmark: 91.4% success rate

### Tại sao quan trọng cho Device Farm

| Khả năng | Ứng dụng Device Farm |
|----------|---------------------|
| Natural language → device actions | Tạo automation flow mà không cần biết selector |
| AI tự adapt khi UI thay đổi | Giảm maintenance cost khi app update |
| Accessibility tree parsing | Hiểu screen structure mà không cần OCR |
| Stealth mode (human-like behavior) | Anti-detection cho social app automation |
| Pluggable device driver | Tích hợp vào farm connection layer hiện có |
| Extensible tool registry | Thêm custom actions cho device farm |

---

## 2. Architecture

### 2.1 High-Level Components

```
┌───────────────────────────────────────────────────────┐
│                    DroidAgent                          │
│               (LlamaIndex Workflow)                    │
│                                                        │
│  ┌─────────────────────────────────────────────────┐  │
│  │  Mode 1: FastAgent (default)                     │  │
│  │  Single LLM agent, XML tool-calling loop         │  │
│  │  1 LLM call per step                             │  │
│  ├─────────────────────────────────────────────────┤  │
│  │  Mode 2: Manager + Executor (reasoning=true)     │  │
│  │  ManagerAgent: plan + decompose goals            │  │
│  │  ExecutorAgent: execute single atomic action     ��  │
│  │  2 LLM calls per step                            │  │
│  └────────────────────┬───────���────────────────────┘  │
│                       │                                │
│  ┌────────────────────▼���───────────────────────────┐  │
│  │              ToolRegistry                        │  │
│  │  click, type, swipe, open_app, wait,            │  │
│  │  system_button, remember, complete, ...          │  │
│  └──���─────────────────┬────────────────────────────┘  │
│                       │                                │
│  ┌─���──────────────────▼────────────────────────────┐  │
│  │             ActionContext                        │  │
│  │  • DeviceDriver (Android/iOS/Cloud)             │  │
│  │  • StateProvider (a11y tree parser)              │  │
│  │  • UIState (element index, coords)              │  │
���  │  • Credential Manager                           │  ���
│  └��───────────────────┬──────────────���─────────────┘  │
└───────────────────────┼──��─────────────────────────────┘
                        │
          ┌───��─────────▼──────────────┐
          │     PortalClient            │
          │  (HTTP/TCP hoặc ADB shell)  │
          └─────────────┬───────���──────┘
                        │ ADB / HTTP
          ┌─────────────▼────���─────────┐
          │   Droidrun Portal APK       │
          │   (trên Android device)     │
          │                             │
          │   • Accessibility Service   │
          │     (đọc full UI tree)      │
          │   • Content Provider        │
          │     (ADB shell query)       │
          │   • HTTP Server (:8080)     │
          │     (TCP fast mode)         │
          │   • Custom Keyboard IME     │
          │     (text input)            │
          │   • Overlay feedback        │
          └─────────────────────────────┘
```

### 2.2 Agent Loop (FastAgent)

```
┌──────────────────────────────────────────────────────┐
│                  AGENT LOOP (max 15 steps)            │
│                                                       │
│  1. prepare_chat                                      │
│     └─ Build system prompt + goal                     │
│                                                       │
│  2. handle_llm_input                                  │
│     ├─ Capture screenshot (if vision=true)            │
│     ├─ Get UI state (accessibility tree via Portal)   │
│     └─ Call LLM with [system + history + UI state]    │
│                                                       │
│  3. handle_llm_output                                 │
│     ├─ Has <function_calls>? → Step 4                 │
│     ├─ Has complete()? → DONE                         │
│     └─ No tools? → Ask LLM again                     │
��                                                       │
│  4. execute_code                                      │
│     ├─ Parse XML tool calls                           │
│     ├─ Dispatch via ToolRegistry                      │
│     └─ Execute action on device                       │
│                                                       │
│  5. handle_execution_result                           │
│     ├─ Add results to chat history                    │
│     ├─ Sleep after_action (default 1s)                │
│     └─ Loop back to Step 2                            │
│                                                       │
│  Exit: complete() called OR max_steps reached         │
└──────────────────────────────────��───────────────────┘
```

### 2.3 Manager + Executor Mode (reasoning=true)

```
┌────────────────────────────┐
│      ManagerAgent          │
│  (Planning LLM)            ��
│                             │
│  Input: high-level goal     │
│  Output:                    │
│    <thought>reasoning</thought>    │
│    <plan>                   │
│      1. Open Settings       │
│      2. Find Battery        │
│      3. Check percentage    │
│    </plan>                  │
│    <add_memory>...</add_memory>    │
└──────────┬─────────────────┘
           │ subgoal (1 at a time)
           ▼
┌─��──────────────────────────┐
│      ExecutorAgent         │
│  (Action LLM)              │
│                             │
│  Input: single subgoal +   │
│         current UI state    │
│  Output:                    │
│    <function_calls>         │
│      <invoke name="click"> │
│        <parameter>5</parameter>    │
│      </invoke>              │
│    </function_calls>        │
│                             │
│  → Execute action           │
│  → Return result to Manager │
└──────────��─────────────────┘
```

---

## 3. Droidrun Portal (On-Device Component)

### Tại sao cần Portal?

Android không expose accessibility tree qua ADB. Portal là companion app chạy trên device, cung cấp:

| Service | Vai trò | Giao thức |
|---------|---------|-----------|
| **Accessibility Service** | Đọc full UI tree (tất cả elements, text, bounds, class) | OS-level |
| **Content Provider** | Query UI state qua `adb shell content query` | ADB shell |
| **HTTP Server (:8080)** | Fast TCP communication (screenshots, state) | HTTP |
| **Custom Keyboard IME** | Nhập text (Unicode, base64 encoded) | ADB / HTTP |
| **Overlay** | Visual feedback (highlight tapped element) | UI |

### Communication Modes

```
Mode 1: Content Provider (default, fallback)
  Python → adb shell content query --uri content://com.droidrun.portal/state
  Latency: ~200-500ms per query

Mode 2: TCP / HTTP (preferred, use_tcp=true)
  Python → adb forward tcp:LOCAL tcp:8080
        → HTTP GET http://localhost:LOCAL/state_full
  Latency: ~50-100ms per query
  Auth: Bearer token (fetched via content provider)
```

### Portal Setup (automatic)

```python
# Droidrun auto-handles Portal installation
droidrun setup  # CLI command

# Programmatically:
# ensure_portal_ready() checks:
#   1. Portal APK installed? → If not, download + install
#   2. Correct version? → If outdated, upgrade
#   3. Accessibility service enabled? → If not, enable via adb
#   4. TCP server running? → If not, start
```

---

## 4. Screen Understanding

### 4.1 Accessibility Tree (Primary — No OCR needed)

Portal's Accessibility Service captures the full Android accessibility tree. Mỗi element có:

```
Index: 5
  Text: "Login"
  ClassName: android.widget.Button
  ContentDescription: "Sign in to your account"
  Bounds: [100, 800, 300, 860]
  Clickable: true
  Focusable: true
  Children: []
```

Tree được format thành text representation và gửi cho LLM:

```
[0] FrameLayout
  [1] LinearLayout
    [2] ImageView "App Logo"
    [3] EditText "Email" (editable, focusable)
    [4] EditText "Password" (editable, focusable)
    [5] Button "Login" (clickable)
    [6] TextView "Forgot password?" (clickable)
```

LLM đọc tree này và quyết định action dựa trên index.

### 4.2 Screenshots + Vision (Optional)

```python
agent = DroidAgent(
    goal="...",
    llms=llm,
    fast_agent_vision=True,  # Enable screenshot analysis
)
```

- Screenshot được capture mỗi step và gửi kèm accessibility tree cho LLM
- Multimodal LLM (GPT-4o, Gemini, Claude) phân tích visual + structural data
- **Cost**: thêm ~$0.01-0.03 per screenshot (token cost)
- **Use case**: Khi accessibility tree không đủ (custom views, canvas, games)

### 4.3 UIState Class

```python
# Internal: parse accessibility tree → queryable structure
ui_state = UIState(tree_data)

# Get element by index
element = ui_state.get_element(5)
# → Element(text="Login", className="Button", bounds=[100,800,300,860])

# Get tap coordinates (center of element)
x, y = ui_state.get_element_coords(5)
# → (200, 830)

# Normalized coordinates [0-1000] for resolution independence
x_norm, y_norm = ui_state.convert_point(0.5, 0.8)
```

---

## 5. Available Actions (Tools)

### 5.1 Built-in Actions

| Action | Parameters | Mô tả | Implementation |
|--------|-----------|-------|---------------|
| `click` | `index: int` | Tap element theo a11y index | ADB `input tap x y` |
| `click_at` | `x, y: int` | Tap tọa độ tuyệt đối | ADB `input tap x y` (disabled by default) |
| `click_area` | `x1,y1,x2,y2` | Tap center vùng chữ nhật | ADB `input tap` (disabled by default) |
| `long_press` | `index: int` | Long press element | ADB swipe (same point, 800ms) |
| `long_press_at` | `x, y: int` | Long press tọa ��ộ | ADB swipe (disabled by default) |
| `type` | `text, index, clear` | Nhập text vào input | Portal Keyboard IME |
| `type_secret` | `secret_id, index` | Nhập credential (LLM không thấy value) | Credential Manager → Portal |
| `system_button` | `button: str` | Press back / home / enter | ADB `input keyevent` |
| `swipe` | `coord1, coord2, duration` | Swipe gesture | ADB `input swipe` |
| `wait` | `duration: float` | Chờ N giây | `asyncio.sleep` |
| `open_app` | `text: str` | Mở app theo tên/mô tả | LLM call → tìm package → `am start` |
| `remember` | `information: str` | Lưu info vào agent memory | In-memory |
| `complete` | `success, message` | Đánh dấu task hoàn thành | Terminate loop |

### 5.2 Stealth Mode (Human-Like Behavior)

```python
from droidrun.tools.android.stealth_driver import StealthDriver

# StealthDriver wraps AndroidDriver, adds:
# • Bezier-curved swipe paths (không thẳng tắp)
# • Micro-jitter on tap coordinates (+/- vài pixels)
# • Word-by-word typing (không paste cả chuỗi)
# • Random delays giữa actions
# • Natural scrolling speed variation
```

**Rất hữu ích cho social app automation** — tránh bị detect là bot.

### 5.3 Macro Recording / Replay

```python
from droidrun.tools.android.recording_driver import RecordingDriver
from droidrun.tools.android.macro_player import MacroPlayer

# Record actions
recording_driver = RecordingDriver(base_driver)
# ... agent runs, actions are recorded ...
macro = recording_driver.get_macro()

# Replay (without LLM — deterministic, free)
player = MacroPlayer(device_driver)
await player.play(macro)
```

**Use case**: Dùng AI để record flow 1 lần → replay miễn phí trên 1000 devices.

---

## 6. LLM Configuration

### 6.1 Supported Providers

| Provider | Model (default) | Install | Cost |
|----------|----------------|---------|------|
| **Google Gemini** | `gemini-3.1-flash-lite-preview` | Built-in | Rẻ nhất (~$0.001/step) |
| **OpenAI** | `gpt-4o` | Built-in | ~$0.01-0.03/step |
| **Anthropic** | `claude-sonnet-4-20250514` | `pip install droidrun[anthropic]` | ~$0.01-0.02/step |
| **Ollama** | Local models | Built-in | Free (self-hosted) |
| **DeepSeek** | `deepseek-chat` | `pip install droidrun[deepseek]` | Rẻ |
| **OpenRouter** | Any model | Built-in | Varies |
| **OpenAI-Like** | Any compatible API | Built-in | Varies |

### 6.2 LLM Profiles (mix & match)

```python
from droidrun import DroidAgent, load_llm

# Cheap model cho planning, expensive cho execution
manager_llm = load_llm("GoogleGenAI", model="gemini-2.5-flash")
executor_llm = load_llm("OpenAI", model="gpt-4o")

agent = DroidAgent(
    goal="...",
    llms={
        "manager": manager_llm,      # Planning
        "executor": executor_llm,     # Action selection
        "fast_agent": manager_llm,    # FastAgent mode
        "app_opener": manager_llm,    # Open app
    },
    reasoning=True,  # Use Manager + Executor mode
)
```

### 6.3 Local Model (Zero Cost)

```python
# Ollama (free, local)
llm = load_llm("Ollama", model="llama3.1:8b")

# Bất kỳ OpenAI-compatible API
llm = load_llm("OpenAILike", model="my-model", api_base="http://localhost:8000/v1")
```

### 6.4 XML Tool-Calling Protocol

Droidrun dùng custom XML protocol thay vì native function calling:

```xml
<!-- LLM output -->
<function_calls>
<invoke name="click">
<parameter name="index">5</parameter>
</invoke>
</function_calls>

<!-- Agent returns -->
<function_results>
<result name="click">
<output>Clicked on Text: 'Login' | Class: Button | Coords: (540, 960)</output>
</result>
</function_results>
```

Hỗ trợ **parallel tool calls** (nhiều `<invoke>` trong 1 block).

---

## 7. Python API & Usage

### 7.1 Basic Usage

```python
import asyncio
from droidrun import DroidAgent, load_llm

async def main():
    llm = load_llm("GoogleGenAI", model="gemini-3.1-flash-lite-preview")

    agent = DroidAgent(
        goal="Open Settings and turn on WiFi",
        llms=llm,
        timeout=1000,       # max execution time (seconds)
        max_steps=15,       # max agent steps
        device_serial="emulator-5554",  # specific device
    )

    # Run with streaming events
    handler = agent.run()
    async for event in handler.stream_events():
        if hasattr(event, "msg"):
            print(event.msg)

    result = await handler
    print(f"Success: {result.success}")
    print(f"Message: {result.message}")

asyncio.run(main())
```

### 7.2 CLI

```bash
# Setup (install Portal APK)
droidrun setup

# Run task
droidrun run "open youtube and search for music"

# With options
droidrun run "login to app" \
    --vision \                    # Enable screenshot analysis
    --reasoning \                 # Manager + Executor mode
    -p OpenAI -m gpt-4o \       # Specific LLM
    --device SERIAL \            # Target device
    --max-steps 20               # Increase step limit

# Utilities
droidrun devices                 # List connected devices
droidrun doctor                  # Diagnose issues
droidrun ping                    # Test Portal connectivity
droidrun tui                     # Terminal UI (interactive)
```

### 7.3 With Credentials (Secure)

```python
agent = DroidAgent(
    goal="Login to Facebook",
    llms=llm,
    credentials={
        "fb_email": "test@example.com",
        "fb_password": "secret123",
    },
    # LLM sees: type_secret(secret_id="fb_email", index=3)
    # LLM NEVER sees actual value "test@example.com"
)
```

### 7.4 Custom Tools

```python
from droidrun.tools.registry import ToolRegistry

# Add custom tool
@ToolRegistry.register("take_photo")
async def take_photo(context: ActionContext) -> str:
    """Take a photo using the device camera"""
    driver = context.driver
    await driver.tap(540, 960)  # tap shutter button
    await asyncio.sleep(2)
    return "Photo taken"
```

### 7.5 MCP Integration (Model Context Protocol)

```python
agent = DroidAgent(
    goal="...",
    llms=llm,
    mcp_servers=[
        {"name": "my-api", "url": "http://localhost:3000/mcp"},
    ],
    # Agent can now call tools exposed by MCP server
)
```

---

## 8. Error Handling & Recovery

### 8.1 Portal Communication

```
State fetch retry: 7 attempts, exponential backoff
  Attempt 1: wait 1s
  Attempt 2: wait 2s
  Attempt 3: wait 3s
  Attempt 4: wait 5s
  Attempt 5: wait 8s → Restart Portal accessibility + TCP server
  Attempt 6: wait 10s
  Attempt 7: fail → DeviceDisconnectedError
```

### 8.2 Agent Level

| Error Type | Handling |
|-----------|---------|
| Portal unreachable | 7 retries + auto-restart Portal services |
| LLM API error | Retry (LlamaIndex built-in) |
| Action failed | Agent sees error in results → tries alternative approach |
| Max steps reached | Return incomplete result |
| Device disconnected | `DeviceDisconnectedError` raised |
| Timeout | Workflow timeout terminates agent |

### 8.3 Self-Recovery

LLM agent có khả năng **tự recover** khi gặp unexpected state:
- Popup xuất hiện → AI nhận ra và dismiss
- Wrong screen → AI nhấn back và thử lại
- Element không tìm thấy → AI scroll để tìm
- App crash → AI detect và reopen app

---

## 9. Device Farm Integration Strategy

### 9.1 Droidrun trong Node Engine

Droidrun có thể là **1 AI node** trong node-based automation system:

```
┌─────────────────────────────────────────────────────────┐
│  Node-Based Flow                                         │
│                                                          │
│  [Install App] → [Launch App] → [AI: Droidrun Node] →  │
│                                  ↓                       │
│                    "Login with email test@mail.com        │
│                     and verify dashboard appears"        │
│                                  ↓                       │
│                    [Assert: Dashboard visible] →         │
│                    [Screenshot] → [Complete]             │
└──��──────────────────────────���───────────────────────────┘
```

### 9.2 Hybrid Approach: Deterministic + AI

```python
# Best practice: Dùng deterministic nodes cho stable steps,
# AI (droidrun) cho dynamic/complex steps

# Deterministic (fast, reliable, free)
await tap(selector={"resource_id": "btn_login"})
await input_text(selector={"resource_id": "email"}, text="test@mail.com")
await input_text(selector={"resource_id": "password"}, text="secret")
await tap(selector={"resource_id": "btn_submit"})

# AI (adaptive, handles unexpected states)
agent = DroidAgent(
    goal="Navigate to Profile > Settings > Privacy and enable 2FA",
    llms=llm,
)
# → AI tự tìm đường, handle popup, scroll, v.v.
```

### 9.3 Macro Record → Replay Strategy

```
Phase 1: AI Record (1 lần, 1 device)
  DroidAgent + RecordingDriver
  → AI navigates, actions recorded as macro
  → Human review macro

Phase 2: Replay (N lần, 1000 devices)
  MacroPlayer replays recorded actions
  → Zero LLM cost
  → Deterministic, fast

Phase 3: Fallback to AI
  Nếu replay fail (UI changed) → fallback to DroidAgent
  → AI adapts, records new macro
  → Update macro library
```

### 9.4 Custom DeviceDriver cho Farm

```python
from droidrun.tools.device_driver import DeviceDriver

class FarmDeviceDriver(DeviceDriver):
    """Custom driver: route qua Device Farm connection layer"""

    def __init__(self, farm_client, device_id: str):
        self.farm = farm_client
        self.device_id = device_id

    async def tap(self, x: int, y: int):
        await self.farm.send_command(self.device_id, "tap", {"x": x, "y": y})

    async def swipe(self, x1, y1, x2, y2, duration=300):
        await self.farm.send_command(self.device_id, "swipe", {...})

    async def input_text(self, text: str):
        await self.farm.send_command(self.device_id, "input_text", {"text": text})

    async def screenshot(self) -> bytes:
        return await self.farm.get_screenshot(self.device_id)

    async def get_ui_tree(self) -> dict:
        return await self.farm.get_ui_state(self.device_id)
```

### 9.5 Scaling: Multi-Device Parallel

```python
import asyncio
from droidrun import DroidAgent, load_llm

async def run_on_device(device_serial: str, goal: str):
    llm = load_llm("GoogleGenAI", model="gemini-3.1-flash-lite-preview")
    agent = DroidAgent(
        goal=goal,
        llms=llm,
        device_serial=device_serial,
    )
    handler = agent.run()
    return await handler

async def run_on_all_devices(device_serials: list[str], goal: str):
    """Fan-out: same goal → all devices"""
    tasks = [run_on_device(serial, goal) for serial in device_serials]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return results

# Run on 100 devices
results = asyncio.run(run_on_all_devices(
    device_serials=["device_001", "device_002", ..., "device_100"],
    goal="Open Settings and verify WiFi is connected",
))
```

**Bottleneck**: LLM API rate limits. Mitigations:
- Dùng Ollama (local) cho simple tasks
- Macro record/replay cho repeated tasks
- Rate limit queue cho LLM API calls
- Mix providers (Gemini cho bulk, GPT-4o cho complex)

---

## 10. So sánh: Droidrun vs Alternatives

### 10.1 Feature Matrix

| Feature | Droidrun | Appium | Maestro | Airtest | Our Node Engine |
|---------|----------|--------|---------|---------|----------------|
| Natural language control | **Yes** | No | No | No | Via AI nodes |
| Explicit selectors | Via a11y index | XPath, ID | Text, ID | Image, Poco | All strategies |
| AI-adaptive | **Yes** | No | No | No | Via ai.auto_heal |
| Stealth mode | **Yes** | No | No | No | Planned |
| Macro record/replay | **Yes** | No | No | Airtest IDE | Planned |
| iOS support | Early | Full | Full | Full | Via WDA |
| Cost per action | LLM API cost | Free | Free | Free | Free (AI nodes = LLM cost) |
| Speed (per action) | 2-5s (LLM) | 200-500ms | 100-300ms | 200-500ms | 200-500ms |
| Reliability | ~91.4% | ~100%* | ~100%* | ~100%* | ~100%* |
| Maintenance cost | Low (AI adapts) | High | Medium | Medium | Medium |
| Learning curve | Low (NL) | High | Medium | Medium | Medium |
| Multi-device built-in | No | No | No | No | **Yes** |

> \* Giả sử scripts đúng. Nếu UI thay đổi thì Appium/Maestro/Airtest cũng fail.

### 10.2 Khi nào dùng Droidrun vs Deterministic Nodes

| Scenario | Droidrun (AI) | Deterministic Nodes |
|----------|-------------|-------------------|
| Prototype / explore app | ✓ | |
| Stable, critical test flow | | ✓ |
| UI thay đổi thường xuyên | ✓ | |
| Performance-sensitive | | ✓ |
| Complex navigation không biết trước | ✓ | |
| 1000 devices, same simple flow | | ✓ (free, fast) |
| Social app, anti-detection | ✓ (stealth) | Combine with stealth driver |
| Generate initial flow | ✓ (record macro) | Replay macro |

---

## 11. Dependencies

### Core

```
droidrun==0.5.2

# Agent framework
llama-index==0.14.4
llama-index-workflows==2.8.3
llama-index-llms-google-genai    # Gemini
llama-index-llms-openai          # GPT-4o
llama-index-llms-ollama          # Local models

# Device connectivity
async_adbutils                    # Async ADB
mobilerun-sdk                     # Cloud devices

# HTTP
httpx                             # Portal TCP mode

# Data
pydantic>=2.11

# UI
rich>=14.1                        # Terminal formatting
textual>=6.11                     # TUI

# Extras
mcp>=1.26                         # Model Context Protocol
arize-phoenix>=12.3               # Tracing
python-dotenv                     # Env management
```

### Optional

```
pip install droidrun[anthropic]   # Claude support
pip install droidrun[deepseek]    # DeepSeek support
pip install droidrun[langfuse]    # Langfuse tracing
```

---

## 12. Limitations

| Limitation | Impact | Mitigation |
|-----------|--------|------------|
| **LLM cost per step** | $0.001-0.03/step, complex task 15+ steps | Macro record → replay, local models (Ollama) |
| **Latency 2-5s/step** | Không phù hợp real-time | Dùng cho exploration, deterministic cho speed |
| **91.4% reliability** | Non-deterministic, cùng task có thể fail | Retry, fallback to deterministic |
| **Portal APK required** | Phải cài trên mọi device | Auto-setup via `droidrun setup` |
| **No drag support** | `drag()` raises NotImplementedError | Dùng swipe workaround |
| **iOS early-stage** | iOS driver minimal | Dùng WDA trực tiếp cho iOS |
| **No OCR** | Phụ thuộc a11y tree, app không expose = blind | Enable vision mode (screenshot → LLM) |
| **Keyboard hijack** | Replace device keyboard | Restore sau execution |
| **Beta API** | Breaking changes giữa versions | Pin version, test trước upgrade |
| **LLM rate limits** | Bottleneck cho 1000 devices parallel | Mix providers, local models, macro replay |
| **Python 3.11-3.13 only** | Không hỗ trợ 3.9-3.10 và 3.14 | Upgrade Python environment |

---

## 13. Key Takeaways cho Device Farm

### Nên áp dụng

1. **AI Node (`ai.droidrun`)**: Thêm DroidAgent như 1 node trong node engine — cho phép natural language automation
2. **Macro Record → Replay**: Dùng AI record flow 1 lần → replay miễn phí trên farm
3. **Stealth Driver**: Integrate Bezier swipe + micro-jitter vào existing touch driver
4. **Accessibility Tree Parser**: Học cách Portal parse a11y tree — implement tương tự cho farm (không cần OCR)
5. **Credential Manager**: Pattern "LLM không thấy password" rất quan trọng cho security
6. **Custom DeviceDriver**: Pluggable architecture — viết driver route qua farm connection

### Không nên

1. **Dùng Droidrun cho mọi action**: Chỉ dùng AI khi cần adaptive behavior
2. **Depend hoàn toàn vào Portal APK**: Nên có fallback (u2, ADB direct)
3. **Scale 1000 devices full-AI**: LLM cost + rate limit. Macro replay cho bulk
4. **Bỏ deterministic nodes**: AI bổ sung, không thay thế

---

## 14. Change Log

| Date | Version | Changes | Author |
|------|---------|---------|--------|
| 2026-03-28 | 1.0 | Initial PRD — architecture, API, device farm integration strategy | Architect |
