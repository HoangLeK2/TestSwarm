#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import uiautomator2 as u2


@dataclass(frozen=True)
class Step:
    name: str
    fn: Callable[[], None]


def _safe_serial_for_path(serial: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in serial)


def _adb_devices(adb_path: str) -> list[str]:
    import subprocess

    out = subprocess.run(
        [adb_path, "devices"], capture_output=True, text=True, timeout=10
    ).stdout
    serials: list[str] = []
    for line in out.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", errors="replace")


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
    # Không đụng gì tới Wi‑Fi; chỉ auto đóng một số dialog cơ bản.
    w = d.watcher
    w("auto_ok").when("OK").click()
    w("auto_ok_vi").when("ĐỒNG Ý").click()
    w("auto_allow").when("Allow").click()
    w("auto_continue").when("Tiếp tục").click()
    w.start()


def _stop_watchers(d: u2.Device) -> None:
    try:
        d.watcher.stop()
    except Exception:
        pass


def _capture_artifacts(d: u2.Device, out_dir: Path, tag: str) -> None:
    _ensure_dir(out_dir)
    ts = int(time.time() * 1000)

    try:
        _write_text(out_dir / f"{ts}_{tag}_app_current.json", str(d.app_current()))
    except Exception as exc:
        _write_text(out_dir / f"{ts}_{tag}_app_current.err.txt", repr(exc))

    try:
        xml = d.dump_hierarchy(compressed=False)
        _write_text(out_dir / f"{ts}_{tag}.xml", xml)
    except Exception as exc:
        _write_text(out_dir / f"{ts}_{tag}_hierarchy.err.txt", repr(exc))

    try:
        d.screenshot(str(out_dir / f"{ts}_{tag}.png"))
    except Exception as exc:
        _write_text(out_dir / f"{ts}_{tag}_screenshot.err.txt", repr(exc))


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Offline uiautomator2 scenario: không cần Wi‑Fi, chỉ thao tác UI cơ bản."
    )
    ap.add_argument("--serial", default="", help="ADB serial (USB) hoặc ip:port nếu bạn đã tự adb connect.")
    ap.add_argument("--adb", default=os.environ.get("ADB", "adb"), help="adb path (default: adb)")
    ap.add_argument("--artifacts", default="artifacts_offline", help="output dir cho artifacts")
    ap.add_argument(
        "--app-pkg",
        default="com.android.settings",
        help="app để mở và đi vài bước (default: Settings, không cần mạng).",
    )
    ap.add_argument(
        "--rotate",
        action="store_true",
        help="cycle orientation portrait → landscape → portrait trong kịch bản (mặc định tắt).",
    )
    args = ap.parse_args(argv)

    serial = args.serial.strip()
    if not serial:
        serials = _adb_devices(args.adb)
        if not serials:
            print("No adb devices in 'device' state. Run: adb devices", file=sys.stderr)
            return 2
        serial = serials[0]

    out_dir = Path(args.artifacts) / _safe_serial_for_path(serial)
    _ensure_dir(out_dir)

    print(f"[u2-offline] connecting to {serial}", flush=True)
    d = u2.connect(serial)

    d.implicitly_wait(10.0)
    d.settings["wait_timeout"] = 20.0
    d.settings["operation_delay"] = (0, 0.1)

    _install_watchers(d)
    try:
        try:
            if not d.screen_on():
                d.screen_on()
        except Exception:
            pass
        try:
            d.unlock()
        except Exception:
            pass

        steps: list[Step] = []

        def step(name: str):
            def _wrap(fn: Callable[[], None]) -> Callable[[], None]:
                steps.append(Step(name=name, fn=fn))
                return fn

            return _wrap

        @step("home")
        def _home() -> None:
            d.press("home")
            time.sleep(0.8)
            _capture_artifacts(d, out_dir, "home")

        @step("open_notifications_and_quicksettings")
        def _notif() -> None:
            d.open_notification()
            time.sleep(1.0)
            _capture_artifacts(d, out_dir, "notifications")
            d.press("back")
            time.sleep(0.5)

        @step("launch_offline_app")
        def _launch() -> None:
            pkg = args.app_pkg
            # dùng monkey để hoạt động trên hầu hết ROM, không cần mạng.
            d.app_start(pkg, use_monkey=True)
            ok = _wait_until(lambda: d.app_current().get("package") == pkg, timeout_s=15.0)
            if not ok:
                _capture_artifacts(d, out_dir, "app_timeout")
                raise RuntimeError(f"App {pkg} không lên foreground, current={d.app_current()}")
            _capture_artifacts(d, out_dir, "app_launched")

        @step("basic_scroll")
        def _scroll() -> None:
            for i in range(2):
                d.swipe_ext("up", scale=0.8)
                time.sleep(0.6)
                _capture_artifacts(d, out_dir, f"scroll_{i}")

        @step("recents_and_back")
        def _recents() -> None:
            d.press("recent")
            time.sleep(0.8)
            _capture_artifacts(d, out_dir, "recents")
            d.press("back")
            time.sleep(0.5)

        @step("orientation_cycle_offline")
        def _rotate() -> None:
            if not args.rotate:
                return
            orig = d.orientation
            try:
                d.set_orientation("l")
                time.sleep(1.0)
                _capture_artifacts(d, out_dir, "rot_landscape")
                d.set_orientation("n")
                time.sleep(1.0)
                _capture_artifacts(d, out_dir, "rot_portrait")
            finally:
                try:
                    d.set_orientation(orig)
                except Exception:
                    pass

        @step("final_home")
        def _final() -> None:
            for _ in range(3):
                d.press("back")
                time.sleep(0.3)
            d.press("home")
            time.sleep(0.8)
            _capture_artifacts(d, out_dir, "final_home")

        for s in steps:
            print(f"[u2-offline] step: {s.name}", flush=True)
            try:
                s.fn()
            except Exception as exc:
                _capture_artifacts(d, out_dir, f"FAILED_{s.name}")
                print(f"[u2-offline] FAILED step={s.name}: {exc}", file=sys.stderr)
                return 1

        print("[u2-offline] OK: scenario finished", flush=True)
        return 0
    finally:
        _stop_watchers(d)


if __name__ == "__main__":
    raise SystemExit(main())

