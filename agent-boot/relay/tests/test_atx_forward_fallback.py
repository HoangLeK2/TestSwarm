from __future__ import annotations

import threading

from relay import agent as agent_mod
from relay.agent import RelayAgent, _atx_forward_host


class _FakePool:
    def __init__(self, *, fail_calls: set[int] | None = None) -> None:
        self.fail_calls = fail_calls if fail_calls is not None else {1}
        self.calls: list[tuple[str, int, str, str, bytes | None, float]] = []
        self.dropped: list[tuple[str, int]] = []

    def request(
        self,
        host: str,
        port: int,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 10.0,
    ) -> tuple[int, dict[str, str], bytes]:
        self.calls.append((host, port, method, path, body, timeout))
        if len(self.calls) in self.fail_calls:
            raise TimeoutError("timed out")
        return 200, {"Content-Type": "text/plain"}, b"pong"

    def drop_host(self, host: str, port: int) -> None:
        self.dropped.append((host, port))


def _agent(*, lan_probe_interval_s: float = 0.0) -> RelayAgent:
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="r1",
        relay_mode="grpc",
    )
    agent._atx_lan_probe_interval_s = lan_probe_interval_s
    return agent


def test_execute_command_runs_adb_reverse_tcp(monkeypatch):
    agent = _agent()
    agent._registry.on_adb_event("usb-serial", "device")
    calls: list[tuple[tuple[str, ...], str | None, int]] = []

    def fake_run(*args: str, serial: str | None = None, timeout: int = 30):
        calls.append((args, serial, timeout))
        return "8081\n", 0

    monkeypatch.setattr(agent_mod, "_run", fake_run, raising=False)

    result = agent_mod.loads(
        agent._execute_command(
            "msg-1",
            "usb-serial",
            agent_mod.dumps({"remote_port": 8081, "local_port": 8081}),
            10,
            agent_mod.CMD_REVERSE_TCP,
        )
    )

    assert result["ok"] is True
    assert result["msg_id"] == "msg-1"
    assert calls == [(("reverse", "tcp:8081", "tcp:8081"), "usb-serial", 10)]


def test_atx_forward_host_prefers_explicit_override(monkeypatch):
    monkeypatch.setenv("ATX_FORWARD_HOST", "10.0.0.10")
    monkeypatch.setenv("ADB_SERVER_SOCKET", "tcp:host.docker.internal:5037")

    assert _atx_forward_host() == "10.0.0.10"


def test_atx_forward_host_uses_remote_adb_host(monkeypatch):
    monkeypatch.delenv("ATX_FORWARD_HOST", raising=False)
    monkeypatch.setenv("ADB_SERVER_SOCKET", "tcp:host.docker.internal:5037")

    assert _atx_forward_host() == "host.docker.internal"


def test_atx_forward_host_falls_back_to_localhost(monkeypatch):
    monkeypatch.delenv("ATX_FORWARD_HOST", raising=False)
    monkeypatch.delenv("ADB_SERVER_SOCKET", raising=False)
    monkeypatch.delenv("ADB_HOST", raising=False)

    assert _atx_forward_host() == "127.0.0.1"


def test_u2_http_uses_adb_forward_first_for_remote_adb_usb_serial(monkeypatch):
    agent = _agent()
    pool = _FakePool(fail_calls=set())
    forwards: list[tuple[tuple[str, ...], str | None, int]] = []

    def fake_run(*args: str, serial: str | None = None, timeout: int = 30):
        forwards.append((args, serial, timeout))
        if args == ("forward", "tcp:0", "tcp:7912"):
            return "43210\n", 0
        raise AssertionError(f"unexpected adb call: {args!r}")

    monkeypatch.setattr(agent_mod, "_run", fake_run, raising=False)
    monkeypatch.setattr("relay.http_pool.default_pool", lambda: pool)
    monkeypatch.setenv("ADB_SERVER_SOCKET", "tcp:host.docker.internal:5037")
    agent._atx_lan_host_cache["usb-serial"] = "192.168.105.63"

    result = agent._do_u2_http(
        "usb-serial",
        "GET",
        "/ping",
        "",
        "application/json",
        2.0,
    )

    assert result == {
        "ok": True,
        "status": 200,
        "body": "pong",
        "content_type": "text/plain",
    }
    assert pool.calls == [("host.docker.internal", 43210, "GET", "/ping", None, 2.0)]
    assert forwards == [(("forward", "tcp:0", "tcp:7912"), "usb-serial", 10)]


