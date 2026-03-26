"""agent-boot/main.py — Local ADB bootstrap agent (chạy 1 lần).

Chạy trên máy tính có USB / WiFi ADB tới thiết bị.
KHÔNG deploy lên cloud — chỉ dùng 1 lần để cài đặt + cấp quyền lần đầu.

Luồng:
  1. (Tuỳ chọn) Bật adb tcpip 5555 để device kết nối WiFi cloud sau này
  2. Cài uiautomator2 APKs (app-uiautomator + app-uiautomator-test)
  3. Boot uiautomator2 server (am instrument, port 9008) — cần ADB
  4. Cài STFService.apk
  5. Cấp quyền cho STFService (WRITE_SECURE_SETTINGS, READ_PHONE_STATE)
  6. Mở STFService IdentityActivity → user scan QR ws:// cloud

Tại sao cần boot u2 qua ADB (bước 3):
  - am instrument yêu cầu shell UID — Android app không thể tự gọi.
  - STFService chỉ kết nối vào u2 server đang chạy sẵn, không tự khởi động.
  - Khi device reboot → cần chạy lại agent-boot (hoặc chạy lệnh adb riêng).

Từ lần sau (không reboot):
  - Chỉ cần mở app STFService trên điện thoại → tự kết nối cloud WS.
  - Không cần chạy lại agent này (trừ khi reboot/reset/cài lại điện thoại).

Usage:
  uv run main.py
  uv run main.py --serial 192.168.1.10:5555
  uv run main.py --apk /path/to/STFService.apk
  uv run main.py --skip-tcpip --skip-stf
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────

_ROOT        = Path(__file__).resolve().parent          # agent-boot/
_FARM_ROOT   = _ROOT.parent                             # deviceFarmer/
_DEVICE_FARM = _FARM_ROOT / "device_farm"

# uiautomator2 APKs (có sẵn trong device_farm/third_party/ hoặc bundle/apks/)
_U2_APK_SEARCH_DIRS = [
    _DEVICE_FARM / "third_party",
    _DEVICE_FARM / "bundle" / "apks",
    _ROOT,                                              # agent-boot/ (nếu user copy vào đây)
]

# STFService APK candidates (theo thứ tự ưu tiên)
_STF_APK_CANDIDATES = [
    _ROOT / "STFService.apk",                           # agent-boot/STFService.apk (manual copy)
    _FARM_ROOT / "device_farm" / "bundle" / "apks" / "STFService.apk",
    # Build outputs (nếu đã build Android project)
    _FARM_ROOT / "STFService.apk" / "app" / "build" / "outputs" / "apk" / "full" / "release" / "app-release.apk",
    _FARM_ROOT / "STFService.apk" / "app" / "build" / "outputs" / "apk" / "full" / "debug" / "app-debug.apk",
    _FARM_ROOT / "STFService.apk" / "app" / "build" / "outputs" / "apk" / "lite" / "debug" / "app-debug.apk",
    _FARM_ROOT / "STFService.apk" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk",
]

# Package names
_U2_PKG      = "com.github.uiautomator"
_U2_TEST_PKG = "com.github.uiautomator.test"
_STF_PKG     = "jp.co.cyberagent.stf"


# ── ADB Helpers ───────────────────────────────────────────────────────────────

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


def _pick_serial() -> str:
    result = _run(["adb", "devices"], check=False)
    lines = result.stdout.strip().splitlines()[1:]
    devices = [
        l.split()[0]
        for l in lines
        if l.strip() and l.split()[-1] == "device"
    ]
    if not devices:
        raise SystemExit(
            "[agent] Không tìm thấy thiết bị ADB nào.\n"
            "  → Cắm USB và bật USB Debugging,\n"
            "    hoặc kết nối qua WiFi: adb connect <ip>:5555"
        )
    if len(devices) > 1:
        # Prefer wireless debugging targets by default (matches farm workflow).
        # Override by passing --serial explicitly.
        preferred = sorted(
            devices,
            key=lambda s: (0 if ":5555" in s else 1, 0 if "." in s else 1, s),
        )
        devices = preferred
        print(f"[agent] Nhiều thiết bị: {devices}")
        print(f"[agent] Dùng thiết bị ưu tiên: {devices[0]}")
        print("[agent] (Dùng --serial để chọn thiết bị khác)")
    return devices[0]


def _get_sdk(serial: str) -> int:
    sdk = _adb_shell("getprop ro.build.version.sdk", serial=serial)
    try:
        return int(sdk.strip())
    except ValueError:
        return 0


def _is_pkg_installed(pkg: str, serial: str) -> bool:
    out = _adb_shell(f"pm path {pkg}", serial=serial)
    return "package:" in out


def _adb_install(apk_path: Path, serial: str, label: str, extra_flags: list[str] | None = None) -> bool:
    """adb install -r [-t] <apk> — return True on success."""
    flags = ["-r"] + (extra_flags or [])
    r = _adb("install", *flags, str(apk_path), serial=serial, check=False, timeout=120)
    out = (r.stdout + r.stderr).strip()
    # adb install: exit 0 on success; sometimes prints "Success", sometimes just returns 0
    ok = r.returncode == 0 and "Failure" not in out and "Exception" not in out
    if ok:
        print(f"      ✓ {label} cài thành công")
    else:
        print(f"      ✗ {label} cài thất bại (rc={r.returncode}): {out[:300]}", file=sys.stderr)
    return ok


# ── Asset Finders ─────────────────────────────────────────────────────────────

def _find_u2_apks() -> tuple[Path | None, Path | None]:
    """Tìm app-uiautomator.apk và app-uiautomator-test.apk."""
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


def _find_stf_apk(override: str | None = None) -> Path | None:
    if override:
        p = Path(override)
        if p.is_file():
            return p
        raise SystemExit(f"[agent] --apk không tồn tại: {p}")

    for p in _STF_APK_CANDIDATES:
        if p.is_file() and p.stat().st_size > 0:
            return p
    return None


# ── Steps ─────────────────────────────────────────────────────────────────────

TOTAL_STEPS = 6

_REMOTE_U2_LOG = "/data/local/tmp/u2.log"
_U2_RUNNER     = "androidx.test.runner.AndroidJUnitRunner"


def step_tcpip(serial: str, port: int) -> None:
    print(f"\n[1/{TOTAL_STEPS}] (Tuỳ chọn) Bật adb tcpip {port} để WiFi cloud kết nối lại sau…")
    try:
        _adb("tcpip", str(port), serial=serial, check=False, timeout=10)
        time.sleep(2)
        print(f"      ✓ adb tcpip {port} OK")
    except Exception as e:
        print(f"      ⚠ adb tcpip thất bại ({e}) — bỏ qua.", file=sys.stderr)


def step_install_u2(serial: str, skip: bool) -> bool:
    """Cài uiautomator2 APKs (main + test)."""
    if skip:
        print(f"\n[2/6] Bỏ qua uiautomator2 APKs (--skip-u2).")
        return False

    print(f"\n[2/6] Cài uiautomator2 APKs…")

    main_installed = _is_pkg_installed(_U2_PKG, serial)
    test_installed = _is_pkg_installed(_U2_TEST_PKG, serial)

    if main_installed and test_installed:
        print(f"      ✓ uiautomator2 APKs đã cài sẵn — bỏ qua.")
        return True

    main_apk, test_apk = _find_u2_apks()
    if main_apk is None or test_apk is None:
        missing = []
        if main_apk is None:
            missing.append("app-uiautomator.apk")
        if test_apk is None:
            missing.append("app-uiautomator-test.apk")
        print(
            f"      ✗ Không tìm thấy APKs: {', '.join(missing)}\n"
            f"        Tìm kiếm trong: {[str(d) for d in _U2_APK_SEARCH_DIRS]}\n"
            "        → Chạy: python ../device_farm/download_bundle.py --no-minitouch --no-stf --no-scrcpy",
            file=sys.stderr,
        )
        return False

    ok = True
    if not main_installed:
        ok &= _adb_install(main_apk, serial, _U2_PKG)
    else:
        print(f"      ✓ {_U2_PKG} đã cài — bỏ qua")

    if not test_installed:
        # -t flag bắt buộc cho test APK trên Android ≥ 29
        ok &= _adb_install(test_apk, serial, _U2_TEST_PKG, extra_flags=["-t"])
    else:
        print(f"      ✓ {_U2_TEST_PKG} đã cài — bỏ qua")

    return ok


def step_boot_u2(serial: str, skip: bool) -> None:
    """
    Start uiautomator2 server qua ADB (am instrument, port 9008).
    Cần ADB vì am instrument yêu cầu shell UID — Android app không thể tự gọi.
    """
    if skip:
        print(f"\n[3/{TOTAL_STEPS}] Bỏ qua boot uiautomator2 (--skip-u2).")
        return

    print(f"\n[3/{TOTAL_STEPS}] Boot uiautomator2 server (port 9008)…")

    if not _is_pkg_installed(_U2_TEST_PKG, serial):
        print(
            f"      ✗ {_U2_TEST_PKG} chưa cài — bỏ qua boot u2.\n"
            "        Cài APK trước (bước 2) rồi chạy lại.",
            file=sys.stderr,
        )
        return

    # Kill tiến trình cũ nếu còn
    _adb_shell(f"am force-stop {_U2_TEST_PKG}", serial=serial)
    time.sleep(0.5)

    # Start uiautomator2 server dưới background (am instrument -w block cho đến khi done)
    subprocess.Popen(
        ["adb", "-s", serial, "shell",
         f"am instrument -w {_U2_TEST_PKG}/{_U2_RUNNER}"
         f" </dev/null >{_REMOTE_U2_LOG} 2>&1"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Chờ tối đa 12s cho port 9008
    for i in range(12):
        time.sleep(1)
        tcp = _adb_shell(
            "cat /proc/net/tcp6 /proc/net/tcp 2>/dev/null | grep -i ':2330' | head -1 || true",
            serial=serial,
        )
        if tcp.strip():
            print(f"      ✓ uiautomator2 server đang chạy trên :9008")
            return

    u2_log = _adb_shell(f"cat {_REMOTE_U2_LOG} 2>/dev/null | tail -10 || true", serial=serial)
    print(
        f"      ⚠ uiautomator2 chưa khởi động sau 12s.\n"
        f"        Log:\n{u2_log[:400]}",
        file=sys.stderr,
    )


def step_install_stf(serial: str, apk_path: Path | None, skip: bool) -> bool:
    """Cài STFService.apk."""
    if skip:
        print(f"\n[4/{TOTAL_STEPS}] Bỏ qua STFService (--skip-stf).")
        return False

    print(f"\n[4/{TOTAL_STEPS}] Cài STFService.apk…")

    if apk_path is None:
        print(
            "      ✗ Không tìm thấy STFService.apk.\n"
            "        Options:\n"
            f"          A) Copy prebuilt APK vào: {_ROOT / 'STFService.apk'}\n"
            "          B) Build Android project: cd ../STFService.apk && ./gradlew assembleFullDebug\n"
            "             APK output: app/build/outputs/apk/full/debug/app-debug.apk\n"
            "          C) Dùng --skip-stf nếu app đã cài sẵn trên máy",
            file=sys.stderr,
        )
        return False

    if _is_pkg_installed(_STF_PKG, serial):
        print(f"      ✓ {_STF_PKG} đã cài — bỏ qua")
        return True

    print(f"      Nguồn: {apk_path}")
    return _adb_install(apk_path, serial, "STFService")


def step_grant_permissions(serial: str, skip: bool) -> None:
    """Cấp quyền đặc biệt cho STFService (cần ADB, chỉ làm 1 lần)."""
    if skip:
        print(f"\n[5/{TOTAL_STEPS}] Bỏ qua cấp quyền (--skip-stf).")
        return

    print(f"\n[5/{TOTAL_STEPS}] Cấp quyền cho STFService…")

    if not _is_pkg_installed(_STF_PKG, serial):
        print(f"      ✗ {_STF_PKG} chưa cài — bỏ qua cấp quyền.", file=sys.stderr)
        return

    perms = [
        "android.permission.WRITE_SECURE_SETTINGS",
        "android.permission.READ_PHONE_STATE",
    ]
    for perm in perms:
        out = _adb_shell(f"pm grant {_STF_PKG} {perm}", serial=serial)
        # pm grant thành công thì output trống
        if out and "Exception" in out:
            print(f"      ⚠ pm grant {perm} có lỗi: {out[:200]}", file=sys.stderr)
        else:
            print(f"      ✓ {perm}")


def step_open_app(serial: str, skip: bool) -> None:
    """Mở STFService (đã custom WS) → user quét QR từ dashboard để kết nối cloud. Không cần Termux."""
    if skip:
        print(f"\n[6/{TOTAL_STEPS}] Bỏ qua mở STFService (--skip-stf).")
        return

    print(f"\n[6/{TOTAL_STEPS}] Mở STFService…")
    _adb("shell", "am", "start", "-n", f"{_STF_PKG}/.IdentityActivity", "-a", "android.intent.action.MAIN", serial=serial, check=False, timeout=10)
    print("      ✓ Đã mở app STFService (IdentityActivity)")

    print()
    print("  ══════════════════════════════════════════════════")
    print("  Bước tiếp theo — trên điện thoại:")
    print("  ══════════════════════════════════════════════════")
    print("  1. Mở dashboard trên PC: http://<BACKEND_IP>:3000 (hoặc :8081)")
    print("  2. Vào Quản lý thiết bị → Đăng ký / Pair device → hiện mã QR")
    print("  3. Trong app STFService: bấm quét QR → quét mã → cho phép quay màn hình")
    print("  4. App sẽ kết nối WebSocket tới backend (STFService đã tích hợp WS, không cần Termux)")
    print("  ══════════════════════════════════════════════════")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Agent boot — cài uiautomator2/STFService + cấp quyền 1 lần.\n"
            "Từ lần sau chỉ cần mở app STFService → tự kết nối cloud.\n"
            "STFService tự khởi động uiautomator2 và minitouch agent."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--serial", "-s",
                        help="ADB serial thiết bị (bỏ qua = tự phát hiện)")
    parser.add_argument("--apk",
                        help="Đường dẫn STFService.apk (bỏ qua = tự tìm)")
    parser.add_argument("--tcpip-port", type=int, default=5555, metavar="PORT",
                        help="Port cho adb tcpip (mặc định: 5555)")
    parser.add_argument("--skip-tcpip", action="store_true",
                        help="Bỏ qua bước adb tcpip")
    parser.add_argument("--skip-u2", action="store_true",
                        help="Bỏ qua cài uiautomator2 APKs")
    parser.add_argument("--skip-stf", action="store_true",
                        help="Bỏ qua cài STFService, cấp quyền và mở app")
    args = parser.parse_args()

    serial = args.serial or _pick_serial()
    sdk    = _get_sdk(serial)
    model  = _adb_shell("getprop ro.product.model", serial=serial)

    print("=" * 60)
    print("[agent-boot] Bắt đầu bootstrap thiết bị")
    print(f"  Serial : {serial}")
    print(f"  Model  : {model}")
    print(f"  SDK    : {sdk}")
    print("=" * 60)

    # Step 1: tcpip
    if not args.skip_tcpip:
        step_tcpip(serial, args.tcpip_port)
    else:
        print(f"\n[1/{TOTAL_STEPS}] Bỏ qua adb tcpip (--skip-tcpip).")

    # Step 2: install u2 APKs
    step_install_u2(serial, skip=args.skip_u2)

    # Step 3: boot uiautomator2 server (requires ADB shell, app cannot do this)
    step_boot_u2(serial, skip=args.skip_u2)

    # Step 4: install STFService
    stf_apk = _find_stf_apk(args.apk)
    step_install_stf(serial, stf_apk, skip=args.skip_stf)

    # Step 5: grant permissions
    step_grant_permissions(serial, skip=args.skip_stf)

    # Step 6: open STFService IdentityActivity
    step_open_app(serial, skip=args.skip_stf)

    # Summary
    print()
    print("=" * 60)
    print("[agent-boot] ✅ Hoàn tất bootstrap lần đầu")
    print()
    print("Bước tiếp theo: trên điện thoại mở STFService → quét mã QR từ dashboard")
    print("(STFService đã tích hợp WebSocket, không cần Termux hay agent_local trên máy.)")
    print()
    print("Lần sau: chỉ cần mở app STFService → quét QR để kết nối.")
    print("(Chạy lại agent-boot chỉ khi reset/cài lại điện thoại)")
    print("=" * 60)


if __name__ == "__main__":
    main()
