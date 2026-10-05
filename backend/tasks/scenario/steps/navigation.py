"""Step handlers: launch_app, stop_app, clear_app, wait_app, push_file, pull_file, open_url, install_apk, key, scroll."""
from __future__ import annotations

import asyncio
import logging
import os
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


def _cancelled(sc: ScenarioContext) -> bool:
    return sc.cancel_event is not None and sc.cancel_event.is_set()


def _mark_cancelled(result: Dict[str, Any], message: str) -> None:
    result["ok"] = False
    result["message"] = message
    result["cancelled"] = True


def _wait_or_cancel(sc: ScenarioContext, seconds: float) -> bool:
    if seconds <= 0:
        return _cancelled(sc)
    if sc.cancel_event is not None:
        return bool(sc.cancel_event.wait(seconds))
    time.sleep(seconds)
    return False


def _poll_u2_ready(device: Any, serial: str, pkg: str, cancel_event: Any = None) -> bool:
    _u2_poll_start = time.monotonic()
    while time.monotonic() - _u2_poll_start < 8.0:
        if cancel_event is not None and cancel_event.is_set():
            return False
        if getattr(device, "_u2", None) is not None:
            return True
        if cancel_event is not None:
            cancel_event.wait(0.5)
        else:
            time.sleep(0.5)
    if getattr(device, "_u2", None) is None:
        log.warning("[%s] launch_app %s: u2 not ready after 8s poll", serial, pkg)
        return False
    return True


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


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, min_value: int = 1, max_value: int = 1000) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return _bounded_int(raw, default, min_value=min_value, max_value=max_value)


def _is_comment_scroll_target(step: Dict[str, Any], by: str, value: str) -> bool:
    """Whether this scroll_to is hunting a comment entry point.

    Purely a property of the selector: any app whose comment affordance is
    labelled "comment"/"bình luận" qualifies. No package allow-list — a scroll
    that misses its target gets the same retry budget on every platform.
    """
    raw_value = str(step.get("value") or value or "").strip().lower()
    raw_by = str(step.get("by") or by or "").strip().lower()
    if not raw_value or raw_by not in {"description", "descriptionstartswith", "text"}:
        return False
    return "bình luận" in raw_value or "comment" in raw_value


def _mark_comment_target_found(sc: ScenarioContext, result: Dict[str, Any]) -> None:
    sc.ctx.pop("_pending_scroll_target", None)
    result["comment_target_missing"] = False


def _mark_pending_scroll_target(
    sc: ScenarioContext,
    result: Dict[str, Any],
    *,
    selector: str,
    requested_max_swipes: int,
    effective_max_swipes: int,
    swipes_done: int,
) -> None:
    marker = {
        "selector": selector,
        "max_swipes_requested": requested_max_swipes,
        "max_swipes_effective": effective_max_swipes,
        "swipes_done": swipes_done,
    }
    sc.ctx["_pending_scroll_target"] = marker
    result["comment_target_missing"] = True
    result["comment_target_missing_detail"] = marker


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
def handle_launch_app(
    sc: ScenarioContext,
    step: Dict[str, Any],
    idx: int,
    result: Dict[str, Any],
) -> None:
    pkg, component = parse_step_package(step)
    if not pkg:
        result["ok"] = False
        result["message"] = "launch_app: empty package/component"
        return
    raw_fallbacks = (
        step.get("package_fallbacks") or step.get("packageFallbacks") or []
    )
    if isinstance(raw_fallbacks, str):
        package_fallbacks = [raw_fallbacks]
    elif isinstance(raw_fallbacks, (list, tuple, set)):
        package_fallbacks = [str(value) for value in raw_fallbacks]
    else:
        package_fallbacks = []
    raw_adb_fallback = step.get("adb_fallback", step.get("adbFallback", True))
    adb_fallback = str(raw_adb_fallback).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    try:
        sc.device.launch_app(
            pkg,
            component=component or None,
            stop_before=bool(step.get("stop_before") or step.get("stop")),
            use_monkey=bool(step.get("use_monkey")),
            package_fallbacks=package_fallbacks,
            adb_fallback=adb_fallback,
        )
        if _cancelled(sc):
            _mark_cancelled(result, "launch_app: cancelled by user")
            return
        launch_wait = float(step.get("wait_after", 2.0) or 2.0)
        if _wait_or_cancel(sc, launch_wait):
            _mark_cancelled(result, "launch_app: cancelled by user")
            return
        log.info("[%s] launch_app %s: waited %ss", sc.serial, pkg, launch_wait)
        if not _poll_u2_ready(sc.device, sc.serial, pkg, sc.cancel_event) and _cancelled(sc):
            _mark_cancelled(result, "launch_app: cancelled by user")
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
    verify_package = str(step.get("verify_package") or "").strip() or None
    try:
        sc.device.install(source, timeout=timeout, verify_package=verify_package)
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
        if sc.cancel_event is not None and sc.cancel_event.is_set():
            result["ok"] = False
            result["message"] = "scroll_down: cancelled by user"
            result["cancelled"] = True
            break
        log.info(f"[{sc.serial}] scroll swipe #{i + 1}: ({sx},{sy1})→({sx},{sy2})")
        try:
            sc.device.swipe(sx, sy1, sx, sy2, duration_ms=duration_ms)
        except Exception as exc:
            result["ok"] = False
            result["message"] = f"swipe scroll #{i + 1} failed: {exc}"
            failed = True
            break
        pause_s = max(0.1, pause_seconds)
        if sc.cancel_event is not None:
            sc.cancel_event.wait(pause_s)
        else:
            time.sleep(pause_s)
    if not failed:
        result["ok"] = not bool(result.get("cancelled"))


