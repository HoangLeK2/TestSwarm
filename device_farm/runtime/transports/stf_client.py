"""
stf_client.py — Lightweight STFService / STFAgent client.

STFService communicates via delimited Protocol Buffers (varint-length-prefixed).
Rather than depending on a compiled .proto file, we do minimal manual parsing:
- We only need battery level, rotation events, and agent key injection.
- Unknown message types are silently skipped.

Wire format (both STFService and STFAgent sockets):
  varint  message_length
  bytes   serialized protobuf message

Protobuf encoding basics used here:
  Field tag = (field_number << 3) | wire_type
  Wire types: 0=varint, 2=length-delimited
  Varint: 7 bits per byte, MSB=1 means more bytes follow

STFService field mapping (from wire.proto):
  Envelope message:
    1: id (uint32)
    2: type (enum MessageType)
    3: Battery (nested)
    ...
  Battery message:
    1: status (enum)
    2: health (enum)
    3: source (enum)
    4: level (int32)
    5: scale (int32)
    6: temp (double)
    7: voltage (double)
    8: online (bool)

  MessageType enum values (relevant):
    BATTERY_EVENT = 5
    ROTATION_EVENT = 20
    GET_DISPLAY = 33
"""
from __future__ import annotations

import logging
import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional


log = logging.getLogger(__name__)


# ── Protobuf Varint helpers ──────────────────────────────────────────────────

def _read_varint(sock: socket.socket) -> int:
    """Read a protobuf-style varint from a socket."""
    result = 0
    shift = 0
    while True:
        b = sock.recv(1)
        if not b:
            raise ConnectionError("STF socket closed while reading varint")
        byte = b[0]
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            break
        shift += 7
    return result


def _decode_varint_from_bytes(data: bytes, pos: int) -> tuple[int, int]:
    """Decode varint from bytes at pos. Returns (value, new_pos)."""
    result = 0
    shift = 0
    while pos < len(data):
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            break
        shift += 7
    return result, pos


def _parse_protobuf_fields(data: bytes) -> dict:
    """
    Minimally parse a protobuf message into {field_number: raw_value}.
    Only handles wire types 0 (varint) and 2 (length-delimited).
    Repeated fields: last value wins (sufficient for our use case).
    """
    fields: dict = {}
    pos = 0
    while pos < len(data):
        tag, pos = _decode_varint_from_bytes(data, pos)
        field_number = tag >> 3
        wire_type = tag & 0x07
        if wire_type == 0:  # varint
            value, pos = _decode_varint_from_bytes(data, pos)
            fields[field_number] = value
        elif wire_type == 2:  # length-delimited
            length, pos = _decode_varint_from_bytes(data, pos)
            value = data[pos:pos + length]
            pos += length
            fields[field_number] = value
        elif wire_type == 5:  # 32-bit fixed
            fields[field_number] = struct.unpack_from("<I", data, pos)[0]
            pos += 4
        elif wire_type == 1:  # 64-bit fixed
            fields[field_number] = struct.unpack_from("<Q", data, pos)[0]
            pos += 8
        else:
            # Unknown wire type — stop parsing this message safely
            break
    return fields


# ── STFServiceClient ─────────────────────────────────────────────────────────

class STFServiceClient(threading.Thread):
    """
    Background thread that:
    - Connects to the STFService socket (forwarded via ADB)
    - Streams incoming events (battery, rotation)
    - Calls registered callbacks on events

    STFService pushes events automatically — no polling needed.
    """

    # MessageType enum values we care about
    MSG_BATTERY_EVENT = 5
    MSG_ROTATION_EVENT = 20

    def __init__(
        self,
        serial: str,
        host: str,
        port: int,
        on_battery: Optional[Callable[[int], None]] = None,
        on_rotation: Optional[Callable[[int], None]] = None,
    ) -> None:
        super().__init__(daemon=True, name=f"stfsvc-{serial}")
        self.serial = serial
        self.host = host
        self.port = port
        self._on_battery = on_battery
        self._on_rotation = on_rotation

        self._logger = logging.getLogger(f"stfservice.{serial}")
        self._running = False
        self._lock = threading.Lock()
        self._battery_level: int = -1
        self._rotation: int = 0

    # ── Public API ───────────────────────────────────────────────────────────

    def start_client(self) -> None:
        self._running = True
        if not self.is_alive():
            self.start()

    def stop_client(self) -> None:
        self._running = False

    def get_battery(self) -> int:
        """Return last known battery level (0-100), or -1 if unknown."""
        with self._lock:
            return self._battery_level

    def get_rotation(self) -> int:
        """Return last known rotation in degrees (0/90/180/270)."""
        with self._lock:
            return self._rotation

    # ── Internal ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        while self._running:
            try:
                self._connect_and_stream()
            except Exception as exc:
                if self._running:
                    self._logger.warning(
                        f"[{self.serial}] STFService stream error: {exc}; retrying in 3s"
                    )
                    time.sleep(3)

    def _connect_and_stream(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10.0)
        try:
            sock.connect((self.host, self.port))
            sock.settimeout(None)
            self._logger.info(f"[{self.serial}] STFService connected on {self.host}:{self.port}")

            while self._running:
                msg_len = _read_varint(sock)
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
            sock.close()

    def _handle_message(self, data: bytes) -> None:
        """Parse Envelope proto and dispatch based on type field."""
        try:
            envelope = _parse_protobuf_fields(data)
            # field 2 = type (MessageType enum)
            msg_type = envelope.get(2, 0)

            if msg_type == self.MSG_BATTERY_EVENT:
                # field 3 = Battery nested message
                battery_bytes = envelope.get(3, b"")
                if isinstance(battery_bytes, bytes):
                    bat = _parse_protobuf_fields(battery_bytes)
                    # field 4 = level (int32)
                    level = bat.get(4, -1)
                    with self._lock:
                        self._battery_level = level
                    if self._on_battery:
                        self._on_battery(level)

            elif msg_type == self.MSG_ROTATION_EVENT:
                # field 3 = Rotation nested message; field 1 = degrees
                rot_bytes = envelope.get(3, b"")
                if isinstance(rot_bytes, bytes):
                    rot = _parse_protobuf_fields(rot_bytes)
                    degrees = rot.get(1, 0)
                    with self._lock:
                        self._rotation = degrees
                    if self._on_rotation:
                        self._on_rotation(degrees)
        except Exception as exc:
            self._logger.debug(f"[{self.serial}] STFService parse error: {exc}")


