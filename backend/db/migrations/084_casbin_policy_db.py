"""084 — Move Casbin RBAC policy storage into the database.

The checked-in CSV remains the bootstrap seed, but runtime authorization reads
from casbin_rule so policy changes are deployable consistently across workers.
"""

from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy import text


_POLICY_PATH = Path(__file__).resolve().parents[2] / "api" / "auth" / "rbac_policy.csv"
_POLICY_COLUMNS = ("ptype", "v0", "v1", "v2", "v3", "v4", "v5")


async def upgrade(conn) -> None:
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS casbin_rule (
            id BIGSERIAL PRIMARY KEY,
            ptype VARCHAR(32) NOT NULL,
            v0 VARCHAR(255),
            v1 VARCHAR(255),
            v2 VARCHAR(255),
            v3 VARCHAR(255),
            v4 VARCHAR(255),
            v5 VARCHAR(255),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    await conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_casbin_rule_unique
            ON casbin_rule (
                ptype,
                COALESCE(v0, ''),
                COALESCE(v1, ''),
                COALESCE(v2, ''),
                COALESCE(v3, ''),
                COALESCE(v4, ''),
                COALESCE(v5, '')
            )
    """))

    for row in _seed_policy_rows():
        params = dict(zip(_POLICY_COLUMNS, row))
        # Explicit VARCHAR casts: asyncpg rejects one bind param used as both
        # text (SELECT list) and varchar (column compare) in the same statement.
        await conn.execute(
            text("""
                INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, v4, v5)
                SELECT
                    CAST(:ptype AS VARCHAR(32)),
                    CAST(:v0 AS VARCHAR(255)),
                    CAST(:v1 AS VARCHAR(255)),
                    CAST(:v2 AS VARCHAR(255)),
                    CAST(:v3 AS VARCHAR(255)),
                    CAST(:v4 AS VARCHAR(255)),
                    CAST(:v5 AS VARCHAR(255))
                WHERE NOT EXISTS (
                    SELECT 1 FROM casbin_rule
                     WHERE ptype = CAST(:ptype AS VARCHAR(32))
                       AND COALESCE(v0, '') = COALESCE(CAST(:v0 AS VARCHAR(255)), '')
                       AND COALESCE(v1, '') = COALESCE(CAST(:v1 AS VARCHAR(255)), '')
                       AND COALESCE(v2, '') = COALESCE(CAST(:v2 AS VARCHAR(255)), '')
                       AND COALESCE(v3, '') = COALESCE(CAST(:v3 AS VARCHAR(255)), '')
                       AND COALESCE(v4, '') = COALESCE(CAST(:v4 AS VARCHAR(255)), '')
                       AND COALESCE(v5, '') = COALESCE(CAST(:v5 AS VARCHAR(255)), '')
                )
            """),
            params,
        )


def _seed_policy_rows() -> list[tuple[str, ...]]:
    rows: list[tuple[str, ...]] = []
    with _POLICY_PATH.open(newline="", encoding="utf-8") as fh:
        for raw in csv.reader(fh):
            if not raw:
                continue
            values = [value.strip() for value in raw]
            if not values or values[0].startswith("#"):
                continue
            padded = values[: len(_POLICY_COLUMNS)] + [""] * (len(_POLICY_COLUMNS) - len(values))
            rows.append(tuple(value or None for value in padded))
    return rows
