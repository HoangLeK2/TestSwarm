# LAMDA — Android Automation & Reverse Engineering Framework

> GitHub: https://github.com/firerpa/lamda

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         LAMDA ARCHITECTURE                              │
│                                                                         │
│  ┌──────────────────────────────────┐                                   │
│  │        YOUR MACHINE (PC)         │                                   │
│  │  ┌────────────────────────────┐  │                                   │
│  │  │   Python SDK (lamda pip)   │  │                                   │
│  │  │  160+ API calls            │  │                                   │
│  │  │  MCP / AI Agent tools      │  │                                   │
│  │  └────────────┬───────────────┘  │                                   │
│  └───────────────│──────────────────┘                                   │
│                  │ TCP / WS / HTTP                                       │
│                  │ Port 65000                                            │
│  ┌───────────────▼──────────────────┐                                   │
│  │    ANDROID DEVICE (rooted)       │                                   │
│  │                                  │                                   │
│  │  ┌──────────────────────────┐    │                                   │
│  │  │   lamda SERVER (on-dev)  │    │                                   │
│  │  │  - Built-in Python 3.9   │    │                                   │
│  │  │  - ADB / SSH / SCP       │    │                                   │
│  │  │  - Frida integration     │    │                                   │
│  │  │  - MITM proxy engine     │    │                                   │
│  │  │  - WebSocket video       │    │                                   │
│  │  │  - Cron scheduler        │    │                                   │
│  │  └──────────────────────────┘    │                                   │
│  │                                  │                                   │
│  │  Android 6.0 → 16 supported      │                                   │
│  └──────────────────────────────────┘                                   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Năm nhóm tính năng chính

```
LAMDA capabilities
├── 1. UI Automation
│   ├── Click, swipe, type, scroll
│   ├── Layout inspector (giống UiAutomatorViewer)
│   ├── XPath / id / text element selector
│   └── Event stream / touch replay
│
├── 2. Remote Desktop
│   ├── Web browser control (Chrome 95+)
│   ├── MJPEG / H.264 video stream
│   └── Low-latency keyboard+mouse injection
│
├── 3. Network Interception (MITM)
│   ├── HTTP / SOCKS5 proxy
│   ├── SSL man-in-the-middle (cert install)
│   ├── OpenVPN tunnel
│   └── Port forwarding (FRP support)
│
├── 4. Reverse Engineering
│   ├── Frida persistence (auto-restart on crash)
│   ├── IDA debug server integration
│   ├── Binary patching helpers
│   └── Script encryption / API locking
│
└── 5. Device / System Control
    ├── App install / uninstall / start / stop
    ├── System props & settings write
    ├── File I/O + encrypted KV storage
    ├── Shell execution & cron scheduling
    └── Device discovery (mDNS)
```

---

## Installation

### Client (PC)
```bash
pip3 install -U lamda
pip3 install -U --force-reinstall 'lamda[full]'  # với Frida support
```

### Server (Android device — rooted)

**Option A: Magisk module (khuyến nghị, auto-start)**
1. Download `lamda-magisk-module.zip` từ Releases
2. Flash qua Magisk app
3. Reboot

**Option B: Manual**
```bash
adb push arm64-v8a.tar.gz /data/local/tmp/
adb shell
tar -xzf /data/local/tmp/arm64-v8a.tar.gz -C /data/local/tmp/
sh /data/local/tmp/arm64-v8a/bin/launch.sh
```

Web UI: `http://<device-ip>:65000`

### Hardware requirements
- Rooted Android 6.0–16 (API 23–35)
- RAM ≥ 2 GB, Storage free ≥ 1 GB
- Compatible: Nox, LeiDian emulators; Alibaba/Huawei cloud phones

---

## So sánh với các công cụ cùng ngành

| Tính năng | LAMDA | Appium | Frida | ADB |
|-----------|:-----:|:------:|:-----:|:---:|
| UI Automation | ✅ | ✅ | ❌ | ❌ |
| MITM Proxy | ✅ | ❌ | ❌ | ❌ |
| Frida built-in | ✅ | ❌ | ✅ | ❌ |
| Remote Desktop | ✅ | ❌ | ❌ | ❌ |
| Python SDK | ✅ | ✅ | ✅ | ❌ |
| AI / MCP Agent | ✅ | ❌ | ❌ | ❌ |
| Không cần ADB binary | ✅ | ❌ | ❌ | ❌ |
| Cần root | ✅ | ❌ | ✅ | ❌ |

---

## Use Cases điển hình

```
┌─────────────────────────────────────────────────────┐
│  USE CASES                                          │
│                                                     │
│  Security Research                                  │
│     └─ Frida hook + MITM → intercept API traffic   │
│                                                     │
│  Device Farm Automation                             │
│     └─ Python SDK → 100 devices parallel control   │
│                                                     │
│  App Testing                                        │
│     └─ UI automation + screenshot + OCR             │
│                                                     │
│  AI Agent Integration                               │
│     └─ MCP tool-call → LLM controls phone          │
│                                                     │
│  Malware Analysis                                   │
│     └─ Dynamic analysis + network tap + memory dump │
└─────────────────────────────────────────────────────┘
```

---

## Quick code example

```python
from lamda.client import Device

d = Device("192.168.1.100")

# UI automation
d.click(500, 800)
d.swipe(500, 1500, 500, 500)
d.type("hello world")

# Launch app
d.start_activity("com.example.app", ".MainActivity")

# MITM proxy
d.set_proxy("http", "192.168.1.1", 8080)

# Take screenshot
d.screenshot().save("screen.png")

# Shell command
result = d.execute_script("ls /data/local/tmp")

# Frida inject
d.frida.get_usb_device()
```

---

## Liên quan đến project deviceFarmer

LAMDA có thể **thay thế hoặc bổ sung** cho stack hiện tại:

| Thành phần hiện tại | LAMDA tương đương |
|--------------------|-------------------|
| minicap (screen capture) | LAMDA WebSocket H.264 stream |
| minitouch (touch inject) | LAMDA touch API |
| u2-server (UIAutomator2) | LAMDA built-in UI automation |
| scrcpy relay | LAMDA remote desktop |
| adb-shell transport | LAMDA built-in ADB (không cần binary) |

**Ưu điểm:** Gói tất cả vào một binary on-device duy nhất, không cần push minicap/minitouch/u2 riêng lẻ.

**Hạn chế:** Yêu cầu root — nếu thiết bị không root thì vẫn cần stack hiện tại.
