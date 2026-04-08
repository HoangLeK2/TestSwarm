from __future__ import annotations

import logging
import socket
import threading
from typing import Optional

from runtime.transports.stf.protobuf_codec import (
    _encode_length_field,
    _encode_string_field,
    _encode_varint_field,
    _frame_message,
)


class STFAgentClient:

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
        key_request = _encode_varint_field(1, keycode) + _encode_varint_field(2, meta_state)
        envelope = _encode_varint_field(2, self.DO_KEYEVENT) + _encode_length_field(3, key_request)
        self._send_message(envelope)

    def send_type(self, text: str) -> None:
        type_request = _encode_string_field(1, text)
        envelope = _encode_varint_field(2, self.DO_TYPE) + _encode_length_field(3, type_request)
        self._send_message(envelope)

    def send_wake(self) -> None:
        """Wake up the screen."""
        envelope = _encode_varint_field(2, self.DO_WAKE)
        self._send_message(envelope)

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
                self._sock.sendall(_frame_message(data))
            except OSError as exc:
                self._logger.error(f"[{self.serial}] STFAgent send error: {exc}")
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None

