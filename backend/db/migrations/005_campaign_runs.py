"""Campaign run tracking — campaign_runs table + run_id column on content_items."""
from sqlalchemy import text


async def upgrade(conn) -> None:
    # Create campaign_runs table
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS campaign_runs (
                id VARCHAR(36) PRIMARY KEY,
                campaign_id VARCHAR(36) NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
                status VARCHAR(20) DEFAULT 'running',
                device_serials JSON DEFAULT '[]',
                workflow_ids JSON DEFAULT '[]',
                scenarios_count INTEGER DEFAULT 0,
                total_saved INTEGER DEFAULT 0,
                total_duplicate INTEGER DEFAULT 0,
                started_at TIMESTAMPTZ DEFAULT NOW(),
                finished_at TIMESTAMPTZ
            )
            """
        )
    )
    await conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_campaign_runs_campaign ON campaign_runs(campaign_id)")
    )
    await conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_campaign_runs_status ON campaign_runs(status)")
    )
    await conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_campaign_runs_started ON campaign_runs(started_at)")
    )

    # Add run_id column to content_items (idempotent via IF NOT EXISTS)
    await conn.execute(
        text(
            """
            ALTER TABLE content_items
            ADD COLUMN IF NOT EXISTS run_id VARCHAR(36)
                REFERENCES campaign_runs(id) ON DELETE SET NULL
            """
        )
    )
    await conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_ci_run_id ON content_items(run_id)")
    )
