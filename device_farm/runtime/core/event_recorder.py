"""
runtime/core/event_recorder.py — EventRecorder: device event recording service.

Records device lifecycle events (disconnect, reconnect, error, state_change)
to an in-memory ring buffer and optionally to PostgreSQL.

Frontend consumers subscribe via add_listener() to receive real-time events
for WS broadcast.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

log = logging.getLogger(__name__)


class EventRecorder:
    """Records device events to in-memory buffer + DB (fire-and-forget)."""

    def __init__(self, db_enabled: bool = True, max_buffer: int = 500) -> None:
        self._buffer: deque[dict] = deque(maxlen=max_buffer)
        self._db_enabled = db_enabled
        self._listeners: list[Callable[[dict], None]] = []
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def record(
        self,
        serial: str,
        event: str,
        *,
        reason: Optional[str] = None,
        old_state: Optional[str] = None,
        new_state: Optional[str] = None,
        device_model: Optional[str] = None,
        device_brand: Optional[str] = None,
        extra: Optional[dict] = None,
    ) -> dict:
        """Record a device event. Thread-safe. Returns the event dict."""
        entry: Dict[str, Any] = {
            "id": str(uuid4()),
            "serial": serial,
            "event": event,
            "reason": reason,
            "old_state": old_state,
            "new_state": new_state,
            "device_model": device_model,
            "device_brand": device_brand,
            "extra_data": extra,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        with self._lock:
            self._buffer.append(entry)

        # Notify listeners (WS broadcast)
        for fn in self._listeners:
            try:
                fn(entry)
            except Exception as exc:
                log.warning("EventRecorder listener error: %s", exc)

        # Fire-and-forget DB write
        if self._db_enabled and self._loop is not None:
            asyncio.run_coroutine_threadsafe(self._write_db(entry), self._loop)

        return entry

    def get_recent(
        self,
        limit: int = 50,
        serial: Optional[str] = None,
        event_type: Optional[str] = None,
    ) -> List[dict]:
        """Return recent events from the in-memory buffer (newest first)."""
        with self._lock:
            items = list(self._buffer)
        # Newest first
        items.reverse()
        if serial:
            items = [e for e in items if e["serial"] == serial]
        if event_type:
            items = [e for e in items if e["event"] == event_type]
        return items[:limit]

    def add_listener(self, fn: Callable[[dict], None]) -> Callable[[], None]:
        """Subscribe to new events. Returns an unsubscribe function."""
        self._listeners.append(fn)

        def _unsub() -> None:
            try:
                self._listeners.remove(fn)
            except ValueError:
                pass

        return _unsub

    async def _write_db(self, entry: dict) -> None:
        """Persist event to PostgreSQL (fire-and-forget)."""
        try:
            from db.database import AsyncSessionLocal
            from db.models.device_event import DeviceEvent

            async with AsyncSessionLocal() as db:
                obj = DeviceEvent(
                    id=entry["id"],
                    serial=entry["serial"],
                    event=entry["event"],
                    reason=entry.get("reason"),
                    old_state=entry.get("old_state"),
                    new_state=entry.get("new_state"),
                    device_model=entry.get("device_model"),
                    device_brand=entry.get("device_brand"),
                    extra_data=entry.get("extra_data"),
                )
                db.add(obj)
                await db.commit()
        except Exception as exc:
            log.warning("EventRecorder DB write failed: %s", exc)

    async def cleanup_old_events(self, keep_days: int = 30) -> int:
        """Delete events older than keep_days. Returns count deleted."""
        if not self._db_enabled:
            return 0
        try:
            from db.database import AsyncSessionLocal
            from db.models.device_event import DeviceEvent
            from sqlalchemy import delete, func
            from datetime import timedelta

            cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    delete(DeviceEvent).where(DeviceEvent.created_at < cutoff)
                )
                await db.commit()
                count = result.rowcount or 0
                if count > 0:
                    log.info("EventRecorder cleanup: deleted %d events older than %d days", count, keep_days)
                return count
        except Exception as exc:
            log.warning("EventRecorder cleanup failed: %s", exc)
            return 0
