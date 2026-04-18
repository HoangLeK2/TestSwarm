"""018 — Add user_id FK to content_items for direct auth queries."""
from __future__ import annotations


async def upgrade(conn) -> None:
    # ── Add user_id column ───────────────────────────────────────────────────
    await conn.execute(
        """
        ALTER TABLE content_items
            ADD COLUMN IF NOT EXISTS user_id VARCHAR(36)
            REFERENCES users(id) ON DELETE SET NULL;
        """
    )

    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_content_items_user ON content_items(user_id);"
    )

    # ── Backfill from execution.user_id ──────────────────────────────────────
    await conn.execute(
        """
        UPDATE content_items ci
        SET user_id = e.user_id
        FROM executions e
        WHERE ci.execution_id = e.id
          AND ci.user_id IS NULL
          AND e.user_id IS NOT NULL;
        """
    )

    # ── Backfill from campaign.user_id (for items without execution) ─────────
    await conn.execute(
        """
        UPDATE content_items ci
        SET user_id = c.user_id
        FROM campaigns c
        WHERE ci.campaign_id = c.id
          AND ci.user_id IS NULL
          AND c.user_id IS NOT NULL;
        """
    )
