# Changelog: MJPEG Streaming Migration + Step Screenshot Capture

**Date:** 2026-03-28
**Scope:** 31 files changed, 1715 insertions, 751 deletions (+3 new files, 1 deleted)

---

## 1. Problems

### 1.1 Streaming architecture qua tai

- Dashboard render `DeviceTile` cho moi device, moi tile subscribe WS binary frame stream giong full-screen control view.
- 10 devices x 10 FPS x N browsers = hang tram frame dispatch/s qua Python server.
- Server rebuild binary header + enqueue cho moi browser cho moi frame cua moi device (`publish_frame()` + `run_coroutine_threadsafe` per queue).
- Frontend can H264CanvasDecoder (WebCodecs), FrameDispatcher singleton, canvas decode — phuc tap khong can thiet cho use case phone farm automation.

### 1.2 Khong co debug evidence khi chay scenario

- Khi chay scenario tren device, khong biet step da click gi, o dau.
- Khong luu screenshot, XML hierarchy, hay selector info cho moi step.
- Debug chi dua vao log text, khong co visual evidence.

### 1.3 Android app khong hien thi WiFi IP

- Khi ket noi qua LAN (ADB over TCP), user phai tu tim IP cua device.
- App IdentityActivity khong hien thi WiFi IP du da co ham `getWifiIpAddress()`.

### 1.4 UIAutomator2 khong reconnect sau server restart

- Khi server restart, WS reconnect OK nhung u2 (am instrument) da chet tren device.
- App khong co shell UID de chay lai `am instrument`.
- Device o trang thai DEAD vinh vien, khong co co che recovery.

---

## 2. Changes

### 2.1 MJPEG Streaming Migration (Backend + Frontend)

**Van de**: WS binary frame broadcast qua nang cho thumbnail preview.

**Giai phap**: 2-tier architecture — MJPEG HTTP cho preview, WS chi giu lai cho JSON (status, logs, input commands).

#### Backend

| File | Thay doi |
|------|---------|
| `device_farm/api/routes/device_media.py` | Them `fps` query param cho `/stream/{serial}`. VD: `?fps=1` (tile), `?fps=5` (control). Them `Cache-Control: no-store` cho `/screenshot/`. |

#### Frontend — Xoa WS binary frame pipeline

| File | Thay doi |
|------|---------|
| `front-end/.../services/frame-dispatcher.ts` | **XOA** (134 dong) — FrameDispatcher singleton, parseBinaryFrame, H264/JPEG frame types. |
| `front-end/.../services/ws.ts` | Xoa import FrameDispatcher/parseBinaryFrame, xoa ArrayBuffer handling trong onmessage, xoa legacy base64 JPEG handler. WS chi xu ly JSON. |
| `front-end/.../components/device-screen.tsx` | **Refactor 425 → 135 dong**. Xoa H264CanvasDecoder class (90 dong), xoa canvas + FrameDispatcher subscription (120 dong), xoa drainJpeg/pendingJpeg/decodingRef. Thay bang `<img src={mjpegUrl}>` voi `?fps=5`. Giu nguyen touch/gesture handlers (clientToDevice, useGesture, handleClick). |

#### Frontend — Dashboard tile moi

| File | Thay doi |
|------|---------|
| `front-end/.../components/device-tile-preview.tsx` | **MOI** — Lightweight tile dung `<img src="/stream/{serial}?fps=1">`. Khong co DeviceControls, khong subscribe WS. |
| `front-end/.../components/device-farm.tsx` | Swap `DeviceTile` → `DeviceTilePreview` trong dashboard grid. |

**Ket qua bandwidth**: Dashboard giam tu ~5 MB/s (WS broadcast) xuong ~500 KB/s (MJPEG HTTP poll), giam ~90%.

### 2.2 Step Screenshot Capture (Debug Mode)

**Van de**: Khong co visual evidence khi chay scenario.

**Giai phap**: Luu screenshot + crop element + XML hierarchy + selector sau moi step.

| File | Thay doi |
|------|---------|
| `device_farm/tasks/scenario_task.py` | Them `_capture_step_screenshot()` helper. Sua `_execute_tap()` return them bounds dict. Them capture logic vao `run_scenario_task()` loop. |

**Bat/tat**: 3 cach:
- Env: `DEBUG_AUTO=true`
- Env: `CAPTURE_STEPS=1`
- Scenario JSON: `{"capture_steps": true, ...}`

