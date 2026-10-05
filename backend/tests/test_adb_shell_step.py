from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from tasks.scenario_task import run_scenario_task


class _Device:
    serial = "logical-serial"
    model = "Pixel"
    screen_width = 1080
    screen_height = 1920
    _loop = object()
    _adb_serial = "10.0.0.7:5555"

    def _resolve_relay_serial(self) -> str:
        return self._adb_serial


class _Relay:
    def __init__(self, result: dict):
        self.result = result
        self.calls: list[tuple[str, str, float]] = []

    def resolve_serial(self, serial: str) -> str:
        return serial

    def relay_for_serial(self, serial: str) -> object:
        return object()

    async def run_command(self, serial: str, command: str, timeout: float) -> dict:
        self.calls.append((serial, command, timeout))
        return self.result


def _run_coro_now(coro, _loop):
    result = {}

    async def _run():
        result["value"] = await coro

    asyncio.run(_run())
    return SimpleNamespace(result=lambda timeout=None: result["value"])


def test_adb_shell_runs_through_agent_boot_relay_and_saves_output():
    relay = _Relay({"ok": True, "exit_code": 0, "output": "wifi"})
    scenario = {
        "steps": [
            {
                "type": "adb_shell",
                "command": "getprop ro.boot.wificountrycode",
                "timeout": 12,
                "save_as": "ADB_COUNTRY",
            }
        ]
    }

    with patch(
        "runtime.transports.adb_relay_server.get_relay_manager",
        return_value=relay,
    ), patch(
        "tasks.scenario.steps.navigation.asyncio.run_coroutine_threadsafe",
        side_effect=_run_coro_now,
    ):
        result = run_scenario_task(_Device(), scenario)

    assert result["success"] is True
    assert relay.calls == [
        ("10.0.0.7:5555", "getprop ro.boot.wificountrycode", 12.0)
    ]
    step = result["step_results"][0]
    assert step["ok"] is True
    assert step["exit_code"] == 0
    assert step["output"] == "wifi"
    assert result["context"]["vars"]["ADB_COUNTRY"] == "wifi"


def test_adb_shell_fails_scenario_on_nonzero_by_default():
    relay = _Relay({"ok": False, "exit_code": 1, "output": "denied", "error": ""})

    with patch(
        "runtime.transports.adb_relay_server.get_relay_manager",
        return_value=relay,
    ), patch(
        "tasks.scenario.steps.navigation.asyncio.run_coroutine_threadsafe",
        side_effect=_run_coro_now,
    ):
        result = run_scenario_task(
            _Device(),
            {"steps": [{"type": "adb_shell", "command": "cmd bad"}]},
        )

    assert result["success"] is False
    assert result["step_results"][0]["message"] == "denied"


def test_adb_shell_can_ignore_nonzero_exit():
    relay = _Relay({"ok": False, "exit_code": 2, "output": "missing", "error": ""})

    with patch(
        "runtime.transports.adb_relay_server.get_relay_manager",
        return_value=relay,
    ), patch(
        "tasks.scenario.steps.navigation.asyncio.run_coroutine_threadsafe",
        side_effect=_run_coro_now,
    ):
        result = run_scenario_task(
            _Device(),
            {
                "steps": [
                    {
                        "type": "adb_shell",
                        "command": "ls /not-found",
                        "fail_on_error": False,
                    }
                ]
            },
        )

    assert result["success"] is True
    assert result["step_results"][0]["exit_code"] == 2


def test_adb_shell_is_in_scenario_schema():
    from common.scenario_schema import SCENARIO_STEP_TYPES, validate_scenario

    assert "adb_shell" in SCENARIO_STEP_TYPES
    assert validate_scenario({"steps": [{"type": "adb_shell", "command": "id"}]}) == []
