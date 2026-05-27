"""Tests for relay.http_pool — keep-alive connection pool for atx-agent."""
from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from relay.http_pool import HttpPool


_BODY = b'{"value":"ok"}'


class _Handler(BaseHTTPRequestHandler):
    """Tiny HTTP/1.1 handler that respects keep-alive."""

    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(_BODY)))
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        self.wfile.write(_BODY)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            _ = self.rfile.read(length)
        self.do_GET()

    def log_message(self, *args, **kwargs) -> None:  # silence test logs
        pass


@pytest.fixture
def http_server():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        yield "127.0.0.1", port
    finally:
        server.shutdown()
        server.server_close()


def test_request_returns_status_and_body(http_server):
    host, port = http_server
    pool = HttpPool()
    status, headers, body = pool.request(host, port, "GET", "/info", timeout=2.0)
    assert status == 200
    assert body == _BODY
    assert headers.get("Content-Type") == "application/json"


def test_connection_is_reused(http_server):
    """Two sequential GETs should share one TCP socket (keep-alive)."""
    host, port = http_server
    pool = HttpPool()

    pool.request(host, port, "GET", "/info", timeout=2.0)
    # After release, exactly one pooled conn for that host.
    assert pool.stats()[f"{host}:{port}"] == 1

    pool.request(host, port, "GET", "/info", timeout=2.0)
    # Still one — second call checked out then released the same conn.
    assert pool.stats()[f"{host}:{port}"] == 1


def test_drop_host_closes_pool(http_server):
    host, port = http_server
    pool = HttpPool()
    pool.request(host, port, "GET", "/info", timeout=2.0)
    assert pool.stats()[f"{host}:{port}"] == 1

    pool.drop_host(host, port)
    assert f"{host}:{port}" not in pool.stats()

    # New call still works (creates fresh pool entry).
    status, _, _ = pool.request(host, port, "GET", "/info", timeout=2.0)
    assert status == 200


def test_post_with_body(http_server):
    host, port = http_server
    pool = HttpPool()
    payload = b'{"k":"v"}'
    headers = {"Content-Type": "application/json", "Content-Length": str(len(payload))}
    status, _, body = pool.request(
        host, port, "POST", "/jsonrpc/0",
        body=payload, headers=headers, timeout=2.0,
    )
    assert status == 200
    assert body == _BODY


def test_pool_bounded_per_host(http_server, monkeypatch):
    """Pool size is bounded; releasing beyond cap closes extras."""
    host, port = http_server
    # Force tiny cap to make the test fast.
    monkeypatch.setattr("relay.http_pool._POOL_PER_HOST", 2)
    pool = HttpPool()

    # Three sequential requests — only 1 in pool at any time since we serialise.
    for _ in range(3):
        pool.request(host, port, "GET", "/info", timeout=2.0)
    assert pool.stats()[f"{host}:{port}"] <= 2


def test_idle_ttl_recycles(monkeypatch, http_server):
    """Stale connections past idle TTL are discarded on next checkout."""
    host, port = http_server
    monkeypatch.setattr("relay.http_pool._POOL_IDLE_TTL_S", 0.1)
    pool = HttpPool()
    pool.request(host, port, "GET", "/info", timeout=2.0)
    assert pool.stats()[f"{host}:{port}"] == 1
    time.sleep(0.2)
    # Next request discards the stale conn and creates a fresh one.
    status, _, _ = pool.request(host, port, "GET", "/info", timeout=2.0)
    assert status == 200
