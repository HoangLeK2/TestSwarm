"""Multi-ADB-server routing: serial → endpoint cache, staleness, recovery."""
from __future__ import annotations

import base64
import threading

import pytest

import relay.adb as adb_mod
from relay.adb_routes import AdbEndpoint, AdbRouteTable

E5037 = AdbEndpoint("127.0.0.1", 5037)
E5038 = AdbEndpoint("127.0.0.1", 5038)


@pytest.fixture
def two_servers(monkeypatch):
    """Configure :5037 + :5038 and hand back a scriptable fake ADB world."""
    monkeypatch.setenv("ADB_SERVER_SOCKETS", "tcp:127.0.0.1:5037,tcp:127.0.0.1:5038")
    adb_mod.route_table.clear()

    class World:
        def __init__(self) -> None:
            # endpoint port → serials currently attached there
            self.devices: dict[int, list[str]] = {5037: [], 5038: []}
            self.dead: set[int] = set()
            self.scans: list[int] = []
            self.commands: list[tuple[str, tuple[str, ...], int]] = []

        def port_of(self, argv) -> int:
            return int(argv[argv.index("-P") + 1])

        # stands in for `adb -H .. -P .. devices`
        def run_raw(self, args, timeout=5):
            port = self.port_of(list(args))
            self.scans.append(port)
            if port in self.dead:
                return "cannot connect to daemon", 1
            lines = "".join(f"{s}\tdevice\n" for s in self.devices[port])
            return f"List of devices attached\n{lines}", 0

        # stands in for the scheduler dispatching one command
        def run_cmd(self, args, *, serial, timeout, lane):
            route = adb_mod.route_table.get(serial)
            port = route.endpoint.port if route else 5037
            self.commands.append((serial, tuple(args), port))
            if port in self.dead:
                return _Result("adb: error: failed to connect to daemon", 1)
            if serial not in self.devices[port]:
                return _Result(f"error: device '{serial}' not found", 1)
            return _Result("ok", 0)

        # `adb exec-out` keeps its diagnostics on stderr, payload on stdout.
        def run_bytes_cmd(self, args, *, serial, timeout, lane):
            text = self.run_cmd(args, serial=serial, timeout=timeout, lane=lane)
            if text.returncode == 0:
                return _BytesResult(b"PNG", 0, "")
            return _BytesResult(b"", text.returncode, text.output)

    class _Result:
        def __init__(self, output, returncode):
            self.output = output
            self.returncode = returncode
            self.timed_out = False
            self.transport = "fake"

    class _BytesResult:
        def __init__(self, output, returncode, error):
            self.output = output
            self.returncode = returncode
            self.error = error
            self.timed_out = False
            self.transport = "fake"

    world = World()

    class _FakeScheduler:
        def run(self, args, *, serial, timeout, lane):
            return world.run_cmd(args, serial=serial, timeout=timeout, lane=lane)

        def run_bytes(self, args, *, serial, timeout, lane):
            return world.run_bytes_cmd(args, serial=serial, timeout=timeout, lane=lane)

    monkeypatch.setattr(adb_mod, "_run_raw", world.run_raw)
    monkeypatch.setattr(adb_mod, "_get_adb_scheduler", lambda: _FakeScheduler())
    yield world
    adb_mod.route_table.clear()


# ── basic routing ────────────────────────────────────────────────────────────


def test_devices_on_different_servers_get_their_own_port(two_servers):
    two_servers.devices[5037] = ["A"]
    two_servers.devices[5038] = ["B"]

    assert adb_mod._run("shell", "true", serial="A") == ("ok", 0)
    assert adb_mod._run("shell", "true", serial="B") == ("ok", 0)

    assert adb_mod.route_table.get("A").endpoint == E5037
    assert adb_mod.route_table.get("B").endpoint == E5038
    assert [(s, p) for s, _a, p in two_servers.commands] == [("A", 5037), ("B", 5038)]


def test_adb_command_uses_routed_server_flags(two_servers):
    adb_mod.route_table.set("B", E5038)
    assert adb_mod._adb_command("shell", "true", serial="B")[:6] == [
        adb_mod._ADB, "-H", "127.0.0.1", "-P", "5038", "-s",
    ]


# ── cached lookup: no rescan per command ─────────────────────────────────────


