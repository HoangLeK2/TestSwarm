"""Capacity / DB-pool probe activities for Temporal load tests."""
from __future__ import annotations

import asyncio
import time
from collections import Counter
from contextvars import ContextVar
from typing import Any

from temporalio import activity


_finalize_sql_stats: ContextVar[dict[str, Any] | None] = ContextVar(
    "campaign_pipeline_finalize_sql_stats",
    default=None,
)


def record_finalize_probe_sql_before(context: Any, statement: Any) -> None:
    """Attribute one SQL statement to the current benchmark finalization task."""
    stats = _finalize_sql_stats.get()
    if stats is None:
        return
    context._campaign_pipeline_finalize_sql_started = time.perf_counter()
    normalized = " ".join(str(statement).split())
    verb = normalized.split(None, 1)[0].upper() if normalized else "OTHER"
    stats["count"] += 1
    stats["by_verb"][verb] += 1
    stats["statements"][normalized[:400]] += 1


def record_finalize_probe_sql_after(context: Any) -> None:
    """Record SQL duration for the current benchmark finalization task."""
    stats = _finalize_sql_stats.get()
    if stats is None:
        return
    started = getattr(context, "_campaign_pipeline_finalize_sql_started", None)
    if started is not None:
        stats["duration_s"] += max(0.0, time.perf_counter() - started)


@activity.defn(name="capacity_probe")
async def capacity_probe(delay_ms: int = 50) -> dict:
    """Sleep briefly to occupy an activity slot without touching devices/DB."""
    delay = max(0, int(delay_ms))
    if delay:
        await asyncio.sleep(delay / 1000.0)
    info = activity.info()
    schedule_to_start_ms = max(
        0.0,
        (info.started_time - info.current_attempt_scheduled_time).total_seconds()
        * 1000.0,
    )
    return {
        "ok": True,
        "delay_ms": delay,
        "activity_id": info.activity_id,
        "attempt": info.attempt,
        "task_queue": info.task_queue,
        "schedule_to_start_ms": schedule_to_start_ms,
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


@activity.defn(name="finalize_campaign_probe")
async def finalize_campaign_probe(inp: dict) -> dict:
    """Measure queue and runtime latency around the real finalization activity."""
    info = activity.info()
    schedule_to_start_ms = max(
        0.0,
        (info.started_time - info.current_attempt_scheduled_time).total_seconds()
        * 1000.0,
    )
    started = time.perf_counter()
    sql_stats: dict[str, Any] = {
        "count": 0,
        "duration_s": 0.0,
        "by_verb": Counter(),
        "statements": Counter(),
    }
    token = _finalize_sql_stats.set(sql_stats)

    from temporal.activities import DeviceActivities

    try:
        await DeviceActivities().finalize_campaign(inp)
    finally:
        _finalize_sql_stats.reset(token)
    return {
        "schedule_to_start_ms": schedule_to_start_ms,
        "duration_ms": max(0.0, (time.perf_counter() - started) * 1000.0),
        "sql_count": int(sql_stats["count"]),
        "sql_duration_ms": max(0.0, float(sql_stats["duration_s"]) * 1000.0),
        "sql_by_verb": dict(sql_stats["by_verb"]),
        "sql_statements": dict(sql_stats["statements"]),
    }
