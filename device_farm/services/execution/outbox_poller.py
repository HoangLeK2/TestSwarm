"""Outbox poller + retention for execution events (DF-T-04-013)."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 1.0
RETENTION_DAYS = 30


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
                count = await process_outbox_batch(db, limit=200)
                await db.commit()
                if count:
                    try:
                        from web.metrics import execution_event_outbox_lag_seconds

                        execution_event_outbox_lag_seconds.set(0)
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

    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    async with AsyncSessionLocal() as db:
        deleted = await purge_events_older_than(db, cutoff=cutoff)
        await db.commit()
        if deleted:
            log.info("purged %s execution events older than %s days", deleted, RETENTION_DAYS)