def test_u2_http_forward_first_preserves_body_headers_and_timeout(monkeypatch):
    agent = _agent()
    pool = _FakePool(fail_calls=set())
    forwards: list[tuple[tuple[str, ...], str | None, int]] = []

    def fake_run(*args: str, serial: str | None = None, timeout: int = 30):
        forwards.append((args, serial, timeout))
        return "43210\r\n", 0

    monkeypatch.setattr(agent_mod, "_run", fake_run, raising=False)
    monkeypatch.setattr("relay.http_pool.default_pool", lambda: pool)
    monkeypatch.setenv("ADB_SERVER_SOCKET", "tcp:host.docker.internal:5037")
    agent._atx_lan_host_cache["usb-serial"] = "192.168.105.63"

    result = agent._do_u2_http(
        "usb-serial",
        "POST",
        "/jsonrpc/0",
        '{"jsonrpc":"2.0"}',
        "application/json",
        7.5,
    )

    assert result["ok"] is True
    assert pool.calls == [
        (
            "host.docker.internal",
            43210,
            "POST",
            "/jsonrpc/0",
            b'{"jsonrpc":"2.0"}',
            7.5,
        ),
    ]
    assert forwards == [(("forward", "tcp:0", "tcp:7912"), "usb-serial", 10)]


def test_atx_forward_creation_runs_in_parallel_for_different_serials(monkeypatch):
    agent = _agent()
    barrier = threading.Barrier(2)
    barrier_broken = threading.Event()
    calls: list[str | None] = []
    calls_lock = threading.Lock()

    def fake_run(*args: str, serial: str | None = None, timeout: int = 30):
        assert args == ("forward", "tcp:0", "tcp:7912")
        assert timeout == 10
        with calls_lock:
            calls.append(serial)
        try:
            barrier.wait(timeout=1.0)
        except threading.BrokenBarrierError:
            barrier_broken.set()
        return {"usb-a": "43001\n", "usb-b": "43002\n"}[serial or ""], 0

    monkeypatch.setattr(agent_mod, "_run", fake_run, raising=False)

    results: dict[str, tuple[str, int] | None] = {}
    threads = [
        threading.Thread(
            target=lambda serial=serial: results.setdefault(
                serial,
                agent._ensure_atx_forward_endpoint(serial),
            )
        )
        for serial in ("usb-a", "usb-b")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2.0)

    assert barrier_broken.is_set() is False
    assert sorted(calls) == ["usb-a", "usb-b"]
    assert results == {
        "usb-a": ("127.0.0.1", 43001),
        "usb-b": ("127.0.0.1", 43002),
    }


def test_atx_forward_creation_honors_global_create_limit(monkeypatch):
    agent = _agent()
    agent._atx_forward_create_limit = 1
    agent._atx_forward_create_sem = threading.BoundedSemaphore(1)
    first_entered = threading.Event()
    second_entered = threading.Event()
    release_first = threading.Event()
    calls: list[str | None] = []
    calls_lock = threading.Lock()

    def fake_run(*args: str, serial: str | None = None, timeout: int = 30):
        assert args == ("forward", "tcp:0", "tcp:7912")
        assert timeout == 10
        with calls_lock:
            calls.append(serial)
        if serial == "usb-a":
            first_entered.set()
            release_first.wait(timeout=1.0)
            return "43001\n", 0
        second_entered.set()
        return "43002\n", 0

    monkeypatch.setattr(agent_mod, "_run", fake_run, raising=False)

    results: dict[str, tuple[str, int] | None] = {}
    first = threading.Thread(
        target=lambda: results.setdefault(
            "usb-a",
            agent._ensure_atx_forward_endpoint("usb-a"),
        )
    )
    second = threading.Thread(
        target=lambda: results.setdefault(
            "usb-b",
            agent._ensure_atx_forward_endpoint("usb-b"),
        )
    )

    first.start()
    assert first_entered.wait(timeout=1.0)
    second.start()
    assert second_entered.wait(timeout=0.05) is False
    release_first.set()
    first.join(timeout=2.0)
    second.join(timeout=2.0)

    assert calls == ["usb-a", "usb-b"]
    assert results == {
        "usb-a": ("127.0.0.1", 43001),
        "usb-b": ("127.0.0.1", 43002),
    }
    stats = agent._u2_forward_stats_snapshot(reset=False)
    assert stats["create_limit"] == 1
    assert stats["create_peak_inflight"] == 1
    assert stats["created"] == 2


