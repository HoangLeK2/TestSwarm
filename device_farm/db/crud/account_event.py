from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Any, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.account_event import AccountEvent
from db.models.utils import _uuid


def encode_event_cursor(created_at: datetime, event_id: str) -> str:
    payload = {"t": created_at.isoformat(), "id": event_id}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def decode_event_cursor(cursor: str) -> Tuple[datetime, str]:
    raw = base64.urlsafe_b64decode(cursor.encode())
    payload = json.loads(raw.decode())
    return datetime.fromisoformat(payload["t"]), payload["id"]


async def insert_events_batch(db: AsyncSession, rows: List[dict]) -> int:
    if not rows:
        return 0
    for row in rows:
        row.setdefault("id", _uuid())
    stmt = pg_insert(AccountEvent).values(rows)
    result = await db.execute(stmt)
    return result.rowcount or len(rows)


async def list_account_events(
    db: AsyncSession,
    account_id: str,
    *,
    limit: int = 50,
    cursor: Optional[str] = None,
    event_type: Optional[str] = None,
) -> Tuple[List[AccountEvent], Optional[str], bool]:
    """Keyset pagination: newest first."""
    limit = max(1, min(limit, 200))
    q = (
        select(AccountEvent)
        .where(AccountEvent.account_id == account_id)
        .order_by(AccountEvent.created_at.desc(), AccountEvent.id.desc())
    )
    if event_type:
        q = q.where(AccountEvent.event_type == event_type)
    if cursor:
        cur_at, cur_id = decode_event_cursor(cursor)
        q = q.where(
            (AccountEvent.created_at < cur_at)
            | (
                (AccountEvent.created_at == cur_at)
                & (AccountEvent.id < cur_id)
            )
        )
    q = q.limit(limit + 1)
    rows = list((await db.execute(q)).scalars().all())
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = encode_event_cursor(last.created_at, last.id)
    return items, next_cursor, has_more
