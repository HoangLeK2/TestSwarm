from __future__ import annotations

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


def _agent() -> RelayAgent:
    return RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="r1",
        relay_mode="grpc",
    )


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


def test_u2_http_falls_back_to_adb_forward_for_usb_serial(monkeypatch):
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
    assert pool.calls == [
        ("192.168.105.63", 7912, "GET", "/ping", None, 2.0),
        ("host.docker.internal", 43210, "GET", "/ping", None, 2.0),
    ]
    assert forwards == [(("forward", "tcp:0", "tcp:7912"), "usb-serial", 10)]


def test_u2_http_fallback_preserves_body_headers_and_timeout(monkeypatch):
    agent = _agent()
    pool = _FakePool()
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
            "192.168.105.63",
            7912,
            "POST",
            "/jsonrpc/0",
            b'{"jsonrpc":"2.0"}',
            7.5,
        ),
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


def test_u2_http_recreates_stale_adb_forward(monkeypatch):
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


def test_u2_http_clears_forward_when_forwarded_request_fails(monkeypatch):
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
    assert "adb-forward: timed out" in result["body"]
    assert agent._atx_forward_cache == {}
    assert pool.dropped == [("host.docker.internal", 43210)]
    assert forwards == [
        (("forward", "tcp:0", "tcp:7912"), "usb-serial", 10),
        (("forward", "--remove", "tcp:43210"), "usb-serial", 5),
    ]


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
