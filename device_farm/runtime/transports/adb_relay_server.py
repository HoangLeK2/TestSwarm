"""
adb_relay_server.py — WebSocket relay server for ADB relay agents.

Architecture:
  Local agent (agent-boot) connects outbound via WebSocket to /relay-agent.
  This server routes ADB commands to the right agent and returns results.

Protocol:
  Control messages  — JSON text frames (both directions)
  Scrcpy frames     — binary frames: 0x53 tag + header + H264 data
  Scrcpy control    — binary frames: 0x43 tag + serial + ctrl bytes

Usage (called from web/server.py at startup):
    manager = create_relay_manager()
    session = WsRelayAgentSession(manager, api_key="secret")
    # Register /relay-agent WS endpoint → session.handle(ws)
    manager = get_relay_manager()
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import struct
import time
import uuid
from typing import Any, Callable, Dict, Optional, Set

from common.fast_codec import dumps, loads
from runtime.stream_telemetry import stream_telemetry

logger = logging.getLogger(__name__)

# CMD_TYPE constants (must match agent-boot relay/agent.py)
CMD_SHELL        = 0
CMD_RESTART_U2   = 1
CMD_ADB_CONNECT  = 2
CMD_RESTART_ATX  = 3
CMD_BOOTSTRAP    = 4  # push binaries + install APKs + start atx-agent + u2
CMD_SCREENCAP    = 5  # screencap → base64 PNG in result["output"]
CMD_PROBE_CAPS       = 6  # probe_capabilities() → JSON dict in result["output"]
CMD_RESTART_SCRCPY   = 7  # stop + resume scrcpy session (must match agent-boot)

# Reply types that carry an "id" matching a pending send_json_request future.
# Every request/reply message type the agent can answer must be listed here, or
# its caller silently waits out the full timeout — shared by both the WebSocket
# and gRPC relay servers so a new type only has to be added once.
_REQUEST_REPLY_TYPES = frozenset({
    "u2_batch_result",
    "u2_flow_result",
    "extra_data_result",
    "ocr_result",
    "image_match_result",
})


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


SCRCPY_DEFAULT_MAX_FPS = max(1, _env_int("SCRCPY_DEFAULT_MAX_FPS", 15))
SCRCPY_DEFAULT_MAX_WIDTH = max(160, _env_int("SCRCPY_DEFAULT_MAX_WIDTH", 540))
SCRCPY_DEFAULT_BITRATE = max(80_000, _env_int("SCRCPY_DEFAULT_BITRATE", 800_000))


def _match_tags(caps: dict, filters: list) -> bool:
    """
    Evaluate tag filter expressions against a capability dict.

    Supported filters:
      "brand=samsung"   → caps["brand"] == "samsung"
      "android>=13"     → int(caps["android_version"]) >= 13
      "sdk>=33"         → int(caps["sdk"]) >= 33
      "ram>=6"          → caps["ram_gb"] >= 6
      "tag=flagship"    → "flagship" in caps["tags"]
    """
    for f in filters:
        try:
            if "=" in f and ">=" not in f and "<=" not in f:
                k, v = f.split("=", 1)
                k = k.strip(); v = v.strip()
                if k == "tag":
                    if v not in caps.get("tags", []):
                        return False
                elif str(caps.get(k, "")).lower() != v.lower():
                    return False
            elif ">=" in f:
                k, v = f.split(">=", 1)
                k = k.strip(); v = v.strip()
                _ALIASES = {"android": "android_version", "ram": "ram_gb"}
                field = _ALIASES.get(k, k)
                if int(caps.get(field, 0) or 0) < int(v):
                    return False
            elif "<=" in f:
                k, v = f.split("<=", 1)
                k = k.strip(); v = v.strip()
                _ALIASES = {"android": "android_version", "ram": "ram_gb"}
                field = _ALIASES.get(k, k)
                if int(caps.get(field, 0) or 0) > int(v):
                    return False
        except Exception:
            pass  # malformed filter — skip
    return True


# ── Per-relay connection ──────────────────────────────────────────────────────

class RelayConnection:
    """
    Represents one active relay agent WebSocket connection.
    Holds a write queue (populated by manager, drained by writer task)
    and a pending-futures map for msg_id correlation.

    Write queue items:
      str  → JSON text frame (command, scrcpy_start/stop, ping)
      bytes → binary frame (scrcpy_ctrl: 0x43 + serial + data)
    """

    def __init__(self, relay_id: str, write_queue: "asyncio.Queue[str | bytes]") -> None:
        self.relay_id = relay_id
        self.serials: Set[str] = set()
        self._write_queue = write_queue
        # msg_id → Future[dict] for pending ADB command responses
        self._pending: Dict[str, "asyncio.Future[dict]"] = {}

    async def send_command(
        self,
        serial: str,
        cmd: str,
        timeout: float,
        cmd_type: int = CMD_SHELL,
    ) -> dict:
        """Enqueue ADB command and await result (msg_id correlation)."""
        msg_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[msg_id] = future

        msg = dumps({
            "type":     "command",
            "msg_id":   msg_id,
            "serial":   serial,
            "cmd":      cmd,
            "timeout":  int(timeout),
            "cmd_type": cmd_type,
        })
        await self._write_queue.put(msg)

        try:
            return await asyncio.wait_for(
                asyncio.shield(future),
                timeout=timeout + 10.0,
            )
        except asyncio.TimeoutError:
            self._pending.pop(msg_id, None)
            return {
                "ok": False, "exit_code": -1, "output": "",
                "error": f"relay timeout ({timeout}s) for serial={serial!r}",
            }
        finally:
            self._pending.pop(msg_id, None)

    async def send_u2_request(
        self,
        serial: str,
        method: str,
        path: str,
        body: str = "",
        content_type: str = "application/json",
        timeout: float = 30.0,
        priority: str | int | None = None,
        deadline_ms: int | float | None = None,
    ) -> dict:
        """Send an HTTP proxy request to atx-agent on the remote device, await result."""
        msg_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[msg_id] = future

        msg = dumps({
            "type":         "u2_request",
            "msg_id":       msg_id,
            "serial":       serial,
            "method":       method,
            "path":         path,
            "body":         body,
            "content_type": content_type,
            "timeout":      max(1.0, float(timeout)),
            **({"priority": priority} if priority is not None else {}),
            **({"deadline_ms": deadline_ms} if deadline_ms is not None else {}),
        })
        await self._write_queue.put(msg)

        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout=timeout + 10.0)
        except asyncio.TimeoutError:
            self._pending.pop(msg_id, None)
            return {
                "ok": False, "status": 0,
                "body": f"u2 relay timeout ({timeout}s) serial={serial!r}",
                "content_type": "",
            }
        finally:
            self._pending.pop(msg_id, None)

    async def send_json_request(
        self,
        msg: dict,
        reply_id: str,
        timeout: float = 30.0,
        timeout_grace: float = 10.0,
    ) -> dict:
        """Send a JSON message and await a matching reply by id."""
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[reply_id] = future

        await self._write_queue.put(dumps(msg))

        try:
            return await asyncio.wait_for(
                asyncio.shield(future),
                timeout=max(0.1, timeout + timeout_grace),
            )
        except asyncio.TimeoutError:
            self._pending.pop(reply_id, None)
            return {"ok": False, "error": f"relay timeout ({timeout}s)"}
        finally:
            self._pending.pop(reply_id, None)

    async def send_json_message(self, msg: dict) -> None:
        """Fire-and-forget JSON message (no correlated reply)."""
        await self._write_queue.put(dumps(msg))

    def resolve(self, msg_id: str, result: dict) -> None:
        future = self._pending.pop(msg_id, None)
        if future and not future.done():
            future.set_result(result)

    def reject(self, msg_id: str, error: str) -> None:
        future = self._pending.pop(msg_id, None)
        if future and not future.done():
            future.set_result({"ok": False, "exit_code": -1, "output": "", "error": error})

    def fail_all(self, error: str) -> None:
        """Called on disconnect — resolve all pending futures with error.

        Uses a superset schema that satisfies both ADB-command consumers
        (ok/exit_code/output/error) and u2-request consumers (ok/status/body/content_type).
        """
        result = {
            "ok":           False,
            "exit_code":    -1,
            "output":       "",
            "error":        error,
            "status":       0,
            "body":         error,
            "content_type": "",
        }
        for future in list(self._pending.values()):
            if not future.done():
                future.set_result(result)
        self._pending.clear()


# ── Manager ───────────────────────────────────────────────────────────────────

class AdbRelayManager:
    """
    Singleton — holds all active RelayConnection objects.
    device_client.py calls adb_shell() / restart_atx() / restart_u2() (legacy) here.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        # relay_id → RelayConnection
        self._relays: Dict[str, RelayConnection] = {}
        # serial → relay_id (fast lookup)
        self._serial_index: Dict[str, str] = {}
        # serial → RelayScrcpyReceiver (push_frame target)
        self._scrcpy_receivers: Dict[str, Any] = {}
        # serials with an active scrcpy session (start sent, stop not yet sent)
        self._scrcpy_running: set = set()
        # serial → DeviceCapability dict (from agent heartbeats)
        self._capabilities: Dict[str, Dict] = {}
        # serial → "available" | "busy"
        self._pool_state: Dict[str, str] = {}
        # ip/serial → callbacks — called when relay reports a matching device.
        self._pending_scrcpy: Dict[str, list[Any]] = {}
        # Called with (serial) whenever a new device comes online via relay.
        self._on_device_online: Optional[Any] = None
        # Called with (serial) when a relay serial is removed.
        self._on_device_offline: Optional[Any] = None
        # Called with (serial, caps_dict) whenever capabilities are updated from heartbeat.
        self._on_capabilities_update: Optional[Any] = None
        # agent_id → asyncio.Queue  (gRPC ctrl queues, one per connected agent-boot)
        self._grpc_agents: Dict[str, "asyncio.Queue"] = {}
        # Per-device monotonic sequence for a11y_action
        self._a11y_seq: Dict[str, int] = {}
        # Wakes commands admitted during a short gRPC relay reconnect.
        # A Condition avoids polling and lets all waiting phones re-check their
        # own serial atomically after one relay registration/heartbeat update.
        self._relay_state_changed = asyncio.Condition()

    def set_on_device_online(self, callback: Any) -> None:
        """Register a callback fired with (serial) when a new relay device appears."""
        self._on_device_online = callback
        for serial in list(self._serial_index.keys()):
            try:
                callback(serial)
            except Exception as exc:
                logger.debug("on_device_online (retroactive) error serial=%s: %s", serial, exc)

    def set_on_device_offline(self, callback: Any) -> None:
        """Register a callback fired with (serial) when a relay device goes away."""
        self._on_device_offline = callback

    def list_online_serials(self) -> list[str]:
        """Current relay serial index (transport-visible devices)."""
        return list(self._serial_index.keys())

    def _pending_keys_for_serial(self, serial: str) -> list[str]:
        ip = serial.rsplit(":", 1)[0] if ":" in serial else serial
        return list(dict.fromkeys([serial, ip]))

    def _pop_pending_scrcpy_callbacks(self, serial: str) -> list[tuple[str, Any]]:
        callbacks: list[tuple[str, Any]] = []
        seen: set[int] = set()
        for key in self._pending_keys_for_serial(serial):
            for cb in self._pending_scrcpy.pop(key, []):
                ident = id(cb)
                if ident in seen:
                    continue
                seen.add(ident)
                callbacks.append((key, cb))
        return callbacks

    def set_on_capabilities_update(self, callback: Any) -> None:
        """Register a callback fired with (serial, caps) when heartbeat caps arrive."""
        self._on_capabilities_update = callback
        # Fire for already-online devices
        for serial in list(self._serial_index.keys()):
            try:
                callback(serial, self._capabilities.get(serial, {}))
            except Exception as exc:
                logger.debug("on_capabilities_update (retroactive) error serial=%s: %s", serial, exc)

    async def register(self, conn: RelayConnection) -> None:
        callbacks_to_fire: list = []
        async with self._lock:
            self._relays[conn.relay_id] = conn
            for s in conn.serials:
                self._serial_index[s] = conn.relay_id
            for s in conn.serials:
                for key, cb in self._pop_pending_scrcpy_callbacks(s):
                    callbacks_to_fire.append((key, s, cb))
        logger.info(
            "relay registered: id=%s serials=%s",
            conn.relay_id, sorted(conn.serials),
        )
        for ip, serial, cb in callbacks_to_fire:
            try:
                cb(serial)
            except Exception as exc:
                logger.debug("pending scrcpy callback error ip=%s: %s", ip, exc)
        async with self._relay_state_changed:
            self._relay_state_changed.notify_all()
        await self._sync_relay_to_redis(conn)
        if self._on_device_online:
            for s in conn.serials:
                try:
                    self._on_device_online(s)
                except Exception as exc:
                    logger.debug("on_device_online error serial=%s: %s", s, exc)

    async def update_serials(self, relay_id: str, serials: Set[str]) -> None:
        async with self._lock:
            conn = self._relays.get(relay_id)
            if not conn:
                return
            old = conn.serials
            for s in old - serials:
                self._serial_index.pop(s, None)
            for s in serials:
                self._serial_index[s] = relay_id
            conn.serials = serials
            removed = old - serials
            new_serials = serials - old
            for s in removed:
                if self._on_device_offline:
                    try:
                        self._on_device_offline(s)
                    except Exception as exc:
                        logger.debug("on_device_offline error serial=%s: %s", s, exc)
            for s in new_serials:
                for key, cb in self._pop_pending_scrcpy_callbacks(s):
                    try:
                        cb(s)
                    except Exception as exc:
                        logger.debug("pending scrcpy callback error key=%s: %s", key, exc)
                if self._on_device_online:
                    try:
                        self._on_device_online(s)
                    except Exception as exc:
                        logger.debug("on_device_online error serial=%s: %s", s, exc)
        if new_serials:
            async with self._relay_state_changed:
                self._relay_state_changed.notify_all()

    async def _wait_for_relay(
        self,
        serial: str,
        *,
        timeout: float,
    ) -> Optional[RelayConnection]:
        """Wait for one transient reconnect without polling or replaying work."""
        conn = self.relay_for_serial(serial)
        if conn is not None or timeout <= 0:
            return conn

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        async with self._relay_state_changed:
            while True:
                conn = self.relay_for_serial(serial)
                if conn is not None:
                    return conn
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return None
                try:
                    await asyncio.wait_for(
                        self._relay_state_changed.wait(),
                        timeout=remaining,
                    )
                except asyncio.TimeoutError:
                    return None

    async def unregister(
        self,
        relay_id: str,
        error: str = "relay disconnected",
        *,
        expected_conn: Optional[RelayConnection] = None,
    ) -> None:
        async with self._lock:
            conn = self._relays.get(relay_id)
            if not conn:
                return
            if expected_conn is not None and conn is not expected_conn:
                expected_conn.fail_all(error)
                logger.debug(
                    "skip stale relay unregister: id=%s current connection is newer",
                    relay_id,
                )
                return
            self._relays.pop(relay_id, None)
            offline_serials = set(conn.serials)
            for s in conn.serials:
                self._serial_index.pop(s, None)
                self._capabilities.pop(s, None)
                self._pool_state.pop(s, None)
                self._scrcpy_running.discard(s)
        if conn:
            conn.fail_all(error)
            await self._remove_relay_from_redis(relay_id, offline_serials)
            if self._on_device_offline:
                for s in offline_serials:
                    try:
                        self._on_device_offline(s)
                    except Exception as exc:
                        logger.debug("on_device_offline error serial=%s: %s", s, exc)
        logger.info("relay unregistered: id=%s", relay_id)

    def update_capabilities(self, caps_list: list) -> None:
        """Store device capability dicts from agent heartbeat.

        Each item is a plain dict with keys: serial, android_version, sdk,
        brand, model, abi, screen_width, screen_height, ram_gb, has_u2,
        has_stf, has_ocr, tags.

        NOTE: the copy below is an explicit whitelist, so a capability the agent
        starts sending is silently dropped until it is added here — the feature
        that reads it just stays off, with no error anywhere. Add new keys in
        both branches.
        """
        for cap in caps_list:
            if isinstance(cap, dict):
                serial = cap.get("serial", "")
            else:
                # Backward compat with any legacy callers
                serial = getattr(cap, "serial", "")
            if not serial:
                continue
            if isinstance(cap, dict):
                next_caps = {
                    "android_version": cap.get("android_version", ""),
                    "sdk":             cap.get("sdk", ""),
                    "brand":           cap.get("brand", ""),
                    "model":           cap.get("model", ""),
                    "device_name":     cap.get("device_name", ""),
                    "marketing_name":  cap.get("marketing_name", ""),
                    "display_name":    cap.get("display_name", ""),
                    "wlan_ip":         cap.get("wlan_ip", ""),
                    "wlan_cidr":       cap.get("wlan_cidr", ""),
                    "abi":             cap.get("abi", ""),
                    "screen_width":    cap.get("screen_width", 0),
                    "screen_height":   cap.get("screen_height", 0),
                    "ram_gb":          cap.get("ram_gb", 0),
                    "has_u2":          bool(cap.get("has_u2", False)),
                    "has_stf":         bool(cap.get("has_stf", False)),
                    "has_ocr":         bool(cap.get("has_ocr", False)),
                    "has_image_match": bool(cap.get("has_image_match", False)),
                    "hardware_serial": cap.get("hardware_serial", ""),
                    "tags":            list(cap.get("tags", [])),
                }
            else:
                next_caps = {
                    "android_version": cap.android_version,
                    "sdk":             cap.sdk,
                    "brand":           cap.brand,
                    "model":           cap.model,
                    "device_name":     getattr(cap, "device_name", ""),
                    "marketing_name":  getattr(cap, "marketing_name", ""),
                    "display_name":    getattr(cap, "display_name", ""),
                    "wlan_ip":         getattr(cap, "wlan_ip", ""),
                    "wlan_cidr":       getattr(cap, "wlan_cidr", ""),
                    "abi":             cap.abi,
                    "screen_width":    cap.screen_width,
                    "screen_height":   cap.screen_height,
                    "ram_gb":          cap.ram_gb,
                    "has_u2":          cap.has_u2,
                    "has_stf":         cap.has_stf,
                    "has_ocr":         bool(getattr(cap, "has_ocr", False)),
                    "has_image_match": bool(getattr(cap, "has_image_match", False)),
                    "tags":            list(cap.tags),
                }
            self._pool_state.setdefault(serial, "available")
            if self._capabilities.get(serial) == next_caps:
                continue
            self._capabilities[serial] = next_caps
            asyncio.ensure_future(self._sync_caps_to_redis(serial, next_caps))
            if self._on_capabilities_update:
                try:
                    self._on_capabilities_update(serial, next_caps)
                except Exception as exc:
                    logger.debug("on_capabilities_update error serial=%s: %s", serial, exc)

 
    async def _sync_relay_to_redis(self, conn: RelayConnection) -> None:
        from services import redis_store
        if not redis_store.enabled():
            return
        try:
            r = redis_store.client()
            pipe = r.pipeline()
            pipe.hset(redis_store.key("relay:agents"), conn.relay_id, dumps({
                "relay_id": conn.relay_id,
                "serials": sorted(conn.serials),
            }))
            for s in conn.serials:
                pipe.set(redis_store.key(f"device:{s}:relay"), conn.relay_id)
            pipe.delete(redis_store.key(f"relay:{conn.relay_id}:serials"))
            for s in conn.serials:
                pipe.sadd(redis_store.key(f"relay:{conn.relay_id}:serials"), s)
            await pipe.execute()
        except Exception as exc:
            logger.debug("Redis relay sync failed for %s: %s", conn.relay_id, exc)

    async def _remove_relay_from_redis(self, relay_id: str, serials: set) -> None:
        from services import redis_store
        if not redis_store.enabled():
            return
        try:
            r = redis_store.client()
            pipe = r.pipeline()
            pipe.hdel(redis_store.key("relay:agents"), relay_id)
            pipe.delete(redis_store.key(f"relay:{relay_id}:serials"))
            for s in serials:
                pipe.delete(redis_store.key(f"device:{s}:relay"))
                pipe.delete(redis_store.key(f"device:{s}:caps"))
            await pipe.execute()
        except Exception as exc:
            logger.debug("Redis relay remove failed for %s: %s", relay_id, exc)

    async def _sync_caps_to_redis(self, serial: str, caps: dict) -> None:
        from services import redis_store
        if not redis_store.enabled():
            return
        try:
            r = redis_store.client()
            # Convert all values to strings for Redis hash
            str_caps = {k: str(v) for k, v in caps.items()}
            await r.hset(redis_store.key(f"device:{serial}:caps"), mapping=str_caps)
        except Exception as exc:
            logger.debug("Redis caps sync failed for %s: %s", serial, exc)

    # ── Device pool ───────────────────────────────────────────────────────────

    def get_capabilities(self, serial: str) -> Optional[Dict]:
        return self._capabilities.get(serial)

    def list_devices(self, tags: Optional[list] = None) -> list:
        result = []
        for serial, caps in self._capabilities.items():
            if not self.relay_for_serial(serial):
                continue
            if tags and not _match_tags(caps, tags):
                continue
            result.append({
                "serial": serial,
                "state":  self._pool_state.get(serial, "available"),
                **caps,
            })
        return result

    def allocate_device(self, tags: Optional[list] = None) -> Optional[str]:
        for device in self.list_devices(tags):
            serial = device["serial"]
            if self._pool_state.get(serial) == "available":
                self._pool_state[serial] = "busy"
                logger.info("pool: allocated %s (tags=%s)", serial, tags)
                return serial
        return None

    def release_device(self, serial: str) -> None:
        if serial in self._pool_state:
            self._pool_state[serial] = "available"
            logger.info("pool: released %s", serial)

    def register_pending_scrcpy(self, ip: str, callback: Any) -> None:
        callbacks = self._pending_scrcpy.setdefault(ip, [])
        if callback not in callbacks:
            callbacks.append(callback)

    def cancel_pending_scrcpy(self, ip: str, callback: Any | None = None) -> None:
        if callback is None:
            self._pending_scrcpy.pop(ip, None)
            return
        callbacks = self._pending_scrcpy.get(ip)
        if not callbacks:
            return
        self._pending_scrcpy[ip] = [cb for cb in callbacks if cb is not callback]
        if not self._pending_scrcpy[ip]:
            self._pending_scrcpy.pop(ip, None)

    # ── Scrcpy relay ──────────────────────────────────────────────────────────

    def register_scrcpy_receiver(self, serial: str, receiver: Any) -> None:
        self._scrcpy_receivers[serial] = receiver

    def get_scrcpy_receiver(self, serial: str) -> Any:
        """Return the DeviceClient-owned receiver currently bound to this relay ADB serial."""
        return self._scrcpy_receivers.get(serial)

    def unregister_scrcpy_receiver(self, serial: str) -> None:
        self._scrcpy_receivers.pop(serial, None)

    def _resolve_receiver_for_frame(self, serial: str) -> Any:
        """Best-effort receiver lookup for transient serial/key mismatches.

        During reconnect handoff, relay can emit frames under one serial while
        receiver is still registered under another equivalent serial key.
        """
        receiver = self._scrcpy_receivers.get(serial)
        if receiver is not None:
            return receiver

        # 1) Try canonical serial resolution first.
        resolved = self.resolve_serial(serial)
        if resolved != serial:
            receiver = self._scrcpy_receivers.get(resolved)
            if receiver is not None:
                # Self-heal alias so next frame is O(1).
                self._scrcpy_receivers[serial] = receiver
                logger.info(
                    "scrcpy receiver remap: incoming=%s resolved=%s",
                    serial,
                    resolved,
                )
                return receiver

        # 2) Fallback by IP prefix only when the match is unique.
        ip = serial.rsplit(":", 1)[0] if ":" in serial else serial
        matches = [
            key for key in self._scrcpy_receivers
            if (key.rsplit(":", 1)[0] if ":" in key else key) == ip
        ]
        if len(matches) == 1:
            key = matches[0]
            receiver = self._scrcpy_receivers.get(key)
            if receiver is not None:
                self._scrcpy_receivers[serial] = receiver
                logger.info(
                    "scrcpy receiver remap by ip: incoming=%s mapped=%s",
                    serial,
                    key,
                )
                return receiver

        return None

    def dispatch_scrcpy_frame(
        self, serial: str, data: bytes, pts_raw: int, width: int, height: int,
        is_config: bool = False, is_keyframe: bool = False, pts: int = 0,
    ) -> None:
        """Called from WS read loop when a scrcpy binary frame arrives from relay agent."""
        # Backward compat: derive from pts_raw if v2 fields not set
        if not is_config and not is_keyframe and pts == 0 and pts_raw:
            is_config = bool(pts_raw & 0x8000_0000_0000_0000)
            pts = int(pts_raw & ~0x8000_0000_0000_0000)
        receiver = self._resolve_receiver_for_frame(serial)
        if is_config:
            logger.info(
                "dispatch_scrcpy_frame: CONFIG serial=%s data_len=%d w=%d h=%d receiver=%s",
                serial, len(data), width, height,
                "present" if receiver is not None else "MISSING",
            )
        if receiver is None:
            # Self-heal race: relay may start streaming before the WS side finishes
            # attach_scrcpy_stream registration. If a pending callback exists for
            # this device IP, trigger it now so receiver binding catches up.
            keys = self._pending_keys_for_serial(serial)
            callbacks: list[Any] = []
            seen: set[int] = set()
            for key in keys:
                for cb in self._pending_scrcpy.pop(key, []):
                    ident = id(cb)
                    if ident in seen:
                        continue
                    seen.add(ident)
                    callbacks.append(cb)
            if callbacks:
                for cb in callbacks:
                    try:
                        cb(serial)
                    except Exception as exc:
                        logger.debug(
                            "pending scrcpy callback error (frame race) serial=%s: %s",
                            serial,
                            exc,
                        )
                receiver = self._resolve_receiver_for_frame(serial)
                if receiver is not None:
                    for key in keys:
                        self._pending_scrcpy.pop(key, None)
                    try:
                        started = time.perf_counter()
                        receiver.push_frame(
                            data,
                            pts_raw,
                            width,
                            height,
                            is_config=is_config,
                            is_keyframe=is_keyframe,
                            pts=pts,
                        )
                        stream_telemetry.record_dispatch(
                            push_ms=(time.perf_counter() - started) * 1000.0
                        )
                    except Exception as exc:
                        stream_telemetry.record_dispatch(push_error=True)
                        logger.warning("scrcpy push_frame error serial=%s: %s", serial, exc)
                    return
            if not hasattr(self, "_no_receiver_log_count"):
                self._no_receiver_log_count = {}
            cnt = self._no_receiver_log_count.get(serial, 0) + 1
            self._no_receiver_log_count[serial] = cnt
            stream_telemetry.record_dispatch(no_receiver=True)
            if cnt <= 3 or cnt % 300 == 0:
                if not self._scrcpy_receivers:
                    logger.debug(
                        "dispatch_scrcpy_frame: no receiver for serial=%s (frame #%d) — no active consumers",
                        serial,
                        cnt,
                    )
                else:
                    logger.warning(
                        "dispatch_scrcpy_frame: no receiver for serial=%s (frame #%d) — registered: %s",
                        serial, cnt, list(self._scrcpy_receivers.keys()),
                    )
            return
        try:
            started = time.perf_counter()
            receiver.push_frame(data, pts_raw, width, height,
                                is_config=is_config, is_keyframe=is_keyframe, pts=pts)
            stream_telemetry.record_dispatch(
                push_ms=(time.perf_counter() - started) * 1000.0
            )
        except Exception as exc:
            stream_telemetry.record_dispatch(push_error=True)
            logger.warning("scrcpy push_frame error serial=%s: %s", serial, exc)

    async def start_scrcpy(
        self,
        serial: str,
        max_fps: int,
        max_width: int,
        enable_control: bool,
        port: int,
        bitrate: int = 2_000_000,
        low_latency: bool = False,
        profile: str | None = None,
    ) -> bool:
        conn = self.relay_for_serial(serial)
        if conn is None:
            logger.warning("start_scrcpy: no relay for serial=%s", serial)
            return False
        msg = dumps({
            "type":        "scrcpy_start",
            "serial":      serial,
            "max_fps":     max_fps or SCRCPY_DEFAULT_MAX_FPS,
            "max_width":   max_width or SCRCPY_DEFAULT_MAX_WIDTH,
            "control":     enable_control,
            "port":        port,
            "bitrate":     bitrate or SCRCPY_DEFAULT_BITRATE,
            "low_latency": low_latency,
            "profile":     profile or "visible",
        })
        await conn._write_queue.put(msg)
        self._scrcpy_running.add(serial)
        logger.info("scrcpy_start → relay=%s serial=%s port=%d", conn.relay_id, serial, port)
        return True

    def is_scrcpy_running(self, serial: str) -> bool:
        return serial in self._scrcpy_running

    async def stop_scrcpy(self, serial: str, reason: str = "unspecified") -> None:
        self._scrcpy_running.discard(serial)
        conn = self.relay_for_serial(serial)
        if conn is not None:
            msg = dumps({"type": "scrcpy_stop", "serial": serial, "reason": reason})
            await conn._write_queue.put(msg)
            logger.info("scrcpy_stop → relay=%s serial=%s reason=%s", conn.relay_id, serial, reason)
        self.unregister_scrcpy_receiver(serial)

    async def send_scrcpy_control(self, serial: str, data: bytes) -> None:
        """Forward raw control bytes (touch/key) to the relay agent.

        Binary frame: [0x43][slen][serial][ctrl_data]
        """
        conn = self.relay_for_serial(serial)
        if conn is None:
            return
        serial_b = serial.encode()
        slen = len(serial_b)
        frame = bytes([0x43, slen]) + serial_b + data
        await conn._write_queue.put(frame)

    def _resolve_serial_by_ip(self, serial: str) -> Optional[str]:
        ip = serial.rsplit(":", 1)[0] if ":" in serial else serial
        matches = [
            known
            for known in self._serial_index
            if ":" in known and known.rsplit(":", 1)[0] == ip
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            logger.warning(
                "resolve_serial_by_ip ambiguous for ip=%s matches=%s; refusing IP-only resolution",
                ip,
                matches,
            )
        return None

    def resolve_serial(self, serial: str) -> str:
        if serial in self._serial_index:
            return serial
        return self._resolve_serial_by_ip(serial) or serial

    def relay_for_serial(self, serial: str) -> Optional[RelayConnection]:
        relay_id = self._serial_index.get(serial)
        if relay_id:
            return self._relays.get(relay_id)
        actual = self._resolve_serial_by_ip(serial)
        if actual:
            relay_id = self._serial_index.get(actual)
            return self._relays.get(relay_id) if relay_id else None
        return None

    def is_available(self) -> bool:
        return True

    # ── gRPC agent management ─────────────────────────────────────────────────

    def register_grpc_agent(self, agent_id: str, ctrl_q: "asyncio.Queue") -> None:
        """Register a gRPC agent's ctrl queue (device_farm → agent-boot direction)."""
        self._grpc_agents[agent_id] = ctrl_q

    def unregister_grpc_agent(
        self,
        agent_id: str,
        *,
        expected_queue: Optional["asyncio.Queue"] = None,
    ) -> None:
        """Remove gRPC agent and signal its ctrl sender to stop."""
        q = self._grpc_agents.get(agent_id)
        if expected_queue is not None and q is not expected_queue:
            logger.debug(
                "skip stale gRPC agent unregister: id=%s current queue is newer",
                agent_id,
            )
            return
        q = self._grpc_agents.pop(agent_id, None)
        if q:
            try:
                q.put_nowait(None)  # sentinel → stops _send_controls()
            except Exception:
                pass

    async def send_grpc_control(self, serial: str, data: bytes) -> None:
        """Send a raw scrcpy control packet to the agent-boot managing this serial via gRPC.

        Finds the RelayConnection for the serial, then puts a ControlMsg onto the
        gRPC ctrl queue. Falls back to WS send_scrcpy_control() if no gRPC agent found.
        """
        from .grpc_gen import relay_pb2

        conn = self.relay_for_serial(serial)
        if conn is None:
            return

        write_q = conn._write_queue
        # _GrpcWriteQueue wraps the ctrl_q — put_nowait handles conversion
        try:
            frame = bytes([0x43, len(serial.encode())]) + serial.encode() + data
            await write_q.put(frame)
        except Exception as exc:
            logger.debug("send_grpc_control error serial=%s: %s", serial, exc)

    # ── Public API (called from device_client.py) ──────────────────────────

    async def adb_shell(
        self, serial: str, cmd: str, timeout: float = 30.0
    ) -> Optional[str]:
        conn = self.relay_for_serial(serial)
        if conn is None:
            logger.warning("adb_shell: no relay for serial=%s", serial)
            return None
        result = await conn.send_command(serial, cmd, timeout, cmd_type=CMD_SHELL)
        if not result.get("ok") and result.get("error"):
            logger.warning("adb_shell error for %s: %s", serial, result["error"])
        return result.get("output")

    async def restart_u2(self, serial: str, timeout: float = 60.0) -> bool:
        conn = self.relay_for_serial(serial)
        if conn is None:
            return False
        result = await conn.send_command(serial, "", timeout, cmd_type=CMD_RESTART_U2)
        return result.get("ok", False)

    async def restart_atx(self, serial: str, timeout: float = 30.0) -> bool:
        """Ask agent-boot to kill + restart atx-agent on the device.

        Agent-boot runs _restart_atx() locally via ADB (same machine as device),
        polls port 7912 until atx is ready, then returns ok=True.
        Returns False if no relay is connected for this serial.
        """
        conn = self.relay_for_serial(serial)
        if conn is None:
            logger.warning("restart_atx: no relay for serial=%s", serial)
            return False
        actual = self.resolve_serial(serial)
        result = await conn.send_command(actual, "", timeout, cmd_type=CMD_RESTART_ATX)
        return result.get("ok", False)

    async def bootstrap(self, serial: str, timeout: float = 180.0) -> bool:
        """Ask agent-boot to bootstrap the device (push binaries, install APKs, start services).

        Returns True when atx-agent is confirmed listening on port 7912.
        Should be called once after a device first appears online via relay.
        """
        result = await self.run_command(serial, "", timeout, cmd_type=CMD_BOOTSTRAP)
        ok = result.get("ok", False)
        if not ok:
            logger.warning(
                "bootstrap failed for %s: %s",
                serial,
                result.get("error") or result.get("output"),
            )
        return ok

    async def restart_scrcpy(self, serial: str, timeout: float = 30.0) -> dict:
        """Stop + resume scrcpy for serial via the video/WS relay command queue."""
        return await self.run_command(serial, "", timeout, cmd_type=CMD_RESTART_SCRCPY)

    async def run_command(
        self,
        serial: str,
        cmd: str,
        timeout: float,
        *,
        cmd_type: int = CMD_SHELL,
    ) -> dict:
        """Enqueue a relay command and return the agent-boot result dict."""
        conn = self.relay_for_serial(serial)
        if conn is None:
            return {
                "ok": False,
                "exit_code": -1,
                "output": "",
                "error": f"no relay for serial={serial!r}",
            }
        actual = self.resolve_serial(serial)
        return await conn.send_command(actual, cmd, timeout, cmd_type=cmd_type)

    async def screencap(self, serial: str, timeout: float = 30.0) -> bytes:
        """Capture a screenshot via relay → base64 PNG → decoded bytes.

        Returns raw PNG bytes or empty bytes on failure.
        Only used as fallback when scrcpy stream is unavailable.
        """
        import base64
        conn = self.relay_for_serial(serial)
        if conn is None:
            return b""
        actual = self.resolve_serial(serial)
        result = await conn.send_command(actual, "", int(timeout), cmd_type=CMD_SCREENCAP)
        if not result.get("ok"):
            return b""
        b64 = result.get("output", "")
        if not b64:
            return b""
        try:
            return base64.b64decode(b64)
        except Exception as exc:
            logger.warning("screencap base64 decode error serial=%s: %s", serial, exc)
            return b""

    async def probe_caps(self, serial: str, timeout: float = 30.0) -> dict:
        """Ask agent-boot to probe device capabilities → dict with android_version, abi, etc."""
        conn = self.relay_for_serial(serial)
        if conn is None:
            return {}
        actual = self.resolve_serial(serial)
        result = await conn.send_command(actual, "", int(timeout), cmd_type=CMD_PROBE_CAPS)
        if not result.get("ok"):
            return {}
        try:
            return loads(result.get("output", "{}"))
        except Exception:
            return {}

    async def u2_http(
        self,
        serial: str,
        method: str,
        path: str,
        body: str = "",
        content_type: str = "application/json",
        timeout: float = 30.0,
        priority: str | int | None = None,
        deadline_ms: int | float | None = None,
    ) -> dict:
        """Proxy an HTTP request to atx-agent (port 7912) on a relay-managed device."""
        conn = self.relay_for_serial(serial)
        if conn is None:
            return {
                "ok": False, "status": 0,
                "body": f"no relay for serial={serial!r}",
                "content_type": "",
            }
        actual = self.resolve_serial(serial)
        return await conn.send_u2_request(
            actual,
            method,
            path,
            body,
            content_type,
            timeout,
            priority=priority,
            deadline_ms=deadline_ms,
        )

    async def u2_batch(
        self,
        serial: str,
        actions: list[dict],
        early_exit: bool = True,
        timeout: float = 30.0,
        cancel_event: Any = None,
        priority: str | int | None = None,
        deadline_ms: int | float | None = None,
    ) -> dict:
        """Send a u2_batch request to agent-boot and await aggregated results."""
        if not actions:
            return {"ok": True, "stopped_at": None, "results": [], "error": None}
        if cancel_event is not None and cancel_event.is_set():
            return {
                "ok": False,
                "stopped_at": 0,
                "results": [],
                "error": "cancelled",
                "cancelled": True,
            }
        conn = await self._wait_for_relay(
            serial,
            timeout=min(2.0, max(0.0, float(timeout))),
        )
        if conn is None:
            return {"ok": False, "stopped_at": 0, "results": [],
                    "error": f"no relay for serial={serial!r}"}
        if cancel_event is not None and cancel_event.is_set():
            return {
                "ok": False,
                "stopped_at": 0,
                "results": [],
                "error": "cancelled",
                "cancelled": True,
            }
        actual = self.resolve_serial(serial)
        fast_touch = self._u2_batch_touch_fast_path_actions(actions)
        if fast_touch is not None:
            return await self._run_u2_batch_touch_fast_path(
                conn=conn,
                serial=actual,
                prepared=fast_touch,
                early_exit=early_exit,
                cancel_event=cancel_event,
            )
        req_id = f"batch-{uuid.uuid4().hex[:8]}"
        request_task = asyncio.create_task(
            conn.send_json_request(
                msg={
                    "type": "u2_batch", "id": req_id, "serial": actual,
                    "schema": 1, "early_exit": early_exit, "actions": actions,
                    **({"priority": priority} if priority is not None else {}),
                    **({"deadline_ms": deadline_ms} if deadline_ms is not None else {}),
                },
                reply_id=req_id, timeout=timeout,
            )
        )
        try:
            while True:
                if request_task.done():
                    return await request_task
                if cancel_event is not None and cancel_event.is_set():
                    with contextlib.suppress(Exception):
                        await conn.send_json_message({
                            "type": "u2_batch_cancel",
                            "id": req_id,
                            "serial": actual,
                        })
                    request_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await request_task
                    return {
                        "ok": False,
                        "stopped_at": 0,
                        "results": [],
                        "error": "cancelled",
                        "cancelled": True,
                    }
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            request_task.cancel()
            raise

    @staticmethod
    def _u2_batch_touch_fast_path_actions(
        actions: list[dict],
    ) -> Optional[list[tuple[str, dict, float]]]:
        prepared: list[tuple[str, dict, float]] = []
        for idx, act in enumerate(actions, start=1):
            op = str(act.get("op", "") or "")
            payload: dict[str, Any] = {"jsonrpc": "2.0", "id": idx}
            timeout = 1.5
            if op == "click":
                payload["method"] = "click"
                payload["params"] = [int(act["x"]), int(act["y"])]
            elif op == "swipe":
                duration = max(0.0, float(act.get("duration", 0.5)))
                payload["method"] = "swipe"
                payload["params"] = [
                    int(act["fx"]), int(act["fy"]),
                    int(act["tx"]), int(act["ty"]),
                    max(1, int(duration * 40)),
                ]
                timeout = max(1.5, duration + 0.8)
            elif op == "long_click":
                duration = max(0.1, float(act.get("duration", 0.5)))
                payload["method"] = "longClick"
                payload["params"] = [int(act["x"]), int(act["y"])]
                timeout = max(1.5, duration + 0.8)
            else:
                return None
            prepared.append((op, payload, timeout))
        return prepared

    async def _run_u2_batch_touch_fast_path(
        self,
        *,
        conn: RelayConnection,
        serial: str,
        prepared: list[tuple[str, dict, float]],
        early_exit: bool,
        cancel_event: Any = None,
    ) -> dict:
        results: list[dict] = []
        stopped_at: Optional[int] = None
        for idx, (op, payload, timeout) in enumerate(prepared):
            if cancel_event is not None and cancel_event.is_set():
                return {
                    "ok": False,
                    "stopped_at": idx,
                    "results": results,
                    "error": "cancelled",
                    "cancelled": True,
                }
            try:
                res = await conn.send_u2_request(
                    serial,
                    "POST",
                    "/jsonrpc/0",
                    dumps(payload),
                    "application/json",
                    timeout,
                )
                ok, error = self._parse_u2_touch_rpc_result(res)
            except Exception as exc:
                ok, error = False, str(exc)
            entry: dict[str, Any] = {"op": op, "ok": ok}
            if error:
                entry["error"] = error
            results.append(entry)
            if not ok and early_exit:
                stopped_at = idx
                break
            if cancel_event is not None and cancel_event.is_set() and idx + 1 < len(prepared):
                return {
                    "ok": False,
                    "stopped_at": idx + 1,
                    "results": results,
                    "error": "cancelled",
                    "cancelled": True,
                }
        all_ok = all(bool(item.get("ok")) for item in results) and len(results) == len(prepared)
        return {
            "ok": all_ok,
            "stopped_at": stopped_at,
            "results": results,
            "error": None if all_ok else (results[-1].get("error") if results else "touch_failed"),
        }

    @staticmethod
    def _parse_u2_touch_rpc_result(res: dict) -> tuple[bool, str]:
        if not bool(res.get("ok")):
            status = int(res.get("status", 0) or 0)
            if status:
                return False, f"JSON-RPC HTTP {status}"
            return False, str(res.get("body") or "JSON-RPC request failed")
        raw = str(res.get("body") or "")
        if not raw.strip():
            return False, "JSON-RPC empty response"
        try:
            data = loads(raw)
        except Exception:
            return False, f"JSON-RPC invalid response: {raw[:120]!r}"
        if "error" in data:
            return False, f"JSON-RPC error: {data['error']}"
        return True, ""

    async def u2_flow(
        self,
        serial: str,
        flow: str,
        params: dict,
        timeout: float = 30.0,
        priority: str | int | None = None,
        deadline_ms: int | float | None = None,
    ) -> dict:
        """Send a u2_flow request to agent-boot and await result."""
        conn = await self._wait_for_relay(
            serial,
            timeout=min(2.0, max(0.0, float(timeout))),
        )
        if conn is None:
            return {"ok": False, "value": None,
                    "error": f"no relay for serial={serial!r}"}
        actual = self.resolve_serial(serial)
        req_id = f"flow-{uuid.uuid4().hex[:8]}"
        return await conn.send_json_request(
            msg={
                "type": "u2_flow", "id": req_id, "serial": actual,
                "flow": flow, "params": params,
                **({"priority": priority} if priority is not None else {}),
                **({"deadline_ms": deadline_ms} if deadline_ms is not None else {}),
            },
            reply_id=req_id, timeout=timeout,
        )

    async def extra_data(
        self,
        serial: str,
        strategy: str,
        context: dict,
        timeout: float = 45.0,
        cancel_event: Any = None,
    ) -> dict:
        """PA B: relay-only edge extract — u2 dump + ingest on agent-boot."""
        conn = self.relay_for_serial(serial)
        if conn is None:
            return {"ok": False, "error": f"no relay for serial={serial!r}"}
        actual = self.resolve_serial(serial)
        req_id = f"extra-{uuid.uuid4().hex[:10]}"
        grace = max(5.0, min(30.0, timeout * 0.15))
        msg = {
            "type": "extra_data",
            "id": req_id,
            "serial": actual,
            "strategy": strategy,
            "context": context or {},
            "timeout_s": timeout,
        }
        request_task = asyncio.create_task(
            conn.send_json_request(
                msg=msg,
                reply_id=req_id,
                timeout=timeout,
                timeout_grace=grace,
            )
        )
        try:
            while True:
                if request_task.done():
                    result = await request_task
                    break
                if cancel_event is not None and cancel_event.is_set():
                    with contextlib.suppress(Exception):
                        await conn.send_json_message({
                            "type": "extra_data_cancel",
                            "id": req_id,
                            "serial": actual,
                            "strategy": strategy,
                        })
                    request_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await request_task
                    return {"ok": False, "error": "cancelled", "cancelled": True}
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await conn.send_json_message({
                    "type": "extra_data_cancel",
                    "id": req_id,
                    "serial": actual,
                    "strategy": strategy,
                })
            request_task.cancel()
            raise
        if result.get("type") != "extra_data_result":
            with contextlib.suppress(Exception):
                await conn.send_json_message({
                    "type": "extra_data_cancel",
                    "id": req_id,
                    "serial": actual,
                    "strategy": strategy,
                })
            return {
                "ok": False,
                "error": str(result.get("error") or result.get("body") or "invalid_extra_data_result"),
            }
        return result

    async def ocr(
        self,
        serial: str,
        *,
        languages: Optional[list] = None,
        region: Optional[dict] = None,
        min_confidence: float = 0.5,
        want_image_on_empty: bool = False,
        timeout: float = 30.0,
        cancel_event: Any = None,
    ) -> dict:
        """Screenshot + OCR on agent-boot; returns text boxes, not an image.

        Media now flows media-adapter → go2rtc without passing through the farm,
        so there is no local frame to OCR. Running it on the agent also keeps a
        ~800 KB screenshot off the wire on every extraction step.
        """
        conn = self.relay_for_serial(serial)
        if conn is None:
            return {"ok": False, "error": f"no relay for serial={serial!r}"}
        actual = self.resolve_serial(serial)
        req_id = f"ocr-{uuid.uuid4().hex[:10]}"
        grace = max(5.0, min(30.0, timeout * 0.15))
        msg = {
            "type": "ocr",
            "id": req_id,
            "serial": actual,
            "languages": list(languages or []),
            "region": region or None,
            "min_confidence": float(min_confidence),
            "want_image_on_empty": bool(want_image_on_empty),
            "timeout_ms": int(timeout * 1000),
        }
        cancel_msg = {"type": "ocr_cancel", "id": req_id, "serial": actual}
        request_task = asyncio.create_task(
            conn.send_json_request(
                msg=msg,
                reply_id=req_id,
                timeout=timeout,
                timeout_grace=grace,
            )
        )
        try:
            if cancel_event is None:
                # Common case. OCR takes ~230ms, so a sleep-poll like the one
                # extra_data uses (a 45s operation, where it costs nothing)
                # would add up to 100ms — a 40% latency tax — for no benefit.
                result = await request_task
            else:
                while True:
                    if request_task.done():
                        result = await request_task
                        break
                    if cancel_event.is_set():
                        with contextlib.suppress(Exception):
                            await conn.send_json_message(cancel_msg)
                        request_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await request_task
                        return {"ok": False, "error": "cancelled", "cancelled": True}
                    # cancel_event is a threading.Event, so it cannot be awaited;
                    # poll fast enough that cancellation latency stays well under
                    # the OCR itself.
                    await asyncio.sleep(0.02)
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await conn.send_json_message(cancel_msg)
            request_task.cancel()
            raise
        if result.get("type") != "ocr_result":
            with contextlib.suppress(Exception):
                await conn.send_json_message(cancel_msg)
            return {
                "ok": False,
                "error": str(result.get("error") or result.get("body") or "invalid_ocr_result"),
            }
        return result

    async def image_match(
        self,
        serial: str,
        *,
        template_sha256: str,
        template_b64: Optional[str] = None,
        threshold: float = 0.8,
        scale: float = 0.25,
        template_screen_w: Optional[int] = None,
        timeout: float = 20.0,
        cancel_event: Any = None,
    ) -> dict:
        """Find a template on the device screen; the agent returns a coordinate.

        Pass ``template_b64=None`` to try the agent's cache: it replies
        ``need_template`` when it has not seen that hash, and the caller resends
        with bytes. Saves reshipping the same image on every loop iteration.
        """
        conn = self.relay_for_serial(serial)
        if conn is None:
            return {"ok": False, "error": f"no relay for serial={serial!r}"}
        actual = self.resolve_serial(serial)
        req_id = f"imatch-{uuid.uuid4().hex[:10]}"
        grace = max(5.0, min(30.0, timeout * 0.15))
        msg: dict[str, Any] = {
            "type": "image_match",
            "id": req_id,
            "serial": actual,
            "template_sha256": template_sha256,
            "threshold": float(threshold),
            "scale": float(scale),
            "timeout_ms": int(timeout * 1000),
        }
        if template_b64:
            msg["template_b64"] = template_b64
        if template_screen_w:
            msg["template_screen_w"] = int(template_screen_w)
        cancel_msg = {"type": "image_match_cancel", "id": req_id, "serial": actual}
        request_task = asyncio.create_task(
            conn.send_json_request(
                msg=msg, reply_id=req_id, timeout=timeout, timeout_grace=grace,
            )
        )
        try:
            if cancel_event is None:
                # Matching takes ~9ms; a sleep-poll would dominate the call.
                result = await request_task
            else:
                while True:
                    if request_task.done():
                        result = await request_task
                        break
                    if cancel_event.is_set():
                        with contextlib.suppress(Exception):
                            await conn.send_json_message(cancel_msg)
                        request_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await request_task
                        return {"ok": False, "error": "cancelled", "cancelled": True}
                    await asyncio.sleep(0.02)
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await conn.send_json_message(cancel_msg)
            request_task.cancel()
            raise
        if result.get("type") != "image_match_result":
            with contextlib.suppress(Exception):
                await conn.send_json_message(cancel_msg)
            return {
                "ok": False,
                "error": str(result.get("error") or result.get("body") or "invalid_image_match_result"),
            }
        return result

    # ── A11y action relay (gRPC/WS meta JSON channel) ────────────────────────

    def next_a11y_seq(self, serial: str) -> int:
        """Return next per-device monotonic seq (never reset during process lifetime)."""
        actual = self.resolve_serial(serial)
        cur = int(self._a11y_seq.get(actual, 0))
        nxt = cur + 1
        self._a11y_seq[actual] = nxt
        return nxt

    async def a11y_mutate(
        self,
        serial: str,
        action: str,
        payload: dict,
        session_id: str,
        timeout: float = 5.0,
    ) -> dict:
        """
        Mutating a11y action: wait for a11y_ack (accepted/queue position), not final result.
        """
        conn = self.relay_for_serial(serial)
        if conn is None:
            return {"ok": False, "accepted": False, "error": f"no relay for serial={serial!r}"}
        actual = self.resolve_serial(serial)
        req_id = f"a11y-{uuid.uuid4().hex[:12]}"
        seq = self.next_a11y_seq(actual)
        ack = await conn.send_json_request(
            msg={
                "type": "a11y_action",
                "id": req_id,
                "serial": actual,
                "seq": seq,
                "ts": int(asyncio.get_running_loop().time() * 1000),
                "session_id": session_id,
                "mode": "mutate",
                "action": action,
                "payload": payload or {},
            },
            reply_id=req_id,
            timeout=timeout,
        )
        if ack.get("type") != "a11y_ack":
            return {"ok": False, "accepted": False, "error": "invalid_ack"}
        return {
            "ok": bool(ack.get("accepted", False)),
            "accepted": bool(ack.get("accepted", False)),
            "queue_pos": int(ack.get("queue_pos", -1)),
            "seq": int(ack.get("seq", seq)),
            "id": req_id,
            "error": ack.get("error", ""),
        }

    async def a11y_query(
        self,
        serial: str,
        action: str,
        payload: dict,
        session_id: str,
        timeout: float = 5.0,
    ) -> dict:
        """Query-style a11y action: await a11y_result."""
        conn = self.relay_for_serial(serial)
        if conn is None:
            return {"ok": False, "error": f"no relay for serial={serial!r}"}
        actual = self.resolve_serial(serial)
        req_id = f"a11y-{uuid.uuid4().hex[:12]}"
        seq = self.next_a11y_seq(actual)
        result = await conn.send_json_request(
            msg={
                "type": "a11y_action",
                "id": req_id,
                "serial": actual,
                "seq": seq,
                "ts": int(asyncio.get_running_loop().time() * 1000),
                "session_id": session_id,
                "mode": "query",
                "action": action,
                "payload": payload or {},
            },
            reply_id=req_id,
            timeout=timeout,
            timeout_grace=1.0,
        )
        if result.get("type") != "a11y_result":
            return {
                "ok": False,
                "error": str(result.get("error") or result.get("body") or "invalid_result"),
            }
        return result

    async def broadcast_adb_connect(self, ip_port: str, timeout: float = 15.0) -> None:
        async with self._lock:
            conns = list(self._relays.values())
        if not conns:
            logger.debug("broadcast_adb_connect: no relay agents connected")
            return
        logger.info("broadcast_adb_connect → %d relay(s): %s", len(conns), ip_port)

        async def _connect_and_log(conn: RelayConnection) -> None:
            result = await conn.send_command(ip_port, "", timeout, cmd_type=CMD_ADB_CONNECT)
            if result.get("ok"):
                logger.info("adb_connect %s succeeded via relay=%s: %s",
                            ip_port, conn.relay_id, result.get("output"))
            else:
                logger.debug("adb_connect %s failed via relay=%s: %s",
                             ip_port, conn.relay_id, result.get("error") or result.get("output"))

        for conn in conns:
            asyncio.create_task(_connect_and_log(conn))

    def registered_relays(self) -> Dict[str, list]:
        return {
            rid: sorted(c.serials)
            for rid, c in self._relays.items()
        }


# ── WebSocket relay agent session ─────────────────────────────────────────────

class WsRelayAgentSession:
    """
    Handles one WebSocket connection from a relay agent (agent-boot).

    Protocol:
      First message (text) MUST be {"type":"register","relay_id":"...","serials":[...],"version":"..."}
      Subsequent text frames: heartbeat, result
      Binary frames (0x53): scrcpy video frames
    """

    def __init__(self, manager: AdbRelayManager, api_key: Optional[str] = None) -> None:
        self._manager = manager
        self._api_key = api_key

    async def handle(self, ws: Any) -> None:
        """Entry point for /relay-agent WebSocket endpoint."""
        from fastapi import WebSocket as _WS

        # Auth check via header or query param
        if self._api_key:
            provided = (
                ws.headers.get("x-relay-api-key", "")
                or ws.query_params.get("api_key", "")
            )
            if provided != self._api_key:
                await ws.close(code=4001, reason="invalid relay API key")
                return

        await ws.accept()

        relay_id: Optional[str] = None
        conn: Optional[RelayConnection] = None
        write_queue: asyncio.Queue = asyncio.Queue(maxsize=512)

        # ── Writer task: drain write_queue → send WS frames ───────────────────
        async def _writer() -> None:
            try:
                while True:
                    item = await write_queue.get()
                    if item is None:
                        return
                    try:
                        if isinstance(item, bytes):
                            await ws.send_bytes(item)
                        else:
                            await ws.send_text(item)
                    except Exception as exc:
                        logger.debug("relay WS writer error: %s", exc)
                        return
            except asyncio.CancelledError:
                return

        writer_task = asyncio.create_task(_writer())

        try:
            while True:
                try:
                    raw = await ws.receive()
                except Exception:
                    break

                msg_type = raw.get("type")
                if msg_type == "websocket.disconnect":
                    break

                # Binary frame: scrcpy video (0x53) or control response (future)
                if "bytes" in raw and raw["bytes"] is not None:
                    data: bytes = raw["bytes"]
                    if len(data) >= 2 and data[0] == 0x53:
                        # Scrcpy frame: [0x53][flags][slen][serial][w:2BE][h:2BE][pts_raw:8BE][payload]
                        if len(data) < 3:
                            continue
                        flags  = data[1]
                        slen   = data[2]
                        if len(data) < 3 + slen + 2 + 2 + 8:
                            continue
                        serial_b = data[3:3 + slen]
                        serial   = serial_b.decode("utf-8", errors="replace")
                        off      = 3 + slen
                        width, height = struct.unpack(">HH", data[off:off + 4])
                        pts_raw, = struct.unpack(">Q", data[off + 4:off + 12])
                        payload  = data[off + 12:]
                        is_cfg   = bool(flags & 0x01)
                        is_key   = bool(flags & 0x02)
                        pts      = int(pts_raw & ~0x8000_0000_0000_0000)
                        if conn is not None:
                            self._manager.dispatch_scrcpy_frame(
                                serial, payload, pts_raw,
                                width, height,
                                is_config=is_cfg,
                                is_keyframe=is_key,
                                pts=pts,
                            )
                    continue

                # Text frame: JSON control message
                text = raw.get("text") or ""
                if not text:
                    continue
                try:
                    msg = loads(text)
                except Exception:
                    continue

                mtype = msg.get("type", "")

                if mtype == "register":
                    relay_id = msg.get("relay_id") or f"relay-{uuid.uuid4().hex[:8]}"
                    serials  = set(msg.get("serials") or [])
                    conn = RelayConnection(relay_id, write_queue)
                    conn.serials = serials
                    await self._manager.register(conn)
                    ack = dumps({
                        "type":    "ack",
                        "message": f"registered {len(serials)} serials",
                    })
                    await write_queue.put(ack)
                    logger.info("relay WS registered: id=%s serials=%s", relay_id, sorted(serials))

                elif mtype == "result":
                    if conn is None:
                        continue
                    conn.resolve(
                        msg.get("msg_id", ""),
                        {
                            "ok":       msg.get("ok", False),
                            "output":   msg.get("output", ""),
                            "exit_code": msg.get("exit_code", -1),
                            "error":    msg.get("error", ""),
                        },
                    )

                elif mtype == "u2_result":
                    if conn is None:
                        continue
                    conn.resolve(
                        msg.get("msg_id", ""),
                        {
                            "ok":           msg.get("ok", False),
                            "status":       msg.get("status", 0),
                            "body":         msg.get("body", ""),
                            "content_type": msg.get("content_type", ""),
                        },
                    )

                elif mtype in _REQUEST_REPLY_TYPES:
                    if conn is None:
                        continue
                    conn.resolve(msg.get("id", ""), msg)

                elif mtype == "a11y_ack":
                    if conn is None:
                        continue
                    conn.resolve(msg.get("id", ""), msg)

                elif mtype == "a11y_result":
                    if conn is None:
                        continue
                    conn.resolve(msg.get("id", ""), msg)

                elif mtype == "heartbeat":
                    if conn is None:
                        continue
                    new_serials = set(msg.get("serials") or [])
                    await self._manager.update_serials(relay_id, new_serials)
                    caps = msg.get("capabilities")
                    if caps:
                        self._manager.update_capabilities(caps)
                    logger.debug("heartbeat relay=%s serials=%s", relay_id, new_serials)

        except Exception as exc:
            logger.warning("relay WS stream error (relay=%s): %s", relay_id, exc)
        finally:
            with contextlib.suppress(Exception):
                await write_queue.put(None)
            if not writer_task.done():
                writer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await writer_task
            if relay_id:
                await self._manager.unregister(relay_id, "relay disconnected")
            try:
                await ws.close()
            except Exception:
                pass


# ── Lifecycle ─────────────────────────────────────────────────────────────────

_manager: Optional[AdbRelayManager] = None


def get_relay_manager() -> Optional[AdbRelayManager]:
    return _manager


def create_relay_manager() -> AdbRelayManager:
    """Create (or return existing) singleton AdbRelayManager."""
    global _manager
    if _manager is None:
        _manager = AdbRelayManager()
    return _manager


# Legacy stubs so old import sites don't crash during migration window
async def init_relay_server(port: int = 50051, api_key: Optional[str] = None) -> Optional[AdbRelayManager]:
    """Deprecated — use create_relay_manager() + WsRelayAgentSession instead."""
    logger.warning("init_relay_server() is deprecated — relay now uses WebSocket on main web port")
    return create_relay_manager()


async def stop_relay_server() -> None:
    """Deprecated — WS relay has no separate server to stop."""
    pass
