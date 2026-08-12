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
import hashlib
import json as _json
import logging
import os as _os
import re
import shlex
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from relay.adb_admission import AdbLane, adb_admission, classify_adb_command
from relay.device_state import DeviceRegistry

logger = logging.getLogger("relay.adb")

# ── adb binary ────────────────────────────────────────────────────────────────

_ADB: str = shutil.which("adb") or "adb"
_SERIAL_ADB_SERVER: dict[str, tuple[str, str]] = {}


def _parse_adb_server(value: str) -> tuple[str, str] | None:
    value = value.strip()
    if value.startswith("tcp:"):
        value = value[4:]
    if ":" not in value:
        return None
    host, port = value.rsplit(":", 1)
    host = host.strip()
    port = port.strip()
    if not host or not port.isdigit():
        return None
    return host, port


def adb_server_specs_from_env() -> list[tuple[str, str]]:
    raw = (
        _os.environ.get("ADB_SERVER_SOCKETS", "").strip()
        or _os.environ.get("AGENT_BOOT_ADB_SERVER_SOCKETS", "").strip()
    )
    if raw:
        specs: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for item in re.split(r"[,;\s]+", raw):
            spec = _parse_adb_server(item)
            if spec and spec not in seen:
                specs.append(spec)
                seen.add(spec)
        if specs:
            return specs

    host = _os.environ.get("ADB_HOST", "").strip()
    port = _os.environ.get("ADB_PORT", "").strip()
    spec = _parse_adb_server(_os.environ.get("ADB_SERVER_SOCKET", "").strip())
    if spec:
        return [spec]
    if host and port:
        return [(host, port)]
    return []


def _remember_serial_adb_server(serial: str, host: str, port: str) -> None:
    serial = str(serial or "").strip()
    if not serial:
        return
    with _ADB_CACHE_LOCK:
        _SERIAL_ADB_SERVER[serial] = (host, port)


def _adb_server_flags_from_env(serial: Optional[str] = None) -> list[str]:
    """Return explicit adb server flags for Docker/remote-ADB mode.

    Some adb client builds do not reliably honor ADB_SERVER_SOCKET for every
    subprocess invocation. Passing -H/-P keeps recovery commands on the same
    host ADB server that the Docker entrypoint already checked.
    """
    if serial:
        with _ADB_CACHE_LOCK:
            cached = _SERIAL_ADB_SERVER.get(serial)
        if cached:
            return ["-H", cached[0], "-P", cached[1]]

    specs = adb_server_specs_from_env()
    if specs:
        host, port = specs[0]
        return ["-H", host, "-P", port]
    return []


def _adb_command(*args: str, serial: Optional[str] = None) -> list[str]:
    cmd = [_ADB, *_adb_server_flags_from_env(serial)]
    if serial:
        cmd += ["-s", serial]
    cmd += list(args)
    return cmd


def _run_raw(args: list[str], *, timeout: int = 5) -> tuple[str, int]:
    env = _os.environ.copy()
    env.pop("MallocStackLogging", None)
    env.pop("MallocStackLoggingDirectory", None)
    try:
        result = subprocess.run(
            [_ADB, *args],
            capture_output=True,
            check=False,
            timeout=timeout,
            env=env,
        )
        out = (result.stdout + result.stderr).decode("utf-8", errors="replace")
        return out, result.returncode
    except Exception as exc:
        return str(exc), -1


def _parse_adb_devices_output(out: str) -> list[str]:
    serials: list[str] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 2 and parts[1].strip() == "device":
            serials.append(parts[0].strip())
    return serials

# ── Asset resolution ──────────────────────────────────────────────────────────
# agent-boot/relay/adb.py lives here; assets are looked up in this order:
#   1. AGENT_BOOT_ASSETS env var (explicit override)
#   2. <agent-boot>/assets/          (production: binaries bundled with agent-boot)
#   3. <repo-root>/device_farm/bundle/ (dev: both repos side by side)

_HERE = Path(__file__).parent

def gts_dir() -> Path:
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


def _assets_dir() -> Path:
    return gts_dir()


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
_U2_ADB_KEYBOARD_IME = f"{_U2_PKG}/.AdbKeyboard"
_U2_RUNNER   = "androidx.test.runner.AndroidJUnitRunner"
_U2_STUB_CLASS = "com.github.uiautomator.stub.Stub"


def _env_int(name: str, default: int) -> int:
    raw = _os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


_CAPABILITY_CACHE_TTL_SECONDS = max(
    0,
    min(3600, _env_int("AGENT_BOOT_CAPABILITY_CACHE_TTL_SECONDS", 300)),
)
_PACKAGE_STATE_CACHE_TTL_SECONDS = max(
    0,
    min(3600, _env_int("AGENT_BOOT_PACKAGE_CACHE_TTL_SECONDS", 900)),
)
_LAN_IP_CACHE_TTL_SECONDS = max(
    0,
    min(600, _env_int("AGENT_BOOT_LAN_IP_CACHE_TTL_SECONDS", 60)),
)


@dataclass(frozen=True)
class _PackageState:
    installed: bool
    apk_path: str = ""
    sha256: str = ""


_ADB_CACHE_LOCK = threading.RLock()
_CAPABILITY_CACHE: dict[str, tuple[float, dict]] = {}
_PACKAGE_STATE_CACHE: dict[tuple[str, str], tuple[float, _PackageState]] = {}
_LAN_IP_CACHE: dict[str, tuple[float, str]] = {}
_LOCAL_SHA256_CACHE: dict[tuple[str, int, int], str] = {}
_ATX_FORWARD_CACHE: dict[str, tuple[str, int]] = {}
_ATX_FORWARD_FAIL_COUNT: dict[str, int] = {}
_ATX_FORWARD_LAST_ERROR: dict[str, str] = {}
_ATX_FORWARD_CREATE_RETRY_AFTER: dict[str, float] = {}
_ATX_FORWARD_SERIAL_LOCKS: dict[str, threading.Lock] = {}
_U2_RESTART_HEALTHY_UNTIL: dict[str, float] = {}
_ADB_COMMAND_STATS: dict[str, int] = {}
_ATX_FORWARD_RECONCILE_NEXT_AT = 0.0
_ATX_FORWARD_FAILURES_BEFORE_RECREATE = max(
    1,
    min(10, _env_int("AGENT_BOOT_ATX_FORWARD_FAILURES_BEFORE_RECREATE", 2)),
)
_ATX_FORWARD_RECONCILE_INTERVAL_SECONDS = max(
    0,
    min(600, _env_int("AGENT_BOOT_ATX_FORWARD_RECONCILE_INTERVAL_SECONDS", 30)),
)
_ATX_FORWARD_CREATE_FAILURE_COOLDOWN_SECONDS = max(
    0,
    min(60, _env_int("AGENT_BOOT_ATX_FORWARD_CREATE_FAILURE_COOLDOWN_SECONDS", 2)),
)
_U2_RESTART_HEALTHY_CACHE_SECONDS = max(
    0,
    min(60, _env_int("AGENT_BOOT_U2_RESTART_HEALTHY_CACHE_SECONDS", 15)),
)


