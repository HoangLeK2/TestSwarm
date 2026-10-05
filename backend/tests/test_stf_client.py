"""Tests for runtime.transports.stf_client — protobuf codec, event parsing, request-response."""
from __future__ import annotations

import socket
import struct
import threading
import time
import unittest
from unittest.mock import MagicMock

from runtime.transports.stf_client import (
    BatteryInfo,
    ConnectivityInfo,
    DisplayInfo,
    MsgType,
    PhoneStateInfo,
    STFAgentClient,
    STFServiceClient,
    _build_envelope,
    _decode_string,
    _decode_varint,
    _encode_length_field,
    _encode_string_field,
    _encode_varint_field,
    _encode_varint_raw,
    _frame_message,
    _parse_fields,
)


# ── Protobuf Codec Tests ──────────────────────────────────────────────────

class TestVarintCodec(unittest.TestCase):
    """Test varint encoding and decoding round-trips."""

    def test_encode_decode_small(self):
        for val in (0, 1, 5, 127):
            encoded = _encode_varint_raw(val)
            decoded, pos = _decode_varint(encoded, 0)
            self.assertEqual(decoded, val)
            self.assertEqual(pos, len(encoded))

    def test_encode_decode_multibyte(self):
        for val in (128, 300, 16384, 100000, 2**21 - 1):
            encoded = _encode_varint_raw(val)
            self.assertGreater(len(encoded), 1)
            decoded, pos = _decode_varint(encoded, 0)
            self.assertEqual(decoded, val)

    def test_encode_varint_field(self):
        # field_number=2, value=14 (EVENT_BATTERY)
        data = _encode_varint_field(2, 14)
        fields = _parse_fields(data)
        self.assertEqual(fields[2], 14)

    def test_encode_length_field(self):
        payload = b"hello"
        data = _encode_length_field(3, payload)
        fields = _parse_fields(data)
        self.assertEqual(fields[3], payload)

    def test_encode_string_field(self):
        data = _encode_string_field(1, "test_serial")
        fields = _parse_fields(data)
        self.assertEqual(_decode_string(fields[1]), "test_serial")


class TestParseFields(unittest.TestCase):
    """Test protobuf field parser with mixed wire types."""

    def test_varint_fields(self):
        data = _encode_varint_field(1, 42) + _encode_varint_field(2, 99)
        fields = _parse_fields(data)
        self.assertEqual(fields[1], 42)
        self.assertEqual(fields[2], 99)

    def test_length_delimited_fields(self):
        data = _encode_length_field(1, b"abc") + _encode_length_field(2, b"xyz")
        fields = _parse_fields(data)
        self.assertEqual(fields[1], b"abc")
        self.assertEqual(fields[2], b"xyz")

    def test_mixed_fields(self):
        data = (
            _encode_varint_field(1, 100)
            + _encode_length_field(2, b"test")
            + _encode_varint_field(3, 0)
        )
        fields = _parse_fields(data)
        self.assertEqual(fields[1], 100)
        self.assertEqual(fields[2], b"test")
        self.assertEqual(fields[3], 0)

    def test_empty_data(self):
        fields = _parse_fields(b"")
        self.assertEqual(fields, {})

    def test_32bit_fixed(self):
        # Wire type 5 (32-bit fixed): used for float fields like xdpi
        # Build: tag = (field_number << 3) | 5
        tag = _encode_varint_raw((4 << 3) | 5)
        value_bytes = struct.pack("<f", 3.14)
        data = tag + value_bytes
        fields = _parse_fields(data)
        self.assertAlmostEqual(fields[4], 3.14, places=2)

    def test_64bit_fixed(self):
        # Wire type 1 (64-bit fixed): used for double fields like temp
        tag = _encode_varint_raw((6 << 3) | 1)
        value_bytes = struct.pack("<d", 25.5)
        data = tag + value_bytes
        fields = _parse_fields(data)
        self.assertAlmostEqual(fields[6], 25.5, places=1)


