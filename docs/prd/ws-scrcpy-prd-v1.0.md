# ws-scrcpy — Product Requirements Document (Research)

---

- **Product Name:** ws-scrcpy
- **Version:** 0.9.0-dev
- **Author / Maintainer:** Sergey Volkov (drauggres / NetrisTV)
- **License:** MIT (Apache-2.0 for scrcpy-server fork)
- **Last Updated:** 2026-03-28
- **Status:** Active development; based on **scrcpy v1.19 fork** with WebSocket transport

---

## 1. Executive Summary

### Product Overview

**ws-scrcpy** is a **web-based client for scrcpy** that enables real-time Android device **screen mirroring and remote control** entirely from a web browser. Unlike the original desktop scrcpy, ws-scrcpy uses **WebSockets** to transport H264 video from device to browser, where it is decoded and rendered using one of four player backends (MSE, Broadway/WASM, TinyH264, WebCodecs).

It ships a **modified fork of scrcpy-server v1.19** (`scrcpy-server.jar`) with an integrated WebSocket server, a **Node.js relay server** (Express + ws), and a **TypeScript SPA** client. Experimental **iOS** support is included via ws-qvh + WebDriverAgent.

### Problem Statement

Organizations running **device farms** or **shared device labs** need:

- **Browser-based** remote device access — no native client install required
- **Multi-user concurrent** access to shared devices
- **Multi-server federation** for distributed labs
- **Low-friction** screen mirroring with input injection via standard web technologies

ws-scrcpy solves the **remote screen + control plane** via WebSocket; it does **not** provide device reservation, booking, CI/CD API, or test orchestration (contrast **STF**, **GADS**).

### Success Criteria

| Metric | Target |
|--------|--------|
| Stream latency | Browser-dependent; MSE ~100ms, WebCodecs ~50ms, WASM ~150ms |
| Concurrent clients | Multiple browsers sharing a single device stream |
| Deployment | Single `npm start` or multi-server federation |
| Platform | Android 5.0+ (API 21+); experimental iOS |

---

## 2. Goals and Objectives

### Primary Goals

- **Zero-install client**: any modern browser controls any connected Android device
- **Multiple decoder options**: graceful degradation across browser capabilities
- **Network-native**: WebSocket transport works over LAN/WAN without ADB tunneling
- **Multi-server**: federate multiple ws-scrcpy instances for distributed labs

### User Goals

- Open browser → see device list → click device → mirror screen + interact
- Use integrated **adb shell** (xterm.js) without external terminal
- **Drag-and-drop** files/APKs onto device
- Access **Chrome DevTools** for WebView debugging
- Browse device filesystem

### OKRs (interpreted)

```
Objective 1: Browser-based device control
+-- KR: H264 stream playback in Chrome, Firefox, Safari
+-- KR: Touch, keyboard, clipboard injection from browser
+-- KR: File push via drag-and-drop

Objective 2: Lab-scale deployment
+-- KR: Multi-server federation with host tracker
+-- KR: Automatic device discovery via adbkit tracker
+-- KR: Configurable HTTPS + reverse proxy support

Objective 3: Developer tooling
+-- KR: Integrated shell (xterm.js)
+-- KR: Chrome DevTools forwarding
+-- KR: File explorer
```

---

## 3. Target Audience

### Persona 1: Manual QA / Developer

| Attribute | Detail |
|-----------|--------|
| Goals | Remote device interaction from browser, reproduce bugs |
| Uses | Screen mirroring, touch/swipe, keyboard, screenshots |
| Pain | Latency vs native scrcpy; no audio streaming |

### Persona 2: Lab / Farm Administrator

| Attribute | Detail |
|-----------|--------|
| Goals | Deploy browser-based device access for team |
| Uses | Multi-server federation, HTTPS config, device management |
| Pain | No auth/booking system built-in; security model is open |

### Persona 3: Automation / Integration Engineer

| Attribute | Detail |
|-----------|--------|
| Goals | Embed device control in web-based dashboards or pipelines |
| Uses | WebSocket API, programmatic control messages |
| Pain | No REST API for reservation; scrcpy-server fork is behind upstream |

---

## 4. User Stories and Use Cases

### US-1: View and select device

As a **user**, I want to **open the ws-scrcpy web UI and see all connected devices**, so that **I can pick one to control**.

**Priority:** P0

---

### US-2: Mirror and control device

As a **user**, I want to **click a device and see its screen in real-time with touch/keyboard input**, so that **I can interact remotely**.