# ── STFAgentClient ────────────────────────────────────────────────────────────

class STFAgentClient:
    """
    Synchronous client for STFAgent (key events, text injection, screen wake).
    STFAgent uses the same varint-prefixed protobuf protocol as STFService.

    For the minitouch relay (Android 10+): STFAgent must be running but
    the Python layer does NOT need to send it any commands — minitouch
    auto-detects the relay socket. This client is only used for key events.
    """

    # Request type enum values from wire.proto
    DO_KEYEVENT = 1
    DO_TYPE = 4
    DO_WAKE = 7

    def __init__(self, serial: str, host: str, port: int) -> None:
        self.serial = serial
        self.host = host
        self.port = port
        self._logger = logging.getLogger(f"stfagent.{serial}")
        self._lock = threading.Lock()
        self._sock: Optional[socket.socket] = None

    def connect(self) -> None:
        with self._lock:
            self._do_connect()

    def disconnect(self) -> None:
        with self._lock:
            if self._sock:
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None

    def send_keyevent(self, keycode: int, meta_state: int = 0) -> None:
        """Inject a key event (e.g., keycode 3 = HOME, 4 = BACK)."""
        # Protobuf manual encode:
        # Envelope { type=DO_KEYEVENT(1), KeyEventRequest { keyCode, metaState } }
        # KeyEventRequest: field1=keyCode, field2=metaState
        key_request = _encode_varint_field(1, keycode) + _encode_varint_field(2, meta_state)
        envelope = (
            _encode_varint_field(2, self.DO_KEYEVENT)  # type
            + _encode_length_field(3, key_request)       # payload
        )
        self._send_message(envelope)

    def send_wake(self) -> None:
        """Wake up the screen."""
        envelope = _encode_varint_field(2, self.DO_WAKE)
        self._send_message(envelope)

    # ── Internal ─────────────────────────────────────────────────────────────

    def _do_connect(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10.0)
        sock.connect((self.host, self.port))
        sock.settimeout(None)
        self._sock = sock
        self._logger.info(f"[{self.serial}] STFAgent connected on {self.host}:{self.port}")

    def _send_message(self, data: bytes) -> None:
        with self._lock:
            if self._sock is None:
                return
            try:
                length_prefix = _encode_varint_raw(len(data))
                self._sock.sendall(length_prefix + data)
            except OSError as exc:
                self._logger.error(f"[{self.serial}] STFAgent send error: {exc}")
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None


# ── Protobuf encoding helpers ─────────────────────────────────────────────────

def _encode_varint_raw(value: int) -> bytes:
    """Encode integer as protobuf varint."""
    bits = []
    while True:
        b = value & 0x7F
        value >>= 7
        if value:
            bits.append(b | 0x80)
        else:
            bits.append(b)
            break
    return bytes(bits)


def _encode_varint_field(field_number: int, value: int) -> bytes:
    """Encode a varint field: tag + varint value."""
    tag = (field_number << 3) | 0  # wire type 0 = varint
    return _encode_varint_raw(tag) + _encode_varint_raw(value)


def _encode_length_field(field_number: int, data: bytes) -> bytes:
    """Encode a length-delimited field: tag + length + bytes."""
    tag = (field_number << 3) | 2  # wire type 2 = length-delimited
    return _encode_varint_raw(tag) + _encode_varint_raw(len(data)) + data