class TestEnvelopeBuilder(unittest.TestCase):
    """Test _build_envelope and _frame_message."""

    def test_build_envelope_event(self):
        # Envelope for EVENT_BATTERY with empty payload
        env = _build_envelope(MsgType.EVENT_BATTERY, b"", msg_id=0)
        fields = _parse_fields(env)
        self.assertEqual(fields[2], MsgType.EVENT_BATTERY)  # type
        self.assertIn(3, fields)  # message field present

    def test_build_envelope_with_id(self):
        payload = _encode_varint_field(1, 1)  # GetDisplayRequest { id=0 }
        env = _build_envelope(MsgType.GET_DISPLAY, payload, msg_id=42)
        fields = _parse_fields(env)
        self.assertEqual(fields[1], 42)  # id
        self.assertEqual(fields[2], MsgType.GET_DISPLAY)  # type

    def test_frame_message(self):
        data = b"\x10\x0e"  # type=14
        framed = _frame_message(data)
        # First byte(s) = varint length, then data
        length, pos = _decode_varint(framed, 0)
        self.assertEqual(length, len(data))
        self.assertEqual(framed[pos:], data)


# ── MessageType Constants ──────────────────────────────────────────────────

class TestMsgTypeConstants(unittest.TestCase):
    """Verify MessageType enum values match wire.proto."""

    def test_event_types(self):
        self.assertEqual(MsgType.EVENT_BATTERY, 14)
        self.assertEqual(MsgType.EVENT_ROTATION, 17)
        self.assertEqual(MsgType.EVENT_CONNECTIVITY, 15)
        self.assertEqual(MsgType.EVENT_AIRPLANE_MODE, 13)
        self.assertEqual(MsgType.EVENT_PHONE_STATE, 16)
        self.assertEqual(MsgType.EVENT_BROWSER_PACKAGE, 18)

    def test_query_types(self):
        self.assertEqual(MsgType.GET_DISPLAY, 19)
        self.assertEqual(MsgType.GET_CLIPBOARD, 6)
        self.assertEqual(MsgType.GET_WIFI_STATUS, 23)
        self.assertEqual(MsgType.GET_BLUETOOTH_STATUS, 29)
        self.assertEqual(MsgType.GET_RINGER_MODE, 27)
        self.assertEqual(MsgType.GET_VERSION, 8)
        self.assertEqual(MsgType.GET_PROPERTIES, 7)
        self.assertEqual(MsgType.GET_ACCOUNTS, 26)
        self.assertEqual(MsgType.GET_BROWSERS, 5)
        self.assertEqual(MsgType.GET_ROOT_STATUS, 31)
        self.assertEqual(MsgType.GET_SD_STATUS, 25)

    def test_control_types(self):
        self.assertEqual(MsgType.SET_CLIPBOARD, 9)
        self.assertEqual(MsgType.SET_WIFI_ENABLED, 22)
        self.assertEqual(MsgType.SET_BLUETOOTH_ENABLED, 30)
        self.assertEqual(MsgType.SET_KEYGUARD_STATE, 10)
        self.assertEqual(MsgType.SET_WAKE_LOCK, 11)
        self.assertEqual(MsgType.SET_RINGER_MODE, 21)
        self.assertEqual(MsgType.SET_MASTER_MUTE, 28)

    def test_action_types(self):
        self.assertEqual(MsgType.DO_IDENTIFY, 1)
        self.assertEqual(MsgType.DO_REMOVE_ACCOUNT, 20)
        self.assertEqual(MsgType.DO_ADD_ACCOUNT_MENU, 24)
        self.assertEqual(MsgType.DO_CLEAN_BLUETOOTH_BONDED, 32)


# ── Event Parsing Tests ───────────────────────────────────────────────────

