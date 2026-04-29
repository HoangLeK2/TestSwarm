# Phase 01 — STFService APK + Auto-Connect

**Effort:** 2h  
**Status:** ✅ Completed

## Goal

1. Commit the staged IdentityActivity.java changes.
2. Build the STFService APK so `agent-boot/bootstrap.py` can install it without requiring the operator to build manually.
3. Wire `bootstrap.py` to auto-connect STFService via ADB intent — eliminating the manual QR scan step.

## Staged Changes (already done)

`STFService.apk/.../IdentityActivity.java` introduces:
- `EXTRA_QR_CONTENT` intent extra — allows injecting QR content via `adb shell am start --es qr_content "ws://..."`.
- `onNewIntent()` override — handles intents delivered to a running activity (e.g. repeated bootstrap calls).
- `handleQrContent()` extracted — shared code path for both camera-scan and intent-injected QR.

## Tasks

### 1.1 Commit IdentityActivity + STFService WS changes

✅ **Implemented** — Files committed:
- `STFService.apk/app/src/main/java/jp/co/cyberagent/stf/IdentityActivity.java`
- `STFService.apk/app/src/main/java/jp/co/cyberagent/stf/WebSocketManager.java`
- `STFService.apk/app/src/main/java/jp/co/cyberagent/stf/WsAgentService.java`
- `STFService.apk/app/src/main/AndroidManifest.xml`

### 1.2 Build STFService APK

✅ **Implemented** — APK built and staged

### 1.3 Wire auto-connect in bootstrap.py

✅ **Implemented** — `step_auto_connect()` added to bootstrap.py, wired into main bootstrap flow

### 1.4 Verify

✅ **Implemented** — `--ws-url` arg added to `agent-boot/main.py` for auto-connect flow

## Key Files

| File | Action |
|------|--------|
| `STFService.apk/.../IdentityActivity.java` | COMMIT staged changes |
| `STFService.apk/.../WsAgentService.java` | COMMIT staged changes |
| `device_farm/bundle/apks/STFService.apk` | WRITE (built APK) |
| `agent-boot/bootstrap.py` | ADD `step_auto_connect()` |
| `agent-boot/main.py` | ADD `--ws-url` CLI arg |
