from __future__ import annotations

from types import SimpleNamespace

from web.server import _find_ws_device_for_relay_serial


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