class TestEventParsing(unittest.TestCase):
    """Test STFServiceClient event handlers with synthetic protobuf data."""

    def _make_client(self, **callbacks) -> STFServiceClient:
        return STFServiceClient(
            serial="test", host="127.0.0.1", port=0, **callbacks
        )

    def _make_battery_event(self, level: int = 85, status: str = "charging",
                            health: str = "good", source: str = "usb",
                            temp: float = 25.0, voltage: float = 4.2) -> bytes:
        """Build a BatteryEvent protobuf body."""
        body = (
            _encode_string_field(1, status)
            + _encode_string_field(2, health)
            + _encode_string_field(3, source)
            + _encode_varint_field(4, level)
            + _encode_varint_field(5, 100)  # scale
        )
        # temp (field 6) and voltage (field 7) are doubles (wire type 1)
        tag6 = _encode_varint_raw((6 << 3) | 1)
        body += tag6 + struct.pack("<d", temp)
        tag7 = _encode_varint_raw((7 << 3) | 1)
        body += tag7 + struct.pack("<d", voltage)
        return body

    def _make_envelope(self, msg_type: int, body: bytes) -> bytes:
        """Build Envelope { type, message }."""
        return (
            _encode_varint_field(2, msg_type)
            + _encode_length_field(3, body)
        )

    def test_battery_event(self):
        callback = MagicMock()
        client = self._make_client(on_battery=callback)
        body = self._make_battery_event(level=72, status="discharging", source="ac")
        envelope_data = self._make_envelope(MsgType.EVENT_BATTERY, body)
        client._handle_message(envelope_data)

        self.assertEqual(client.get_battery(), 72)
        info = client.get_battery_info()
        self.assertEqual(info.level, 72)
        self.assertEqual(info.status, "discharging")
        self.assertEqual(info.source, "ac")
        self.assertEqual(info.health, "good")
        self.assertAlmostEqual(info.temp, 25.0, places=1)
        callback.assert_called_once_with(72)

    def test_rotation_event_raw_value(self):
        """RotationEvent with raw value 0-3 (converted to degrees)."""
        callback = MagicMock()
        client = self._make_client(on_rotation=callback)
        body = _encode_varint_field(1, 1)  # rotation=1 → 90°
        envelope_data = self._make_envelope(MsgType.EVENT_ROTATION, body)
        client._handle_message(envelope_data)

        self.assertEqual(client.get_rotation(), 90)
        callback.assert_called_once_with(90)

    def test_rotation_event_degrees(self):
        """RotationEvent with degrees value > 3 (used as-is)."""
        callback = MagicMock()
        client = self._make_client(on_rotation=callback)
        body = _encode_varint_field(1, 270)
        envelope_data = self._make_envelope(MsgType.EVENT_ROTATION, body)
        client._handle_message(envelope_data)

        self.assertEqual(client.get_rotation(), 270)

    def test_connectivity_event(self):
        callback = MagicMock()
        client = self._make_client(on_connectivity=callback)
        body = (
            _encode_varint_field(1, 1)        # connected=true
            + _encode_string_field(2, "wifi")  # type
            + _encode_string_field(3, "")      # subtype
            + _encode_varint_field(4, 0)       # failover=false
            + _encode_varint_field(5, 0)       # roaming=false
        )
        envelope_data = self._make_envelope(MsgType.EVENT_CONNECTIVITY, body)
        client._handle_message(envelope_data)

        info = client.get_connectivity()
        self.assertTrue(info.connected)
        self.assertEqual(info.type, "wifi")
        self.assertFalse(info.roaming)
        callback.assert_called_once()

    def test_airplane_mode_event(self):
        callback = MagicMock()
        client = self._make_client(on_airplane=callback)
        body = _encode_varint_field(1, 1)  # enabled=true
        envelope_data = self._make_envelope(MsgType.EVENT_AIRPLANE_MODE, body)
        client._handle_message(envelope_data)

        self.assertTrue(client.get_airplane_mode())
        callback.assert_called_once_with(True)

    def test_phone_state_event(self):
        callback = MagicMock()
        client = self._make_client(on_phone_state=callback)
        body = (
            _encode_string_field(1, "in_service")
            + _encode_varint_field(2, 0)  # manual=false
            + _encode_string_field(3, "Viettel")
        )
        envelope_data = self._make_envelope(MsgType.EVENT_PHONE_STATE, body)
        client._handle_message(envelope_data)

        info = client.get_phone_state()
        self.assertEqual(info.state, "in_service")
        self.assertEqual(info.operator, "Viettel")
        self.assertFalse(info.manual)
        callback.assert_called_once()

    def test_unknown_event_type_ignored(self):
        """Unknown message types should not crash."""
        client = self._make_client()
        body = _encode_varint_field(1, 1)
        envelope_data = self._make_envelope(999, body)
        # Should not raise
        client._handle_message(envelope_data)


