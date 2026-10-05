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

import asyncio
import atexit
import json
import logging
import os
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

from core.config import Config
from runtime.core.device_client import DeviceClient, DeviceState
from runtime.core.event_recorder import EventRecorder


log = logging.getLogger(__name__)

# Slot-map persistence runs off the event loop — see _schedule_save_index_map.
_INDEX_SAVE_POOL = ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="device-index-save"
)
atexit.register(lambda: _INDEX_SAVE_POOL.shutdown(wait=False))
_INDEX_SAVE_DEBOUNCE_S = 1.0


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
        self._local_emulator_forwards: Dict[str, int] = {}

        # Serial → slot index (persisted so the same device gets the same slot)
        self._index_map: Dict[str, int] = {}
        self._index_save_lock: threading.Lock = threading.Lock()
        self._index_save_pending: bool = False
        self._index_save_dirty: bool = False
        # Running set + rising hint keep slot assignment O(1) per new device.
        self._used_indices: set[int] = set()
        self._next_index_hint: int = 0
        self._load_index_map()
        # Keep index history for stable slot assignment, but do not pre-register
        # devices from disk. Registry should reflect only currently live devices.

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
            self._fire_redis_sync(serial, client)
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
        self._fire_redis_remove(serial)

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
            self._fire_redis_sync(serial, client)
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

    def register_local_emulator(self, serial: str) -> Optional[DeviceClient]:
        """Register one local Android emulator through a bounded ADB forward."""
        serial = str(serial or "").strip()
        if re.fullmatch(r"emulator-[0-9]{4,5}", serial) is None:
            log.warning("local emulator registration rejected serial=%r", serial)
            return None
        adb = str(getattr(self.config.adb, "path", "adb") or "adb")
        existing = self.get_device(serial)
        if (
            existing is not None
            and getattr(existing, "_local_emulator_adb", False)
            and existing.state in {DeviceState.READY, DeviceState.BUSY}
            and existing.ensure_u2_healthy()
        ):
            return existing
        old_port = self._local_emulator_forwards.pop(serial, None)
        if old_port is not None:
            subprocess.run(
                [adb, "-s", serial, "forward", "--remove", f"tcp:{old_port}"],
                capture_output=True,
                timeout=5,
                check=False,
            )
        try:
            state = subprocess.run(
                [adb, "-s", serial, "get-state"],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
            if state != "device":
                return None
            port_text = subprocess.run(
                [adb, "-s", serial, "forward", "tcp:0", "tcp:7912"],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
            port = int(port_text)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            log.warning("local emulator registration failed serial=%s: %s", serial, exc)
            return None

        client = self.ensure_device(serial)
        client._adb_serial = serial
        client._tunnel_ports = {"u2": port}
        client.state = DeviceState.CONNECTING
        if not client._reconnect_u2():
            subprocess.run(
                [adb, "-s", serial, "forward", "--remove", f"tcp:{port}"],
                capture_output=True,
                timeout=5,
                check=False,
            )
            self.remove_device(serial)
            return None
        client._local_emulator_adb = True
        client.state = DeviceState.READY
        self._local_emulator_forwards[serial] = port
        log.info("Registered local emulator %s via atx forward tcp:%s", serial, port)
        return client

    # ── Redis sync (fire-and-forget) ─────────────────────────────────────────

    def _fire_redis_sync(self, serial: str, client: DeviceClient) -> None:
        loop = self._event_loop
        if loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._sync_device_to_redis(serial, client), loop)

    def _fire_redis_remove(self, serial: str) -> None:
        loop = self._event_loop
        if loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._remove_device_from_redis(serial), loop)

    async def _sync_device_to_redis(self, serial: str, client: DeviceClient) -> None:
        from services import redis_store
        if not redis_store.enabled():
            return
        try:
            r = redis_store.client()
            await r.hset(redis_store.key("devices"), serial, json.dumps({
                "serial": serial,
                "index": client.index,
                "state": client.state.name if isinstance(client.state, DeviceState) else str(client.state),
                "model": getattr(client, "_model", ""),
                "brand": getattr(client, "_brand", ""),
            }))
        except Exception as exc:
            log.debug("Redis device sync failed for %s: %s", serial, exc)

    async def _remove_device_from_redis(self, serial: str) -> None:
        from services import redis_store
        if not redis_store.enabled():
            return
        try:
            r = redis_store.client()
            await r.hdel(redis_store.key("devices"), serial)
        except Exception as exc:
            log.debug("Redis device remove failed for %s: %s", serial, exc)

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
        adb = str(getattr(self.config.adb, "path", "adb") or "adb")
        for serial, port in tuple(self._local_emulator_forwards.items()):
            subprocess.run(
                [adb, "-s", serial, "forward", "--remove", f"tcp:{port}"],
                capture_output=True,
                timeout=5,
                check=False,
            )
        self._local_emulator_forwards.clear()
        # Slot assignments are written on a debounce; make sure the last one
        # reaches disk so a restart reuses the same slots.
        self.flush_index_map()

    # ── Serial → Index Persistence ────────────────────────────────────────────

    def _get_or_assign_index(self, serial: str) -> int:
        """Assign the lowest free slot in O(1) amortised.

        This runs once per newly reported phone, inside the relay online
        callback, on the API event loop. Rebuilding ``set(index_map.values())``
        on every call made a fleet registration O(N^2): at 2000 phones that
        alone was hundreds of milliseconds of stalled loop. Slots are never
        released (the map is history), so a running set plus a rising hint
        gives the same answer without the rescan.
        """
        existing = self._index_map.get(serial)
        if existing is not None:
            return existing
        idx = self._next_index_hint
        while idx in self._used_indices:
            idx += 1
        self._index_map[serial] = idx
        self._used_indices.add(idx)
        self._next_index_hint = idx + 1
        self._schedule_save_index_map()
        return idx

    def _load_index_map(self) -> None:
        path = self.config.device.index_file
        if os.path.exists(path):
            try:
                with open(path) as f:
                    self._index_map = json.load(f)
                log.info(
                    "Loaded persisted device slot map (history, not live registry): %s",
                    self._index_map,
                )
            except Exception as exc:
                log.warning(f"Could not load index map {path}: {exc}")
        self._used_indices = {int(v) for v in self._index_map.values()}
        self._next_index_hint = 0

    def _schedule_save_index_map(self) -> None:
        """Persist the slot map off the caller's thread, coalescing bursts.

        register_relay_device runs inside the relay online callback, which the
        gRPC handler awaits on the API event loop. A relay reporting 100 new
        phones used to mean 100 synchronous json.dump calls there — on a docker
        bind mount that is not free. Slot assignment is already in memory and
        authoritative; the file is only history, so it can lag by a second.

        Only a flag is set here — O(1). Copying the map on the caller's side
        would put the O(N) back on the event loop and make a fleet registration
        quadratic again. The writer thread snapshots under ``self._lock``
        instead; it is a different thread, so taking that lock is safe.
        """
        with self._index_save_lock:
            self._index_save_dirty = True
            if self._index_save_pending:
                return
            self._index_save_pending = True
        try:
            _INDEX_SAVE_POOL.submit(self._drain_index_map_saves)
        except RuntimeError:
            # Interpreter shutting down — write inline so the slot is not lost.
            # The caller holds self._lock, so snapshot directly rather than
            # re-acquiring it.
            with self._index_save_lock:
                self._index_save_pending = False
                self._index_save_dirty = False
            self._save_index_map(dict(self._index_map))

    def _snapshot_index_map(self) -> Optional[Dict[str, int]]:
        """Take a consistent copy if there is anything new to write."""
        with self._index_save_lock:
            if not self._index_save_dirty:
                return None
            self._index_save_dirty = False
        with self._lock:
            return dict(self._index_map)

    def _drain_index_map_saves(self) -> None:
        while True:
            snapshot = self._snapshot_index_map()
            if snapshot is None:
                with self._index_save_lock:
                    # Re-check: an assignment may have landed since the snapshot.
                    if self._index_save_dirty:
                        continue
                    self._index_save_pending = False
                    return
            else:
                self._save_index_map(snapshot)
            # Coalesce the rest of the burst into the next write.
            time.sleep(_INDEX_SAVE_DEBOUNCE_S)

    def flush_index_map(self) -> None:
        """Write any pending slot assignment now (shutdown path)."""
        snapshot = self._snapshot_index_map()
        if snapshot is not None:
            self._save_index_map(snapshot)

    def _save_index_map(self, index_map: Optional[Dict[str, int]] = None) -> None:
        path = self.config.device.index_file
        snapshot = self._index_map if index_map is None else index_map
        try:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(path, "w") as f:
                json.dump(snapshot, f, indent=2)
        except Exception as exc:
            log.warning(f"Could not save index map {path}: {exc}")