def test_atx_forward_creation_coalesces_same_serial(monkeypatch):
    agent = _agent()
    release = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def fake_run(*args: str, serial: str | None = None, timeout: int = 30):
        nonlocal calls
        assert args == ("forward", "tcp:0", "tcp:7912")
        assert serial == "usb-serial"
        assert timeout == 10
        with calls_lock:
            calls += 1
        release.wait(timeout=1.0)
        return "43001\n", 0

    monkeypatch.setattr(agent_mod, "_run", fake_run, raising=False)

    results: list[tuple[str, int] | None] = []
    threads = [
        threading.Thread(
            target=lambda: results.append(
                agent._ensure_atx_forward_endpoint("usb-serial")
            )
        )
        for _index in range(2)
    ]
    for thread in threads:
        thread.start()
    release.set()
    for thread in threads:
        thread.join(timeout=2.0)

    assert calls == 1
    assert results == [("127.0.0.1", 43001), ("127.0.0.1", 43001)]
    stats = agent._u2_forward_stats_snapshot(reset=True)
    assert stats["created"] == 1
    assert stats["create_joined"] == 1


def test_atx_forward_creation_cools_down_repeated_failures(monkeypatch):
    agent = _agent()
    agent._atx_forward_create_failure_cooldown_s = 5.0
    now = 100.0
    calls = 0

    def fake_monotonic() -> float:
        return now

    def fake_run(*args: str, serial: str | None = None, timeout: int = 30):
        nonlocal calls
        assert args == ("forward", "tcp:0", "tcp:7912")
        assert serial == "usb-serial"
        assert timeout == 10
        calls += 1
        return "cannot bind", 1

    monkeypatch.setattr(agent_mod, "_run", fake_run, raising=False)
    monkeypatch.setattr(agent_mod.time, "monotonic", fake_monotonic)

    assert agent._ensure_atx_forward_endpoint("usb-serial") is None
    assert agent._ensure_atx_forward_endpoint("usb-serial") is None
    now = 106.0
    assert agent._ensure_atx_forward_endpoint("usb-serial") is None

    assert calls == 2
    stats = agent._u2_forward_stats_snapshot(reset=True)
    assert stats["create_failed"] == 2
    assert stats["create_cooldown_skip"] == 1


def test_u2_http_lan_first_mode_still_falls_back_to_adb_forward(monkeypatch):
    agent = _agent()
    pool = _FakePool()
    forwards: list[tuple[tuple[str, ...], str | None, int]] = []

    def fake_run(*args: str, serial: str | None = None, timeout: int = 30):
        forwards.append((args, serial, timeout))
        if args == ("forward", "tcp:0", "tcp:7912"):
            return "43210\n", 0
        raise AssertionError(f"unexpected adb call: {args!r}")

    monkeypatch.setattr(agent_mod, "_run", fake_run, raising=False)
    monkeypatch.setattr("relay.http_pool.default_pool", lambda: pool)
    monkeypatch.setenv("AGENT_BOOT_U2_FORWARD_MODE", "lan_first")
    monkeypatch.setenv("ADB_SERVER_SOCKET", "tcp:host.docker.internal:5037")
    agent._atx_lan_host_cache["usb-serial"] = "192.168.105.63"

    result = agent._do_u2_http(
        "usb-serial",
        "GET",
        "/ping",
        "",
        "application/json",
        2.0,
    )

    assert result["ok"] is True
    assert pool.calls == [
        ("192.168.105.63", 7912, "GET", "/ping", None, 2.0),
        ("host.docker.internal", 43210, "GET", "/ping", None, 2.0),
    ]
    assert forwards == [(("forward", "tcp:0", "tcp:7912"), "usb-serial", 10)]


