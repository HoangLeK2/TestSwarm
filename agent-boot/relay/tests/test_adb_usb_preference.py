"""Tests for dedupe_adb_serials_prefer_usb and reconcile_usb_preferred_for_duplicate_devices."""
from __future__ import annotations

import relay.adb as adb_mod
from relay.adb import dedupe_adb_serials_prefer_usb, reconcile_usb_preferred_for_duplicate_devices
from relay.device_state import DeviceContext, DeviceRegistry, DeviceState


def test_dedupe_usb_wins_over_tcp_same_host_key(monkeypatch):
    """Host key matches when TCP serial is host:port and USB serial equals host."""
    calls: list[tuple[str, ...]] = []

    def fake_run(*args: str, serial=None, timeout=30):
        calls.append(tuple(args))
        return "", 0

    monkeypatch.setattr(adb_mod, "_run", fake_run)

    out = dedupe_adb_serials_prefer_usb(["emulator-5554", "emulator-5554:5555"])
    assert out == ["emulator-5554"]
    disconnects = [c for c in calls if c and c[0] == "disconnect"]
    assert ("disconnect", "emulator-5554:5555") in disconnects


def test_dedupe_keeps_tcp_when_no_usb_for_host(monkeypatch):
    calls: list[tuple[str, ...]] = []

    def fake_run(*args: str, serial=None, timeout=30):
        calls.append(tuple(args))
        return "", 0

    monkeypatch.setattr(adb_mod, "_run", fake_run)

    out = dedupe_adb_serials_prefer_usb(["10.0.0.1:5555"])
    assert out == ["10.0.0.1:5555"]
    assert not any(c and c[0] == "disconnect" for c in calls)


def test_dedupe_two_tcp_same_ip_last_wins(monkeypatch):
    calls: list[tuple[str, ...]] = []

    def fake_run(*args: str, serial=None, timeout=30):
        calls.append(tuple(args))
        return "", 0

    monkeypatch.setattr(adb_mod, "_run", fake_run)

    out = dedupe_adb_serials_prefer_usb(["192.168.0.2:5555", "192.168.0.2:12345"])
    assert out == ["192.168.0.2:12345"]
    disconnects = [c for c in calls if c and c[0] == "disconnect"]
    assert ("disconnect", "192.168.0.2:5555") in disconnects


def test_dedupe_multiple_usb_devices_sorted(monkeypatch):
    def fake_run(*args: str, serial=None, timeout=30):
        return "", 0

    monkeypatch.setattr(adb_mod, "_run", fake_run)

    out = dedupe_adb_serials_prefer_usb(["ZEBRA", "ALPHA", "10.1.1.1:5555"])
    assert out == ["10.1.1.1:5555", "ALPHA", "ZEBRA"]


def test_reconcile_disconnects_tcp_when_usb_shares_hardware_serial(monkeypatch):
    calls: list[tuple[str, ...]] = []

    def fake_run(*args: str, serial=None, timeout=30):
        calls.append(tuple(args))
        return "", 0

    monkeypatch.setattr(adb_mod, "_run", fake_run)

    reg = DeviceRegistry()
    u = DeviceContext("R58USB", state=DeviceState.ONLINE)
    u.capabilities = {"hardware_serial": "ABC123"}
    t = DeviceContext("192.168.1.10:5555", state=DeviceState.ONLINE)
    t.capabilities = {"hardware_serial": "ABC123"}
    reg._devices["R58USB"] = u
    reg._devices["192.168.1.10:5555"] = t

    pairs = reconcile_usb_preferred_for_duplicate_devices(reg)
    assert pairs == [("192.168.1.10:5555", "R58USB")]
    assert ("disconnect", "192.168.1.10:5555") in calls


def test_reconcile_noop_when_only_tcp(monkeypatch):
    calls: list[tuple[str, ...]] = []

    def fake_run(*args: str, serial=None, timeout=30):
        calls.append(tuple(args))
        return "", 0

    monkeypatch.setattr(adb_mod, "_run", fake_run)

    reg = DeviceRegistry()
    t = DeviceContext("192.168.1.10:5555", state=DeviceState.ONLINE)
    t.capabilities = {"hardware_serial": "ABC123"}
    reg._devices["192.168.1.10:5555"] = t

    assert reconcile_usb_preferred_for_duplicate_devices(reg) == []
    assert not any(c and c[0] == "disconnect" for c in calls)


def test_reconcile_skips_empty_hardware_serial(monkeypatch):
    calls: list[tuple[str, ...]] = []

    def fake_run(*args: str, serial=None, timeout=30):
        calls.append(tuple(args))
        return "", 0

    monkeypatch.setattr(adb_mod, "_run", fake_run)

    reg = DeviceRegistry()
    u = DeviceContext("R58USB", state=DeviceState.ONLINE)
    u.capabilities = {"hardware_serial": ""}
    t = DeviceContext("192.168.1.10:5555", state=DeviceState.ONLINE)
    t.capabilities = {"model": "x"}
    reg._devices["R58USB"] = u
    reg._devices["192.168.1.10:5555"] = t

    assert reconcile_usb_preferred_for_duplicate_devices(reg) == []
    assert not any(c and c[0] == "disconnect" for c in calls)
