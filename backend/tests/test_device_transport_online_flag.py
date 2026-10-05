"""`transport_online` answers by serial, not by who owns the agent.

An allocated pool phone is carried by the managing workspace's agent. The
tenant's `/relay-agents` is org-scoped and never lists that agent, so the client
cannot decide transport on its own — the list rendered every allocated phone as
"no transport" and the online filter hid it while it was streaming.
"""
from __future__ import annotations

from types import SimpleNamespace

from api.routes.devices import _device_serial_aliases, _transport_online_for


class _Ctrl:
    def __init__(self, serials: set[str]) -> None:
        self._serials = serials

    def conn_for_serial(self, serial: str):
        return object() if serial in self._serials else None


class _Relay:
    def __init__(self, serials: set[str]) -> None:
        self._serials = serials

    def relay_for_serial(self, serial: str):
        return object() if serial in self._serials else None


def _device(**overrides):
    base = {
        "serial": "SN-1",
        "device_serial": "SN-1",
        "adb_serial": None,
        "relay_serial": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_aliases_are_deduped_and_ordered():
    device = _device(adb_serial="SN-1", relay_serial="SN-1", device_serial="SN-1")
    assert _device_serial_aliases(device) == ["SN-1"]
    assert _device_serial_aliases(device, adb_serial="ADB-9") == ["ADB-9", "SN-1"]


def test_transport_online_when_control_channel_holds_the_serial():
    device = _device(serial="SN-POOL", adb_serial="SN-POOL")
    ctrl = _Ctrl({"SN-POOL"})
    assert _transport_online_for(device, ctrl, None) is True


def test_transport_online_when_only_the_video_relay_holds_the_serial():
    device = _device(serial="SN-POOL", relay_serial="RELAY-POOL")
    assert _transport_online_for(device, None, _Relay({"RELAY-POOL"})) is True


def test_transport_offline_when_no_registry_knows_the_serial():
    device = _device(serial="SN-GONE", adb_serial="SN-GONE")
    assert _transport_online_for(device, _Ctrl(set()), _Relay(set())) is False
    assert _transport_online_for(device, None, None) is False


def test_another_phone_being_live_does_not_make_this_one_online():
    """Reachability is per serial — never "some agent of mine is up"."""
    device = _device(serial="SN-MINE", adb_serial="SN-MINE")
    assert _transport_online_for(device, _Ctrl({"SN-OTHER"}), _Relay({"SN-OTHER"})) is False
