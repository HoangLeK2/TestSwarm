"""
device_manager.py — DeviceManager: device registry supporting two connection modes.

Mode A — WebSocket Agent (existing):
  Devices connect automatically when Agent APK opens a WebSocket to /device-agent.
  ensure_device(serial) is called by DeviceAgentSession on connect.

Mode B — ADB Transport (new, no `adb` binary):
  Farm server discovers devices via mDNS (_adb-tls-connect._tcp) or explicit
  HTTP registration (POST /api/devices/adb-register).
  register_adb_device(host, port) connects via adb-shell library directly.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import Dict, List, Optional

from core.config import Config
from runtime.core.device_client import DeviceClient, DeviceState


log = logging.getLogger(__name__)


class DeviceManager:
    """
    Central registry for all agent-connected devices.
    Thread-safe: all registry mutations use a lock.
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self._lock: threading.Lock = threading.Lock()
        self._registry: Dict[str, DeviceClient] = {}
        self._event_loop = None

        # Serial → slot index (persisted so the same device gets the same slot)
        self._index_map: Dict[str, int] = {}
        self._load_index_map()
        # Pre-populate registry from index so dashboard shows devices (DISCONNECTED) before any agent connects
        for serial in list(self._index_map.keys()):
            self.ensure_device(serial)

    # ── Registry ──────────────────────────────────────────────────────────────

    def ensure_device(self, serial: str) -> DeviceClient:
        """
        Get or create a DeviceClient for an incoming agent connection.
        Does NOT call setup() — agent sends its own hello/status to become READY.
        """
        with self._lock:
            existing = self._registry.get(serial)
            if existing is not None:
                return existing
            idx = self._get_or_assign_index(serial)
            client = DeviceClient(serial, idx, self.config)
            if self._event_loop is not None:
                client.set_event_loop(self._event_loop)
            self._registry[serial] = client
            log.info(f"Registered new device via WebSocket agent: {serial} → slot {idx}")
            return client

    def get_device(self, serial: str) -> Optional[DeviceClient]:
        with self._lock:
            return self._registry.get(serial)

    def all_devices(self) -> List[DeviceClient]:
        with self._lock:
            return list(self._registry.values())

    def ready_devices(self) -> List[DeviceClient]:
        with self._lock:
            return [d for d in self._registry.values() if d.state == DeviceState.READY]

    def remove_device(self, serial: str) -> None:
        """Remove a device from registry when agent permanently disconnects."""
        with self._lock:
            self._registry.pop(serial, None)

    # ── ADB Mode Registration (Mode B) ───────────────────────────────────────

    def register_adb_device(
        self,
        host: str,
        port: int = 5555,
        serial_hint: Optional[str] = None,
    ) -> Optional[DeviceClient]:
        """
        Connect to a device via ADB over TCP (no `adb` binary).

        Steps:
          1. Connect AdbTransport to device_ip:port
          2. Read device serial via getprop
          3. Create/get DeviceClient
          4. Call device.attach_adb_transport() to start bootstrap

        Returns the DeviceClient or None if connection fails.
        Used by:
          - POST /api/devices/adb-register (manual registration)
          - AdbMdnsDiscovery callback (automatic via Android 11+ Wireless Debugging)
        """
        from runtime.transports.adb_transport import AdbTransport

        tmp_serial = serial_hint or f"{host}:{port}"
        log.info(f"Connecting ADB transport to {host}:{port}")

        transport = AdbTransport(host, port)
        if not transport.connect():
            log.error(f"ADB connect failed: {host}:{port}")
            return None

        # Get real serial from device
        real_serial = transport.get_serial().strip()
        if not real_serial or real_serial == f"{host}:{port}":
            # Fallback: use IP:port as serial
            real_serial = tmp_serial
        log.info(f"ADB device serial: {real_serial}")

        with self._lock:
            # If device already registered (via WS agent), reuse it
            existing = self._registry.get(real_serial)
            if existing and existing.is_adb_mode:
                log.info(f"Device {real_serial} already in ADB mode")
                transport.close()
                return existing
            if existing is None:
                idx = self._get_or_assign_index(real_serial)
                client = DeviceClient(real_serial, idx, self.config)
                if self._event_loop is not None:
                    client.set_event_loop(self._event_loop)
                self._registry[real_serial] = client
                log.info(f"Registered ADB device: {real_serial} → slot {idx}")
            else:
                client = existing

        # Start ADB bootstrap (non-blocking)
        client.attach_adb_transport(transport)
        return client

    def reconnect_adb_device(self, serial: str) -> Optional[DeviceClient]:
        """
        Tear down and re-bootstrap an ADB device.
        Called by watchdog when ADB health check fails.
        Only reconnects READY devices (not BUSY — avoid interrupting tasks).
        """
        device = self.get_device(serial)
        if device is None:
            log.warning(f"reconnect_adb_device: {serial} not found in registry")
            return None
        if not device.is_adb_mode or device._adb_transport is None:
            log.warning(f"reconnect_adb_device: {serial} is not in ADB mode")
            return None

        host = device._adb_transport.host
        port = device._adb_transport.port

        log.info(f"[{serial}] Re-bootstrapping ADB device ({host}:{port})...")

        # 1. Tear down existing transports (scrcpy, u2)
        device.state = DeviceState.CONNECTING
        device.detach_all_transports()

        # 2. Reconnect ADB transport
        transport = device._adb_transport
        if not transport.reconnect(retries=3):
            log.error(f"[{serial}] ADB reconnect failed — creating new transport")
            try:
                transport.close()
            except Exception:
                pass
            # Create fresh transport
            from runtime.transports.adb_transport import AdbTransport
            transport = AdbTransport(host, port)
            if not transport.connect():
                log.error(f"[{serial}] New ADB transport also failed")
                device.state = DeviceState.DEAD
                return None

        # 3. Re-attach and bootstrap
        device.attach_adb_transport(transport)
        log.info(f"[{serial}] ADB re-bootstrap initiated")
        return device

    def start_mdns_discovery(self) -> bool:
        """
        Start mDNS listener for Android 11+ Wireless Debugging.
        When a device advertises _adb-tls-connect._tcp, automatically connects.
        Returns True if zeroconf is available.
        """
        try:
            from runtime.transports.adb_transport import AdbMdnsDiscovery
        except ImportError:
            return False

        def _on_device(host: str, port: int, name: str) -> None:
            log.info(f"mDNS: auto-connecting ADB device {name} at {host}:{port}")
            self.register_adb_device(host, port)

        self._mdns = AdbMdnsDiscovery(on_device=_on_device)
        return self._mdns.start()

    # ── Event Loop ───────────────────────────────────────────────────────────

    def register_event_loop(self, loop) -> None:
        """Propagate the asyncio event loop to all registered DeviceClients."""
        self._event_loop = loop
        with self._lock:
            for device in self._registry.values():
                device.set_event_loop(loop)

    # ── Shutdown ─────────────────────────────────────────────────────────────

    def teardown_all(self) -> None:
        with self._lock:
            devices = list(self._registry.values())
        for device in devices:
            try:
                device.teardown()
            except Exception as exc:
                log.error(f"[{device.serial}] teardown error: {exc}")

    # ── Serial → Index Persistence ────────────────────────────────────────────

    def _get_or_assign_index(self, serial: str) -> int:
        if serial in self._index_map:
            return self._index_map[serial]
        used = set(self._index_map.values())
        idx = 0
        while idx in used:
            idx += 1
        self._index_map[serial] = idx
        self._save_index_map()
        return idx

    def _load_index_map(self) -> None:
        path = self.config.device.index_file
        if os.path.exists(path):
            try:
                with open(path) as f:
                    self._index_map = json.load(f)
                log.info(f"Loaded device index map: {self._index_map}")
            except Exception as exc:
                log.warning(f"Could not load index map {path}: {exc}")

    def _save_index_map(self) -> None:
        path = self.config.device.index_file
        try:
            with open(path, "w") as f:
                json.dump(self._index_map, f, indent=2)
        except Exception as exc:
            log.warning(f"Could not save index map {path}: {exc}")