def _atx_forward_serial_lock(serial: str) -> threading.Lock:
    with _ADB_CACHE_LOCK:
        lock = _ATX_FORWARD_SERIAL_LOCKS.get(serial)
        if lock is None:
            lock = threading.Lock()
            _ATX_FORWARD_SERIAL_LOCKS[serial] = lock
        return lock


def _adb_command_stat_key(args: tuple[str, ...]) -> str:
    command = str(args[0]).strip().lower() if args else "unknown"
    if command == "shell":
        return "shell"
    if command == "exec-out":
        return "exec_out"
    if command in {"push", "install", "install-multiple", "uninstall"}:
        return command.replace("-", "_")
    if command in {"forward", "reverse"}:
        subcommand = str(args[1]).strip().lower() if len(args) > 1 else ""
        if subcommand == "--list":
            return f"{command}_list"
        if subcommand == "--remove":
            return f"{command}_remove"
        return command
    if command in {"devices", "connect", "disconnect"}:
        return command
    return "other"


def _record_adb_command_stat(
    args: tuple[str, ...],
    *,
    lane: AdbLane,
    rc: int | None,
    timed_out: bool = False,
) -> None:
    key = _adb_command_stat_key(args)
    lane_name = AdbLane(lane).name.lower()
    with _ADB_CACHE_LOCK:
        _ADB_COMMAND_STATS[f"cmd_{key}"] = _ADB_COMMAND_STATS.get(f"cmd_{key}", 0) + 1
        _ADB_COMMAND_STATS[f"lane_{lane_name}"] = (
            _ADB_COMMAND_STATS.get(f"lane_{lane_name}", 0) + 1
        )
        if timed_out:
            _ADB_COMMAND_STATS["timeout"] = _ADB_COMMAND_STATS.get("timeout", 0) + 1
        elif rc not in (0, None):
            _ADB_COMMAND_STATS["failed"] = _ADB_COMMAND_STATS.get("failed", 0) + 1


def adb_command_stats(*, reset: bool = False) -> dict[str, int]:
    with _ADB_CACHE_LOCK:
        stats = dict(_ADB_COMMAND_STATS)
        if reset:
            _ADB_COMMAND_STATS.clear()
        return stats


def invalidate_adb_device_cache(
    serial: str,
    *,
    packages: Optional[list[str]] = None,
    capabilities: bool = True,
    lan_ip: bool = True,
) -> None:
    """Invalidate process-local ADB probe caches for one phone."""
    serial = str(serial or "").strip()
    if not serial:
        return
    with _ADB_CACHE_LOCK:
        if capabilities:
            _CAPABILITY_CACHE.pop(serial, None)
        if lan_ip:
            _LAN_IP_CACHE.pop(serial, None)
        endpoint = _ATX_FORWARD_CACHE.pop(serial, None)
        _ATX_FORWARD_FAIL_COUNT.pop(serial, None)
        _ATX_FORWARD_LAST_ERROR.pop(serial, None)
        _ATX_FORWARD_CREATE_RETRY_AFTER.pop(serial, None)
        if packages is None:
            stale = [key for key in _PACKAGE_STATE_CACHE if key[0] == serial]
        else:
            stale = [(serial, package) for package in packages]
        for key in stale:
            _PACKAGE_STATE_CACHE.pop(key, None)
    if endpoint is not None:
        _run("forward", "--remove", f"tcp:{endpoint[1]}", serial=serial, timeout=5)

def _run(
    *args: str,
    serial: Optional[str] = None,
    timeout: int = 30,
    lane: AdbLane | None = None,
) -> tuple[str, int]:
    """
    Run `adb [-s serial] <args>` and return (stdout+stderr, returncode).
    Never raises — all exceptions become ("error", -1) pairs.
    """
    cmd = _adb_command(*args, serial=serial)
    classified_lane = lane if lane is not None else classify_adb_command(tuple(args))
    # Suppress macOS MallocStackLogging spam in subprocess output
    env = _os.environ.copy()
    env.pop("MallocStackLogging", None)
    env.pop("MallocStackLoggingDirectory", None)
    try:
        with adb_admission(
            serial=serial,
            lane=classified_lane,
        ):
            result = subprocess.run(
                cmd,
                capture_output=True,
                check=False,
                timeout=timeout,
                env=env,
            )
        out = (result.stdout + result.stderr).decode("utf-8", errors="replace")
        _record_adb_command_stat(tuple(args), lane=classified_lane, rc=result.returncode)
        return out, result.returncode
    except subprocess.TimeoutExpired:
        _record_adb_command_stat(
            tuple(args),
            lane=classified_lane,
            rc=None,
            timed_out=True,
        )
        return f"adb timeout after {timeout}s", -1
    except FileNotFoundError:
        _record_adb_command_stat(tuple(args), lane=classified_lane, rc=-1)
        return f"adb binary not found at {_ADB!r}", -1
    except Exception as exc:
        _record_adb_command_stat(tuple(args), lane=classified_lane, rc=-1)
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
    specs = adb_server_specs_from_env()
    if not specs:
        out, _ = _run("devices", timeout=5)
        return dedupe_adb_serials_prefer_usb(_parse_adb_devices_output(out))

    serials: list[str] = []
    for host, port in specs:
        out, rc = _run_raw(["-H", host, "-P", port, "devices"], timeout=5)
        if rc != 0:
            logger.debug("adb devices failed host=%s port=%s output=%s", host, port, out)
            continue
        for serial in _parse_adb_devices_output(out):
            _remember_serial_adb_server(serial, host, port)
            serials.append(serial)
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
    now = time.monotonic()
    if _LAN_IP_CACHE_TTL_SECONDS > 0:
        with _ADB_CACHE_LOCK:
            cached = _LAN_IP_CACHE.get(serial)
            if cached and now - cached[0] < _LAN_IP_CACHE_TTL_SECONDS:
                return cached[1] or None
    for prop in ("dhcp.wlan0.ipaddress", "dhcp.wlan1.ipaddress"):
        out, _ = _adb_shell(serial, f"getprop {prop}", timeout=4)
        ip = out.strip()
        if _looks_like_ipv4(ip):
            with _ADB_CACHE_LOCK:
                _LAN_IP_CACHE[serial] = (time.monotonic(), ip)
            return ip
    out, _ = _adb_shell(
        serial,
        "ip -f inet route get 8.8.8.8 2>/dev/null || ip route get 8.8.8.8 2>/dev/null",
        timeout=6,
    )
    m = re.search(r"\bsrc\s+(\d{1,3}(?:\.\d{1,3}){3})\b", out)
    if m and _looks_like_ipv4(m.group(1)):
        with _ADB_CACHE_LOCK:
            _LAN_IP_CACHE[serial] = (time.monotonic(), m.group(1))
        return m.group(1)
    with _ADB_CACHE_LOCK:
        _LAN_IP_CACHE[serial] = (time.monotonic(), "")
    return None