**Priority:** P0

---

### US-3: Integrated shell

As a **developer**, I want to **open an adb shell in the browser** (xterm.js), so that **I can run commands without a separate terminal**.

**Priority:** P1

---

### US-4: File transfer

As a **user**, I want to **drag-and-drop files/APKs onto the device screen**, so that **files are pushed or APKs installed**.

**Priority:** P1

---

### US-5: Chrome DevTools

As a **developer**, I want to **access Chrome DevTools for a device's WebView** from the ws-scrcpy UI, so that **I can debug web content remotely**.

**Priority:** P2

---

### US-6: Multi-server federation

As a **lab admin**, I want to **federate multiple ws-scrcpy servers** and see all devices in one view, so that **distributed labs are unified**.

**Priority:** P2

---

### Use Case: Device Farm Integration

1. Deploy ws-scrcpy on server with ADB-connected devices.
2. Users open `https://server:8000` in browser.
3. Device list auto-populates via adbkit tracker.
4. Click device → select player (MSE/Broadway/TinyH264/WebCodecs).
5. Mirror screen, interact with touch/keyboard, push files.
6. For multi-site: configure `remoteHostList` to aggregate devices.

---

## 5. Features and Requirements

### Feature 1: Real-time screen mirroring

**Description:** H264 video stream from modified scrcpy-server via WebSocket. Four decoder/player options:

| Player | Technology | HW Accel | Browser Support |
|--------|-----------|----------|-----------------|
| **MsePlayer** | Media Source Extensions | Yes (browser) | Chrome, Firefox, Edge |
| **BroadwayPlayer** | WASM H264 decoder + WebGL | No (software) | All modern browsers |
| **TinyH264Player** | WASM + Web Workers | No (software) | All modern browsers |
| **WebCodecsPlayer** | WebCodecs API | Yes (native) | Chromium-only |

**Configurable:** bitrate, resolution bounds, max FPS, I-frame interval, codec options, encoder name — all adjustable live.

**Priority:** P0

---

### Feature 2: Device input injection

**Description:** Touch (multi-touch emulation with CTRL/SHIFT), keyboard (KeyCode + text), scroll, clipboard sync. Binary protocol messages:

- `TouchControlMessage` — 29 bytes: action, pointerId, position, pressure, buttons
- `ScrollControlMessage` — scroll position + amounts (30ms throttle)
- `KeyCodeControlMessage` — Android KeyEvent codes
- `TextControlMessage` — ASCII text injection
- `CommandControlMessage` — meta-commands (video settings, clipboard, rotation)

**Priority:** P0

---

### Feature 3: Integrated developer tools

**Description:**
- **Remote shell** — xterm.js terminal connected via node-pty
- **Chrome DevTools** — forwarded from device for WebView debugging
- **File explorer** — browse, push, and manage files on device

**Priority:** P1

---

### Feature 4: Multi-server federation

**Description:** `remoteHostList` in config references other ws-scrcpy instances. `HostTracker` middleware aggregates device lists. `useProxy: true` routes through local server; `false` allows direct browser-to-device connection.

**Priority:** P2

---

### Feature 5: iOS support (experimental)

**Description:** Screen casting via `ws-qvh` (WebSocket wrapper for quicktime_video_hack) or MJPEG via WDA. Control via WebDriverAgent (simple touch, scroll, home button only). Not built by default — requires build config override.

**Priority:** P3

---

### Non-Functional Requirements

#### Security (explicit caveats from README)

| Concern | Detail |
|---------|--------|
| Encryption | No encryption by default between browser↔server or browser↔device; HTTPS is opt-in |
| Authentication | **None** — no auth or authorization at any level |
| Device exposure | Modified scrcpy listens on **all network interfaces** by default |
| Process lifecycle | scrcpy-server **keeps running** after last client disconnects |

#### Platform Requirements

| Role | Requirement |
|------|-------------|
| **Server OS** | Linux, macOS, Windows (Node.js) |
| **Server deps** | Node.js v10+, `adb` in PATH, node-gyp build tools |
| **Android** | 5.0+ (API 21+), USB debugging enabled |
| **Browser** | WebSocket + one of: MSE, WebAssembly, WebCodecs |
| **iOS** (optional) | ws-qvh binary, WebDriverAgent |

---

## 6. Technical Specifications

### Three-tier architecture

