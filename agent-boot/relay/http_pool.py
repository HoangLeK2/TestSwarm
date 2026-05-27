"""
relay/http_pool.py — Lightweight HTTP/1.1 keep-alive pool for atx-agent calls.

Why:
  `urllib.request.urlopen` opens a fresh TCP socket per call. On WiFi-attached
  phones each connection costs ~30-100ms in TCP handshake, which dominates
  short atx-agent requests like /dump/hierarchy, /tap, /info. On a 40-phone
  fleet doing 5+ u2 HTTP calls / sec / device, that's seconds of pure
  handshake latency stacked on top of the work — visible as slow scenarios
  and inflated thread pool occupation.

  atx-agent (Go) supports HTTP/1.1 keep-alive natively. Reusing one
  connection per (host, port) cuts setup cost to ~0 for the warm case and
  meaningfully reduces ADB-forward churn.

Design:
  - LIFO pool per (host, port): hot connections stay warm.
  - Per-host bounded size (default 4). Worker threads check out → use →
    return; if the pool is full on return, the connection is closed.
  - Connection is automatically discarded on transport error so the next
    call retries with a fresh socket. atx-agent occasionally drops idle
    sockets after a few minutes of silence; we treat that as a soft retry.
  - Thread-safe: uses `queue.LifoQueue`, which has a C-level lock.
  - No external deps — stdlib `http.client` only.
"""
from __future__ import annotations

import http.client
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("relay.http_pool")


# Max idle connections kept per (host, port). 4 covers the realistic fan-out
# from the adb thread pool to one device — most devices are touched by one
# worker at a time, but bursts (extra_data dump + a11y tap) can use 2-3.
_POOL_PER_HOST = max(1, int(os.getenv("RELAY_HTTP_POOL_PER_HOST", "4")))

# How long a connection may sit idle before we discard it on next checkout.
# atx-agent's default keep-alive timeout is ~90s; staying well below avoids
# the "Connection reset" race where Go closed the socket between checkout
# and request.
_POOL_IDLE_TTL_S = max(5.0, float(os.getenv("RELAY_HTTP_POOL_IDLE_TTL_S", "30.0")))


@dataclass
class _PooledConn:
    conn: http.client.HTTPConnection
    last_used: float = field(default_factory=time.monotonic)


class _HostPool:
    __slots__ = ("host", "port", "pool")

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.pool: queue.LifoQueue[_PooledConn] = queue.LifoQueue(maxsize=_POOL_PER_HOST)

    def acquire(self, timeout: float) -> http.client.HTTPConnection:
        # Try LIFO checkout. If idle TTL exceeded, drop and create new.
        while True:
            try:
                entry = self.pool.get_nowait()
            except queue.Empty:
                return http.client.HTTPConnection(self.host, self.port, timeout=timeout)
            if (time.monotonic() - entry.last_used) > _POOL_IDLE_TTL_S:
                try:
                    entry.conn.close()
                except Exception:
                    pass
                continue
            # Apply caller's timeout to this checked-out connection.
            try:
                entry.conn.timeout = timeout
                sock = entry.conn.sock
                if sock is not None:
                    sock.settimeout(timeout)
            except Exception:
                pass
            return entry.conn

    def release(self, conn: http.client.HTTPConnection) -> None:
        try:
            self.pool.put_nowait(_PooledConn(conn=conn))
        except queue.Full:
            try:
                conn.close()
            except Exception:
                pass

    def discard(self, conn: http.client.HTTPConnection) -> None:
        try:
            conn.close()
        except Exception:
            pass


class HttpPool:
    """Per-process pool of HTTP/1.1 keep-alive connections, keyed by (host, port)."""

    def __init__(self) -> None:
        self._hosts: dict[tuple[str, int], _HostPool] = {}
        self._lock = threading.Lock()

    def _host_pool(self, host: str, port: int) -> _HostPool:
        key = (host, port)
        # Fast path without lock — dict reads are atomic in CPython.
        hp = self._hosts.get(key)
        if hp is not None:
            return hp
        with self._lock:
            hp = self._hosts.get(key)
            if hp is None:
                hp = _HostPool(host, port)
                self._hosts[key] = hp
            return hp

    def request(
        self,
        host: str,
        port: int,
        method: str,
        path: str,
        body: Optional[bytes] = None,
        headers: Optional[dict[str, str]] = None,
        timeout: float = 10.0,
    ) -> tuple[int, dict[str, str], bytes]:
        """
        Execute one HTTP/1.1 request and return (status, headers, body).

        Raises on transport-level failure. atx-agent error responses are
        returned with their actual status; only TCP/socket errors raise.
        """
        hp = self._host_pool(host, port)
        # Two attempts: a stale keep-alive socket can reset on first request.
        # The second attempt always uses a fresh connection.
        last_exc: Exception | None = None
        for attempt in (1, 2):
            conn = hp.acquire(timeout=timeout)
            try:
                conn.request(method, path, body=body, headers=headers or {})
                resp = conn.getresponse()
                data = resp.read()
                # Capture headers BEFORE the connection is reused — getheader
                # is bound to the response object.
                resp_headers = {k: v for k, v in resp.getheaders()}
                status = resp.status
                # If server signals close, do not return to pool.
                if resp_headers.get("Connection", "").lower() == "close":
                    hp.discard(conn)
                else:
                    hp.release(conn)
                return status, resp_headers, data
            except (http.client.HTTPException, OSError) as exc:
                hp.discard(conn)
                last_exc = exc
                if attempt == 1:
                    # Likely a stale keep-alive socket — retry with fresh conn.
                    continue
                raise
            except Exception:
                hp.discard(conn)
                raise
        # Unreachable, but quiet the type checker.
        raise last_exc if last_exc else RuntimeError("http_pool: unreachable")

    def drop_host(self, host: str, port: int) -> None:
        """Close and forget all connections for a (host, port) — call on device offline."""
        with self._lock:
            hp = self._hosts.pop((host, port), None)
        if hp is None:
            return
        # Drain queue and close everything.
        while True:
            try:
                entry = hp.pool.get_nowait()
            except queue.Empty:
                break
            try:
                entry.conn.close()
            except Exception:
                pass

    def stats(self) -> dict[str, int]:
        """For runtime stats logger — count of pooled conns per host."""
        with self._lock:
            return {
                f"{h}:{p}": hp.pool.qsize()
                for (h, p), hp in self._hosts.items()
            }


# Singleton — most callers don't need their own pool.
_DEFAULT_POOL: Optional[HttpPool] = None


def default_pool() -> HttpPool:
    global _DEFAULT_POOL
    if _DEFAULT_POOL is None:
        _DEFAULT_POOL = HttpPool()
    return _DEFAULT_POOL
