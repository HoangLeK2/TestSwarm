#!/usr/bin/env python3
"""
setup_agent.py — Auto-setup script cho Device Farm Agent (chay tren Termux / Android).

Chay mot lan truoc khi start agent:
    python setup_agent.py

Hoac tu dong chay khi agent khoi dong lan dau:
    python agent_local.py --auto-setup

Cai dat tu dong:
  1. minitouch binary   — tai tu GitHub (stf-binaries), chmod +x, chay background
  2. uiautomator2 APKs  — tai va cai: app-uiautomator.apk + app-uiautomator-test.apk
  3. STFService APK     — tai va cai: STFService.apk
  4. Kiem tra tat ca service da hoat dong
"""
from __future__ import annotations

import json
import logging
import os
import socket
import stat
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

log = logging.getLogger("setup_agent")

# ── Constants ──────────────────────────────────────────────────────────────────

def _project_root() -> Path:
    """Repo root (``…/device_farm``) or flat Termux dir next to ``bundle/``."""
    p = Path(__file__).resolve().parent
    return p.parent if p.name == "scripts" else p


# Bundle local — dat cac file vao day de khong can internet
# Cau truc:
#   bundle/minitouch/arm64-v8a/minitouch
#   bundle/minitouch/armeabi-v7a/minitouch
#   bundle/minitouch/x86_64/minitouch
#   bundle/minitouch/x86/minitouch
#   bundle/apks/app-uiautomator.apk
#   bundle/apks/app-uiautomator-test.apk
#   bundle/apks/STFService.apk
BUNDLE_DIR = _project_root() / "bundle"

# minitouch binary locations (thu tu uu tien de cai)
MINITOUCH_INSTALL_PATHS = [
    "/data/local/tmp/minitouch",
    str(Path.home() / "minitouch"),
]

# Thu muc luu APK tai ve
APK_CACHE_DIR = Path.home() / ".farm" / "apks"

# Download URLs — chi dung khi khong co bundle local
_U2_RELEASES_URL = "https://api.github.com/repos/openatx/android-uiautomator-server/releases/latest"

# Known-good fallback URLs (khi GitHub API bi rate-limit)
_U2_APK_FALLBACK      = "https://github.com/openatx/android-uiautomator-server/releases/download/0.3.3/app-uiautomator.apk"
_U2_TEST_APK_FALLBACK = "https://github.com/openatx/android-uiautomator-server/releases/download/0.3.3/app-uiautomator-test.apk"

# minitouch prebuilt binaries (openatx fork — supports Android 5+)
_MINITOUCH_BASE = (
    "https://github.com/openatx/stf-binaries/raw/master/"
    "node_modules/minitouch-prebuilt/prebuilt/{abi}/bin/minitouch"
)

