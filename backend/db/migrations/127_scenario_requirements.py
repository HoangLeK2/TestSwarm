"""127 — persist scenario-level execution requirements."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    postgres = conn.dialect.name == "postgresql"
    json_type = "JSONB" if postgres else "JSON"
    default_expr = "'{}'::jsonb" if postgres else "'{}'"
    await conn.execute(
        text(
            f"""
            ALTER TABLE scenarios
            ADD COLUMN IF NOT EXISTS requirements {json_type} NOT NULL DEFAULT {default_expr}
            """
        )
    )
    await conn.execute(
        text(
            f"""
            ALTER TABLE scenario_versions
            ADD COLUMN IF NOT EXISTS requirements {json_type} NOT NULL DEFAULT {default_expr}
            """
        )
    )


async def downgrade(conn) -> None:
    await conn.execute(
        text("ALTER TABLE scenario_versions DROP COLUMN IF EXISTS requirements")
    )
    await conn.execute(text("ALTER TABLE scenarios DROP COLUMN IF EXISTS requirements"))
