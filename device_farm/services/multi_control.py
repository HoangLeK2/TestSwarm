from __future__ import annotations

import asyncio
import os
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Iterable


SIMPLE_ACTIONS = {
    "tap",
    "tap_ratio",
    "swipe",
    "swipe_ratio",
    "double_tap",
    "double_tap_ratio",
    "long_tap",
    "long_tap_ratio",
    "drag",
    "drag_ratio",
    "pinch",
    "pinch_ratio",
    "swipe_ext",
    "key",
    "screen_on",
    "screen_off",
    "unlock",
}
HEAVY_ACTIONS = {
    "tap_selector",
    "input_text",
    "launch_app",
    "open_url",
}
SUPPORTED_ACTIONS = SIMPLE_ACTIONS | HEAVY_ACTIONS


def _env_int(name: str, default: int, *, min_value: int = 1, max_value: int = 100) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except Exception:
        value = default
    return max(min_value, min(max_value, value))


def _now_ms() -> int:
    return int(time.monotonic() * 1000)


def _clamp_ratio(value: Any) -> float:
    try:
        ratio = float(value)
    except Exception:
        return 0.0
    return max(0.0, min(1.0, ratio))


def _device_state_name(device: Any) -> str:
    state = getattr(device, "state", "")
    return str(state or "").replace("DeviceState.", "").upper()


