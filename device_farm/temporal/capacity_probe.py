"""Capacity / DB-pool probe activities for Temporal load tests."""
from __future__ import annotations

import asyncio

from temporalio import activity


@activity.defn(name="capacity_probe")
async def capacity_probe(delay_ms: int = 50) -> dict:
    """Sleep briefly to occupy an activity slot without touching devices/DB."""
    delay = max(0, int(delay_ms))
    if delay:
        await asyncio.sleep(delay / 1000.0)
    info = activity.info()
    return {
        "ok": True,
        "delay_ms": delay,
        "activity_id": info.activity_id,
        "attempt": info.attempt,
        "task_queue": info.task_queue,
    }


@activity.defn(name="db_hold_probe")
async def db_hold_probe(hold_ms: int = 500) -> dict:
    """Hold an activity DB connection — reproduces QueuePool pressure like finalize_campaign."""
    from sqlalchemy import text

    from db.database import activity_session

    hold = max(0, int(hold_ms))
    async with activity_session() as db:
        await db.execute(text("SELECT 1"))
        if hold:
            await asyncio.sleep(hold / 1000.0)
    info = activity.info()
    return {
        "ok": True,
        "hold_ms": hold,
        "activity_id": info.activity_id,
        "attempt": info.attempt,
        "task_queue": info.task_queue,
    }
