"""
bootstrap.py — One-time device setup.

Steps per device:
  1. adb tcpip <port>               (optional, enables WiFi ADB)
  2. Enable Wireless Debugging      (Android 11+, for mDNS auto-discovery)
  3. Install uiautomator2 APKs      (main + test)
  4. Push + start atx-agent         (manages u2 lifecycle automatically)
  5. Install STFService.apk
  6. Grant STFService permissions
  7. Open STFService → user scans QR to connect cloud
"""
from __future__ import annotations

import subprocess
import tarfile
import threading
import time
import urllib.request
import os
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.rule import Rule
from rich.table import Table

# ── Paths ─────────────────────────────────────────────────────────────────────

_ROOT        = Path(__file__).resolve().parent          # agent-boot/
_FARM_ROOT   = _ROOT.parent                             # deviceFarmer/
_DEVICE_FARM = _FARM_ROOT / "device_farm"

_U2_APK_SEARCH_DIRS = [
    _DEVICE_FARM / "third_party",
    _DEVICE_FARM / "bundle" / "apks",
    _ROOT,
]

_STF_APK_CANDIDATES = [
    _ROOT / "STFService.apk",
    _FARM_ROOT / "device_farm" / "bundle" / "apks" / "STFService.apk",
    _FARM_ROOT / "STFService.apk" / "app" / "build" / "outputs" / "apk" / "full" / "release" / "app-release.apk",
    _FARM_ROOT / "STFService.apk" / "app" / "build" / "outputs" / "apk" / "full" / "debug" / "app-debug.apk",
    _FARM_ROOT / "STFService.apk" / "app" / "build" / "outputs" / "apk" / "lite" / "debug" / "app-debug.apk",
    _FARM_ROOT / "STFService.apk" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk",
]

# Package names
_U2_PKG      = "com.github.uiautomator"
_U2_TEST_PKG = "com.github.uiautomator.test"
_STF_PKG     = "jp.co.cyberagent.stf"
_STF_A11Y_SERVICE = f"{_STF_PKG}/jp.co.cyberagent.stf.TouchAccessibilityService"

# atx-agent
_ATX_AGENT_VERSION  = "0.10.1"
_ATX_AGENT_REMOTE   = "/data/local/tmp/atx-agent"
_ATX_AGENT_PORT_HEX = "1EE8"   # 7912 decimal
_ATX_BUNDLE_DIR     = _DEVICE_FARM / "bundle" / "atx-agent"
_DEVICE_BUNDLE_TGZ  = _DEVICE_FARM / "bundle" / "device_bundle.tar.gz"

TOTAL_STEPS = 7

_print_lock = threading.Lock()
console = Console()


def _auto_open_stf_enabled() -> bool:
    """
    Whether bootstrap should auto-launch STFService UI.
    Default OFF to avoid unexpectedly hijacking the device screen.
    Enable via AUTO_OPEN_STF_APP=1.
    """
    return os.environ.get("AUTO_OPEN_STF_APP", "").strip().lower() in {"1", "true", "yes"}


# ── ADB helpers ───────────────────────────────────────────────────────────────

def _run(cmd: list[str], check: bool = True, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)
    return result


