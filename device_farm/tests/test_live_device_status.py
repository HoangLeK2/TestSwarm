from __future__ import annotations

from datetime import datetime, timezone

from api.routes.public import (
    _apply_media_adapter_status,
    _apply_realtime_connectivity,
    _build_live_device_alias_index,
    _live_device_realtime_aliases,
    _live_device_aliases,
    _match_live_device,
    _media_adapter_status_for_aliases,
    _relay_online_for_live_device,
    _synthesize_live_device_from_media_adapter,
    _synthesize_live_device_from_relay,
    _device_health_projection,
)


def test_device_health_projection_separates_agent_stream_and_command():
    health = _device_health_projection(
        {
            "state": "READY",
            "agent_connected": True,
            "media_adapter_connected": True,
            "media_stream_active": False,
            "media_stream_connected": False,
            "usage_state": "idle",
        }
    )

    assert health["overall"] == "ready"
    assert health["agent"]["status"] == "online"
    assert health["stream"] == {
        "status": "starting",
        "observed_at": None,
        "reason": "waiting_first_frame",
    }
    assert health["command"]["status"] == "ready"


def test_device_health_projection_distinguishes_live_observation_from_db_heartbeat():
    health = _device_health_projection(
        {"state": "READY", "agent_connected": True},
        heartbeat_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        evaluated_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
    )

    assert health["heartbeat_at"] == "2026-08-01T00:00:00+00:00"
    assert health["last_signal_at"] == "2026-08-09T00:00:00+00:00"
    assert health["last_signal_source"] == "live_transport"


def test_device_health_projection_marks_busy_without_calling_it_offline():
    health = _device_health_projection(
        {
            "state": "BUSY",
            "agent_connected": True,
            "media_stream_active": True,
            "media_stream_connected": True,
        }
    )

    assert health["overall"] == "busy"
    assert health["agent"]["status"] == "online"
    assert health["command"] == {"status": "busy", "reason": "device_busy"}


def test_device_health_projection_does_not_trust_stale_ready_state_without_transport():
    health = _device_health_projection(
        {
            "state": "READY",
            "agent_connected": False,
            "stf_connected": False,
            "media_stream_active": True,
            "media_stream_connected": True,
        }
    )

    assert health["overall"] == "offline"
    assert health["command"]["status"] == "unavailable"
    assert health["stream"]["status"] == "ready"


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


def test_live_device_status_marks_relay_required_offline_before_stale_transport_revives_it():
    for state in ("DEAD", "DISCONNECTED", "CONNECTING"):
        device = {
            "serial": "serial-1",
            "state": state,
            "agent_connected": True,
            "u2_ready": True,
            "touch_method": "u2",
            "stf_connected": True,
        }

        _apply_realtime_connectivity(device, relay_online=False, requires_relay=True)

        assert device["state"] == "DISCONNECTED"
        assert device["touch_method"] == "none"
        assert device["stf_connected"] is False


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


def test_live_device_status_keeps_relay_managed_device_online_from_control_authority():
    device = {
        "serial": "serial-1",
        "state": "DISCONNECTED",
        "agent_connected": False,
        "u2_ready": False,
        "touch_method": "none",
        "stf_connected": False,
    }

    _apply_realtime_connectivity(device, relay_online=True, requires_relay=True)

    assert device["state"] == "READY"
    assert device["agent_connected"] is True


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


class _FakeMediaAdapterControl:
    def __init__(self, streams: dict[str, dict] | None = None) -> None:
        self.streams = streams or {}

    def has_serial(self, serial: str) -> bool:
        return serial in self.streams

    def stream_for_serial(self, serial: str) -> dict | None:
        return self.streams.get(serial)


def test_live_device_status_exposes_media_plane_independently_from_control_plane():
    media_ctrl = _FakeMediaAdapterControl(
        {
            "serial-1": {
                "serial": "serial-1",
                "stream_name": "device-serial-1",
                "active": True,
                "connected": True,
                "width": 216,
                "height": 480,
                "last_frame_unix_ms": 1234,
            }
        }
    )

    connected, stream = _media_adapter_status_for_aliases(
        ["serial-1"],
        media_ctrl=media_ctrl,
    )
    device = {
        "serial": "serial-1",
        "state": "DISCONNECTED",
        "agent_connected": False,
        "u2_ready": False,
        "touch_method": "none",
    }
    _apply_media_adapter_status(device, media_connected=connected, stream=stream)

    assert device["media_adapter_connected"] is True
    assert device["media_stream_active"] is True
    assert device["media_stream_connected"] is True
    assert device["media_stream_name"] == "device-serial-1"
    assert device["media_stream_last_frame_unix_ms"] == 1234
    assert device["agent_connected"] is False


