"""
ws_tunnel.py — TCP-over-WebSocket tunnel (server side).

Replaces `adb forward tcp:PORT localabstract:minitouch` with a WebSocket tunnel.

Architecture:
  Tool (MinitouchSender / u2 / STFServiceClient)
    ↕ TCP (localhost:random_port)
  TcpWsTunnel  ←→  websocket  ←→  Agent on Android
    channel = "minitouch" | "u2" | "stfservice"

The Agent maintains a corresponding bridge:
  - minitouch channel: reads/writes minitouch unix socket
  - u2 channel: proxies HTTP to 127.0.0.1:9008 (uiautomator2 am instrument)
  - stfservice channel: reads/writes localabstract:stfservice socket

Message format (JSON over WebSocket):
  {"type": "tunnel_data", "channel": "minitouch", "data": "<base64>"}
"""
from __future__ import annotations

import base64
import logging
import socket
import threading
import time
from typing import Callable, Dict, Optional

log = logging.getLogger(__name__)


class TcpWsTunnel:
    """
    One TCP-over-WebSocket tunnel for a named channel (minitouch / u2 / stfservice).

    - Starts a local TCP server on a random port.
    - Waits for exactly one tool to connect (MinitouchSender / u2 / STFServiceClient).
    - Forwards: TCP → base64 → WS  and  WS → base64-decode → TCP.
    """

    def __init__(
        self,
        channel: str,
        send_ws: Callable[[Dict], None],
        serial: str = "",
    ) -> None:
        self.channel   = channel
        self._send_ws  = send_ws
        self._serial   = serial
        self._logger   = logging.getLogger(f"tunnel.{serial}.{channel}")

        self._server_sock: Optional[socket.socket] = None
        self._client_sock: Optional[socket.socket] = None
        self._client_lock  = threading.Lock()

        self._port   = 0
        self._running = False
        # Buffer data received from agent before a tool has connected
        self._pre_connect_buf: bytes = b""
        self._pre_connect_lock = threading.Lock()
        # Generation counter for U2: prevents stale response from old TCP connection
        # being written to a new TCP connection (NanoHTTPD closes after each response)
        self._conn_gen: int = 0    # incremented when new tool TCP connection accepted
        self._active_gen: int = 0  # set to _conn_gen when tool sends first data (request)

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self) -> int:
        """
        Bind a local TCP server to an OS-assigned port. Return the port number.
        Call this BEFORE telling the Agent which port to expect.
        """
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        self._port = srv.getsockname()[1]
        srv.listen(1)
        self._server_sock = srv
        self._running = True

        t = threading.Thread(
            target=self._accept_loop,
            daemon=True,
            name=f"tunnel-accept-{self._serial}-{self.channel}",
        )
        t.start()
        self._logger.info(f"Tunnel [{self.channel}] listening on port {self._port}")
        return self._port

    def stop(self) -> None:
        self._running = False
        if self._server_sock:
            try: self._server_sock.close()
            except Exception: pass
        with self._client_lock:
            if self._client_sock:
                try: self._client_sock.close()
                except Exception: pass
                self._client_sock = None

    @property
    def port(self) -> int:
        return self._port

    # ── From Agent → TCP tool ─────────────────────────────────────────────────

    def write_from_agent(self, b64_data: str) -> None:
        """
        Called when a tunnel_data message arrives from the agent.
        Decode and write to the local TCP tool socket.
        """
        data = base64.b64decode(b64_data)
        with self._client_lock:
            conn = self._client_sock
            # U2 generation gating: drop stale response from previous request cycle
            if self.channel == "u2":
                if conn is None:
                    return  # no tool connected → stale data, drop silently
                if self._active_gen != self._conn_gen:
                    return  # tool connected but hasn't sent request → stale data
        if conn is None:
            # Non-U2 channels: buffer for banner flush
            with self._pre_connect_lock:
                self._pre_connect_buf += data
            return
        try:
            conn.sendall(data)
        except OSError as exc:
            self._logger.debug(f"Tunnel [{self.channel}] write-to-tool error: {exc}")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _accept_loop(self) -> None:
        """Accept one tool connection, start reading from it."""
        assert self._server_sock is not None
        self._server_sock.settimeout(1.0)
        while self._running:
            try:
                conn, addr = self._server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self._logger.info(f"Tunnel [{self.channel}] tool connected from {addr}")
            with self._client_lock:
                if self._client_sock:
                    # For u2 the client uses HTTP keep-alive over a persistent TCP
                    # connection. Only one logical client exists at a time, so if a
                    # second TCP connection arrives it means the old one has already
                    # been replaced (e.g. after _session.close() during protocol
                    # detection). Do NOT force-close it here — the _read_loop will
                    # clean it up as soon as it receives EOF. Closing it early would
                    # corrupt any in-flight HTTP response.
                    if self.channel != "u2":
                        try: self._client_sock.close()
                        except Exception: pass
            if self.channel == "u2":
                # U2: clear stale buffer, increment generation, set client
                with self._pre_connect_lock:
                    stale = len(self._pre_connect_buf)
                    self._pre_connect_buf = b""
                if stale:
                    self._logger.debug(f"Tunnel [u2] discarded {stale}b stale buffer on new connection")
                with self._client_lock:
                    self._client_sock = conn
                    self._conn_gen += 1
                # _active_gen stays at old value until _read_loop reads first data
            elif self.channel == "minitouch":
                # Flush buffer BEFORE setting _client_sock so banner is sent first
                with self._pre_connect_lock:
                    buffered = self._pre_connect_buf
                    self._pre_connect_buf = b""
                if buffered:
                    self._logger.info(f"Tunnel [{self.channel}] flushing {len(buffered)}b pre-connect buffer")
                    try:
                        conn.sendall(buffered)
                    except OSError:
                        pass
                with self._pre_connect_lock:
                    more = self._pre_connect_buf
                    self._pre_connect_buf = b""
                if more:
                    try:
                        conn.sendall(more)
                    except OSError:
                        pass

            if self.channel == "minitouch" and not buffered and not more:
                # Banner not arrived yet; wait 2.5s for tunnel_data then set client and flush
                def _delayed_flush() -> None:
                    time.sleep(2.5)
                    with self._pre_connect_lock:
                        late = self._pre_connect_buf
                        self._pre_connect_buf = b""
                    with self._client_lock:
                        self._client_sock = conn
                    if late:
                        self._logger.info(f"Tunnel [minitouch] delayed flush {len(late)}b")
                        try:
                            conn.sendall(late)
                        except OSError:
                            pass
                threading.Thread(target=_delayed_flush, daemon=True, name=f"tunnel-delayed-{self._serial}-minitouch").start()
            elif self.channel not in ("u2", "minitouch"):
                # stfservice and other channels: set client + flush
                with self._pre_connect_lock:
                    buffered = self._pre_connect_buf
                    self._pre_connect_buf = b""
                if buffered:
                    self._logger.info(f"Tunnel [{self.channel}] flushing {len(buffered)}b pre-connect buffer")
                    try:
                        conn.sendall(buffered)
                    except OSError:
                        pass
                with self._client_lock:
                    self._client_sock = conn

            # Read loop in a new thread so accept_loop can accept re-connections
            t = threading.Thread(
                target=self._read_loop,
                args=(conn,),
                daemon=True,
                name=f"tunnel-read-{self._serial}-{self.channel}",
            )
            t.start()

    def _read_loop(self, conn: socket.socket) -> None:
        """Read from TCP tool, forward to WebSocket agent."""
        try:
            while self._running:
                data = conn.recv(8192)
                if not data:
                    break
                # U2: mark this connection as having sent a request → response data now valid
                if self.channel == "u2":
                    with self._client_lock:
                        self._active_gen = self._conn_gen
                b64 = base64.b64encode(data).decode("ascii")
                self._send_ws({
                    "type":    "tunnel_data",
                    "channel": self.channel,
                    "data":    b64,
                })
        except OSError as exc:
            self._logger.debug(f"Tunnel [{self.channel}] read-from-tool closed: {exc}")
        finally:
            with self._client_lock:
                if self._client_sock is conn:
                    self._client_sock = None
            # Clear stale pre-connect buffer — data from old connection must not
            # be flushed to the next connection (causes BadStatusLine / corruption)
            with self._pre_connect_lock:
                stale = len(self._pre_connect_buf)
                self._pre_connect_buf = b""
            if stale:
                self._logger.debug(f"Tunnel [{self.channel}] cleared {stale}b stale buffer on disconnect")
            self._logger.info(f"Tunnel [{self.channel}] tool disconnected")


