from __future__ import annotations

import os
import secrets
from uuid import uuid4

from passlib.context import CryptContext
from sqlalchemy import text


_pwd = CryptContext(schemes=["bcrypt_sha256"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return _pwd.verify(password, hashed)


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


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

    existing = await conn.execute(
        text("SELECT id FROM users WHERE lower(email) = :email LIMIT 1"),
        {"email": email},
    )
    row = existing.first()
    if row is not None:
        await conn.execute(
            text("""
                UPDATE users
                   SET name = :name,
                       hashed_password = :hashed_password,
                       role = 'superadmin',
                       is_active = TRUE,
                       org_id = NULL
                 WHERE id = :user_id
            """),
            {
                "user_id": row[0],
                "name": name,
                "hashed_password": hashed_password,
            },
        )
        return

    await conn.execute(
        text("""
            INSERT INTO users
                (id, email, name, hashed_password, api_key, role, is_active, org_id, created_at)
            VALUES
                (:id, :email, :name, :hashed_password, :api_key, 'superadmin', TRUE, NULL, CURRENT_TIMESTAMP)
        """),
        {
            "id": str(uuid4()),
            "email": email,
            "name": name,
            "hashed_password": hashed_password,
            "api_key": secrets.token_urlsafe(32)[:64],
        },
    )


async def upgrade(conn) -> None:
    await _allow_superadmin_role(conn)
    await _seed_superadmin(conn)
