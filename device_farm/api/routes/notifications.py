from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import func, select

from api.deps import CurrentUser, DB
from api.schemas.notification import (
    NotificationChannelCreate,
    NotificationChannelOut,
    NotificationChannelPatch,
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


async def _get_notification_or_404(db: DB, notification_id: str, user_id: str) -> Notification:
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user_id,
        )
    )
    notification = result.scalar_one_or_none()
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    return notification


async def _ensure_default_channel(db: DB, user_id: str) -> None:
    result = await db.execute(
        select(NotificationChannel.id).where(
            NotificationChannel.user_id == user_id,
            NotificationChannel.type == "in_app",
        )
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
            user_id=user_id,
        )
    )
    await db.flush()


@router.get("/notification-channels", response_model=list[NotificationChannelOut])
async def list_channels(db: DB, user: CurrentUser):
    await _ensure_default_channel(db, user.id)
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
)
async def create_channel(body: NotificationChannelCreate, db: DB, user: CurrentUser):
    channel = NotificationChannel(
        name=body.name,
        type=body.type,
        config=body.config,
        events=body.events,
        is_enabled=body.is_enabled,
        user_id=user.id,
    )
    db.add(channel)
    await db.flush()
    return channel


@router.patch("/notification-channels/{channel_id}", response_model=NotificationChannelOut)
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


@router.delete("/notification-channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(channel_id: str, db: DB, user: CurrentUser):
    channel = await _get_channel_or_404(db, channel_id, user.id)
    await db.delete(channel)
    await db.flush()


@router.post(
    "/notification-channels/{channel_id}/test",
    response_model=TestNotificationOut,
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


@router.get("/notifications", response_model=NotificationListOut)
async def list_notifications(
    db: DB,
    user: CurrentUser,
    unread: bool | None = None,
    offset: int = 0,
    limit: int = 50,
):
    q = select(Notification).where(Notification.user_id == user.id)
    count_q = select(func.count(Notification.id)).where(Notification.user_id == user.id)
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


@router.get("/notifications/unread-count", response_model=UnreadCountOut)
async def unread_count(db: DB, user: CurrentUser):
    count = (
        await db.execute(
            select(func.count(Notification.id)).where(
                Notification.user_id == user.id,
                Notification.is_read.is_(False),
            )
        )
    ).scalar() or 0
    return UnreadCountOut(count=count)


@router.patch("/notifications/{notification_id}/read", response_model=NotificationOut)
async def mark_read(notification_id: str, db: DB, user: CurrentUser):
    notification = await _get_notification_or_404(db, notification_id, user.id)
    notification.is_read = True
    await db.flush()
    return notification


@router.post("/notifications/read-all", response_model=UnreadCountOut)
async def mark_all_read(db: DB, user: CurrentUser):
    result = await db.execute(
        select(Notification).where(
            Notification.user_id == user.id,
            Notification.is_read.is_(False),
        )
    )
    rows = list(result.scalars().all())
    for notification in rows:
        notification.is_read = True
    await db.flush()
    return UnreadCountOut(count=0)
