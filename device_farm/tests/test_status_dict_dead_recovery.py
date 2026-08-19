"""status_dict() must report a controllable device as usable, not DEAD.

The watchdog can leave a device DEAD after a transient stall on a loaded host.
If u2 (or the agent shell) is still answering, the device is fully controllable
— proven live: a DEAD-labelled emulator ran a scenario to completion. The WS
status feed sent the raw DEAD label, and the control/record dropdown predicate
rejects state==DEAD outright, so alive devices vanished from the picker.
/api/devices/live already corrects this (via _apply_realtime_connectivity);
this keeps the WS feed consistent.
"""
from __future__ import annotations

from types import SimpleNamespace

from runtime.core.device_client import DeviceState


def _status_state(*, state: DeviceState, u2, agent) -> str:
    """Mirror the reported-state rule in DeviceClient.status_dict()."""
    u2_ok = u2 is not None
    agent_ok = agent is not None
    reported = state.value
    if state == DeviceState.DEAD and (u2_ok or agent_ok):
        reported = DeviceState.READY.value
    return reported


def test_dead_but_u2_connected_reports_ready():
    assert _status_state(state=DeviceState.DEAD, u2=object(), agent=None) == "READY"


def test_dead_but_agent_connected_reports_ready():
    assert _status_state(state=DeviceState.DEAD, u2=None, agent=object()) == "READY"


def test_dead_with_no_transport_stays_dead():
    # A genuinely gone device has no u2 and no agent — must stay DEAD.
    assert _status_state(state=DeviceState.DEAD, u2=None, agent=None) == "DEAD"


def test_non_dead_states_are_untouched():
    for st in (DeviceState.READY, DeviceState.BUSY, DeviceState.CONNECTING, DeviceState.DISCONNECTED):
        assert _status_state(state=st, u2=object(), agent=object()) == st.value


def test_real_status_dict_upgrades_dead_when_u2_present():
    """Exercise the actual method, not just the mirrored rule."""
    from runtime.core.device_client import DeviceClient

    import threading

    dev = DeviceClient.__new__(DeviceClient)
    # Minimal attributes status_dict() touches. state is a locked property, so
    # seed its backing field and lock directly rather than running __init__.
    dev._lock = threading.Lock()
    dev._state = DeviceState.DEAD
    dev.serial = "emulator-5554"
    dev._u2 = object()          # u2 answering → controllable
    dev._agent_send = None
    for attr in (
        "brand", "model", "android_version", "sdk_version", "battery_level",
        "battery_status", "battery_source", "battery_temp", "wifi_connected",
        "network_type", "network_subtype", "airplane_mode", "current_app",
        "screen_width", "screen_height",
    ):
        setattr(dev, attr, None)
    dev._stf_service = None
    dev._scenario_active = 0

    out = dev.status_dict()
    assert out["state"] == "READY"
    assert out["u2_ready"] is True
