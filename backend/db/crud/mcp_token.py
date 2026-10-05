from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.mcp_token import McpToken
from db.models.utils import _now
from mcp.token_store import TokenScope, hash_token, token_id

MCP_TOKEN_PREFIX = "dfmcp_"


def _generate_plaintext() -> str:
    return f"{MCP_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def lookup_mcp_token(db: AsyncSession, raw_token: str) -> McpToken | None:
    token = (raw_token or "").strip()
    if not token.startswith(MCP_TOKEN_PREFIX):
        return None
    hashed = hash_token(token)
    result = await db.execute(
        select(McpToken).where(
            McpToken.hashed_value == hashed,
            McpToken.revoked_at.is_(None),
        ).limit(1)
    )
    return result.scalar_one_or_none()


async def list_mcp_tokens(
    db: AsyncSession,
    *,
    include_revoked: bool = False,
    org_id: str | None = None,
    owner_user_id: str | None = None,
) -> list[McpToken]:
    stmt = select(McpToken).order_by(McpToken.created_at.desc())
    if org_id is not None:
        if owner_user_id is not None:
            stmt = stmt.where(
                or_(
                    McpToken.org_id == org_id,
                    and_(McpToken.org_id.is_(None), McpToken.owner_user_id == owner_user_id),
                )
            )
        else:
            stmt = stmt.where(McpToken.org_id == org_id)
    elif owner_user_id is not None:
        stmt = stmt.where(McpToken.owner_user_id == owner_user_id)
    if not include_revoked:
        stmt = stmt.where(McpToken.revoked_at.is_(None))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def create_mcp_token(
    db: AsyncSession,
    *,
    name: str,
    scope_type: TokenScope,
    scope_ref: str | None = None,
    owner_user_id: str | None = None,
    org_id: str | None = None,
) -> tuple[McpToken, str]:
    if scope_type not in {"device", "user"}:
        raise ValueError("scope_type must be device or user")
    plaintext = _generate_plaintext()
    row = McpToken(
        id=token_id(plaintext),
        name=name.strip() or f"{scope_type} MCP token",
        hashed_value=hash_token(plaintext),
        scope_type=scope_type,
        scope_ref=str(scope_ref) if scope_ref is not None else None,
        owner_user_id=str(owner_user_id) if owner_user_id is not None else None,
        org_id=str(org_id) if org_id is not None else None,
        created_at=_now(),
    )
    db.add(row)
    await db.flush()
    return row, plaintext


async def revoke_mcp_token(
    db: AsyncSession,
    record_id: str,
    *,
    org_id: str | None = None,
) -> bool:
    stmt = (
        update(McpToken)
        .where(
            McpToken.id == record_id,
            McpToken.revoked_at.is_(None),
        )
        .values(revoked_at=_now())
        .returning(McpToken.id)
    )
    if org_id is not None:
        stmt = stmt.where(McpToken.org_id == org_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


def row_to_record(row: McpToken):
    from mcp.token_store import McpTokenRecord

    created_at = _as_utc(row.created_at)
    revoked_at = _as_utc(row.revoked_at)
    return McpTokenRecord(
        id=row.id,
        name=row.name,
        hashed_value=row.hashed_value,
        scope_type=row.scope_type,  # type: ignore[arg-type]
        scope_ref=row.scope_ref,
        owner_user_id=row.owner_user_id,
        org_id=row.org_id,
        created_at=created_at.timestamp() if created_at else 0.0,
        revoked_at=revoked_at.timestamp() if revoked_at else None,
    )