def test_u2_http_uses_cached_forward_without_lan_retry(monkeypatch):
    agent = _agent()
    pool = _FakePool(fail_calls=set())
    forwards: list[tuple[tuple[str, ...], str | None, int]] = []
    agent._atx_forward_cache["usb-serial"] = ("host.docker.internal", 43210)
    agent._atx_lan_host_cache["usb-serial"] = "192.168.105.63"

    def fake_run(*args: str, serial: str | None = None, timeout: int = 30):
        forwards.append((args, serial, timeout))
        return "unexpected", 1

    monkeypatch.setattr(agent_mod, "_run", fake_run, raising=False)
    monkeypatch.setattr("relay.http_pool.default_pool", lambda: pool)

    result = agent._do_u2_http(
        "usb-serial",
        "GET",
        "/ping",
        "",
        "application/json",
        2.0,
    )

    assert result["ok"] is True
    assert pool.calls == [("host.docker.internal", 43210, "GET", "/ping", None, 2.0)]
    assert forwards == []


def test_u2_http_uses_cached_lan_route_without_adb_forward(monkeypatch):
    agent = _agent()
    pool = _FakePool(fail_calls=set())
    forwards: list[tuple[tuple[str, ...], str | None, int]] = []
    agent._atx_u2_route_cache["usb-serial"] = "lan"
    agent._atx_forward_cache["usb-serial"] = ("host.docker.internal", 43210)
    agent._atx_lan_host_cache["usb-serial"] = "192.168.105.63"

    def fake_run(*args: str, serial: str | None = None, timeout: int = 30):
        forwards.append((args, serial, timeout))
        return "unexpected", 1

    monkeypatch.setattr(agent_mod, "_run", fake_run, raising=False)
    monkeypatch.setattr("relay.http_pool.default_pool", lambda: pool)
    monkeypatch.setenv("ADB_SERVER_SOCKET", "tcp:host.docker.internal:5037")

    result = agent._do_u2_http(
        "usb-serial",
        "GET",
        "/ping",
        "",
        "application/json",
        2.0,
    )

    assert result["ok"] is True
    assert pool.calls == [("192.168.105.63", 7912, "GET", "/ping", None, 2.0)]
    assert forwards == []
    assert agent._atx_u2_route_cache["usb-serial"] == "lan"


def test_u2_http_lan_route_failure_falls_back_to_adb_forward(monkeypatch):
    agent = _agent()
    pool = _FakePool(fail_calls={1})
    forwards: list[tuple[tuple[str, ...], str | None, int]] = []
    agent._atx_u2_route_cache["usb-serial"] = "lan"
    agent._atx_lan_host_cache["usb-serial"] = "192.168.105.63"

    def fake_run(*args: str, serial: str | None = None, timeout: int = 30):
        forwards.append((args, serial, timeout))
        if args == ("forward", "tcp:0", "tcp:7912"):
            return "43210\n", 0
        raise AssertionError(f"unexpected adb call: {args!r}")

    monkeypatch.setattr(agent_mod, "_run", fake_run, raising=False)
    monkeypatch.setattr("relay.http_pool.default_pool", lambda: pool)
    monkeypatch.setenv("ADB_SERVER_SOCKET", "tcp:host.docker.internal:5037")

    result = agent._do_u2_http(
        "usb-serial",
        "GET",
        "/ping",
        "",
        "application/json",
        2.0,
    )

    assert result["ok"] is True
    assert pool.calls == [
        ("192.168.105.63", 7912, "GET", "/ping", None, 2.0),
        ("host.docker.internal", 43210, "GET", "/ping", None, 2.0),
    ]
    assert forwards == [(("forward", "tcp:0", "tcp:7912"), "usb-serial", 10)]
    assert agent._atx_u2_route_cache["usb-serial"] == "forward"


def test_u2_http_does_not_adb_forward_for_tcp_serial(monkeypatch):
    agent = _agent()
    pool = _FakePool()
    forwards: list[tuple[tuple[str, ...], str | None, int]] = []

    def fake_run(*args: str, serial: str | None = None, timeout: int = 30):
        forwards.append((args, serial, timeout))
        return "unexpected", 1

    monkeypatch.setattr(agent_mod, "_run", fake_run, raising=False)
    monkeypatch.setattr("relay.http_pool.default_pool", lambda: pool)

    result = agent._do_u2_http(
        "192.168.105.63:5555",
        "GET",
        "/ping",
        "",
        "application/json",
        2.0,
    )

    assert result["ok"] is False
    assert result["status"] == 0
    assert "timed out" in result["body"]
    assert forwards == []
    assert pool.calls == [("192.168.105.63", 7912, "GET", "/ping", None, 2.0)]


