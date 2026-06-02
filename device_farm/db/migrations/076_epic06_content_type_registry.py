"""076 — Epic 06: content type registry (DF-T-06-001)."""
from __future__ import annotations

from sqlalchemy import text

_SEED_TYPES = [
    ("fb_post", "facebook", "post", "active", "[]", "Facebook feed post"),
    ("fb_comment", "facebook", "comment", "active", '["fb_post"]', "Facebook comment on a post"),
    ("tiktok_video", "tiktok", "video", "active", "[]", "TikTok video item"),
    ("tiktok_comment", "tiktok", "comment", "active", '["tiktok_video"]', "TikTok comment"),
    ("threads_post", "threads", "post", "active", "[]", "Threads post"),
    ("threads_comment", "threads", "comment", "active", '["threads_post"]', "Threads comment"),
    ("ig_media", "instagram", "media", "active", "[]", "Instagram media post"),
    ("ig_comment", "instagram", "comment", "active", '["ig_media"]', "Instagram comment"),
    ("ig_profile", "instagram", "profile", "active", "[]", "Instagram profile page"),
]


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS content_types (
                code VARCHAR(64) PRIMARY KEY,
                platform VARCHAR(32) NOT NULL,
                object_kind VARCHAR(32) NOT NULL,
                status VARCHAR(16) NOT NULL DEFAULT 'active',
                parent_kinds_json JSONB NOT NULL DEFAULT '[]',
                description TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_content_types_platform_status
            ON content_types (platform, status);
            """
        )
    )
    # create_all may have created this table without server defaults on timestamps.
    await conn.execute(
        text(
            """
            ALTER TABLE content_types
                ALTER COLUMN created_at SET DEFAULT NOW()
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE content_types
                ALTER COLUMN updated_at SET DEFAULT NOW()
            """
        )
    )
    await conn.execute(
        text(
            """
            UPDATE content_types
            SET created_at = COALESCE(created_at, NOW()),
                updated_at = COALESCE(updated_at, NOW())
            WHERE created_at IS NULL OR updated_at IS NULL
            """
        )
    )
    for code, platform, object_kind, status, parent_kinds, description in _SEED_TYPES:
        await conn.execute(
            text(
                """
                INSERT INTO content_types
                    (code, platform, object_kind, status, parent_kinds_json, description,
                     created_at, updated_at)
                VALUES (
                    :code, :platform, :object_kind, :status,
                    CAST(:parent_kinds AS JSONB), :description, NOW(), NOW()
                )
                ON CONFLICT (code) DO UPDATE SET
                    platform = EXCLUDED.platform,
                    object_kind = EXCLUDED.object_kind,
                    status = EXCLUDED.status,
                    parent_kinds_json = EXCLUDED.parent_kinds_json,
                    description = EXCLUDED.description,
                    updated_at = NOW();
                """
            ),
            {
                "code": code,
                "platform": platform,
                "object_kind": object_kind,
                "status": status,
                "parent_kinds": parent_kinds,
                "description": description,
            },
        )
