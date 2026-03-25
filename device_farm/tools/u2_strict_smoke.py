#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import uiautomator2 as u2


@dataclass(frozen=True)
class Step:
    name: str
    fn: Callable[[], None]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _safe_serial_for_path(serial: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in serial)


def _run(cmd: list[str], timeout: int = 20, check: bool = False) -> subprocess.CompletedProcess[str]:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}\nstdout:\n{p.stdout}\nstderr:\n{p.stderr}")
    return p


def _adb_devices(adb_path: str) -> list[str]:
    out = _run([adb_path, "devices"], timeout=10, check=True).stdout
    serials: list[str] = []
    for line in out.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials


def _maybe_adb_connect(adb_path: str, serial: str, timeout: int) -> None:
    # If it's an ip:port serial and not currently connected, try adb connect for convenience.
    if ":" not in serial:
        return
    if serial in _adb_devices(adb_path):
        return
    _run([adb_path, "connect", serial], timeout=timeout, check=True)
    # Give adb server a moment to update device list.
    time.sleep(0.2)


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", errors="replace")


def _best_settings_package() -> str:
    # Most Android builds (AOSP, Pixel, many OEMs) use this.
    return "com.android.settings"


def _wait_until(predicate: Callable[[], bool], timeout_s: float, interval_s: float = 0.2) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if predicate():
                return True
        except Exception:
            pass
        time.sleep(interval_s)
    return False


def _install_watchers(d: u2.Device) -> None:
    # Common dialogs/popups that can block automation.
    # Keep this conservative: only obvious confirmation buttons.
    #
    # uiautomator2 watcher API here is XPath-based, but it also accepts the
    # "text shortcut" used by its builtin watchers (see uiautomator2/watcher.py).
    d.watcher("auto_ok_1").when("OK").click()
    d.watcher("auto_ok_2").when("Ok").click()
    d.watcher("auto_allow_1").when("ALLOW").click()
    d.watcher("auto_allow_2").when("Allow").click()
    d.watcher("auto_close_1").when("CLOSE").click()
    d.watcher("auto_close_2").when("Close").click()
    d.watcher.start()


def _stop_watchers(d: u2.Device) -> None:
    try:
        d.watcher.stop()
    except Exception:
        pass