# STFService APK tu OpenSTF repo
_STF_SERVICE_APK_URL = (
    "https://github.com/openstf/stf/raw/master/vendor/STFService.apk"
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(cmd: list, timeout: int = 30, check: bool = False) -> tuple[int, str, str]:
    """Chay lenh, tra ve (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(
            cmd, capture_output=True, timeout=timeout,
        )
        out = r.stdout.decode("utf-8", errors="replace").strip()
        err = r.stderr.decode("utf-8", errors="replace").strip()
        return r.returncode, out, err
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)


def _prop(name: str) -> str:
    _, out, _ = _run(["getprop", name])
    return out.strip()


def _get_abi() -> str:
    """Lay ABI chinh cua device (arm64-v8a, armeabi-v7a, x86, x86_64)."""
    abi = _prop("ro.product.cpu.abi")
    if not abi:
        import platform
        machine = platform.machine()
        abi_map = {
            "aarch64": "arm64-v8a",
            "armv7l":  "armeabi-v7a",
            "x86_64":  "x86_64",
            "i686":    "x86",
        }
        abi = abi_map.get(machine, "arm64-v8a")
    return abi


def _is_package_installed(pkg: str) -> bool:
    """Kiem tra APK da duoc cai chua."""
    code, out, _ = _run(["pm", "list", "packages", pkg])
    return f"package:{pkg}" in out


def _download(url: str, dest: Path, label: str = "") -> bool:
    """Tai file tu URL ve dest. Tra ve True neu thanh cong."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    label = label or dest.name
    log.info(f"Downloading {label} ...")
    log.info(f"  URL: {url}")
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "DeviceFarm-SetupAgent/1.0"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            chunk = 65536
            with open(dest, "wb") as f:
                while True:
                    data = resp.read(chunk)
                    if not data:
                        break
                    f.write(data)
                    downloaded += len(data)
                    if total:
                        pct = downloaded * 100 // total
                        print(f"\r  {label}: {pct}%  ({downloaded}/{total} bytes)", end="", flush=True)
            print()
        log.info(f"  Saved to {dest} ({downloaded} bytes)")
        return True
    except Exception as e:
        log.error(f"  Download failed: {e}")
        if dest.exists():
            dest.unlink()
        return False


def _get_github_release_asset(api_url: str, name_contains: str) -> Optional[str]:
    """Lay download URL cua asset trong GitHub latest release."""
    try:
        req = urllib.request.Request(
            api_url,
            headers={"User-Agent": "DeviceFarm-SetupAgent/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        for asset in data.get("assets", []):
            if name_contains.lower() in asset["name"].lower():
                return asset["browser_download_url"]
    except Exception as e:
        log.debug(f"GitHub API error: {e}")
    return None


def _install_apk(apk_path: Path, label: str = "") -> bool:
    """Cai APK bang 'pm install'. Yeu cau Android 10+ hoac root."""
    label = label or apk_path.name
    log.info(f"Installing {label} ...")

    def _is_failure(out: str, err: str) -> bool:
        combined = (out + err).lower()
        return "failure" in combined or "exception" in combined

    # Thu pm install -r (replace existing)
    # Android moi: pm install tra ve exit code 0 khi thanh cong,
    # khong nhat thiet in "Success" ra stdout.
    code, out, err = _run(
        ["pm", "install", "-r", str(apk_path)],
        timeout=60,
    )
    if code == 0 and not _is_failure(out, err):
        log.info(f"  {label} installed OK")
        return True

    # Thu voi --user 0 (mot so ROM can user flag tuong minh)
    code, out, err = _run(
        ["pm", "install", "-r", "--user", "0", str(apk_path)],
        timeout=60,
    )
    if code == 0 and not _is_failure(out, err):
        log.info(f"  {label} installed OK (--user 0)")
        return True

    log.warning(f"  pm install failed (code={code}): {err or out}")
    return False


def _tcp_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True
    except Exception:
        return False


# ── Setup Steps ───────────────────────────────────────────────────────────────

class SetupResult:
    def __init__(self) -> None:
        self.minitouch_path:  Optional[str] = None
        self.minitouch_ready: bool = False
        self.u2_ready:        bool = False
        self.stfservice_ready: bool = False

    def summary(self) -> None:
        print("\n" + "=" * 50)
        print("Setup Summary")
        print("=" * 50)
        print(f"  minitouch  : {'✓ ' + (self.minitouch_path or '') if self.minitouch_ready else '✗  (touch se dung fallback input)'}")
        print(f"  u2 server  : {'✓ :9008' if self.u2_ready else '✗  (u2 tunnel se khong hoat dong)'}")
        print(f"  stfservice : {'✓' if self.stfservice_ready else '✗  (battery/rotation events bi tat)'}")
        print("=" * 50)
        if self.minitouch_ready and self.u2_ready:
            print("Trang thai: SAN SANG — chay agent_local.py")
        else:
            print("Trang thai: MOT SO TINH NANG BI THIEU — agent van chay nhung han che")
        print()


def _get_bundled_minitouch(abi: str) -> Optional[Path]:
    """Tim minitouch binary trong bundle/ local. Tra ve Path neu co, None neu khong."""
    candidate = BUNDLE_DIR / "minitouch" / abi / "minitouch"
    if candidate.is_file():
        return candidate
    # Fallback ABI
    fallback_map = {
        "arm64-v8a":   "armeabi-v7a",
        "armeabi-v7a": "arm64-v8a",
        "x86_64":      "x86",
        "x86":         "x86_64",
    }
    fb = fallback_map.get(abi)
    if fb:
        candidate2 = BUNDLE_DIR / "minitouch" / fb / "minitouch"
        if candidate2.is_file():
            log.info(f"minitouch: dung ABI fallback {fb} thay {abi}")
            return candidate2
    return None


def _get_bundled_apk(filename: str) -> Optional[Path]:
    """Tim APK trong bundle/apks/. Tra ve Path neu co, None neu khong."""
    candidate = BUNDLE_DIR / "apks" / filename
    return candidate if candidate.is_file() else None


def setup_minitouch(result: SetupResult) -> None:
    """Buoc 1: Cai minitouch binary va start."""
    print("\n[1/3] minitouch")

    # Kiem tra neu da duoc cai o vi tri dich
    for path in MINITOUCH_INSTALL_PATHS:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            log.info(f"minitouch da co: {path}")
            result.minitouch_path = path
            result.minitouch_ready = True
            _start_minitouch(path, result)
            return

    abi = _get_abi()
    log.info(f"ABI: {abi}")

    # Chon vi tri cai dat
    dest = Path(MINITOUCH_INSTALL_PATHS[0])  # /data/local/tmp/minitouch
    if not _try_write_dir(dest.parent):
        dest = Path(MINITOUCH_INSTALL_PATHS[1])  # ~/minitouch

    # Uu tien 1: Bundle local
    bundled = _get_bundled_minitouch(abi)
    if bundled:
        log.info(f"Dung minitouch tu bundle local: {bundled}")
        import shutil
        try:
            shutil.copy2(str(bundled), str(dest))
            log.info(f"Copied to {dest}")
        except Exception as e:
            log.error(f"Copy bundle failed: {e}")
            return
    else:
        # Uu tien 2: Tai tu internet
        log.info("Khong co bundle local → tai minitouch tu GitHub ...")
        url = _MINITOUCH_BASE.format(abi=abi)
        if not _download(url, dest, "minitouch"):
            # Thu armeabi-v7a neu arm64 that bai
            if abi == "arm64-v8a":
                log.info("Thu lai voi armeabi-v7a ...")
                url2 = _MINITOUCH_BASE.format(abi="armeabi-v7a")
                if not _download(url2, dest, "minitouch (armeabi-v7a)"):
                    log.error("Khong tai duoc minitouch. Touch se dung 'input' fallback.")
                    return
            else:
                log.error("Khong tai duoc minitouch. Touch se dung 'input' fallback.")
                return

    # chmod +x
    try:
        dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        log.info(f"chmod +x {dest}")
    except Exception as e:
        log.warning(f"chmod failed: {e}")

    result.minitouch_path = str(dest)
    result.minitouch_ready = True
    _start_minitouch(str(dest), result)


def _try_write_dir(d: Path) -> bool:
    try:
        d.mkdir(parents=True, exist_ok=True)
        test = d / ".write_test"
        test.touch()
        test.unlink()
        return True
    except Exception:
        return False


def _start_minitouch(path: str, result: SetupResult) -> None:
    """Start minitouch process neu chua chay."""
    code, out, _ = _run(["pgrep", "-f", "minitouch"])
    if code == 0 and out:
        log.info("minitouch da dang chay (pid=" + out.split()[0] + ")")
        return
    log.info(f"Starting minitouch: {path}")
    try:
        # -n minitouch: dat ten abstract socket la "minitouch"
        # (server dung adb forward tcp:PORT localabstract:minitouch de ket noi)
        subprocess.Popen(
            [path, "-n", "minitouch"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1.0)
        # Verify process is up
        code, out, _ = _run(["pgrep", "-f", "minitouch"])
        if code == 0:
            log.info("minitouch dang chay OK (socket: localabstract:minitouch)")
        else:
            log.warning("minitouch khong start duoc (co the thieu quyen). Touch se dung fallback.")
            result.minitouch_ready = False
    except Exception as e:
        log.warning(f"minitouch start error: {e}")
        result.minitouch_ready = False


def _resolve_apk(filename: str, fallback_url: str, label: str) -> Optional[Path]:
    """
    Lay duong dan APK:
      1. Tim trong bundle/apks/ truoc
      2. Neu khong co → tai tu internet ve APK_CACHE_DIR
    """
    # Uu tien bundle local
    bundled = _get_bundled_apk(filename)
    if bundled:
        log.info(f"{label}: dung bundle local ({bundled})")
        return bundled

    # Tai tu internet
    log.info(f"{label}: khong co bundle → tai tu internet ...")
    APK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest = APK_CACHE_DIR / filename
    if dest.is_file():
        log.info(f"{label}: da co trong cache ({dest})")
        return dest
    if _download(fallback_url, dest, filename):
        return dest
    return None


def setup_uiautomator2(result: SetupResult) -> None:
    """Buoc 2: Cai uiautomator2 APKs va start server."""
    print("\n[2/3] uiautomator2 (ATX-Agent)")

    main_pkg = "com.github.uiautomator"
    test_pkg = "com.github.uiautomator.test"

    main_installed = _is_package_installed(main_pkg)
    test_installed = _is_package_installed(test_pkg)

    if main_installed and test_installed:
        log.info("uiautomator2 APKs da cai. Kiem tra server :9008 ...")
        _start_u2_server(result)
        return

    # Lay URL moi nhat tu GitHub (chi dung khi phai tai internet)
    latest_main = _get_github_release_asset(_U2_RELEASES_URL, "app-uiautomator.apk")
    latest_test = _get_github_release_asset(_U2_RELEASES_URL, "app-uiautomator-test.apk")

    if not main_installed:
        apk = _resolve_apk(
            "app-uiautomator.apk",
            latest_main or _U2_APK_FALLBACK,
            "app-uiautomator",
        )
        if apk:
            _install_apk(apk, "com.github.uiautomator")
        else:
            log.error("Khong lay duoc app-uiautomator.apk")
            return

    if not test_installed:
        apk = _resolve_apk(
            "app-uiautomator-test.apk",
            latest_test or _U2_TEST_APK_FALLBACK,
            "app-uiautomator-test",
        )
        if apk:
            _install_apk(apk, "com.github.uiautomator.test")

    _start_u2_server(result)


def _start_u2_server(result: SetupResult) -> None:
    """Start uiautomator2 HTTP server (am instrument, port 9008). Khong dung ATX-agent."""
    if _tcp_reachable("127.0.0.1", 9008):
        log.info("uiautomator2 server da chay tren :9008")
        result.u2_ready = True
        return

    log.info("Start uiautomator2 server (am instrument :9008) ...")
    _run([
        "sh", "-c",
        "am instrument -w com.github.uiautomator.test/androidx.test.runner.AndroidJUnitRunner"
        + " </dev/null >/data/local/tmp/u2.log 2>&1 &",
    ], timeout=5)

    for i in range(12):
        time.sleep(1)
        if _tcp_reachable("127.0.0.1", 9008):
            log.info("uiautomator2 server UP :9008")
            result.u2_ready = True
            return
        log.debug(f"Waiting for u2 server... ({i+1}/12)")

    log.warning("uiautomator2 server khong start duoc tren :9008")
    log.warning("Thu chay: am instrument -w com.github.uiautomator.test/androidx.test.runner.AndroidJUnitRunner")


def setup_stfservice(result: SetupResult) -> None:
    """Buoc 3: Cai STFService APK."""
    print("\n[3/3] STFService")

    pkg = "jp.co.cyberagent.stf"

    if _is_package_installed(pkg):
        log.info("STFService da cai")
        result.stfservice_ready = True
        # Start service neu chua chay
        _run([
            "am", "startservice",
            "-n", f"{pkg}/.STFService",
            "-a", "jp.co.cyberagent.stf.SERVICE",
        ], timeout=10)
        return

    apk = _resolve_apk(
        "STFService.apk",
        _STF_SERVICE_APK_URL,
        "STFService",
    )
    if not apk:
        log.warning("Khong lay duoc STFService.apk")
        log.warning("STFService se khong hoat dong (battery/rotation events bi tat)")
        return

    if _install_apk(apk, "STFService"):
        _run([
            "am", "startservice",
            "-n", f"{pkg}/.STFService",
            "-a", "jp.co.cyberagent.stf.SERVICE",
        ], timeout=10)
        time.sleep(1)
        result.stfservice_ready = True


# ── Public API ─────────────────────────────────────────────────────────────────

def run_setup(verbose: bool = True) -> SetupResult:
    """
    Chay toan bo qua trinh setup.
    Goi ham nay tu agent_local.py hoac chay truc tiep.
    """
    if verbose:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
        )

    print("=" * 50)
    print("Device Farm Agent — Auto Setup")
    print("=" * 50)
    abi = _get_abi()
    print(f"ABI: {abi}")
    print(f"Android: {_prop('ro.build.version.release')} (SDK {_prop('ro.build.version.sdk')})")
    print()

    result = SetupResult()
    setup_minitouch(result)
    setup_uiautomator2(result)
    setup_stfservice(result)
    result.summary()
    return result


def quick_check() -> SetupResult:
    """
    Chi kiem tra nhanh trang thai (khong cai dat them).
    Dung khi agent khoi dong de kiem tra dich vu con song khong.
    """
    result = SetupResult()

    # minitouch
    for path in MINITOUCH_INSTALL_PATHS:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            result.minitouch_path = path
            code, out, _ = _run(["pgrep", "-f", "minitouch"])
            result.minitouch_ready = code == 0
            break

    # u2 (am instrument :9008)
    result.u2_ready = _tcp_reachable("127.0.0.1", 9008, timeout=1.0)

    # stfservice
    result.stfservice_ready = _is_package_installed("jp.co.cyberagent.stf")

    return result


def ensure_services_running(setup_result: Optional[SetupResult] = None) -> None:
    """
    Dam bao tat ca service dang chay. Restart neu chet.
    Goi dinh ky tu agent.
    """
    # minitouch
    if setup_result and setup_result.minitouch_path:
        code, out, _ = _run(["pgrep", "-f", "minitouch"])
        if code != 0:
            log.warning("minitouch da chet — restart ...")
            try:
                subprocess.Popen(
                    [setup_result.minitouch_path, "-n", "minitouch"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                time.sleep(0.5)
            except Exception as e:
                log.warning(f"minitouch restart failed: {e}")

    # u2 (am instrument :9008)
    if not _tcp_reachable("127.0.0.1", 9008, timeout=1.0):
        log.warning("uiautomator2 server chet — restart am instrument ...")
        _run([
            "sh", "-c",
            "am instrument -w com.github.uiautomator.test/androidx.test.runner.AndroidJUnitRunner"
            + " </dev/null >/data/local/tmp/u2.log 2>&1 &",
        ], timeout=5)


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Device Farm Agent — Auto Setup")
    ap.add_argument(
        "--check",
        action="store_true",
        help="Chi kiem tra trang thai, khong cai them",
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    if args.check:
        r = quick_check()
        r.summary()
    else:
        run_setup()


if __name__ == "__main__":
    main()