def test_repeated_commands_do_not_rescan_ports(two_servers):
    two_servers.devices[5038] = ["A"]

    for _ in range(10):
        assert adb_mod._run("shell", "true", serial="A") == ("ok", 0)

    # One discovery scan sweep (5037 miss, 5038 hit), then pure cache hits.
    assert two_servers.scans == [5037, 5038]
    assert len(two_servers.commands) == 10


def test_single_endpoint_config_never_scans(monkeypatch, two_servers):
    monkeypatch.setenv("ADB_SERVER_SOCKETS", "tcp:127.0.0.1:5037")
    two_servers.devices[5037] = ["A"]

    adb_mod._run("shell", "true", serial="A")

    assert two_servers.scans == []


# ── cache miss ───────────────────────────────────────────────────────────────


def test_unknown_serial_is_discovered_then_cached(two_servers):
    two_servers.devices[5038] = ["A"]

    assert adb_mod.route_table.get("A") is None
    assert adb_mod._run("shell", "true", serial="A") == ("ok", 0)
    assert adb_mod.route_table.get("A").endpoint == E5038


def test_missing_device_anywhere_leaves_no_route(two_servers):
    out, rc = adb_mod._run("shell", "true", serial="GHOST")

    assert rc == 1
    assert "not found" in out
    assert adb_mod.route_table.get("GHOST") is None


# ── stale route: device moved between servers ────────────────────────────────


def test_device_moving_ports_recovers_without_restart(two_servers):
    two_servers.devices[5037] = ["A"]
    adb_mod._run("shell", "true", serial="A")
    assert adb_mod.route_table.get("A").endpoint == E5037

    # Phone re-plugged onto the other ADB server.
    two_servers.devices[5037] = []
    two_servers.devices[5038] = ["A"]

    assert adb_mod._run("shell", "true", serial="A") == ("ok", 0)
    assert adb_mod.route_table.get("A").endpoint == E5038
    # Exactly one retry: failed on 5037, succeeded on 5038.
    assert [p for _s, _a, p in two_servers.commands] == [5037, 5037, 5038]


def test_screencap_recovers_from_stale_route(two_servers):
    """_run_bytes has binary stdout — the reroute verdict must come from stderr."""
    two_servers.devices[5037] = ["A"]
    assert adb_mod._screencap("A") == (base64.b64encode(b"PNG").decode(), 0)

    two_servers.devices[5037] = []
    two_servers.devices[5038] = ["A"]
    two_servers.commands.clear()

    assert adb_mod._screencap("A") == (base64.b64encode(b"PNG").decode(), 0)
    assert adb_mod.route_table.get("A").endpoint == E5038
    assert [p for _s, _a, p in two_servers.commands] == [5037, 5038]


def test_tracker_snapshot_moves_route_between_endpoints():
    table = AdbRouteTable()
    table.sync_endpoint(E5037, {"A": "device"})
    assert table.get("A").endpoint == E5037

    table.sync_endpoint(E5038, {"A": "device"})
    table.sync_endpoint(E5037, {})  # old tracker reports A gone

    assert table.get("A").endpoint == E5038


def test_tracker_snapshot_drops_route_when_device_disconnects():
    table = AdbRouteTable()
    table.sync_endpoint(E5037, {"A": "device"})
    table.sync_endpoint(E5037, {})
    assert table.get("A") is None


def test_duplicate_serial_last_device_report_wins():
    """Documented policy: newest endpoint reporting state=device owns the serial."""
    table = AdbRouteTable()
    table.sync_endpoint(E5037, {"A": "device"})
    table.sync_endpoint(E5038, {"A": "device"})
    assert table.get("A").endpoint == E5038

    # A stale tracker on 5037 saying "gone" must not steal the newer route.
    table.sync_endpoint(E5037, {})
    assert table.get("A").endpoint == E5038


# ── offline / unauthorized: no route churn, no infinite retry ────────────────


@pytest.mark.parametrize(
    "message",
    [
        "error: device offline",
        "error: device unauthorized. Please check the confirmation dialog",
    ],
)
def test_offline_and_unauthorized_do_not_invalidate_route(
    two_servers, monkeypatch, message
):
    two_servers.devices[5037] = ["A"]
    adb_mod._run("shell", "true", serial="A")
    two_servers.commands.clear()
    two_servers.scans.clear()
    _force_result(monkeypatch, two_servers, message, 1)

    out, rc = adb_mod._run("shell", "true", serial="A")

    assert rc == 1
    assert out == message
    assert adb_mod.route_table.get("A").endpoint == E5037  # route kept
    assert two_servers.scans == []  # no rediscovery storm