def test_u2_http_keeps_cached_forward_after_one_transient_failure(monkeypatch):
    agent = _agent()
    pool = _FakePool()
    forwards: list[tuple[tuple[str, ...], str | None, int]] = []
    agent._atx_forward_cache["usb-serial"] = ("host.docker.internal", 11111)

    def fake_run(*args: str, serial: str | None = None, timeout: int = 30):
        forwards.append((args, serial, timeout))
        if args == ("forward", "--remove", "tcp:11111"):
            return "", 0
        if args == ("forward", "tcp:0", "tcp:7912"):
            return "43210\n", 0
        raise AssertionError(f"unexpected adb call: {args!r}")

    monkeypatch.setattr(agent_mod, "_run", fake_run, raising=False)
    monkeypatch.setattr("relay.http_pool.default_pool", lambda: pool)
    monkeypatch.setenv("ADB_SERVER_SOCKET", "tcp:host.docker.internal:5037")

    result = agent._do_u2_http(
        "usb-serial",
        "GET",
        "/ping",
        "",
        "application/json",
        2.0,
    )

    assert result["ok"] is True
    assert pool.calls == [
        ("host.docker.internal", 11111, "GET", "/ping", None, 2.0),
        ("host.docker.internal", 11111, "GET", "/ping", None, 2.0),
    ]
    assert forwards == []
    assert pool.dropped == [("host.docker.internal", 11111)]
    assert agent._atx_forward_cache["usb-serial"] == ("host.docker.internal", 11111)


def test_u2_http_recreates_forward_after_failure_threshold(monkeypatch):
    monkeypatch.setenv("AGENT_BOOT_U2_FORWARD_FAILURES_BEFORE_RECREATE", "1")
    agent = _agent()
    pool = _FakePool()
    forwards: list[tuple[tuple[str, ...], str | None, int]] = []
    agent._atx_forward_cache["usb-serial"] = ("host.docker.internal", 11111)

    def fake_run(*args: str, serial: str | None = None, timeout: int = 30):
        forwards.append((args, serial, timeout))
        if args == ("forward", "--remove", "tcp:11111"):
            return "", 0
        if args == ("forward", "tcp:0", "tcp:7912"):
            return "43210\n", 0
        raise AssertionError(f"unexpected adb call: {args!r}")

    monkeypatch.setattr(agent_mod, "_run", fake_run, raising=False)
    monkeypatch.setattr("relay.http_pool.default_pool", lambda: pool)
    monkeypatch.setenv("ADB_SERVER_SOCKET", "tcp:host.docker.internal:5037")

    result = agent._do_u2_http(
        "usb-serial",
        "GET",
        "/ping",
        "",
        "application/json",
        2.0,
    )

    assert result["ok"] is True
    assert pool.calls == [
        ("host.docker.internal", 11111, "GET", "/ping", None, 2.0),
        ("host.docker.internal", 43210, "GET", "/ping", None, 2.0),
    ]
    assert forwards == [
        (("forward", "--remove", "tcp:11111"), "usb-serial", 5),
        (("forward", "tcp:0", "tcp:7912"), "usb-serial", 10),
    ]
    assert pool.dropped == [("host.docker.internal", 11111)]


def test_u2_http_returns_original_error_when_forward_creation_fails(monkeypatch):
    agent = _agent()
    pool = _FakePool()
    forwards: list[tuple[tuple[str, ...], str | None, int]] = []
    agent._atx_lan_host_cache["usb-serial"] = "192.168.105.63"

    def fake_run(*args: str, serial: str | None = None, timeout: int = 30):
        forwards.append((args, serial, timeout))
        return "cannot bind", 1

    monkeypatch.setattr(agent_mod, "_run", fake_run, raising=False)
    monkeypatch.setattr("relay.http_pool.default_pool", lambda: pool)

    result = agent._do_u2_http(
        "usb-serial",
        "GET",
        "/ping",
        "",
        "application/json",
        2.0,
    )

    assert result["ok"] is False
    assert result["status"] == 0
    assert result["body"] == "timed out"
    assert agent._atx_forward_cache == {}
    assert forwards == [(("forward", "tcp:0", "tcp:7912"), "usb-serial", 10)]


