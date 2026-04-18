# Vivo V2352A Codec2 IDR Verification

**Device:** Vivo V2352A, Android 16 (SDK 36)
**Serial:** 10AE7S00HD002JK
**Goal:** Verify that `c2.qti.avc.encoder` on this device responds to scrcpy control
message `RESET_VIDEO` (type 17) by emitting a fresh IDR keyframe within 500ms.
**Gate:** ✅ IDR observed → rollout proceeds P2-P4. ❌ no IDR → Tier 1 encoder
override must ship before P4.

## Status: PENDING — user action required

The verification is **disruptive** (interrupts a live scrcpy stream). It must be
run interactively by an operator with device + laptop access. Cook skipped the
disruptive step intentionally.

## Pre-flight (already confirmed 2026-04-18)

| Check | Result |
|-------|--------|
| scrcpy-server 3.3.4 running | ✓ PID 23569 |
| adb forward `tcp:27184 → localabstract:scrcpy` | ✓ |
| `_BUNDLED_JAR_VERSION = "3.3.4"` | ✓ ≥ 3.2 = includes RESET_VIDEO (PR #5432) |
| RESET_VIDEO protocol byte in code | ✓ `_SC_CTRL_RESET_VIDEO = 17` in `scrcpy_relay.py:100` |
| agent-boot loaded latest code | ✓ PID 30776 started after file mtime |

## Procedure (run in two terminals)

### Terminal A — logcat filter
```bash
adb -s 10AE7S00HD002JK logcat -c
adb -s 10AE7S00HD002JK logcat | grep -iE 'scrcpy|codec|keyframe|idr|sync_frame|dequeueOutputBuffer'
```

### Terminal B — send RESET_VIDEO via control socket
The relay already has a live control socket on tcp:27184. Open a SECOND
connection to the same forward port and send one byte = 0x11 (17 = RESET_VIDEO).

```python
# In a python REPL (`uv run python` inside agent-boot/):
import socket
s = socket.create_connection(("127.0.0.1", 27184))
# scrcpy expects a 64-byte device name read first on fresh connect — skip by
# just sending the byte. If scrcpy drops the connection, that's expected —
# the live relay's own control socket is independent and still running.
s.sendall(bytes([17]))
# Note the wall-clock time. Then in Terminal A look for IDR / SYNC_FRAME log
# within the next 500ms.
s.close()
```

**WARNING:** opening a fresh ctrl socket to an active scrcpy forward may confuse
the server. Safer path: add a one-shot CLI to agent-boot that calls
`session._request_idr()` on the existing session object. Prefer this if you
want a non-disruptive test.

### Expected outcomes

| Logcat within 500ms | Verdict |
|---------------------|---------|
| `MediaCodec ... keyframe` or `SYNC_FRAME` | ✅ works — proceed P2 |
| `MediaCodec ... BAD_INDEX` / error | ❌ Codec2 doesn't respect → Tier 1 needed |
| Nothing | ❌ ambiguous — try 3 more times, count fraction that work |

### Recording

After running, append below:

```
[TIMESTAMP] IDR sent at HH:MM:SS.mmm → IDR observed at HH:MM:SS.mmm (delta: Xms)
[TIMESTAMP] IDR sent at HH:MM:SS.mmm → NO RESPONSE (60s wait)
...

Verdict: WORKS | DOESN'T WORK | INCONCLUSIVE
```

## Less disruptive alternative — natural-trigger test

Wait for a natural frame stall (encoder freeze), then check if the agent-boot
log emits `requested IDR keyframe` AND the stream recovers within 500ms
(`last_frame_time` bumps up in session state).

Run:
```bash
kill -0 $(pgrep -f main.py) && echo "agent alive"
grep -E 'requested IDR keyframe|encoder stalled|last_frame_time' /tmp/agent-canary.log | tail -40
```

If we see `requested IDR keyframe` AND no `encoder stalled` RuntimeError within
~5s of that line → IDR recovery path is working in production.

## Fallback if verification fails

Mandate Tier 1 before P4 deploy:

1. Edit `relay/scrcpy_relay.py:_start_scrcpy_server`:
   - Read `SCRCPY_VIDEO_ENCODER` env var.
   - Append `video_encoder=OMX.qcom.video.encoder.avc` to server_cmd if set.
2. Export on launch for Vivo devices: `SCRCPY_VIDEO_ENCODER=OMX.qcom.video.encoder.avc`.
3. Probe `--list-encoders` in bootstrap and log what's available per device.

This pins the Qualcomm HW encoder instead of Vivo's Codec2 wrapper. See
`docs/plans/agent-boot-stability/references/famous-solutions-research.md` Tier 1.