def test_normal_command_failure_is_not_a_routing_failure(two_servers, monkeypatch):
    two_servers.devices[5037] = ["A"]
    adb_mod._run("shell", "true", serial="A")
    two_servers.scans.clear()
    _force_result(monkeypatch, two_servers, "ls: no such file", 1)

    assert adb_mod._run("shell", "ls /nope", serial="A")[1] == 1
    assert adb_mod.route_table.get("A").endpoint == E5037
    assert two_servers.scans == []


def test_route_miss_retries_at_most_once(two_servers):
    """A device that is genuinely gone must not loop rediscovering forever."""
    two_servers.devices[5037] = ["A"]
    adb_mod._run("shell", "true", serial="A")
    two_servers.devices[5037] = []
    two_servers.commands.clear()
    two_servers.scans.clear()

    out, rc = adb_mod._run("shell", "true", serial="A")

    assert rc == 1
    assert len(two_servers.commands) == 1  # failed once, no retry (nothing found)
    assert two_servers.scans == [5037, 5038]  # one bounded sweep
    assert adb_mod.route_table.get("A") is None


# ── one dead ADB server must not break the others ────────────────────────────


def test_dead_server_does_not_break_devices_on_healthy_server(two_servers):
    two_servers.devices[5038] = ["B"]
    two_servers.dead.add(5037)

    assert adb_mod._run("shell", "true", serial="B") == ("ok", 0)
    assert adb_mod.route_table.get("B").endpoint == E5038


def test_list_serials_skips_dead_server(two_servers, monkeypatch):
    monkeypatch.setattr(adb_mod, "_run", lambda *a, **k: ("", 0))
    two_servers.devices[5038] = ["B"]
    two_servers.dead.add(5037)

    assert adb_mod._list_serials() == ["B"]
    assert adb_mod.route_table.get("B").endpoint == E5038


# ── concurrency ──────────────────────────────────────────────────────────────


def test_concurrent_misses_share_one_discovery():
    table = AdbRouteTable()
    scans = []
    gate = threading.Barrier(8)

    def discover(serial):
        scans.append(serial)
        return E5038

    def worker():
        gate.wait()
        table.resolve("A", discover)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert scans == ["A"]
    assert table.get("A").endpoint == E5038


def test_concurrent_commands_for_uncached_serial_scan_once(two_servers):
    two_servers.devices[5038] = ["A"]
    gate = threading.Barrier(6)

    def worker():
        gate.wait()
        adb_mod._run("shell", "true", serial="A")

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert two_servers.scans == [5037, 5038]
    assert len(two_servers.commands) == 6


# ── helpers ──────────────────────────────────────────────────────────────────


def _force_result(monkeypatch, world, output: str, returncode: int) -> None:
    """Pin every dispatched command to one fixed ADB result."""

    class _Result:
        def __init__(self):
            self.output = output
            self.returncode = returncode
            self.timed_out = False
            self.transport = "fake"

    class _Scheduler:
        def run(self, args, *, serial, timeout, lane):
            world.commands.append((serial, tuple(args), 0))
            return _Result()

    monkeypatch.setattr(adb_mod, "_get_adb_scheduler", lambda: _Scheduler())


# ── duplicate ownership ──────────────────────────────────────────────────────


def test_single_endpoint_move_is_not_reported_as_a_conflict():
    table = AdbRouteTable()
    table.set("A", E5037)
    table.set("A", E5038)
    assert table.stats().get("conflicts", 0) == 0
    assert table.get("A").endpoint == E5038


def test_serial_claimed_by_both_servers_is_recorded_as_a_conflict(caplog):
    table = AdbRouteTable()
    table.set("A", E5037)
    # Two trackers taking turns: the route flips back inside the window.
    table.set("A", E5038)
    with caplog.at_level("WARNING", logger="relay.adb.routes"):
        table.set("A", E5037)
    assert table.stats()["conflicts"] == 1
    assert "device route conflict serial=A" in caplog.text


def test_conflict_counter_resets_with_the_table():
    table = AdbRouteTable()
    table.set("A", E5037)
    table.set("A", E5038)
    table.set("A", E5037)
    assert table.stats()["conflicts"] == 1
    table.clear()
    table.set("A", E5037)
    table.set("A", E5038)
    assert table.stats().get("conflicts", 0) == 0


# ── atx forward reconcile across endpoints ───────────────────────────────────


