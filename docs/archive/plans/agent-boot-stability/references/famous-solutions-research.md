# Research: Famous OSS solutions for agent-boot stability problems

**Date:** 2026-04-18
**Scope:** Find battle-tested open-source solutions for (A) USB+WiFi hot-failover in Android device farms, (B) Vivo/MIUI/ColorOS scrcpy encoder stall on Android 16 SDK 36.
**Method:** 4× WebSearch (Gemini auth still broken).

---

## Executive Summary

1. **USB+WiFi hot-failover** — **no famous OSS has it.** STF, atxserver2, Appium farm, agoda-android-farm all use single-transport. Our dual-transport design would be novel; the good news is we don't need to import a library, the bad news is no reference implementation to copy. Ship the stability fixes first (they already deliver 80% of the value), then reconsider only if residual pain justifies the complexity.
2. **Vivo/OEM Codec2 stall** — **our current fix (IDR request on 1.5s stall) matches scrcpy upstream's own strategy.** Upstream PR #5432 shipped the same RESET_VIDEO control message for the same reason. Additional levers worth adding: encoder allowlist (`--video-encoder=OMX.qcom.video.encoder.avc`), H265 fallback, and version pinning (v3.2+ regressed on some ColorOS 15 devices per issue #6022).
3. **"Unplug and replug" is the industry state of the art for stubborn USB flap.** Appium forums, STF forums, and XDA all converge on this. There is no magic reconnect.

---

## Key findings

### A — USB + WiFi dual transport

