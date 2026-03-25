"""
watchdog.py — WatchdogThread (No-ADB architecture).

Health check for WebSocket-agent devices:
  - If agent is connected (_agent_send is set) and state is READY → healthy
  - If agent disconnected but device still in registry → mark DISCONNECTED
  - If device has been DISCONNECTED/ERROR too long → mark DEAD

No ADB ping, no u2 health check, no minicap/minitouch checks.
The agent itself is responsible for reconnecting.
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


class WatchdogThread(threading.Thread):
    """Daemon thread that monitors agent-connected device health."""

    def __init__(self, manager: DeviceManager, config: Config) -> None:
        super().__init__(daemon=True, name="watchdog")
        self.manager = manager
        self.config  = config
        self._running = False
        # Track when each serial entered a non-READY state
        self._bad_since: dict[str, float] = {}

    def start_watchdog(self) -> None:
        self._running = True
        if not self.is_alive():
            self.start()

    def stop_watchdog(self) -> None:
        self._running = False

    def run(self) -> None:
        interval = self.config.watchdog.interval
        log.info(f"Watchdog started (interval={interval}s, no-ADB mode)")

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
        # ADB mode: no agent; READY means scrcpy+u2 are up — treat as healthy
        if getattr(device, "is_adb_mode", False) and device.state == DeviceState.READY:
            self._bad_since.pop(serial, None)
            device.reconnect_attempts = 0
            return
        agent_alive = device._agent_send is not None
        if agent_alive and device.state == DeviceState.READY:
            # Healthy — clear any accumulated bad time
            self._bad_since.pop(serial, None)
            device.reconnect_attempts = 0
            return

        # Agent disconnected or stuck in a bad state
        now = time.monotonic()
        if serial not in self._bad_since:
            self._bad_since[serial] = now
            log.warning(
                f"[{serial}] Not healthy "
                f"(agent_alive={agent_alive} state={device.state.value})"
            )
            return

        elapsed = now - self._bad_since[serial]
        if elapsed > _MAX_DISCONNECTED_SECS:
            log.error(
                f"[{serial}] DEAD after {elapsed:.0f}s without agent reconnect"
            )
            device.state = DeviceState.DEAD
            self._bad_since.pop(serial, None)