def _adb_shell(
    serial: str,
    cmd: str,
    timeout: int = 30,
    *,
    lane: AdbLane | None = None,
) -> tuple[str, int]:
    """Run shell command on device. Returns (output, exit_code)."""
    # Background commands (ending with '&') must NOT have '; echo __EXIT__$?'
    # appended — Android's /system/bin/sh rejects '&; echo...' as a syntax error.
    if cmd.rstrip().endswith("&"):
        out, _ = _run("shell", cmd, serial=serial, timeout=timeout, lane=lane)
        return out.rstrip("\n"), 0
    out, rc = _run(
        "shell",
        f"{cmd}; echo __EXIT__$?",
        serial=serial,
        timeout=timeout,
        lane=lane,
    )
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
        f"cat /proc/net/tcp6 /proc/net/tcp 2>/dev/null | awk '$2 ~ /:{hex_port}$/ && $4 == \"0A\" {{print; exit}}'",
        timeout=timeout,
    )
    return bool(out.strip())


def _atx_forward_host() -> str:
    override = _os.environ.get("ATX_FORWARD_HOST", "").strip()
    if override:
        return override
    sock = _os.environ.get("ADB_SERVER_SOCKET", "").strip()
    if sock.startswith("tcp:"):
        rest = sock[4:]
        if ":" in rest:
            host = rest.rsplit(":", 1)[0].strip()
            if host:
                return host
    adb_host = _os.environ.get("ADB_HOST", "").strip()
    if adb_host and adb_host not in ("127.0.0.1", "localhost"):
        return adb_host
    return "127.0.0.1"


def _parse_adb_forward_port(output: str) -> int:
    for token in (output or "").replace("\r", " ").split():
        if token.isdigit():
            return int(token)
    return 0


def _parse_atx_forward_list(output: str) -> dict[str, tuple[str, int]]:
    forwards: dict[str, tuple[str, int]] = {}
    for raw_line in (output or "").splitlines():
        parts = raw_line.split()
        if len(parts) < 3:
            continue
        serial, local, remote = parts[0], parts[1], parts[2]
        if not local.startswith("tcp:") or remote != "tcp:7912":
            continue
        port_raw = local.removeprefix("tcp:")
        if not port_raw.isdigit():
            continue
        forwards[serial] = (_atx_forward_host(), int(port_raw))
    return forwards


def reconcile_atx_forward_cache(serials: Optional[set[str]] = None) -> dict[str, tuple[str, int]]:
    """Refresh the process cache from `adb forward --list`.

    This does not remove unknown host forwards. Its job is to reuse existing
    tcp:7912 forwards and avoid allocating duplicates after transient cache
    loss or hot reloads.
    """
    out, rc = _run("forward", "--list", timeout=5)
    if rc != 0:
        logger.debug("adb forward --list failed during atx reconcile: %s", out[:200])
        return {}
    discovered = _parse_atx_forward_list(out)
    wanted = {s for s in (serials or set()) if s}
    with _ADB_CACHE_LOCK:
        if wanted:
            for serial in wanted:
                if serial in discovered:
                    _ATX_FORWARD_CACHE[serial] = discovered[serial]
                else:
                    _ATX_FORWARD_CACHE.pop(serial, None)
                    _ATX_FORWARD_FAIL_COUNT.pop(serial, None)
                    _ATX_FORWARD_LAST_ERROR.pop(serial, None)
                    _ATX_FORWARD_CREATE_RETRY_AFTER.pop(serial, None)
        else:
            _ATX_FORWARD_CACHE.clear()
            _ATX_FORWARD_CACHE.update(discovered)
            stale = [serial for serial in _ATX_FORWARD_FAIL_COUNT if serial not in discovered]
            for serial in stale:
                _ATX_FORWARD_FAIL_COUNT.pop(serial, None)
                _ATX_FORWARD_LAST_ERROR.pop(serial, None)
                _ATX_FORWARD_CREATE_RETRY_AFTER.pop(serial, None)
        return dict(_ATX_FORWARD_CACHE)


def _maybe_reconcile_atx_forward_cache(serial: str) -> None:
    global _ATX_FORWARD_RECONCILE_NEXT_AT
    if _ATX_FORWARD_RECONCILE_INTERVAL_SECONDS <= 0:
        return
    now = time.monotonic()
    with _ADB_CACHE_LOCK:
        if now < _ATX_FORWARD_RECONCILE_NEXT_AT:
            return
        _ATX_FORWARD_RECONCILE_NEXT_AT = now + _ATX_FORWARD_RECONCILE_INTERVAL_SECONDS
    reconcile_atx_forward_cache({serial})


def _clear_atx_forward(serial: str) -> None:
    if not serial:
        return
    with _ADB_CACHE_LOCK:
        endpoint = _ATX_FORWARD_CACHE.pop(serial, None)
        _ATX_FORWARD_FAIL_COUNT.pop(serial, None)
        _ATX_FORWARD_LAST_ERROR.pop(serial, None)
        _ATX_FORWARD_CREATE_RETRY_AFTER.pop(serial, None)
    if endpoint is not None:
        _run("forward", "--remove", f"tcp:{endpoint[1]}", serial=serial, timeout=5)


def _atx_forward_create_retry_error(serial: str) -> str | None:
    now = time.monotonic()
    with _ADB_CACHE_LOCK:
        retry_after = _ATX_FORWARD_CREATE_RETRY_AFTER.get(serial)
        if retry_after is None:
            return None
        if now >= retry_after:
            _ATX_FORWARD_CREATE_RETRY_AFTER.pop(serial, None)
            return None
        return _ATX_FORWARD_LAST_ERROR.get(serial, "adb forward creation cooling down")


