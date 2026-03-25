"""
Session + device lock layer for MCP multi-user safety.

- Device usage state: idle | reserved | running | offline
- reserve_device(serial) / release_device(serial)
- start_session(serial) → session_id (device goes to running)
- end_session(session_id) → device goes idle
- get_device_for_session(session_id) → serial or None
"""
from __future__ import annotations

import threading
import uuid
from typing import Dict, Optional

USAGE_IDLE = "idle"
USAGE_RESERVED = "reserved"
USAGE_RUNNING = "running"
USAGE_OFFLINE = "offline"


class SessionLockStore:
    """In-memory store: device usage state + session_id ↔ device_serial."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # serial -> usage_state
        self._usage: Dict[str, str] = {}
        # session_id -> device_serial
        self._session_to_serial: Dict[str, str] = {}
        # device_serial -> session_id (when running)
        self._serial_to_session: Dict[str, str] = {}

    def get_usage(self, serial: str) -> str:
        with self._lock:
            return self._usage.get(serial, USAGE_IDLE)

    def set_usage(self, serial: str, state: str) -> None:
        with self._lock:
            self._usage[serial] = state

    def reserve_device(self, serial: str) -> bool:
        """Set device to reserved if currently idle. Returns True if success."""
        with self._lock:
            current = self._usage.get(serial, USAGE_IDLE)
            if current != USAGE_IDLE:
                return False
            self._usage[serial] = USAGE_RESERVED
            return True

    def release_device(self, serial: str) -> bool:
        """Set device to idle if reserved (or running without session). Returns True if changed."""
        with self._lock:
            current = self._usage.get(serial, USAGE_IDLE)
            if current == USAGE_IDLE:
                return True
            sid = self._serial_to_session.pop(serial, None)
            if sid:
                self._session_to_serial.pop(sid, None)
            self._usage[serial] = USAGE_IDLE
            return True

    def start_session(self, serial: str, session_id: Optional[str] = None) -> str:
        """
        Bind a session to device; device goes to running.
        If session_id is None, generate one. Returns session_id.
        """
        sid = session_id or str(uuid.uuid4())
        with self._lock:
            self._usage[serial] = USAGE_RUNNING
            self._session_to_serial[sid] = serial
            self._serial_to_session[serial] = sid
        return sid

    def end_session(self, session_id: str) -> Optional[str]:
        """
        End session and set device to idle. Returns device_serial or None if unknown.
        """
        with self._lock:
            serial = self._session_to_serial.pop(session_id, None)
            if serial:
                self._serial_to_session.pop(serial, None)
                self._usage[serial] = USAGE_IDLE
            return serial

    def get_device_for_session(self, session_id: str) -> Optional[str]:
        with self._lock:
            return self._session_to_serial.get(session_id)
