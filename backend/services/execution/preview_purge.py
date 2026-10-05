"""Auto-purge stale preview artifacts (DF-T-04-018)."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update

from db.models.content import ContentItem
from db.models.enums import ExecutionKind
from db.models.execution import Execution
from db.models.execution_step import ExecutionStep
from services.execution.preview_collection import preview_collection_name

log = logging.getLogger(__name__)


def preview_retention_days() -> int:
    raw = os.environ.get("DEVICE_FARM_PREVIEW_RETENTION_DAYS", "7")
    try:
        return max(1, min(365, int(raw)))
    except ValueError:
        return 7


def preview_purge_interval_seconds() -> int:
    raw = os.environ.get("DEVICE_FARM_PREVIEW_PURGE_INTERVAL_SECONDS", "3600")
    try:
        return max(300, min(86_400, int(raw)))
    except ValueError:
        return 3600


async def purge_stale_preview_artifacts(db, *, retention_days: int | None = None) -> int:
    """Delete preview content + clear step artifacts for executions older than retention."""
    days = retention_days if retention_days is not None else preview_retention_days()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    result = await db.execute(
        select(Execution).where(
            Execution.kind == ExecutionKind.PREVIEW.value,
            Execution.created_at < cutoff,
        )
    )
    executions = list(result.scalars().all())
    purged = 0

    for execution in executions:
        meta = dict(execution.meta or {})
        if meta.get("artifacts_purged"):
            continue
        org_id = execution.org_id or ""
        collection = preview_collection_name(org_id) if org_id else None

        if collection:
            await db.execute(
                delete(ContentItem).where(
                    ContentItem.execution_id == execution.id,
                    ContentItem.collection == collection,
                )
            )

        await db.execute(
            update(ExecutionStep)
            .where(ExecutionStep.execution_id == execution.id)
            .values(artifacts_json=[])
        )

        meta["artifacts_purged"] = True
        meta["artifacts_purged_at"] = datetime.now(timezone.utc).isoformat()
        execution.meta = meta
        purged += 1

    if purged:
        await db.flush()
    return purged


async def preview_artifact_purge_loop() -> None:
    """Background loop: purge preview artifacts older than retention window."""
    from db.database import AsyncSessionLocal

    interval = preview_purge_interval_seconds()
    retention = preview_retention_days()
    log.info(
        "Preview artifact purge loop started (interval=%ss, retention=%sd)",
        interval,
        retention,
    )

    while True:
        await asyncio.sleep(interval)
        try:
            async with AsyncSessionLocal() as db:
                count = await purge_stale_preview_artifacts(db, retention_days=retention)
                await db.commit()
            if count:
                log.info("Preview purge removed artifacts for %s execution(s)", count)
        except Exception as exc:
            log.warning("Preview artifact purge loop failed: %s", exc)
