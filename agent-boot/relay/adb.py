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

import base64
import logging
import os as _os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

from relay.device_state import DeviceRegistry

logger = logging.getLogger("relay.adb")

# ── adb binary ────────────────────────────────────────────────────────────────

_ADB: str = shutil.which("adb") or "adb"

# ── Asset resolution ──────────────────────────────────────────────────────────
# agent-boot/relay/adb.py lives here; assets are looked up in this order:
#   1. AGENT_BOOT_ASSETS env var (explicit override)
#   2. <agent-boot>/assets/          (production: binaries bundled with agent-boot)
#   3. <repo-root>/device_farm/bundle/ (dev: both repos side by side)

_HERE = Path(__file__).parent

def _assets_dir() -> Path:
    from_env = _os.environ.get("AGENT_BOOT_ASSETS", "").strip()
    if from_env and Path(from_env).is_dir():
        return Path(from_env)
    local = _HERE.parent / "assets"
    if local.is_dir():
        return local
    dev_bundle = _HERE.parent.parent / "device_farm" / "bundle"
    if dev_bundle.is_dir():
        return dev_bundle
    return local  # may not exist — callers check

# ABI → atx-agent binary name
_ABI_BINARY: dict[str, str] = {
    "arm64-v8a":   "atx-agent-arm64",
    "armeabi-v7a": "atx-agent-arm",
    "armeabi":     "atx-agent-arm",
    "x86_64":      "atx-agent-amd64",
    "x86":         "atx-agent-386",
}

# u2 APK package names
_U2_PKG      = "com.github.uiautomator"
_U2_TEST_PKG = "com.github.uiautomator.test"
_U2_RUNNER   = "androidx.test.runner.AndroidJUnitRunner"

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

def dedupe_adb_serials_prefer_usb(serials: list[str]) -> list[str]:
    """
    Collapse duplicate routes to the same ADB host key, preferring USB (serial
    without ':') over TCP (ip:port). Disconnects dropped TCP serials from the
    local adb server.

    Host key: part before first ':' for TCP; full serial for USB.
    """
    seen_hosts: dict[str, str] = {}
    for serial in serials:
        host = serial.split(":", 1)[0] if ":" in serial else serial
        existing = seen_hosts.get(host)
        if existing is None:
            seen_hosts[host] = serial
            continue
        new_tcp = ":" in serial
        old_tcp = ":" in existing
        if old_tcp and not new_tcp:
            seen_hosts[host] = serial
        elif not old_tcp and new_tcp:
            pass
        else:
            seen_hosts[host] = serial

    chosen = set(seen_hosts.values())
    for serial in serials:
        if ":" in serial and serial not in chosen:
            _run("disconnect", serial, timeout=15)

    return sorted(seen_hosts.values())


def _list_serials() -> list[str]:
    """Snapshot of currently connected serials (startup / fallback only).
    Real-time tracking is handled by AdbDeviceWatcher (adb track-devices)."""
    out, _ = _run("devices", timeout=5)
    serials = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 2 and parts[1].strip() == "device":
            serials.append(parts[0].strip())
    return dedupe_adb_serials_prefer_usb(serials)


def reconcile_usb_preferred_for_duplicate_devices(
    registry: DeviceRegistry,
) -> list[tuple[str, str]]:
    """
    When the same physical device appears as both USB and TCP (same
    hardware_serial in probed capabilities), disconnect TCP so ADB and the
    farm see a single stable USB serial.

    Returns [(tcp_serial, usb_serial), ...] for each TCP disconnected so the
    relay can suppress auto-reconnect while the USB anchor stays online.
    """
    disconnected: list[tuple[str, str]] = []
    by_hw: dict[str, list[str]] = {}
    for s in registry.online_serials:
        ctx = registry.get(s)
        if ctx is None:
            continue
        hw = (ctx.capabilities or {}).get("hardware_serial", "")
        if isinstance(hw, str):
            hw = hw.strip()
        if not hw:
            continue
        by_hw.setdefault(hw, []).append(s)

    for _hw, group in by_hw.items():
        usbs = [x for x in group if ":" not in x]
        tcps = [x for x in group if ":" in x]
        if not usbs or not tcps:
            continue
        usb_anchor = usbs[0]
        for w in tcps:
            out, rc = _run("disconnect", w, timeout=15)
            logger.info(
                "USB preferred: adb disconnect %s (rc=%s) %s",
                w,
                rc,
                (out or "").strip()[:120],
            )
            disconnected.append((w, usb_anchor))
    return disconnected


_IPV4_RE = re.compile(
    r"^(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)$"
)


def _looks_like_ipv4(s: str) -> bool:
    return bool(s and _IPV4_RE.match(s.strip()))


