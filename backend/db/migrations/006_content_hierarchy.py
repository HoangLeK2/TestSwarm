"""Content hierarchy — add parent_id + item_level to content_items.

parent_id  : content_hash of the parent item (NULL for top-level posts).
             Uses content_hash (not UUID FK) so the link is computed deterministically
             at crawl time without a DB lookup, and works across platforms/runs.
item_level : 0 = post/top-level, 1 = comment, 2 = reply.
             Indexed together with parent_id for fast child lookups.
"""
from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text(
        """
        ALTER TABLE content_items
        ADD COLUMN IF NOT EXISTS parent_id  VARCHAR(64)  DEFAULT NULL,
        ADD COLUMN IF NOT EXISTS item_level SMALLINT     NOT NULL DEFAULT 0
        """
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_ci_parent_id ON content_items(parent_id)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_ci_item_level ON content_items(item_level)"
    ))
    # Composite: fetch all comments for a post in one scan
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_ci_parent_level "
        "ON content_items(parent_id, item_level)"
    ))
