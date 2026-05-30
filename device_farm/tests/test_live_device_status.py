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

    _apply_realtime_connectivity(device)

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

    _apply_realtime_connectivity(via_relay, relay_online=True)
    _apply_realtime_connectivity(via_agent, relay_online=False)

    assert via_relay["state"] == "READY"
    assert via_agent["state"] == "READY"


def test_live_device_status_marks_relay_managed_device_offline_without_agent_boot():
    device = {
        "serial": "serial-1",
        "state": "READY",
        "agent_connected": True,
        "u2_ready": True,
    }

    _apply_realtime_connectivity(device, relay_online=False, requires_relay=True)

    assert device["state"] == "DISCONNECTED"


def test_live_device_status_keeps_relay_managed_device_online_when_agent_boot_connected():
    device = {
        "serial": "serial-1",
        "state": "READY",
        "agent_connected": True,
        "u2_ready": True,
    }

    _apply_realtime_connectivity(device, relay_online=True, requires_relay=True)

    assert device["state"] == "READY"
