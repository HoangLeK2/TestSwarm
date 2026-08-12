"""Add fast lookup indexes for leasing crawled Facebook posts."""

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_content_items_action_frontier "
            "ON content_items (org_id, platform, content_type, extracted_at DESC, id) "
            "WHERE deleted_at IS NULL AND item_level = 0 "
            "AND content_type IN ('fb_post', 'post')"
        )
    )
    if conn.dialect.name == "postgresql":
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_content_items_action_fts "
                "ON content_items USING GIN "
                "(to_tsvector('simple', coalesce(title, '') || ' ' || "
                "coalesce(body, ''))) "
                "WHERE deleted_at IS NULL AND item_level = 0 "
                "AND content_type IN ('fb_post', 'post')"
            )
        )


async def downgrade(conn) -> None:
    await conn.execute(text("DROP INDEX IF EXISTS idx_content_items_action_fts"))
    await conn.execute(text("DROP INDEX IF EXISTS idx_content_items_action_frontier"))
