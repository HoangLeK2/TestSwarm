"""Outbox poller + retention for execution events (DF-T-04-013)."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 1.0
RETENTION_DAYS = 30

# Events worth keeping long after the run is forgotten. A ban surfaces weeks
# later, and by then the 30-day window had already deleted the only record of
# what the account did — execution_events is the sole source of steps below
# depth 0, and it is never rebuilt.
#
# This is 3.6% of rows in practice (292/8218 measured), so the extra retention
# costs almost nothing next to the successes it leaves on the old schedule.
FORENSIC_EVENT_PREFIXES = ("incident.", "execution.dlq.", "account_action.")
FORENSIC_EVENT_TYPES = ("step.failed", "execution.failed", "execution.cancelled")


def _retention_days(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _lease_seconds() -> float:
    try:
        return max(5.0, float(os.getenv("EXECUTION_EVENT_OUTBOX_LEASE_SECONDS", "30")))
    except (TypeError, ValueError):
        return 30.0


async def execution_event_outbox_loop() -> None:
    from db.database import AsyncSessionLocal
    from services.execution.event_publisher import process_outbox_batch

    tick = 0
    while True:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        from db.database import schema_init_ok

        if schema_init_ok is not True:
            continue
        try:
            async with AsyncSessionLocal() as db:
                await process_outbox_batch(
                    db,
                    limit=200,
                    lease_seconds=_lease_seconds(),
                )
                from db.crud.execution_events import get_unpublished_event_stats

                stats = await get_unpublished_event_stats(db)
                await db.commit()
                try:
                    from web.metrics import (
                        execution_event_outbox_backlog,
                        execution_event_outbox_lag_seconds,
                    )

                    execution_event_outbox_backlog.set(stats.count)
                    execution_event_outbox_lag_seconds.set(stats.oldest_age_seconds)
                except Exception:
                    pass
        except Exception as exc:
            log.warning("execution event outbox poll failed: %s", exc)

        tick += 1
        if tick % 3600 == 0:
            try:
                await _purge_old_events()
            except Exception as exc:
                log.warning("execution event retention purge failed: %s", exc)


async def _purge_old_events() -> None:
    from db.crud.execution_events import purge_events_older_than
    from db.database import AsyncSessionLocal

    now = datetime.now(timezone.utc)
    routine_days = _retention_days("EXECUTION_EVENT_RETENTION_DAYS", RETENTION_DAYS)
    forensic_days = _retention_days("EXECUTION_EVENT_FORENSIC_RETENTION_DAYS", 365)
    async with AsyncSessionLocal() as db:
        deleted = await purge_events_older_than(
            db,
            cutoff=now - timedelta(days=routine_days),
            keep_types=FORENSIC_EVENT_TYPES,
            keep_type_prefixes=FORENSIC_EVENT_PREFIXES,
        )
        # The forensic set is not kept forever, only longer. Past its own
        # window it goes the same way.
        deleted += await purge_events_older_than(
            db, cutoff=now - timedelta(days=forensic_days)
        )
        await db.commit()
        if deleted:
            log.info(
                "purged %s execution events (routine=%sd forensic=%sd)",
                deleted,
                routine_days,
                forensic_days,
            )
