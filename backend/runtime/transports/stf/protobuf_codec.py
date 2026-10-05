from __future__ import annotations

import socket
import struct


# ── Protobuf Varint helpers ────────────────────────────────────────────────

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


def _decode_varint(data: bytes, pos: int) -> tuple[int, int]:
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


def _parse_fields(data: bytes) -> dict:
    """
    Parse protobuf message into {field_number: raw_value}.
    Handles wire types 0 (varint), 1 (64-bit), 2 (length-delimited), 5 (32-bit).
    For repeated fields, last value wins (sufficient for our use).
    """
    fields: dict = {}
    pos = 0
    while pos < len(data):
        tag, pos = _decode_varint(data, pos)
        field_number = tag >> 3
        wire_type = tag & 0x07
        if wire_type == 0:  # varint
            value, pos = _decode_varint(data, pos)
            fields[field_number] = value
        elif wire_type == 2:  # length-delimited
            length, pos = _decode_varint(data, pos)
            fields[field_number] = data[pos:pos + length]
            pos += length
        elif wire_type == 5:  # 32-bit fixed
            fields[field_number] = struct.unpack_from("<f", data, pos)[0]
            pos += 4
        elif wire_type == 1:  # 64-bit fixed
            fields[field_number] = struct.unpack_from("<d", data, pos)[0]
            pos += 8
        else:
            break
    return fields


def _decode_string(data: bytes) -> str:
    """Decode bytes as UTF-8 string, handling both raw bytes and already-parsed values."""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return str(data)


# ── Protobuf encoding helpers ──────────────────────────────────────────────

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
    tag = (field_number << 3) | 0
    return _encode_varint_raw(tag) + _encode_varint_raw(value)


def _encode_length_field(field_number: int, data: bytes) -> bytes:
    """Encode a length-delimited field: tag + length + bytes."""
    tag = (field_number << 3) | 2
    return _encode_varint_raw(tag) + _encode_varint_raw(len(data)) + data


def _encode_string_field(field_number: int, text: str) -> bytes:
    """Encode a string field."""
    return _encode_length_field(field_number, text.encode("utf-8"))


def _build_envelope(msg_type: int, payload: bytes = b"", msg_id: int = 0) -> bytes:
    """Build an Envelope protobuf: { id(1), type(2), message(3) }."""
    envelope = b""
    if msg_id:
        envelope += _encode_varint_field(1, msg_id)
    envelope += _encode_varint_field(2, msg_type)
    if payload:
        envelope += _encode_length_field(3, payload)
    else:
        # Empty message field still required by proto
        envelope += _encode_length_field(3, b"")
    return envelope


def _frame_message(data: bytes) -> bytes:
    """Varint-length prefix a message for the wire."""
    return _encode_varint_raw(len(data)) + data