def _unique_serials(serials: Iterable[Any], max_devices: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in serials:
        serial = str(raw or "").strip()
        if not serial or serial in seen:
            continue
        seen.add(serial)
        out.append(serial)
        if len(out) >= max_devices:
            break
    return out


class MultiControlCoordinator:
    """Backend fan-out for manual multi-device control.

    The coordinator keeps the browser path thin: frontend submits one action in
    ratio/selector form, and backend handles per-device guards, scaling,
    bounded fan-out, timeout, and per-device result reporting.
    """

    def __init__(
        self,
        manager: Any,
        *,
        simple_concurrency_per_relay: int | None = None,
        heavy_concurrency_per_relay: int | None = None,
        max_devices: int | None = None,
        default_timeout_ms: int | None = None,
    ) -> None:
        self.manager = manager
        self.simple_concurrency_per_relay = simple_concurrency_per_relay or _env_int(
            "MULTI_CONTROL_SIMPLE_CONCURRENCY_PER_RELAY", 10, min_value=1, max_value=50
        )
        self.heavy_concurrency_per_relay = heavy_concurrency_per_relay or _env_int(
            "MULTI_CONTROL_HEAVY_CONCURRENCY_PER_RELAY", 4, min_value=1, max_value=20
        )
        self.max_devices = max_devices or _env_int(
            "MULTI_CONTROL_MAX_DEVICES", 50, min_value=1, max_value=200
        )
        self.default_timeout_ms = default_timeout_ms or _env_int(
            "MULTI_CONTROL_DEFAULT_TIMEOUT_MS", 2500, min_value=100, max_value=60_000
        )
        self._executor = ThreadPoolExecutor(
            max_workers=_env_int(
                "MULTI_CONTROL_MAX_WORKERS", 32, min_value=1, max_value=200
            ),
            thread_name_prefix="multi-control",
        )
        self._semaphores: dict[tuple[str, str], asyncio.Semaphore] = {}

    async def execute(
        self,
        payload: dict[str, Any],
        *,
        allowed_serials: set[str] | None = None,
        read_only: bool = False,
    ) -> dict[str, Any]:
        request_id = str(payload.get("request_id") or "").strip()
        serials = _unique_serials(payload.get("serials") or [], self.max_devices)
        action = payload.get("action") if isinstance(payload.get("action"), dict) else {}
        action_type = str(action.get("type") or "").strip()
        timeout_ms = self._timeout_ms(payload, action)

        if not request_id:
            request_id = f"multi-{_now_ms()}"

        if read_only:
            return self._top_level_error(request_id, serials, "read_only")
        if not serials:
            return self._top_level_error(request_id, serials, "no_serials")
        if action_type not in SUPPORTED_ACTIONS:
            return self._top_level_error(request_id, serials, "unsupported_action")

        prepared: list[tuple[str, Any, str] | dict[str, Any]] = []
        for serial in serials:
            if allowed_serials is not None and serial not in allowed_serials:
                prepared.append(self._result(serial, False, error="not_allowed"))
                continue
            device = self.manager.get_device(serial)
            if device is None:
                prepared.append(self._result(serial, False, error="not_found"))
                continue
            busy_error = self._busy_error(device)
            if busy_error:
                prepared.append(self._result(serial, False, error=busy_error))
                continue
            prepared.append((serial, device, self._relay_key(device, serial)))

        result_by_serial: dict[str, dict[str, Any]] = {}
        groups: dict[str, list[tuple[str, Any]]] = defaultdict(list)
        for item in prepared:
            if isinstance(item, dict):
                result_by_serial[item["serial"]] = item
            else:
                serial, device, relay_key = item
                groups[relay_key].append((serial, device))

        category = "heavy" if action_type in HEAVY_ACTIONS else "simple"
        await asyncio.gather(
            *[
                self._execute_group(
                    relay_key,
                    category,
                    items,
                    action,
                    timeout_ms,
                    result_by_serial,
                )
                for relay_key, items in groups.items()
            ]
        )

        results = [
            result_by_serial.get(serial)
            or self._result(serial, False, error="internal_missing_result")
            for serial in serials
        ]
        ok = all(item.get("ok") for item in results)
        return {
            "type": "multi_action_result",
            "request_id": request_id,
            "ok": ok,
            "count": len(results),
            "results": results,
        }

    def _top_level_error(self, request_id: str, serials: list[str], error: str) -> dict[str, Any]:
        return {
            "type": "multi_action_result",
            "request_id": request_id,
            "ok": False,
            "count": len(serials),
            "error": error,
            "results": [self._result(serial, False, error=error) for serial in serials],
        }

    def _timeout_ms(self, payload: dict[str, Any], action: dict[str, Any]) -> int:
        raw = payload.get("timeout_ms", action.get("timeout_ms", self.default_timeout_ms))
        try:
            value = int(raw)
        except Exception:
            value = self.default_timeout_ms
        return max(100, min(60_000, value))

    def _busy_error(self, device: Any) -> str | None:
        if _device_state_name(device) == "BUSY":
            return "device_busy"
        try:
            active = int(
                getattr(device, "_scenario_active", getattr(device, "scenario_active", 0)) or 0
            )
        except Exception:
            active = 0
        if active > 0:
            return "scenario_active"
        return None

    def _relay_key(self, device: Any, serial: str) -> str:
        for attr in ("relay_id", "_relay_id", "relay_serial", "_relay_serial"):
            value = getattr(device, attr, None)
            if value:
                return str(value)
        try:
            from runtime.transports.adb_relay_server import get_relay_manager

            relay = get_relay_manager()
            actual = serial
            resolve = getattr(device, "_resolve_relay_serial", None)
            if callable(resolve):
                actual = str(resolve() or serial)
            conn = relay.relay_for_serial(actual) if relay is not None else None
            relay_id = getattr(conn, "relay_id", None)
            if relay_id:
                return str(relay_id)
        except Exception:
            pass
        return "local"

    def _semaphore(self, relay_key: str, category: str) -> asyncio.Semaphore:
        key = (relay_key, category)
        sem = self._semaphores.get(key)
        if sem is not None:
            return sem
        limit = (
            self.heavy_concurrency_per_relay
            if category == "heavy"
            else self.simple_concurrency_per_relay
        )
        sem = asyncio.Semaphore(limit)
        self._semaphores[key] = sem
        return sem

    async def _execute_group(
        self,
        relay_key: str,
        category: str,
        items: list[tuple[str, Any]],
        action: dict[str, Any],
        timeout_ms: int,
        result_by_serial: dict[str, dict[str, Any]],
    ) -> None:
        sem = self._semaphore(relay_key, category)

        async def _run(serial: str, device: Any) -> None:
            async with sem:
                result_by_serial[serial] = await self._execute_one(serial, device, action, timeout_ms)

        await asyncio.gather(*[_run(serial, device) for serial, device in items])

    async def _execute_one(
        self,
        serial: str,
        device: Any,
        action: dict[str, Any],
        timeout_ms: int,
    ) -> dict[str, Any]:
        started = time.monotonic()
        loop = asyncio.get_running_loop()
        try:
            await asyncio.wait_for(
                loop.run_in_executor(self._executor, self._invoke_sync, device, action),
                timeout=timeout_ms / 1000.0,
            )
            return self._result(serial, True, latency_ms=self._elapsed_ms(started))
        except asyncio.TimeoutError:
            return self._result(serial, False, error="timeout", latency_ms=self._elapsed_ms(started))
        except Exception as exc:
            return self._result(
                serial,
                False,
                error=exc.__class__.__name__,
                message=str(exc),
                latency_ms=self._elapsed_ms(started),
            )

    def _invoke_sync(self, device: Any, action: dict[str, Any]) -> None:
        action_type = str(action.get("type") or "")
        if action_type == "tap_ratio":
            rx = _clamp_ratio(action.get("rx", action.get("x", 0)))
            ry = _clamp_ratio(action.get("ry", action.get("y", 0)))
            device.tap(round(rx * self._width(device)), round(ry * self._height(device)))
        elif action_type == "tap":
            device.tap(int(action.get("x", 0)), int(action.get("y", 0)))
        elif action_type == "swipe_ratio":
            device.swipe(
                round(_clamp_ratio(action.get("rx1")) * self._width(device)),
                round(_clamp_ratio(action.get("ry1")) * self._height(device)),
                round(_clamp_ratio(action.get("rx2")) * self._width(device)),
                round(_clamp_ratio(action.get("ry2")) * self._height(device)),
                int(action.get("ms", 300)),
            )
        elif action_type == "swipe":
            device.swipe(
                int(action.get("x1", 0)),
                int(action.get("y1", 0)),
                int(action.get("x2", 0)),
                int(action.get("y2", 0)),
                int(action.get("ms", 300)),
            )
        elif action_type == "double_tap_ratio":
            rx = _clamp_ratio(action.get("rx", action.get("x", 0)))
            ry = _clamp_ratio(action.get("ry", action.get("y", 0)))
            device.double_tap(round(rx * self._width(device)), round(ry * self._height(device)))
        elif action_type == "double_tap":
            device.double_tap(int(action.get("x", 0)), int(action.get("y", 0)))
        elif action_type == "long_tap_ratio":
            rx = _clamp_ratio(action.get("rx", action.get("x", 0)))
            ry = _clamp_ratio(action.get("ry", action.get("y", 0)))
            device.long_tap(
                round(rx * self._width(device)),
                round(ry * self._height(device)),
                int(action.get("duration_ms", action.get("ms", 800))),
            )
        elif action_type == "long_tap":
            device.long_tap(
                int(action.get("x", 0)),
                int(action.get("y", 0)),
                int(action.get("duration_ms", action.get("ms", 800))),
            )
        elif action_type == "drag_ratio":
            device.drag(
                round(_clamp_ratio(action.get("rx1")) * self._width(device)),
                round(_clamp_ratio(action.get("ry1")) * self._height(device)),
                round(_clamp_ratio(action.get("rx2")) * self._width(device)),
                round(_clamp_ratio(action.get("ry2")) * self._height(device)),
                int(action.get("duration_ms", action.get("ms", 1000))),
            )
        elif action_type == "drag":
            device.drag(
                int(action.get("x1", 0)),
                int(action.get("y1", 0)),
                int(action.get("x2", 0)),
                int(action.get("y2", 0)),
                int(action.get("duration_ms", action.get("ms", 1000))),
            )
        elif action_type == "pinch_ratio":
            device.pinch(
                round(_clamp_ratio(action.get("rcx", action.get("rx", 0.5))) * self._width(device)),
                round(_clamp_ratio(action.get("rcy", action.get("ry", 0.5))) * self._height(device)),
                float(action.get("scale", 0.5)),
                int(action.get("duration_ms", action.get("ms", 400))),
            )
        elif action_type == "pinch":
            device.pinch(
                int(action.get("cx", 0)),
                int(action.get("cy", 0)),
                float(action.get("scale", 0.5)),
                int(action.get("duration_ms", action.get("ms", 400))),
            )
        elif action_type == "swipe_ext":
            device.swipe_ext(str(action.get("direction", "up")), float(action.get("scale", 0.8)), int(action.get("duration_ms", action.get("ms", 500))))
        elif action_type == "key":
            device.key(str(action.get("key", "home")))
        elif action_type == "tap_selector":
            device.tap_selector(str(action.get("by", "text")), str(action.get("value", "")))
        elif action_type == "input_text":
            device.input_text(str(action.get("text", "")))
        elif action_type == "launch_app":
            device.launch_app(str(action.get("package", "")))
        elif action_type == "open_url":
            device.open_url(str(action.get("url", "")), action.get("package"))
        elif action_type == "screen_on":
            device.screen_on()
        elif action_type == "screen_off":
            device.screen_off()
        elif action_type == "unlock":
            device.unlock()
        else:
            raise ValueError(f"unsupported action type {action_type!r}")

    def _width(self, device: Any) -> int:
        try:
            return max(1, int(getattr(device, "screen_width", 1080) or 1080))
        except Exception:
            return 1080

    def _height(self, device: Any) -> int:
        try:
            return max(1, int(getattr(device, "screen_height", 1920) or 1920))
        except Exception:
            return 1920

    def _elapsed_ms(self, started: float) -> int:
        return max(0, int((time.monotonic() - started) * 1000))

    def _result(
        self,
        serial: str,
        ok: bool,
        *,
        error: str | None = None,
        message: str | None = None,
        latency_ms: int | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {"serial": serial, "ok": ok}
        if error:
            result["error"] = error
        if message:
            result["message"] = message
        if latency_ms is not None:
            result["latency_ms"] = latency_ms
        return result
