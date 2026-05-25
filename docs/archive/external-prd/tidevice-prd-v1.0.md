# tidevice — Product Requirements Document (Research)

---

- **Product Name:** tidevice
- **Version:** Latest release (pre-iOS 17)
- **Author / Maintainer:** Alibaba (codeskyblue / Shengxiang)
- **Repository:** [github.com/alibaba/tidevice](https://github.com/alibaba/tidevice)
- **License:** MIT
- **Last Updated:** 2026-03-28
- **Status:** **Maintenance paused** — iOS 17+ not supported; successor project: [tidevice3](https://github.com/codeskyblue/tidevice3) (based on pymobiledevice3)

---

## 1. Executive Summary

### Product Overview

**tidevice** is a pure-Python CLI tool and library that communicates directly with iOS devices over USB **without requiring Xcode or libimobiledevice**. It reimplements Apple's proprietary **usbmuxd**, **Lockdown**, **AFC**, **DTX/Instruments**, and **Testmanagerd** protocols in Python, enabling iOS device automation from **macOS, Linux, and Windows**.

Core capabilities: **app install/launch/kill**, **XCTest/WebDriverAgent execution**, **real-time performance monitoring** (CPU, memory, FPS, GPU, network, energy), **screenshot**, **file system operations**, **syslog streaming**, **crash log collection**, and **TCP port relay**.

### Problem Statement

iOS device automation historically requires:

- **Xcode** (macOS-only) for XCTest and Instruments
- **libimobiledevice** (C library, complex build on non-macOS)
- No cross-platform solution for running **WebDriverAgent** or collecting **performance metrics**

tidevice solves the **iOS device tooling plane** by providing a portable Python implementation of Apple's device protocols, enabling CI/CD on Linux and Windows without Xcode.

### Success Criteria

| Metric | Target |
|--------|--------|
| Platform | macOS, Linux, Windows (cross-platform) |
| Xcode dependency | None (pure Python) |
| XCTest/WDA | Launch and proxy without Xcode |
| Performance metrics | CPU, memory, FPS, GPU, network, energy per-app |
| iOS support | Up to iOS 16.x (iOS 17+ requires tidevice3) |

---

## 2. Goals and Objectives

### Original Goals

- **Cross-platform** iOS device control without Xcode
- Pure Python reimplementation of Apple proprietary protocols
- CLI + Python API for both manual and programmatic use
- Enable **WebDriverAgent** on Linux CI runners

### User Goals

- Install/launch/manage iOS apps from any OS
- Run XCTest bundles and WebDriverAgent without Xcode
- Collect real-time performance metrics for profiling
- Access device filesystem (AFC) for test artifacts
- Stream syslog and crash reports for debugging

### OKRs (interpreted)

```
Objective 1: Cross-platform iOS tooling
+-- KR: CLI works on macOS, Linux, Windows
+-- KR: No Xcode or libimobiledevice dependency

Objective 2: Automation enablement
+-- KR: XCTest/WDA launch via CLI and Python API
+-- KR: TCP relay for Appium/WDA integration
+-- KR: App lifecycle management (install, launch, kill, uninstall)

Objective 3: Performance profiling
+-- KR: Real-time CPU, memory, FPS, GPU, network, energy streaming
+-- KR: Per-app metrics with configurable sampling
```

---

## 3. Target Audience

### Persona 1: iOS Automation Engineer

| Attribute | Detail |
|-----------|--------|
| Goals | Run WebDriverAgent on Linux CI, automate app testing |
| Uses | `tidevice wdaproxy`, `tidevice xctest`, `tidevice install` |
| Pain | Xcode-only limitation, no Linux/Windows WDA support |

### Persona 2: Performance Engineer

| Attribute | Detail |
|-----------|--------|
| Goals | Profile app CPU, memory, FPS, GPU during test runs |
| Uses | `tidevice perf -B com.example.app` |
| Pain | Instruments requires macOS + Xcode, no scriptable streaming |

### Persona 3: Device Farm Operator

| Attribute | Detail |
|-----------|--------|
| Goals | Manage iOS devices in a shared lab, install apps, collect crash logs |
| Uses | Python API for device enumeration, app management, file sync |
| Pain | Need cross-platform tooling for heterogeneous server fleet |

---

## 4. User Stories and Use Cases

### US-1: List connected devices

As an **operator**, I want `tidevice list` with JSON output, so that **I can enumerate all connected iOS devices**.

**Priority:** P0

---

### US-2: Install and launch app

As an **automation engineer**, I want `tidevice install app.ipa && tidevice launch com.example.app`, so that **I can deploy and start apps from CI**.

**Priority:** P0

---

### US-3: Run WebDriverAgent

As an **automation engineer**, I want `tidevice wdaproxy -B com.facebook.WebDriverAgentRunner.xctrunner --port 8100`, so that **Appium can connect to WDA on Linux**.

**Priority:** P0

---

### US-4: Collect performance metrics

As a **performance engineer**, I want `tidevice perf -B com.example.app`, so that **I get real-time CPU, memory, FPS, GPU, network, and energy data**.

**Priority:** P1

---

### US-5: Access device filesystem

As a **tester**, I want `tidevice fsync -B com.example.app pull /Documents/report.txt ./report.txt`, so that **I can retrieve test artifacts from the app sandbox**.

**Priority:** P1

---

### Use Case: CI job with Appium on Linux

1. Linux CI runner with USB-connected iOS device (usbmuxd installed).
2. `tidevice list` — verify device is detected.
3. `tidevice install app.ipa` — deploy the IPA.
4. `tidevice wdaproxy -B com.facebook.WebDriverAgentRunner.xctrunner --port 8100` — start WDA.
5. Run Appium tests against `http://localhost:8100`.
6. `tidevice perf -B com.example.app` — collect metrics during test.
7. `tidevice uninstall com.example.app` — cleanup.

---

## 5. Features and Requirements

### Feature 1: Device Management

**Description:** List devices, device info, pair/unpair, reboot, shutdown, date, sysinfo, wait-for-device, watch (attach/detach events).

**Priority:** P0

---

### Feature 2: App Lifecycle

**Description:** Install IPA (local file or URL), uninstall, launch (with env vars and arguments), kill, app list (user/system/all), app info, running processes.

**Priority:** P0

---

### Feature 3: XCTest / WebDriverAgent Execution

**Description:** Run XCTest bundles via Testmanagerd protocol. Fuzzy bundle ID matching for WDA. `wdaproxy` command combines WDA launch + TCP relay in one step.

**Priority:** P0

---

### Feature 4: Performance Monitoring

**Description:** Real-time streaming of CPU, memory, FPS, GPU utilization, network I/O, and energy consumption per-app via DTX/Instruments channels. Multi-threaded with configurable sampling and callback support.

**Priority:** P1

---

### Feature 5: File System Operations (AFC)

**Description:** Full AFC filesystem access: ls, cat, pull, push, rm, mkdir, rmtree, stat, tree, touch — scoped to app sandbox via `MobileHouseArrest`.

**Priority:** P1

---

### Feature 6: Screenshot

**Description:** Single-frame capture via `MobileScreenshotr` service. Outputs to file. Python API returns PIL Image.

**Priority:** P1

---

### Feature 7: System Logs & Crash Reports

**Description:** Stream syslog in real-time. List, download, and clear crash reports from device.

**Priority:** P2

---

### Feature 8: TCP Port Relay

**Description:** Forward host TCP port to device port (equivalent to `iproxy`). Essential for WDA, debugging, and custom services.

**Priority:** P0

---

### Non-Functional Requirements

#### Platform

| Role | Notes |
|------|-------|
| **macOS** | usbmuxd ships natively |
| **Linux** | usbmuxd must be installed (`apt install usbmuxd`) |
| **Windows** | iTunes must be installed (provides Apple Mobile Device Service) |
| **iOS** | Up to iOS 16.x; iOS 17+ **not supported** |

#### Security

- Device pairing uses RSA certificate exchange (stored locally)
- Optional `pyOpenSSL` for pairing certificate operations
- No built-in authentication for CLI/API access (local tool)

---

## 6. Technical Specifications

### Protocol Architecture (three-layer stack)

```
+--------------------------------------------------+
|  Layer 3: DTX / Instruments Protocol             |
|  Binary protocol, 32-byte DTXMessageHeader       |
|  Magic: 0x1F3D5B79, multiplexed channels         |
|  Payloads: bplist (binary property list)          |
|  Channels: ProcessControl, DeviceInfo,            |
|    Sysmontap, Graphics, Network, Energy           |
+--------------------------------------------------+
|  Layer 2: Lockdown + Plist Services              |
|  Device port 62078                                |
|  Pairing (RSA + SSL/TLS), service activation      |
|  Services: AFC, InstallationProxy,                |
|    MobileScreenshotr, HouseArrest, CrashReport   |
+--------------------------------------------------+
|  Layer 1: usbmuxd                                |
|  Unix socket /var/run/usbmuxd (macOS/Linux)       |
|  TCP 127.0.0.1:27015 (Windows)                    |
|  16-byte header + plist body                      |
|  Device listing, monitoring, port forwarding      |
+--------------------------------------------------+
|  USB / Network Transport                          |
+--------------------------------------------------+
```

### Key Source Files

| File | Purpose |
|------|---------|
| `_device.py` | `BaseDevice` class — core API for all device operations |
| `__main__.py` | CLI entry point with all subcommands |
| `_usbmux.py` | usbmuxd socket client (cross-platform) |
| `_instruments.py` | DTX protocol + `ServiceInstruments` |
| `_perf.py` | Performance monitoring (multi-threaded streaming) |
| `_proto.py` | Protocol constants, service names, AFC operations |
| `_installation.py` | App install/uninstall logic |
| `_imagemounter.py` | DeveloperDiskImage mounting |
| `_crash.py` | Crash report management |
| `_relay.py` | TCP port forwarding |
| `_sync.py` | AFC file sync operations |
| `_wdaproxy.py` | WebDriverAgent proxy |
| `_ca.py` | Certificate authority / pairing certificates |
| `_safe_socket.py` | Thread-safe socket wrapper |

### Dependencies

**Core:**
- `Pillow` — screenshot image handling
- `requests` — HTTP for remote IPA downloads
- `tornado` + `simple_tornado>=0.2.2` — async networking
- `retry` — automatic retries on transient failures
- `colored`, `tabulate`, `logzero` — CLI output formatting
- `simplejson`, `packaging`, `deprecation`

**Optional (`openssl` extra):** `pyOpenSSL`, `pyasn1` — for device pairing certificate operations

### CLI Reference

```bash
# Device management
tidevice list --json
tidevice info -k ProductVersion
tidevice pair

# App lifecycle
tidevice install app.ipa
tidevice install https://example.com/app.ipa
tidevice launch com.example.app --env KEY=VALUE
tidevice kill com.example.app
tidevice applist --type user
tidevice uninstall com.example.app

# XCTest / WDA
tidevice xctest -B com.facebook.WebDriverAgentRunner.xctrunner
tidevice wdaproxy -B com.facebook.WebDriverAgentRunner.xctrunner --port 8100

# Performance
tidevice perf -B com.example.app   # streams CPU, mem, FPS, GPU, network, energy

# File system (AFC)
tidevice fsync -B com.example.app ls /Documents/
tidevice fsync -B com.example.app pull /Documents/file.txt ./local.txt
tidevice fsync -B com.example.app push ./local.txt /Documents/file.txt

# System
tidevice screenshot screenshot.png
tidevice syslog
tidevice relay 8100 8100
tidevice crashreport -l
tidevice crashreport ./crashes/
```

### Python API

```python
import tidevice

# Enumerate devices
u = tidevice.Usbmux()
for d in u.device_list():
    dev = tidevice.Device(d.udid)
    print(dev.name, dev.product_version)

    # Screenshot
    img = dev.screenshot()  # returns PIL Image

    # App management
    dev.app_install("app.ipa")
    dev.app_start("com.example.app")

    # Performance iteration
    for data in dev.connect_instruments().iter_cpu_memory(pid):
        print(data)
```

---

## 7. Analytics and Metrics

Open source project (~2.6k GitHub stars). No built-in product analytics or telemetry.

---

## 8. Risks and Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| **iOS 17+ not supported** | Certain | Critical | Migrate to [tidevice3](https://github.com/codeskyblue/tidevice3) or [pymobiledevice3](https://github.com/doronz88/pymobiledevice3) |
| **Maintenance paused** | Certain | High | Use for iOS ≤16 only; plan migration path |
| **DeveloperDiskImage required** | High | Medium | Pre-download matching DDI per iOS version; automate mounting |
| **Windows requires iTunes** | Always | Low | Document prerequisite; script check in CI |
| **iOS 16 developer mode** | Always | Low | Manual one-time enable per device; document in setup guide |
| **No wireless pairing** | Always | Medium | USB-only; for remote devices, combine with usbmuxd network relay |
| **Protocol documentation incomplete** | High | Medium | Only Layer 1 (usbmuxd) documented; DTX/Plist layers undocumented |

---

## 9. Timeline and Milestones

### Historical

- [x] Full protocol reimplementation (usbmuxd, Lockdown, DTX)
- [x] Cross-platform CLI + Python API
- [x] XCTest/WDA support without Xcode
- [x] Performance monitoring via Instruments channels
- [x] ~2.6k GitHub stars, widely adopted

### Current

- [ ] **Maintenance paused** — no iOS 17+ support
- [ ] Successor: **tidevice3** (based on pymobiledevice3)
- [ ] Community may contribute patches for iOS ≤16 bugs

---

## 10. Open Questions and Assumptions

### Open Questions

1. Should Device Farmer adopt tidevice (iOS ≤16) or go directly to **pymobiledevice3/tidevice3** for iOS 17+ support?
2. Is DeveloperDiskImage auto-download/mounting feasible in the farm server bootstrap flow?
3. How to handle mixed iOS version fleet (≤16 via tidevice, 17+ via pymobiledevice3)?

### Assumptions

1. Target iOS devices are **test devices** with developer mode enabled
2. USB connection is primary; network relay is secondary
3. WebDriverAgent is pre-built and signed (`.xctrunner` bundle available)
4. usbmuxd (or iTunes on Windows) is pre-installed on farm server

### Out of Scope (tidevice core)

1. **Android device management** — tidevice is iOS-only
2. **Real-time screen mirroring** — only single-frame screenshots (no video stream)
3. **Multi-device orchestration** — CLI operates on one device; orchestration is caller's responsibility
4. **App building/signing** — tidevice installs pre-built IPAs only
5. **iOS 17+ support** — use tidevice3/pymobiledevice3

---

## 11. Resources and Team

- **Repository:** [github.com/alibaba/tidevice](https://github.com/alibaba/tidevice)
- **Successor:** [github.com/codeskyblue/tidevice3](https://github.com/codeskyblue/tidevice3)
- **Foundation:** [github.com/doronz88/pymobiledevice3](https://github.com/doronz88/pymobiledevice3)
- **WebDriverAgent:** [github.com/appium/WebDriverAgent](https://github.com/appium/WebDriverAgent)
- **Protocol reference:** `PROTOCOL.md` in repo (Layer 1 only)

---

## 12. Change Log

| Date | Version | Changes | Author |
|------|---------|---------|--------|
| 2026-03-28 | 1.0 | Initial PRD-style research (README + repo analysis) | Claude |

---

## 13. Comparison: tidevice vs pymobiledevice3 vs libimobiledevice vs go-ios

| Dimension | tidevice | pymobiledevice3 | libimobiledevice | go-ios |
|-----------|----------|------------------|-------------------|--------|
| **Language** | Python | Python | C | Go |
| **iOS 17+** | No | Yes | Partial | Yes |
| **Xcode required** | No | No | No | No |
| **Cross-platform** | Yes (macOS/Linux/Windows) | Yes | Yes (build complexity) | Yes |
| **XCTest/WDA** | Yes | Yes | No (direct) | Yes |
| **Performance metrics** | Yes (full Instruments) | Yes | No | Limited |
| **Maintenance** | Paused | Active | Active (community) | Active |
| **Python API** | Yes (native) | Yes (native) | Via bindings | No |
| **License** | MIT | GPL-3.0 | LGPL-2.1 | MIT |

**Recommendation for Device Farmer:** For iOS ≤16, tidevice provides the cleanest Python integration. For iOS 17+, **pymobiledevice3** is the de-facto standard (note GPL-3.0 license implications). **tidevice3** wraps pymobiledevice3 with a tidevice-compatible CLI.
