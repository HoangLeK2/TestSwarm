"""095 — accelerate source-pool exclusion of active assignments."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            UPDATE execution_entity_assignments AS assignment
            SET status = execution.status,
                completed_at = COALESCE(
                    execution.finished_at,
                    assignment.assigned_at
                )
            FROM executions AS execution
            WHERE assignment.execution_id = execution.id
              AND assignment.completed_at IS NULL
              AND execution.status IN (
                  'completed',
                  'failed',
                  'cancelled',
                  'dlq_closed'
              );
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS
                idx_execution_entity_assignments_active_source
            ON execution_entity_assignments (org_id, external_entity_id)
            WHERE completed_at IS NULL AND status = 'assigned';
            """
        )
    )