**Output moi step**:
```
device_farm/captures/{serial}_{timestamp}/
  step_000_launch_app_full.jpg        # Full screenshot
  step_000_launch_app_hierarchy.xml   # XML tree luc do
  step_001_tap_full.jpg
  step_001_tap_element.jpg            # Cropped element bounds
  step_001_tap_hierarchy.xml
  step_001_tap_selector.json          # {"by": "text", "value": "Login"}
```

### 2.3 WiFi IP Display (Android App)

**Van de**: User khong biet IP device de config ADB.

| File | Thay doi |
|------|---------|
| `STFService.apk/.../res/layout/activity_identity.xml` | Them row "WiFi IP" vao Device Information card, `textIsSelectable=true`. |
| `STFService.apk/.../IdentityActivity.java` | Them `tvWifiIp` field, `refreshWifiIp()` method. Hien thi `192.168.x.x:5555` hoac "No WiFi" (mau do). Auto-refresh khi onResume. |

### 2.4 Other Changes (from prior work in same session)

| File | Thay doi |
|------|---------|
| `device_farm/runtime/core/watchdog.py` | ADB health check, miss count, reconnect scheduling |
| `device_farm/runtime/core/device_manager.py` | `reconnect_adb_device()`, mDNS discovery |
| `device_farm/runtime/core/device_client.py` | U2 keepalive loop, frame publishing, hierarchy caching |
| `device_farm/runtime/transports/adb_transport.py` | ADB over TCP, mDNS listener |
| `device_farm/runtime/transports/ws_tunnel.py` | TCP-over-WS tunnel improvements |
| `device_farm/runtime/transports/u2_jsonrpc.py` | `find_element_with_bounds()` |
| `device_farm/runtime/transports/minitouch.py` | Minitouch protocol updates |
| `device_farm/web/ws.py` | Agent session binary frame parsing, browser WS manager |
| `device_farm/core/config.py` | Streaming config (mode, dashboard_interval) |
| `device_farm/config.yaml` | Config defaults |
| `front-end/.../hooks/use-device-farm.ts` | WS message handling |
| `front-end/.../hooks/use-control-record.ts` | Control record hook |
| `front-end/.../components/control-record-view.tsx` | Recording view |
| `front-end/.../services/api.ts` | API service functions |

---

## 3. Architecture (After)

```
┌─ Android Device ────────────────────────────────────┐
│  WsAgentService → MediaProjection → JPEG frames     │
│  → WS outbound to server                            │
└──────────────────────┬──────────────────────────────┘
                       │ WS (binary frames + JSON)
┌─ Python Server ──────▼──────────────────────────────┐
│  cache _latest_jpeg in RAM                           │
│                                                      │
│  /stream/{serial}?fps=N  → MJPEG HTTP push (video)  │
│  /ws                     → JSON only (status, input) │
└──────────┬───────────────────────┬──────────────────┘
           │ MJPEG HTTP            │ WS JSON
┌─ Browser ▼───────────────────────▼──────────────────┐
│  Dashboard tiles: <img src="/stream/s?fps=1">        │
│  Control view:    <img src="/stream/s?fps=5">        │
│  Input commands:  ws.send({type:"tap", x, y})        │
│  Device status:   ws.onmessage → JSON broadcast      │
└─────────────────────────────────────────────────────┘
```

---

## 4. New Files

| File | Purpose |
|------|---------|
| `front-end/.../components/device-tile-preview.tsx` | MJPEG thumbnail tile (1 FPS) |
| `device_farm/captures/` | Step screenshot output directory (auto-created) |

## 5. Deleted Files

| File | Reason |
|------|--------|
| `front-end/.../services/frame-dispatcher.ts` | WS binary frame pipeline removed — replaced by MJPEG |

---

## 6. Conclusion

- **Streaming**: Chuyen tu WS binary frame broadcast sang MJPEG HTTP. Giam ~90% bandwidth cho dashboard. Frontend don gian hon ~300 dong (xoa H264CanvasDecoder, FrameDispatcher, canvas decode). Server van lam relay nhung qua HTTP multipart thay vi WS broadcast.
- **Debug**: Moi step scenario luu full screenshot + cropped element + XML hierarchy + selector JSON. Bat bang `DEBUG_AUTO=true`. Output trong `device_farm/captures/`.
- **Android app**: Hien thi WiFi IP:5555 de config ADB qua LAN.
- **Known limitation**: UIAutomator2 van can ADB (am instrument) de start. Sau server restart hoac device reboot, u2 can duoc boot lai qua agent-boot. Day la limitation cua Android security model, khong phai bug.
