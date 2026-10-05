"""Evidence manifest registration with verified-storage and retention semantics."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models.ai_device_lab import RunAttempt
from db.models.ai_device_lab_delivery import EvidenceItem
from tenancy.context import tenant_context

log = logging.getLogger(__name__)


class EvidenceInvariantError(ValueError):
    pass


class PrivateEvidenceStorage(Protocol):
    async def delete_private(self, *, object_key: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class ConfiguredMinioPrivateEvidenceStorage:
    """MinIO deletion adapter enabled only after private storage is confirmed."""

    confirmation_env: str = "AI_DEVICE_LAB_PRIVATE_EVIDENCE_STORAGE_CONFIRMED"

    async def delete_private(self, *, object_key: str) -> bool:
        if os.getenv(self.confirmation_env, "").strip().lower() not in {
            "1",
            "true",
            "yes",
        }:
            return False
        from services import minio_store

        if not minio_store.enabled():
            return False
        return await asyncio.to_thread(minio_store.delete_object, object_key)


@dataclass(frozen=True, slots=True)
class EvidenceExpiryResult:
    attempted: int
    deleted: int


@dataclass(frozen=True, slots=True)
class RegisterEvidence:
    org_id: str
    run_attempt_id: str
    step_path: str
    step_attempt_index: int
    kind: str
    captured_at: datetime
    retention_until: datetime
    object_key: str | None = None
    content_type: str | None = None
    checksum_sha256: str | None = None
    capture_error_code: str | None = None
    storage_verified: bool = False


async def register_evidence(
    db: AsyncSession, command: RegisterEvidence
) -> EvidenceItem:
    attempt = (
        await db.execute(
            select(RunAttempt).where(
                RunAttempt.id == command.run_attempt_id,
                RunAttempt.org_id == command.org_id,
            )
        )
    ).scalar_one_or_none()
    if attempt is None:
        raise EvidenceInvariantError("run attempt not found")
    available = bool(
        command.storage_verified and command.object_key and command.checksum_sha256
    )
    status = "available" if available else "missing"
    if command.kind == "video" and command.capture_error_code == "UNSUPPORTED":
        status = "unsupported"
    item = EvidenceItem(
        org_id=command.org_id,
        service_campaign_id=attempt.service_campaign_id,
        run_attempt_id=attempt.id,
        execution_id=attempt.execution_id,
        step_path=command.step_path,
        step_attempt_index=command.step_attempt_index,
        kind=command.kind,
        object_key=command.object_key if available else None,
        content_type=command.content_type if available else None,
        captured_at=command.captured_at,
        checksum_sha256=command.checksum_sha256 if available else None,
        capture_error_code=command.capture_error_code,
        status=status,
        retention_until=command.retention_until,
    )
    db.add(item)
    await db.flush()
    return item


async def expire_evidence(
    db: AsyncSession,
    *,
    now: datetime,
    storage: PrivateEvidenceStorage | None = None,
    batch_size: int = 100,
    delete_concurrency: int = 8,
) -> int:
    """Delete expired private objects, then persist tombstones for confirmed deletes."""
    result = await expire_evidence_batch(
        db,
        now=now,
        storage=storage,
        batch_size=batch_size,
        delete_concurrency=delete_concurrency,
    )
    return result.deleted


async def expire_evidence_batch(
    db: AsyncSession,
    *,
    now: datetime,
    storage: PrivateEvidenceStorage | None = None,
    batch_size: int = 100,
    delete_concurrency: int = 8,
) -> EvidenceExpiryResult:
    if not 1 <= batch_size <= 1_000:
        raise EvidenceInvariantError("batch_size must be between 1 and 1000")
    if not 1 <= delete_concurrency <= 32:
        raise EvidenceInvariantError("delete_concurrency must be between 1 and 32")

    candidates = list(
        (
            await db.execute(
                select(EvidenceItem)
                .where(
                    EvidenceItem.status == "available",
                    EvidenceItem.retention_until <= now,
                    EvidenceItem.pinned_by_report.is_(False),
                )
                .order_by(EvidenceItem.retention_until, EvidenceItem.id)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
        ).scalars()
    )
    adapter = storage or ConfiguredMinioPrivateEvidenceStorage()
    semaphore = asyncio.Semaphore(delete_concurrency)

    async def delete(item: EvidenceItem) -> bool:
        if not item.object_key:
            return False
        try:
            async with semaphore:
                return await adapter.delete_private(object_key=item.object_key)
        except Exception:  # noqa: BLE001 - storage adapters must fail closed for retry
            return False

    deleted = await asyncio.gather(*(delete(item) for item in candidates))
    deleted_count = 0
    for item, was_deleted in zip(candidates, deleted, strict=True):
        if not was_deleted:
            continue
        item.status = "expired"
        item.deleted_at = now
        deleted_count += 1
    await db.flush()
    return EvidenceExpiryResult(attempted=len(candidates), deleted=deleted_count)


async def run_evidence_retention_batch(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
    storage: PrivateEvidenceStorage | None = None,
    batch_size: int = 100,
    delete_concurrency: int = 8,
) -> EvidenceExpiryResult:
    """Run one bounded cross-tenant cleanup pass with tenant isolation enabled."""
    if not 1 <= batch_size <= 1_000:
        raise EvidenceInvariantError("batch_size must be between 1 and 1000")
    if not 1 <= delete_concurrency <= 32:
        raise EvidenceInvariantError("delete_concurrency must be between 1 and 32")

    observed_at = now or datetime.now(UTC)
    async with session_factory() as discovery_db:
        result = await discovery_db.execute(
            text(
                """
                SELECT org_id, MIN(retention_until) AS oldest_retention
                FROM evidence_items
                WHERE status = 'available'
                  AND pinned_by_report IS FALSE
                  AND retention_until <= :now
                GROUP BY org_id
                ORDER BY oldest_retention, org_id
                LIMIT :org_limit
                """
            ),
            {"now": observed_at, "org_limit": min(batch_size, 100)},
        )
        org_ids = [str(row[0]) for row in result]

    adapter = storage or ConfiguredMinioPrivateEvidenceStorage()
    attempted = 0
    deleted = 0
    for org_id in org_ids:
        remaining = batch_size - attempted
        if remaining <= 0:
            break
        with tenant_context(org_id):
            async with session_factory() as db:
                outcome = await expire_evidence_batch(
                    db,
                    now=observed_at,
                    storage=adapter,
                    batch_size=remaining,
                    delete_concurrency=delete_concurrency,
                )
                await db.commit()
        attempted += outcome.attempted
        deleted += outcome.deleted
    return EvidenceExpiryResult(attempted=attempted, deleted=deleted)


def evidence_retention_interval_seconds() -> int:
    raw = os.getenv("AI_DEVICE_LAB_EVIDENCE_RETENTION_INTERVAL_SECONDS", "3600")
    try:
        return max(300, min(86_400, int(raw)))
    except ValueError:
        return 3600


async def evidence_retention_loop() -> None:
    """Run bounded cleanup passes until the application lifecycle cancels the task."""
    from db import database
    from web.metrics import (
        ai_device_lab_evidence_deleted_total,
        ai_device_lab_evidence_retention_duration_seconds,
        ai_device_lab_evidence_retention_runs_total,
    )

    interval = evidence_retention_interval_seconds()
    log.info("AI Device Lab evidence retention loop started (interval=%ss)", interval)
    while True:
        started = time.perf_counter()
        status = "success"
        try:
            if database.schema_init_ok is False:
                status = "schema_unavailable"
            else:
                outcome = await run_evidence_retention_batch(database.AsyncSessionLocal)
                if outcome.deleted:
                    ai_device_lab_evidence_deleted_total.inc(outcome.deleted)
                    log.info(
                        "AI Device Lab evidence retention deleted=%s attempted=%s",
                        outcome.deleted,
                        outcome.attempted,
                    )
        except Exception as exc:  # noqa: BLE001 - background worker must remain alive
            status = "error"
            log.warning("AI Device Lab evidence retention pass failed: %s", exc)
        finally:
            ai_device_lab_evidence_retention_runs_total.labels(status=status).inc()
            ai_device_lab_evidence_retention_duration_seconds.observe(
                time.perf_counter() - started
            )
        await asyncio.sleep(interval)
