from __future__ import annotations

from api.routes.public import (
    _apply_realtime_connectivity,
    _build_live_device_alias_index,
    _live_device_realtime_aliases,
    _live_device_aliases,
    _match_live_device,
    _synthesize_live_device_from_relay,
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


def test_live_device_status_keeps_device_online_when_control_transport_is_available():
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

    assert via_relay["state"] == "CONNECTING"
    assert via_agent["state"] == "READY"


def test_live_device_status_marks_relay_only_disconnected_device_connecting():
    device = {
        "serial": "serial-1",
        "state": "DISCONNECTED",
        "agent_connected": False,
        "u2_ready": False,
    }

    _apply_realtime_connectivity(device, relay_online=True)

    assert device["state"] == "CONNECTING"


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


def test_live_device_status_promotes_connecting_relay_device_when_agent_boot_connected():
    device = {
        "serial": "serial-1",
        "state": "CONNECTING",
        "agent_connected": True,
        "u2_ready": False,
        "touch_method": "none",
        "stf_connected": False,
    }

    _apply_realtime_connectivity(device, relay_online=True, requires_relay=True)

    assert device["state"] == "READY"
    assert device["touch_method"] == "none"


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


class _FakeRelayCaps:
    def __init__(self, caps_by_serial: dict[str, dict[str, object]]) -> None:
        self._caps_by_serial = caps_by_serial

    def get_capabilities(self, serial: str) -> dict[str, object] | None:
        return self._caps_by_serial.get(serial)


class _FakeRelayOnline(_FakeRelayCaps):
    def __init__(
        self, online: set[str], caps_by_serial: dict[str, dict[str, object]]
    ) -> None:
        super().__init__(caps_by_serial)
        self._online = online

    def relay_for_serial(self, serial: str) -> object | None:
        return object() if serial in self._online else None

    def resolve_serial(self, serial: str) -> str:
        return serial

    def list_devices(self) -> list[dict[str, object]]:
        return [
            {
                "serial": serial,
                **self._caps_by_serial.get(serial, {}),
            }
            for serial in self._online
        ]


def test_live_device_match_uses_hardware_serial_when_wifi_ip_changes():
    allowed_devices = {
        "HW123": {
            "display_name": "Pixel Lab",
            "relay_aliases": ["HW123", "10.0.0.2", "10.0.0.2:5555"],
        }
    }
    relay = _FakeRelayCaps(
        {
            "10.0.0.9:41111": {
                "hardware_serial": "HW123",
                "wlan_ip": "10.0.0.9",
            }
        }
    )

    index = _build_live_device_alias_index(allowed_devices)
    registered_serial, info = _match_live_device(
        "10.0.0.9:41111",
        index,
        relay=relay,
    )

    assert registered_serial == "HW123"
    assert info["display_name"] == "Pixel Lab"


def test_live_device_realtime_aliases_include_runtime_serial_after_wifi_ip_changes():
    aliases = _live_device_realtime_aliases(
        "HW123",
        "10.0.0.9:41111",
        {
            "relay_aliases": ["HW123", "10.0.0.2", "10.0.0.2:5555"],
        },
    )

    assert "10.0.0.2:5555" in aliases
    assert "10.0.0.9:41111" in aliases


def test_live_device_status_synthesizes_relay_device_when_manager_registry_lags():
    relay = _FakeRelayOnline(
        {"10AE7S00HD002JK"},
        {
            "10AE7S00HD002JK": {
                "brand": "vivo",
                "model": "V2352A",
                "has_u2": True,
                "screen_width": "1080",
                "screen_height": "2400",
            }
        },
    )

    device = _synthesize_live_device_from_relay(
        "10AE7S00HD002JK",
        {
            "name": "V2352A",
            "display_name": "V2352A",
            "requires_relay": True,
            "relay_aliases": ["10AE7S00HD002JK"],
        },
        relay=relay,
    )

    assert device is not None
    assert device["serial"] == "10AE7S00HD002JK"
    assert device["registered_serial"] == "10AE7S00HD002JK"
    assert device["state"] == "READY"
    assert device["u2_ready"] is True
    assert device["touch_method"] == "u2"


def test_live_device_status_synthesizes_relay_device_after_runtime_serial_changes():
    relay = _FakeRelayOnline(
        {"10.0.0.9:41111"},
        {
            "10.0.0.9:41111": {
                "hardware_serial": "HW123",
                "brand": "Google",
                "model": "Pixel",
                "has_u2": True,
                "screen_width": 1080,
                "screen_height": 2400,
            }
        },
    )

    device = _synthesize_live_device_from_relay(
        "HW123",
        {
            "name": "Pixel",
            "display_name": "Pixel Lab",
            "requires_relay": True,
            "relay_aliases": ["HW123", "10.0.0.2:5555"],
        },
        relay=relay,
    )

    assert device is not None
    assert device["serial"] == "10.0.0.9:41111"
    assert device["registered_serial"] == "HW123"
    assert device["state"] == "READY"
    assert device["u2_ready"] is True
