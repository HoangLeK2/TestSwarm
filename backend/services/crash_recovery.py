"""Phase 1 — Crash recovery for interrupted executions.

On server startup, finds Executions in status='running' that were left behind
by a crashed previous session. These cannot resume automatically (device state
is unknown) but they are visible in the DLQ so operators can retry manually
using the existing checkpoint_step to skip already-completed steps.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from db.database import activity_session
from db.models.execution import Execution

log = logging.getLogger(__name__)


async def recover_stuck_executions(stale_after_minutes: int = 5) -> dict:
    """
    Mark executions stuck in 'running' state as 'failed' and DLQ them.

    `stale_after_minutes` — consider an execution stuck if started_at
    is older than this and no completion recorded. Short window because
    on fresh startup, nothing is actively running yet.

    Returns {"scanned": N, "recovered": M}.
    """
    from db.crud.execution_dlq import create_dlq_entry

    stats = {"scanned": 0, "recovered": 0}
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_after_minutes)

    async with activity_session() as db:
        stmt = (
            select(Execution)
            .where(Execution.status == "running")
            .where(Execution.started_at.isnot(None))
            .where(Execution.started_at < cutoff)
        )
        result = await db.execute(stmt)
        stuck = list(result.scalars().all())
        stats["scanned"] = len(stuck)

        for exc in stuck:
            # Mark as failed so dispatcher doesn't re-process blindly.
            exc.status = "failed"
            exc.finished_at = datetime.now(timezone.utc)
            meta = dict(exc.meta or {})
            meta["recovery_reason"] = "interrupted_by_restart"
            meta["recovery_checkpoint"] = exc.checkpoint_step
            exc.meta = meta
            # DLQ entry so operators can retry via existing API.
            try:
                await create_dlq_entry(
                    db,
                    execution_id=exc.id,
                    device_serial="",  # unknown at recovery time; per-device result carries it
                    org_id=exc.org_id,
                    error=f"Interrupted by server restart at step {exc.checkpoint_step}",
                )
            except Exception as e:
                log.warning("DLQ entry failed for execution %s: %s", exc.id, e)
            stats["recovered"] += 1

        if stats["recovered"]:
            await db.commit()
            log.info(
                "crash recovery: marked %d stuck execution(s) as failed (scanned %d)",
                stats["recovered"], stats["scanned"],
            )

    return stats