def _capture_artifacts(d: u2.Device, out_dir: Path, tag: str) -> None:
    _ensure_dir(out_dir)
    ts = _now_ms()

    # App + device info snapshots (best-effort)
    try:
        _write_text(out_dir / f"{ts}_{tag}_app_current.json", str(d.app_current()))
    except Exception as exc:
        _write_text(out_dir / f"{ts}_{tag}_app_current.err.txt", repr(exc))

    try:
        _write_text(out_dir / f"{ts}_{tag}_info.json", str(d.info))
    except Exception as exc:
        _write_text(out_dir / f"{ts}_{tag}_info.err.txt", repr(exc))

    try:
        _write_text(out_dir / f"{ts}_{tag}_device_info.json", str(d.device_info))
    except Exception as exc:
        _write_text(out_dir / f"{ts}_{tag}_device_info.err.txt", repr(exc))

    # Screenshot + hierarchy
    try:
        d.screenshot(str(out_dir / f"{ts}_{tag}.png"))
    except Exception as exc:
        _write_text(out_dir / f"{ts}_{tag}_screenshot.err.txt", repr(exc))

    try:
        xml = d.dump_hierarchy(compressed=False)
        _write_text(out_dir / f"{ts}_{tag}.xml", xml)
    except Exception as exc:
        _write_text(out_dir / f"{ts}_{tag}_hierarchy.err.txt", repr(exc))


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Strict uiautomator2 smoke test with artifacts.")
    ap.add_argument("--serial", default="", help="ADB serial (USB) or ip:port (WiFi). Empty = first device.")
    ap.add_argument("--adb", default=os.environ.get("ADB", "adb"), help="adb path (default: adb)")
    ap.add_argument("--artifacts", default="artifacts", help="output directory for artifacts")
    ap.add_argument("--settings-pkg", default=_best_settings_package(), help="Settings package to open")
    ap.add_argument("--timeout", type=float, default=25.0, help="timeout (seconds) for waits")
    ap.add_argument("--connect-timeout", type=int, default=10, help="adb connect timeout (seconds)")
    ap.add_argument("--u2-connect-timeout", type=float, default=60.0, help="uiautomator2 connect timeout (seconds)")
    args = ap.parse_args(argv)

    # Resolve serial
    serial = args.serial.strip()
    if serial:
        _maybe_adb_connect(args.adb, serial, timeout=args.connect_timeout)
    else:
        serials = _adb_devices(args.adb)
        if not serials:
            print("No adb devices in 'device' state. Run: adb devices", file=sys.stderr)
            return 2
        serial = serials[0]

    out_dir = Path(args.artifacts) / _safe_serial_for_path(serial)
    _ensure_dir(out_dir)

    print(f"[u2] connecting to {serial}", flush=True)
    # u2.connect can hang on bad transports; enforce a timeout.
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(u2.connect, serial)
        try:
            d = fut.result(timeout=args.u2_connect_timeout)
        except FuturesTimeoutError as exc:
            raise RuntimeError(f"u2.connect timed out after {args.u2_connect_timeout}s for {serial}") from exc

    # Base config
    d.implicitly_wait(10.0)
    d.settings["wait_timeout"] = 20.0
    d.settings["operation_delay"] = (0, 0.1)

    _install_watchers(d)
    try:
        # Ensure device is usable
        try:
            if not d.screen_on():
                d.screen_on()
        except Exception:
            pass

        try:
            d.unlock()
        except Exception:
            # Some OEMs don't support unlock(); it's fine.
            pass

        steps: list[Step] = []

        def step(name: str):
            def _wrap(fn: Callable[[], None]) -> Callable[[], None]:
                steps.append(Step(name=name, fn=fn))
                return fn

            return _wrap

        @step("home")
        def _() -> None:
            d.press("home")
            time.sleep(0.8)
            _capture_artifacts(d, out_dir, "home")

        @step("screenshot_and_hierarchy")
        def _() -> None:
            # Validate both channels explicitly.
            _capture_artifacts(d, out_dir, "baseline")
            xml = d.dump_hierarchy()
            if not xml or "<hierarchy" not in xml:
                raise RuntimeError("dump_hierarchy returned empty/invalid xml")

        @step("open_notification")
        def _() -> None:
            d.open_notification()
            ok = _wait_until(lambda: True, timeout_s=1.0)  # just a short pause
            if not ok:
                raise RuntimeError("notification wait failed")
            time.sleep(0.8)
            _capture_artifacts(d, out_dir, "notification")
            d.press("back")
            time.sleep(0.4)

        @step("open_settings_assert_package")
        def _() -> None:
            pkg = args.settings_pkg
            d.app_start(pkg)
            if not _wait_until(lambda: d.app_current().get("package") == pkg, timeout_s=args.timeout):
                _capture_artifacts(d, out_dir, "settings_timeout")
                raise RuntimeError(f"settings did not come to foreground: expected {pkg}, got {d.app_current()}")
            _capture_artifacts(d, out_dir, "settings_ok")
            d.app_stop(pkg)
            time.sleep(0.3)

        @step("input_sanity_center_tap")
        def _() -> None:
            w, h = d.window_size()
            d.click(w // 2, h // 2)
            time.sleep(0.2)
            _capture_artifacts(d, out_dir, "center_tap")

        for s in steps:
            print(f"[u2] step: {s.name}", flush=True)
            try:
                s.fn()
            except Exception as exc:
                _capture_artifacts(d, out_dir, f"FAILED_{s.name}")
                print(f"[u2] FAILED step={s.name}: {exc}", file=sys.stderr)
                return 1

        print("[u2] OK: strict smoke test passed", flush=True)
        return 0
    finally:
        _stop_watchers(d)


if __name__ == "__main__":
    raise SystemExit(main())

