from __future__ import annotations

import threading
import time

import pytest

from services.multi_control import MultiControlCoordinator


class _FakeDevice:
    def __init__(
        self,
        serial: str,
        *,
        width: int = 1080,
        height: int = 1920,
        relay_id: str = "relay-1",
        state: str = "READY",
        scenario_active: int = 0,
        delay_s: float = 0.0,
        active_counter: dict[str, int] | None = None,
        counter_lock: threading.Lock | None = None,
    ) -> None:
        self.serial = serial
        self.screen_width = width
        self.screen_height = height
        self._relay_id = relay_id
        self.state = state
        self._scenario_active = scenario_active
        self.delay_s = delay_s
        self.calls: list[tuple] = []
        self.active_counter = active_counter
        self.counter_lock = counter_lock

    def input_route_hint(self) -> str:
        return "fake"

    def tap(self, x: int, y: int) -> None:
        if self.active_counter is not None and self.counter_lock is not None:
            with self.counter_lock:
                self.active_counter["active"] += 1
                self.active_counter["max"] = max(
                    self.active_counter["max"], self.active_counter["active"]
                )
        try:
            if self.delay_s:
                time.sleep(self.delay_s)
            self.calls.append(("tap", x, y))
        finally:
            if self.active_counter is not None and self.counter_lock is not None:
                with self.counter_lock:
                    self.active_counter["active"] -= 1

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int) -> None:
        self.calls.append(("swipe", x1, y1, x2, y2, ms))


class _FakeManager:
    def __init__(self, devices: list[_FakeDevice]) -> None:
        self.devices = {device.serial: device for device in devices}

    def get_device(self, serial: str):
        return self.devices.get(serial)


@pytest.mark.asyncio
async def test_multi_action_tap_ratio_scales_each_target_device():
    primary = _FakeDevice("A", width=1000, height=2000, relay_id="r1")
    follower = _FakeDevice("B", width=500, height=1000, relay_id="r1")
    coordinator = MultiControlCoordinator(
        _FakeManager([primary, follower]),
        simple_concurrency_per_relay=4,
    )

    result = await coordinator.execute(
        {
            "request_id": "req-1",
            "primary_serial": "A",
            "serials": ["A", "B"],
            "action": {"type": "tap_ratio", "rx": 0.25, "ry": 0.5},
        }
    )

    assert result["ok"] is True
    assert primary.calls == [("tap", 250, 1000)]
    assert follower.calls == [("tap", 125, 500)]
    assert [item["ok"] for item in result["results"]] == [True, True]


@pytest.mark.asyncio
async def test_multi_action_rejects_busy_and_disallowed_devices_per_item():
    allowed = _FakeDevice("A", state="READY")
    busy = _FakeDevice("B", state="BUSY")
    scenario = _FakeDevice("C", scenario_active=1)
    denied = _FakeDevice("D")
    coordinator = MultiControlCoordinator(
        _FakeManager([allowed, busy, scenario, denied]),
        simple_concurrency_per_relay=4,
    )

    result = await coordinator.execute(
        {
            "request_id": "req-2",
            "serials": ["A", "B", "C", "D", "missing"],
            "action": {"type": "tap_ratio", "rx": 0.1, "ry": 0.2},
        },
        allowed_serials={"A", "B", "C", "missing"},
    )

    by_serial = {item["serial"]: item for item in result["results"]}
    assert by_serial["A"]["ok"] is True
    assert by_serial["B"]["ok"] is False
    assert by_serial["B"]["error"] == "device_busy"
    assert by_serial["C"]["error"] == "scenario_active"
    assert by_serial["D"]["error"] == "not_allowed"
    assert by_serial["missing"]["error"] == "not_found"
    assert denied.calls == []


@pytest.mark.asyncio
async def test_multi_action_caps_concurrency_per_relay():
    lock = threading.Lock()
    active_counter = {"active": 0, "max": 0}
    devices = [
        _FakeDevice(
            f"SN{i}",
            relay_id="relay-shared",
            delay_s=0.03,
            active_counter=active_counter,
            counter_lock=lock,
        )
        for i in range(6)
    ]
    coordinator = MultiControlCoordinator(
        _FakeManager(devices),
        simple_concurrency_per_relay=2,
    )

    result = await coordinator.execute(
        {
            "request_id": "req-3",
            "serials": [device.serial for device in devices],
            "action": {"type": "tap_ratio", "rx": 0.5, "ry": 0.5},
        }
    )

    assert result["ok"] is True
    assert active_counter["max"] <= 2
    assert all(item["ok"] for item in result["results"])
