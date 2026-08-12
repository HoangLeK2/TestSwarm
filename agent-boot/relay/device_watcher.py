"""
relay/device_watcher.py — Real-time ADB device detection via `adb track-devices`.

`adb track-devices` pushes a full device-list snapshot on every change —
latency <100ms vs the old 5s polling heartbeat loop.

Protocol:
  Two output formats seen in the wild:
    (A) Plain:  "List of devices attached\\n<serial>\\t<state>\\n...\\n\\n"
    (B) Raw:    4-hex-length prefix then payload  (some ADB versions)
  Both are handled.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Awaitable, Callable

from relay.adb import _remember_serial_adb_server, adb_server_specs_from_env

logger = logging.getLogger("relay.watcher")

_DEVICE_LINE_RE = re.compile(
    r"^(\S+)\t(device|offline|unauthorized|no permissions|"
    r"sideload|recovery|rescue|bootloader|connecting|host)$"
)

DeviceEventCb = Callable[[str, str], Awaitable[None]]


class AdbDeviceWatcher:
    """
    Wraps `adb track-devices`.  Diffs each snapshot against the previous one
    and fires on_device_event for every change.

    - New serial           → emits (serial, its_state)
    - State changed        → emits (serial, new_state)
    - Serial disappeared   → emits (serial, "offline")
    """

    def __init__(self, on_device_event: DeviceEventCb) -> None:
        self._cb       = on_device_event
        self._snapshot: dict[str, str] = {}
        self._snapshots: dict[str, dict[str, str]] = {}
        self._proc: asyncio.subprocess.Process | None = None
        self._procs: list[asyncio.subprocess.Process] = []

    async def run(self) -> None:
        """Loop forever; restarts subprocess on failure."""
        servers = adb_server_specs_from_env()
        if len(servers) > 1:
            await asyncio.gather(
                *[
                    self._run_server(host, port)
                    for host, port in servers
                ],
            )
            return
        while True:
            try:
                server = servers[0] if servers else None
                await self._track_loop(server=server)
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

    async def _track_loop(
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

    async def _apply(self, new_snapshot: dict[str, str], *, key: str = "default") -> None:
        if key != "default" and ":" in key:
            host, port = key.rsplit(":", 1)
            for serial, state in new_snapshot.items():
                if state == "device":
                    _remember_serial_adb_server(serial, host, port)
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
