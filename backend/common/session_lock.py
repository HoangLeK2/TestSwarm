"""Session + device lock layer for MCP multi-user safety.

Consistency contract
--------------------
The database (table: mcp_sessions) is the authority for session existence
and ownership. This module is an in-memory cache/optimization that lets hot
paths (usage probes, dispatcher) avoid a round-trip on every request.

Write precedence: callers MUST commit to the DB before mirroring into this
store. If a DB write fails, the cache stays unchanged, and the next read
will correctly see the device as idle.

Read precedence:
- `get_usage` / `get_device_for_session`: memory first; safe for hot paths
  where a stale miss only causes a late retry — never a security decision.
- Security-relevant checks (ownership, cross-tenant access) MUST go through
  `api.auth.policy.*` which reads the DB. Never decide authorization from
  this cache.

Lease
-----
Entries expire `SESSION_LEASE_SECONDS` after `start_session` unless
`renew_session` is called. This prevents stale memory entries from
shadowing DB state forever if the DB writer crashes mid-flight.
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Dict, Optional

USAGE_IDLE = "idle"
USAGE_RESERVED = "reserved"
USAGE_RUNNING = "running"
USAGE_OFFLINE = "offline"

SESSION_LEASE_SECONDS = 60 * 60  # 1h — cache eviction, not auth timeout
RESERVATION_LEASE_SECONDS = 5 * 60  # 5m — reserves auto-release if forgotten


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
        # session_id -> user_id (cache; DB is authority)
        self._session_owner: Dict[str, str] = {}
        # session_id -> monotonic deadline
        self._session_deadline: Dict[str, float] = {}
        # serial -> monotonic deadline (reservations)
        self._reserve_deadline: Dict[str, float] = {}

    # ── Sweep helpers (called inside the lock) ────────────────────────────
    def _sweep_expired(self) -> None:
        now = time.monotonic()
        # Expire running sessions whose lease ran out.
        dead = [sid for sid, dl in self._session_deadline.items() if dl <= now]
        for sid in dead:
            serial = self._session_to_serial.pop(sid, None)
            self._session_owner.pop(sid, None)
            self._session_deadline.pop(sid, None)
            if serial and self._serial_to_session.get(serial) == sid:
                self._serial_to_session.pop(serial, None)
                self._usage[serial] = USAGE_IDLE
        # Expire reservations.
        stale_reserves = [s for s, dl in self._reserve_deadline.items() if dl <= now]
        for s in stale_reserves:
            if self._usage.get(s) == USAGE_RESERVED:
                self._usage[s] = USAGE_IDLE
            self._reserve_deadline.pop(s, None)

    # ── Usage probes ──────────────────────────────────────────────────────
    def get_usage(self, serial: str) -> str:
        with self._lock:
            self._sweep_expired()
            return self._usage.get(serial, USAGE_IDLE)

    def set_usage(self, serial: str, state: str) -> None:
        with self._lock:
            self._usage[serial] = state

    # ── Reservations ─────────────────────────────────────────────────────
    def reserve_device(self, serial: str) -> bool:
        """Reserve if idle. Automatically expires after RESERVATION_LEASE_SECONDS."""
        with self._lock:
            self._sweep_expired()
            current = self._usage.get(serial, USAGE_IDLE)
            if current != USAGE_IDLE:
                return False
            self._usage[serial] = USAGE_RESERVED
            self._reserve_deadline[serial] = time.monotonic() + RESERVATION_LEASE_SECONDS
            return True

    def release_device(self, serial: str) -> bool:
        with self._lock:
            current = self._usage.get(serial, USAGE_IDLE)
            if current == USAGE_IDLE:
                self._reserve_deadline.pop(serial, None)
                return True
            sid = self._serial_to_session.pop(serial, None)
            if sid:
                self._session_to_serial.pop(sid, None)
                self._session_owner.pop(sid, None)
                self._session_deadline.pop(sid, None)
            self._usage[serial] = USAGE_IDLE
            self._reserve_deadline.pop(serial, None)
            return True

    # ── Sessions ─────────────────────────────────────────────────────────
    def start_session(
        self,
        serial: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> str:
        """Mirror a DB-committed session into memory.

        Callers MUST have already committed `create_mcp_session` in the DB
        before calling this. Passing `user_id` lets fast-path reads return
        the owner without hitting the DB; security-sensitive consumers
        still validate against the DB row.
        """
        sid = session_id or str(uuid.uuid4())
        deadline = time.monotonic() + SESSION_LEASE_SECONDS
        with self._lock:
            self._usage[serial] = USAGE_RUNNING
            self._session_to_serial[sid] = serial
            self._serial_to_session[serial] = sid
            if user_id:
                self._session_owner[sid] = user_id
            self._session_deadline[sid] = deadline
            self._reserve_deadline.pop(serial, None)
        return sid

    def renew_session(self, session_id: str) -> bool:
        with self._lock:
            if session_id not in self._session_to_serial:
                return False
            self._session_deadline[session_id] = (
                time.monotonic() + SESSION_LEASE_SECONDS
            )
            return True

    def end_session(self, session_id: str) -> Optional[str]:
        with self._lock:
            serial = self._session_to_serial.pop(session_id, None)
            self._session_owner.pop(session_id, None)
            self._session_deadline.pop(session_id, None)
            if serial:
                self._serial_to_session.pop(serial, None)
                self._usage[serial] = USAGE_IDLE
            return serial

    def get_device_for_session(self, session_id: str) -> Optional[str]:
        with self._lock:
            self._sweep_expired()
            return self._session_to_serial.get(session_id)

    def get_session_owner(self, session_id: str) -> Optional[str]:
        """Cached owner — DB remains the authority; treat None as 'unknown'."""
        with self._lock:
            return self._session_owner.get(session_id)
