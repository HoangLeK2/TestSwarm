from __future__ import annotations

from api.routes.public import _apply_realtime_connectivity


def test_live_device_status_marks_stale_runtime_entry_disconnected_without_transport():
    device = {
        "serial": "serial-1",
        "state": "READY",
        "agent_connected": False,
        "u2_ready": False,
        "touch_method": "u2",
        "stf_connected": True,
    }

    _apply_realtime_connectivity(device, relay_lookup=lambda _serial: False)

    assert device["state"] == "DISCONNECTED"
    assert device["touch_method"] == "none"
    assert device["stf_connected"] is False


def test_live_device_status_keeps_device_online_when_transport_is_available():
    via_relay = {
        "serial": "serial-1",
        "state": "READY",
        "agent_connected": False,
        "u2_ready": False,
    }
    via_agent = {
        "serial": "serial-2",
        "state": "READY",
        "agent_connected": True,
        "u2_ready": False,
    }

    _apply_realtime_connectivity(via_relay, relay_lookup=lambda _serial: True)
    _apply_realtime_connectivity(via_agent, relay_lookup=lambda _serial: False)

    assert via_relay["state"] == "READY"
    assert via_agent["state"] == "READY"
