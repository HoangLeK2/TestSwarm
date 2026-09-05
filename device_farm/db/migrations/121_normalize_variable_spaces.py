"""121 - Strip exotic Unicode spaces out of campaign and scenario variables.

Facebook renders group names with a real NBSP (U+00A0). Six campaigns hold
``GROUP_TEXT = "OpenClaw VN · Truy cập"``; the steps that select on it
build a UiSelector, which compares byte-exact *on the device* and never
matches, so every one of those taps waits out its full 8s timeout. Measured
p50 for ``tap_selector`` was 7.9s — the timeout itself.

The runtime now has a whitespace-tolerant fallback phase, so this is hygiene,
not the fix. Only invisible space lookalikes are replaced; whitespace runs are
NOT collapsed and values are NOT stripped, because these columns also hold
captions and passwords.

``downgrade`` is a no-op: nothing here needs the NBSP back, and we could not
tell which of the plain spaces used to be one.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import text

from db.models.utils import normalize_variable_spaces

log = logging.getLogger(__name__)

_TABLES = ("campaigns", "scenarios")


async def upgrade(conn) -> None:
    # Postgres will not assign text to a json column without an explicit cast;
    # SQLite stores the same column as TEXT and rejects the cast.
    bind = "CAST(:v AS json)" if conn.dialect.name == "postgresql" else ":v"
    for table in _TABLES:
        rows = await conn.execute(
            text(f"SELECT id, variables FROM {table} WHERE variables IS NOT NULL")  # noqa: S608 - fixed literal
        )
        for row_id, raw in rows.fetchall():
            current = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
            cleaned = normalize_variable_spaces(current)
            if cleaned == current:
                continue
            log.info(
                "121: %s %s variables normalized\n  before: %s\n   after: %s",
                table, row_id,
                json.dumps(current, ensure_ascii=True),
                json.dumps(cleaned, ensure_ascii=True),
            )
            await conn.execute(
                text(f"UPDATE {table} SET variables = {bind} WHERE id = :id"),  # noqa: S608
                {"v": json.dumps(cleaned, ensure_ascii=False), "id": row_id},
            )


async def downgrade(conn) -> None:
    """No-op — the original NBSP positions are not recoverable, nor wanted."""
