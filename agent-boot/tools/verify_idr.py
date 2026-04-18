#!/usr/bin/env python3
"""
verify_idr.py — Phase 1 empirical check that scrcpy-server on a given device
emits a fresh IDR keyframe when the client sends RESET_VIDEO (ctrl msg type 17).

Usage:
    uv run python tools/verify_idr.py --serial 10AE7S00HD002JK [--port 27184]

Expected logcat markers within 500ms of the send:
    - "keyframe" or "SYNC_FRAME" on MediaCodec (Android 10+)
    - "dequeueOutputBuffer" emits with flag 1 (BUFFER_FLAG_KEY_FRAME)

Exit codes:
    0  IDR observed (feature works on this device)
    1  No IDR within timeout (encoder does not honor RESET_VIDEO — Tier 1 needed)
    2  Pre-flight failure (device offline, no scrcpy running, etc.)

This test is DISRUPTIVE — it opens a second control socket to an active scrcpy
forward and may drop the live session. Run on a quiet window.
"""
from __future__ import annotations

import argparse
import re
import socket
import subprocess
import sys
import threading
import time
from typing import Optional

RESET_VIDEO = 17        # scrcpy-server ≥ 3.2 control message type
DEFAULT_PORT = 27184    # must match the agent's forward — check `adb forward --list`
WAIT_TIMEOUT = 3.0      # seconds to watch logcat after sending

_KEYFRAME_RE = re.compile(r"(keyframe|sync_frame|BUFFER_FLAG_KEY_FRAME|signalEndOfInputStream)", re.I)


def _preflight(serial: str) -> Optional[str]:
    """Return None on OK, or an error message."""
    # Device online?
    out = subprocess.run(
        ["adb", "-s", serial, "get-state"],
        capture_output=True, text=True, timeout=5,
    )
    if "device" not in out.stdout:
        return f"adb get-state: {out.stdout.strip()}{out.stderr.strip()}"
    # scrcpy-server running on device?
    r = subprocess.run(
        ["adb", "-s", serial, "shell", "pgrep", "-f", "com.genymobile.scrcpy.Server"],
        capture_output=True, text=True, timeout=5,
    )
    if not r.stdout.strip():
        return "no scrcpy-server running on device — start a session first"
    # Forward present?
    r = subprocess.run(
        ["adb", "-s", serial, "forward", "--list"],
        capture_output=True, text=True, timeout=5,
    )
    if f"localabstract:scrcpy" not in r.stdout:
        return "no adb forward to localabstract:scrcpy — agent not attached"
    return None


def _watch_logcat(serial: str, result: dict, stop: threading.Event) -> None:
    """Tail logcat in a thread, set result['hit'] on first keyframe marker."""
    proc = subprocess.Popen(
        ["adb", "-s", serial, "logcat", "-T", "1"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            if stop.is_set():
                break
            if _KEYFRAME_RE.search(line):
                result["hit"] = line.strip()
                result["hit_at"] = time.monotonic()
                break
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--serial", required=True, help="adb serial (USB or ip:port)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT,
                   help=f"local forward port (default {DEFAULT_PORT})")
    p.add_argument("--timeout", type=float, default=WAIT_TIMEOUT,
                   help=f"seconds to watch logcat (default {WAIT_TIMEOUT})")
    args = p.parse_args()

    err = _preflight(args.serial)
    if err:
        print(f"pre-flight FAIL: {err}", file=sys.stderr)
        return 2

    print(f"[verify_idr] {args.serial} port={args.port} — watching logcat for {args.timeout}s")
    result: dict = {}
    stop = threading.Event()
    watcher = threading.Thread(
        target=_watch_logcat, args=(args.serial, result, stop), daemon=True
    )
    watcher.start()
    time.sleep(0.5)  # let logcat warm up

    # Send the byte via a NEW control socket connection. WARNING — this is
    # disruptive. Using a fresh socket instead of hijacking the agent's socket
    # is intentional: no state to mutate in the agent.
    sent_at = time.monotonic()
    try:
        with socket.create_connection(("127.0.0.1", args.port), timeout=3.0) as s:
            s.sendall(bytes([RESET_VIDEO]))
    except Exception as exc:
        stop.set()
        print(f"socket send FAIL: {exc}", file=sys.stderr)
        return 2
    sent_wall = time.strftime("%H:%M:%S")
    print(f"[verify_idr] sent RESET_VIDEO at {sent_wall}")

    # Wait for watcher
    deadline = sent_at + args.timeout
    while time.monotonic() < deadline:
        if "hit" in result:
            break
        time.sleep(0.05)
    stop.set()
    watcher.join(timeout=2)

    hit = result.get("hit")
    if hit:
        delta_ms = (result["hit_at"] - sent_at) * 1000
        print(f"[verify_idr] ✅ IDR observed in {delta_ms:.0f}ms")
        print(f"            marker: {hit[:140]}")
        return 0

    print(f"[verify_idr] ❌ NO keyframe marker within {args.timeout:.1f}s")
    print(f"            Conclusion: c2.qti.avc.encoder (Vivo Codec2) likely ignores RESET_VIDEO.")
    print(f"            Recommend Tier 1 — set SCRCPY_VIDEO_ENCODER before next agent restart:")
    print(f"              export SCRCPY_VIDEO_ENCODER__{args.serial.replace(':','_').replace('.','_')}=OMX.qcom.video.encoder.avc")
    return 1


if __name__ == "__main__":
    sys.exit(main())
