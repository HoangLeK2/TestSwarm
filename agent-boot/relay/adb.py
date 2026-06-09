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
import urllib.error
import urllib.request
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
_STF_PKG     = "jp.co.cyberagent.stf"
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
    if ":" in serial:
        host = serial.rsplit(":", 1)[0].strip()
        if _looks_like_ipv4(host):
            return host
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


def _device_port_listening(serial: str, port: int, timeout: int = 5) -> bool:
    hex_port = format(port, "04X")
    out, _ = _adb_shell(
        serial,
        f"cat /proc/net/tcp6 /proc/net/tcp 2>/dev/null | grep -i ':{hex_port}' | head -1 || true",
        timeout=timeout,
    )
    return bool(out.strip())


def _atx_http_ping(serial: str, timeout: float = 2.0, host: str | None = None) -> tuple[bool, str]:
    host = host or _resolve_device_lan_ip(serial)
    if not host:
        return False, "device LAN IP unavailable"
    url = f"http://{host}:7912/ping"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read(128).decode("utf-8", errors="replace").strip()
            if 200 <= int(resp.status) < 300:
                return True, body or f"HTTP {resp.status}"
            return False, f"HTTP {resp.status}: {body}"
    except urllib.error.HTTPError as exc:
        body = exc.read(128).decode("utf-8", errors="replace") if exc.fp else ""
        return False, f"HTTP {exc.code}: {body.strip()}"
    except Exception as exc:
        return False, str(exc)


def _restart_u2(serial: str, timeout: int = 60) -> tuple[str, int]:
    _apply_u2_stability_settings(serial)
    _adb_shell(serial, f"am force-stop {_U2_TEST_PKG}", timeout=10)
    _adb_shell(serial, f"am force-stop {_U2_PKG}", timeout=10)
    _adb_shell(serial, "pkill -9 -f 'uiautomator' 2>/dev/null || true", timeout=5)
    time.sleep(0.3)
    _adb_shell(
        serial,
        f"nohup am instrument -w -e debug false {_U2_TEST_PKG}/{_U2_RUNNER}"
        f" </dev/null >/data/local/tmp/u2.log 2>&1 &",
        timeout=10,
    )

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(1.0)
        if _device_port_listening(serial, 9008):
            lock_portrait_rotation(serial)
            return "u2 started", 0
    log_tail, _ = _adb_shell(serial, "tail -n 40 /data/local/tmp/u2.log 2>/dev/null || true", timeout=5)
    return f"u2 did not start within timeout; log_tail={log_tail[-1000:]}", -1


def _restart_atx(serial: str, timeout: int = 30) -> tuple[str, int]:
    """Kill atx-agent (+ any zombie u2 instrumentation) and restart it.

    atx-agent manages u2 lifecycle on-device — restarting it is faster and
    cleaner than restarting u2 instrumentation directly when atx is frozen/dead.
    """
    _apply_u2_stability_settings(serial)
    # Kill zombie u2 first — a stuck u2 process is the #1 reason atx freezes.
    _adb_shell(serial, "/data/local/tmp/atx-agent server --stop 2>/dev/null || true", timeout=5)
    _adb_shell(serial, f"am force-stop {_U2_TEST_PKG}", timeout=10)
    _adb_shell(serial, f"am force-stop {_U2_PKG}", timeout=10)
    _adb_shell(serial, "pkill -9 -f 'uiautomator' 2>/dev/null || true", timeout=5)
    _adb_shell(serial, "pkill -9 -f 'atx-agent' 2>/dev/null || true", timeout=5)
    time.sleep(0.5)
    # Restart atx-agent as a background daemon.
    _adb_shell(
        serial,
        "nohup /data/local/tmp/atx-agent server -d"
        " </dev/null >/data/local/tmp/atx-agent.log 2>&1 &",
        timeout=5,
    )
    # Poll until atx-agent is actually responsive. Port-open alone can be a
    # false positive when the Go process accepts but the HTTP handler is wedged.
    deadline = time.monotonic() + timeout
    last_ping = ""
    atx_host = _resolve_device_lan_ip(serial)
    while time.monotonic() < deadline:
        time.sleep(1.5)
        ok, last_ping = _atx_http_ping(serial, host=atx_host)
        if ok:
            return "atx-agent started", 0
        if not last_ping.startswith("device LAN IP unavailable"):
            continue
        if _device_port_listening(serial, 7912):
            return "atx-agent started (port check only; LAN HTTP unavailable)", 0
    log_tail, _ = _adb_shell(serial, "tail -n 60 /data/local/tmp/atx-agent.log 2>/dev/null || true", timeout=5)
    return f"atx-agent did not start within timeout; last_ping={last_ping}; log_tail={log_tail[-1000:]}", -1