def test_forward_list_is_gathered_from_every_endpoint(two_servers, monkeypatch):
    """A forward lives on the server that owns the phone.

    Asking only the first endpoint reports nothing for phones on the second, and
    the caller reads that absence as "forward is gone".
    """
    forwards = {
        5037: "A tcp:9001 tcp:7912\n",
        5038: "B tcp:9002 tcp:7912\n",
    }

    def run_raw(args, timeout=5):
        argv = list(args)
        port = int(argv[argv.index("-P") + 1])
        two_servers.scans.append(port)
        return forwards[port], 0

    monkeypatch.setattr(adb_mod, "_run_raw", run_raw)
    discovered = adb_mod._list_atx_forwards_all_endpoints()
    assert discovered == {
        "A": ("127.0.0.1", 9001),
        "B": ("127.0.0.1", 9002),
    }


def test_forward_list_survives_one_dead_endpoint(two_servers, monkeypatch):
    def run_raw(args, timeout=5):
        argv = list(args)
        port = int(argv[argv.index("-P") + 1])
        if port == 5037:
            return "cannot connect to daemon", 1
        return "B tcp:9002 tcp:7912\n", 0

    monkeypatch.setattr(adb_mod, "_run_raw", run_raw)
    assert adb_mod._list_atx_forwards_all_endpoints() == {"B": ("127.0.0.1", 9002)}


def test_forward_list_reports_no_answer_distinctly_from_no_forwards(
    two_servers, monkeypatch
):
    """`None` must not be read as "every forward disappeared"."""
    monkeypatch.setattr(
        adb_mod, "_run_raw", lambda args, timeout=5: ("cannot connect", 1)
    )
    assert adb_mod._list_atx_forwards_all_endpoints() is None

    monkeypatch.setattr(adb_mod, "_run_raw", lambda args, timeout=5: ("", 0))
    assert adb_mod._list_atx_forwards_all_endpoints() == {}


def test_reconcile_keeps_cache_when_no_endpoint_answers(two_servers, monkeypatch):
    adb_mod._ATX_FORWARD_CACHE["A"] = ("127.0.0.1", 9001)
    monkeypatch.setattr(
        adb_mod, "_run_raw", lambda args, timeout=5: ("cannot connect", 1)
    )
    try:
        assert adb_mod.reconcile_atx_forward_cache({"A"}) == {}
        assert adb_mod._ATX_FORWARD_CACHE["A"] == ("127.0.0.1", 9001)
    finally:
        adb_mod._ATX_FORWARD_CACHE.pop("A", None)


def test_reconcile_finds_a_forward_that_lives_on_the_second_server(
    two_servers, monkeypatch
):
    """The behaviour fix, at the public API.

    Before: `forward --list` was asked of the first endpoint only, so a phone on
    the second one looked like it had lost its forward on every pass.
    """
    adb_mod.route_table.set("B", E5038)

    def run_raw(args, timeout=5):
        argv = list(args)
        port = int(argv[argv.index("-P") + 1])
        if port == 5038:
            return "B tcp:9002 tcp:7912\n", 0
        return "", 0

    monkeypatch.setattr(adb_mod, "_run_raw", run_raw)
    monkeypatch.setattr(
        adb_mod,
        "_run",
        lambda *a, **k: pytest.fail("must not fall back to a single endpoint"),
    )
    try:
        assert adb_mod.reconcile_atx_forward_cache({"B"}) == {"B": ("127.0.0.1", 9002)}
        assert adb_mod._ATX_FORWARD_CACHE["B"] == ("127.0.0.1", 9002)
    finally:
        adb_mod._ATX_FORWARD_CACHE.pop("B", None)


def test_route_discovery_does_not_consume_the_usb_budget(two_servers, monkeypatch):
    """`adb devices` asks the ADB server; it never touches USB.

    The heavy lane rations USB bandwidth between pushes and installs, and is
    squeezed to one global slot whenever a STARTUP command is queued. Charging a
    ~10ms host query to that slot lets one in-flight APK push stall every route
    lookup in the process.
    """
    import contextlib

    lanes: list[adb_mod.AdbLane] = []

    @contextlib.contextmanager
    def recording_admission(*, serial, lane):
        lanes.append(lane)
        yield

    monkeypatch.setattr(adb_mod, "adb_admission", recording_admission)
    two_servers.devices[5038] = ["B"]

    assert adb_mod._discover_route("B") == E5038
    assert lanes, "discovery took no admission at all"
    heavy = [lane for lane in lanes if lane.heavy]
    assert not heavy, f"discovery took the USB budget: {heavy}"