def test_u2_http_returns_original_error_when_forward_output_has_no_port(monkeypatch):
    agent = _agent()
    pool = _FakePool()
    agent._atx_lan_host_cache["usb-serial"] = "192.168.105.63"

    def fake_run(*args: str, serial: str | None = None, timeout: int = 30):
        return "ok but no port", 0

    monkeypatch.setattr(agent_mod, "_run", fake_run, raising=False)
    monkeypatch.setattr("relay.http_pool.default_pool", lambda: pool)

    result = agent._do_u2_http(
        "usb-serial",
        "GET",
        "/ping",
        "",
        "application/json",
        2.0,
    )

    assert result["ok"] is False
    assert result["status"] == 0
    assert result["body"] == "timed out"
    assert agent._atx_forward_cache == {}


def test_u2_http_keeps_new_forward_when_first_forwarded_request_fails(monkeypatch):
    agent = _agent()
    pool = _FakePool(fail_calls={1, 2})
    forwards: list[tuple[tuple[str, ...], str | None, int]] = []
    agent._atx_lan_host_cache["usb-serial"] = "192.168.105.63"

    def fake_run(*args: str, serial: str | None = None, timeout: int = 30):
        forwards.append((args, serial, timeout))
        if args == ("forward", "tcp:0", "tcp:7912"):
            return "43210\n", 0
        if args == ("forward", "--remove", "tcp:43210"):
            return "", 0
        raise AssertionError(f"unexpected adb call: {args!r}")

    monkeypatch.setattr(agent_mod, "_run", fake_run, raising=False)
    monkeypatch.setattr("relay.http_pool.default_pool", lambda: pool)
    monkeypatch.setenv("ADB_SERVER_SOCKET", "tcp:host.docker.internal:5037")

    result = agent._do_u2_http(
        "usb-serial",
        "GET",
        "/ping",
        "",
        "application/json",
        2.0,
    )

    assert result["ok"] is False
    assert result["status"] == 0
    assert result["body"] == "timed out"
    assert agent._atx_forward_cache["usb-serial"] == ("host.docker.internal", 43210)
    assert pool.dropped == [("host.docker.internal", 43210)]
    assert forwards == [(("forward", "tcp:0", "tcp:7912"), "usb-serial", 10)]


def test_clear_atx_forward_removes_adb_rule_and_drops_pool(monkeypatch):
    agent = _agent()
    pool = _FakePool(fail_calls=set())
    forwards: list[tuple[tuple[str, ...], str | None, int]] = []
    agent._atx_forward_cache["usb-serial"] = ("host.docker.internal", 43210)

    def fake_run(*args: str, serial: str | None = None, timeout: int = 30):
        forwards.append((args, serial, timeout))
        return "", 0

    monkeypatch.setattr(agent_mod, "_run", fake_run, raising=False)
    monkeypatch.setattr("relay.http_pool.default_pool", lambda: pool)

    agent._clear_atx_forward("usb-serial")

    assert agent._atx_forward_cache == {}
    assert pool.dropped == [("host.docker.internal", 43210)]
    assert forwards == [(("forward", "--remove", "tcp:43210"), "usb-serial", 5)]


def test_lan_route_probe_promotes_lan_and_removes_adb_forward(monkeypatch):
    agent = _agent()
    pool = _FakePool(fail_calls=set())
    forwards: list[tuple[tuple[str, ...], str | None, int]] = []
    agent._atx_forward_cache["usb-serial"] = ("host.docker.internal", 43210)
    agent._atx_u2_route_cache["usb-serial"] = "forward"
    agent._atx_lan_host_cache["usb-serial"] = "192.168.105.63"

    def fake_run(*args: str, serial: str | None = None, timeout: int = 30):
        forwards.append((args, serial, timeout))
        if args == ("forward", "--remove", "tcp:43210"):
            return "", 0
        raise AssertionError(f"unexpected adb call: {args!r}")

    monkeypatch.setattr(agent_mod, "_run", fake_run, raising=False)
    monkeypatch.setattr("relay.http_pool.default_pool", lambda: pool)

    assert agent._probe_atx_lan_route_once("usb-serial") is True

    assert pool.calls == [
        ("192.168.105.63", 7912, "GET", "/ping", None, 0.25),
    ]
    assert agent._atx_u2_route_cache["usb-serial"] == "lan"
    assert agent._atx_forward_cache == {}
    assert pool.dropped == [("host.docker.internal", 43210)]
    assert forwards == [(("forward", "--remove", "tcp:43210"), "usb-serial", 5)]
