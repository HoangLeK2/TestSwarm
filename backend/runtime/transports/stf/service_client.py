from __future__ import annotations

import logging
import socket
import threading
import time
from typing import Callable, Dict, List, Optional

from runtime.transports.stf.agent_client import STFAgentClient  # noqa: F401  (import cycles guard for tooling)
from runtime.transports.stf.enums import MsgType
from runtime.transports.stf.protobuf_codec import (
    _build_envelope,
    _decode_string,
    _encode_length_field,
    _encode_string_field,
    _encode_varint_field,
    _frame_message,
    _parse_fields,
    _read_varint,
)
from runtime.transports.stf.types import BatteryInfo, ConnectivityInfo, DisplayInfo, PhoneStateInfo


class STFServiceClient(threading.Thread):
    """
    Background thread that:
    - Connects to STFService socket (forwarded via ADB or WS tunnel)
    - Streams all 6 event types (battery, rotation, connectivity, airplane, phone, browser)
    - Supports request-response queries and control commands
    - Thread-safe: all state accessed via lock
    """

    def __init__(
        self,
        serial: str,
        host: str,
        port: int,
        on_battery: Optional[Callable[[int], None]] = None,
        on_rotation: Optional[Callable[[int], None]] = None,
        on_connectivity: Optional[Callable[[ConnectivityInfo], None]] = None,
        on_airplane: Optional[Callable[[bool], None]] = None,
        on_phone_state: Optional[Callable[[PhoneStateInfo], None]] = None,
        on_stream_error: Optional[Callable[[Exception], None]] = None,
    ) -> None:
        super().__init__(daemon=True, name=f"stfsvc-{serial}")
        self.serial = serial
        self.host = host
        self.port = port

        self._on_battery = on_battery
        self._on_rotation = on_rotation
        self._on_connectivity = on_connectivity
        self._on_airplane = on_airplane
        self._on_phone_state = on_phone_state
        self._on_stream_error = on_stream_error

        self._logger = logging.getLogger(f"stfservice.{serial}")
        self._running = False
        self._lock = threading.Lock()

        # State from events
        self._battery = BatteryInfo()
        self._rotation: int = 0
        self._connectivity = ConnectivityInfo()
        self._airplane_mode: bool = False
        self._phone_state = PhoneStateInfo()

        # Socket for request-response (shared with event stream)
        self._sock: Optional[socket.socket] = None
        self._sock_lock = threading.Lock()

        # Request-response: id counter + pending responses
        self._req_id = 0
        self._req_id_lock = threading.Lock()
        self._pending: Dict[int, threading.Event] = {}
        self._responses: Dict[int, bytes] = {}

    # ── Public API: State Getters ────────────────────────────────────────────

    def start_client(self) -> None:
        self._running = True
        if not self.is_alive():
            self.start()

    def stop_client(self) -> None:
        self._running = False
        with self._sock_lock:
            if self._sock:
                try:
                    self._sock.close()
                except Exception:
                    pass

    @property
    def connected(self) -> bool:
        with self._sock_lock:
            return self._sock is not None

    def get_battery(self) -> int:
        """Return last known battery level (0-100), or -1 if unknown."""
        with self._lock:
            return self._battery.level

    def get_battery_info(self) -> BatteryInfo:
        """Return full battery info."""
        with self._lock:
            return BatteryInfo(
                status=self._battery.status,
                health=self._battery.health,
                source=self._battery.source,
                level=self._battery.level,
                scale=self._battery.scale,
                temp=self._battery.temp,
                voltage=self._battery.voltage,
            )

    def get_rotation(self) -> int:
        """Return last known rotation in degrees (0/90/180/270)."""
        with self._lock:
            return self._rotation

    def get_connectivity(self) -> ConnectivityInfo:
        with self._lock:
            return ConnectivityInfo(
                connected=self._connectivity.connected,
                type=self._connectivity.type,
                subtype=self._connectivity.subtype,
                failover=self._connectivity.failover,
                roaming=self._connectivity.roaming,
            )

    def get_airplane_mode(self) -> bool:
        with self._lock:
            return self._airplane_mode

    def get_phone_state(self) -> PhoneStateInfo:
        with self._lock:
            return PhoneStateInfo(
                state=self._phone_state.state,
                manual=self._phone_state.manual,
                operator=self._phone_state.operator,
            )

    # ── Public API: Request-Response Queries ────────────────────────────────

    def get_display(self, display_id: int = 0) -> Optional[DisplayInfo]:
        payload = _encode_varint_field(1, display_id)
        resp = self._send_request(MsgType.GET_DISPLAY, payload, timeout=5.0)
        if resp is None:
            return None
        f = _parse_fields(resp)
        if not f.get(1, 0):  # success
            return None
        return DisplayInfo(
            width=f.get(2, 0),
            height=f.get(3, 0),
            xdpi=f.get(4, 0.0),
            ydpi=f.get(5, 0.0),
            fps=f.get(6, 0.0),
            density=f.get(7, 0.0),
            rotation=f.get(8, 0),
            secure=bool(f.get(9, 0)),
        )

    def get_clipboard(self) -> Optional[str]:
        payload = _encode_varint_field(1, 1)  # ClipboardType.TEXT = 1
        resp = self._send_request(MsgType.GET_CLIPBOARD, payload, timeout=5.0)
        if resp is None:
            return None
        f = _parse_fields(resp)
        if not f.get(1, 0):  # success
            return None
        text_bytes = f.get(3, b"")
        return _decode_string(text_bytes) if text_bytes else ""

    def get_wifi_status(self) -> Optional[bool]:
        resp = self._send_request(MsgType.GET_WIFI_STATUS, b"", timeout=5.0)
        if resp is None:
            return None
        f = _parse_fields(resp)
        if not f.get(1, 0):
            return None
        return bool(f.get(2, 0))

    def get_bluetooth_status(self) -> Optional[bool]:
        resp = self._send_request(MsgType.GET_BLUETOOTH_STATUS, b"", timeout=5.0)
        if resp is None:
            return None
        f = _parse_fields(resp)
        if not f.get(1, 0):
            return None
        return bool(f.get(2, 0))

    def get_ringer_mode(self) -> Optional[str]:
        resp = self._send_request(MsgType.GET_RINGER_MODE, b"", timeout=5.0)
        if resp is None:
            return None
        f = _parse_fields(resp)
        if not f.get(1, 0):
            return None
        mode_val = f.get(2, 2)
        return {0: "silent", 1: "vibrate", 2: "normal"}.get(mode_val, "normal")

    def get_root_status(self) -> Optional[bool]:
        resp = self._send_request(MsgType.GET_ROOT_STATUS, b"", timeout=5.0)
        if resp is None:
            return None
        f = _parse_fields(resp)
        if not f.get(1, 0):
            return None
        return bool(f.get(2, 0))

    def get_sd_status(self) -> Optional[bool]:
        resp = self._send_request(MsgType.GET_SD_STATUS, b"", timeout=5.0)
        if resp is None:
            return None
        f = _parse_fields(resp)
        if not f.get(1, 0):
            return None
        return bool(f.get(2, 0))

    def get_version(self) -> Optional[str]:
        resp = self._send_request(MsgType.GET_VERSION, b"", timeout=5.0)
        if resp is None:
            return None
        f = _parse_fields(resp)
        if not f.get(1, 0):
            return None
        v = f.get(2, b"")
        return _decode_string(v) if v else ""

    def get_properties(self, props: List[str] = None) -> Optional[Dict[str, str]]:
        payload = b""
        if props:
            for p in props:
                payload += _encode_string_field(1, p)
        resp = self._send_request(MsgType.GET_PROPERTIES, payload, timeout=5.0)
        if resp is None:
            return None
        f = _parse_fields(resp)
        if not f.get(1, 0):
            return None
        result: Dict[str, str] = {}
        raw = f.get(2, b"")
        if isinstance(raw, bytes) and raw:
            pf = _parse_fields(raw)
            name = _decode_string(pf.get(1, b"")) if pf.get(1) else ""
            value = _decode_string(pf.get(2, b"")) if pf.get(2) else ""
            if name:
                result[name] = value
        return result

    def get_accounts(self, account_type: str = "") -> Optional[List[str]]:
        payload = b""
        if account_type:
            payload = _encode_string_field(1, account_type)
        resp = self._send_request(MsgType.GET_ACCOUNTS, payload, timeout=5.0)
        if resp is None:
            return None
        f = _parse_fields(resp)
        if not f.get(1, 0):
            return None
        accts = f.get(2, b"")
        if isinstance(accts, bytes) and accts:
            return [_decode_string(accts)]
        return []

    # ── Public API: Control Commands ────────────────────────────────────────

    def set_clipboard(self, text: str) -> bool:
        payload = _encode_varint_field(1, 1) + _encode_string_field(2, text)
        resp = self._send_request(MsgType.SET_CLIPBOARD, payload, timeout=5.0)
        if resp is None:
            return False
        f = _parse_fields(resp)
        return bool(f.get(1, 0))

    def set_wifi_enabled(self, enabled: bool) -> bool:
        payload = _encode_varint_field(1, int(enabled))
        resp = self._send_request(MsgType.SET_WIFI_ENABLED, payload, timeout=5.0)
        if resp is None:
            return False
        f = _parse_fields(resp)
        return bool(f.get(1, 0))

    def set_bluetooth_enabled(self, enabled: bool) -> bool:
        payload = _encode_varint_field(1, int(enabled))
        resp = self._send_request(MsgType.SET_BLUETOOTH_ENABLED, payload, timeout=5.0)
        if resp is None:
            return False
        f = _parse_fields(resp)
        return bool(f.get(1, 0))

    def set_keyguard(self, enabled: bool) -> bool:
        payload = _encode_varint_field(1, int(enabled))
        resp = self._send_request(MsgType.SET_KEYGUARD_STATE, payload, timeout=5.0)
        if resp is None:
            return False
        f = _parse_fields(resp)
        return bool(f.get(1, 0))

    def set_wake_lock(self, enabled: bool) -> bool:
        payload = _encode_varint_field(1, int(enabled))
        resp = self._send_request(MsgType.SET_WAKE_LOCK, payload, timeout=5.0)
        if resp is None:
            return False
        f = _parse_fields(resp)
        return bool(f.get(1, 0))

    def set_ringer_mode(self, mode: str) -> bool:
        mode_map = {"silent": 0, "vibrate": 1, "normal": 2}
        mode_val = mode_map.get((mode or "").lower(), 2)
        payload = _encode_varint_field(1, mode_val)
        resp = self._send_request(MsgType.SET_RINGER_MODE, payload, timeout=5.0)
        if resp is None:
            return False
        f = _parse_fields(resp)
        return bool(f.get(1, 0))

    def set_master_mute(self, enabled: bool) -> bool:
        payload = _encode_varint_field(1, int(enabled))
        resp = self._send_request(MsgType.SET_MASTER_MUTE, payload, timeout=5.0)
        if resp is None:
            return False
        f = _parse_fields(resp)
        return bool(f.get(1, 0))

    # ── Public API: Device Actions ──────────────────────────────────────────

    def identify(self, device_serial: str) -> bool:
        payload = _encode_string_field(1, device_serial)
        resp = self._send_request(MsgType.DO_IDENTIFY, payload, timeout=5.0)
        if resp is None:
            return False
        f = _parse_fields(resp)
        return bool(f.get(1, 0))

    def clean_bluetooth_bonds(self) -> bool:
        resp = self._send_request(MsgType.DO_CLEAN_BLUETOOTH_BONDED, b"", timeout=5.0)
        if resp is None:
            return False
        f = _parse_fields(resp)
        return bool(f.get(1, 0))

    def remove_account(self, account_type: str, account: str = "") -> bool:
        payload = _encode_string_field(1, account_type)
        if account:
            payload += _encode_string_field(2, account)
        resp = self._send_request(MsgType.DO_REMOVE_ACCOUNT, payload, timeout=5.0)
        if resp is None:
            return False
        f = _parse_fields(resp)
        return bool(f.get(1, 0))

    # ── Internal: Event Loop ────────────────────────────────────────────────

    def run(self) -> None:
        while self._running:
            try:
                self._connect_and_stream()
            except Exception as exc:
                if self._running:
                    if self._on_stream_error:
                        try:
                            self._on_stream_error(exc)
                        except Exception as cb_exc:
                            self._logger.debug(f"[{self.serial}] STFService on_stream_error callback failed: {cb_exc}")
                    self._logger.warning(f"[{self.serial}] STFService stream error: {exc}; retrying in 3s")
                    time.sleep(3)

    def _connect_and_stream(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10.0)
        try:
            sock.connect((self.host, self.port))
            sock.settimeout(30.0)
            with self._sock_lock:
                self._sock = sock
            self._logger.info(f"[{self.serial}] STFService connected on {self.host}:{self.port}")

            while self._running:
                try:
                    msg_len = _read_varint(sock)
                except socket.timeout:
                    continue
                if msg_len == 0:
                    continue

                msg_data = b""
                while len(msg_data) < msg_len:
                    chunk = sock.recv(msg_len - len(msg_data))
                    if not chunk:
                        raise ConnectionError("STFService socket closed mid-message")
                    msg_data += chunk

                self._handle_message(msg_data)
        finally:
            with self._sock_lock:
                self._sock = None
            sock.close()

    def _handle_message(self, data: bytes) -> None:
        try:
            envelope = _parse_fields(data)
            msg_type = envelope.get(2, 0)
            msg_id = envelope.get(1, 0)
            msg_body = envelope.get(3, b"")
            if not isinstance(msg_body, bytes):
                msg_body = b""

            if msg_id and msg_id in self._pending:
                self._responses[msg_id] = msg_body
                self._pending[msg_id].set()
                return

            if msg_type == MsgType.EVENT_BATTERY:
                self._on_battery_event(msg_body)
            elif msg_type == MsgType.EVENT_ROTATION:
                self._on_rotation_event(msg_body)
            elif msg_type == MsgType.EVENT_CONNECTIVITY:
                self._on_connectivity_event(msg_body)
            elif msg_type == MsgType.EVENT_AIRPLANE_MODE:
                self._on_airplane_event(msg_body)
            elif msg_type == MsgType.EVENT_PHONE_STATE:
                self._on_phone_state_event(msg_body)
            # EVENT_BROWSER_PACKAGE is rarely needed here
        except Exception as exc:
            self._logger.debug(f"[{self.serial}] STFService parse error: {exc}")

    def _on_battery_event(self, body: bytes) -> None:
        f = _parse_fields(body)
        with self._lock:
            if f.get(1):
                self._battery.status = _decode_string(f[1])
            if f.get(2):
                self._battery.health = _decode_string(f[2])
            if f.get(3):
                self._battery.source = _decode_string(f[3])
            if 4 in f:
                self._battery.level = f[4]
            if 5 in f:
                self._battery.scale = f[5]
            if 6 in f:
                self._battery.temp = f[6]
            if 7 in f:
                self._battery.voltage = f[7]
            level = self._battery.level
        if self._on_battery:
            self._on_battery(level)

    def _on_rotation_event(self, body: bytes) -> None:
        f = _parse_fields(body)
        raw = f.get(1, 0)
        degrees = raw * 90 if raw <= 3 else raw
        with self._lock:
            self._rotation = degrees
        if self._on_rotation:
            self._on_rotation(degrees)

    def _on_connectivity_event(self, body: bytes) -> None:
        f = _parse_fields(body)
        info = ConnectivityInfo(
            connected=bool(f.get(1, 0)),
            type=_decode_string(f[2]) if f.get(2) else "",
            subtype=_decode_string(f[3]) if f.get(3) else "",
            failover=bool(f.get(4, 0)),
            roaming=bool(f.get(5, 0)),
        )
        with self._lock:
            self._connectivity = info
        if self._on_connectivity:
            self._on_connectivity(info)

    def _on_airplane_event(self, body: bytes) -> None:
        f = _parse_fields(body)
        enabled = bool(f.get(1, 0))
        with self._lock:
            self._airplane_mode = enabled
        if self._on_airplane:
            self._on_airplane(enabled)

    def _on_phone_state_event(self, body: bytes) -> None:
        f = _parse_fields(body)
        info = PhoneStateInfo(
            state=_decode_string(f[1]) if f.get(1) else "unknown",
            manual=bool(f.get(2, 0)),
            operator=_decode_string(f[3]) if f.get(3) else "",
        )
        with self._lock:
            self._phone_state = info
        if self._on_phone_state:
            self._on_phone_state(info)

    def _next_id(self) -> int:
        with self._req_id_lock:
            self._req_id += 1
            return self._req_id

    def _send_request(self, msg_type: int, payload: bytes, timeout: float = 5.0) -> Optional[bytes]:
        with self._sock_lock:
            sock = self._sock
        if sock is None:
            self._logger.debug(f"[{self.serial}] STFService not connected, cannot send request")
            return None

        req_id = self._next_id()
        event = threading.Event()
        self._pending[req_id] = event

        try:
            envelope = _build_envelope(msg_type, payload, msg_id=req_id)
            framed = _frame_message(envelope)
            with self._sock_lock:
                if self._sock is not None:
                    self._sock.sendall(framed)
                else:
                    return None

            if not event.wait(timeout):
                self._logger.warning(f"[{self.serial}] STFService request timeout (type={msg_type}, id={req_id})")
                return None

            return self._responses.pop(req_id, None)
        except Exception as exc:
            self._logger.warning(f"[{self.serial}] STFService request error: {exc}")
            return None
        finally:
            self._pending.pop(req_id, None)
            self._responses.pop(req_id, None)

