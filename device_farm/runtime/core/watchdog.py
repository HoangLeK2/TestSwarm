"""
watchdog.py — WatchdogThread: health monitoring for both WS-agent and ADB devices.

Health checks:
  - WS Agent mode: agent WebSocket alive + state READY → healthy
  - ADB mode: periodic `adb shell echo ok` ping → healthy
  - If device unhealthy too long → mark DEAD
  - ADB devices: trigger auto-reconnect on transport failure
"""
from __future__ import annotations

import logging
import threading
import time

from core.config import Config
from runtime.core.device_client import DeviceClient, DeviceState
from runtime.core.device_manager import DeviceManager

log = logging.getLogger(__name__)

# Seconds a device can stay DISCONNECTED/ERROR before being marked DEAD
_MAX_DISCONNECTED_SECS = 120

# ADB health check: consecutive failures before triggering reconnect
_ADB_MAX_MISS = 3

# Cooldown between ADB reconnect attempts (seconds)
_ADB_RECONNECT_COOLDOWN = 60


class WatchdogThread(threading.Thread):
    """Daemon thread that monitors device health for both agent and ADB modes."""

    def __init__(self, manager: DeviceManager, config: Config) -> None:
        super().__init__(daemon=True, name="watchdog")
        self.manager = manager
        self.config  = config
        self._running = False
        # Track when each serial entered a non-READY state
        self._bad_since: dict[str, float] = {}
        # ADB health: consecutive miss count per serial
        self._adb_miss_count: dict[str, int] = {}
        # Last ADB reconnect attempt time per serial (for cooldown)
        self._adb_last_reconnect: dict[str, float] = {}

    def start_watchdog(self) -> None:
        self._running = True
        if not self.is_alive():
            self.start()

    def stop_watchdog(self) -> None:
        self._running = False

    def run(self) -> None:
        interval = self.config.watchdog.interval
        log.info(f"Watchdog started (interval={interval}s)")

        while self._running:
            time.sleep(interval)
            if not self._running:
                break

            for device in self.manager.all_devices():
                if device.state == DeviceState.DEAD:
                    continue
                try:
                    self._check_device(device)
                except Exception as exc:
                    log.error(f"[{device.serial}] Watchdog error: {exc}")

    def _check_device(self, device: DeviceClient) -> None:
        serial = device.serial

        # ── ADB mode: active health check via shell ping ──
        if getattr(device, "is_adb_mode", False):
            self._check_adb_device(device)
            return

        # ── WS Agent mode: passive check (agent alive + state) ──
        agent_alive = device._agent_send is not None
        if agent_alive and device.state == DeviceState.READY:
            self._bad_since.pop(serial, None)
            device.reconnect_attempts = 0
            return

        # Agent disconnected or stuck in a bad state
        self._track_bad_state(device)

    def _check_adb_device(self, device: DeviceClient) -> None:
        """Active health check for ADB-connected devices."""
        serial = device.serial
        transport = getattr(device, "_adb_transport", None)

        # No transport → not really ADB mode, skip
        if transport is None:
            return

        # Only check READY or BUSY devices (not CONNECTING or already ERROR)
        if device.state not in (DeviceState.READY, DeviceState.BUSY):
            self._track_bad_state(device)
            return

        # Don't ping devices that are BUSY running tasks — assume healthy
        if device.state == DeviceState.BUSY:
            self._adb_miss_count.pop(serial, None)
            self._bad_since.pop(serial, None)
            return

        # Ping ADB transport
        if transport.is_alive(timeout=5.0):
            # Healthy
            self._adb_miss_count.pop(serial, None)
            self._bad_since.pop(serial, None)
            device.reconnect_attempts = 0
            return

        # Ping failed
        miss = self._adb_miss_count.get(serial, 0) + 1
        self._adb_miss_count[serial] = miss
        log.warning(f"[{serial}] ADB ping failed ({miss}/{_ADB_MAX_MISS})")

        if miss >= _ADB_MAX_MISS:
            self._adb_miss_count.pop(serial, None)
            device.state = DeviceState.ERROR
            self._schedule_adb_reconnect(device)

    def _schedule_adb_reconnect(self, device: DeviceClient) -> None:
        """Trigger ADB re-bootstrap in background, respecting cooldown."""
        serial = device.serial
        now = time.monotonic()
        last = self._adb_last_reconnect.get(serial, 0)

        if now - last < _ADB_RECONNECT_COOLDOWN:
            remaining = _ADB_RECONNECT_COOLDOWN - (now - last)
            log.info(f"[{serial}] ADB reconnect cooldown ({remaining:.0f}s remaining)")
            return

        self._adb_last_reconnect[serial] = now
        log.info(f"[{serial}] Scheduling ADB re-bootstrap...")
        threading.Thread(
            target=self._do_adb_reconnect,
            args=(device,),
            daemon=True,
            name=f"adb-reconnect-{serial}",
        ).start()

    def _do_adb_reconnect(self, device: DeviceClient) -> None:
        """Background thread: attempt ADB reconnect + full re-bootstrap."""
        serial = device.serial
        try:
            self.manager.reconnect_adb_device(serial)
        except Exception as exc:
            log.error(f"[{serial}] ADB reconnect failed: {exc}")
            device.state = DeviceState.DEAD
            self._bad_since.pop(serial, None)

    def _track_bad_state(self, device: DeviceClient) -> None:
        """Track how long a device has been in a bad state; mark DEAD if too long."""
        serial = device.serial
        now = time.monotonic()
        if serial not in self._bad_since:
            self._bad_since[serial] = now
            log.warning(
                f"[{serial}] Not healthy (state={device.state.value})"
            )
            return

        elapsed = now - self._bad_since[serial]
        if elapsed > _MAX_DISCONNECTED_SECS:
            log.error(
                f"[{serial}] DEAD after {elapsed:.0f}s without recovery"
            )
            device.state = DeviceState.DEAD
            self._bad_since.pop(serial, None)
            self._adb_miss_count.pop(serial, None)
