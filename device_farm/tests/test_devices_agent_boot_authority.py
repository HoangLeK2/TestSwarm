from __future__ import annotations

from types import SimpleNamespace

from services.agent_boot_presence import (
    agent_boot_presence_for_device,
    control_conn_for_device,
)

class _FakeConn:
    def __init__(self, relay_id: str) -> None:
        self.relay_id = relay_id


class _FakeCtrl:
    def __init__(self, serials: dict[str, str]) -> None:
        self._serials = serials

    def conn_for_serial(self, serial: str):
        relay_id = self._serials.get(serial)
        return _FakeConn(relay_id) if relay_id else None

    def find_serial_by_ip(self, ip: str) -> str | None:
        for serial in self._serials:
            serial_ip = serial.split(":", 1)[0]
            if serial_ip == ip:
                return serial
        return None


def _device(**overrides):
    data = {
        "serial": "HW123",
        "adb_serial": "HW123",
        "relay_serial": None,
        "adb_ip": None,
        "adb_port": 5555,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_agent_boot_presence_keeps_reported_serial_online():
    device = _device()
    ctrl = _FakeCtrl({"HW123": "relay-1"})

    assert control_conn_for_device(ctrl, device).relay_id == "relay-1"
    presence = agent_boot_presence_for_device(ctrl, device)
    assert presence.reported is True
    assert presence.relay_id == "relay-1"


def test_agent_boot_presence_marks_relay_device_dead_when_serial_missing():
    device = _device()
    ctrl = _FakeCtrl({})

    assert control_conn_for_device(ctrl, device) is None
    presence = agent_boot_presence_for_device(ctrl, device)
    assert presence.reported is False
    assert presence.relay_id is None


def test_agent_boot_presence_matches_adb_ip_dynamic_port():
    device = _device(serial="HW123", adb_serial=None, adb_ip="10.130.248.83")
    ctrl = _FakeCtrl({"10.130.248.83:42123": "relay-1"})

    assert control_conn_for_device(ctrl, device).relay_id == "relay-1"
    presence = agent_boot_presence_for_device(ctrl, device)
    assert presence.reported is True
    assert presence.relay_id == "relay-1"
