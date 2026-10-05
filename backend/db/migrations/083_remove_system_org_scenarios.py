"""083 — Remove __system org-scenario duplicates; templates live in scenario_templates only."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            DELETE FROM org_scenario_tags
            WHERE org_scenario_id IN (
                SELECT id FROM org_scenarios WHERE org_id = '__system'
            );
            """
        )
    )
    await conn.execute(
        text("DELETE FROM org_scenarios WHERE org_id = '__system';")
    )


async def downgrade(conn) -> None:
    # Data was removed intentionally; re-seed via seed_system_org_templates if needed.
    pass