class TunnelSet:
    """
    Manages all tunnels for one device session.
    Created when an agent connects, destroyed when it disconnects.

    minitouch channel: No longer uses TcpWsTunnel. MinitouchWsClient sends
    commands directly as tunnel_data WS messages (no TCP socket needed).
    We still include "minitouch" key in start_all() ports (value=0) so that
    the agent creates its ServiceTunnel for abstract:minitouchagent, which is
    needed for the server→agent command path.  Banner bytes from agent are
    drained silently (we don't need them).
    """

    CHANNELS = ("u2", "stfservice")  # minitouch uses direct WS, not TCP tunnel

    def __init__(self, send_ws: Callable[[Dict], None], serial: str) -> None:
        self._tunnels: Dict[str, TcpWsTunnel] = {}
        for ch in self.CHANNELS:
            self._tunnels[ch] = TcpWsTunnel(ch, send_ws, serial)

    def start_all(self) -> Dict[str, int]:
        """Start all tunnels, return {channel: port} mapping."""
        ports = {ch: t.start() for ch, t in self._tunnels.items()}
        # port=0: agent only checks presence of "minitouch" key (not the port value)
        ports["minitouch"] = 0
        return ports

    def stop_all(self) -> None:
        for t in self._tunnels.values():
            t.stop()

    def route(self, channel: str, b64_data: str) -> None:
        """Route incoming tunnel_data from agent to the correct tunnel."""
        if channel == "minitouch":
            # Banner bytes from MinitouchAgent — drain silently.
            # Commands flow in the opposite direction (MinitouchWsClient → WS → agent).
            return
        tunnel = self._tunnels.get(channel)
        if tunnel:
            tunnel.write_from_agent(b64_data)
        else:
            log.warning(f"Unknown tunnel channel: {channel!r}")

    def port(self, channel: str) -> int:
        return self._tunnels[channel].port
