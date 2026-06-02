"""Artifact retention policy + cleanup job (DF-T-06-011)."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.content import ExecutionArtifact
from db.models.execution import Execution
from db.models.enums import ExecutionStatus

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetentionPolicy:
    execution_success_days: int = 30
    execution_failed_days: int = 90
    execution_pinned_days: int = -1
    direct_extract_days: int = 7


def load_retention_policy() -> RetentionPolicy:
    def _days(name: str, default: int) -> int:
        raw = os.environ.get(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    return RetentionPolicy(
        execution_success_days=_days("ARTIFACT_RETENTION_SUCCESS_DAYS", 30),
        execution_failed_days=_days("ARTIFACT_RETENTION_FAILED_DAYS", 90),
        execution_pinned_days=_days("ARTIFACT_RETENTION_PINNED_DAYS", -1),
        direct_extract_days=_days("ARTIFACT_RETENTION_DIRECT_DAYS", 7),
    )


def retention_interval_seconds() -> int:
    raw = os.environ.get("ARTIFACT_RETENTION_INTERVAL_SECONDS", "86400")
    try:
        return max(3600, min(604_800, int(raw)))
    except ValueError:
        return 86400


def _retention_days_for(execution: Execution, artifact: ExecutionArtifact, policy: RetentionPolicy) -> int | None:
    if execution.pinned_at is not None:
        return None if policy.execution_pinned_days < 0 else policy.execution_pinned_days
    if artifact.retention_class == "direct_extract":
        return policy.direct_extract_days
    if execution.status in {ExecutionStatus.FAILED.value, ExecutionStatus.DLQ_OPEN.value}:
        return policy.execution_failed_days
    return policy.execution_success_days


class ArtifactRetentionService:
    def __init__(self, policy: RetentionPolicy | None = None) -> None:
        self._policy = policy or load_retention_policy()

    async def evaluate_and_cleanup(
        self,
        db: AsyncSession,
        *,
        batch_size: int = 500,
        dry_run: bool = False,
    ) -> dict[str, int]:
        now = datetime.now(timezone.utc)
        deleted = 0
        bytes_freed = 0
        started = time.perf_counter()

        stmt = (
            select(ExecutionArtifact, Execution)
            .join(Execution, Execution.id == ExecutionArtifact.execution_id)
            .where(ExecutionArtifact.object_deleted.is_(False))
            .limit(batch_size)
        )
        rows = (await db.execute(stmt)).all()

        for artifact, execution in rows:
            days = _retention_days_for(execution, artifact, self._policy)
            if days is None:
                continue
            cutoff = now - timedelta(days=days)
            if artifact.captured_at > cutoff:
                continue
            if dry_run:
                deleted += 1
                bytes_freed += int(artifact.size_bytes or 0)
                continue
            if artifact.object_key:
                from services import minio_store

                if minio_store.enabled():
                    minio_store.delete_object(artifact.object_key)
            await db.execute(
                update(ExecutionArtifact)
                .where(ExecutionArtifact.id == artifact.id)
                .values(object_deleted=True, object_deleted_at=now)
            )
            deleted += 1
            bytes_freed += int(artifact.size_bytes or 0)

        if deleted and not dry_run:
            await db.flush()

        duration = time.perf_counter() - started
        try:
            from web.metrics import (
                artifact_cleanup_bytes_freed,
                artifact_cleanup_deleted_total,
                artifact_cleanup_duration_seconds,
            )

            if not dry_run and deleted:
                artifact_cleanup_deleted_total.inc(deleted)
                artifact_cleanup_bytes_freed.inc(bytes_freed)
                artifact_cleanup_duration_seconds.observe(duration)
        except Exception:
            pass

        log.info(
            "artifact retention cleanup deleted=%s bytes_freed=%s dry_run=%s",
            deleted,
            bytes_freed,
            dry_run,
        )
        return {"deleted": deleted, "bytes_freed": bytes_freed, "dry_run": int(dry_run)}


async def artifact_retention_loop() -> None:
    from db.database import AsyncSessionLocal, schema_init_ok

    interval = retention_interval_seconds()
    service = ArtifactRetentionService()
    log.info("Artifact retention loop started (interval=%ss)", interval)
    while True:
        await asyncio.sleep(interval)
        if schema_init_ok is False:
            log.debug("artifact retention skipped — DB schema not ready")
            continue
        try:
            async with AsyncSessionLocal() as db:
                await service.evaluate_and_cleanup(db, batch_size=10_000)
                await db.commit()
        except Exception as exc:
            msg = str(exc)
            if "execution_artifacts" in msg and "does not exist" in msg:
                log.debug("artifact retention skipped — execution_artifacts not migrated yet")
            else:
                log.warning("artifact retention loop failed: %s", exc)
