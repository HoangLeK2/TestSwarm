"""Dead detection worker — RECONNECTING → DEAD when past tenant threshold (DF-T-02-005)."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import AsyncSessionLocal
from db.models.enums import DeviceFsmState
from db.models.tenant_settings import DEFAULT_DEAD_THRESHOLD_SEC
from services.device_state.service import (
    ApplyOutcome,
    DEAD_DETECTION_INTERVAL_SEC,
    DEAD_DETECTION_SCAN_LIMIT,
    DeviceStateService,
    list_stale_reconnecting_candidates,
    refresh_device_state_gauges,
)
from tenancy.context import get_current_org_id, tenant_context

log = logging.getLogger(__name__)

_service = DeviceStateService()

# Cluster-wide singleton worker lock (PostgreSQL advisory lock key).
DEAD_DETECTION_ADVISORY_LOCK_KEY = 90205005


async def _try_advisory_lock(db: AsyncSession) -> bool:
    if db.get_bind().dialect.name != "postgresql":
        return True
    result = await db.execute(
        text("SELECT pg_try_advisory_lock(:key)"),
        {"key": DEAD_DETECTION_ADVISORY_LOCK_KEY},
    )
    return bool(result.scalar())


async def _advisory_unlock(db: AsyncSession) -> None:
    if db.get_bind().dialect.name != "postgresql":
        return
    await db.execute(
        text("SELECT pg_advisory_unlock(:key)"),
        {"key": DEAD_DETECTION_ADVISORY_LOCK_KEY},
    )


async def _orgs_with_stale_reconnecting(db: AsyncSession) -> list[str]:
    """Distinct org_ids with RECONNECTING devices past dead threshold (raw SQL)."""
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        result = await db.execute(
            text(
                """
                SELECT DISTINCT d.org_id
                FROM device_states s
                JOIN devices d ON d.id = s.device_id
                LEFT JOIN tenant_settings ts ON ts.org_id = d.org_id
                WHERE s.state = :reconnecting
                  AND s.reconnecting_since IS NOT NULL
                  AND d.org_id IS NOT NULL
                  AND s.reconnecting_since <= timezone('UTC', now()) - make_interval(
                    0, 0, 0, 0, 0, 0, COALESCE(ts.dead_threshold_sec, :default_sec)
                  )
                """
            ),
            {
                "reconnecting": DeviceFsmState.RECONNECTING.value,
                "default_sec": DEFAULT_DEAD_THRESHOLD_SEC,
            },
        )
        return [row[0] for row in result.all() if row[0]]

    result = await db.execute(
        text(
            """
            SELECT DISTINCT d.org_id
            FROM device_states s
            JOIN devices d ON d.id = s.device_id
            WHERE s.state = :reconnecting
              AND s.reconnecting_since IS NOT NULL
              AND d.org_id IS NOT NULL
            """
        ),
        {"reconnecting": DeviceFsmState.RECONNECTING.value},
    )
    return [row[0] for row in result.all() if row[0]]


async def _run_dead_detection_batches(db: AsyncSession) -> int:
    """Process stale RECONNECTING devices until the current tenant batch is drained."""
    total_marked = 0
    while True:
        batch_marked, batch_size = await _run_dead_detection_batch(db)
        total_marked += batch_marked
        await db.commit()
        if batch_size == 0:
            break
        if batch_size < DEAD_DETECTION_SCAN_LIMIT:
            break
        if batch_marked == 0:
            break
    return total_marked


async def _run_dead_detection_batch(db: AsyncSession) -> tuple[int, int]:
    """Mark one batch of stale RECONNECTING devices DEAD.

    Returns ``(marked_dead_count, stale_candidate_count)``.
    """
    marked = 0
    stale_candidates = await list_stale_reconnecting_candidates(
        db, limit=DEAD_DETECTION_SCAN_LIMIT
    )
    for candidate in stale_candidates:
        event_id = f"dead-{candidate.snapshot.device_id}-{uuid.uuid4().hex[:12]}"
        result = await _service.mark_dead_reconnect_timeout(
            db,
            candidate.snapshot.device_id,
            owner_user_id=candidate.user_id,
            device_serial=candidate.serial,
            event_id=event_id,
        )
        if result.outcome == ApplyOutcome.APPLIED:
            marked += 1
    return marked, len(stale_candidates)


async def run_dead_detection_once() -> int:
    """Scan stale RECONNECTING devices and mark DEAD when past org threshold.

    Uses a PostgreSQL advisory lock so only one API replica runs a scan at a
    time. Commits after each batch to shorten row-lock duration.
    """
    total_marked = 0
    async with AsyncSessionLocal() as db:
        if not await _try_advisory_lock(db):
            log.debug("dead_detection skipped: advisory lock held by peer")
            return 0
        try:
            if get_current_org_id() is None:
                for org_id in await _orgs_with_stale_reconnecting(db):
                    with tenant_context(org_id):
                        total_marked += await _run_dead_detection_batches(db)
            else:
                total_marked = await _run_dead_detection_batches(db)
            if total_marked > 0:
                await refresh_device_state_gauges(db)
                await db.commit()
        except Exception:
            await db.rollback()
            raise
        finally:
            await _advisory_unlock(db)
    if total_marked:
        log.info("dead_detection marked %s device(s) DEAD", total_marked)
    return total_marked


async def dead_detection_loop(
    *,
    interval_seconds: int | None = None,
) -> None:
    """Background loop — scan every 60s by default."""
    interval = interval_seconds if interval_seconds is not None else DEAD_DETECTION_INTERVAL_SEC
    while True:
        started = time.perf_counter()
        try:
            await run_dead_detection_once()
        except Exception as exc:
            log.warning("dead_detection scan failed: %s", exc)
        elapsed = time.perf_counter() - started
        await asyncio.sleep(max(0.0, interval - elapsed))
