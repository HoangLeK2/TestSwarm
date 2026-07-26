"""091 — repair execution DLQ tenant ownership from the parent execution."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            UPDATE execution_dlq AS dlq
               SET org_id = execution.org_id
              FROM executions AS execution
             WHERE dlq.execution_id = execution.id
               AND (dlq.org_id IS NULL OR dlq.org_id = '')
               AND execution.org_id IS NOT NULL
               AND execution.org_id <> '';
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE execution_dlq
                ALTER COLUMN org_id SET NOT NULL;
            """
        )
    )