def _record_atx_forward_create_failure(serial: str, error: str) -> None:
    with _ADB_CACHE_LOCK:
        _ATX_FORWARD_LAST_ERROR[serial] = error
        if _ATX_FORWARD_CREATE_FAILURE_COOLDOWN_SECONDS > 0:
            _ATX_FORWARD_CREATE_RETRY_AFTER[serial] = (
                time.monotonic() + _ATX_FORWARD_CREATE_FAILURE_COOLDOWN_SECONDS
            )
        else:
            _ATX_FORWARD_CREATE_RETRY_AFTER.pop(serial, None)


def _ensure_atx_forward_endpoint(serial: str) -> tuple[str, int] | None:
    if not serial or ":" in serial:
        return None
    with _ADB_CACHE_LOCK:
        cached = _ATX_FORWARD_CACHE.get(serial)
        if cached is not None:
            return cached
    if _atx_forward_create_retry_error(serial) is not None:
        return None
    _maybe_reconcile_atx_forward_cache(serial)
    serial_lock = _atx_forward_serial_lock(serial)
    with serial_lock:
        with _ADB_CACHE_LOCK:
            cached = _ATX_FORWARD_CACHE.get(serial)
            if cached is not None:
                return cached
        if _atx_forward_create_retry_error(serial) is not None:
            return None
        out, rc = _run("forward", "tcp:0", "tcp:7912", serial=serial, timeout=10)
        if rc != 0:
            _record_atx_forward_create_failure(
                serial,
                f"adb forward failed: {(out or '').strip()}",
            )
            return None
        port = _parse_adb_forward_port(out)
        if port <= 0:
            _record_atx_forward_create_failure(
                serial,
                f"adb forward returned no port: {(out or '').strip()}",
            )
            return None
        endpoint = (_atx_forward_host(), port)
        with _ADB_CACHE_LOCK:
            _ATX_FORWARD_CACHE[serial] = endpoint
            _ATX_FORWARD_FAIL_COUNT.pop(serial, None)
            _ATX_FORWARD_LAST_ERROR.pop(serial, None)
            _ATX_FORWARD_CREATE_RETRY_AFTER.pop(serial, None)
        return endpoint


def _record_atx_forward_ping_success(serial: str) -> None:
    with _ADB_CACHE_LOCK:
        _ATX_FORWARD_FAIL_COUNT.pop(serial, None)


def _record_atx_forward_ping_failure(serial: str) -> int:
    with _ADB_CACHE_LOCK:
        count = _ATX_FORWARD_FAIL_COUNT.get(serial, 0) + 1
        _ATX_FORWARD_FAIL_COUNT[serial] = count
        return count


def _atx_http_ping_via_adb_forward(serial: str, timeout: float = 2.0) -> tuple[bool, str]:
    if not serial or ":" in serial:
        return False, "adb forward unavailable for tcp serial"
    endpoint = _ensure_atx_forward_endpoint(serial)
    if endpoint is None:
        with _ADB_CACHE_LOCK:
            error = _ATX_FORWARD_LAST_ERROR.get(serial, "adb forward failed")
        return False, error
    host, port = endpoint
    url = f"http://{host}:{port}/ping"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read(128).decode("utf-8", errors="replace").strip()
            if 200 <= int(resp.status) < 300:
                _record_atx_forward_ping_success(serial)
                return True, body or f"HTTP {resp.status} via adb-forward"
            return False, f"HTTP {resp.status} via adb-forward: {body}"
    except urllib.error.HTTPError as exc:
        body = exc.read(128).decode("utf-8", errors="replace") if exc.fp else ""
        return False, f"HTTP {exc.code} via adb-forward: {body.strip()}"
    except Exception as exc:
        if _record_atx_forward_ping_failure(serial) >= _ATX_FORWARD_FAILURES_BEFORE_RECREATE:
            _clear_atx_forward(serial)
        return False, f"adb-forward ping failed: {exc}"


def _atx_http_ping(serial: str, timeout: float = 2.0, host: str | None = None) -> tuple[bool, str]:
    host = host or _resolve_device_lan_ip(serial)
    if not host:
        return _atx_http_ping_via_adb_forward(serial, timeout=timeout)
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
        forward_ok, forward_msg = _atx_http_ping_via_adb_forward(serial, timeout=timeout)
        if forward_ok:
            return True, forward_msg
        return False, f"{exc}; {forward_msg}"


