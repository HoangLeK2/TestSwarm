"""Aggregate execution outcomes into campaign terminal status (DF-T-04-007)."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import CampaignStatus, DLQStatus, ExecutionStatus
from db.models.execution import Execution
from db.models.execution_dlq import ExecutionDLQ
from services.campaign.lifecycle import TransitionResult, apply_campaign_transition
from services.campaign.errors import CampaignNotFoundError

_ACTIVE_EXECUTION = frozenset(
    {
        ExecutionStatus.PENDING.value,
        ExecutionStatus.RUNNING.value,
        ExecutionStatus.PAUSED.value,
    }
)
_OPEN_DLQ = frozenset({DLQStatus.PENDING.value, DLQStatus.RETRYING.value})
_AGGREGATOR_ELIGIBLE = frozenset(
    {
        CampaignStatus.RUNNING,
        CampaignStatus.PAUSED,
    }
)


async def _execution_status_counts(
    db: AsyncSession,
    campaign_id: str,
) -> dict[str, int] | None:
    """Single grouped query instead of loading all execution rows."""
    result = await db.execute(
        select(Execution.status, func.count())
        .where(Execution.campaign_id == campaign_id)
        .group_by(Execution.status)
    )
    rows = result.all()
    if not rows:
        return None
    return {status: int(count) for status, count in rows}


async def _open_dlq_count_for_campaign(db: AsyncSession, campaign_id: str) -> int:
    """Count open DLQ rows via join — avoids large execution_id IN (...) lists."""
    result = await db.execute(
        select(func.count())
        .select_from(ExecutionDLQ)
        .join(Execution, ExecutionDLQ.execution_id == Execution.id)
        .where(
            Execution.campaign_id == campaign_id,
            ExecutionDLQ.status.in_(tuple(_OPEN_DLQ)),
        )
    )
    return int(result.scalar_one())


def compute_terminal_from_counts(
    *,
    total: int,
    active_count: int,
    completed_count: int,
    open_dlq_count: int,
) -> CampaignStatus | None:
    """Pure aggregate rule — safe to unit test without DB."""
    if total <= 0 or active_count > 0:
        return None
    if open_dlq_count >= total and open_dlq_count > 0:
        return CampaignStatus.FAILED
    if open_dlq_count == 0:
        return CampaignStatus.COMPLETED
    if completed_count > 0:
        return CampaignStatus.COMPLETED
    return CampaignStatus.FAILED


def compute_terminal_campaign_status(
    executions: list[Execution],
    *,
    open_dlq_count: int,
) -> CampaignStatus | None:
    """Return completed/failed when all executions are terminal; else None."""
    if not executions:
        return None
    total = len(executions)
    active_count = sum(1 for ex in executions if ex.status in _ACTIVE_EXECUTION)
    completed_count = sum(
        1 for ex in executions if ex.status == ExecutionStatus.COMPLETED.value
    )
    return compute_terminal_from_counts(
        total=total,
        active_count=active_count,
        completed_count=completed_count,
        open_dlq_count=open_dlq_count,
    )


async def evaluate_campaign_status(
    db: AsyncSession,
    *,
    org_id: str,
    campaign_id: str,
    user_id: str | None = None,
    reason: str | None = None,
) -> TransitionResult | None:
    """Recompute campaign status from execution aggregate (running → completed/failed)."""
    from db.crud import campaign_entity as repo

    row = await repo.get_campaign_entity(db, campaign_id)
    if row is None or row.org_id != org_id:
        raise CampaignNotFoundError()

    try:
        current = CampaignStatus(row.status)
    except ValueError:
        return None

    if current in (
        CampaignStatus.CANCELLED,
        CampaignStatus.ARCHIVED,
        CampaignStatus.DRAFT,
        CampaignStatus.SCHEDULED,
        CampaignStatus.IDLE,
        CampaignStatus.COMPLETED,
        CampaignStatus.FAILED,
    ):
        return None
    if current not in _AGGREGATOR_ELIGIBLE:
        return None

    status_counts = await _execution_status_counts(db, campaign_id)
    if status_counts is None:
        return None

    total = sum(status_counts.values())
    active_count = sum(status_counts.get(s, 0) for s in _ACTIVE_EXECUTION)
    if active_count > 0:
        return None

    completed_count = status_counts.get(ExecutionStatus.COMPLETED.value, 0)
    open_dlq = await _open_dlq_count_for_campaign(db, campaign_id)
    target = compute_terminal_from_counts(
        total=total,
        active_count=active_count,
        completed_count=completed_count,
        open_dlq_count=open_dlq,
    )
    if target is None:
        return None

    agg_reason = reason
    if target == CampaignStatus.FAILED and not agg_reason:
        agg_reason = (
            "all_executions_dlq_open" if open_dlq >= total else "executions_failed"
        )

    return await apply_campaign_transition(
        db,
        row,
        target,
        org_id=org_id,
        user_id=user_id,
        reason=agg_reason,
    )
