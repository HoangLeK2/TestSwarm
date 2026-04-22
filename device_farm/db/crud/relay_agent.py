from __future__ import annotations

from typing import Optional

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.relay_agent import RelayAgent
from db.models.utils import _now, _uuid


async def upsert_relay_agent(
    db: AsyncSession,
    *,
    relay_id: str,
    hostname: str,
    ip: str,
    version: str,
    serials: list[str],
) -> RelayAgent:
    now = _now()
    stmt = (
        insert(RelayAgent)
        .values(
            id=_uuid(),
            relay_id=relay_id,
            hostname=hostname,
            ip=ip,
            version=version,
            serials=list(serials),
            status="online",
            connected_at=now,
            last_heartbeat_at=now,
            disconnected_at=None,
            created_at=now,
        )
        .on_conflict_do_update(
            index_elements=["relay_id"],
            set_={
                "hostname":          hostname,
                "ip":                ip,
                "version":           version,
                "serials":           list(serials),
                "status":            "online",
                "connected_at":      now,
                "last_heartbeat_at": now,
                "disconnected_at":   None,
            },
        )
        .returning(RelayAgent)
    )
    result = await db.execute(stmt)
    return result.scalar_one()


async def update_relay_heartbeat(
    db: AsyncSession,
    *,
    relay_id: str,
    serials: list[str],
) -> None:
    await db.execute(
        update(RelayAgent)
        .where(RelayAgent.relay_id == relay_id)
        .values(serials=list(serials), last_heartbeat_at=_now())
    )


async def mark_relay_offline(db: AsyncSession, relay_id: str) -> None:
    await db.execute(
        update(RelayAgent)
        .where(RelayAgent.relay_id == relay_id)
        .values(status="offline", disconnected_at=_now())
    )


async def list_relay_agents(db: AsyncSession) -> list[RelayAgent]:
    result = await db.execute(
        select(RelayAgent).order_by(RelayAgent.connected_at.desc())
    )
    return list(result.scalars().all())


async def get_relay_agent(db: AsyncSession, relay_id: str) -> Optional[RelayAgent]:
    result = await db.execute(
        select(RelayAgent).where(RelayAgent.relay_id == relay_id)
    )
    return result.scalar_one_or_none()