def _atx_jsonrpc_device_info_endpoint(host: str, port: int, timeout: float = 2.0) -> tuple[bool, str]:
    payload = _json.dumps({
        "jsonrpc": "2.0",
        "id":      1,
        "method":  "deviceInfo",
        "params":  {},
    }).encode("utf-8")
    request = urllib.request.Request(
        f"http://{host}:{port}/jsonrpc/0",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            body = resp.read(4096).decode("utf-8", errors="replace")
            if not (200 <= int(resp.status) < 300):
                return False, f"HTTP {resp.status}: {body[:200]}"
        try:
            parsed = _json.loads(body)
        except Exception as exc:
            return False, f"invalid JSON-RPC response: {exc}: {body[:200]}"
        if isinstance(parsed, dict) and parsed.get("error"):
            return False, f"JSON-RPC error: {str(parsed.get('error'))[:200]}"
        result = parsed.get("result") if isinstance(parsed, dict) else None
        if isinstance(result, dict) and "currentPackageName" in result:
            return True, "deviceInfo OK"
        return False, f"deviceInfo unexpected: {str(result)[:200]}"
    except urllib.error.HTTPError as exc:
        body = exc.read(256).decode("utf-8", errors="replace") if exc.fp else ""
        return False, f"HTTP {exc.code}: {body.strip()[:200]}"
    except Exception as exc:
        return False, str(exc)


def _atx_jsonrpc_device_info_via_adb_forward(serial: str, timeout: float = 2.0) -> tuple[bool, str]:
    if not serial or ":" in serial:
        return False, "adb forward unavailable for tcp serial"
    endpoint = _ensure_atx_forward_endpoint(serial)
    if endpoint is None:
        with _ADB_CACHE_LOCK:
            error = _ATX_FORWARD_LAST_ERROR.get(serial, "adb forward failed")
        return False, error
    host, port = endpoint
    ok, msg = _atx_jsonrpc_device_info_endpoint(host, port, timeout=timeout)
    if ok:
        _record_atx_forward_ping_success(serial)
        return True, f"{msg} via adb-forward"
    if _record_atx_forward_ping_failure(serial) >= _ATX_FORWARD_FAILURES_BEFORE_RECREATE:
        _clear_atx_forward(serial)
    return False, f"adb-forward JSON-RPC failed: {msg}"


def _atx_jsonrpc_device_info(serial: str, timeout: float = 2.0, host: str | None = None) -> tuple[bool, str]:
    host = host or _resolve_device_lan_ip(serial)
    if host:
        ok, msg = _atx_jsonrpc_device_info_endpoint(host, 7912, timeout=timeout)
        if ok:
            return True, msg
        forward_ok, forward_msg = _atx_jsonrpc_device_info_via_adb_forward(serial, timeout=timeout)
        if forward_ok:
            return True, forward_msg
        return False, f"{msg}; {forward_msg}"
    return _atx_jsonrpc_device_info_via_adb_forward(serial, timeout=timeout)


def _wait_for_atx_jsonrpc_device_info(
    serial: str,
    *,
    timeout: float,
    interval: float = 0.75,
    host: str | None = None,
) -> tuple[bool, str]:
    deadline = time.monotonic() + max(0.0, timeout)
    last_msg = ""
    while time.monotonic() < deadline:
        ok, last_msg = _atx_jsonrpc_device_info(serial, timeout=2.0, host=host)
        if ok:
            return True, last_msg
        time.sleep(interval)
    ok, last_msg = _atx_jsonrpc_device_info(serial, timeout=2.0, host=host)
    return ok, last_msg


def _run_u2_recovery_cleanup(serial: str, *, stop_atx: bool) -> None:
    commands: list[str] = []
    if stop_atx:
        commands.append("/data/local/tmp/atx-agent server --stop 2>/dev/null || true")
    commands.extend(
        [
            f"am force-stop {_U2_TEST_PKG}",
            f"am force-stop {_U2_PKG}",
            "pkill -9 -f '[u]iautomator' 2>/dev/null || true",
        ]
    )
    if stop_atx:
        commands.append("pkill -9 -f 'atx-agent' 2>/dev/null || true")
    script = "\n".join(f"({cmd}) >/dev/null 2>&1 || true" for cmd in commands)
    _adb_shell(serial, script, timeout=12)


def _u2_restart_recently_proved_healthy(serial: str) -> bool:
    if not serial or _U2_RESTART_HEALTHY_CACHE_SECONDS <= 0:
        return False
    now = time.monotonic()
    with _ADB_CACHE_LOCK:
        healthy_until = _U2_RESTART_HEALTHY_UNTIL.get(serial, 0.0)
        if now < healthy_until:
            return True
        _U2_RESTART_HEALTHY_UNTIL.pop(serial, None)
    return False


def _mark_u2_restart_healthy(serial: str) -> None:
    if not serial or _U2_RESTART_HEALTHY_CACHE_SECONDS <= 0:
        return
    with _ADB_CACHE_LOCK:
        _U2_RESTART_HEALTHY_UNTIL[serial] = (
            time.monotonic() + _U2_RESTART_HEALTHY_CACHE_SECONDS
        )


def _restart_u2(serial: str, timeout: int = 60) -> tuple[str, int]:
    if _u2_restart_recently_proved_healthy(serial):
        return "u2 recently healthy; skipped duplicate restart", 0

    _apply_u2_stability_settings(serial)

    if _u2_atx_healthy(serial):
        lock_portrait_rotation(serial)
        _mark_u2_restart_healthy(serial)
        return "u2 already healthy; skipped restart", 0

    atx_host = _resolve_device_lan_ip(serial)
    _run_u2_recovery_cleanup(serial, stop_atx=False)

    atx_ok, _ = _atx_http_ping(serial, timeout=1.5, host=atx_host)
    if atx_ok:
        rpc_ok, _ = _wait_for_atx_jsonrpc_device_info(
            serial,
            timeout=min(8.0, timeout),
            host=atx_host,
        )
    else:
        rpc_ok = False

    if rpc_ok:
        lock_portrait_rotation(serial)
        _mark_u2_restart_healthy(serial)
        return "u2 started via atx-agent", 0

    _adb_shell(
        serial,
        f"nohup am instrument -w -e debug false -e class {_U2_STUB_CLASS} {_U2_TEST_PKG}/{_U2_RUNNER}"
        f" </dev/null >/data/local/tmp/u2.log 2>&1 &",
        timeout=10,
    )

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(1.0)
        rpc_ok, _ = _atx_jsonrpc_device_info(serial, timeout=2.0, host=atx_host)
        if rpc_ok:
            lock_portrait_rotation(serial)
            _mark_u2_restart_healthy(serial)
            return "u2 started", 0
    log_tail, _ = _adb_shell(serial, "tail -n 40 /data/local/tmp/u2.log 2>/dev/null || true", timeout=5)
    return f"u2 did not start within timeout; log_tail={log_tail[-1000:]}", -1


def _restart_atx(serial: str, timeout: int = 30) -> tuple[str, int]:
    """Kill atx-agent (+ any zombie u2 instrumentation) and restart it.

    atx-agent manages u2 lifecycle on-device — restarting it is faster and
    cleaner than restarting u2 instrumentation directly when atx is frozen/dead.
    """
    _apply_u2_stability_settings(serial)

    atx_host = _resolve_device_lan_ip(serial)
    rpc_ok, rpc_msg = _atx_jsonrpc_device_info(serial, timeout=2.0, host=atx_host)
    if rpc_ok:
        lock_portrait_rotation(serial)
        _mark_u2_restart_healthy(serial)
        return "atx-agent and u2 already healthy; skipped restart", 0

    atx_ok, atx_ping = _atx_http_ping(serial, timeout=1.5, host=atx_host)
    if atx_ok:
        msg, rc = _restart_u2(serial, timeout=min(timeout, 60))
        if rc == 0:
            return f"atx-agent healthy; {msg}", 0
        logger.warning("[%s] atx-agent healthy but u2 restart failed: %s", serial, msg)
    elif atx_ping.startswith("device LAN IP unavailable"):
        logger.debug("[%s] atx-agent JSON-RPC unavailable before restart: %s", serial, rpc_msg)

    # Kill zombie u2 first — a stuck u2 process is the #1 reason atx freezes.
    _run_u2_recovery_cleanup(serial, stop_atx=True)
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
        ok, last_ping = _atx_jsonrpc_device_info(serial, host=atx_host)
        if ok:
            return "atx-agent and u2 started", 0
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
    if _lock_rotation_enabled():
        commands.extend(
            [
                "settings put system accelerometer_rotation 0",
                "settings put system user_rotation 0",
            ]
        )
    script = "\n".join(f"({cmd}) >/dev/null 2>&1 || true" for cmd in commands)
    _adb_shell(serial, script, timeout=12)
    ok, msg = ensure_u2_input_ime(serial)
    if ok:
        logger.info("[%s] u2 AdbKeyboard IME: %s", serial, msg)
    else:
        logger.warning("[%s] u2 AdbKeyboard IME not pinned: %s", serial, msg)


def _list_input_methods(serial: str) -> list[str]:
    out, _ = _adb_shell(serial, "ime list -s -a", timeout=10)
    return [line.strip() for line in out.splitlines() if line.strip()]


def ensure_u2_input_ime(serial: str) -> tuple[bool, str]:
    """
    Pin openatx AdbKeyboard as the default IME for u2 text input.

    Matches uiautomator2 ``set_input_ime()`` / ``ADB_KEYBOARD_INPUT_TEXT`` so
    live typing and scenarios do not fall back to setText or clipboard paste.
    Idempotent — safe on every bootstrap.
    """
    pkg = shlex.quote(_U2_PKG)
    ime = shlex.quote(_U2_ADB_KEYBOARD_IME)
    script = f"""
emit() {{ printf '__DF__%s=%s\\n' "$1" "$2"; }}
pkg_ok=0
if pm path {pkg} >/dev/null 2>&1; then pkg_ok=1; fi
emit pkg "$pkg_ok"
ime_found=0
if ime list -s -a 2>/dev/null | grep -Fqx {ime}; then ime_found=1; fi
emit ime "$ime_found"
current="$(settings get secure default_input_method 2>/dev/null)"
emit current "$current"
if [ "$pkg_ok" = "1" ] && [ "$ime_found" = "1" ] && [ "$current" != {ime} ]; then
  ime enable {ime} >/dev/null 2>&1 || true
  ime set {ime} >/dev/null 2>&1 || true
  settings put secure default_input_method {ime} >/dev/null 2>&1 || true
  current="$(settings get secure default_input_method 2>/dev/null)"
fi
emit final "$current"
"""
    out, _ = _adb_shell(serial, script, timeout=10)
    values = _parse_probe_kv(out)
    if values.get("pkg") != "1":
        return False, "u2 package not installed"
    if values.get("ime") != "1":
        return False, f"{_U2_ADB_KEYBOARD_IME} not registered (reinstall u2 APK?)"
    current = (values.get("current") or "").strip()
    if current == _U2_ADB_KEYBOARD_IME:
        return True, "already default"
    final = (values.get("final") or "").strip()
    if final == _U2_ADB_KEYBOARD_IME:
        return True, "enabled"
    return False, f"default still {final!r}"


def _run_bytes(
    *args: str,
    serial: Optional[str] = None,
    timeout: int = 30,
) -> tuple[bytes, int]:
    """Like _run() but returns raw stdout bytes (for binary data like screencap)."""
    cmd = _adb_command(*args, serial=serial)
    env = _os.environ.copy()
    env.pop("MallocStackLogging", None)
    env.pop("MallocStackLoggingDirectory", None)
    try:
        with adb_admission(
            serial=serial,
            lane=classify_adb_command(tuple(args)),
        ):
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=timeout,
                env=env,
            )
        return result.stdout, result.returncode
    except subprocess.TimeoutExpired:
        return b"", -1
    except Exception:
        return b"", -1