def _resolve_device_lan_ip(serial: str) -> str | None:
    """LAN IPv4 to reach atx-agent :7912 when ADB serial is USB (not ip:port)."""
    if not serial:
        return None
    for prop in ("dhcp.wlan0.ipaddress", "dhcp.wlan1.ipaddress"):
        out, _ = _adb_shell(serial, f"getprop {prop}", timeout=4)
        ip = out.strip()
        if _looks_like_ipv4(ip):
            return ip
    out, _ = _adb_shell(
        serial,
        "ip -f inet route get 8.8.8.8 2>/dev/null || ip route get 8.8.8.8 2>/dev/null",
        timeout=6,
    )
    m = re.search(r"\bsrc\s+(\d{1,3}(?:\.\d{1,3}){3})\b", out)
    if m and _looks_like_ipv4(m.group(1)):
        return m.group(1)
    return None


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


def _restart_atx(serial: str, timeout: int = 30) -> tuple[str, int]:
    """Kill atx-agent (+ any zombie u2 instrumentation) and restart it.

    atx-agent manages u2 lifecycle on-device — restarting it is faster and
    cleaner than restarting u2 instrumentation directly when atx is frozen/dead.
    """
    # Kill zombie u2 first — a stuck u2 process is the #1 reason atx freezes.
    _adb_shell(serial, "pkill -9 -f 'uiautomator' 2>/dev/null || true", timeout=5)
    _adb_shell(serial, "pkill -9 atx-agent 2>/dev/null || true", timeout=5)
    time.sleep(0.5)
    # Restart atx-agent as a background daemon.
    _adb_shell(
        serial,
        "nohup /data/local/tmp/atx-agent server -d"
        " </dev/null >/data/local/tmp/atx-agent.log 2>&1 &",
        timeout=5,
    )
    # Poll port 7912 until atx-agent is ready to accept connections.
    _ATX_PORT_HEX = "1EE8"  # 7912 decimal (0x1EE8)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(1.5)
        out, _ = _adb_shell(
            serial,
            f"cat /proc/net/tcp6 /proc/net/tcp 2>/dev/null | grep -i ':{_ATX_PORT_HEX}' | head -1 || true",
            timeout=5,
        )
        if out.strip():
            return "atx-agent started", 0
    return "atx-agent did not start within timeout", -1


def _run_bytes(
    *args: str,
    serial: Optional[str] = None,
    timeout: int = 30,
) -> tuple[bytes, int]:
    """Like _run() but returns raw stdout bytes (for binary data like screencap)."""
    cmd = [_ADB]
    if serial:
        cmd += ["-s", serial]
    cmd += list(args)
    env = _os.environ.copy()
    env.pop("MallocStackLogging", None)
    env.pop("MallocStackLoggingDirectory", None)
    try:
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, env=env,
        )
        return result.stdout, result.returncode
    except subprocess.TimeoutExpired:
        return b"", -1
    except Exception:
        return b"", -1


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
    hw_serial = shell("getprop ro.boot.serialno").strip() or shell("getprop ro.serialno").strip()
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
        "hardware_serial": hw_serial,
    }


def _screencap(serial: str, timeout: int = 30) -> tuple[str, int]:
    """Screenshot via `adb exec-out screencap -p` → base64-encoded PNG string.

    Returns ("", -1) on failure.
    exec-out avoids stdout/stderr mixing that `adb shell` suffers from for binary data.
    """
    raw, rc = _run_bytes("exec-out", "screencap", "-p", serial=serial, timeout=timeout)
    if rc != 0 or not raw:
        return "", -1
    return base64.b64encode(raw).decode("ascii"), 0


def _push_atx_agent(serial: str, abi: str) -> tuple[str, int]:
    """Push the atx-agent binary matching `abi` to /data/local/tmp/ on device."""
    binary_name = _ABI_BINARY.get(abi)
    if not binary_name:
        return f"unsupported ABI: {abi}", -1

    assets = _assets_dir()
    # Check canonical location: assets/atx-agent/<binary_name>
    candidates = [
        assets / "atx-agent" / binary_name,
        assets / binary_name,
    ]
    local_path: Optional[Path] = None
    for c in candidates:
        if c.is_file():
            local_path = c
            break

    if local_path is None:
        msg = (
            f"atx-agent binary for ABI={abi!r} not found. "
            f"Expected one of: {[str(c) for c in candidates]}. "
            f"Set AGENT_BOOT_ASSETS env var or place binary in agent-boot/assets/atx-agent/."
        )
        logger.warning(msg)
        return msg, -1

    out, rc = _run("push", str(local_path), "/data/local/tmp/atx-agent",
                   serial=serial, timeout=60)
    if rc != 0:
        return f"push failed: {out}", -1
    _adb_shell(serial, "chmod 755 /data/local/tmp/atx-agent", timeout=5)
    return "atx-agent pushed", 0


