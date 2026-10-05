"""
runtime/core/device_pool.py — DevicePool

Wraps AdbRelayManager's capability/pool state with an asyncio-safe allocation
queue: callers can await a matching device instead of polling.

Usage:
    pool = DevicePool(relay_manager)
    serial = await pool.wait_for_device(tags=["android>=13", "brand=samsung"], timeout=60)
    if serial:
        try:
            ... do work ...
        finally:
            pool.release(serial)

Tag filter syntax (same as AdbRelayManager.list_devices):
    "brand=samsung"     exact match
    "android>=13"       android_version integer compare
    "sdk>=33"           sdk integer compare
    "ram>=6"            ram_gb integer compare
    "tag=flagship"      custom tag present
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import List, Optional

logger = logging.getLogger("device_pool")

_POLL_INTERVAL = 1.0  # seconds between allocation retries while waiting


class DevicePool:
    """
    Asyncio-safe device allocation backed by AdbRelayManager.

    Thin wrapper — relay manager holds the actual state.
    This class adds:
      - async wait_for_device() with timeout
      - context-manager pattern (async with pool.reserve(...))
    """

    def __init__(self, relay_manager: "Any") -> None:
        self._relay = relay_manager

    # ── Synchronous API ───────────────────────────────────────────────────────

    def available(self, tags: Optional[List[str]] = None) -> List[dict]:
        """Return list of available devices matching tag filters."""
        return [
            d for d in self._relay.list_devices(tags)
            if d.get("state") == "available"
        ]

    def allocate(self, tags: Optional[List[str]] = None) -> Optional[str]:
        """Immediately allocate one matching device. Returns serial or None."""
        return self._relay.allocate_device(tags)

    def release(self, serial: str) -> None:
        self._relay.release_device(serial)

    # ── Async API ─────────────────────────────────────────────────────────────

    async def wait_for_device(
        self,
        tags: Optional[List[str]] = None,
        timeout: float = 60.0,
    ) -> Optional[str]:
        """
        Wait until a matching device becomes available, up to `timeout` seconds.
        Returns the allocated serial or None on timeout.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            serial = self.allocate(tags)
            if serial:
                return serial
            remaining = deadline - time.monotonic()
            await asyncio.sleep(min(_POLL_INTERVAL, remaining))
        return None

    def reserve(self, tags: Optional[List[str]] = None, timeout: float = 60.0) -> "_Reservation":
        """Async context manager: allocates on enter, releases on exit."""
        return _Reservation(self, tags, timeout)

    # ── Info ──────────────────────────────────────────────────────────────────

    def summary(self) -> dict:
        """Quick stats for dashboards / health checks."""
        all_devices = self._relay.list_devices()
        available   = [d for d in all_devices if d.get("state") == "available"]
        busy        = [d for d in all_devices if d.get("state") == "busy"]
        return {
            "total":     len(all_devices),
            "available": len(available),
            "busy":      len(busy),
            "devices":   all_devices,
        }


class _Reservation:
    """Async context manager returned by DevicePool.reserve()."""

    def __init__(self, pool: DevicePool, tags: Optional[List[str]], timeout: float) -> None:
        self._pool    = pool
        self._tags    = tags
        self._timeout = timeout
        self.serial: Optional[str] = None

    async def __aenter__(self) -> Optional[str]:
        self.serial = await self._pool.wait_for_device(self._tags, self._timeout)
        return self.serial

    async def __aexit__(self, *_) -> None:
        if self.serial:
            self._pool.release(self.serial)
            self.serial = None
