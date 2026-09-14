"""
relay/device_watcher.py - real-time ADB device detection.

ADB track-devices pushes a full device-list snapshot on every change, with
latency <100ms vs the old polling heartbeat loop. In hybrid/adbutils mode the
watcher talks to the ADB server directly instead of spawning a long-lived adb
binary.

Protocol:
  Two output formats seen in the wild:
    (A) Plain:  "List of devices attached\\n<serial>\\t<state>\\n...\\n\\n"
    (B) Raw:    4-hex-length prefix then payload  (some ADB versions)
  Both are handled.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
from typing import Awaitable, Callable, Protocol

from relay.adb import adb_server_specs_from_env, sync_adb_endpoint_serials

logger = logging.getLogger("relay.watcher")

_DEVICE_LINE_RE = re.compile(
    r"^(\S+)\t(device|offline|unauthorized|no permissions|"
    r"sideload|recovery|rescue|bootloader|connecting|host)$"
)

DeviceEventCb = Callable[[str, str], Awaitable[None]]


class _AdbutilsConnection(Protocol):
    def send_command(self, cmd: str) -> None:
        ...

    def check_okay(self) -> None:
        ...

    def read_string_block(self) -> str:
        ...

    def close(self) -> None:
        ...


class _AdbutilsClient(Protocol):
    def make_connection(self, timeout: float | None = None) -> _AdbutilsConnection:
        ...


AdbutilsClientFactory = Callable[..., _AdbutilsClient]


def _stream_transport_mode() -> str:
    raw = (
        os.environ.get("AGENT_BOOT_ADB_STREAM_TRANSPORT", "").strip()
        or os.environ.get("AGENT_BOOT_ADB_TRANSPORT", "").strip()
    )
    value = raw.lower()
    if value in {"adbutils", "hybrid"}:
        return "adbutils"
    return "binary"


class AdbDeviceWatcher:
    """
    Wraps `adb track-devices`.  Diffs each snapshot against the previous one
    and fires on_device_event for every change.

    - New serial           → emits (serial, its_state)
    - State changed        → emits (serial, new_state)
    - Serial disappeared   → emits (serial, "offline")
    """

    def __init__(
        self,
        on_device_event: DeviceEventCb,
        *,
        adbutils_client_factory: AdbutilsClientFactory | None = None,
    ) -> None:
        self._cb       = on_device_event
        self._snapshot: dict[str, str] = {}
        self._snapshots: dict[str, dict[str, str]] = {}
        self._proc: asyncio.subprocess.Process | None = None
        self._procs: list[asyncio.subprocess.Process] = []
        self._adbutils_client_factory = adbutils_client_factory
        self._adbutils_connections: list[_AdbutilsConnection] = []
        self._adbutils_stop_events: list[threading.Event] = []

    async def run(self) -> None:
        """Loop forever; restarts the selected stream backend on failure."""
        servers = adb_server_specs_from_env()
        if servers:
            # One configured server gets a keyed tracker too, not just several.
            # The key is what makes _apply feed the route table, and without it
            # a device hot-plugged after startup has no route — so u2 falls back
            # to the `adbutils.adb` singleton and its ANDROID_ADB_SERVER_* env.
            await asyncio.gather(
                *[
                    self._run_server(host, port)
                    for host, port in servers
                ],
            )
            return
        # No ADB server configured: local adb in the container, nothing to route.
        while True:
            try:
                await self._track_loop(server=None)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("device_watcher crashed (%s) — restarting in 2s", exc)
                await asyncio.sleep(2)

    async def _run_server(self, host: str, port: str) -> None:
        key = f"{host}:{port}"
        while True:
            try:
                await self._track_loop(server=(host, port), key=key)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "device_watcher crashed host=%s port=%s (%s) — restarting in 2s",
                    host,
                    port,
                    exc,
                )
                await asyncio.sleep(2)

    def stop(self) -> None:
        if self._proc and self._proc.returncode is None:
            self._proc.kill()
        for proc in list(self._procs):
            if proc.returncode is None:
                proc.kill()
        for event in list(self._adbutils_stop_events):
            event.set()
        for connection in list(self._adbutils_connections):
            try:
                connection.close()
            except Exception:
                pass

    async def _track_loop(
        self,
        *,
        server: tuple[str, str] | None = None,
        key: str = "default",
    ) -> None:
        if _stream_transport_mode() == "adbutils":
            await self._track_loop_adbutils(server=server, key=key)
            return
        await self._track_loop_binary(server=server, key=key)

    async def _track_loop_binary(
        self,
        *,
        server: tuple[str, str] | None = None,
        key: str = "default",
    ) -> None:
        argv = ["adb"]
        if server:
            argv += ["-H", server[0], "-P", server[1]]
        argv.append("track-devices")
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self._proc = proc
        self._procs.append(proc)
        assert proc.stdout
        reader = proc.stdout

        try:
            while True:
                # Read exactly 4 bytes — the hex-encoded payload length
                header = await reader.readexactly(4)
                header_str = header.decode("ascii", errors="replace")

                # Detect Format A fallback: "List" instead of hex — old ADB / some hosts
                if not re.fullmatch(r"[0-9a-fA-F]{4}", header_str):
                    # Read the rest of the line and discard (it's the "List of devices..." header)
                    await reader.readline()
                    # Collect device lines until empty line
                    pending: dict[str, str] = {}
                    while True:
                        line_raw = await reader.readline()
                        line = line_raw.decode("utf-8", errors="replace").rstrip("\n\r")
                        if not line:
                            break
                        m = _DEVICE_LINE_RE.match(line)
                        if m:
                            pending[m.group(1)] = m.group(2)
                    await self._apply(pending, key=key)
                    continue

                # Format B (standard raw protocol): read exactly `length` bytes of payload
                length = int(header_str, 16)
                if length == 0:
                    await self._apply({}, key=key)
                    continue

                payload = await reader.readexactly(length)
                text = payload.decode("utf-8", errors="replace")

                snapshot: dict[str, str] = {}
                for line in text.splitlines():
                    m = _DEVICE_LINE_RE.match(line.rstrip("\r"))
                    if m:
                        snapshot[m.group(1)] = m.group(2)

                await self._apply(snapshot, key=key)

        except asyncio.IncompleteReadError:
            # adb process closed stdout (e.g., daemon restart) — outer loop retries
            pass
        finally:
            if proc.returncode is None:
                proc.kill()
            try:
                self._procs.remove(proc)
            except ValueError:
                pass

    async def _track_loop_adbutils(
        self,
        *,
        server: tuple[str, str] | None = None,
        key: str = "default",
    ) -> None:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, str] | BaseException] = asyncio.Queue()
        stop_event = threading.Event()
        with self._adbutils_tracking(stop_event):
            thread = threading.Thread(
                target=self._adbutils_track_worker,
                args=(loop, queue, stop_event, server),
                name=f"adbutils-track-devices-{key}",
                daemon=True,
            )
            thread.start()
            while True:
                item = await queue.get()
                if isinstance(item, BaseException):
                    raise item
                await self._apply(item, key=key)

    def _adbutils_tracking(self, stop_event: threading.Event):
        class _TrackingContext:
            def __enter__(ctx_self):
                self._adbutils_stop_events.append(stop_event)
                return ctx_self

            def __exit__(ctx_self, *_args):
                stop_event.set()
                try:
                    self._adbutils_stop_events.remove(stop_event)
                except ValueError:
                    pass
                return False

        return _TrackingContext()

    def _adbutils_track_worker(
        self,
        loop: asyncio.AbstractEventLoop,
        queue: asyncio.Queue[dict[str, str] | BaseException],
        stop_event: threading.Event,
        server: tuple[str, str] | None,
    ) -> None:
        connection: _AdbutilsConnection | None = None
        try:
            client = self._make_adbutils_client(server=server)
            connection = client.make_connection(timeout=None)
            self._adbutils_connections.append(connection)
            connection.send_command("host:track-devices")
            connection.check_okay()
            while not stop_event.is_set():
                snapshot = _parse_track_devices_snapshot(
                    connection.read_string_block()
                )
                loop.call_soon_threadsafe(queue.put_nowait, snapshot)
        except BaseException as exc:
            if not stop_event.is_set():
                loop.call_soon_threadsafe(queue.put_nowait, exc)
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
                try:
                    self._adbutils_connections.remove(connection)
                except ValueError:
                    pass

    def _make_adbutils_client(
        self,
        *,
        server: tuple[str, str] | None,
    ) -> _AdbutilsClient:
        factory = self._adbutils_client_factory
        if factory is None:
            from adbutils import AdbClient

            factory = AdbClient
        host, port = server if server else ("127.0.0.1", "5037")
        return factory(host=host, port=int(port), socket_timeout=None)

    async def _apply(self, new_snapshot: dict[str, str], *, key: str = "default") -> None:
        if key != "default" and ":" in key:
            # Full snapshot from one ADB server: claims routes for its devices
            # and releases routes for serials that left it (moved port / gone).
            host, port = key.rsplit(":", 1)
            sync_adb_endpoint_serials(host, port, new_snapshot)
        old = dict(self._snapshot)
        if key == "default":
            self._snapshot = dict(new_snapshot)
        else:
            self._snapshots[key] = dict(new_snapshot)
            self._snapshot = self._aggregate_snapshots()
        for serial, state in self._snapshot.items():
            if old.get(serial) != state:
                await self._cb(serial, state)
        for serial in old:
            if serial not in self._snapshot:
                await self._cb(serial, "offline")

    def _aggregate_snapshots(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for snapshot in self._snapshots.values():
            for serial, state in snapshot.items():
                if out.get(serial) == "device":
                    continue
                out[serial] = state
        return out

    @property
    def current_serials(self) -> list[str]:
        return [s for s, st in self._snapshot.items() if st == "device"]


def _parse_track_devices_snapshot(text: str) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for line in text.splitlines():
        m = _DEVICE_LINE_RE.match(line.rstrip("\r"))
        if m:
            snapshot[m.group(1)] = m.group(2)
    return snapshot
