"""Register Temporal cron for account cooldown expiry (DF-T-07-005)."""
from __future__ import annotations

import logging

from temporalio.client import Client, Schedule, ScheduleActionStartWorkflow, ScheduleSpec

from temporal.account_state_workflows import AccountCooldownTickWorkflow

log = logging.getLogger(__name__)

COOLDOWN_SCHEDULE_ID = "df-account-cooldown-tick"
# Cooldown expiry runs on two independent paths: this Temporal schedule and the
# in-process loop in web/server.py, which sleeps COOLDOWN_TICK_INTERVAL_SECONDS
# between passes. Both call the same idempotent process_expired_cooldowns, so
# the effective granularity is the faster of the two — the in-process loop.
# The Temporal schedule is deliberately slower: it exists as the durable
# backstop, and a tick every 15 minutes keeps the workflow list readable.
COOLDOWN_TICK_INTERVAL_SECONDS = 300
_CRON = "*/15 * * * *"


async def _sync_cooldown_schedule_cron(client: Client) -> None:
    from temporalio.client import ScheduleSpec, ScheduleUpdate

    handle = client.get_schedule_handle(COOLDOWN_SCHEDULE_ID)

    def _updater(input):
        schedule = input.description.schedule
        schedule.spec = ScheduleSpec(cron_expressions=[_CRON])
        return ScheduleUpdate(schedule=schedule)

    await handle.update(_updater)
    log.info("Temporal schedule updated: %s cron=%s", COOLDOWN_SCHEDULE_ID, _CRON)


async def ensure_account_cooldown_schedule(
    client: Client,
    *,
    task_queue: str,
) -> None:
    """Idempotent: create or sync 5-minute cooldown tick schedule."""
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
            try:
                await _sync_cooldown_schedule_cron(client)
            except Exception as sync_exc:
                log.warning(
                    "Temporal schedule %s exists but cron sync failed: %s",
                    COOLDOWN_SCHEDULE_ID,
                    sync_exc,
                )
            return
        raise
