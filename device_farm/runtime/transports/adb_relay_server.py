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
import json
import logging
import struct
import uuid
from typing import Any, Callable, Dict, Optional, Set

logger = logging.getLogger(__name__)

# CMD_TYPE constants (must match agent-boot relay/agent.py)
CMD_SHELL        = 0
CMD_RESTART_U2   = 1
CMD_ADB_CONNECT  = 2
CMD_RESTART_ATX  = 3
CMD_BOOTSTRAP    = 4  # push binaries + install APKs + start atx-agent + u2
CMD_SCREENCAP    = 5  # screencap → base64 PNG in result["output"]
CMD_PROBE_CAPS   = 6  # probe_capabilities() → JSON dict in result["output"]


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

        msg = json.dumps({
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
    ) -> dict:
        """Send an HTTP proxy request to atx-agent on the remote device, await result."""
        msg_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[msg_id] = future

        msg = json.dumps({
            "type":         "u2_request",
            "msg_id":       msg_id,
            "serial":       serial,
            "method":       method,
            "path":         path,
            "body":         body,
            "content_type": content_type,
            "timeout":      max(1.0, float(timeout)),
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

        await self._write_queue.put(json.dumps(msg))

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
        await self._write_queue.put(json.dumps(msg))

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
        # ip → callable — called when relay reports a device at that IP.
        self._pending_scrcpy: Dict[str, Any] = {}
        # Called with (serial) whenever a new device comes online via relay.
        self._on_device_online: Optional[Any] = None
        # Called with (serial, caps_dict) whenever capabilities are updated from heartbeat.
        self._on_capabilities_update: Optional[Any] = None
        # agent_id → asyncio.Queue  (gRPC ctrl queues, one per connected agent-boot)
        self._grpc_agents: Dict[str, "asyncio.Queue"] = {}
        # Per-device monotonic sequence for a11y_action
        self._a11y_seq: Dict[str, int] = {}

    def set_on_device_online(self, callback: Any) -> None:
        """Register a callback fired with (serial) when a new relay device appears."""
        self._on_device_online = callback

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
                ip = s.rsplit(":", 1)[0] if ":" in s else s
                cb = self._pending_scrcpy.pop(ip, None)
                if cb is not None:
                    callbacks_to_fire.append((ip, s, cb))
        logger.info(
            "relay registered: id=%s serials=%s",
            conn.relay_id, sorted(conn.serials),
        )
        for ip, serial, cb in callbacks_to_fire:
            try:
                cb(serial)
            except Exception as exc:
                logger.debug("pending scrcpy callback error ip=%s: %s", ip, exc)
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
            new_serials = serials - old
            for s in new_serials:
                ip = s.rsplit(":", 1)[0] if ":" in s else s
                cb = self._pending_scrcpy.pop(ip, None)
                if cb is not None:
                    try:
                        cb(s)
                    except Exception as exc:
                        logger.debug("pending scrcpy callback error ip=%s: %s", ip, exc)
                if self._on_device_online:
                    try:
                        self._on_device_online(s)
                    except Exception as exc:
                        logger.debug("on_device_online error serial=%s: %s", s, exc)

    async def unregister(self, relay_id: str, error: str = "relay disconnected") -> None:
        async with self._lock:
            conn = self._relays.pop(relay_id, None)
            if not conn:
                return
            for s in conn.serials:
                self._serial_index.pop(s, None)
                self._capabilities.pop(s, None)
                self._pool_state.pop(s, None)
                self._scrcpy_running.discard(s)
        if conn:
            conn.fail_all(error)
            await self._remove_relay_from_redis(relay_id, conn.serials)
        logger.info("relay unregistered: id=%s", relay_id)

    def update_capabilities(self, caps_list: list) -> None:
        """Store device capability dicts from agent heartbeat.

        Each item is a plain dict with keys: serial, android_version, sdk,
        brand, model, abi, screen_width, screen_height, ram_gb, has_u2,
        has_stf, tags.
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
                self._capabilities[serial] = {
                    "android_version": cap.get("android_version", ""),
                    "sdk":             cap.get("sdk", ""),
                    "brand":           cap.get("brand", ""),
                    "model":           cap.get("model", ""),
                    "abi":             cap.get("abi", ""),
                    "screen_width":    cap.get("screen_width", 0),
                    "screen_height":   cap.get("screen_height", 0),
                    "ram_gb":          cap.get("ram_gb", 0),
                    "has_u2":          bool(cap.get("has_u2", False)),
                    "has_stf":         bool(cap.get("has_stf", False)),
                    "tags":            list(cap.get("tags", [])),
                }
            else:
                self._capabilities[serial] = {
                    "android_version": cap.android_version,
                    "sdk":             cap.sdk,
                    "brand":           cap.brand,
                    "model":           cap.model,
                    "abi":             cap.abi,
                    "screen_width":    cap.screen_width,
                    "screen_height":   cap.screen_height,
                    "ram_gb":          cap.ram_gb,
                    "has_u2":          cap.has_u2,
                    "has_stf":         cap.has_stf,
                    "tags":            list(cap.tags),
                }
            self._pool_state.setdefault(serial, "available")
            asyncio.ensure_future(self._sync_caps_to_redis(serial, self._capabilities[serial]))
            if self._on_capabilities_update:
                try:
                    self._on_capabilities_update(serial, self._capabilities[serial])
                except Exception as exc:
                    logger.debug("on_capabilities_update error serial=%s: %s", serial, exc)

 
    async def _sync_relay_to_redis(self, conn: RelayConnection) -> None:
        from services import redis_store
        if not redis_store.enabled():
            return
        try:
            r = redis_store.client()
            pipe = r.pipeline()
            pipe.hset(redis_store.key("relay:agents"), conn.relay_id, json.dumps({
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
        self._pending_scrcpy[ip] = callback

    def cancel_pending_scrcpy(self, ip: str) -> None:
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
            ip = serial.rsplit(":", 1)[0] if ":" in serial else serial
            cb = self._pending_scrcpy.get(ip)
            if cb is not None:
                try:
                    cb(serial)
                except Exception as exc:
                    logger.debug("pending scrcpy callback error (frame race) ip=%s: %s", ip, exc)
                receiver = self._resolve_receiver_for_frame(serial)
                if receiver is not None:
                    self._pending_scrcpy.pop(ip, None)
                    try:
                        receiver.push_frame(
                            data,
                            pts_raw,
                            width,
                            height,
                            is_config=is_config,
                            is_keyframe=is_keyframe,
                            pts=pts,
                        )
                    except Exception as exc:
                        logger.warning("scrcpy push_frame error serial=%s: %s", serial, exc)
                    return
            if not hasattr(self, "_no_receiver_log_count"):
                self._no_receiver_log_count = {}
            cnt = self._no_receiver_log_count.get(serial, 0) + 1
            self._no_receiver_log_count[serial] = cnt
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
            receiver.push_frame(data, pts_raw, width, height,
                                is_config=is_config, is_keyframe=is_keyframe, pts=pts)
        except Exception as exc:
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
    ) -> bool:
        conn = self.relay_for_serial(serial)
        if conn is None:
            logger.warning("start_scrcpy: no relay for serial=%s", serial)
            return False
        msg = json.dumps({
            "type":        "scrcpy_start",
            "serial":      serial,
            "max_fps":     max_fps or 30,
            "max_width":   max_width or 800,
            "control":     enable_control,
            "port":        port,
            "bitrate":     bitrate,
            "low_latency": low_latency,
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
            msg = json.dumps({"type": "scrcpy_stop", "serial": serial, "reason": reason})
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

    def unregister_grpc_agent(self, agent_id: str) -> None:
        """Remove gRPC agent and signal its ctrl sender to stop."""
        q = self._grpc_agents.pop(agent_id, None)
        if q:
            try:
                q.put_nowait(None)  # sentinel → stops _send_controls()
            except Exception:
                pass

    def dispatch_grpc_video_frame(self, frame: Any) -> None:
        """Route a VideoFrame proto received via gRPC to the appropriate RelayScrcpyReceiver."""
        # Build pts_raw matching the existing dispatch_scrcpy_frame signature
        pts_raw = int(frame.pts_us)
        if frame.is_config:
            pts_raw |= 0x8000_0000_0000_0000
        self.dispatch_scrcpy_frame(
            frame.serial,
            bytes(frame.data),
            pts_raw,
            frame.width,
            frame.height,
            is_config=frame.is_config,
            is_keyframe=frame.is_key,
            pts=frame.pts_us,
        )

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
        conn = self.relay_for_serial(serial)
        if conn is None:
            logger.warning("bootstrap: no relay for serial=%s", serial)
            return False
        actual = self.resolve_serial(serial)
        result = await conn.send_command(actual, "", int(timeout), cmd_type=CMD_BOOTSTRAP)
        ok = result.get("ok", False)
        if not ok:
            logger.warning("bootstrap failed for %s: %s",
                           serial, result.get("error") or result.get("output"))
        return ok

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
        import json
        conn = self.relay_for_serial(serial)
        if conn is None:
            return {}
        actual = self.resolve_serial(serial)
        result = await conn.send_command(actual, "", int(timeout), cmd_type=CMD_PROBE_CAPS)
        if not result.get("ok"):
            return {}
        try:
            return json.loads(result.get("output", "{}"))
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
        return await conn.send_u2_request(actual, method, path, body, content_type, timeout)

    async def u2_batch(
        self,
        serial: str,
        actions: list[dict],
        early_exit: bool = True,
        timeout: float = 30.0,
    ) -> dict:
        """Send a u2_batch request to agent-boot and await aggregated results."""
        if not actions:
            return {"ok": True, "stopped_at": None, "results": [], "error": None}
        conn = self.relay_for_serial(serial)
        if conn is None:
            return {"ok": False, "stopped_at": 0, "results": [],
                    "error": f"no relay for serial={serial!r}"}
        actual = self.resolve_serial(serial)
        req_id = f"batch-{uuid.uuid4().hex[:8]}"
        return await conn.send_json_request(
            msg={
                "type": "u2_batch", "id": req_id, "serial": actual,
                "schema": 1, "early_exit": early_exit, "actions": actions,
            },
            reply_id=req_id, timeout=timeout,
        )

    async def u2_flow(
        self,
        serial: str,
        flow: str,
        params: dict,
        timeout: float = 30.0,
    ) -> dict:
        """Send a u2_flow request to agent-boot and await result."""
        conn = self.relay_for_serial(serial)
        if conn is None:
            return {"ok": False, "value": None,
                    "error": f"no relay for serial={serial!r}"}
        actual = self.resolve_serial(serial)
        req_id = f"flow-{uuid.uuid4().hex[:8]}"
        return await conn.send_json_request(
            msg={
                "type": "u2_flow", "id": req_id, "serial": actual,
                "flow": flow, "params": params,
            },
            reply_id=req_id, timeout=timeout,
        )

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
            timeout_grace=0.0,
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
                    msg = json.loads(text)
                except Exception:
                    continue

                mtype = msg.get("type", "")

                if mtype == "register":
                    relay_id = msg.get("relay_id") or f"relay-{uuid.uuid4().hex[:8]}"
                    serials  = set(msg.get("serials") or [])
                    conn = RelayConnection(relay_id, write_queue)
                    conn.serials = serials
                    await self._manager.register(conn)
                    ack = json.dumps({
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

                elif mtype in ("u2_batch_result", "u2_flow_result"):
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
            await write_queue.put(None)
            writer_task.cancel()
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
