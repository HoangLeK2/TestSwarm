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


def _maybe_adb_connect(adb_path: str, serial: str, timeout: int = 10) -> None:
    import subprocess

    if ":" not in serial:
        return
    if serial in _adb_devices(adb_path):
        return
    subprocess.run(
        [adb_path, "connect", serial], capture_output=True, text=True, timeout=timeout
    )
    time.sleep(0.3)


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
    # Advanced: combine a few chained conditions via watchers,
    # but still keep it generic. This auto-accepts permission dialogs, terms, etc.
    w = d.watcher
    w("auto_allow").when("允许").click()
    w("auto_allow_en").when("Allow").click()
    w("auto_ok").when("OK").click()
    w("auto_ok_vi").when("ĐỒNG Ý").click()
    w("auto_continue").when("Tiếp tục").click()
    w("auto_continue_en").when("Continue").click()
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
        description="More complex uiautomator2 scenario: launch app, navigate UI, scroll, search, rotate, toggle wifi."
    )
    ap.add_argument("--serial", default="", help="ADB serial or ip:port. Empty = first device.")
    ap.add_argument("--adb", default=os.environ.get("ADB", "adb"), help="adb path (default: adb)")
    ap.add_argument("--artifacts", default="artifacts_complex", help="output dir for artifacts")
    ap.add_argument(
        "--app-pkg",
        default="com.android.settings",
        help="target app package (default: Android Settings, đổi thành app của bạn nếu muốn).",
    )
    ap.add_argument(
        "--search-text",
        default="Wi‑Fi",
        help="text để thử tìm trong UI (ví dụ Wi‑Fi / Cài đặt / tên feature trong app).",
    )
    ap.add_argument(
        "--rotate",
        action="store_true",
        help="cycle orientation portrait → landscape → portrait trong kịch bản.",
    )
    args = ap.parse_args(argv)

    serial = args.serial.strip()
    if serial:
        _maybe_adb_connect(args.adb, serial)
    else:
        serials = _adb_devices(args.adb)
        if not serials:
            print("No adb devices in 'device' state. Run: adb devices", file=sys.stderr)
            return 2
        serial = serials[0]

    out_dir = Path(args.artifacts) / _safe_serial_for_path(serial)
    _ensure_dir(out_dir)

    print(f"[u2-complex] connecting to {serial}", flush=True)
    d = u2.connect(serial)

    d.implicitly_wait(10.0)
    d.settings["wait_timeout"] = 20.0
    d.settings["operation_delay"] = (0, 0.1)

    _install_watchers(d)
    try:
        # Ensure screen on + unlock
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
        def _() -> None:
            d.press("home")
            time.sleep(0.8)
            _capture_artifacts(d, out_dir, "home")

        @step("launch_app")
        def _() -> None:
            pkg = args.app_pkg
            d.app_start(pkg, use_monkey=True)
            if not _wait_until(lambda: d.app_current().get("package") == pkg, timeout_s=20.0):
                _capture_artifacts(d, out_dir, "launch_timeout")
                raise RuntimeError(f"App {pkg} không lên foreground, current={d.app_current()}")
            _capture_artifacts(d, out_dir, "app_launched")

        @step("scroll_pages")
        def _() -> None:
            # Dùng swipe_ext để scroll vài lần, chụp artifact mỗi lần.
            for i in range(3):
                d.swipe_ext("up", scale=0.8)
                time.sleep(0.6)
                _capture_artifacts(d, out_dir, f"scroll_{i}")

        @step("search_text_if_possible")
        def _() -> None:
            target = args.search_text
            if not target:
                return

            edit = d(className="android.widget.EditText")
            if edit.exists:
                edit.set_text(target)
                d.press("enter")
                time.sleep(1.0)
                _capture_artifacts(d, out_dir, "search_edittext")
            else:
                node = d(textContains="Tìm") | d(textContains="Search") | d(
                    descriptionContains="Search"
                )
                if node.exists:
                    node.click()
                    time.sleep(0.4)
                    d.send_keys(target)
                    d.press("enter")
                    time.sleep(1.0)
                    _capture_artifacts(d, out_dir, "search_generic")

        @step("orientation_cycle")
        def _() -> None:
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

        @step("toggle_wifi_via_shell")
        def _() -> None:
            def _wifi_state() -> str:
                out = d.shell(["cmd", "wifi", "status"]).output
                return out

            before = _wifi_state()
            d.shell(["svc", "wifi", "disable"])
            time.sleep(1.5)
            mid = _wifi_state()
            d.shell(["svc", "wifi", "enable"])
            time.sleep(1.5)
            after = _wifi_state()
            text = f"BEFORE:\n{before}\n\nMID:\n{mid}\n\nAFTER:\n{after}\n"
            _write_text(out_dir / "wifi_toggle.txt", text)
            _capture_artifacts(d, out_dir, "wifi_toggled")

        @step("back_to_home")
        def _() -> None:
            for _i in range(3):
                d.press("back")
                time.sleep(0.3)
            d.press("home")
            time.sleep(0.8)
            _capture_artifacts(d, out_dir, "final_home")

        for s in steps:
            print(f"[u2-complex] step: {s.name}", flush=True)
            try:
                s.fn()
            except Exception as exc:
                _capture_artifacts(d, out_dir, f"FAILED_{s.name}")
                print(f"[u2-complex] FAILED step={s.name}: {exc}", file=sys.stderr)
                return 1

        print("[u2-complex] OK: scenario finished", flush=True)
        return 0
    finally:
        _stop_watchers(d)


if __name__ == "__main__":
    raise SystemExit(main())

