from __future__ import annotations

from api.routes.public import (
    _apply_realtime_connectivity,
    _build_live_device_alias_index,
    _live_device_aliases,
)


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


def test_live_device_status_revives_disconnected_relay_device():
    device = {
        "serial": "serial-1",
        "state": "DISCONNECTED",
        "agent_connected": False,
        "u2_ready": False,
    }

    _apply_realtime_connectivity(device, relay_online=True)

    assert device["state"] == "READY"


def test_live_device_status_does_not_revive_dead_device_from_relay_only():
    device = {
        "serial": "serial-1",
        "state": "DEAD",
        "agent_connected": False,
        "u2_ready": False,
        "touch_method": "none",
        "stf_connected": False,
    }

    _apply_realtime_connectivity(device, relay_online=True)

    assert device["state"] == "DEAD"


def test_live_device_status_revives_dead_device_when_device_transport_is_ready():
    device = {
        "serial": "serial-1",
        "state": "DEAD",
        "agent_connected": False,
        "u2_ready": True,
        "touch_method": "u2",
        "stf_connected": False,
    }

    _apply_realtime_connectivity(device, relay_online=False)

    assert device["state"] == "READY"


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


def test_live_device_alias_index_matches_runtime_alias_without_rewriting_serial():
    allowed_devices = {
        "HW123": {
            "name": "pixel",
            "display_name": "Pixel Lab",
            "requires_relay": True,
            "relay_aliases": ["HW123", "10.0.0.2", "10.0.0.2:5555"],
        }
    }

    index = _build_live_device_alias_index(allowed_devices)
    registered_serial, info = index["10.0.0.2:5555"]

    assert registered_serial == "HW123"
    assert info["display_name"] == "Pixel Lab"
    assert "10.0.0.2:5555" in _live_device_aliases(registered_serial, info)


def test_live_device_alias_index_keeps_canonical_match():
    allowed_devices = {
        "HW123": {
            "display_name": "Pixel Lab",
            "relay_aliases": ["10.0.0.2:5555"],
        }
    }

    index = _build_live_device_alias_index(allowed_devices)

    assert index["HW123"][0] == "HW123"
    assert index["10.0.0.2:5555"][0] == "HW123"


def test_live_device_alias_index_does_not_match_unknown_runtime_serial():
    allowed_devices = {
        "HW123": {
            "display_name": "Pixel Lab",
            "relay_aliases": ["10.0.0.2:5555"],
        }
    }

    index = _build_live_device_alias_index(allowed_devices)

    assert index.get("unknown-device") is None