@register_step("scroll_to")
def handle_scroll_to(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    from tasks.scenario.utils import resolve_step_selector_fields
    from services.scenario_selector import selector_summary, spec_to_agent_payload

    spec, by, value, _ = resolve_step_selector_fields(step)
    direction = str(step.get("direction", "down") or "down")
    max_swipes = int(step.get("max_swipes", 5) or 5)
    requested_max_swipes = max_swipes
    if spec is None or spec.is_empty():
        result["ok"] = False
        result["message"] = "scroll_to: empty selector"
        return
    lbl = selector_summary(spec)
    is_comment_target = _is_comment_scroll_target(step, by, value)
    pending_post = sc.ctx.get("_pending_scroll_target")
    if (
        is_comment_target
        and isinstance(pending_post, dict)
        and pending_post.get("reason_code") == "post_extract_pending"
    ):
        result["skipped"] = True
        result["comment_target_missing"] = True
        result["comment_target_missing_detail"] = pending_post
        result["message"] = "scroll_to: skipped — current post extract not ready"
        return
    if is_comment_target:
        comment_cap = _env_int(
            "COMMENT_SCROLL_TO_MAX_SWIPES",
            8,
            min_value=1,
            max_value=max(1, requested_max_swipes),
        )
        max_swipes = min(max_swipes, comment_cap)
        if max_swipes != requested_max_swipes:
            result["scroll_to_max_swipes_requested"] = requested_max_swipes
            result["scroll_to_max_swipes_effective"] = max_swipes

    flow = getattr(sc.device, "u2_flow", None)
    if (
        callable(flow)
        and _env_bool("SCROLL_TO_U2_FLOW_ENABLED", True)
        and not _cancelled(sc)
    ):
        flow_direction = {
            "down": "up",
            "up": "down",
            "left": "left",
            "right": "right",
        }.get(direction, "up")
        swipe_duration_s = float(step.get("scroll_duration_s", 0.12) or 0.12)
        settle_s = max(0.0, float(step.get("scroll_settle_s", 0.35) or 0.35))
        # The step's configured wait belongs to the first probe: the target is
        # usually already on screen and the screen is usually still rendering.
        # Answering "no" at timeout=0 scrolls a present target out of view.
        first_wait_s = max(0.0, min(30.0, float(step.get("timeout", 0.0) or 0.0)))
        # Each iteration costs a swipe, the settle that lets the fling stop, and
        # one presence probe. Budget for all of them or the flow times out
        # mid-scroll and the step reports "not found" while still moving.
        flow_budget_s = max(
            5.0,
            first_wait_s + max_swipes * (swipe_duration_s + settle_s + 0.7) + 2.0,
        )
        try:
            flow_started = time.monotonic()
            flow_result = flow(
                "swipe_until_found",
                {
                    "selector": {"spec": spec_to_agent_payload(spec)},
                    "direction": flow_direction,
                    "max_swipes": max_swipes,
                    "step_ratio": float(step.get("scroll_step_ratio", 0.4) or 0.4),
                    "duration": swipe_duration_s,
                    "settle_s": settle_s,
                    "first_wait_s": first_wait_s,
                    "width": sc.w,
                    "height": sc.h,
                },
                timeout=float(step.get("scroll_to_timeout_s", flow_budget_s) or flow_budget_s),
            )
            found = bool(flow_result.get("found"))
            swipes_done = int(flow_result.get("swipes") or 0)
            # Which mechanism actually scrolled — "uiscrollable" drove the real
            # container, "blind_swipe" fell back to screen-centre coordinates.
            # Without this a failure log cannot tell the two apart.
            scroll_driver = str(flow_result.get("driver") or "u2_flow")
            exhausted = bool(flow_result.get("exhausted"))
            result["scroll_to_driver"] = scroll_driver
            result["scroll_to_flow_ms"] = round((time.monotonic() - flow_started) * 1000.0, 1)
            result["scroll_to_swipes"] = swipes_done
            if exhausted:
                result["scroll_to_exhausted"] = True
            if found:
                if is_comment_target:
                    _mark_comment_target_found(sc, result)
                result["message"] = (
                    f"scroll_to found {lbl} after {swipes_done} swipe(s) "
                    f"[{scroll_driver}]"
                )
            else:
                result["ok"] = False
                if is_comment_target:
                    _mark_pending_scroll_target(
                        sc,
                        result,
                        selector=lbl,
                        requested_max_swipes=requested_max_swipes,
                        effective_max_swipes=max_swipes,
                        swipes_done=swipes_done,
                    )
                reason = "list exhausted" if exhausted else f"{max_swipes} swipes"
                result["message"] = (
                    f"scroll_to {lbl} not found after {reason} [{scroll_driver}]"
                )
            return
        except Exception as exc:
            result["scroll_to_flow_error"] = str(exc)[:200]

    sx = sc.w // 2
    if direction == "up":
        sy1, sy2 = int(sc.h * 0.3), int(sc.h * 0.7)
    else:
        sy1, sy2 = int(sc.h * 0.7), int(sc.h * 0.3)
    found = False
    swipes_done = 0
    # Same rule as the flow path: the configured wait belongs to the first probe.
    fallback_first_wait_s = max(0.0, min(30.0, float(step.get("timeout", 0.0) or 0.0)))
    for i in range(max_swipes):
        if sc.cancel_event is not None and sc.cancel_event.is_set():
            result["ok"] = False
            result["message"] = "scroll_to: cancelled by user"
            result["cancelled"] = True
            break
        probe_timeout = fallback_first_wait_s if i == 0 else 0
        try:
            u2 = sc.device.u2
            if u2 is not None:
                if hasattr(u2, "find_element_spec"):
                    hit = u2.find_element_spec(spec, timeout=probe_timeout) is not None
                else:
                    hit = u2.find_element(by, value, timeout=probe_timeout) is not None
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
        if sc.cancel_event is not None:
            sc.cancel_event.wait(0.3)
        else:
            time.sleep(0.3)
        swipes_done = i + 1
    if result.get("cancelled"):
        return
    if not found:
        result["ok"] = False
        if is_comment_target:
            _mark_pending_scroll_target(
                sc,
                result,
                selector=lbl,
                requested_max_swipes=requested_max_swipes,
                effective_max_swipes=max_swipes,
                swipes_done=swipes_done,
            )
        result["message"] = f"scroll_to {lbl} not found after {max_swipes} swipes"
    else:
        if is_comment_target:
            _mark_comment_target_found(sc, result)
        result["message"] = f"scroll_to found {lbl} after {swipes_done} swipe(s)"
