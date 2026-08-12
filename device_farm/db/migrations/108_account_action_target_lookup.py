"""Add lookup indexes for high-volume account target leasing."""

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_account_actions_target_state "
            "ON account_actions "
            "(org_id, account_id, platform, action_type, status)"
        )
    )
    if conn.dialect.name == "postgresql":
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_account_actions_target_identity "
                "ON account_actions "
                "(org_id, account_id, platform, action_type, "
                "(target->>'action'), (target->>'target_id'))"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_external_entities_display_name_fts "
                "ON external_entities USING GIN "
                "(to_tsvector('simple', coalesce(display_name, '')))"
            )
        )


async def downgrade(conn) -> None:
    await conn.execute(
        text("DROP INDEX IF EXISTS idx_external_entities_display_name_fts")
    )
    await conn.execute(text("DROP INDEX IF EXISTS idx_account_actions_target_identity"))
    await conn.execute(text("DROP INDEX IF EXISTS idx_account_actions_target_state"))
