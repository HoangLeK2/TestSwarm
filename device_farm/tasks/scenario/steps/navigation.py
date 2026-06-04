"""Step handlers: launch_app, stop_app, clear_app, wait_app, push_file, pull_file, open_url, install_apk, key, scroll."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict

from tasks.scenario.app_package import parse_step_package
from tasks.scenario.steps import register_step
from tasks.scenario.context import ScenarioContext

log = logging.getLogger(__name__)

_ADB_SHELL_DEFAULT_TIMEOUT_S = 30.0
_ADB_SHELL_MAX_TIMEOUT_S = 120.0
_ADB_SHELL_DEFAULT_MAX_OUTPUT_CHARS = 8000
_ADB_SHELL_MAX_OUTPUT_CHARS = 50000


def _poll_u2_ready(device: Any, serial: str, pkg: str) -> None:
    _u2_poll_start = time.monotonic()
    while time.monotonic() - _u2_poll_start < 8.0:
        if getattr(device, "_u2", None) is not None:
            break
        time.sleep(0.5)
    if getattr(device, "_u2", None) is None:
        log.warning("[%s] launch_app %s: u2 not ready after 8s poll", serial, pkg)


def _bounded_float(raw: Any, default: float, *, min_value: float, max_value: float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = default
    return min(max_value, max(min_value, value))


def _bounded_int(raw: Any, default: int, *, min_value: int, max_value: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return min(max_value, max(min_value, value))


def _truncate_output(output: str, limit: int) -> tuple[str, bool]:
    if len(output) <= limit:
        return output, False
    return output[:limit], True


def _output_preview(output: str, limit: int = 160) -> str:
    preview = " ".join(line.strip() for line in output.splitlines() if line.strip())
    if len(preview) <= limit:
        return preview
    return preview[:limit] + "..."


def _resolve_relay_serial(device: Any, fallback_serial: str) -> str:
    resolver = getattr(device, "_resolve_relay_serial", None)
    if callable(resolver):
        resolved = resolver()
        if resolved:
            return str(resolved)
    return str(
        getattr(device, "_adb_serial", None)
        or getattr(device, "serial", None)
        or fallback_serial
    )


@register_step("launch_app")
def handle_launch_app(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    pkg, component = parse_step_package(step)
    if not pkg:
        result["ok"] = False
        result["message"] = "launch_app: empty package/component"
        return
    try:
        sc.device.launch_app(
            pkg,
            component=component or None,
            stop_before=bool(step.get("stop_before") or step.get("stop")),
            use_monkey=bool(step.get("use_monkey")),
        )
        launch_wait = float(step.get("wait_after", 2.0) or 2.0)
        time.sleep(launch_wait)
        log.info("[%s] launch_app %s: waited %ss", sc.serial, pkg, launch_wait)
        _poll_u2_ready(sc.device, sc.serial, pkg)
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"launch_app({pkg}) failed: {exc}"


@register_step("stop_app")
def handle_stop_app(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    pkg, _ = parse_step_package(step)
    if not pkg:
        result["ok"] = False
        result["message"] = "stop_app: empty package"
        return
    try:
        sc.device.stop_app(pkg)
        log.info("[%s] stop_app %s", sc.serial, pkg)
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"stop_app({pkg}) failed: {exc}"


@register_step("clear_app")
def handle_clear_app(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    pkg, _ = parse_step_package(step)
    if not pkg:
        result["ok"] = False
        result["message"] = "clear_app: empty package"
        return
    try:
        sc.device.clear_app(pkg)
        log.info("[%s] clear_app %s", sc.serial, pkg)
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"clear_app({pkg}) failed: {exc}"


@register_step("wait_app")
def handle_wait_app(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    pkg, _ = parse_step_package(step)
    if not pkg:
        result["ok"] = False
        result["message"] = "wait_app: empty package"
        return
    timeout = float(step.get("timeout", 20.0) or 20.0)
    front = bool(step.get("front", True))
    try:
        ok = sc.device.wait_app(pkg, front=front, timeout=timeout)
        if not ok:
            result["ok"] = False
            result["message"] = f"wait_app({pkg}): not in foreground within {timeout}s"
        else:
            result["message"] = f"wait_app({pkg}): foreground ok"
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"wait_app({pkg}) failed: {exc}"


@register_step("push_file")
def handle_push_file(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    local_path = str(step.get("local_path") or step.get("src") or "").strip()
    remote_path = str(step.get("remote_path") or step.get("dst") or "").strip()
    if not local_path or not remote_path:
        result["ok"] = False
        result["message"] = "push_file: local_path and remote_path required"
        return
    try:
        mode = step.get("mode")
        sc.device.push_file(local_path, remote_path, mode=mode)
        log.info("[%s] push_file %s -> %s", sc.serial, local_path, remote_path)
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"push_file failed: {exc}"


@register_step("pull_file")
def handle_pull_file(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    remote_path = str(step.get("remote_path") or step.get("src") or "").strip()
    local_path = str(step.get("local_path") or step.get("dst") or "").strip()
    if not local_path or not remote_path:
        result["ok"] = False
        result["message"] = "pull_file: local_path and remote_path required"
        return
    try:
        sc.device.pull_file(remote_path, local_path)
        log.info("[%s] pull_file %s -> %s", sc.serial, remote_path, local_path)
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"pull_file failed: {exc}"


@register_step("open_url")
def handle_open_url(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    url = str(step.get("url") or "").strip()
    if not url:
        result["ok"] = False
        result["message"] = "open_url: empty url"
    else:
        pkg = (step.get("package") or "").strip() or "com.android.chrome"
        try:
            sc.device.open_url(url, package=pkg)
        except Exception as exc:
            result["ok"] = False
            result["message"] = f"open_url failed: {exc}"


@register_step("install_apk")
def handle_install_apk(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    source = str(step.get("url") or step.get("apk_url") or "").strip()
    if not source:
        result["ok"] = False
        result["message"] = "install_apk: empty url"
        return
    try:
        timeout = float(step.get("timeout", 90.0) or 90.0)
    except (TypeError, ValueError):
        timeout = 90.0
    timeout = min(600.0, max(10.0, timeout))
    try:
        sc.device.install(source, timeout=timeout)
        log.info("[%s] install_apk ok: %s", sc.serial, source)
        result["message"] = f"install_apk: ok ({source})"
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"install_apk failed: {exc}"


@register_step("key")
def handle_key(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    key = str(step.get("key") or "")
    if not key:
        result["ok"] = False
        result["message"] = "key: empty key"
    else:
        try:
            sc.device.key(key)
        except Exception as exc:
            result["ok"] = False
            result["message"] = f"key({key}) failed: {exc}"


@register_step("adb_shell")
def handle_adb_shell(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    command = str(step.get("command") or step.get("cmd") or "").strip()
    if not command:
        result["ok"] = False
        result["message"] = "adb_shell: empty command"
        return

    timeout = _bounded_float(
        step.get("timeout"),
        _ADB_SHELL_DEFAULT_TIMEOUT_S,
        min_value=1.0,
        max_value=_ADB_SHELL_MAX_TIMEOUT_S,
    )
    max_output_chars = _bounded_int(
        step.get("max_output_chars"),
        _ADB_SHELL_DEFAULT_MAX_OUTPUT_CHARS,
        min_value=1000,
        max_value=_ADB_SHELL_MAX_OUTPUT_CHARS,
    )
    fail_on_error = bool(step.get("fail_on_error", True))
    save_as = str(step.get("save_as") or "").strip()

    try:
        from runtime.transports.adb_relay_server import get_relay_manager
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"adb_shell: relay manager unavailable: {exc}"
        return

    relay = get_relay_manager()
    loop = getattr(sc.device, "_loop", None)
    target_serial = _resolve_relay_serial(sc.device, sc.serial)
    if relay is None or loop is None or not target_serial:
        result["ok"] = False
        result["message"] = "adb_shell: no agent-boot relay loop available"
        return

    actual_serial = relay.resolve_serial(target_serial)
    if relay.relay_for_serial(actual_serial) is None:
        result["ok"] = False
        result["message"] = f"adb_shell: no relay for serial={actual_serial!r}"
        return

    try:
        fut = asyncio.run_coroutine_threadsafe(
            relay.run_command(actual_serial, command, timeout),
            loop,
        )
        relay_result = fut.result(timeout=timeout + 10.0) or {}
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"adb_shell failed: {exc}"
        return

    output = str(relay_result.get("output") or "")
    truncated_output, was_truncated = _truncate_output(output, max_output_chars)
    exit_code = int(relay_result.get("exit_code", 0) or 0)
    ok = bool(relay_result.get("ok", False))
    error = str(relay_result.get("error") or "")

    result["exit_code"] = exit_code
    result["output"] = truncated_output
    result["output_truncated"] = was_truncated
    result["relay_serial"] = actual_serial
    preview = _output_preview(truncated_output)
    result["message"] = (
        f"adb_shell exit={exit_code}"
        + (f" · {preview}" if preview else "")
        + (f" output_truncated={max_output_chars}" if was_truncated else "")
    )

    if save_as:
        sc.var_ctx.set(save_as, truncated_output)
        sc.ctx.setdefault("vars", {})[save_as] = truncated_output
        result["save_as"] = save_as

    if not ok and fail_on_error:
        result["ok"] = False
        result["message"] = error or truncated_output or f"adb_shell exit={exit_code}"
    elif not ok:
        result["ok"] = True
        result["message"] = (
            f"adb_shell ignored failure exit={exit_code}: "
            f"{error or truncated_output or 'no output'}"
        )


@register_step("scroll_down")
def handle_scroll_down(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    try:
        repeats = int(step.get("repeats", 1) or 1)
    except Exception:
        repeats = 1
    try:
        start_y_ratio = float(step.get("start_y_ratio", 0.65))
    except Exception:
        start_y_ratio = 0.65
    try:
        end_y_ratio = float(step.get("end_y_ratio", 0.47))
    except Exception:
        end_y_ratio = 0.47
    try:
        duration_ms = int(step.get("duration_ms", 520) or 520)
    except Exception:
        duration_ms = 520
    try:
        pause_seconds = float(step.get("pause_seconds", 0.6) or 0.6)
    except Exception:
        pause_seconds = 0.6
    try:
        start_x_ratio = float(step.get("start_x_ratio", 0.5) or 0.5)
    except Exception:
        start_x_ratio = 0.5

    start_y_ratio = min(0.95, max(0.55, start_y_ratio))
    end_y_ratio = min(0.75, max(0.1, end_y_ratio))
    if end_y_ratio >= start_y_ratio:
        end_y_ratio = max(0.1, start_y_ratio - 0.22)

    start_x_ratio = min(0.95, max(0.05, start_x_ratio))
    sx = int(sc.w * start_x_ratio)
    sy1 = int(sc.h * start_y_ratio)
    sy2 = int(sc.h * end_y_ratio)
    failed = False
    for i in range(max(1, repeats)):
        log.info(f"[{sc.serial}] scroll swipe #{i + 1}: ({sx},{sy1})→({sx},{sy2})")
        try:
            sc.device.swipe(sx, sy1, sx, sy2, duration_ms=duration_ms)
        except Exception as exc:
            result["ok"] = False
            result["message"] = f"swipe scroll #{i + 1} failed: {exc}"
            failed = True
            break
        time.sleep(max(0.1, pause_seconds))
    if not failed:
        result["ok"] = True


@register_step("scroll_to")
def handle_scroll_to(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    from tasks.scenario.utils import resolve_step_selector_fields
    from services.scenario_selector import selector_summary

    spec, by, value, _ = resolve_step_selector_fields(step)
    direction = str(step.get("direction", "down") or "down")
    max_swipes = int(step.get("max_swipes", 5) or 5)
    if spec is None or spec.is_empty():
        result["ok"] = False
        result["message"] = "scroll_to: empty selector"
        return
    lbl = selector_summary(spec)

    sx = sc.w // 2
    if direction == "up":
        sy1, sy2 = int(sc.h * 0.3), int(sc.h * 0.7)
    else:
        sy1, sy2 = int(sc.h * 0.7), int(sc.h * 0.3)
    found = False
    swipes_done = 0
    for i in range(max_swipes):
        try:
            u2 = sc.device.u2
            if u2 is not None:
                if hasattr(u2, "find_element_spec"):
                    hit = u2.find_element_spec(spec, timeout=0) is not None
                else:
                    hit = u2.find_element(by, value, timeout=0) is not None
                if hit:
                    found = True
                    swipes_done = i
                    break
        except Exception:
            pass
        try:
            sc.device.swipe(sx, sy1, sx, sy2, duration_ms=500)
        except Exception:
            pass
        time.sleep(0.3)
        swipes_done = i + 1
    if not found:
        result["ok"] = False
        result["message"] = f"scroll_to {lbl} not found after {max_swipes} swipes"
    else:
        result["message"] = f"scroll_to found {lbl} after {swipes_done} swipe(s)"
