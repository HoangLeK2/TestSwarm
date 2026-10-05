"""CRUD for McpSession."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.mcp_session import McpSession
from db.models.utils import _now


async def create_mcp_session(
    db: AsyncSession,
    session_id: str,
    device_serial: str,
    user_id: Optional[str] = None,
) -> McpSession:
    row = McpSession(
        id=session_id,
        device_serial=device_serial,
        user_id=user_id,
        status="active",
    )
    db.add(row)
    await db.flush()
    return row


async def end_mcp_session(db: AsyncSession, session_id: str) -> bool:
    r = await db.execute(
        update(McpSession)
        .where(McpSession.id == session_id, McpSession.status == "active")
        .values(status="ended", ended_at=_now())
    )
    return r.rowcount > 0


async def get_mcp_session(db: AsyncSession, session_id: str) -> Optional[McpSession]:
    r = await db.execute(select(McpSession).where(McpSession.id == session_id))
    return r.scalar_one_or_none()