# ── Response Routing Tests ────────────────────────────────────────────────

class TestResponseRouting(unittest.TestCase):
    """Test that responses with matching ids unblock waiters."""

    def test_response_unblocks_waiter(self):
        client = STFServiceClient(serial="test", host="127.0.0.1", port=0)
        req_id = 42
        event = threading.Event()
        client._pending[req_id] = event

        # Build a response envelope with matching id
        resp_body = _encode_varint_field(1, 1)  # success=true
        envelope = (
            _encode_varint_field(1, req_id)  # id
            + _encode_varint_field(2, MsgType.GET_WIFI_STATUS)
            + _encode_length_field(3, resp_body)
        )
        client._handle_message(envelope)

        self.assertTrue(event.is_set())
        self.assertIn(req_id, client._responses)
        self.assertEqual(client._responses[req_id], resp_body)

    def test_event_does_not_unblock_wrong_waiter(self):
        client = STFServiceClient(serial="test", host="127.0.0.1", port=0)
        req_id = 42
        event = threading.Event()
        client._pending[req_id] = event

        # Battery event has no id field — should NOT trigger waiter
        body = _encode_varint_field(4, 80)  # level=80
        envelope = (
            _encode_varint_field(2, MsgType.EVENT_BATTERY)
            + _encode_length_field(3, body)
        )
        client._handle_message(envelope)
        self.assertFalse(event.is_set())


# ── Dataclass Tests ───────────────────────────────────────────────────────

class TestDataclasses(unittest.TestCase):
    def test_battery_defaults(self):
        b = BatteryInfo()
        self.assertEqual(b.level, -1)
        self.assertEqual(b.status, "unknown")
        self.assertEqual(b.scale, 100)

    def test_connectivity_defaults(self):
        c = ConnectivityInfo()
        self.assertFalse(c.connected)
        self.assertEqual(c.type, "")

    def test_phone_state_defaults(self):
        p = PhoneStateInfo()
        self.assertEqual(p.state, "unknown")
        self.assertEqual(p.operator, "")

    def test_display_info(self):
        d = DisplayInfo(width=1080, height=2340, fps=60.0, density=2.0)
        self.assertEqual(d.width, 1080)
        self.assertEqual(d.height, 2340)
        self.assertEqual(d.fps, 60.0)
        self.assertFalse(d.secure)


# ── STFAgentClient Encoding Tests ─────────────────────────────────────────

class TestSTFAgentClient(unittest.TestCase):
    """Test STFAgentClient message encoding (without a real socket)."""

    def test_keyevent_encoding(self):
        """Verify keyevent envelope structure."""
        # Build what send_keyevent builds
        key_request = _encode_varint_field(1, 3) + _encode_varint_field(2, 0)  # HOME, metaState=0
        envelope = (
            _encode_varint_field(2, STFAgentClient.DO_KEYEVENT)
            + _encode_length_field(3, key_request)
        )
        fields = _parse_fields(envelope)
        self.assertEqual(fields[2], 1)  # DO_KEYEVENT = 1
        key_fields = _parse_fields(fields[3])
        self.assertEqual(key_fields[1], 3)  # keycode=HOME

    def test_type_encoding(self):
        """Verify type text envelope structure."""
        type_request = _encode_string_field(1, "hello")
        envelope = (
            _encode_varint_field(2, STFAgentClient.DO_TYPE)
            + _encode_length_field(3, type_request)
        )
        fields = _parse_fields(envelope)
        self.assertEqual(fields[2], 4)  # DO_TYPE = 4
        inner = _parse_fields(fields[3])
        self.assertEqual(_decode_string(inner[1]), "hello")

    def test_wake_encoding(self):
        envelope = _encode_varint_field(2, STFAgentClient.DO_WAKE)
        fields = _parse_fields(envelope)
        self.assertEqual(fields[2], 7)  # DO_WAKE = 7


