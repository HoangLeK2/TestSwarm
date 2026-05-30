"""Register Temporal cron for account cooldown expiry (DF-T-07-005)."""
from __future__ import annotations

import logging

from temporalio.client import Client, Schedule, ScheduleActionStartWorkflow, ScheduleSpec

from temporal.account_state_workflows import AccountCooldownTickWorkflow

log = logging.getLogger(__name__)

COOLDOWN_SCHEDULE_ID = "df-account-cooldown-tick"
_CRON = "*/1 * * * *"


async def ensure_account_cooldown_schedule(
    client: Client,
    *,
    task_queue: str,
) -> None:
    """Idempotent: create 1-minute cooldown tick schedule if missing."""
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            AccountCooldownTickWorkflow.run,
            id=f"{COOLDOWN_SCHEDULE_ID}-run",
            task_queue=task_queue,
        ),
        spec=ScheduleSpec(cron_expressions=[_CRON]),
    )
    try:
        await client.create_schedule(COOLDOWN_SCHEDULE_ID, schedule)
        log.info("Temporal schedule created: %s cron=%s", COOLDOWN_SCHEDULE_ID, _CRON)
    except Exception as exc:
        msg = str(exc).lower()
        if "already exists" in msg or "already_exists" in msg:
            log.debug("Temporal schedule %s already exists", COOLDOWN_SCHEDULE_ID)
            return
        raise
