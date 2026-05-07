from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func, select

from api.deps import CurrentUser, DB
from api.schemas.analytics import ActivityLogListOut, ActivityLogOut
from db.models.activity import ActivityLog

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/activity", response_model=ActivityLogListOut)
async def list_activity(
    db: DB,
    user: CurrentUser,
    action: str | None = None,
    device_serial: str | None = None,
    offset: int = 0,
    limit: int = 50,
):
    safe_limit = min(max(limit, 1), 100)
    q = select(ActivityLog).where(ActivityLog.user_id == user.id)
    count_q = select(func.count(ActivityLog.id)).where(ActivityLog.user_id == user.id)

    if action:
        q = q.where(ActivityLog.action == action)
        count_q = count_q.where(ActivityLog.action == action)
    if device_serial:
        q = q.where(ActivityLog.device_serial == device_serial)
        count_q = count_q.where(ActivityLog.device_serial == device_serial)

    total = (await db.execute(count_q)).scalar() or 0
    rows = (
        await db.execute(
            q.order_by(ActivityLog.created_at.desc())
            .offset(max(offset, 0))
            .limit(safe_limit)
        )
    ).scalars().all()

    return ActivityLogListOut(
        total=total,
        offset=max(offset, 0),
        limit=safe_limit,
        activities=[ActivityLogOut.model_validate(row) for row in rows],
    )