def _first_nonempty(*values: str) -> str:
    for value in values:
        value = (value or "").strip()
        if value and value.lower() not in {"null", "unknown", "<unknown>"}:
            return value
    return ""


def _parse_probe_kv(output: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in output.splitlines():
        if not line.startswith("__DF__") or "=" not in line:
            continue
        key, value = line[len("__DF__"):].split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _probe_capabilities_uncached(serial: str) -> dict:
    script = r"""
emit() { printf '__DF__%s=%s\n' "$1" "$2"; }
gp() { getprop "$1" 2>/dev/null; }
emit sdk "$(gp ro.build.version.sdk)"
emit android_version "$(gp ro.build.version.release)"
emit abi "$(gp ro.product.cpu.abi)"
emit brand "$(gp ro.product.brand)"
emit model "$(gp ro.product.model)"
emit marketname "$(gp ro.product.marketname)"
emit marketing_name "$(gp ro.config.marketing_name)"
emit vendor_marketname "$(gp ro.product.vendor.marketname)"
emit global_device_name "$(settings get global device_name 2>/dev/null)"
emit bluetooth_name "$(settings get secure bluetooth_name 2>/dev/null)"
emit persist_device_name "$(gp persist.sys.device_name)"
emit hardware_serial "$(gp ro.boot.serialno)"
emit ro_serialno "$(gp ro.serialno)"
emit build_fingerprint "$(gp ro.build.fingerprint)"
emit boot_id "$(cat /proc/sys/kernel/random/boot_id 2>/dev/null)"
wm_size="$(wm size 2>/dev/null | sed -n 's/.*Physical size: //p' | head -n1)"
emit wm_size "$wm_size"
mem_kb="$(awk '/MemTotal/ {print $2; exit}' /proc/meminfo 2>/dev/null)"
emit mem_kb "$mem_kb"
ip_line="$(ip -o -4 addr show wlan0 2>/dev/null | head -n1)"
if [ -z "$ip_line" ]; then ip_line="$(ip -o -4 addr show 2>/dev/null | head -n1)"; fi
emit ip_line "$ip_line"
if cat /proc/net/tcp6 /proc/net/tcp 2>/dev/null | grep -iq ':1EE8'
then emit atx_agent 1
else emit atx_agent 0
fi
if pm path com.github.uiautomator >/dev/null 2>&1; then emit u2 1; else emit u2 0; fi
if pm path jp.co.cyberagent.stf >/dev/null 2>&1; then emit stf 1; else emit stf 0; fi
"""
    out, _ = _adb_shell(serial, script, timeout=10)
    values = _parse_probe_kv(out)

    screen_width = 0
    screen_height = 0
    wm_size = values.get("wm_size", "")
    if "x" in wm_size:
        try:
            w_raw, h_raw = wm_size.strip().split("x", 1)
            screen_width = int(w_raw)
            screen_height = int(h_raw)
        except Exception:
            screen_width = 0
            screen_height = 0

    ram_gb = 0
    try:
        ram_gb = round(int(values.get("mem_kb") or "0") / 1024 / 1024)
    except Exception:
        ram_gb = 0

    wifi_ip = ""
    wifi_cidr = ""
    ip_line = values.get("ip_line", "")
    for match in re.finditer(r"\binet\s+(\d+\.\d+\.\d+\.\d+)/(\d+)", ip_line):
        ip = match.group(1)
        prefix = match.group(2)
        if not ip.startswith("127."):
            wifi_ip = ip
            wifi_cidr = f"{ip}/{prefix}"
            break

    brand = (values.get("brand") or "").lower()
    model = values.get("model") or ""
    marketing_name = _first_nonempty(
        values.get("marketname", ""),
        values.get("marketing_name", ""),
        values.get("vendor_marketname", ""),
    )
    device_name = _first_nonempty(
        values.get("global_device_name", ""),
        values.get("bluetooth_name", ""),
        values.get("persist_device_name", ""),
        marketing_name,
        model,
    )
    hw_serial = _first_nonempty(
        values.get("hardware_serial", ""),
        values.get("ro_serialno", ""),
    )
    return {
        "sdk": values.get("sdk", ""),
        "android_version": values.get("android_version", ""),
        "abi": values.get("abi", ""),
        "brand": brand,
        "model": model,
        "device_name": device_name,
        "marketing_name": marketing_name,
        "display_name": _first_nonempty(
            device_name,
            marketing_name,
            " ".join(p for p in [brand, model] if p),
        ),
        "wlan_ip": wifi_ip,
        "wlan_cidr": wifi_cidr,
        "screen_width": screen_width,
        "screen_height": screen_height,
        "ram_gb": ram_gb,
        "atx_agent": values.get("atx_agent") == "1",
        "u2": values.get("u2") == "1",
        "stf": values.get("stf") == "1",
        "tags": [],  # populated by user config / env vars
        "hardware_serial": hw_serial,
        "build_fingerprint": values.get("build_fingerprint", ""),
        "boot_id": values.get("boot_id", ""),
    }


def _probe_capabilities(serial: str) -> dict:
    """
    Probe rich device capabilities once when device first comes ONLINE.
    Includes android_version, brand, ram_gb, screen dims for device pool matching.
    """
    now = time.monotonic()
    if _CAPABILITY_CACHE_TTL_SECONDS > 0:
        with _ADB_CACHE_LOCK:
            cached = _CAPABILITY_CACHE.get(serial)
            if cached and now - cached[0] < _CAPABILITY_CACHE_TTL_SECONDS:
                return dict(cached[1])

    caps = _probe_capabilities_uncached(serial)
    if _CAPABILITY_CACHE_TTL_SECONDS > 0:
        with _ADB_CACHE_LOCK:
            _CAPABILITY_CACHE[serial] = (time.monotonic(), dict(caps))
            if caps.get("wlan_ip"):
                _LAN_IP_CACHE[serial] = (
                    time.monotonic(),
                    str(caps.get("wlan_ip") or ""),
                )
    return caps


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
    force_install = _os.getenv(
        "AGENT_BOOT_FORCE_U2_INSTALL",
        "",
    ).strip().lower() in {"1", "true", "yes", "on"}
    installed_main = _pkg_installed(serial, _U2_PKG)
    installed_test = _pkg_installed(serial, _U2_TEST_PKG)

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

    main_matches = _installed_apk_matches(serial, _U2_PKG, main_apk) if installed_main else False
    test_matches = (
        _installed_apk_matches(serial, _U2_TEST_PKG, test_apk)
        if installed_test
        else False
    )
    pair_mismatch = main_matches is False or test_matches is False
    if installed_main and installed_test and not force_install and not pair_mismatch:
        if main_matches is True and test_matches is True:
            return "u2 APKs already installed; hashes match local assets", 0
        return "u2 APKs already installed; hashes unavailable", 0

    if main_apk is None:
        msg = (
            f"u2 APKs not found in {assets}. "
            f"Place app-uiautomator.apk + app-uiautomator-test.apk in agent-boot/assets/apks/."
        )
        logger.warning(msg)
        return msg, -1

    out_m = "Success"
    out_t = "Success"
    reinstall_pair = force_install or pair_mismatch
    if reinstall_pair or not installed_main:
        logger.info("[%s] installing u2 main APK from %s", serial, main_apk)
        invalidate_adb_device_cache(serial, packages=[_U2_PKG], capabilities=False, lan_ip=False)
        out, rc = _run("push", str(main_apk), "/data/local/tmp/u2-main.apk",
                       serial=serial, timeout=120)
        if rc != 0:
            return f"push u2 main APK failed: {out}", -1
        out_m, rc_m = _adb_shell(serial, "pm install -r /data/local/tmp/u2-main.apk", timeout=120)
    if reinstall_pair or not installed_test:
        logger.info("[%s] installing u2 test APK from %s", serial, test_apk)
        invalidate_adb_device_cache(
            serial,
            packages=[_U2_TEST_PKG],
            capabilities=False,
            lan_ip=False,
        )
        out, rc = _run("push", str(test_apk), "/data/local/tmp/u2-test.apk",
                       serial=serial, timeout=120)
        if rc != 0:
            return f"push u2 test APK failed: {out}", -1
        out_t, rc_t = _adb_shell(
            serial,
            "pm install -r -t /data/local/tmp/u2-test.apk",
            timeout=120,
        )

    combined = f"{out_m}\n{out_t}"
    if (
        "INSTALL_FAILED_UPDATE_INCOMPATIBLE" in combined
        or "INSTALL_FAILED_VERSION_DOWNGRADE" in combined
        or "signatures do not match" in combined
    ):
        _adb_shell(serial, f"pm uninstall {_U2_TEST_PKG} 2>/dev/null || true", timeout=30)
        _adb_shell(serial, f"pm uninstall {_U2_PKG} 2>/dev/null || true", timeout=30)
        invalidate_adb_device_cache(
            serial,
            packages=[_U2_PKG, _U2_TEST_PKG],
            capabilities=False,
            lan_ip=False,
        )
        out, rc = _run("push", str(main_apk), "/data/local/tmp/u2-main.apk",
                       serial=serial, timeout=120)
        if rc != 0:
            return f"push u2 main APK failed after uninstall: {out}", -1
        out, rc = _run("push", str(test_apk), "/data/local/tmp/u2-test.apk",
                       serial=serial, timeout=120)
        if rc != 0:
            return f"push u2 test APK failed after uninstall: {out}", -1
        out_m, rc_m = _adb_shell(serial, "pm install -r /data/local/tmp/u2-main.apk", timeout=120)
        out_t, rc_t = _adb_shell(
            serial,
            "pm install -r -t /data/local/tmp/u2-test.apk",
            timeout=120,
        )

    _adb_shell(serial, "rm -f /data/local/tmp/u2-main.apk /data/local/tmp/u2-test.apk", timeout=10)

    if "Success" not in out_m or "Success" not in out_t:
        return f"u2 install failed: main={out_m!r} test={out_t!r}", -1
    invalidate_adb_device_cache(
        serial,
        packages=[_U2_PKG, _U2_TEST_PKG],
        capabilities=True,
        lan_ip=False,
    )
    if installed_main or installed_test:
        return "u2 APKs already installed; installed missing package(s)", 0
    return "u2 APKs installed", 0


def _parse_package_state_output(output: str) -> dict[str, _PackageState]:
    states: dict[str, _PackageState] = {}
    for line in output.splitlines():
        if not line.startswith("__DFPKG__"):
            continue
        fields = line[len("__DFPKG__"):].split("\t")
        if len(fields) < 3:
            continue
        package = fields[0].strip()
        apk_path = fields[1].strip()
        sha = fields[2].strip().lower()
        states[package] = _PackageState(
            installed=bool(apk_path),
            apk_path=apk_path,
            sha256=sha if re.fullmatch(r"[0-9a-f]{64}", sha) else "",
        )
    return states


def _query_package_states(
    serial: str,
    packages: list[str],
) -> dict[str, _PackageState]:
    if not packages:
        return {}
    lines = [
        "hash_apk() { "
        "sha256sum \"$1\" 2>/dev/null "
        "|| toybox sha256sum \"$1\" 2>/dev/null "
        "|| true; }",
    ]
    for package in packages:
        quoted = shlex.quote(package)
        lines.append(
            "pkg={pkg}; "
            "apk=$(pm path \"$pkg\" 2>/dev/null | head -n1 | sed 's/^package://'); "
            "sha=\"\"; "
            "if [ -n \"$apk\" ]; then "
            "sha=$(hash_apk \"$apk\" | awk '{{print $1; exit}}'); "
            "fi; "
            "printf '__DFPKG__%s\\t%s\\t%s\\n' \"$pkg\" \"$apk\" \"$sha\"".format(
                pkg=quoted,
            )
        )
    out, _ = _adb_shell(serial, "\n".join(lines), timeout=15)
    states = _parse_package_state_output(out)
    return {
        package: states.get(package, _PackageState(installed=False))
        for package in packages
    }


def _installed_package_states(
    serial: str,
    packages: list[str],
) -> dict[str, _PackageState]:
    now = time.monotonic()
    unique_packages = list(dict.fromkeys(packages))
    if _PACKAGE_STATE_CACHE_TTL_SECONDS > 0:
        with _ADB_CACHE_LOCK:
            cached: dict[str, _PackageState] = {}
            missing: list[str] = []
            for package in unique_packages:
                item = _PACKAGE_STATE_CACHE.get((serial, package))
                if item and now - item[0] < _PACKAGE_STATE_CACHE_TTL_SECONDS:
                    cached[package] = item[1]
                else:
                    missing.append(package)
        if not missing:
            return cached
    else:
        cached = {}
        missing = unique_packages

    queried = _query_package_states(serial, missing)
    if _PACKAGE_STATE_CACHE_TTL_SECONDS > 0:
        with _ADB_CACHE_LOCK:
            timestamp = time.monotonic()
            for package, state in queried.items():
                _PACKAGE_STATE_CACHE[(serial, package)] = (timestamp, state)
    cached.update(queried)
    return cached


def _pkg_installed(serial: str, package: str) -> bool:
    return _installed_package_states(serial, [package])[package].installed


def _sha256_file(path: Path) -> str:
    stat = path.stat()
    key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns)
    with _ADB_CACHE_LOCK:
        cached = _LOCAL_SHA256_CACHE.get(key)
        if cached:
            return cached
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    value = digest.hexdigest()
    with _ADB_CACHE_LOCK:
        _LOCAL_SHA256_CACHE[key] = value
    return value


