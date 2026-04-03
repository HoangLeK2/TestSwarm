"""agent-boot/main.py — Local ADB bootstrap agent (chạy 1 lần).

Chạy trên máy tính có USB / WiFi ADB tới thiết bị.
KHÔNG deploy lên cloud — chỉ dùng 1 lần để cài đặt + cấp quyền lần đầu.

Luồng:
  1. (Tuỳ chọn) Bật adb tcpip 5555 để device kết nối WiFi cloud sau này
  2. Cài uiautomator2 APKs (app-uiautomator + app-uiautomator-test)
  3. Push + khởi động atx-agent daemon (port 7912) — quản lý u2 lifecycle tự động
  4. Cài STFService.apk
  5. Cấp quyền cho STFService (WRITE_SECURE_SETTINGS, READ_PHONE_STATE)
  6. Mở STFService IdentityActivity → user scan QR ws:// cloud

atx-agent (bước 3):
  - Binary Go chạy liên tục trên device, tự restart u2 khi process chết.
  - Farm server kết nối thẳng device_ip:7912 — không cần WS tunnel cho u2.
  - Sau reboot: atx-agent KHÔNG tự khởi động lại → cần chạy lại bước này.
    (Hoặc thêm atx-agent vào boot script trên device.)

Từ lần sau (không reboot):
  - Chỉ cần mở app STFService trên điện thoại → tự kết nối cloud WS.
  - Không cần chạy lại agent này (trừ khi reboot/reset/cài lại điện thoại).

Usage:
  uv run main.py                          # boot tất cả thiết bị song song
  uv run main.py --serial 192.168.1.10:5555  # chỉ boot 1 thiết bị
  uv run main.py --apk /path/to/STFService.apk
  uv run main.py --skip-tcpip --skip-stf
  uv run main.py --skip-atx              # bỏ qua push atx-agent (đã chạy sẵn)
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tarfile
import time
import threading
import urllib.request
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

# atx-agent
_ATX_AGENT_VERSION = "0.10.1"
_ATX_AGENT_REMOTE  = "/data/local/tmp/atx-agent"
_ATX_AGENT_PORT_HEX = "1EE8"  # 7912 decimal
_ATX_BUNDLE_DIR    = _DEVICE_FARM / "bundle" / "atx-agent"


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


def _list_serials() -> list[str]:
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
    return sorted(devices, key=lambda s: (0 if ":5555" in s else 1, 0 if "." in s else 1, s))


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


# ── atx-agent Helpers ─────────────────────────────────────────────────────────

def _get_device_abi(serial: str) -> str:
    """Trả về arm64, arm, x86_64 hoặc x86 dựa trên ro.product.cpu.abi."""
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
    """Tải atx-agent binary từ GitHub releases, cache vào bundle/atx-agent/.

    Bảo mật:
    - Chỉ extract regular file (isfile()), bỏ symlink/hardlink/device node.
    - Dùng tarfile filter="data" (Python 3.12+) để block path traversal.
    - urlopen với timeout=120s để không hang vô thời hạn.
    """
    # Go arch naming
    # Filename format: atx-agent_{version}_linux_{go_arch}.tar.gz
    # ARM 32-bit devices use "armv7" in filename (not "arm")
    go_arch = {"arm64": "arm64", "arm": "armv7", "x86_64": "amd64", "x86": "386"}.get(abi, "arm64")
    version = _ATX_AGENT_VERSION
    filename = f"atx-agent_{version}_linux_{go_arch}.tar.gz"
    url = f"https://github.com/openatx/atx-agent/releases/download/{version}/{filename}"

    dest = _atx_agent_local(abi)
    if dest.is_file() and dest.stat().st_size > 0:
        return dest

    _ATX_BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _ATX_BUNDLE_DIR / filename

    print(f"      Tải atx-agent v{version} ({go_arch}) từ GitHub…")
    try:
        with urllib.request.urlopen(url, timeout=120) as resp:
            with open(tmp, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
    except Exception as e:
        print(f"      ✗ Tải thất bại: {e}\n"
              f"        URL: {url}\n"
              f"        Tải thủ công rồi đặt vào: {dest}",
              file=sys.stderr)
        tmp.unlink(missing_ok=True)
        return None

    try:
        with tarfile.open(tmp) as tf:
            # Chỉ lấy regular file tên kết thúc "atx-agent" — bỏ symlink/hardlink
            member = next(
                (m for m in tf.getmembers()
                 if m.name.endswith("atx-agent") and m.isfile()),
                None,
            )
            if member is None:
                raise RuntimeError("atx-agent regular-file binary không tìm thấy trong archive")
            member.name = "atx-agent"  # strip any directory prefix
            # filter="data" (Python 3.12+): block absolute paths, "..", symlink targets
            try:
                tf.extract(member, _ATX_BUNDLE_DIR, filter="data")
            except TypeError:
                # Python < 3.12: filter kwarg chưa có — extract thủ công sau khi đã
                # validate member.isfile() và member.name (đã set ở trên)
                tf.extract(member, _ATX_BUNDLE_DIR)
        (_ATX_BUNDLE_DIR / "atx-agent").rename(dest)
        print(f"      ✓ Đã lưu: {dest}")
    except Exception as e:
        print(f"      ✗ Giải nén thất bại: {e}", file=sys.stderr)
        dest.unlink(missing_ok=True)
        return None
    finally:
        tmp.unlink(missing_ok=True)

    return dest


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

_U2_RUNNER = "androidx.test.runner.AndroidJUnitRunner"


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


def step_push_atx_agent(serial: str, skip: bool) -> bool:
    """
    Push atx-agent binary lên device và khởi động daemon trên port 7912.

    atx-agent tự quản lý vòng đời của uiautomator2-server:
    - Tự start am instrument khi cần
    - Tự restart khi u2 chết
    Farm server kết nối thẳng device_ip:7912 thay vì qua WS tunnel.

    Lưu ý: atx-agent KHÔNG tự khởi động sau reboot. Cần chạy lại bước này.
    """
    if skip:
        print(f"\n[3/{TOTAL_STEPS}] Bỏ qua push atx-agent (--skip-atx hoặc --skip-u2).")
        return False

    print(f"\n[3/{TOTAL_STEPS}] Push + khởi động atx-agent (port 7912)…")

    if not _is_pkg_installed(_U2_TEST_PKG, serial):
        print(
            f"      ✗ {_U2_TEST_PKG} chưa cài — atx-agent cần APK này để start u2.\n"
            "        Đảm bảo bước 2 thành công trước.",
            file=sys.stderr,
        )
        return False

    abi = _get_device_abi(serial)
    print(f"      CPU ABI: {abi}")

    binary = _atx_agent_local(abi)
    if not (binary.is_file() and binary.stat().st_size > 0):
        binary = _download_atx_agent(abi)
    if binary is None:
        return False

    # Push binary lên device
    r = _adb("push", str(binary), _ATX_AGENT_REMOTE, serial=serial, check=False, timeout=30)
    if r.returncode != 0:
        print(f"      ✗ adb push thất bại: {(r.stdout + r.stderr).strip()[:200]}", file=sys.stderr)
        return False
    _adb_shell(f"chmod 755 {_ATX_AGENT_REMOTE}", serial=serial)
    print(f"      ✓ Đã push {binary.name} lên {_ATX_AGENT_REMOTE}")

    # Dừng instance cũ (nếu có)
    _adb_shell(f"{_ATX_AGENT_REMOTE} server --stop 2>/dev/null; sleep 0.3", serial=serial)

    # Khởi động daemon
    _adb_shell(f"{_ATX_AGENT_REMOTE} server -d 2>/dev/null", serial=serial)

    # Chờ tối đa 15s cho port 7912 (0x1EE8)
    for i in range(15):
        time.sleep(1)
        tcp = _adb_shell(
            f"cat /proc/net/tcp6 /proc/net/tcp 2>/dev/null"
            f" | grep -i ':{_ATX_AGENT_PORT_HEX}' | head -1 || true",
            serial=serial,
        )
        if tcp.strip():
            print(f"      ✓ atx-agent daemon đang chạy trên :7912")
            return True

    print(
        f"      ⚠ atx-agent chưa sẵn sàng sau 15s.\n"
        f"        Kiểm tra log: adb -s {serial} shell {_ATX_AGENT_REMOTE} server",
        file=sys.stderr,
    )
    return False


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


# ── Per-device bootstrap ──────────────────────────────────────────────────────

_print_lock = threading.Lock()


def _pprint(*msg: str) -> None:
    """Thread-safe print."""
    with _print_lock:
        print(*msg)


def boot_device(serial: str, args: argparse.Namespace, stf_apk: Path | None) -> bool:
    """Bootstrap một thiết bị. Trả về True nếu thành công."""
    sdk   = _get_sdk(serial)
    model = _adb_shell("getprop ro.product.model", serial=serial)

    with _print_lock:
        print("=" * 60)
        print(f"[agent-boot] [{serial}] Bắt đầu bootstrap")
        print(f"  Model  : {model}")
        print(f"  SDK    : {sdk}")
        print("=" * 60)

    try:
        if not args.skip_tcpip:
            step_tcpip(serial, args.tcpip_port)
        else:
            _pprint(f"\n[1/{TOTAL_STEPS}] [{serial}] Bỏ qua adb tcpip (--skip-tcpip).")

        step_install_u2(serial, skip=args.skip_u2)
        step_push_atx_agent(serial, skip=args.skip_u2 or args.skip_atx)
        step_install_stf(serial, stf_apk, skip=args.skip_stf)
        step_grant_permissions(serial, skip=args.skip_stf)
        step_open_app(serial, skip=args.skip_stf)

        with _print_lock:
            print()
            print(f"[agent-boot] [{serial}] ✅ Hoàn tất bootstrap")
        return True
    except Exception as e:
        with _print_lock:
            print(f"[agent-boot] [{serial}] ✗ Lỗi: {e}", file=sys.stderr)
        return False


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Agent boot — cài uiautomator2/STFService + cấp quyền 1 lần.\n"
            "Mặc định boot TẤT CẢ thiết bị song song.\n"
            "Dùng --serial để chỉ boot 1 thiết bị cụ thể."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--serial", "-s",
                        help="ADB serial thiết bị (bỏ qua = boot tất cả)")
    parser.add_argument("--apk",
                        help="Đường dẫn STFService.apk (bỏ qua = tự tìm)")
    parser.add_argument("--tcpip-port", type=int, default=5555, metavar="PORT",
                        help="Port cho adb tcpip (mặc định: 5555)")
    parser.add_argument("--skip-tcpip", action="store_true",
                        help="Bỏ qua bước adb tcpip")
    parser.add_argument("--skip-u2", action="store_true",
                        help="Bỏ qua cài uiautomator2 APKs và push atx-agent")
    parser.add_argument("--skip-atx", action="store_true",
                        help="Bỏ qua push atx-agent (APKs vẫn được cài)")
    parser.add_argument("--skip-stf", action="store_true",
                        help="Bỏ qua cài STFService, cấp quyền và mở app")
    args = parser.parse_args()

    serials = [args.serial] if args.serial else _list_serials()
    stf_apk = _find_stf_apk(args.apk)

    if len(serials) > 1:
        print(f"[agent] Boot {len(serials)} thiết bị song song: {serials}")
    else:
        print(f"[agent] Boot thiết bị: {serials[0]}")

    results: dict[str, bool] = {}
    if len(serials) == 1:
        results[serials[0]] = boot_device(serials[0], args, stf_apk)
    else:
        threads = [
            threading.Thread(
                target=lambda s=s: results.__setitem__(s, boot_device(s, args, stf_apk)),
                daemon=True,
            )
            for s in serials
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    ok = all(results.values())
    failed = [s for s, v in results.items() if not v]

    print()
    print("=" * 60)
    if ok:
        print("[agent-boot] ✅ Tất cả thiết bị đã bootstrap xong")
    else:
        print(f"[agent-boot] ⚠ Một số thiết bị thất bại: {failed}")
    print()
    print("Bước tiếp theo: trên điện thoại mở STFService → quét mã QR từ dashboard")
    print("Lần sau: chỉ cần mở app STFService → quét QR để kết nối.")
    print("=" * 60)


if __name__ == "__main__":
    main()