def test_live_device_status_uses_media_snapshot_without_per_alias_calls():
    media_ctrl = _FakeMediaAdapterControl()
    media_ctrl.has_serial = lambda _serial: (_ for _ in ()).throw(
        AssertionError("no per-alias has_serial")
    )
    media_ctrl.stream_for_serial = lambda _serial: (_ for _ in ()).throw(
        AssertionError("no per-alias stream_for_serial")
    )

    connected, stream = _media_adapter_status_for_aliases(
        ["serial-1"],
        media_ctrl=media_ctrl,
        online_serials={"serial-1"},
        streams={
            "serial-1": {
                "serial": "serial-1",
                "stream_name": "device-serial-1",
                "active": True,
                "connected": True,
            }
        },
    )

    assert connected is True
    assert stream["stream_name"] == "device-serial-1"


def test_live_device_status_can_synthesize_media_only_device():
    media_ctrl = _FakeMediaAdapterControl(
        {
            "adb-serial-1": {
                "serial": "adb-serial-1",
                "active": False,
                "connected": False,
                "width": 320,
                "height": 640,
            }
        }
    )
    info = {
        "name": "Phone 1",
        "display_name": "Phone 1",
        "brand": "Google",
        "model": "Pixel",
        "relay_aliases": ["registered-1", "adb-serial-1"],
    }

    device = _synthesize_live_device_from_media_adapter(
        "registered-1",
        info,
        media_ctrl=media_ctrl,
    )

    assert device is not None
    assert device["serial"] == "adb-serial-1"
    assert device["registered_serial"] == "registered-1"
    assert device["state"] == "MEDIA_READY"
    assert device["agent_connected"] is False
    assert device["screen_width"] == 320
    assert device["screen_height"] == 640


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


class _FakeCtrlOnline:
    def __init__(self, online: set[str]) -> None:
        self._online = online

    def conn_for_serial(self, serial: str) -> object | None:
        return object() if serial in self._online else None


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


def test_relay_required_live_status_uses_agent_boot_control_channel():
    relay = _FakeRelayOnline(set(), {})
    ctrl = _FakeCtrlOnline({"serial-1"})

    assert (
        _relay_online_for_live_device(
            "serial-1",
            relay=relay,
            ctrl=ctrl,
            requires_relay=True,
        )
        is True
    )
    assert (
        _relay_online_for_live_device(
            "serial-1",
            relay=relay,
            ctrl=ctrl,
            requires_relay=False,
        )
        is True
    )

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


def test_live_device_status_synthesizes_relay_device_from_snapshots_without_hot_loop_calls():
    class _SnapshotOnlyRelay(_FakeRelayCaps):
        def relay_for_serial(self, _serial: str) -> object | None:
            raise AssertionError("no per-serial relay lookup")

        def list_devices(self) -> list[dict[str, object]]:
            raise AssertionError("relay devices should be snapshotted once")

    class _SnapshotOnlyCtrl:
        def conn_for_serial(self, _serial: str) -> object | None:
            raise AssertionError("no per-serial control lookup")

    relay = _SnapshotOnlyRelay(
        {
            "10.0.0.9:41111": {
                "hardware_serial": "HW123",
                "brand": "Google",
                "model": "Pixel",
                "has_u2": True,
            }
        }
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
        ctrl=_SnapshotOnlyCtrl(),
        relay_devices=[
            {
                "serial": "10.0.0.9:41111",
                "hardware_serial": "HW123",
                "brand": "Google",
                "model": "Pixel",
                "has_u2": True,
            }
        ],
        relay_online_serials={"10.0.0.9:41111"},
        control_online_serials={"10.0.0.9:41111"},
    )

    assert device is not None
    assert device["serial"] == "10.0.0.9:41111"
    assert device["state"] == "READY"
    assert device["agent_connected"] is True
