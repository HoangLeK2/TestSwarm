"""125 - Account TXT import formats."""
from __future__ import annotations

import json

from sqlalchemy import text


_BUILTIN_FORMATS = (
    {
        "id": "6b7c5c2a-0ebf-4a8b-9bd0-0a8c2836a001",
        "slug": "facebook_uid_password_totp_cookies_token_email",
        "name": "Facebook UID, password, 2FA, cookies, token, email",
        "description": "uid|password|totp_secret|cookies|token|email|email_password",
        "delimiter": "|",
        "platform": "facebook",
        "fields": [
            "username",
            "password",
            "totp_secret",
            "cookies",
            "token",
            "email",
            "metadata.email_password",
            "ignore",
        ],
    },
    {
        "id": "6b7c5c2a-0ebf-4a8b-9bd0-0a8c2836a002",
        "slug": "facebook_uid_password_totp_email_token",
        "name": "Facebook UID, password, 2FA, email, token",
        "description": (
            "uid|password|totp_secret|email|email_password|"
            "recovery_email|token|external_id"
        ),
        "delimiter": "|",
        "platform": "facebook",
        "fields": [
            "username",
            "password",
            "totp_secret",
            "email",
            "metadata.email_password",
            "metadata.recovery_email",
            "token",
            "metadata.external_id",
        ],
    },
)


async def upgrade(conn) -> None:
    postgres = conn.dialect.name == "postgresql"
    json_type = "JSONB" if postgres else "JSON"
    json_bind = "CAST(:fields AS JSONB)" if postgres else ":fields"
    await conn.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS account_import_formats (
                id VARCHAR(36) PRIMARY KEY,
                slug VARCHAR(100) NOT NULL,
                name VARCHAR(255) NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                delimiter VARCHAR(10) NOT NULL DEFAULT '|',
                platform VARCHAR(50) NOT NULL DEFAULT 'facebook',
                fields {json_type} NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                is_builtin BOOLEAN NOT NULL DEFAULT FALSE,
                created_by_user_id VARCHAR(36) NULL REFERENCES users(id) ON DELETE SET NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_account_import_formats_slug UNIQUE (slug)
            )
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_account_import_formats_active
            ON account_import_formats (is_active)
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE account_import_formats
                ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE account_import_formats
                ALTER COLUMN updated_at SET DEFAULT CURRENT_TIMESTAMP
            """
        )
    )
    await conn.execute(
        text(
            """
            UPDATE account_import_formats
            SET created_at = COALESCE(created_at, CURRENT_TIMESTAMP),
                updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP)
            WHERE created_at IS NULL OR updated_at IS NULL
            """
        )
    )
    for row in _BUILTIN_FORMATS:
        await conn.execute(
            text(
                """
                INSERT INTO account_import_formats (
                    id, slug, name, description, delimiter, platform, fields,
                    is_active, is_builtin, created_at, updated_at
                )
                VALUES (
                    :id, :slug, :name, :description, :delimiter, :platform,
                    """
                + json_bind
                + """, TRUE, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                ON CONFLICT (slug) DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    delimiter = EXCLUDED.delimiter,
                    platform = EXCLUDED.platform,
                    fields = EXCLUDED.fields,
                    is_active = TRUE,
                    is_builtin = TRUE,
                    updated_at = CURRENT_TIMESTAMP
                """
            ),
            {**row, "fields": json.dumps(row["fields"])},
        )