def _install_u2_apks(serial: str) -> tuple[str, int]:
    """Push and install uiautomator2 APKs onto the device."""
    assets = _assets_dir()
    # Look in assets/apks/ then assets/ directly
    apk_dirs = [assets / "apks", assets]
    main_apk: Optional[Path] = None
    test_apk: Optional[Path] = None
    for d in apk_dirs:
        m = d / "app-uiautomator.apk"
        t = d / "app-uiautomator-test.apk"
        if m.is_file() and t.is_file():
            main_apk, test_apk = m, t
            break

    if main_apk is None:
        msg = (
            f"u2 APKs not found in {assets}. "
            f"Place app-uiautomator.apk + app-uiautomator-test.apk in agent-boot/assets/apks/."
        )
        logger.warning(msg)
        return msg, -1

    # Push both APKs then install
    out, rc = _run("push", str(main_apk), "/data/local/tmp/u2-main.apk",
                   serial=serial, timeout=120)
    if rc != 0:
        return f"push u2 main APK failed: {out}", -1
    out, rc = _run("push", str(test_apk), "/data/local/tmp/u2-test.apk",
                   serial=serial, timeout=120)
    if rc != 0:
        return f"push u2 test APK failed: {out}", -1

    out_m, rc_m = _adb_shell(serial, "pm install -r /data/local/tmp/u2-main.apk", timeout=120)
    out_t, rc_t = _adb_shell(serial, "pm install -r -t /data/local/tmp/u2-test.apk", timeout=120)
    _adb_shell(serial, "rm -f /data/local/tmp/u2-main.apk /data/local/tmp/u2-test.apk", timeout=10)

    if "Success" not in out_m or "Success" not in out_t:
        return f"u2 install failed: main={out_m!r} test={out_t!r}", -1
    return "u2 APKs installed", 0


def _bootstrap_device(serial: str, timeout: int = 180) -> tuple[str, int]:
    """
    Full device bootstrap via ADB (runs in agent-boot, close to the device):

    1. Probe ABI
    2. Push atx-agent binary if missing
    3. Install u2 APKs if missing
    4. Start atx-agent (wait for port 7912)
    5. Start atx-agent (wait for port 7912)

    Returns ("bootstrap complete", 0) on success, error string + -1 on failure.
    Designed to be idempotent — safe to call multiple times.
    """
    logger.info("[%s] Bootstrap starting", serial)

    # 1. Probe ABI
    abi, _ = _adb_shell(serial, "getprop ro.product.cpu.abi", timeout=5)
    abi = abi.strip()
    logger.info("[%s] ABI=%s", serial, abi)

    # 2. Push atx-agent if not present
    out, _ = _adb_shell(serial,
        "test -f /data/local/tmp/atx-agent && echo present || echo missing", timeout=5)
    if "missing" in out:
        msg, rc = _push_atx_agent(serial, abi)
        if rc != 0:
            logger.warning("[%s] atx-agent push skipped: %s", serial, msg)
            # Non-fatal: device may already have atx-agent from a previous run
        else:
            logger.info("[%s] %s", serial, msg)

    # 3. Install u2 APKs if missing
    out, _ = _adb_shell(serial, f"pm path {_U2_PKG} 2>/dev/null || echo missing", timeout=5)
    if "package:" not in out:
        msg, rc = _install_u2_apks(serial)
        if rc != 0:
            logger.warning("[%s] u2 APK install skipped: %s", serial, msg)
            # Non-fatal: device may already have u2 installed
        else:
            logger.info("[%s] %s", serial, msg)

    # 4. Exclude u2 from Doze battery optimization (idempotent)
    for pkg in (_U2_PKG, _U2_TEST_PKG):
        _adb_shell(serial, f"dumpsys deviceidle whitelist +{pkg} 2>/dev/null || true", timeout=5)

    # 5. Start atx-agent
    msg, rc = _restart_atx(serial, timeout=min(timeout // 2, 45))
    if rc != 0:
        return f"atx-agent failed to start: {msg}", -1
    logger.info("[%s] atx-agent ready", serial)

    # 6. Start u2 instrumentation
    msg, rc = _restart_u2(serial, timeout=min(timeout // 2, 90))
    if rc != 0:
        logger.warning("[%s] u2 failed to start: %s (continuing)", serial, msg)
        # Non-fatal: atx-agent alone is sufficient for basic control
    else:
        logger.info("[%s] u2 ready", serial)

    logger.info("[%s] Bootstrap complete", serial)
    return "bootstrap complete", 0
