from __future__ import annotations

import hashlib
import logging
import secrets
from typing import Optional

from sqlalchemy import case, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.crud.user import get_user_org_id
from db.models.relay_agent import RelayAgent, RelayAgentToken
from db.models.utils import _now, _uuid
from tenancy.context import tenant_context

log = logging.getLogger(__name__)

RELAY_ID_PREFIX = "agt_"
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


def mint_relay_id() -> str:
    """Server-issued, opaque agent identity. Never derived from client input."""
    return f"{RELAY_ID_PREFIX}{secrets.token_hex(6)}"


async def resolve_relay_identity(
    db: AsyncSession,
    *,
    org_id: str,
    token_id: str,
    proposed_relay_id: str,
) -> str:
    """Pick the relay_id a registering agent gets. Empty string means refuse.

    The agent's proposal is honoured only when it already names a row in this
    org — identity belongs to the server. One activation code binds one machine,
    so the token is also the anchor that hands the original row back to an agent
    that lost its state directory (fresh container, wiped volume, reinstall).
    """
    table = RelayAgent.__table__
    proposed = (proposed_relay_id or "").strip()
    if proposed:
        known = (
            await db.execute(
                select(table.c.relay_id)
                .where(table.c.org_id == org_id, table.c.relay_id == proposed)
                .limit(1)
            )
        ).scalar_one_or_none()
        if known:
            return str(known)
        log.warning(
            "relay register: ignoring unknown relay_id=%s (server issues identity)",
            proposed,
        )

    bound = (
        await db.execute(
            select(table.c.relay_id, table.c.status)
            .where(
                table.c.org_id == org_id,
                table.c.enrollment_token_id == token_id,
                table.c.status != "archived",
            )
            .order_by(
                func.coalesce(table.c.last_heartbeat_at, table.c.connected_at).desc()
            )
        )
    ).all()
    if not bound:
        return mint_relay_id()
    if any(row.status == "online" for row in bound):
        log.warning(
            "relay register refused: activation token %s is already bound to an "
            "online agent — one code enrols one machine",
            token_id,
        )
        return ""
    return str(bound[0].relay_id)


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
    name: str = "",
) -> RelayAgent:
    now = _now()
    stmt = (
        insert(RelayAgent)
        .values(
            id=_uuid(),
            org_id=org_id,
            relay_id=relay_id,
            # `name` is written at row birth only — never in the conflict update,
            # so an admin rename survives every reconnect.
            name=name,
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
                # An admin turning an agent off must outlast the agent's own
                # reconnect loop; a plain "online" here resurrected it seconds
                # later and the tenant kept driving the phones.
                "status":            case(
                    (RelayAgent.__table__.c.status == "disabled", "disabled"),
                    else_="online",
                ),
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
        .values(
            # Disconnecting must not clear an admin's "disabled": that is how a
            # kicked agent laundered itself back to a re-registerable state.
            status=case(
                (RelayAgent.status == "disabled", "disabled"),
                else_="offline",
            ),
            disconnected_at=_now(),
            # `serials` is the last known phone list, not a liveness signal —
            # liveness comes from the transports. Clearing it here threw away
            # the only serial → agent map, so a disable could no longer tell the
            # media plane which phones must go dark.
        )
    )


async def disabled_relay_entries(db: AsyncSession) -> list[tuple[str, list[str]]]:
    """(relay_id, serials) for every disabled agent — rebuilds the registry."""
    table = RelayAgent.__table__
    rows = (
        await db.execute(
            select(table.c.relay_id, table.c.serials).where(
                table.c.status == "disabled"
            )
        )
    ).all()
    return [(str(relay_id), list(serials or [])) for relay_id, serials in rows]


async def disabled_relay_serials(db: AsyncSession) -> set[str]:
    """Serials owned by disabled agents (unscoped — used by gRPC register paths).

    Read as a small set rather than a per-serial query: disabled agents are rare
    and this runs once per adapter registration, not per frame.
    """
    table = RelayAgent.__table__
    rows = (
        await db.execute(
            select(table.c.serials).where(table.c.status == "disabled")
        )
    ).all()
    out: set[str] = set()
    for (serials,) in rows:
        for serial in serials or []:
            cleaned = str(serial).strip()
            if cleaned and not cleaned.startswith("pending-"):
                out.add(cleaned)
    return out


async def relay_agent_is_disabled(db: AsyncSession, relay_id: str) -> bool:
    """Unscoped check for the gRPC register path (no tenant context there)."""
    table = RelayAgent.__table__
    status = (
        await db.execute(
            select(table.c.status).where(table.c.relay_id == relay_id).limit(1)
        )
    ).scalar_one_or_none()
    return str(status or "") == "disabled"


async def list_relay_agents(
    db: AsyncSession,
    *,
    user_id: Optional[str] = None,
    org_id: Optional[str] = None,
) -> list[RelayAgent]:
    stmt = select(RelayAgent).order_by(RelayAgent.connected_at.desc())
    if user_id is not None:
        stmt = stmt.where(RelayAgent.user_id == user_id)
    if org_id is not None:
        stmt = stmt.where(RelayAgent.org_id == org_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_relay_agent(
    db: AsyncSession,
    relay_id: str,
    *,
    user_id: Optional[str] = None,
    org_id: Optional[str] = None,
) -> Optional[RelayAgent]:
    stmt = select(RelayAgent).where(RelayAgent.relay_id == relay_id)
    if user_id is not None:
        stmt = stmt.where(RelayAgent.user_id == user_id)
    if org_id is not None:
        stmt = stmt.where(RelayAgent.org_id == org_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