```
+------------------+
|   Web Browser    |  TypeScript SPA (webpack)
|  H264 decoder    |  MSE / WASM / WebCodecs
|  Touch/KB input  |  ControlMessage binary protocol
+--------+---------+
         | WebSocket
+--------v---------+
|  Node.js Server  |  Express + ws library
|  ControlCenter   |  adbkit device tracker
|  Middleware sys   |  WS proxy, multiplexer, shell, devtools
+--------+---------+
         | ADB (USB/TCP) or direct WS
+--------v---------+
| Android Device   |  Modified scrcpy-server.jar (v1.19-ws7)
| H264 encoder     |  WebSocket server on port 8886
| Input injector   |  app_process / InputManager
+------------------+
```

### WebSocket actions (endpoints)

| Action | Purpose |
|--------|---------|
| `stream` | H264 video stream from Android |
| `stream-qvh` | QVHack video stream from iOS |
| `stream-mjpeg` | MJPEG stream from iOS WDA |
| `proxy-adb` | WS proxy through ADB port forwarding |
| `proxy-ws` | Generic WebSocket proxy |
| `proxy-wda` | WebDriverAgent proxy for iOS |
| `goog-device-list` | Android device list tracking |
| `appl-device-list` | iOS device list tracking |
| `list-hosts` | Multi-server host tracking |
| `shell` | Remote adb shell (xterm.js) |
| `devtools` | Chrome DevTools forwarding |
| `list-files` | File listing on device |
| `multiplex` | WebSocket multiplexer channel |

### Key dependencies

**Server:**
- `ws` v8.18 — WebSocket
- `@dead50f7/adbkit` — ADB client (fork of DeviceFarmer/adbkit)
- `node-pty` — pseudo-terminal for remote shell
- `portfinder` — dynamic port allocation
- `ios-device-lib` — iOS device detection (optional)

**Client:**
- `h264-converter` — NALU-to-MP4 containerization (for MSE)
- `xterm.js` — terminal emulator
- Custom WASM decoders (Broadway, TinyH264)

### Configuration

- `WS_SCRCPY_CONFIG` env var → YAML config file
- `WS_SCRCPY_PATHNAME` → reverse proxy path prefix
- `SCRCPY_LISTENS_ON_ALL_INTERFACES` → device WS server binding
- Build features toggled via `webpack/build.config.override.json` (ifdef-loader)

### Source structure (183 TypeScript files)

```
/src/server/    — Node.js server (36 files)
/src/app/       — Browser client (~130 files)
/src/common/    — Shared types and constants (8 files)
/src/types/     — TypeScript type definitions (20+ files)
/vendor/        — Pre-built scrcpy-server.jar (v1.19-ws7)
```

---

## 7. Analytics and Metrics

No built-in product analytics. Client-side video quality stats available per player (dropped frames, decode time). No server-side usage tracking.

---

## 8. Risks and Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| **No authentication** — any browser on network can control devices | High | Critical | Deploy behind VPN/firewall; add reverse proxy auth (nginx basic auth, OAuth proxy) |
| **scrcpy-server fork stuck at v1.19** — upstream scrcpy at v3.x+ with audio, H265, AV1 | High | Medium | Monitor upstream; potential rebasing effort |
| **No audio streaming** | Certain | Medium | Use separate audio solution or wait for upstream merge |
| **TinyH264Player startup failure** | Medium | Low | Page reload workaround; prefer MSE or WebCodecs |
| **MsePlayer dropped frames reporting** | Medium | Low | Under investigation; use WebCodecs for accuracy |
| **Text injection ASCII-only** | Certain | Low | Use clipboard for non-ASCII text |

---

## 9. Timeline and Milestones

### Historical

- [x] Initial release with MSE + Broadway players
- [x] WebCodecs player added (Chromium-only)
- [x] Multi-server federation support
- [x] iOS experimental support (ws-qvh + WDA)
- [x] File explorer and drag-and-drop push

### Current (v0.9.0-dev)

- [ ] Still based on scrcpy v1.19 fork
- [ ] No audio streaming
- [ ] No built-in authentication
- [ ] iOS support remains experimental

---

## 10. Open Questions and Assumptions

### Open Questions

1. Will the scrcpy-server fork be rebased to upstream v2.x/v3.x for audio, H265, and AV1 support?
2. Is there a plan for built-in authentication/authorization?
3. How does multi-client stream sharing handle conflicting input (two users touching same device)?
4. What is the maximum practical number of concurrent device streams per server?

### Assumptions

1. Devices are on the same network (or reachable via ADB TCP) as the ws-scrcpy server
2. `adb` binary is available on the server host
3. Users accept higher latency vs native scrcpy in exchange for browser convenience
4. No test suite exists — stability relies on manual testing

