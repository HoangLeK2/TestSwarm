"""Typed H264 packet shared by scrcpy producers and transport adapters."""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass, field

_PTS_CONFIG_MASK = 0x8000_0000_0000_0000


@dataclass(slots=True)
class VideoPacket:
    """One encoded scrcpy packet without a transport-specific envelope."""

    serial: str
    data: bytes
    is_config: bool
    is_key: bool
    pts_us: int
    width: int = 0
    height: int = 0
    received_ns: int = field(default_factory=time.monotonic_ns)
    enqueued_ns: int = 0

    def to_legacy_bytes(self) -> bytes:
        """Serialize the packet for the legacy WebSocket binary protocol."""
        serial_b = self.serial.encode()
        if len(serial_b) > 255:
            raise ValueError("video packet serial exceeds legacy protocol limit")
        flags = (0x01 if self.is_config else 0) | (0x02 if self.is_key else 0)
        pts_raw = int(self.pts_us)
        if self.is_config:
            pts_raw |= _PTS_CONFIG_MASK
        return (
            struct.pack(">BBB", 0x53, flags, len(serial_b))
            + serial_b
            + struct.pack(
                ">HHQ",
                self.width if self.is_config else 0,
                self.height if self.is_config else 0,
                pts_raw,
            )
            + self.data
        )