def _installed_pkg_sha256(serial: str, package: str) -> Optional[str]:
    state = _installed_package_states(serial, [package])[package]
    return state.sha256 or None


def _installed_apk_matches(serial: str, package: str, local_apk: Optional[Path]) -> Optional[bool]:
    if local_apk is None or not local_apk.is_file():
        return None
    installed_sha = _installed_pkg_sha256(serial, package)
    if not installed_sha:
        return None
    return installed_sha == _sha256_file(local_apk)


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

    logger.info("[%s] installing STFService APK from %s", serial, apk_path)
    invalidate_adb_device_cache(serial, packages=[_STF_PKG], capabilities=False, lan_ip=False)
    out, rc = _run("install", "-r", str(apk_path), serial=serial, timeout=180)
    if rc != 0 or "Success" not in out:
        return f"STFService install failed: {out}", -1
    invalidate_adb_device_cache(serial, packages=[_STF_PKG], capabilities=True, lan_ip=False)
    return "STFService installed", 0


def _grant_stf_permissions(serial: str) -> list[str]:
    notes: list[str] = []
    for perm in ("android.permission.WRITE_SECURE_SETTINGS", "android.permission.READ_PHONE_STATE"):
        out, rc = _adb_shell(serial, f"pm grant {_STF_PKG} {perm}", timeout=10)
        if rc != 0 or "Exception" in out:
            notes.append(f"pm grant {perm}: {out[:200]}")
    return notes


