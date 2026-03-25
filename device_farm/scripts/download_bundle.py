#!/usr/bin/env python3
"""
download_bundle.py — Chuan bi bundle/ cho agent (chay tren PC truoc khi phan phoi).

Tai tat ca binary/APK can thiet va luu vao thu muc bundle/:
    bundle/
    ├── minitouch/
    │   ├── arm64-v8a/minitouch      (Android 64-bit — pho bien nhat)
    │   ├── armeabi-v7a/minitouch    (Android 32-bit cu)
    │   ├── x86_64/minitouch         (emulator 64-bit)
    │   └── x86/minitouch            (emulator 32-bit)
    └── apks/
        ├── app-uiautomator.apk          (uiautomator2 main)
        ├── app-uiautomator-test.apk     (uiautomator2 test runner — BAT BUOC)
        └── STFService.apk               (battery/rotation events)

Sau do copy ca thu muc bundle/ len Termux, kem hai file day du trong scripts/ (khong dung shim *.py o root repo):
  - scripts/agent_local.py
  - scripts/setup_agent.py

Tu thu muc goc device_farm tren PC:
    adb push bundle/ /data/data/com.termux/files/home/
    adb push scripts/agent_local.py scripts/setup_agent.py /data/data/com.termux/files/home/

Tren Termux:
    python agent_local.py --server ws://SERVER:8081/device-agent --auto-setup

Usage (tu thu muc device_farm):
    python download_bundle.py               # hoac: python scripts/download_bundle.py
    python download_bundle.py --abi arm64
    python download_bundle.py --no-minitouch
    python download_bundle.py --no-stf
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import urllib.request
from pathlib import Path


def _project_root() -> Path:
    p = Path(__file__).resolve().parent
    return p.parent if p.name == "scripts" else p


BUNDLE_DIR = _project_root() / "bundle"
RUNTIME_DIR = _project_root() / "runtime"

# ── Download URLs ──────────────────────────────────────────────────────────────

MINITOUCH_ABIS = ["arm64-v8a", "armeabi-v7a", "x86_64", "x86"]

MINITOUCH_URL = (
    "https://github.com/openatx/stf-binaries/raw/master/"
    "node_modules/minitouch-prebuilt/prebuilt/{abi}/bin/minitouch"
)

_U2_API = "https://api.github.com/repos/openatx/android-uiautomator-server/releases/latest"
U2_APK_FALLBACK      = "https://github.com/openatx/android-uiautomator-server/releases/download/0.3.3/app-uiautomator.apk"
U2_TEST_APK_FALLBACK = "https://github.com/openatx/android-uiautomator-server/releases/download/0.3.3/app-uiautomator-test.apk"

STF_SERVICE_URL = "https://github.com/openstf/stf/raw/master/vendor/STFService.apk"

# scrcpy-server: version must match SCRCPY_SERVER_VERSION in runtime/transports/scrcpy_receiver.py
# Download from official Genymobile/scrcpy GitHub releases.
_SCRCPY_VERSION = "3.3"   # version tag on GitHub (e.g. "3.3" → release v3.3)
SCRCPY_SERVER_URL = (
    f"https://github.com/Genymobile/scrcpy/releases/download/v{_SCRCPY_VERSION}"
    f"/scrcpy-server-v{_SCRCPY_VERSION}"
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _download(url: str, dest: Path, label: str = "") -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    label = label or dest.name
    print(f"  Downloading {label} ...")
    print(f"    {url}")
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "DeviceFarm-BundleDownloader/1.0"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = downloaded * 100 // total
                        print(f"\r    {pct}% ({downloaded}/{total} bytes)", end="", flush=True)
            print(f"\r    OK — {downloaded} bytes saved to {dest}          ")
        return True
    except Exception as e:
        print(f"\r    FAIL: {e}                                              ")
        if dest.exists():
            dest.unlink()
        return False


def _get_github_latest_urls() -> dict:
    """Lay URL APK moi nhat tu GitHub releases."""
    urls = {}
    try:
        req = urllib.request.Request(
            _U2_API,
            headers={"User-Agent": "DeviceFarm-BundleDownloader/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        for asset in data.get("assets", []):
            name = asset["name"]
            if "app-uiautomator-test" in name:
                urls["test"] = asset["browser_download_url"]
            elif "app-uiautomator" in name:
                urls["main"] = asset["browser_download_url"]
        print(f"  uiautomator2 latest version: {data.get('tag_name', 'unknown')}")
    except Exception as e:
        print(f"  GitHub API error: {e} — dung fallback URL")
    return urls


# ── Download steps ────────────────────────────────────────────────────────────

def download_minitouch(abis: list[str]) -> None:
    print("\n[1/3] minitouch binaries")
    ok = 0
    for abi in abis:
        dest = BUNDLE_DIR / "minitouch" / abi / "minitouch"
        if dest.is_file():
            print(f"  {abi}: da co (skip)")
            ok += 1
            continue
        url = MINITOUCH_URL.format(abi=abi)
        if _download(url, dest, f"minitouch/{abi}"):
            # chmod +x
            dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            ok += 1
    print(f"  minitouch: {ok}/{len(abis)} ABI thanh cong")


def download_uiautomator2() -> None:
    print("\n[2/3] uiautomator2 APKs")
    latest = _get_github_latest_urls()

    # Main APK
    main_dest = BUNDLE_DIR / "apks" / "app-uiautomator.apk"
    if main_dest.is_file():
        print(f"  app-uiautomator.apk: da co (skip)")
    else:
        _download(latest.get("main", U2_APK_FALLBACK), main_dest, "app-uiautomator.apk")

    # Test APK (BAT BUOC — uiautomator2 khong chay neu thieu)
    test_dest = BUNDLE_DIR / "apks" / "app-uiautomator-test.apk"
    if test_dest.is_file():
        print(f"  app-uiautomator-test.apk: da co (skip)")
    else:
        _download(latest.get("test", U2_TEST_APK_FALLBACK), test_dest, "app-uiautomator-test.apk")


def download_stfservice() -> None:
    print("\n[3/3] STFService APK")
    dest = BUNDLE_DIR / "apks" / "STFService.apk"
    if dest.is_file():
        print(f"  STFService.apk: da co (skip)")
        return
    _download(STF_SERVICE_URL, dest, "STFService.apk")


def download_scrcpy_server() -> None:
    """
    Tai scrcpy-server JAR ve runtime/scrcpy-server.
    JAR nay dung phia server (host), khong push vao bundle/ (khong deploy len dien thoai).
    Path nay duoc doc boi AdbDeviceBootstrap._resolve_scrcpy_jar().

    Luu y: version trong SCRCPY_SERVER_URL phai khop voi
    SCRCPY_SERVER_VERSION trong runtime/transports/scrcpy_receiver.py.
    """
    print(f"\n[4/4] scrcpy-server v{_SCRCPY_VERSION} (server-side JAR)")
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    dest = RUNTIME_DIR / "scrcpy-server"
    if dest.is_file():
        print(f"  scrcpy-server: da co tai {dest} (skip)")
        _set_scrcpy_env_hint(dest)
        return

    ok = _download(SCRCPY_SERVER_URL, dest, f"scrcpy-server-v{_SCRCPY_VERSION}")
    if ok:
        # chmod +x (optional but good practice)
        try:
            dest.chmod(dest.stat().st_mode | 0o111)
        except Exception:
            pass
        _set_scrcpy_env_hint(dest)
    else:
        print(
            f"  WARN: scrcpy-server download that bai.\n"
            f"  Tai thu cong tu: https://github.com/Genymobile/scrcpy/releases/tag/v{_SCRCPY_VERSION}\n"
            f"  Luu vao: {dest}"
        )


def _set_scrcpy_env_hint(dest: Path) -> None:
    print(f"  Dat SCRCPY_JAR={dest.resolve()}")
    print(f"  Hoac them vao config.yaml: scrcpy_jar: {dest.resolve()}")


def print_summary() -> None:
    print("\n" + "=" * 55)
    print("Bundle Summary")
    print("=" * 55)

    for abi in MINITOUCH_ABIS:
        p = BUNDLE_DIR / "minitouch" / abi / "minitouch"
        size = f"{p.stat().st_size:,} bytes" if p.exists() else "MISSING"
        print(f"  minitouch/{abi:15s}: {size}")

    for apk in ["app-uiautomator.apk", "app-uiautomator-test.apk", "STFService.apk"]:
        p = BUNDLE_DIR / "apks" / apk
        size = f"{p.stat().st_size:,} bytes" if p.exists() else "MISSING"
        print(f"  apks/{apk:30s}: {size}")

    scrcpy_jar = RUNTIME_DIR / "scrcpy-server"
    scrcpy_size = f"{scrcpy_jar.stat().st_size:,} bytes" if scrcpy_jar.exists() else "MISSING — chay: python download_bundle.py --scrcpy-only"
    print(f"  runtime/scrcpy-server (server-side)  : {scrcpy_size}")

    print("=" * 55)
    print()
    print("Tiep theo — copy bundle len dien thoai (chon 1 trong 2 cach):")
    print()
    print("  [ADB — Mode A: Termux agent tren dien thoai]")
    print("    adb push bundle/ /data/data/com.termux/files/home/")
    print("    adb push scripts/agent_local.py scripts/setup_agent.py /data/data/com.termux/files/home/")
    print("    # Tren Termux:")
    print("    pip install websockets pillow")
    print("    python agent_local.py --server ws://<SERVER_IP>:8081/device-agent --auto-setup")
    print()
    print("  [Mode B: ADB Transport — server ket noi thang vao dien thoai]")
    print("    export SCRCPY_JAR=$(pwd)/runtime/scrcpy-server")
    print("    python main.py")
    print()


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Tai truoc bundle minitouch/APK cho Device Farm Agent"
    )
    ap.add_argument(
        "--abi",
        choices=["arm64", "arm32", "x86_64", "x86", "all"],
        default="all",
        help="Chi tai ABI nhat dinh (mac dinh: all)",
    )
    ap.add_argument("--no-minitouch",  action="store_true", help="Bo qua minitouch")
    ap.add_argument("--no-u2",         action="store_true", help="Bo qua uiautomator2")
    ap.add_argument("--no-stf",        action="store_true", help="Bo qua STFService")
    ap.add_argument("--no-scrcpy",     action="store_true", help="Bo qua scrcpy-server JAR")
    ap.add_argument("--scrcpy-only",   action="store_true", help="Chi tai scrcpy-server JAR")
    args = ap.parse_args()

    abi_map = {
        "arm64":  ["arm64-v8a"],
        "arm32":  ["armeabi-v7a"],
        "x86_64": ["x86_64"],
        "x86":    ["x86"],
        "all":    MINITOUCH_ABIS,
    }
    abis = abi_map[args.abi]

    print("=" * 55)
    print("Device Farm — Download Bundle")
    print(f"Output: {BUNDLE_DIR}")
    print("=" * 55)

    if args.scrcpy_only:
        download_scrcpy_server()
        print_summary()
        return

    if not args.no_minitouch:
        download_minitouch(abis)

    if not args.no_u2:
        download_uiautomator2()

    if not args.no_stf:
        download_stfservice()

    if not args.no_scrcpy:
        download_scrcpy_server()

    print_summary()


if __name__ == "__main__":
    main()