# ── Thread Safety Tests ──────────────────────────────────────────────────

class TestThreadSafety(unittest.TestCase):
    """Test concurrent access to STFServiceClient state."""

    def test_concurrent_event_updates(self):
        """Multiple threads updating state concurrently should not corrupt data."""
        client = STFServiceClient(serial="test", host="127.0.0.1", port=0)
        errors = []

        def update_battery(n):
            try:
                for i in range(100):
                    body = _encode_varint_field(4, i)  # level=i
                    envelope = (
                        _encode_varint_field(2, MsgType.EVENT_BATTERY)
                        + _encode_length_field(3, body)
                    )
                    client._handle_message(envelope)
                    _ = client.get_battery()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=update_battery, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        self.assertEqual(errors, [])
        level = client.get_battery()
        self.assertGreaterEqual(level, 0)
        self.assertLessEqual(level, 99)


# ── Integration: Loopback Socket Test ────────────────────────────────────

class TestLoopbackSocket(unittest.TestCase):
    """Test STFServiceClient with a real TCP loopback server."""

    def test_event_stream_over_tcp(self):
        """Verify STFServiceClient processes events from a real socket."""
        # Start a mock STFService server
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        port = srv.getsockname()[1]
        srv.listen(1)

        battery_levels = []

        def on_battery(level):
            battery_levels.append(level)

        client = STFServiceClient(
            serial="loopback",
            host="127.0.0.1",
            port=port,
            on_battery=on_battery,
        )
        client.start_client()

        # Accept connection and send battery events
        conn, _ = srv.accept()
        try:
            for level in (50, 60, 70):
                body = _encode_varint_field(4, level)
                envelope = (
                    _encode_varint_field(2, MsgType.EVENT_BATTERY)
                    + _encode_length_field(3, body)
                )
                framed = _frame_message(envelope)
                conn.sendall(framed)
                time.sleep(0.1)

            # Wait for events to be processed
            time.sleep(0.5)
            self.assertEqual(battery_levels, [50, 60, 70])
            self.assertEqual(client.get_battery(), 70)
        finally:
            client.stop_client()
            conn.close()
            srv.close()

    def test_request_response_over_tcp(self):
        """Verify request-response works over a real socket (mock server echoes success)."""
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        port = srv.getsockname()[1]
        srv.listen(1)

        client = STFServiceClient(serial="rr-test", host="127.0.0.1", port=port)
        client.start_client()

        conn, _ = srv.accept()
        try:
            # Run request in a thread since it blocks
            result = [None]

            def do_request():
                result[0] = client.get_wifi_status()

            t = threading.Thread(target=do_request)
            t.start()

            # Read the request from server side
            time.sleep(0.3)
            req_data = conn.recv(4096)
            # Parse the request to get the id
            msg_len, pos = _decode_varint(req_data, 0)
            envelope_bytes = req_data[pos:pos + msg_len]
            env_fields = _parse_fields(envelope_bytes)
            req_id = env_fields.get(1, 0)

            # Send response with matching id
            resp_body = _encode_varint_field(1, 1) + _encode_varint_field(2, 1)  # success=true, status=true
            resp_envelope = _build_envelope(MsgType.GET_WIFI_STATUS, resp_body, msg_id=req_id)
            conn.sendall(_frame_message(resp_envelope))

            t.join(timeout=5.0)
            self.assertTrue(result[0])
        finally:
            client.stop_client()
            conn.close()
            srv.close()


if __name__ == "__main__":
    unittest.main()
