from __future__ import annotations

import asyncio
import logging
import os

log = logging.getLogger(__name__)


def _maintenance_interval_seconds() -> int:
    raw = os.environ.get("DEVICE_FARM_DLQ_MAINTENANCE_INTERVAL_SECONDS", "300")
    try:
        return max(60, min(86_400, int(raw)))
    except ValueError:
        return 300


def _offline_dismiss_minutes() -> int:
    raw = os.environ.get("DEVICE_FARM_DLQ_OFFLINE_DISMISS_MINUTES", "5")
    try:
        return max(1, min(10_080, int(raw)))
    except ValueError:
        return 5


async def dlq_stale_offline_maintenance_loop(*, manager=None) -> None:
    """Background loop: auto-dismiss DLQ pending rows for long-offline devices."""
    from db.database import AsyncSessionLocal
    from services.dlq_maintenance import dismiss_stale_offline_dlq_all_users

    interval = _maintenance_interval_seconds()
    offline_minutes = _offline_dismiss_minutes()
    log.info(
        "DLQ maintenance loop started (interval=%ss, offline_after=%sm)",
        interval,
        offline_minutes,
    )

    while True:
        await asyncio.sleep(interval)
        try:
            async with AsyncSessionLocal() as db:
                dismissed = await dismiss_stale_offline_dlq_all_users(
                    db,
                    offline_after_minutes=offline_minutes,
                    manager=manager,
                )
            if dismissed:
                log.info("DLQ maintenance dismissed %s stale-offline entries", dismissed)
        except Exception as exc:
            log.warning("DLQ maintenance loop failed: %s", exc)
