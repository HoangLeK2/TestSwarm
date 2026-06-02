"""CRUD for execution_artifacts (Epic 06)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.content import ExecutionArtifact


async def create_execution_artifact(db: AsyncSession, **kwargs: Any) -> ExecutionArtifact:
    row = ExecutionArtifact(**kwargs)
    db.add(row)
    await db.flush()
    return row


async def get_execution_artifact(db: AsyncSession, artifact_id: str) -> ExecutionArtifact | None:
    return await db.get(ExecutionArtifact, artifact_id)


async def list_execution_artifact_rows(
    db: AsyncSession,
    execution_id: str,
    *,
    include_deleted: bool = False,
) -> list[ExecutionArtifact]:
    stmt = select(ExecutionArtifact).where(ExecutionArtifact.execution_id == execution_id)
    if not include_deleted:
        stmt = stmt.where(ExecutionArtifact.object_deleted.is_(False))
    stmt = stmt.order_by(ExecutionArtifact.step_index, ExecutionArtifact.captured_at)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def mark_artifact_object_deleted(
    db: AsyncSession,
    artifact_id: str,
    *,
    deleted_at: datetime | None = None,
) -> bool:
    ts = deleted_at or datetime.now(timezone.utc)
    result = await db.execute(
        update(ExecutionArtifact)
        .where(ExecutionArtifact.id == artifact_id, ExecutionArtifact.object_deleted.is_(False))
        .values(object_deleted=True, object_deleted_at=ts)
    )
    return result.rowcount > 0
