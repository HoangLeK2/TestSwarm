"""uiautomator2 must use the ADB server that owns the phone.

`u2.connect(<str>)` resolves the serial through `adbutils.adb` — a module
singleton built once from ANDROID_ADB_SERVER_HOST/PORT. It does not know about
ADB_SERVER_SOCKETS, so with several servers configured every u2 session lands on
one port while the rest of agent-boot routes per serial. A phone on :5038 ends
up with a working `adb shell` and a u2 session negotiated against :5037.
"""
from __future__ import annotations

import asyncio
import sys
import types

import pytest

import relay.adb as adb_mod
from relay.adb_routes import AdbEndpoint
from relay.u2_session_pool import U2SessionPool

E5037 = AdbEndpoint("127.0.0.1", 5037)
E5038 = AdbEndpoint("127.0.0.1", 5038)


class _FakeDevice:
    def __init__(self, serial: str, host: str, port: int) -> None:
        self.serial = serial
        self.host = host
        self.port = port


class _FakeClient:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = int(port)

    def device(self, serial: str) -> _FakeDevice:
        return _FakeDevice(serial, self.host, self.port)


@pytest.fixture
def fake_adbutils(monkeypatch):
    """Stand in for the `adbutils` module imported inside adb_device_for_u2."""
    created: list[_FakeClient] = []

    def AdbClient(host: str, port: int) -> _FakeClient:  # noqa: N802 — mirrors adbutils
        client = _FakeClient(host, port)
        created.append(client)
        return client

    module = types.ModuleType("adbutils")
    module.AdbClient = AdbClient
    monkeypatch.setitem(sys.modules, "adbutils", module)
    adb_mod._ADBUTILS_CLIENTS.clear()
    yield created
    adb_mod._ADBUTILS_CLIENTS.clear()


@pytest.fixture
def two_servers(monkeypatch):
    monkeypatch.setenv("ADB_SERVER_SOCKETS", "tcp:127.0.0.1:5037,tcp:127.0.0.1:5038")
    adb_mod.route_table.clear()
    yield
    adb_mod.route_table.clear()


def test_phone_on_5038_gets_a_u2_device_on_5038(two_servers, fake_adbutils):
    adb_mod.route_table.set("B", E5038)
    device = adb_mod.adb_device_for_u2("B")
    assert (device.host, device.port) == ("127.0.0.1", 5038)
    assert device.serial == "B"


def test_phone_on_5037_gets_a_u2_device_on_5037(two_servers, fake_adbutils):
    adb_mod.route_table.set("A", E5037)
    device = adb_mod.adb_device_for_u2("A")
    assert (device.host, device.port) == ("127.0.0.1", 5037)


def test_phones_on_different_servers_do_not_share_an_endpoint(
    two_servers, fake_adbutils
):
    adb_mod.route_table.set("A", E5037)
    adb_mod.route_table.set("B", E5038)
    a = adb_mod.adb_device_for_u2("A")
    b = adb_mod.adb_device_for_u2("B")
    assert a.port != b.port


def test_one_client_is_reused_per_endpoint(two_servers, fake_adbutils):
    adb_mod.route_table.set("A", E5037)
    adb_mod.route_table.set("A2", E5037)
    adb_mod.adb_device_for_u2("A")
    adb_mod.adb_device_for_u2("A2")
    adb_mod.adb_device_for_u2("A")
    assert len(fake_adbutils) == 1


def test_unknown_serial_falls_back_to_u2_own_resolution(
    two_servers, fake_adbutils, monkeypatch
):
    """No route and no device anywhere: return None rather than guess a server."""
    monkeypatch.setattr(adb_mod, "_discover_route", lambda serial: None)
    assert adb_mod.adb_device_for_u2("GHOST") is None
    assert fake_adbutils == []


def test_blank_serial_is_not_routed(two_servers, fake_adbutils):
    assert adb_mod.adb_device_for_u2("") is None


def test_route_is_discovered_before_connecting(two_servers, fake_adbutils, monkeypatch):
    monkeypatch.setattr(adb_mod, "_discover_route", lambda serial: E5038)
    device = adb_mod.adb_device_for_u2("B")
    assert device.port == 5038


# ── pool wiring ──────────────────────────────────────────────────────────────


def _pool(**kwargs) -> U2SessionPool:
    return U2SessionPool(loop=asyncio.new_event_loop(), **kwargs)


def test_pool_hands_u2_the_routed_device(two_servers, fake_adbutils):
    adb_mod.route_table.set("B", E5038)
    target = _pool()._connect_target("B")
    assert isinstance(target, _FakeDevice)
    assert target.port == 5038


def test_pool_falls_back_to_the_serial_when_unrouted(
    two_servers, fake_adbutils, monkeypatch
):
    monkeypatch.setattr(adb_mod, "_discover_route", lambda serial: None)
    assert _pool()._connect_target("GHOST") == "GHOST"


def test_pool_strips_the_tcp_port_when_unrouted(two_servers, fake_adbutils, monkeypatch):
    monkeypatch.setattr(adb_mod, "_discover_route", lambda serial: None)
    assert _pool()._connect_target("10.0.0.5:5555") == "10.0.0.5"


def test_empty_route_table_yields_the_plain_serial(two_servers, fake_adbutils, monkeypatch):
    """What keeps every existing pool test working: no route ⇒ old string path."""
    monkeypatch.setattr(adb_mod, "_discover_route", lambda serial: None)
    pool = _pool(connect_fn=lambda serial: None)
    assert pool._connect_target("B") == "B"
    assert fake_adbutils == []


def test_routing_failure_never_blocks_a_connect(two_servers, monkeypatch):
    def boom(serial):
        raise RuntimeError("adb server exploded")

    monkeypatch.setattr(adb_mod, "adb_device_for_u2", boom)
    assert _pool()._connect_target("B") == "B"


@pytest.mark.asyncio
async def test_route_lookup_never_runs_on_the_event_loop(two_servers, fake_adbutils):
    """Resolving a route spawns `adb devices` and waits on admission.

    On the loop thread that stalls every other phone in the process, and it sits
    outside the connect timeout, so a wedged ADB server would hang the pool.
    """
    import threading

    loop_thread = threading.current_thread()
    lookup_threads: list[threading.Thread] = []

    def routed(serial):
        # This is the call that can spawn a subprocess and block on admission.
        lookup_threads.append(threading.current_thread())
        return _FakeDevice(serial, "127.0.0.1", 5038)

    connected: list[object] = []

    def connect(target):
        connected.append(target)
        device = _FakeDevice("B", "127.0.0.1", 5038)
        device.alive = True
        return device

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(adb_mod, "adb_device_for_u2", routed)
        pool = U2SessionPool(loop=asyncio.get_running_loop())
        pool._get_connect_fn = lambda: connect
        await pool._connect("B")

    assert lookup_threads, "route lookup never ran"
    assert loop_thread not in lookup_threads, (
        "route lookup ran on the event loop — it blocks every other phone "
        "and sits outside the connect timeout"
    )
    assert connected and connected[0].port == 5038, "u2 must get the routed device"
