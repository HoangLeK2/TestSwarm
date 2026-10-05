from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path
from typing import Any

from core.config import Config
from runtime.core import DeviceClient
from runtime.transports.u2_jsonrpc import _BatchRelaySession
from tasks.scenario_task import run_scenario_task

_REPO_ROOT = Path(__file__).resolve().parents[2]
_AGENT_BOOT = _REPO_ROOT / "agent-boot"
if str(_AGENT_BOOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_BOOT))

from relay.u2_executor import U2Executor  # noqa: E402


class _LoopThread:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._started = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self._started.set()
        self.loop.run_forever()

    def start(self) -> asyncio.AbstractEventLoop:
        self._thread.start()
        self._started.wait(timeout=2.0)
        return self.loop

    def stop(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(timeout=2.0)
        self.loop.close()


class _MockPhone:
    def __init__(self) -> None:
        self.current_package = ""
        self.events: list[tuple[Any, ...]] = []

    def app_start(self, package: str, activity: str | None = None, **kwargs: Any) -> None:
        self.current_package = package
        self.events.append(("app_start", package, activity, kwargs))

    def app_wait(self, package: str, *, front: bool = True, timeout: float = 20.0) -> int:
        self.events.append(("app_wait", package, front, timeout))
        return 4242 if package == self.current_package else 0

    def click(self, x: int, y: int) -> None:
        self.events.append(("click", x, y))

    def swipe(self, fx: int, fy: int, tx: int, ty: int, *, duration: float) -> None:
        self.events.append(("swipe", fx, fy, tx, ty, duration))

    def press(self, key: str) -> None:
        self.events.append(("press", key))

    def dump_hierarchy(self, **kwargs: Any) -> str:
        self.events.append(("dump_hierarchy", kwargs))
        package = self.current_package or "com.example.heavy"
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<hierarchy rotation="0">'
            f'<node text="Mock heavy screen" package="{package}" '
            'class="android.widget.TextView" bounds="[0,0][1080,1920]" />'
            "</hierarchy>"
        )

    def shell(self, command: str) -> tuple[str, int]:
        self.events.append(("shell", command))
        if "dumpsys activity activities" in command:
            package = self.current_package or "com.example.heavy"
            return (
                "mResumedActivity: ActivityRecord{mock "
                f"{package}/.MainActivity t1}}",
                0,
            )
        if command.startswith("echo "):
            return command.removeprefix("echo ").strip(), 0
        return "OK", 0


class _AgentBootPool:
    def __init__(self, phone: _MockPhone) -> None:
        self.phone = phone
        self.evict_count = 0

    async def run_locked(self, _serial: str, fn: Any) -> Any:
        return fn(self.phone)

    async def evict(self, _serial: str) -> None:
        self.evict_count += 1


class _MockAgentBootRelay:
    def __init__(self, serial: str, loop: asyncio.AbstractEventLoop, phone: _MockPhone) -> None:
        self.serial = serial
        self.phone = phone
        self.executor = U2Executor(pool=_AgentBootPool(phone), loop=loop)

    def resolve_serial(self, serial: str) -> str:
        return self.serial if serial in {self.serial, "mock-phone"} else serial

    def relay_for_serial(self, serial: str) -> str | None:
        return "mock-agent-boot" if serial == self.serial else None

    def get_capabilities(self, serial: str) -> dict[str, bool]:
        if self.resolve_serial(serial) != self.serial:
            return {}
        return {
            "has_u2": True,
            "supports_shell": True,
            "supports_screenshot": True,
            "supports_advanced_gestures": True,
        }

    async def u2_batch(
        self,
        serial: str,
        actions: list[dict],
        *,
        timeout: float = 30.0,
        cancel_event: Any | None = None,
        priority: str | int | None = None,
        deadline_ms: int | float | None = None,
    ) -> dict:
        del timeout
        return await self.executor.run_batch(
            self.resolve_serial(serial),
            actions,
            cancel_event=cancel_event,
            priority=priority,
            deadline_ms=deadline_ms,
        )

    async def adb_shell(self, serial: str, command: str, timeout: float = 30.0) -> str:
        del serial, timeout
        output, _rc = self.phone.shell(command)
        return output

    async def run_command(self, serial: str, command: str, timeout: float = 30.0) -> dict[str, Any]:
        del serial, timeout
        output, rc = self.phone.shell(command)
        return {"ok": rc == 0, "exit_code": rc, "output": output, "error": ""}


def test_mock_scenario_runs_end_to_end_through_agent_boot_phone(monkeypatch) -> None:
    from runtime.transports import adb_relay_server
    from tasks.scenario.steps import navigation

    loop_thread = _LoopThread()
    loop = loop_thread.start()
    try:
        serial = "mock-phone"
        phone = _MockPhone()
        relay = _MockAgentBootRelay(serial, loop, phone)
        monkeypatch.setattr(adb_relay_server, "get_relay_manager", lambda: relay)
        monkeypatch.setattr(navigation, "_poll_u2_ready", lambda *_args, **_kwargs: True)

        device = DeviceClient(serial=serial, index=0, config=Config())
        device.screen_width = 1080
        device.screen_height = 1920
        device.set_event_loop(loop)
        device._adb_serial = serial
        device._u2_batch = _BatchRelaySession(relay, serial, loop)

        result = run_scenario_task(
            device,
            {
                "capability_preflight": True,
                "capture_steps": False,
                "jitter": {"enabled": False},
                "settle_timeout_ms": 0,
                "steps": [
                    {
                        "type": "launch_app",
                        "package": "com.example.heavy",
                        "stop_before": True,
                        "wait_after": 0.01,
                    },
                    {"type": "tap_ratio", "x": 0.25, "y": 0.4},
                    {
                        "type": "swipe_ratio",
                        "x1": 0.5,
                        "y1": 0.82,
                        "x2": 0.5,
                        "y2": 0.25,
                        "duration_ms": 120,
                    },
                    {"type": "key", "key": "home"},
                    {
                        "type": "adb_shell",
                        "command": "echo heavy-e2e-ok",
                        "save_as": "agent_boot_shell",
                    },
                    {
                        "type": "wait_app",
                        "package": "com.example.heavy",
                        "timeout": 0.2,
                    },
                ],
            },
            context={},
        )
    finally:
        loop_thread.stop()

    assert result["success"] is True
    assert result["steps_executed"] == 6
    assert [step["type"] for step in result["step_results"]] == [
        "launch_app",
        "tap_ratio",
        "swipe_ratio",
        "key",
        "adb_shell",
        "wait_app",
    ]
    assert result["context"]["vars"]["agent_boot_shell"] == "heavy-e2e-ok"
    assert ("click", 270, 768) in phone.events
    assert ("press", "home") in phone.events
    assert any(event[0] == "swipe" for event in phone.events)
    assert any(event[:2] == ("app_start", "com.example.heavy") for event in phone.events)
