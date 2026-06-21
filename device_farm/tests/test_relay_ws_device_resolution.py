from __future__ import annotations

from types import SimpleNamespace

from runtime.core.device_client import DeviceState
from web.server import (
    _find_ws_device_for_relay_serial,
    _relay_capabilities_status_payload,
)


def _device(
    serial: str,
    *,
    adb_serial: str = "",
    u2_host: str = "",
    agent: bool = True,
):
    return SimpleNamespace(
        serial=serial,
        _adb_serial=adb_serial,
        _u2_host=u2_host or None,
        _agent_send=(object() if agent else None),
    )


def test_relay_resolution_matches_hardware_serial_from_capabilities():
    device_a = _device("phone-A")
    device_b = _device("phone-B")

    assert (
        _find_ws_device_for_relay_serial(
            [device_a, device_b],
            "172.16.0.86:44601",
            caps={"hardware_serial": "phone-B"},
        )
        is device_b
    )


def test_relay_resolution_does_not_guess_lone_ws_agent():
    device_a = _device("phone-A")

    assert (
        _find_ws_device_for_relay_serial(
            [device_a],
            "172.16.0.86:44601",
            caps={"hardware_serial": "phone-B"},
        )
        is None
    )


def test_relay_resolution_matches_existing_adb_or_u2_identity():
    by_adb = _device("phone-A", adb_serial="172.16.0.83:5555")
    by_u2 = _device("phone-B", u2_host="172.16.0.86")

    assert (
        _find_ws_device_for_relay_serial([by_adb, by_u2], "172.16.0.83:44601")
        is by_adb
    )
    assert (
        _find_ws_device_for_relay_serial([by_adb, by_u2], "172.16.0.86:44601")
        is by_u2
    )


def test_relay_capabilities_do_not_revive_dead_runtime_device():
    device = SimpleNamespace(state=DeviceState.DEAD)

    payload = _relay_capabilities_status_payload(
        device,
        {
            "brand": "Samsung",
            "model": "SM-G930S",
            "android_version": "8.0",
            "screen_width": 1080,
            "screen_height": 1920,
        },
    )

    assert payload["brand"] == "Samsung"
    assert payload["model"] == "SM-G930S"
    assert "state" not in payload


def test_relay_capabilities_mark_non_dead_runtime_device_ready():
    device = SimpleNamespace(state=DeviceState.DISCONNECTED)

    payload = _relay_capabilities_status_payload(device, {})

    assert payload["state"] == "READY"


def test_relay_capabilities_do_not_override_busy_runtime_device():
    device = SimpleNamespace(state=DeviceState.BUSY)

    payload = _relay_capabilities_status_payload(device, {})

    assert "state" not in payload
