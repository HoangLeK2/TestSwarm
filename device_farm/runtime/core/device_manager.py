"""
device_manager.py — DeviceManager: device registry supporting two connection modes.

Mode A — WebSocket Agent:
  Devices connect automatically when Agent APK opens a WebSocket to /device-agent.
  ensure_device(serial) is called by DeviceAgentSession on connect.

Mode B — Relay (agent-boot):
  Devices connect via agent-boot gRPC/WebSocket relay. ADB operations (bootstrap,
  shell, screencap) are executed by agent-boot on the same LAN as the device.
  register_relay_device(serial) is called when relay heartbeat reports a new device.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import Dict, List, Optional

from core.config import Config
from runtime.core.device_client import DeviceClient, DeviceState
from runtime.core.event_recorder import EventRecorder


log = logging.getLogger(__name__)


class DeviceManager:
    """
    Central registry for all agent-connected devices.
    Thread-safe: all registry mutations use a lock.
    """

    def __init__(self, config: Config, event_recorder: Optional[EventRecorder] = None) -> None:
        self.config = config
        self._lock: threading.Lock = threading.Lock()
        self._registry: Dict[str, DeviceClient] = {}
        self._event_loop = None
        self.event_recorder = event_recorder

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
            client._event_recorder = self.event_recorder
            if self._event_loop is not None:
                client.set_event_loop(self._event_loop)
            self._registry[serial] = client
            log.info(f"Registered new device via WebSocket agent: {serial} → slot {idx}")
            return client

    def get_device(self, serial: str) -> Optional[DeviceClient]:
        with self._lock:
            return self._registry.get(serial)

    @property
    def devices(self) -> Dict[str, DeviceClient]:
        """Shallow copy of the registry (legacy: ``len(manager.devices)``)."""
        with self._lock:
            return dict(self._registry)

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

    # ── Relay Device Registration (Mode B) ──────────────────────────────────

    def register_relay_device(self, serial: str) -> DeviceClient:
        """
        Register (or reuse) a DeviceClient for a device that appeared via relay heartbeat.

        The relay agent-boot already has ADB access. Bootstrap (push binaries,
        start atx-agent + u2) is triggered separately via relay.bootstrap(serial).
        This method only creates the DeviceClient registry entry — it does NOT
        block waiting for bootstrap to complete.
        """
        with self._lock:
            existing = self._registry.get(serial)
            if existing is not None:
                return existing
            idx = self._get_or_assign_index(serial)
            client = DeviceClient(serial, idx, self.config)
            client._event_recorder = self.event_recorder
            if self._event_loop is not None:
                client.set_event_loop(self._event_loop)
            self._registry[serial] = client
            log.info(f"Registered relay device: {serial} → slot {idx}")
            return client

    # register_adb_device kept as compatibility shim — routes to relay bootstrap.
    # POST /api/devices/adb-register passes host:port; we convert to serial and
    # ask agent-boot to bootstrap via relay.
    def register_adb_device(
        self,
        host: str,
        port: int = 5555,
        serial_hint: Optional[str] = None,
    ) -> Optional[DeviceClient]:
        """Compatibility shim: register device by IP via relay bootstrap."""
        from runtime.transports.adb_relay_server import get_relay_manager
        import asyncio

        serial = serial_hint or f"{host}:{port}"
        rm = get_relay_manager()
        if rm is None:
            log.error("register_adb_device: relay manager not available — is relay enabled?")
            return None

        client = self.register_relay_device(serial)

        # Trigger bootstrap in background (non-blocking)
        loop = self._event_loop
        if loop is not None:
            async def _bootstrap() -> None:
                ok = await rm.bootstrap(serial)
                if ok:
                    log.info(f"[{serial}] relay bootstrap complete")
                else:
                    log.warning(f"[{serial}] relay bootstrap failed")
            asyncio.run_coroutine_threadsafe(_bootstrap(), loop)
        else:
            log.warning(f"[{serial}] no event loop — bootstrap will run when relay connects")

        return client

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
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(path, "w") as f:
                json.dump(self._index_map, f, indent=2)
        except Exception as exc:
            log.warning(f"Could not save index map {path}: {exc}")
