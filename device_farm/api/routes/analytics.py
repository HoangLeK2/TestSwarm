from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from api.deps import CurrentUser, DB, require_permission
from api.org_scope import activity_log_scope, data_owner_user_id
from api.schemas.analytics import ActivityLogListOut
from db.models.activity import ActivityLog
from services.activity_presenter import present_activity_logs

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get(
    "/activity",
    response_model=ActivityLogListOut,
    dependencies=[Depends(require_permission("analytics", "read"))],
)
async def list_activity(
    db: DB,
    user: CurrentUser,
    action: str | None = None,
    device_serial: str | None = None,
    offset: int = 0,
    limit: int = 50,
):
    safe_limit = min(max(limit, 1), 100)
    scope = await activity_log_scope(db, user)
    q = select(ActivityLog).where(scope)
    count_q = select(func.count(ActivityLog.id)).where(scope)

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
        activities=await present_activity_logs(db, list(rows)),
    )
