from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from datetime import datetime, timezone

from sqlalchemy import func, or_, select

from api.deps import CurrentUser, DB, require_permission
from api.org_scope import data_owner_user_id
from db import crud as repo
from tenancy.context import get_current_org_id
from api.schemas.notification import (
    NotificationChannelCreate,
    NotificationChannelOut,
    NotificationChannelPatch,
    NotificationChannelTestRequest,
    NotificationListOut,
    NotificationOut,
    TestNotificationOut,
    UnreadCountOut,
)
from db.models.notification import Notification, NotificationChannel
from services.notification_service import DEFAULT_EVENTS, NotificationService

router = APIRouter(tags=["notifications"])


def _notification_service(request: Request) -> NotificationService:
    svc = getattr(request.app.state, "notification_service", None)
    if isinstance(svc, NotificationService):
        return svc
    return NotificationService(getattr(request.app.state, "ws_manager", None))


async def _resolve_org_id(db: DB, user: CurrentUser) -> str:
    org_id = getattr(user, "org_id", None) or get_current_org_id()
    if not org_id:
        org_id = await repo.get_user_org_id(db, user.id)
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization context required",
        )
    return org_id


async def _get_channel_or_404(db: DB, channel_id: str, user_id: str) -> NotificationChannel:
    result = await db.execute(
        select(NotificationChannel).where(
            NotificationChannel.id == channel_id,
            NotificationChannel.user_id == user_id,
        )
    )
    channel = result.scalar_one_or_none()
    if channel is None:
        raise HTTPException(status_code=404, detail="Notification channel not found")
    return channel


async def _get_notification_or_404(
    db: DB, notification_id: str, user: CurrentUser
) -> Notification:
    stmt = select(Notification).where(Notification.id == notification_id)
    org_id = getattr(user, "org_id", None)
    if org_id:
        stmt = stmt.where(
            Notification.org_id == org_id,
            or_(Notification.user_id == user.id, Notification.user_id.is_(None)),
        )
    else:
        owner_id = data_owner_user_id(user)
        if owner_id:
            stmt = stmt.where(Notification.user_id == owner_id)
    result = await db.execute(stmt)
    notification = result.scalar_one_or_none()
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    return notification


def _apply_notification_user_filter(stmt, user: CurrentUser):
    org_id = getattr(user, "org_id", None)
    if org_id:
        return stmt.where(
            Notification.org_id == org_id,
            or_(Notification.user_id == user.id, Notification.user_id.is_(None)),
        )
    owner_id = data_owner_user_id(user)
    if owner_id:
        return stmt.where(Notification.user_id == owner_id)
    return stmt


async def _unread_count_for_user(db: DB, user: CurrentUser) -> int:
    stmt = _apply_notification_user_filter(select(func.count(Notification.id)), user)
    stmt = stmt.where(Notification.is_read.is_(False))
    return (await db.execute(stmt)).scalar() or 0


async def _ensure_default_channel(db: DB, user: CurrentUser) -> None:
    org_id = await _resolve_org_id(db, user)
    result = await db.execute(
        select(NotificationChannel.id)
        .where(
            NotificationChannel.user_id == user.id,
            NotificationChannel.type == "in_app",
        )
        .limit(1)
    )
    if result.scalar_one_or_none():
        return
    db.add(
        NotificationChannel(
            name="Browser",
            type="in_app",
            config={},
            events=DEFAULT_EVENTS,
            is_enabled=True,
            user_id=user.id,
            org_id=org_id,
        )
    )
    await db.flush()


@router.get(
    "/notification-channels",
    response_model=list[NotificationChannelOut],
    dependencies=[Depends(require_permission("notifications", "read"))],
)
async def list_channels(db: DB, user: CurrentUser):
    await _ensure_default_channel(db, user)
    result = await db.execute(
        select(NotificationChannel)
        .where(NotificationChannel.user_id == user.id)
        .order_by(NotificationChannel.created_at.desc())
    )
    return list(result.scalars().all())


@router.post(
    "/notification-channels",
    response_model=NotificationChannelOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("notifications", "create"))],
)
async def create_channel(body: NotificationChannelCreate, db: DB, user: CurrentUser):
    org_id = await _resolve_org_id(db, user)
    channel = NotificationChannel(
        name=body.name,
        type=body.type,
        config=body.config,
        events=body.events,
        is_enabled=body.is_enabled,
        user_id=user.id,
        org_id=org_id,
    )
    db.add(channel)
    await db.flush()
    return channel


