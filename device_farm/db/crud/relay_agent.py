from __future__ import annotations

import hashlib
import secrets
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.crud.user import get_user_org_id
from db.models.relay_agent import RelayAgent, RelayAgentToken
from db.models.utils import _now, _uuid
from tenancy.context import tenant_context


RELAY_AGENT_TOKEN_PREFIX = "dfra_"
RELAY_AGENT_TOKEN_BYTES = 32
RELAY_AGENT_TOKEN_PREFIX_CHARS = 13


def generate_relay_agent_token() -> str:
    return f"{RELAY_AGENT_TOKEN_PREFIX}{secrets.token_urlsafe(RELAY_AGENT_TOKEN_BYTES)}"


def hash_relay_agent_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def lookup_relay_agent_org_id(db: AsyncSession, relay_id: str) -> str | None:
    """Resolve relay org without tenant context (gRPC/background paths)."""
    table = RelayAgent.__table__
    result = await db.execute(
        select(table.c.org_id).where(table.c.relay_id == relay_id).limit(1)
    )
    return result.scalar_one_or_none()


async def lookup_relay_token_enrollment(
    db: AsyncSession,
    raw_token: str,
) -> tuple[str, str, str] | None:
    """Return (org_id, user_id, token_id) for a valid enrollment token (unscoped)."""
    token = (raw_token or "").strip()
    if not token:
        return None
    table = RelayAgentToken.__table__
    result = await db.execute(
        select(table.c.org_id, table.c.user_id, table.c.id).where(
            table.c.token_hash == hash_relay_agent_token(token),
            table.c.status == "active",
            table.c.revoked_at.is_(None),
        ).limit(1)
    )
    row = result.first()
    if row is None:
        return None
    org_id, user_id, token_id = row[0], row[1], row[2]
    if not org_id:
        org_id = await get_user_org_id(db, user_id)
    if not org_id:
        return None
    return org_id, user_id, token_id


async def create_relay_agent_token(
    db: AsyncSession,
    *,
    user_id: str,
    name: str,
    org_id: str | None = None,
) -> tuple[str, RelayAgentToken]:
    resolved_org_id = org_id or await get_user_org_id(db, user_id)
    if not resolved_org_id:
        raise ValueError("user has no organization for relay enrollment token")
    raw_token = generate_relay_agent_token()
    row = RelayAgentToken(
        id=_uuid(),
        org_id=resolved_org_id,
        user_id=user_id,
        name=(name or "").strip(),
        token_hash=hash_relay_agent_token(raw_token),
        prefix=raw_token[:RELAY_AGENT_TOKEN_PREFIX_CHARS],
        status="active",
        created_at=_now(),
    )
    db.add(row)
    await db.flush()
    return raw_token, row


async def list_relay_agent_tokens(db: AsyncSession, *, user_id: str) -> list[RelayAgentToken]:
    result = await db.execute(
        select(RelayAgentToken)
        .where(RelayAgentToken.user_id == user_id)
        .order_by(RelayAgentToken.created_at.desc())
    )
    return list(result.scalars().all())


async def resolve_relay_agent_token(db: AsyncSession, raw_token: str) -> Optional[RelayAgentToken]:
    identity = await lookup_relay_token_enrollment(db, raw_token)
    if identity is None:
        return None
    org_id, _user_id, token_id = identity
    with tenant_context(org_id):
        result = await db.execute(
            select(RelayAgentToken).where(RelayAgentToken.id == token_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        row.last_used_at = _now()
        await db.flush()
        return row


async def revoke_relay_agent_token(db: AsyncSession, *, token_id: str, user_id: str) -> bool:
    result = await db.execute(
        update(RelayAgentToken)
        .where(
            RelayAgentToken.id == token_id,
            RelayAgentToken.user_id == user_id,
            RelayAgentToken.status == "active",
        )
        .values(status="revoked", revoked_at=_now())
        .returning(RelayAgentToken.id)
    )
    return result.scalar_one_or_none() is not None


async def upsert_relay_agent(
    db: AsyncSession,
    *,
    org_id: str,
    relay_id: str,
    hostname: str,
    ip: str,
    version: str,
    serials: list[str],
    user_id: Optional[str] = None,
    enrollment_token_id: Optional[str] = None,
) -> RelayAgent:
    now = _now()
    stmt = (
        insert(RelayAgent)
        .values(
            id=_uuid(),
            org_id=org_id,
            relay_id=relay_id,
            hostname=hostname,
            ip=ip,
            version=version,
            serials=list(serials),
            status="online",
            user_id=user_id,
            enrollment_token_id=enrollment_token_id,
            connected_at=now,
            last_heartbeat_at=now,
            disconnected_at=None,
            created_at=now,
        )
        .on_conflict_do_update(
            index_elements=["relay_id"],
            set_={
                "org_id":            org_id,
                "hostname":          hostname,
                "ip":                ip,
                "version":           version,
                "serials":           list(serials),
                "status":            "online",
                "user_id":           user_id,
                "enrollment_token_id": enrollment_token_id,
                "connected_at":      now,
                "last_heartbeat_at": now,
                "disconnected_at":   None,
            },
        )
        .returning(RelayAgent)
    )
    result = await db.execute(stmt)
    row = result.scalar_one()
    # One physical host should not leave many stale "online" rows when relay_id changes.
    if hostname and ip:
        await db.execute(
            update(RelayAgent)
            .where(
                RelayAgent.relay_id != relay_id,
                RelayAgent.hostname == hostname,
                RelayAgent.ip == ip,
                RelayAgent.status == "online",
            )
            .values(status="offline", disconnected_at=now)
        )
    return row


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
        .values(status="offline", disconnected_at=_now(), serials=[])
    )


async def list_relay_agents(db: AsyncSession, *, user_id: Optional[str] = None) -> list[RelayAgent]:
    stmt = select(RelayAgent).order_by(RelayAgent.connected_at.desc())
    if user_id is not None:
        stmt = stmt.where(RelayAgent.user_id == user_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_relay_agent(db: AsyncSession, relay_id: str, *, user_id: Optional[str] = None) -> Optional[RelayAgent]:
    stmt = select(RelayAgent).where(RelayAgent.relay_id == relay_id)
    if user_id is not None:
        stmt = stmt.where(RelayAgent.user_id == user_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
