"""026 — Add checkpoint_step column to executions for resume-on-crash support.

Phase 1 (crawling-enhancement): when a scenario execution is interrupted (server
crash, device disconnect, task cancelled), the dispatcher may re-schedule the
execution. `checkpoint_step` records the index of the last step that committed
work so the executor can skip already-completed steps on resume.

Idempotent — safe to re-run.
"""
from __future__ import annotations


async def upgrade(conn) -> None:
    await conn.execute(
        """
        ALTER TABLE executions
            ADD COLUMN IF NOT EXISTS checkpoint_step INTEGER NOT NULL DEFAULT 0;
        """
    )