@router.patch(
    "/notification-channels/{channel_id}",
    response_model=NotificationChannelOut,
    dependencies=[Depends(require_permission("notifications", "update"))],
)
async def update_channel(
    channel_id: str,
    body: NotificationChannelPatch,
    db: DB,
    user: CurrentUser,
):
    channel = await _get_channel_or_404(db, channel_id, user.id)
    patch = body.model_dump(exclude_none=True)
    for key, value in patch.items():
        if hasattr(channel, key):
            setattr(channel, key, value)
    await db.flush()
    return channel


@router.delete(
    "/notification-channels/{channel_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("notifications", "delete"))],
)
async def delete_channel(channel_id: str, db: DB, user: CurrentUser):
    channel = await _get_channel_or_404(db, channel_id, user.id)
    await db.delete(channel)
    await db.flush()


@router.post(
    "/notification-channels/test-draft",
    response_model=TestNotificationOut,
    dependencies=[Depends(require_permission("notifications", "execute"))],
)
async def test_channel_draft(
    body: NotificationChannelTestRequest,
    request: Request,
    db: DB,
    user: CurrentUser,
):
    try:
        await _notification_service(request).send_test_draft(
            db, body.type, body.config, user.id
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TestNotificationOut(ok=True, message="Test notification sent")


@router.post(
    "/notification-channels/{channel_id}/test",
    response_model=TestNotificationOut,
    dependencies=[Depends(require_permission("notifications", "execute"))],
)
async def test_channel(
    channel_id: str,
    request: Request,
    db: DB,
    user: CurrentUser,
):
    channel = await _get_channel_or_404(db, channel_id, user.id)
    try:
        await _notification_service(request).send_test(db, channel, user.id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TestNotificationOut(ok=True, message="Test notification sent")


@router.get(
    "/notifications",
    response_model=NotificationListOut,
    dependencies=[Depends(require_permission("notifications", "read"))],
)
async def list_notifications(
    db: DB,
    user: CurrentUser,
    unread: bool | None = None,
    offset: int = 0,
    limit: int = 50,
):
    q = _apply_notification_user_filter(select(Notification), user)
    count_q = _apply_notification_user_filter(
        select(func.count(Notification.id)), user
    )
    if unread is not None:
        q = q.where(Notification.is_read.is_(not unread))
        count_q = count_q.where(Notification.is_read.is_(not unread))
    total = (await db.execute(count_q)).scalar() or 0
    rows = (
        await db.execute(
            q.order_by(Notification.is_read.asc(), Notification.created_at.desc())
            .offset(offset)
            .limit(min(max(limit, 1), 100))
        )
    ).scalars().all()
    return NotificationListOut(
        total=total,
        offset=offset,
        limit=limit,
        notifications=[NotificationOut.model_validate(row) for row in rows],
    )


@router.get(
    "/notifications/unread-count",
    response_model=UnreadCountOut,
    dependencies=[Depends(require_permission("notifications", "read"))],
)
async def unread_count(db: DB, user: CurrentUser):
    return UnreadCountOut(count=await _unread_count_for_user(db, user))


@router.patch(
    "/notifications/{notification_id}/read",
    response_model=NotificationOut,
    dependencies=[Depends(require_permission("notifications", "update"))],
)
async def mark_read(notification_id: str, db: DB, user: CurrentUser):
    notification = await _get_notification_or_404(db, notification_id, user)
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = datetime.now(timezone.utc)
    elif notification.read_at is None:
        notification.read_at = datetime.now(timezone.utc)
    await db.flush()
    return {
        **NotificationOut.model_validate(notification).model_dump(),
        "unread_count": await _unread_count_for_user(db, user),
    }


@router.post(
    "/notifications/read-all",
    response_model=UnreadCountOut,
    dependencies=[Depends(require_permission("notifications", "update"))],
)
async def mark_all_read(db: DB, user: CurrentUser):
    stmt = _apply_notification_user_filter(select(Notification), user)
    stmt = stmt.where(Notification.is_read.is_(False))
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    now = datetime.now(timezone.utc)
    for notification in rows:
        notification.is_read = True
        if notification.read_at is None:
            notification.read_at = now
    await db.flush()
    return UnreadCountOut(count=0)