def _adb(*args: str, serial: str, check: bool = False, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return _run(["adb", "-s", serial, *args], check=check, timeout=timeout)


def _adb_shell(cmd: str, serial: str, timeout: int = 30) -> str:
    r = _adb("shell", cmd, serial=serial, check=False, timeout=timeout)
    return (r.stdout + r.stderr).strip()


def list_serials() -> list[str]:
    from relay.adb import dedupe_adb_serials_prefer_usb

    result = _run(["adb", "devices"], check=False)
    lines = result.stdout.strip().splitlines()[1:]
    devices = [
        line.split()[0]
        for line in lines
        if line.strip() and line.split()[-1] == "device"
    ]
    if not devices:
        raise SystemExit(
            "[agent] No ADB devices found.\n"
            "  → Plug USB and enable USB Debugging,\n"
            "    or connect via WiFi: adb connect <ip>:5555"
        )

    return dedupe_adb_serials_prefer_usb(devices)


def _get_sdk(serial: str) -> int:
    try:
        return int(_adb_shell("getprop ro.build.version.sdk", serial=serial).strip())
    except ValueError:
        return 0


def _is_pkg_installed(pkg: str, serial: str) -> bool:
    return "package:" in _adb_shell(f"pm path {pkg}", serial=serial)

def _is_atx_listening(serial: str) -> bool:
    out = _adb_shell(
        f"cat /proc/net/tcp6 /proc/net/tcp 2>/dev/null | grep -i ':{_ATX_AGENT_PORT_HEX}' | head -1 || true",
        serial=serial,
    ).strip()
    return bool(out)


def _adb_install(apk_path: Path, serial: str, label: str, extra_flags: list[str] | None = None) -> bool:
    flags = ["-r"] + (extra_flags or [])
    r = _adb("install", *flags, str(apk_path), serial=serial, check=False, timeout=120)
    out = (r.stdout + r.stderr).strip()
    ok = r.returncode == 0 and "Failure" not in out and "Exception" not in out
    if ok:
        console.print(f"    [green]✓[/green] {label} installed")
    else:
        console.print(f"    [red]✗[/red] {label} failed (rc={r.returncode}): {out[:800]}")
    return ok


# ── atx-agent helpers ─────────────────────────────────────────────────────────

def _get_device_abi(serial: str) -> str:
    abi = _adb_shell("getprop ro.product.cpu.abi", serial=serial)
    if "arm64" in abi:
        return "arm64"
    if "x86_64" in abi:
        return "x86_64"
    if "x86" in abi:
        return "x86"
    return "arm"


def _atx_agent_local(abi: str) -> Path:
    return _ATX_BUNDLE_DIR / f"atx-agent-{abi}"


def _download_atx_agent(abi: str) -> Path | None:
    go_arch = {"arm64": "arm64", "arm": "armv7", "x86_64": "amd64", "x86": "386"}.get(abi, "arm64")
    version  = _ATX_AGENT_VERSION
    filename = f"atx-agent_{version}_linux_{go_arch}.tar.gz"
    url      = f"https://github.com/openatx/atx-agent/releases/download/{version}/{filename}"
    dest     = _atx_agent_local(abi)

    if dest.is_file() and dest.stat().st_size > 0:
        return dest

    _ATX_BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _ATX_BUNDLE_DIR / filename

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task(f"Downloading atx-agent v{version} ({go_arch})…", total=None)
        try:
            with urllib.request.urlopen(url, timeout=120) as resp:
                with open(tmp, "wb") as f:
                    while chunk := resp.read(65536):
                        f.write(chunk)
            progress.update(task, description=f"Extracting atx-agent…")
        except Exception as e:
            console.print(f"    [red]✗[/red] Download failed: {e}")
            console.print(f"      URL: {url}")
            console.print(f"      Manual path: {dest}")
            tmp.unlink(missing_ok=True)
            return None

    try:
        with tarfile.open(tmp) as tf:
            member = next(
                (m for m in tf.getmembers() if m.name.endswith("atx-agent") and m.isfile()),
                None,
            )
            if member is None:
                raise RuntimeError("atx-agent binary not found in archive")
            member.name = "atx-agent"
            try:
                tf.extract(member, _ATX_BUNDLE_DIR, filter="data")
            except TypeError:
                tf.extract(member, _ATX_BUNDLE_DIR)
        (_ATX_BUNDLE_DIR / "atx-agent").rename(dest)
        console.print(f"    [green]✓[/green] Saved: {dest}")
    except Exception as e:
        console.print(f"    [red]✗[/red] Extract failed: {e}")
        dest.unlink(missing_ok=True)
        return None
    finally:
        tmp.unlink(missing_ok=True)

    return dest


# ── Asset finders ─────────────────────────────────────────────────────────────

def find_u2_apks() -> tuple[Path | None, Path | None]:
    main_apk = test_apk = None
    for d in _U2_APK_SEARCH_DIRS:
        if main_apk is None:
            p = d / "app-uiautomator.apk"
            if p.is_file() and p.stat().st_size > 0:
                main_apk = p
        if test_apk is None:
            p = d / "app-uiautomator-test.apk"
            if p.is_file() and p.stat().st_size > 0:
                test_apk = p
        if main_apk and test_apk:
            break
    return main_apk, test_apk


def find_stf_apk(override: str | None = None) -> Path | None:
    if override:
        p = Path(override)
        if p.is_file():
            return p
        raise SystemExit(f"[agent] --apk not found: {p}")
    return next((p for p in _STF_APK_CANDIDATES if p.is_file() and p.stat().st_size > 0), None)


# ── Bootstrap steps ───────────────────────────────────────────────────────────

def _step_header(n: int, title: str) -> None:
    console.print(Rule(f"[bold cyan]Step {n}/{TOTAL_STEPS}[/bold cyan]  {title}", style="cyan"))


def step_tcpip(serial: str, port: int) -> str:
    """Enable tcpip and return the serial to use for subsequent steps.

    If the device is already connected over WiFi (serial contains ':'), tcpip
    causes the current connection to drop.  We reconnect to <ip>:<port> so the
    rest of bootstrap can proceed without seeing 'device offline'.
    """
    _step_header(1, f"Enable adb tcpip {port}")
    try:
        _adb("tcpip", str(port), serial=serial, check=False, timeout=10)
        time.sleep(2)
        console.print(f"    [green]✓[/green] adb tcpip {port} OK")
    except Exception as e:
        console.print(f"    [yellow]⚠[/yellow] adb tcpip failed ({e}) — skipping.")
        return serial

    # If already a WiFi serial (ip:port), reconnect on the new port.
    if ":" in serial:
        ip = serial.split(":")[0]
        new_serial = f"{ip}:{port}"
        if new_serial != serial:
            r = _run(["adb", "connect", new_serial], check=False, timeout=15)
            out = (r.stdout + r.stderr).strip()
            if "connected" in out.lower():
                console.print(f"    [green]✓[/green] Reconnected as {new_serial}")
                time.sleep(1)
                return new_serial
            else:
                console.print(f"    [yellow]⚠[/yellow] adb connect {new_serial}: {out[:200]}")

    return serial


def step_wireless_debugging(serial: str, skip: bool) -> None:
    """
    Enable Android 11+ Wireless Debugging via ADB.
    This allows zeroconf mDNS auto-discovery without manual IP entry.
    No-op on Android < 11 (SDK < 30).
    """
    if skip:
        _step_header(2, "Wireless Debugging")
        console.print("    [dim]Skipped (--skip-tcpip)[/dim]")
        return

    sdk = _get_sdk(serial)
    if sdk < 30:
        _step_header(2, "Wireless Debugging")
        console.print(f"    [dim]Skipped — Android SDK {sdk} < 30[/dim]")
        return

    _step_header(2, f"Enable Wireless Debugging (Android 11+, SDK {sdk})")
    try:
        out = _adb_shell("settings put global adb_wifi_enabled 1", serial=serial)
        if out and "exception" in out.lower():
            raise RuntimeError(out)
        console.print("    [green]✓[/green] Wireless Debugging enabled — zeroconf mDNS will auto-discover this device")
    except Exception as e:
        console.print(f"    [yellow]⚠[/yellow] Could not enable Wireless Debugging ({e})")
        console.print("      Enable manually: Settings → Developer Options → Wireless Debugging → ON")


def step_install_u2(serial: str, skip: bool) -> bool:
    _step_header(3, "Install uiautomator2 APKs")
    if skip:
        console.print("    [dim]Skipped (--skip-u2)[/dim]")
        return False

    main_ok = _is_pkg_installed(_U2_PKG, serial)
    test_ok = _is_pkg_installed(_U2_TEST_PKG, serial)
    if main_ok and test_ok:
        console.print("    [green]✓[/green] Already installed — skipping.")
        return True

    main_apk, test_apk = find_u2_apks()
    if main_apk is None or test_apk is None:
        missing = [n for n, p in [("app-uiautomator.apk", main_apk), ("app-uiautomator-test.apk", test_apk)] if p is None]
        console.print(f"    [red]✗[/red] APKs not found: {', '.join(missing)}")
        console.print(f"      Search dirs: {[str(d) for d in _U2_APK_SEARCH_DIRS]}")
        console.print("      Run: python ../device_farm/download_bundle.py --no-minitouch --no-stf --no-scrcpy")
        return False

    ok = True
    if not main_ok:
        ok &= _adb_install(main_apk, serial, _U2_PKG)
    if not test_ok:
        ok &= _adb_install(test_apk, serial, _U2_TEST_PKG, extra_flags=["-t"])
    return ok


def step_push_atx_agent(serial: str, skip: bool) -> bool:
    _step_header(4, "Push + start atx-agent (port 7912)")
    if skip:
        console.print("    [dim]Skipped (--skip-atx or --skip-u2)[/dim]")
        return False

    if not _is_pkg_installed(_U2_TEST_PKG, serial):
        console.print(f"    [red]✗[/red] {_U2_TEST_PKG} not installed — atx-agent needs it.")
        return False

    # Do not skip just because port is open: stale/duplicated atx-agent processes
    # are common and can make control path flaky. Always refresh the daemon.
    if _is_atx_listening(serial):
        console.print("    [cyan]→[/cyan] atx-agent detected on :7912 — refreshing process")

    abi    = _get_device_abi(serial)
    binary = _atx_agent_local(abi)
    if not (binary.is_file() and binary.stat().st_size > 0):
        binary = _download_atx_agent(abi)
    if binary is None:
        return False

    r = _adb("push", str(binary), _ATX_AGENT_REMOTE, serial=serial, check=False, timeout=30)
    if r.returncode != 0:
        console.print(f"    [red]✗[/red] adb push failed: {(r.stdout + r.stderr).strip()[:200]}")
        return False
    _adb_shell(f"chmod 755 {_ATX_AGENT_REMOTE}", serial=serial)
    console.print(f"    [green]✓[/green] Pushed {binary.name} → {_ATX_AGENT_REMOTE}")

    _adb_shell(
        f"pkill -f atx-agent 2>/dev/null || true; {_ATX_AGENT_REMOTE} server --stop 2>/dev/null; sleep 0.3",
        serial=serial,
    )
    _adb_shell(f"{_ATX_AGENT_REMOTE} server -d 2>/dev/null", serial=serial)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Waiting for atx-agent on :7912…", total=None)
        for _ in range(15):
            time.sleep(1)
            if _is_atx_listening(serial):
                console.print("    [green]✓[/green] atx-agent running on :7912")
                return True
        _ = task  # silence unused warning

    console.print(f"    [yellow]⚠[/yellow] atx-agent not ready after 15s.")
    console.print(f"      Check: adb -s {serial} shell {_ATX_AGENT_REMOTE} server")
    return False


def step_deploy_bundle_if_needed(serial: str, *, force: bool = False) -> bool:
    """
    Optional: deploy device_bundle.tar.gz and run launch.sh on device.
    Used when a fresh phone doesn't have u2/atx-agent ready yet.
    """
    if not force:
        u2_ok = _is_pkg_installed(_U2_PKG, serial) and _is_pkg_installed(_U2_TEST_PKG, serial)
        if u2_ok and _is_atx_listening(serial):
            return True

    try:
        if not _DEVICE_BUNDLE_TGZ.exists() or _DEVICE_BUNDLE_TGZ.stat().st_size == 0:
            from pack_bundle import pack_bundle as _pack_bundle
            result = _pack_bundle(force=False)
            if result is None:
                console.print("    [yellow]⚠[/yellow] Bundle pack skipped (missing assets). Falling back to normal bootstrap.")
                return False

        console.print("    [cyan]→[/cyan] Deploying device_bundle.tar.gz + launch.sh …")
        r = _adb("push", str(_DEVICE_BUNDLE_TGZ), "/data/local/tmp/device_bundle.tar.gz",
                 serial=serial, check=False, timeout=60)
        if r.returncode != 0:
            console.print(f"    [yellow]⚠[/yellow] adb push bundle failed: {(r.stdout + r.stderr).strip()[:200]}")
            return False

        # Clean then extract then launch (avoid bad symlink/old dirs)
        _adb_shell(
            "cd /data/local/tmp && rm -rf launch.sh apks atx-agent scrcpy-server "
            "&& tar -xzf device_bundle.tar.gz && sh launch.sh",
            serial=serial,
            timeout=120,
        )

        # Verify atx-agent is up
        for _ in range(10):
            time.sleep(0.5)
            if _is_atx_listening(serial):
                console.print("    [green]✓[/green] bundle launch OK (atx-agent :7912)")
                return True
        console.print("    [yellow]⚠[/yellow] bundle launched but atx-agent not detected on :7912")
        return False
    except Exception as e:
        console.print(f"    [yellow]⚠[/yellow] bundle deploy failed ({e})")
        return False


def step_install_stf(serial: str, apk_path: Path | None, skip: bool) -> bool:
    _step_header(5, "Install STFService.apk")
    if skip:
        console.print("    [dim]Skipped (--skip-stf)[/dim]")
        return False
    if apk_path is None:
        console.print("    [red]✗[/red] STFService.apk not found.")
        console.print(f"      A) Copy prebuilt APK → {_ROOT / 'STFService.apk'}")
        console.print("      B) Build: cd ../STFService.apk && ./gradlew assembleFullDebug")
        console.print("      C) Use --skip-stf if already installed")
        return False
    if _is_pkg_installed(_STF_PKG, serial):
        console.print(f"    [green]✓[/green] {_STF_PKG} already installed — skipping.")
        return True
    return _adb_install(apk_path, serial, "STFService")


def step_grant_permissions(serial: str, skip: bool) -> None:
    _step_header(6, "Grant STFService permissions")
    if skip:
        console.print("    [dim]Skipped (--skip-stf)[/dim]")
        return
    if not _is_pkg_installed(_STF_PKG, serial):
        console.print(f"    [red]✗[/red] {_STF_PKG} not installed — skipping.")
        return
    for perm in ["android.permission.WRITE_SECURE_SETTINGS", "android.permission.READ_PHONE_STATE"]:
        out = _adb_shell(f"pm grant {_STF_PKG} {perm}", serial=serial)
        if out and "Exception" in out:
            console.print(f"    [yellow]⚠[/yellow] pm grant {perm}: {out[:200]}")
        else:
            console.print(f"    [green]✓[/green] {perm}")


def _is_stf_a11y_bound(serial: str) -> bool:
    """
    True when STF accessibility service is currently bound by AccessibilityManager.
    """
    out = _adb_shell("dumpsys accessibility", serial=serial, timeout=20)
    for line in out.splitlines():
        if "Bound services:" in line and _STF_A11Y_SERVICE in line:
            return True
    return False


def _ensure_stf_a11y_bound(serial: str) -> bool:
    """
    Auto-heal common Vivo/ColorOS state:
      - enabled_accessibility_services contains STF service
      - but Bound services is empty (service not actually attached)
    """
    if _is_stf_a11y_bound(serial):
        console.print("    [green]✓[/green] Accessibility service already bound")
        return True

    enabled = _adb_shell("settings get secure enabled_accessibility_services", serial=serial, timeout=10)
    if _STF_A11Y_SERVICE not in enabled:
        _adb_shell(
            f"settings put secure enabled_accessibility_services '{_STF_A11Y_SERVICE}'",
            serial=serial,
            timeout=10,
        )
        _adb_shell("settings put secure accessibility_enabled 1", serial=serial, timeout=10)
        console.print("    [cyan]→[/cyan] Added STF accessibility service to secure settings")

    # Rebind sequence: toggle a11y off/on and restart STF process.
    _adb_shell("settings put secure enabled_accessibility_services ''", serial=serial, timeout=10)
    _adb_shell("settings put secure accessibility_enabled 0", serial=serial, timeout=10)
    _adb_shell(f"am force-stop {_STF_PKG}", serial=serial, timeout=10)
    _adb_shell(
        f"settings put secure enabled_accessibility_services '{_STF_A11Y_SERVICE}'",
        serial=serial,
        timeout=10,
    )
    _adb_shell("settings put secure accessibility_enabled 1", serial=serial, timeout=10)
    _adb(
        "shell", "am", "start", "-n", f"{_STF_PKG}/.IdentityActivity",
        "-a", "android.intent.action.MAIN", serial=serial, check=False, timeout=10
    )

    for _ in range(6):
        time.sleep(0.8)
        if _is_stf_a11y_bound(serial):
            console.print("    [green]✓[/green] Accessibility service rebound")
            return True

    console.print("    [yellow]⚠[/yellow] Accessibility enabled but not bound yet (manual toggle may still be needed)")
    return False


def _ensure_stability_settings(serial: str) -> None:
    """
    Device-side settings that keep agent-boot connections stable.

    Currently: stay_on_while_plugged_in=3 → screen stays on while on AC/USB,
    avoids the sleep → adb offline → scrcpy crash cycle (Genymobile/scrcpy#6607).

    NOTE: We previously tried to whitelist `com.github.uiautomator/.AccessibilityService`
    here. That service does NOT exist in the uiautomator APK — openatx/uiautomator2
    runs via the UiAutomation API (test instrumentation), not an AccessibilityService.
    Android silently rejects unknown services. STF is the only a11y service
    actually needed; its rebind is handled by _ensure_stf_a11y_bound.

    Idempotent — safe to re-run on every bootstrap.
    """
    try:
        _adb_shell("settings put global stay_on_while_plugged_in 3", serial=serial, timeout=10)
        console.print("    [green]✓[/green] stay_on_while_plugged_in=3 (screen stays on while charging)")
    except Exception as exc:
        console.print(f"    [yellow]⚠[/yellow] stay_on_while_plugged_in failed: {exc}")

    # Log available H264/H265 encoders so operators know what to flip to
    # via SCRCPY_VIDEO_ENCODER if the default encoder stalls. Non-blocking:
    # any failure here is diagnostic-only, never fails bootstrap.
    try:
        raw = _adb_shell("dumpsys media.codec 2>/dev/null", serial=serial, timeout=15)
        encoders: list[str] = []
        for line in raw.splitlines():
            line = line.strip()
            # Codec2 (c2.*) and legacy (OMX.*) encoder names for H264/H265
            if (line.startswith(("c2.", "OMX.")) and
                any(tag in line.lower() for tag in ("avc", "h264", "hevc", "h265")) and
                "encoder" in line.lower()):
                name = line.split()[0].rstrip(":")
                if name not in encoders:
                    encoders.append(name)
        if encoders:
            console.print(f"    [cyan]→[/cyan] available video encoders: {', '.join(encoders[:6])}")
            console.print(
                "      [dim]flip via SCRCPY_VIDEO_ENCODER=<name> or per-serial "
                f"SCRCPY_VIDEO_ENCODER__{serial.replace(':','_').replace('.','_')}=<name>[/dim]"
            )
    except Exception as exc:
        console.print(f"    [dim]encoder probe skipped: {exc}[/dim]")


def step_open_app(serial: str, skip: bool) -> None:
    _step_header(7, "Open STFService")
    if skip:
        console.print("    [dim]Skipped (--skip-stf)[/dim]")
        return
    if not _auto_open_stf_enabled():
        console.print("    [dim]Skipped auto-open (set AUTO_OPEN_STF_APP=1 to enable)[/dim]")
        return
    _adb("shell", "am", "start", "-n", f"{_STF_PKG}/.IdentityActivity",
         "-a", "android.intent.action.MAIN", serial=serial, check=False, timeout=10)
    console.print("    [green]✓[/green] STFService opened (IdentityActivity)")
    _ensure_stf_a11y_bound(serial)
    console.print()
    console.print(Panel(
        "[bold]Next steps on phone:[/bold]\n\n"
        "  1. Open dashboard: [cyan]http\\://<BACKEND_IP>:8081[/cyan]\n"
        "  2. Device Management → Register → show QR code\n"
        "  3. In STFService: tap [bold]Scan QR[/bold] → scan → allow screen recording",
        title="[bold green]Bootstrap complete[/bold green]",
        border_style="green",
        expand=False,
    ))


# ── Per-device orchestration ──────────────────────────────────────────────────

def boot_device(serial: str, stf_apk: Path | None, *,
                skip_tcpip: bool = False, tcpip_port: int = 5555,
                use_bundle: bool = False,
                skip_u2: bool = False, skip_atx: bool = False,
                skip_stf: bool = False) -> bool:
    sdk   = _get_sdk(serial)
    model = _adb_shell("getprop ro.product.model", serial=serial)

    with _print_lock:
        console.print(Panel(
            f"[bold]Serial:[/bold] {serial}\n"
            f"[bold]Model:[/bold]  {model}\n"
            f"[bold]SDK:[/bold]    {sdk}",
            title="[bold blue]Bootstrap[/bold blue]",
            border_style="blue",
            expand=False,
        ))

    try:
        active = serial
        # Only run tcpip if connected via USB — WiFi serials are already usable.
        if not skip_tcpip and ":" not in serial:
            active = step_tcpip(serial, tcpip_port)
        elif ":" in serial:
            _step_header(1, f"Enable adb tcpip {tcpip_port}")
            console.print(f"    [dim]Skipped — already on WiFi ({serial})[/dim]")
        step_wireless_debugging(active, skip=skip_tcpip)
        # If requested, try the "single tar push" path only when needed.
        if use_bundle and not skip_u2 and not skip_atx:
            _step_header(3, "Install uiautomator2 APKs")
            console.print("    [dim]Bundled mode (--use-bundle): handled by launch.sh[/dim]")
            _step_header(4, "Push + start atx-agent (port 7912)")
            bundle_ok = step_deploy_bundle_if_needed(active)
            u2_ok = bundle_ok and _is_pkg_installed(_U2_PKG, active) and _is_pkg_installed(_U2_TEST_PKG, active)
            atx_ok = bundle_ok and _is_atx_listening(active)
        else:
            u2_ok  = step_install_u2(active, skip=skip_u2)
            atx_ok = step_push_atx_agent(active, skip=skip_u2 or skip_atx)
        step_install_stf(active, stf_apk, skip=skip_stf)
        step_grant_permissions(active, skip=skip_stf)
        step_open_app(active, skip=skip_stf)
        # MUST run after step_open_app — the STF a11y rebind sequence inside
        # _ensure_stf_a11y_bound() clears enabled_accessibility_services then
        # sets ONLY the STF service. Running our settings after it guarantees
        # the u2 AccessibilityService survives the rebind.
        _ensure_stability_settings(active)

        # u2 + atx-agent are required for device control
        critical_ok = skip_u2 or (u2_ok and atx_ok)
        if critical_ok:
            with _print_lock:
                console.print(f"\n[bold green]✅ [{serial}] Bootstrap done![/bold green]")
        else:
            with _print_lock:
                console.print(f"\n[bold yellow]⚠ [{serial}] Bootstrap incomplete — u2/atx-agent failed[/bold yellow]")
        return critical_ok
    except Exception as e:
        with _print_lock:
            console.print(f"\n[bold red]✗ [{serial}] Error: {e}[/bold red]")
        return False


def run_bootstrap(serials: list[str], stf_apk: Path | None, **kwargs) -> dict[str, bool]:
    """Bootstrap all serials in parallel. Returns {serial: success}."""
    results: dict[str, bool] = {}

    if len(serials) == 1:
        results[serials[0]] = boot_device(serials[0], stf_apk, **kwargs)
    else:
        threads = [
            threading.Thread(
                target=lambda s=s: results.__setitem__(s, boot_device(s, stf_apk, **kwargs)),
                daemon=True,
            )
            for s in serials
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    # Summary table
    table = Table(title="Bootstrap Results", show_header=True, header_style="bold")
    table.add_column("Serial", style="cyan")
    table.add_column("Result", justify="center")
    for serial, ok in results.items():
        table.add_row(serial, "[green]✅ OK[/green]" if ok else "[red]✗ FAILED[/red]")
    console.print(table)

    return results
