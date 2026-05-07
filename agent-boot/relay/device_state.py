"""
relay/device_state.py — Device lifecycle state machine.

States:
  UNKNOWN → CONNECTING → ONLINE ↔ BUSY
                              ↓
                        OFFLINE / RECONNECTING
                              ↓ (max retries)
                            DEAD
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

_MAX_RETRIES = 5


class DeviceState(Enum):
    UNKNOWN      = "unknown"
    CONNECTING   = "connecting"
    ONLINE       = "online"
    BUSY         = "busy"
    OFFLINE      = "offline"
    RECONNECTING = "reconnecting"
    DEAD         = "dead"


@dataclass
class DeviceContext:
    serial: str
    state: DeviceState = DeviceState.UNKNOWN
    retry_count: int = 0
    capabilities: dict = field(default_factory=dict)
    last_seen: float = field(default_factory=time.monotonic)
    last_state_change: float = field(default_factory=time.monotonic)

    def transition(self, new_state: DeviceState) -> bool:
        """Transition to new_state. Returns True if state actually changed."""
        if self.state == new_state:
            return False
        self.state = new_state
        self.last_state_change = time.monotonic()
        if new_state == DeviceState.ONLINE:
            self.retry_count = 0
            self.last_seen = time.monotonic()
        elif new_state == DeviceState.RECONNECTING:
            self.retry_count += 1
        return True

    @property
    def is_dead(self) -> bool:
        return self.retry_count >= _MAX_RETRIES

    @property
    def is_available(self) -> bool:
        return self.state in (DeviceState.ONLINE, DeviceState.BUSY)


class DeviceRegistry:
    """Registry of all known devices and their states."""

    def __init__(self) -> None:
        self._devices: dict[str, DeviceContext] = {}

    def on_adb_event(self, serial: str, adb_state: str) -> tuple[DeviceContext, bool]:
        """
        Process an adb device event. Returns (context, state_changed).
        adb_state: "device" | "offline" | "unauthorized" | "connecting" | …
        """
        ctx = self._devices.setdefault(serial, DeviceContext(serial=serial))

        if adb_state == "device":
            changed = ctx.transition(DeviceState.ONLINE)
        elif adb_state in ("offline", "unauthorized", "no permissions"):
            if ctx.state in (DeviceState.ONLINE, DeviceState.BUSY):
                new = DeviceState.DEAD if ctx.is_dead else DeviceState.RECONNECTING
            else:
                new = DeviceState.OFFLINE
            changed = ctx.transition(new)
        elif adb_state == "connecting":
            changed = ctx.transition(DeviceState.CONNECTING)
        else:
            changed = ctx.transition(DeviceState.OFFLINE)

        return ctx, changed

    def set_capabilities(self, serial: str, caps: dict) -> None:
        if serial in self._devices:
            self._devices[serial].capabilities = caps

    def set_busy(self, serial: str) -> None:
        if serial in self._devices:
            self._devices[serial].transition(DeviceState.BUSY)

    def set_online(self, serial: str) -> None:
        if serial in self._devices:
            self._devices[serial].transition(DeviceState.ONLINE)

    @property
    def online_serials(self) -> list[str]:
        return [s for s, ctx in self._devices.items() if ctx.is_available]

    @property
    def all_serials(self) -> list[str]:
        return list(self._devices.keys())

    def get(self, serial: str) -> Optional[DeviceContext]:
        return self._devices.get(serial)