def _lock_rotation_enabled() -> bool:
    """Env AGENT_BOOT_LOCK_ROTATION (default on)."""
    raw = _os.environ.get("AGENT_BOOT_LOCK_ROTATION", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def lock_rotation_after_shell_enabled() -> bool:
    """Re-apply lock after each ADB shell from device_farm (default on).

    Env: AGENT_BOOT_LOCK_ROTATION_AFTER_SHELL=0 to disable.
    """
    raw = _os.environ.get("AGENT_BOOT_LOCK_ROTATION_AFTER_SHELL", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def lock_portrait_rotation(serial: str) -> None:
    """Disable auto-rotate and lock portrait (best-effort, idempotent)."""
    if not _lock_rotation_enabled():
        return
    for cmd in (
        "settings put system accelerometer_rotation 0",
        "settings put system user_rotation 0",
    ):
        _adb_shell(serial, cmd, timeout=5)


def _apply_u2_stability_settings(serial: str) -> None:
    """
    Best-effort Android/OEM settings that keep u2 alive on aggressive ROMs.

    Vivo/iQOO commonly kills instrumentation/native background processes when
    the screen turns off. These commands are idempotent and intentionally
    non-fatal: some ROM builds reject one or more appops/settings.
    """
    commands = [
        # Keep display awake while the farm is attached over USB/charging.
        "settings put global stay_on_while_plugged_in 3",
        "svc power stayon true",
        "settings put system screen_off_timeout 2147483647",
        # Reduce Doze/background restrictions for the app and u2 packages.
        f"dumpsys deviceidle whitelist +{_STF_PKG} 2>/dev/null || true",
        f"dumpsys deviceidle whitelist +{_U2_PKG} 2>/dev/null || true",
        f"dumpsys deviceidle whitelist +{_U2_TEST_PKG} 2>/dev/null || true",
        f"cmd deviceidle whitelist +{_STF_PKG} 2>/dev/null || true",
        f"cmd deviceidle whitelist +{_U2_PKG} 2>/dev/null || true",
        f"cmd deviceidle whitelist +{_U2_TEST_PKG} 2>/dev/null || true",
        # openatx recommends overlay appop; harmless when unsupported.
        f"appops set {_U2_PKG} SYSTEM_ALERT_WINDOW allow 2>/dev/null || true",
        f"appops set {_U2_TEST_PKG} SYSTEM_ALERT_WINDOW allow 2>/dev/null || true",
        f"appops set {_STF_PKG} RUN_IN_BACKGROUND allow 2>/dev/null || true",
        f"appops set {_STF_PKG} RUN_ANY_IN_BACKGROUND allow 2>/dev/null || true",
    ]
    for cmd in commands:
        _adb_shell(serial, cmd, timeout=5)
    lock_portrait_rotation(serial)


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

    def first_nonempty(*values: str) -> str:
        for value in values:
            value = (value or "").strip()
            if value and value.lower() not in {"null", "unknown", "<unknown>"}:
                return value
        return ""

    def wlan_addr() -> tuple[str, str]:
        raw = shell("ip -o -4 addr show wlan0 2>/dev/null || ip -o -4 addr show 2>/dev/null")
        for match in re.finditer(r"\binet\s+(\d+\.\d+\.\d+\.\d+)/(\d+)", raw):
            ip = match.group(1)
            prefix = match.group(2)
            if not ip.startswith("127."):
                return ip, f"{ip}/{prefix}"
        return "", ""

    w, h = screen_dims()
    brand = shell("getprop ro.product.brand").lower()
    model = shell("getprop ro.product.model")
    marketing_name = first_nonempty(
        shell("getprop ro.product.marketname"),
        shell("getprop ro.config.marketing_name"),
        shell("getprop ro.product.vendor.marketname"),
    )
    device_name = first_nonempty(
        shell("settings get global device_name"),
        shell("settings get secure bluetooth_name"),
        shell("getprop persist.sys.device_name"),
        marketing_name,
        model,
    )
    wifi_ip, wifi_cidr = wlan_addr()
    hw_serial = shell("getprop ro.boot.serialno").strip() or shell("getprop ro.serialno").strip()
    return {
        "sdk":             shell("getprop ro.build.version.sdk"),
        "android_version": shell("getprop ro.build.version.release"),
        "abi":             shell("getprop ro.product.cpu.abi"),
        "brand":           brand,
        "model":           model,
        "device_name":     device_name,
        "marketing_name":  marketing_name,
        "display_name":    first_nonempty(device_name, marketing_name, " ".join(p for p in [brand, model] if p)),
        "wlan_ip":         wifi_ip,
        "wlan_cidr":       wifi_cidr,
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
    force_install = _os.getenv("AGENT_BOOT_FORCE_U2_INSTALL", "").strip().lower() in {"1", "true", "yes", "on"}
    installed_main = _pkg_installed(serial, _U2_PKG)
    installed_test = _pkg_installed(serial, _U2_TEST_PKG)
    if installed_main and installed_test and not force_install:
        return "u2 APKs already installed", 0

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

    out_m = "Success"
    out_t = "Success"
    if force_install or not installed_main:
        out, rc = _run("push", str(main_apk), "/data/local/tmp/u2-main.apk",
                       serial=serial, timeout=120)
        if rc != 0:
            return f"push u2 main APK failed: {out}", -1
        out_m, rc_m = _adb_shell(serial, "pm install -r /data/local/tmp/u2-main.apk", timeout=120)
    if force_install or not installed_test:
        out, rc = _run("push", str(test_apk), "/data/local/tmp/u2-test.apk",
                       serial=serial, timeout=120)
        if rc != 0:
            return f"push u2 test APK failed: {out}", -1
        out_t, rc_t = _adb_shell(serial, "pm install -r -t /data/local/tmp/u2-test.apk", timeout=120)

    combined = f"{out_m}\n{out_t}"
    if "INSTALL_FAILED_UPDATE_INCOMPATIBLE" in combined or "signatures do not match" in combined:
        _adb_shell(serial, f"pm uninstall {_U2_TEST_PKG} 2>/dev/null || true", timeout=30)
        _adb_shell(serial, f"pm uninstall {_U2_PKG} 2>/dev/null || true", timeout=30)
        out, rc = _run("push", str(main_apk), "/data/local/tmp/u2-main.apk",
                       serial=serial, timeout=120)
        if rc != 0:
            return f"push u2 main APK failed after uninstall: {out}", -1
        out, rc = _run("push", str(test_apk), "/data/local/tmp/u2-test.apk",
                       serial=serial, timeout=120)
        if rc != 0:
            return f"push u2 test APK failed after uninstall: {out}", -1
        out_m, rc_m = _adb_shell(serial, "pm install -r /data/local/tmp/u2-main.apk", timeout=120)
        out_t, rc_t = _adb_shell(serial, "pm install -r -t /data/local/tmp/u2-test.apk", timeout=120)

    _adb_shell(serial, "rm -f /data/local/tmp/u2-main.apk /data/local/tmp/u2-test.apk", timeout=10)

    if "Success" not in out_m or "Success" not in out_t:
        return f"u2 install failed: main={out_m!r} test={out_t!r}", -1
    if installed_main or installed_test:
        return "u2 APKs already installed; installed missing package(s)", 0
    return "u2 APKs installed", 0


def _pkg_installed(serial: str, package: str) -> bool:
    out, _ = _adb_shell(serial, f"pm path {package} 2>/dev/null || true", timeout=5)
    return "package:" in out


def _install_stf_apk(serial: str) -> tuple[str, int]:
    if _pkg_installed(serial, _STF_PKG):
        return "STFService already installed", 0

    assets = _assets_dir()
    candidates = [
        assets / "apks" / "STFService.apk",
        assets / "STFService.apk",
    ]
    apk_path = next((p for p in candidates if p.is_file()), None)
    if apk_path is None:
        return (
            f"STFService.apk not found. Expected one of: {[str(p) for p in candidates]}. "
            "Set AGENT_BOOT_ASSETS or put STFService.apk in agent-boot/assets/apks/.",
            -1,
        )

    out, rc = _run("install", "-r", str(apk_path), serial=serial, timeout=180)
    if rc != 0 or "Success" not in out:
        return f"STFService install failed: {out}", -1
    return "STFService installed", 0


def _grant_stf_permissions(serial: str) -> list[str]:
    notes: list[str] = []
    for perm in ("android.permission.WRITE_SECURE_SETTINGS", "android.permission.READ_PHONE_STATE"):
        out, rc = _adb_shell(serial, f"pm grant {_STF_PKG} {perm}", timeout=10)
        if rc != 0 or "Exception" in out:
            notes.append(f"pm grant {perm}: {out[:200]}")
    return notes


def _u2_atx_healthy(serial: str) -> bool:
    """True when atx-agent and u2 instrumentation are already up (skip cold restart)."""
    atx_host = _resolve_device_lan_ip(serial)
    atx_ok, ping_err = _atx_http_ping(serial, host=atx_host)
    if not atx_ok and not ping_err.startswith("device LAN IP unavailable"):
        atx_ok = _device_port_listening(serial, 7912)
    elif not atx_ok:
        atx_ok = _device_port_listening(serial, 7912)
    return atx_ok and _device_port_listening(serial, 9008)


def _bootstrap_device(serial: str, timeout: int = 180) -> tuple[str, int]:
    """
    Full device bootstrap via ADB (runs in agent-boot, close to the device):

    1. Probe ABI
    2. Push atx-agent binary if missing
    3. Install u2 APKs from the current bundle
    4. Install STFService if missing
    5. Apply permissions/stability settings
    6. Start atx-agent (wait for port 7912)
    7. Start u2 instrumentation

    Returns a compact JSON summary on success, error string + -1 on failure.
    Designed to be idempotent — safe to call multiple times.
    """
    import json as _json

    logger.info("[%s] Bootstrap starting", serial)
    summary: dict[str, object] = {
        "stf_installed": False,
        "u2_ready": False,
        "atx_ready": False,
        "permissions_ok": True,
        "wlan_ip": "",
        "wlan_cidr": "",
        "errors": [],
    }

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
            summary["errors"].append(msg)
        else:
            logger.info("[%s] %s", serial, msg)

    # 3. Ensure u2 APKs exist. Do not reinstall every bootstrap; Android package
    # install can interrupt devices and adds unnecessary startup latency.
    msg, rc = _install_u2_apks(serial)
    if rc != 0:
        logger.warning("[%s] u2 APK install failed: %s", serial, msg)
        summary["errors"].append(msg)
        return _json.dumps(summary), -1
    else:
        logger.info("[%s] %s", serial, msg)

    # 4. Install STFService before granting permissions and pushing connect URLs later.
    msg, rc = _install_stf_apk(serial)
    if rc != 0:
        logger.warning("[%s] STFService install failed: %s", serial, msg)
        summary["errors"].append(msg)
        return _json.dumps(summary), -1
    logger.info("[%s] %s", serial, msg)
    summary["stf_installed"] = True

    # 5. Apply display/battery/Doze stability settings before starting services.
    _apply_u2_stability_settings(serial)
    permission_notes = _grant_stf_permissions(serial)
    if permission_notes:
        summary["permissions_ok"] = False
        summary["errors"].extend(permission_notes)

    # 6–7. Start atx-agent + u2. When both are already healthy, skip force-stop
    # cycles (~10–15s per device) — server re-bootstrap on reconnect is common.
    if _u2_atx_healthy(serial):
        logger.info("[%s] atx-agent and u2 already running — skip restart", serial)
        summary["atx_ready"] = True
        summary["u2_ready"] = True
    else:
        msg, rc = _restart_atx(serial, timeout=min(timeout // 2, 45))
        if rc != 0:
            summary["errors"].append(f"atx-agent failed to start: {msg}")
            return _json.dumps(summary), -1
        logger.info("[%s] atx-agent ready", serial)
        summary["atx_ready"] = True

        msg, rc = _restart_u2(serial, timeout=min(timeout // 2, 90))
        if rc != 0:
            logger.warning("[%s] u2 failed to start: %s", serial, msg)
            summary["errors"].append(f"u2 failed to start: {msg}")
            return _json.dumps(summary), -1
        logger.info("[%s] u2 ready", serial)
        summary["u2_ready"] = True

    caps = _probe_capabilities(serial)
    summary["wlan_ip"] = str(caps.get("wlan_ip") or "")
    summary["wlan_cidr"] = str(caps.get("wlan_cidr") or "")

    lock_portrait_rotation(serial)
    logger.info("[%s] Bootstrap complete", serial)
    return _json.dumps(summary), 0
