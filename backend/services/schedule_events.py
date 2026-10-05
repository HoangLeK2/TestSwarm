"""Schedule domain events and audit helpers for DF-E-05."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

SCHEDULE_RUN_TERMINAL = "schedule.run.terminal"


async def emit_schedule_run_terminal(
    db: AsyncSession,
    *,
    organization_id: Optional[str],
    schedule_id: str,
    run_id: str,
    status: str,
    execution_id: Optional[str] = None,
    occurred_at: Optional[datetime] = None,
    details: Optional[dict[str, Any]] = None,
) -> None:
    """Emit the terminal schedule-run domain event via audit + notifications.

    The scheduling module does not own the execution event outbox, so this keeps
    the event at the schedule domain boundary and lets Notifications subscribe
    to `schedule.run.terminal`.
    """
    payload = {
        "schedule_id": schedule_id,
        "run_id": run_id,
        "status": status,
        "execution_id": execution_id,
        "occurred_at": occurred_at.isoformat() if occurred_at else None,
        **(details or {}),
    }
    if organization_id:
        try:
            from services.activity_logger import log_activity

            await log_activity(
                db,
                action=SCHEDULE_RUN_TERMINAL,
                entity_type="schedule_run",
                entity_id=run_id,
                org_id=organization_id,
                after_state=payload,
                details={"source_event_type": SCHEDULE_RUN_TERMINAL, **payload},
            )
        except Exception:
            log.debug("schedule terminal activity log skipped", exc_info=True)

    try:
        from services.notification_service import notification_service

        await notification_service.notify(
            SCHEDULE_RUN_TERMINAL,
            "Schedule run finished",
            f"Schedule {schedule_id} run {run_id} finished with status {status}",
            payload,
        )
    except Exception:
        log.debug("schedule terminal notification skipped", exc_info=True)
