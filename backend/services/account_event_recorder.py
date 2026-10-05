"""
Append-only account timeline recorder.

Events are buffered in memory and flushed in batches after the caller commits
the main transaction — never inside ``FOR UPDATE`` rotation locks.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from db.models.enums import AccountEventType
from db.models.utils import _uuid

log = logging.getLogger(__name__)

_SENSITIVE_KEYS = frozenset({
    "password",
    "password_encrypted",
    "password_plain",
    "cookies",
    "token",
    "access_token",
    "refresh_token",
    "2fa_secret",
    "two_factor_secret",
})


def _redact_details(details: Optional[dict]) -> dict:
    if not details:
        return {}
    out: dict[str, Any] = {}
    for key, value in details.items():
        lower = key.lower()
        if lower in _SENSITIVE_KEYS or "password" in lower or "token" in lower:
            continue
        if isinstance(value, dict):
            nested = _redact_details(value)
            if nested:
                out[key] = nested
        else:
            out[key] = value
    return out


@dataclass
class _PendingEvent:
    account_id: str
    event_type: str
    user_id: Optional[str] = None
    device_serial: Optional[str] = None
    platform: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    details: dict = field(default_factory=dict)


class AccountEventRecorder:
    def __init__(
        self,
        *,
        enabled: bool = True,
        max_batch_size: int = 100,
        max_pending: int = 1000,
    ) -> None:
        self.enabled = enabled
        self.max_batch_size = max_batch_size
        self.max_pending = max_pending
        self._pending: list[_PendingEvent] = []
        self._lock = asyncio.Lock()
        self.dropped_total = 0

    def record(
        self,
        *,
        account_id: str,
        event_type: str | AccountEventType,
        user_id: Optional[str] = None,
        device_serial: Optional[str] = None,
        platform: Optional[str] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> None:
        if not self.enabled or not account_id:
            return
        et = event_type.value if isinstance(event_type, AccountEventType) else str(event_type)
        if len(self._pending) >= self.max_pending:
            self.dropped_total += 1
            if self.dropped_total == 1 or self.dropped_total % 100 == 0:
                log.warning(
                    "account_events queue full (%d), dropping event %s for %s",
                    self.max_pending,
                    et,
                    account_id,
                )
            return
        self._pending.append(
            _PendingEvent(
                account_id=account_id,
                event_type=et,
                user_id=user_id,
                device_serial=device_serial,
                platform=platform,
                entity_type=entity_type,
                entity_id=entity_id,
                details=_redact_details(details),
            )
        )

    async def flush(self, db) -> int:
        """Persist buffered events. Call after ``db.commit()`` on the request session."""
        async with self._lock:
            batch = self._pending[: self.max_batch_size]
            self._pending = self._pending[self.max_batch_size :]
        if not batch:
            return 0
        from db.crud.account_event import insert_events_batch

        rows = [
            {
                "id": _uuid(),
                "account_id": e.account_id,
                "user_id": e.user_id,
                "event_type": e.event_type,
                "device_serial": e.device_serial,
                "platform": e.platform,
                "entity_type": e.entity_type,
                "entity_id": e.entity_id,
                "details": e.details,
            }
            for e in batch
        ]
        try:
            n = await insert_events_batch(db, rows)
            await db.commit()
            return n
        except Exception as exc:
            log.warning("account_events flush failed (%d rows): %s", len(rows), exc)
            try:
                await db.rollback()
            except Exception:
                pass
            return 0

    async def flush_all(self) -> int:
        """Drain entire queue (used after dispatch)."""
        total = 0
        from db.database import AsyncSessionLocal

        while self._pending:
            async with AsyncSessionLocal() as db:
                n = await self.flush(db)
                if n == 0:
                    break
                total += n
        return total


_recorder: Optional[AccountEventRecorder] = None


def get_account_event_recorder() -> AccountEventRecorder:
    global _recorder
    if _recorder is None:
        enabled = os.environ.get("ACCOUNT_HISTORY_ENABLED", "true").strip().lower() not in (
            "0",
            "false",
            "no",
            "off",
        )
        max_batch = int(os.environ.get("ACCOUNT_HISTORY_MAX_BATCH", "100"))
        max_pending = int(os.environ.get("ACCOUNT_HISTORY_MAX_PENDING", "1000"))
        _recorder = AccountEventRecorder(
            enabled=enabled,
            max_batch_size=max_batch,
            max_pending=max_pending,
        )
    return _recorder


def reset_account_event_recorder(recorder: Optional[AccountEventRecorder] = None) -> None:
    """Test helper."""
    global _recorder
    _recorder = recorder
