from __future__ import annotations

import os
import re
import secrets
import unicodedata
from datetime import datetime, timezone
from uuid import uuid4

from passlib.context import CryptContext
from sqlalchemy import text


_pwd = CryptContext(schemes=["bcrypt_sha256"], deprecated="auto")
_DIACRITIC_MAP = str.maketrans({"đ": "d", "Đ": "D"})


def hash_password(password: str) -> str:
    return _pwd.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return _pwd.verify(password, hashed)


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


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


async def _users_columns(conn) -> set[str]:
    dialect = getattr(getattr(conn, "dialect", None), "name", "")
    if dialect == "sqlite":
        result = await conn.execute(text("PRAGMA table_info(users)"))
        return {row[1] for row in result.fetchall()}
    result = await conn.execute(text("""
        SELECT column_name
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = 'users'
    """))
    return {row[0] for row in result.fetchall()}


async def _users_org_column(conn) -> str:
    """Return users.org_id or users.default_org_id depending on schema age."""
    columns = await _users_columns(conn)
    if "org_id" in columns:
        return "org_id"
    if "default_org_id" in columns:
        return "default_org_id"
    return "org_id"


async def _insert_superadmin_user(
    conn,
    *,
    user_id: str,
    email: str,
    name: str,
    hashed_password: str,
    api_key: str,
    org_id: str,
    org_column: str,
) -> None:
    columns = await _users_columns(conn)
    insert_cols = [
        "id",
        "email",
        "name",
        "hashed_password",
        "api_key",
        "role",
        "is_active",
        org_column,
        "created_at",
    ]
    insert_vals = [
        ":id",
        ":email",
        ":name",
        ":hashed_password",
        ":api_key",
        "'superadmin'",
        "TRUE",
        ":org_id",
        "CURRENT_TIMESTAMP",
    ]
    if "failed_login_count" in columns:
        insert_cols.append("failed_login_count")
        insert_vals.append("0")
    if "must_change_password" in columns:
        insert_cols.append("must_change_password")
        insert_vals.append("FALSE")
    await conn.execute(
        text(f"""
            INSERT INTO users ({", ".join(insert_cols)})
            VALUES ({", ".join(insert_vals)})
        """),
        {
            "id": user_id,
            "email": email,
            "name": name,
            "hashed_password": hashed_password,
            "api_key": api_key,
            "org_id": org_id,
        },
    )


async def _ensure_personal_org_for_user(
    conn,
    *,
    user_id: str,
    name: str,
    email: str,
    org_column: str,
) -> str:
    existing_org = await conn.execute(
        text(f"""
            SELECT {org_column}
              FROM users
             WHERE id = :user_id
             LIMIT 1
        """),
        {"user_id": user_id},
    )
    row = existing_org.first()
    if row is not None and row[0]:
        return row[0]

    membership_org = await conn.execute(
        text("""
            SELECT organization_id
              FROM organization_members
             WHERE user_id = :user_id
             ORDER BY created_at
             LIMIT 1
        """),
        {"user_id": user_id},
    )
    membership_row = membership_org.first()
    if membership_row is not None and membership_row[0]:
        await conn.execute(
            text(f"UPDATE users SET {org_column} = :org_id WHERE id = :user_id"),
            {"org_id": membership_row[0], "user_id": user_id},
        )
        return membership_row[0]

    org_id = str(uuid4())
    now = datetime.now(timezone.utc)
    await conn.execute(
        text("""
            INSERT INTO organizations
                (id, business_name, business_email, created_at)
            VALUES (:id, :business_name, :business_email, :created_at)
        """),
        {
            "id": org_id,
            "business_name": _personal_org_name(name, email),
            "business_email": email or None,
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
        text(f"UPDATE users SET {org_column} = :org_id WHERE id = :user_id"),
        {"org_id": org_id, "user_id": user_id},
    )
    return org_id


async def _allow_superadmin_role(conn) -> None:
    if getattr(getattr(conn, "dialect", None), "name", "") != "postgresql":
        return
    await conn.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'users'
            ) THEN
                IF EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'check_user_role'
                ) THEN
                    ALTER TABLE users DROP CONSTRAINT check_user_role;
                END IF;
                ALTER TABLE users
                    ADD CONSTRAINT check_user_role
                    CHECK (role IN ('superadmin', 'admin', 'operator'));
            END IF;
        END $$;
        """
    )


async def _seed_superadmin(conn) -> None:
    email = _env("DEVICE_FARM_SUPERADMIN_EMAIL").lower()
    password = _env("DEVICE_FARM_SUPERADMIN_PASSWORD")
    if not email or not password:
        return

    name = _env("DEVICE_FARM_SUPERADMIN_NAME") or "Super Admin"
    hashed_password = hash_password(password)
    org_column = await _users_org_column(conn)

    existing = await conn.execute(
        text("SELECT id FROM users WHERE lower(email) = :email LIMIT 1"),
        {"email": email},
    )
    row = existing.first()
    if row is not None:
        user_id = row[0]
        await conn.execute(
            text("""
                UPDATE users
                   SET name = :name,
                       hashed_password = :hashed_password,
                       role = 'superadmin',
                       is_active = TRUE
                 WHERE id = :user_id
            """),
            {
                "user_id": user_id,
                "name": name,
                "hashed_password": hashed_password,
            },
        )
        await _ensure_personal_org_for_user(
            conn,
            user_id=user_id,
            name=name,
            email=email,
            org_column=org_column,
        )
        return

    user_id = str(uuid4())
    org_id = str(uuid4())
    now = datetime.now(timezone.utc)
    await conn.execute(
        text("""
            INSERT INTO organizations
                (id, business_name, business_email, created_at)
            VALUES (:id, :business_name, :business_email, :created_at)
        """),
        {
            "id": org_id,
            "business_name": _personal_org_name(name, email),
            "business_email": email,
            "created_at": now,
        },
    )
    await _insert_superadmin_user(
        conn,
        user_id=user_id,
        email=email,
        name=name,
        hashed_password=hashed_password,
        api_key=secrets.token_urlsafe(32)[:64],
        org_id=org_id,
        org_column=org_column,
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


async def upgrade(conn) -> None:
    await _allow_superadmin_role(conn)
    await _seed_superadmin(conn)
