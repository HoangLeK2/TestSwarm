"""Remove unused CampaignRun counters (never written; use /runs/{id}/content/stats)."""

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("ALTER TABLE campaign_runs DROP COLUMN IF EXISTS total_saved"))
    await conn.execute(text("ALTER TABLE campaign_runs DROP COLUMN IF EXISTS total_duplicate"))
