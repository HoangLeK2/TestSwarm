"""Backfill org_id for superadmin users after tenancy NOT NULL on users.org_id.

Migration 051 seeds superadmin with org_id NULL for global access, but migration 044
requires users.org_id NOT NULL. Superadmin still bypasses tenant checks via role;
org_id satisfies the schema and gives a default workspace.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import text


_DIACRITIC_MAP = str.maketrans({"đ": "d", "Đ": "D"})


def _ascii_fold(value: str | None) -> str:
    text_value = (value or "").translate(_DIACRITIC_MAP)
    normalized = unicodedata.normalize("NFKD", text_value)
    ascii_text = "".join(
        ch for ch in normalized
        if not unicodedata.combining(ch) and ord(ch) < 128
    )
    return re.sub(r"\s+", " ", ascii_text).strip()


def _personal_org_name(name: str | None, email: str | None) -> str:
    base = _ascii_fold(name)
    if not base:
        base = _ascii_fold((email or "").split("@", 1)[0])
    if not base:
        return "My Workspace"
    return f"{base}'s Workspace"


async def upgrade(conn) -> None:
    await conn.execute(text("""
        UPDATE users u
           SET org_id = (
               SELECT m.organization_id
                 FROM organization_members m
                WHERE m.user_id = u.id
                ORDER BY m.created_at
                LIMIT 1
           )
         WHERE u.role = 'superadmin'
           AND (u.org_id IS NULL OR u.org_id = '')
           AND EXISTS (
               SELECT 1 FROM organization_members m WHERE m.user_id = u.id
           )
    """))

    result = await conn.execute(text("""
        SELECT u.id, u.name, u.email, u.created_at
          FROM users u
         WHERE u.role = 'superadmin'
           AND (u.org_id IS NULL OR u.org_id = '')
    """))
    rows = result.fetchall()
    for user_id, name, email, created_at in rows:
        org_id = str(uuid4())
        now = created_at or datetime.now(timezone.utc)
        await conn.execute(
            text("""
                INSERT INTO organizations
                    (id, business_name, business_email, created_at)
                VALUES (:id, :business_name, :business_email, :created_at)
            """),
            {
                "id": org_id,
                "business_name": _personal_org_name(name, email),
                "business_email": (email or "").strip() or None,
                "created_at": now,
            },
        )
        await conn.execute(
            text("""
                INSERT INTO organization_members
                    (id, organization_id, user_id, role, created_at)
                VALUES (:id, :organization_id, :user_id, 'owner', :created_at)
            """),
            {
                "id": str(uuid4()),
                "organization_id": org_id,
                "user_id": user_id,
                "created_at": now,
            },
        )
        await conn.execute(
            text("UPDATE users SET org_id = :org_id WHERE id = :user_id"),
            {"org_id": org_id, "user_id": user_id},
        )