def _u2_atx_healthy(serial: str) -> bool:
    """True when the active atx-agent JSON-RPC route can reach u2."""
    atx_host = _resolve_device_lan_ip(serial)
    ok, msg = _atx_jsonrpc_device_info(serial, host=atx_host)
    if ok:
        return True
    atx_ok, ping_err = _atx_http_ping(serial, host=atx_host)
    if atx_ok:
        logger.warning("[%s] atx-agent reachable but u2 JSON-RPC unhealthy: %s", serial, msg)
    else:
        logger.warning("[%s] atx-agent HTTP unhealthy: %s", serial, ping_err)
    return False


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

    ime_ok, ime_msg = ensure_u2_input_ime(serial)
    summary["u2_ime_ready"] = ime_ok
    if ime_ok:
        logger.info("[%s] u2 AdbKeyboard IME: %s", serial, ime_msg)
    else:
        logger.warning("[%s] u2 AdbKeyboard IME not pinned: %s", serial, ime_msg)
        summary["errors"].append(f"u2 ime: {ime_msg}")

    caps = _probe_capabilities(serial)
    summary["wlan_ip"] = str(caps.get("wlan_ip") or "")
    summary["wlan_cidr"] = str(caps.get("wlan_cidr") or "")

    lock_portrait_rotation(serial)
    logger.info("[%s] Bootstrap complete", serial)
    return _json.dumps(summary), 0
