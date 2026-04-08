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
        self._proc: asyncio.subprocess.Process | None = None

    async def run(self) -> None:
        """Loop forever; restarts subprocess on failure."""
        while True:
            try:
                await self._track_loop()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("device_watcher crashed (%s) — restarting in 2s", exc)
                await asyncio.sleep(2)

    def stop(self) -> None:
        if self._proc and self._proc.returncode is None:
            self._proc.kill()

    async def _track_loop(self) -> None:
        self._proc = await asyncio.create_subprocess_exec(
            "adb", "track-devices",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        assert self._proc.stdout
        reader = self._proc.stdout

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
                    await self._apply(pending)
                    continue

                # Format B (standard raw protocol): read exactly `length` bytes of payload
                length = int(header_str, 16)
                if length == 0:
                    await self._apply({})
                    continue

                payload = await reader.readexactly(length)
                text = payload.decode("utf-8", errors="replace")

                snapshot: dict[str, str] = {}
                for line in text.splitlines():
                    m = _DEVICE_LINE_RE.match(line.rstrip("\r"))
                    if m:
                        snapshot[m.group(1)] = m.group(2)

                await self._apply(snapshot)

        except asyncio.IncompleteReadError:
            # adb process closed stdout (e.g., daemon restart) — outer loop retries
            pass
        finally:
            if self._proc.returncode is None:
                self._proc.kill()

    async def _apply(self, new_snapshot: dict[str, str]) -> None:
        old = self._snapshot
        for serial, state in new_snapshot.items():
            if old.get(serial) != state:
                await self._cb(serial, state)
        for serial in old:
            if serial not in new_snapshot:
                await self._cb(serial, "offline")
        self._snapshot = dict(new_snapshot)

    @property
    def current_serials(self) -> list[str]:
        return [s for s, st in self._snapshot.items() if st == "device"]
