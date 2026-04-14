"""
010_scenario_graph — Add nodes/edges columns to scenarios table.

Additive migration: keeps steps[] intact for executor backward compat.
Existing scenarios get empty nodes/edges arrays (populated lazily on first edit).
"""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("""
        ALTER TABLE scenarios
            ADD COLUMN IF NOT EXISTS nodes JSONB NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN IF NOT EXISTS edges JSONB NOT NULL DEFAULT '[]'::jsonb
    """))
    await conn.execute(text("""
        ALTER TABLE scenario_templates
            ADD COLUMN IF NOT EXISTS nodes JSONB NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN IF NOT EXISTS edges JSONB NOT NULL DEFAULT '[]'::jsonb
    """))


async def downgrade(conn) -> None:
    await conn.execute(text(
        "ALTER TABLE scenarios DROP COLUMN IF EXISTS nodes, DROP COLUMN IF EXISTS edges"
    ))
    await conn.execute(text(
        "ALTER TABLE scenario_templates DROP COLUMN IF EXISTS nodes, DROP COLUMN IF EXISTS edges"
    ))
