"""
relay/adb.py — ADB helpers via subprocess.

Uses the `adb` binary directly instead of ppadb so that:
  - Multiple device operations truly run in parallel (no Python GIL / TCP-to-daemon
    serialization that ppadb suffers from at 20+ devices).
  - Each subprocess.run() is independent — one slow device never blocks another.
  - No dependency on ppadb socket lifecycle management.

All functions are blocking — call via loop.run_in_executor() from async code.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import time
from typing import Optional

logger = logging.getLogger("relay.adb")

# ── adb binary ────────────────────────────────────────────────────────────────

_ADB: str = shutil.which("adb") or "adb"


import os as _os

def _run(
    *args: str,
    serial: Optional[str] = None,
    timeout: int = 30,
) -> tuple[str, int]:
    """
    Run `adb [-s serial] <args>` and return (stdout+stderr, returncode).
    Never raises — all exceptions become ("error", -1) pairs.
    """
    cmd = [_ADB]
    if serial:
        cmd += ["-s", serial]
    cmd += list(args)
    # Suppress macOS MallocStackLogging spam in subprocess output
    env = _os.environ.copy()
    env.pop("MallocStackLogging", None)
    env.pop("MallocStackLoggingDirectory", None)
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout, env=env)
        out = (result.stdout + result.stderr).decode("utf-8", errors="replace")
        return out, result.returncode
    except subprocess.TimeoutExpired:
        return f"adb timeout after {timeout}s", -1
    except FileNotFoundError:
        return f"adb binary not found at {_ADB!r}", -1
    except Exception as exc:
        return str(exc), -1


# ── Public API ────────────────────────────────────────────────────────────────

def _list_serials() -> list[str]:
    """Snapshot of currently connected serials (startup / fallback only).
    Real-time tracking is handled by AdbDeviceWatcher (adb track-devices)."""
    out, _ = _run("devices", timeout=5)
    serials = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 2 and parts[1].strip() == "device":
            serials.append(parts[0].strip())
    return serials


def _adb_shell(serial: str, cmd: str, timeout: int = 30) -> tuple[str, int]:
    """Run shell command on device. Returns (output, exit_code)."""
    # Background commands (ending with '&') must NOT have '; echo __EXIT__$?'
    # appended — Android's /system/bin/sh rejects '&; echo...' as a syntax error.
    if cmd.rstrip().endswith("&"):
        out, _ = _run("shell", cmd, serial=serial, timeout=timeout)
        return out.rstrip("\n"), 0
    out, rc = _run("shell", f"{cmd}; echo __EXIT__$?", serial=serial, timeout=timeout)
    if "__EXIT__" in out:
        output, rc_str = out.rsplit("__EXIT__", 1)
        try:
            return output.rstrip("\n"), int(rc_str.strip())
        except ValueError:
            return output.strip(), 0
    return out.strip(), rc


def _adb_connect(ip_port: str, timeout: int = 15) -> tuple[str, int]:
    """Connect to a TCP/IP device. Returns (message, 0) on success."""
    out, _ = _run("connect", ip_port, timeout=timeout)
    ok = "connected" in out.lower() or "already connected" in out.lower()
    return out.strip(), 0 if ok else 1


def _restart_u2(serial: str, timeout: int = 60) -> tuple[str, int]:
    _U2_PKG    = "com.github.uiautomator.test"
    _U2_RUNNER = "androidx.test.runner.AndroidJUnitRunner"

    _adb_shell(serial, f"am force-stop {_U2_PKG}", timeout=10)
    _adb_shell(
        serial,
        f"nohup am instrument -w {_U2_PKG}/{_U2_RUNNER}"
        f" </dev/null >/data/local/tmp/u2.log 2>&1 &",
        timeout=10,
    )

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(1.0)
        out, _ = _adb_shell(
            serial,
            "cat /proc/net/tcp6 /proc/net/tcp 2>/dev/null | grep -i ':2330' | head -1 || true",
            timeout=5,
        )
        if out.strip():
            return "u2 started", 0
    return "u2 did not start within timeout", -1


def _probe_capabilities(serial: str) -> dict:
    """
    Probe rich device capabilities once when device first comes ONLINE.
    Includes android_version, brand, ram_gb, screen dims for device pool matching.
    """
    def shell(cmd: str) -> str:
        out, _ = _adb_shell(serial, cmd, timeout=5)
        return out.strip()

    def pkg_installed(pkg: str) -> bool:
        return "package:" in shell(f"pm path {pkg}")

    def port_open(port: int) -> bool:
        hex_port = format(port, "04X")
        return bool(shell(
            f"cat /proc/net/tcp6 /proc/net/tcp 2>/dev/null"
            f" | grep -i ':{hex_port}' | head -1 || true"
        ))

    def screen_dims() -> tuple[int, int]:
        for line in shell("wm size").splitlines():
            if "Physical size" in line and "x" in line:
                try:
                    w, h = line.split(":")[-1].strip().split("x")
                    return int(w), int(h)
                except Exception:
                    pass
        return 0, 0

    def ram_gb() -> int:
        raw = shell("cat /proc/meminfo | grep MemTotal")
        try:
            return round(int(raw.split()[1]) / 1024 / 1024)
        except Exception:
            return 0

    w, h = screen_dims()
    return {
        "sdk":             shell("getprop ro.build.version.sdk"),
        "android_version": shell("getprop ro.build.version.release"),
        "abi":             shell("getprop ro.product.cpu.abi"),
        "brand":           shell("getprop ro.product.brand").lower(),
        "model":           shell("getprop ro.product.model"),
        "screen_width":    w,
        "screen_height":   h,
        "ram_gb":          ram_gb(),
        "atx_agent":       port_open(7912),
        "u2":              pkg_installed("com.github.uiautomator"),
        "stf":             pkg_installed("jp.co.cyberagent.stf"),
        "tags":            [],  # populated by user config / env vars
    }