| Project | Transport | Failover | Notes |
|---------|-----------|----------|-------|
| [openstf/stf](https://github.com/openstf/stf) | USB via adb server | None | WiFi "supported" but community reports it as flaky ([#16](https://github.com/openstf/stf/issues/16)) |
| [openatx/atxserver2-android-provider](https://github.com/openatx/atxserver2-android-provider) | USB primary via `adb track-devices`; TCP also accepted | No hot-failover — each transport is a separate device entry | Auto-installs minicap, minitouch, atx-agent, app-uiautomator on connect |
| [agoda-com/android-farm](https://github.com/agoda-com/android-farm) | USB + emulators | N/A (emulator replaces flaky USB) | Agoda's answer to USB pain: switch to emulators |
| [tinyzimmer/android-farm-operator](https://github.com/tinyzimmer/android-farm-operator) | K8s-scheduled, USB pass-through to pod | None | Solves scale, not transport resilience |
| [AppiumTestDistribution/appium-device-farm](https://github.com/AppiumTestDistribution/appium-device-farm) | USB or TCP, not both | None | Remote-ADB setup is known painful ([#714](https://github.com/AppiumTestDistribution/appium-device-farm/issues/714)) |

**Verdict:** no famous project solves USB+WiFi hot-failover. The *de facto* patterns are:

1. **Single transport per device entry** (our current behavior when the reconcile logic disconnects TCP).
2. **Emulator replacement** when USB is unreliable (Agoda's approach).
3. **Manual reconnect** — Appium/STF forums all recommend unplug/replug.

If we still want dual-transport, we build it ourselves. References to copy behaviors from:
- `atxserver2-android-provider`'s `adb track-devices` watcher — we already have an equivalent.
- STF's per-device state machine — we already have `DeviceRegistry`.
- K8s operator's liveness probe pattern — nothing prevents us copying the idea into `RelaySupervisor`.

**Implication for our plan:** the USB+WiFi hot-failover proposal stands as a greenfield feature. It would put us ahead of the pack, but it's unproven and we lose the "match the ecosystem" benefit. Recommend: do NOT build it until after we observe 1-2 weeks of the stability fixes in production.

---

### B — Vivo/MIUI/ColorOS scrcpy encoder stall

**Upstream already knows this class of bug and landed the exact fix we just shipped:**

- **[scrcpy PR #5432 (rom1v, Sep 2024)](https://github.com/Genymobile/scrcpy/pull/5432)** — "Add shortcut to reset video capture/encoding." Client-side shortcut `MOD+Shift+R` sends a control message that calls `signalEndOfInputStream()` on the device-side MediaCodec, interrupting `dequeueOutputBuffer()` immediately and emitting a new keyframe. Same idea, same mechanism, same ~200ms recovery. **Confirms our Phase 1 IDR-request is upstream-aligned.**
- **[Issue #5947](https://github.com/Genymobile/scrcpy/issues/5947)** — users manually reset video on fullscreen YouTube transitions. Same root cause: encoder stalls when resolution/format changes.
- **[Issue #6022 (OnePlus ColorOS 15 / Android 15)](https://github.com/Genymobile/scrcpy/issues/6022)** — v3.2+ regressed on some ColorOS 15 devices; daily freezes. Downgrade to v2.7 fixes it. **Our bundled JAR is 3.3.4 — worth keeping v2.7 as a fallback.**
- **[Issue #6238 (Xiaomi MIUI delay)](https://github.com/Genymobile/scrcpy/issues/6238)** — known latency on MIUI. No fix.
- **[Issue #3127 (MIUI 12.5 → 13 breaks scrcpy)](https://github.com/Genymobile/scrcpy/issues/3127)** — OEM major-version updates regularly break encoder config.
- **[Issue #5286 (h264 encoder create failed)](https://github.com/Genymobile/scrcpy/issues/5286)** — workaround: `--video-encoder=OMX.qcom.video.encoder.avc`. Upstream supports per-device encoder override.
- **[Issue #1810 (OMX.Intel.hw_ve.h264 crash)](https://github.com/Genymobile/scrcpy/issues/1810)** — dedicated HW encoder crashes under load; switch encoder.
- **[Issue #5646](https://github.com/Genymobile/scrcpy/issues/5646)** — MediaCodec errors after phone reboot (not our case, but same class).
- **[Issue #3260](https://github.com/Genymobile/scrcpy/issues/3260)** — IDR frame interval support (our `i-frame-interval:int=1` already applies).
- **[scrcpy video.md](https://github.com/Genymobile/scrcpy/blob/master/doc/video.md)** — H264 default (low latency), H265 better quality, AV1 too slow for production, software encoders exist but slow. `--no-downsize-on-error` flag controls auto-downsize behavior.

**Levers we are NOT yet using:**

| Lever | Our state | What to consider |
|-------|-----------|------------------|
| `--video-encoder=OMX.qcom.video.encoder.avc` | not set | Qualcomm HW encoder explicit — avoids whatever Vivo custom encoder Codec2 picks by default. The `C2.qti.avc.encoder` on Vivo Android 16 may be the problem. |
| `video_codec=h265` instead of h264 | h264 | H265 encoders on recent OEMs are often more stable than H264. Try on one Vivo device. |
| Fallback to scrcpy v2.7 JAR | v3.3.4 bundled | One bug report of v3.2+ regression on ColorOS. Keep v2.7 as env-switchable fallback. |
| `--no-downsize-on-error` | unused | When encoder errors, scrcpy halves resolution. Useful for us (farm runs small anyway, 480px max). Explicit OFF → fail fast instead of silently degrading. |
| Encoder allowlist per device model | not set | Bootstrap can probe `--list-encoders` per device and persist a per-model preference. |

**All five are low-risk env/config changes — no code surgery.**

---

## Recommended incremental actions (ordered by effort/impact)

### Tier 1 — ship now, env-only (30 min each)

1. **Add `SCRCPY_VIDEO_ENCODER` env override** in `scrcpy_relay._start_scrcpy_server`. Default empty (let scrcpy pick). Let ops set `OMX.qcom.video.encoder.avc` on Vivo devices without code redeploy.
2. **Add `SCRCPY_VIDEO_CODEC` env override** (default h264). Switch specific devices to h265 if they stall.
3. **Add `SCRCPY_JAR_VERSION` env override** with bundled v3.3.4 and a checked-in v2.7 fallback. Switch per serial if v3.x regresses (ColorOS #6022 pattern).
4. **Probe `adb shell ime/dumpsys media.codec --list-encoders` in bootstrap** and log the H264 encoder list. Helps diagnose which device needs which encoder.

### Tier 2 — cheap code add (half day)

5. **On frame-timeout → retry with fallback encoder.** Our current flow goes: IDR → hard timeout → restart. Add a third step: on the *second* consecutive restart within 60s, flip to fallback encoder (env-defined). One device one bad encoder ≠ all devices one bad encoder.
6. **Per-serial encoder memory** in agent state. Persist the last-working encoder per `hardware_serial` in `/data/local/tmp/scrcpy-encoder.ok`. Survives reboot.

### Tier 3 — only if Tier 1+2 insufficient (multi-day)

7. **USB+WiFi hot-failover**. Our original proposal. No famous OSS template to copy — we'd be the first. Wait 1-2 weeks of Tier 1+2 signal before committing.

---

## Common pitfalls (from issue trackers)

1. **Don't blindly downgrade scrcpy-server** — ColorOS 15 needs v2.7; other devices may regress on v2.7. Make it per-serial.
2. **Don't force encoder options `profile=` / `level=`** — #1 cause of MediaCodec crash on API 34+. Our code already avoids this, keep avoiding.
3. **OMX.* encoder names are legacy.** On Android 12+ (SDK 31+), the framework exposes `c2.*` names. Use whatever `--list-encoders` returns.
4. **Virtual display capture** (what scrcpy uses on newer Androids) can behave differently from `--display-id=0` main display. Our SurfaceFlinger dump showed `virtual:com.android.shell,2000,scrcpy,27` — this is normal, not a bug.
5. **`signalEndOfInputStream()` vs restarting MediaCodec** — upstream PR #5432 chose the former because it's ~200ms vs ~2s for full restart. Our `_request_idr` is the client side of this; we must NOT also tear down the session on the first stall (already correct).

---

## Unresolved questions

1. Does Vivo V2352A's `c2.qti.avc.encoder` respond to RESET_VIDEO (signalEndOfInputStream)? Need empirical test — send keyframe request via `send_control(bytes([17]))` on a running session and observe if new IDR arrives in <500ms.
2. Is scrcpy v2.7 protocol compatible with our current frame parser? If we want per-serial jar override we must verify the binary frame format didn't change between 2.7 and 3.3.4.
3. Can we reliably detect "this device's encoder is bad" without trial-and-error? Probably not — have to observe retry pattern and flip.

## Next steps

1. Ship the stability fixes from yesterday/today (commit + deploy). Observe.
2. **Tier 1** env overrides — one PR, 1h work.
3. Wait 1-2 weeks. Only then decide on Tier 2/3.
