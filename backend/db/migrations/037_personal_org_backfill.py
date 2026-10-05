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
    result = await conn.execute(text("""
        SELECT u.id, u.name, u.email, u.created_at
          FROM users u
          LEFT JOIN organization_members m ON m.user_id = u.id
         WHERE m.id IS NULL
    """))
    for user_id, name, email, created_at in result.fetchall():
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
