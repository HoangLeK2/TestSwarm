"""CRUD for execution_steps subtable (DF-T-04-010 / DF-T-04-014)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.crud.execution import get_execution
from db.models.execution_step import ExecutionStep
from db.models.utils import _now, _uuid


async def upsert_execution_step(
    db: AsyncSession,
    *,
    execution_id: str,
    step_index: int,
    status: str,
    step_id: str | None = None,
    step_type: str | None = None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    duration_ms: float | None = None,
    error_json: dict[str, Any] | None = None,
    effective_config_json: dict[str, Any] | None = None,
    artifacts_json: list | None = None,
    attempts_json: list | None = None,
    marked_ignored: bool = False,
    message: str | None = None,
    device_id: str | None = None,
    org_id: str | None = None,
) -> ExecutionStep:
    result = await db.execute(
        select(ExecutionStep).where(
            ExecutionStep.execution_id == execution_id,
            ExecutionStep.step_index == step_index,
        )
    )
    row = result.scalar_one_or_none()
    now = _now()

    if row is None:
        if not org_id:
            execution = await get_execution(db, execution_id)
            if execution is None:
                raise ValueError(f"execution not found: {execution_id}")
            org_id = execution.org_id
        row = ExecutionStep(
            id=_uuid(),
            org_id=org_id,
            execution_id=execution_id,
            device_id=device_id,
            step_index=step_index,
            step_id=step_id,
            step_type=step_type,
            status=status,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            error_json=error_json or {},
            effective_config_json=effective_config_json or {},
            artifacts_json=artifacts_json or [],
            attempts_json=attempts_json or [],
            marked_ignored=marked_ignored,
            message=message,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        if status != "running":
            row.status = status
        elif row.ended_at is None or (started_at is not None and started_at > row.ended_at):
            # A running write that was scheduled before the step finished can
            # land after it (executor queues both on the device loop), which
            # would pin the row at "running" forever. A genuine re-run of the
            # same index starts after the previous attempt ended — allow that.
            row.status = status
        if step_id is not None:
            row.step_id = step_id
        if device_id is not None:
            # The first write for a step is now the "running" row, which has no
            # device yet, so every later write is an UPDATE — without this the
            # device would be dropped and the column would go back to empty.
            row.device_id = device_id
        if step_type is not None:
            row.step_type = step_type
        if started_at is not None:
            row.started_at = started_at
        if ended_at is not None:
            row.ended_at = ended_at
        if duration_ms is not None:
            row.duration_ms = duration_ms
        if error_json is not None:
            row.error_json = error_json
        if effective_config_json is not None:
            row.effective_config_json = effective_config_json
        if artifacts_json is not None:
            incoming = list(artifacts_json or [])
            existing = list(row.artifacts_json or [])
            if incoming or not existing:
                row.artifacts_json = incoming
        if attempts_json is not None:
            row.attempts_json = attempts_json
        if status != "running":
            # The running write knows nothing about error policy; it must not
            # reset a flag the finished write already set.
            row.marked_ignored = marked_ignored
        if message is not None:
            row.message = message
        row.updated_at = now

    await db.flush()
    return row


async def update_execution_step_artifacts(
    db: AsyncSession,
    *,
    execution_id: str,
    step_index: int,
    artifacts_json: list,
) -> Optional[ExecutionStep]:
    result = await db.execute(
        select(ExecutionStep).where(
            ExecutionStep.execution_id == execution_id,
            ExecutionStep.step_index == step_index,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    incoming = list(artifacts_json or [])
    existing = list(row.artifacts_json or [])
    if incoming or not existing:
        row.artifacts_json = incoming
    row.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return row


async def get_execution_step(
    db: AsyncSession,
    execution_id: str,
    step_index: int,
) -> Optional[ExecutionStep]:
    result = await db.execute(
        select(ExecutionStep).where(
            ExecutionStep.execution_id == execution_id,
            ExecutionStep.step_index == step_index,
        )
    )
    return result.scalar_one_or_none()


async def list_execution_steps(
    db: AsyncSession,
    execution_id: str,
) -> list[ExecutionStep]:
    result = await db.execute(
        select(ExecutionStep)
        .where(ExecutionStep.execution_id == execution_id)
        .order_by(ExecutionStep.step_index)
    )
    return list(result.scalars().all())


async def bulk_upsert_execution_steps(
    db: AsyncSession,
    rows: list[dict[str, Any]],
) -> list[ExecutionStep]:
    out: list[ExecutionStep] = []
    for payload in rows:
        out.append(await upsert_execution_step(db, **payload))
    return out


__all__ = [
    "upsert_execution_step",
    "update_execution_step_artifacts",
    "get_execution_step",
    "list_execution_steps",
    "bulk_upsert_execution_steps",
]
