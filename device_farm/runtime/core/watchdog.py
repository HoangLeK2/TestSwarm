"""
watchdog.py — WatchdogThread: health monitoring for WS-agent and relay devices.

Health checks:
  - WS Agent mode: agent WebSocket alive + state READY → healthy
    - atx-agent sub-check: HTTP /ping probe on port 7912 every interval; 2 misses → restart
  - Relay mode: frame liveness check (scrcpy stream)
  - If device unhealthy too long → mark DEAD
"""
from __future__ import annotations

import asyncio
import logging
import socket
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.config import Config
from runtime.core.device_client import DeviceClient, DeviceState
from runtime.core.device_manager import DeviceManager

log = logging.getLogger(__name__)

# Seconds a device can stay DISCONNECTED/ERROR before being marked DEAD
_MAX_DISCONNECTED_SECS = 120

# atx-agent HTTP probe: consecutive /ping failures before triggering restart
_ATX_MAX_MISS = 2

# Cooldown between atx-agent restart triggers (seconds)
_ATX_RESTART_COOLDOWN = 20


class WatchdogThread(threading.Thread):
    """Daemon thread that monitors device health for both agent and ADB modes."""

    def __init__(self, manager: DeviceManager, config: Config) -> None:
        super().__init__(daemon=True, name="watchdog")
        self.manager = manager
        self.config  = config
        self._running = False
        # Track when each serial entered a non-READY state
        self._bad_since: dict[str, float] = {}
        # atx-agent HTTP probe: consecutive miss count per serial
        self._atx_miss_count: dict[str, int] = {}
        # Last atx-agent restart trigger time per serial (for cooldown)
        self._atx_last_restart: dict[str, float] = {}

    def start_watchdog(self) -> None:
        self._running = True
        if not self.is_alive():
            self.start()

    def stop_watchdog(self) -> None:
        self._running = False

    # Max parallel TCP probes — keeps system FD usage bounded even for 1000+ devices.
    # Each probe holds one socket for up to 0.5s; 64 concurrent = ~32s worst-case fan-out
    # across 1000 unreachable devices instead of 500s sequential.
    _PROBE_WORKERS = 64

    def run(self) -> None:
        interval = self.config.watchdog.interval
        log.info(f"Watchdog started (interval={interval}s)")

        with ThreadPoolExecutor(max_workers=self._PROBE_WORKERS, thread_name_prefix="wd-probe") as pool:
            while self._running:
                time.sleep(interval)
                if not self._running:
                    break

                devices = [d for d in self.manager.all_devices() if d.state != DeviceState.DEAD]
                if not devices:
                    continue

                futures = {
                    pool.submit(self._check_device, device): device
                    for device in devices
                }
                for fut in as_completed(futures):
                    device = futures[fut]
                    try:
                        fut.result()
                    except Exception as exc:
                        log.error(f"[{device.serial}] Watchdog error: {exc}")

    def _check_device(self, device: DeviceClient) -> None:
        serial = device.serial

        # ── Relay-only device: no ADB access from server — check frame liveness ──
        is_relay_device = device._agent_send is None and getattr(device, "_scrcpy_active", False)
        if is_relay_device:
            # Two DeviceClients can share one relay ADB serial (placeholder + WS NAT
            # device). Only the one registered in _scrcpy_receivers receives frames;
            # the other would look "stale" forever and trigger false unhealthy / churn.
            try:
                from runtime.transports.adb_relay_server import get_relay_manager

                relay = get_relay_manager()
                my_recv = getattr(device, "_scrcpy_receiver", None)
                reg = relay.get_scrcpy_receiver(serial) if relay else None
                if my_recv is not None and reg is not None and reg is not my_recv:
                    try:
                        my_recv.stop_receiver()
                    except Exception:
                        pass
                    device._scrcpy_active = False
                    device._scrcpy_receiver = None
                    self._bad_since.pop(serial, None)
                    return
            except Exception:
                pass

            last_frame = getattr(device, "_last_frame_time", 0.0)
            frame_age = time.monotonic() - last_frame if last_frame > 0 else float("inf")
            # Allow 30s grace on startup (last_frame==0), then require frames within 30s
            frame_ok = last_frame == 0.0 or frame_age < 30.0
            if device.state in (DeviceState.READY, DeviceState.BUSY) and frame_ok:
                self._bad_since.pop(serial, None)
                device.reconnect_attempts = 0
            else:
                self._track_bad_state(device)
            return

        # ── WS Agent mode: passive check (agent alive + state) ──
        agent_alive = device._agent_send is not None
        if agent_alive and device.state == DeviceState.READY:
            self._bad_since.pop(serial, None)
            device.reconnect_attempts = 0
            # ── atx-agent sub-check: HTTP /ping probe on port 7912 ───────────
            # Detects frozen atx-agent before the next u2 RPC times out.
            # Only probe when u2 is currently connected (_u2_host set, _u2 live).
            atx_host = getattr(device, "_u2_host", None)
            u2_live   = getattr(device, "_u2", None) is not None
            if atx_host and u2_live:
                self._check_atx_agent(device, atx_host)
            return

        # Relay USB placeholder: no agent APK, scrcpy yielded to another DeviceClient
        # (NAT WS path registered the same relay ADB serial). Ghost cleanup clears
        # _scrcpy_active — without this branch the next tick hits "no agent" and
        # falsely reports Not healthy for the placeholder serial.
        if (
            not agent_alive
            and device.state in (DeviceState.READY, DeviceState.BUSY)
            and not getattr(device, "_scrcpy_active", False)
        ):
            try:
                from runtime.transports.adb_relay_server import get_relay_manager

                r = get_relay_manager()
                if r is not None and r.relay_for_serial(serial) is not None:
                    if r.get_scrcpy_receiver(serial) is not None:
                        self._bad_since.pop(serial, None)
                        return
            except Exception:
                pass

        # Agent disconnected or stuck in a bad state
        self._track_bad_state(device)

    def _check_atx_agent(self, device: DeviceClient, host: str) -> None:
        """Probe atx-agent /ping before u2 RPCs time out.

        A frozen atx-agent can keep the port open while its HTTP handler is wedged.
        Two consecutive HTTP misses trigger a restart.
        """
        serial = device.serial
        if self._probe_atx_agent_alive(device, host):
            self._atx_miss_count.pop(serial, None)
            return

        miss = self._atx_miss_count.get(serial, 0) + 1
        self._atx_miss_count[serial] = miss
        log.warning("[%s] atx-agent probe failed (%d/%d)", serial, miss, _ATX_MAX_MISS)
        if miss >= _ATX_MAX_MISS:
            self._atx_miss_count.pop(serial, None)
            now = time.monotonic()
            last = self._atx_last_restart.get(serial, 0.0)
            if now - last >= _ATX_RESTART_COOLDOWN:
                self._atx_last_restart[serial] = now
                log.warning("[%s] atx-agent unresponsive — triggering restart", serial)
                # Only null u2 and set backoff if no restart is already in-flight.
                # If _trigger_atx_restart_async was recently called (< 15s), a
                # _poll_atx_recovery thread is already running and will clear the
                # backoff when port 7912 comes back.  Resetting backoff here would
                # undo that and add 30s downtime on top of a recovery already underway.
                restart_in_flight = (
                    now - getattr(device, "_atx_restart_triggered_at", float("-inf")) < 15.0
                )
                if not restart_in_flight:
                    with device._u2_lock:
                        device._u2 = None
                    device._u2_reconnect_failed_at = time.monotonic()
                device._trigger_atx_restart_async(host)
            else:
                remaining = _ATX_RESTART_COOLDOWN - (now - last)
                log.info("[%s] atx restart cooldown %.0fs remaining", serial, remaining)

    def _probe_atx_agent_alive(self, device: DeviceClient, host: str) -> bool:
        """Prefer relay /ping probe in Docker; fallback to direct TCP for local LAN."""
        loop = getattr(device, "_loop", None)
        if loop:
            try:
                from runtime.transports.adb_relay_server import get_relay_manager

                relay = get_relay_manager()
                actual = None
                if relay is not None:
                    selector = getattr(device, "_select_u2_relay_serial", None)
                    if callable(selector):
                        actual = selector(relay, host)
                    else:
                        hint = f"{host}:5555"
                        actual = relay.resolve_serial(hint) if relay.relay_for_serial(hint) else None
                if relay is not None and actual:
                    fut = asyncio.run_coroutine_threadsafe(
                        relay.u2_http(actual, "GET", "/ping", timeout=2.0),
                        loop,
                    )
                    result = fut.result(timeout=5.0)
                    return bool(result.get("ok"))
            except Exception as exc:
                log.debug("[%s] atx-agent relay probe failed: %s", device.serial, exc)

        try:
            with urllib.request.urlopen(f"http://{host}:7912/ping", timeout=1.0) as resp:
                return 200 <= int(resp.status) < 300
        except Exception:
            return False

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
            # Record explicit dead event with reason before state change
            recorder = getattr(device, "_event_recorder", None)
            if recorder:
                elapsed_min = int(elapsed // 60)
                elapsed_sec = int(elapsed % 60)
                if elapsed_min > 0:
                    human_dur = f"{elapsed_min}m{elapsed_sec}s"
                else:
                    human_dur = f"{elapsed_sec}s"
                recorder.record(
                    serial=serial,
                    event="dead",
                    reason=f"No response for {human_dur}",
                    old_state=device.state.value,
                    new_state=DeviceState.DEAD.value,
                    device_model=device.model,
                    device_brand=device.brand,
                )
            device.state = DeviceState.DEAD
            self._bad_since.pop(serial, None)
            self._atx_miss_count.pop(serial, None)
            self._atx_last_restart.pop(serial, None)