### Out of Scope (ws-scrcpy core)

1. **Device reservation / booking** — no user management, no lock/release API
2. **CI/CD REST API** — no programmatic device allocation (contrast STF, GADS)
3. **Test orchestration** — no scenario engine, no test framework integration
4. **Audio streaming** — not supported in the scrcpy v1.19 fork
5. **Cross-platform native client** — browser-only by design

---

## 11. Resources and Team

- **Repository:** [github.com/NetrisTV/ws-scrcpy](https://github.com/NetrisTV/ws-scrcpy)
- **Forked scrcpy-server:** [github.com/NetrisTV/scrcpy](https://github.com/NetrisTV/scrcpy) (v1.19-ws7)
- **ADB client:** `@dead50f7/adbkit` (fork of DeviceFarmer/adbkit)
- **Upstream scrcpy:** [github.com/Genymobile/scrcpy](https://github.com/Genymobile/scrcpy)

---

## 12. Change Log

| Date | Version | Changes | Author |
|------|---------|---------|--------|
| 2026-03-28 | 1.0 | Initial PRD-style research (README + source analysis) | Claude |

---

## 13. Comparison: ws-scrcpy vs scrcpy vs STF

| Dimension | ws-scrcpy | scrcpy (native) | STF (OpenSTF) |
|-----------|-----------|-----------------|---------------|
| **Client** | Web browser | Native C app (SDL) | Web browser |
| **Transport** | WebSocket | ADB tunnel (TCP/USB) | WebSocket (minicap) |
| **Video codec** | H264 (scrcpy v1.19 fork) | H264/H265/AV1 (v3.x) | JPEG frames (minicap) |
| **Video decode** | MSE/WASM/WebCodecs | FFmpeg (hardware) | Canvas (JPEG) |
| **Audio** | No | Yes (v2.0+) | No |
| **Latency** | ~50-150ms (decoder-dependent) | ~35ms | ~50-100ms |
| **Multi-user** | Yes (shared stream) | No (1 client) | Yes (per-user session) |
| **Auth** | None | N/A (local) | OAuth2 tokens |
| **Device reservation** | None | N/A | REST API (reserve/release) |
| **iOS** | Experimental | No | No |
| **Shell** | xterm.js in browser | Separate terminal | Shell in UI |
| **File push** | Drag-and-drop | `adb push` | Drag-and-drop |
| **DevTools** | Integrated | Separate | Separate |
| **Multi-server** | Yes (federation) | No | Yes (provider model) |
| **Deployment** | `npm start` | Binary download | Multi-process + RethinkDB |
| **Best for** | Browser-based mirroring lab | Local dev / low-latency | Enterprise device farm |

---

## 14. Relevance to Device Farm Project

### What ws-scrcpy brings

- **Screen mirroring engine**: H264 via WebSocket is significantly better quality than minicap JPEG frames
- **Browser-native**: no minicap/minitouch binaries needed on device — scrcpy-server handles both capture and input
- **Multiple decoder fallbacks**: robust cross-browser support
- **Federation model**: multi-server awareness built in

### Integration considerations for Device Farm

| Aspect | Current Device Farm | ws-scrcpy approach | Integration path |
|--------|--------------------|--------------------|------------------|
| Screen capture | minicap (JPEG frames) | scrcpy-server (H264 stream) | Replace minicap with scrcpy-server; higher quality, lower bandwidth |
| Input injection | minitouch (text protocol) | scrcpy-server (binary ControlMessage) | Replace minitouch; scrcpy handles both capture + input |
| Device agent | STFService APK | None needed (app_process) | Simplify — no APK install required |
| Device info | STFService protobuf | adb shell commands | Already implemented in Mode B (adb_device_bootstrap.py) |
| Transport | WebSocket (custom) | WebSocket (scrcpy protocol) | Align protocols; reuse ws-scrcpy's StreamReceiver |
| Web UI | Custom dashboard | ws-scrcpy SPA | Either embed ws-scrcpy player components or adopt its UI patterns |

### Recommended approach

1. **Adopt scrcpy-server** as the unified screen+input engine (replacing minicap + minitouch)
2. **Reuse ws-scrcpy's H264 decoder** components (MsePlayer/WebCodecsPlayer) in the dashboard
3. **Keep Device Farm's** task queue, dispatcher, watchdog, and API layer
4. **Add auth/booking** that ws-scrcpy lacks — this is Device Farm's value-add
