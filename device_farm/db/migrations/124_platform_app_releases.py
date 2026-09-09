"""124 - Global platform app release registry."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS platform_app_releases (
                id VARCHAR(36) PRIMARY KEY,
                platform VARCHAR(50) NOT NULL,
                package_name VARCHAR(128) NOT NULL,
                version_name VARCHAR(128) NOT NULL,
                version_code VARCHAR(64) NULL,
                sha256 VARCHAR(64) NOT NULL,
                size_bytes BIGINT NOT NULL DEFAULT 0,
                object_key VARCHAR(512) NOT NULL,
                original_filename VARCHAR(255) NULL,
                content_type_mime VARCHAR(128) NOT NULL DEFAULT 'application/vnd.android.package-archive',
                status VARCHAR(20) NOT NULL DEFAULT 'draft',
                notes TEXT NULL,
                uploaded_by_user_id VARCHAR(36) NULL REFERENCES users(id) ON DELETE SET NULL,
                published_at TIMESTAMPTZ NULL,
                archived_at TIMESTAMPTZ NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_platform_app_releases_sha UNIQUE (platform, package_name, sha256)
            )
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_platform_app_releases_platform_status
            ON platform_app_releases (platform, package_name, status)
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_platform_app_releases_active
            ON platform_app_releases (platform, package_name)
            WHERE status = 'active'
            """
        )
    )
