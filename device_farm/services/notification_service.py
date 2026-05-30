from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import AsyncSessionLocal
from db.crud.user import get_user_org_id
from db.models.notification import Notification, NotificationChannel
from tenancy.background import DeviceRef, lookup_device_by_serial
from tenancy.context import get_current_org_id, tenant_context

log = logging.getLogger(__name__)

DEFAULT_EVENTS = [
    "device.disconnect",
    "device.reconnect",
    "task.failed",
    "dlq.threshold",
    "campaign.complete",
    "campaign.failed",
    "schedule.triggered",
    "schedule.failed",
    "account.banned",
    "content.milestone",
]


def event_matches(subscriptions: list[str] | None, event: str) -> bool:
    if not subscriptions:
        return False
    for item in subscriptions:
        if item == "*" or item == event:
            return True
        if item.endswith(".*") and event.startswith(item[:-1]):
            return True
    return False


def notification_to_dict(notification: Notification) -> dict[str, Any]:
    return {
        "id": notification.id,
        "channel_id": notification.channel_id,
        "event": notification.event,
        "title": notification.title,
        "body": notification.body,
        "data": notification.data or {},
        "is_read": notification.is_read,
        "sent_at": notification.sent_at.isoformat() if notification.sent_at else None,
        "user_id": notification.user_id,
        "created_at": notification.created_at.isoformat() if notification.created_at else None,
    }


def device_event_label(
    *,
    serial: str,
    brand: str = "",
    model: str = "",
    name: str = "",
) -> str:
    """Stable display label for device connect/disconnect notifications."""
    brand_model = " ".join(p for p in [brand, model] if p).strip()
    if brand_model:
        return brand_model
    clean_name = name.strip()
    if clean_name:
        return clean_name
    return serial


def _enrich_device_event(entry: dict[str, Any], ref: DeviceRef | None) -> dict[str, Any]:
    if ref is None:
        return entry
    out = dict(entry)
    if not str(out.get("device_brand") or "").strip() and ref.brand:
        out["device_brand"] = ref.brand
    if not str(out.get("device_model") or "").strip() and ref.model:
        out["device_model"] = ref.model
    if not str(out.get("device_name") or "").strip() and ref.name:
        out["device_name"] = ref.name
    return out


class NotificationService:
    def __init__(self, ws_manager=None) -> None:
        self._ws_manager = ws_manager
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_ws_manager(self, ws_manager) -> None:
        self._ws_manager = ws_manager

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def notify(
        self,
        event: str,
        title: str,
        body: str | None = None,
        data: Optional[dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> list[Notification]:
        async with AsyncSessionLocal() as db:
            try:
                channels = await self._channels_for_event(db, event, user_id)
                saved: list[Notification] = []
                for channel in channels:
                    try:
                        if channel.type == "in_app":
                            notification = await self._send_in_app(
                                db, channel, event, title, body, data or {}, user_id
                            )
                            saved.append(notification)
                        elif channel.type == "telegram":
                            await self._send_telegram(channel, title, body)
                        elif channel.type == "webhook":
                            await self._send_webhook(channel, event, title, body, data or {})
                    except Exception as exc:
                        log.warning(
                            "notification channel failed id=%s type=%s event=%s: %s",
                            channel.id,
                            channel.type,
                            event,
                            exc,
                        )
                await db.commit()
                for notification in saved:
                    await self._push_in_app(notification)
                return saved
            except Exception:
                await db.rollback()
                raise

    async def send_test(self, db: AsyncSession, channel: NotificationChannel, user_id: str) -> None:
        event = "task.failed"
        title = "Test notification"
        body = "Device Farm notification channel is working."
        if channel.type == "in_app":
            notification = await self._send_in_app(
                db, channel, event, title, body, {"test": True}, user_id
            )
            await db.flush()
            await self._push_in_app(notification)
        elif channel.type == "telegram":
            await self._send_telegram(channel, title, body)
        elif channel.type == "webhook":
            await self._send_webhook(channel, event, title, body, {"test": True})

    def bind_device_events(self, recorder) -> None:
        recorder.add_listener(self._on_device_event)

    def _on_device_event(self, entry: dict[str, Any]) -> None:
        if self._loop is None:
            return
        if self._map_device_event(entry) is None:
            return
        asyncio.run_coroutine_threadsafe(
            self._notify_for_device_event(entry),
            self._loop,
        )

    async def _notify_for_device_event(
        self,
        entry: dict[str, Any],
    ) -> None:
        serial = str(entry.get("serial") or "")
        ref = await self._lookup_device_ref(serial)
        if not ref or not ref.org_id:
            log.debug(
                "device-event notification skipped (no org): serial=%s",
                serial,
            )
            return
        enriched = _enrich_device_event(entry, ref)
        mapped = self._map_device_event(enriched)
        if mapped is None:
            return
        event, title, body, data = mapped
        try:
            with tenant_context(ref.org_id):
                await self.notify(event, title, body, data, user_id=ref.user_id)
        except Exception as exc:
            log.warning(
                "device-event notification failed event=%s serial=%s: %s",
                event,
                serial,
                exc,
            )

    async def _lookup_device_ref(self, serial: str) -> DeviceRef | None:
        if not serial:
            return None
        try:
            async with AsyncSessionLocal() as db:
                return await lookup_device_by_serial(db, serial)
        except Exception:
            return None

    async def _resolve_device_owner(self, serial: str) -> tuple[Optional[str], Optional[str]]:
        ref = await self._lookup_device_ref(serial)
        if ref is None:
            return None, None
        return ref.user_id, ref.org_id

    def _map_device_event(
        self,
        entry: dict[str, Any],
    ) -> Optional[tuple[str, str, str, dict[str, Any]]]:
        raw = entry.get("event")
        serial = str(entry.get("serial") or "")
        brand = entry.get("device_brand") or ""
        model = entry.get("device_model") or ""
        name = entry.get("device_name") or ""
        label = device_event_label(serial=serial, brand=brand, model=model, name=name)
        reason = entry.get("reason") or ""
        if raw in {"disconnected", "dead"}:
            event = "device.disconnect"
            title = f"Device {label} disconnected"
            body = reason or f"{label} lost connection"
        elif raw in {"connected", "reconnected"}:
            event = "device.reconnect"
            title = f"Device {label} reconnected"
            body = f"{label} is online"
        elif raw == "error":
            event = "task.failed"
            title = f"Device {label} reported an error"
            body = reason or f"{label} entered error state"
        else:
            return None
        data = {
            "serial": serial,
            "device_brand": brand,
            "device_model": model,
            "device_name": name,
            "device_event_id": entry.get("id"),
            "raw_event": raw,
            "extra_data": entry.get("extra_data") or {},
        }
        return event, title, body, data

    async def _channels_for_event(
        self,
        db: AsyncSession,
        event: str,
        user_id: Optional[str],
    ) -> list[NotificationChannel]:
        if user_id:
            await self._ensure_default_in_app_channel(db, user_id)
        stmt = select(NotificationChannel).where(NotificationChannel.is_enabled.is_(True))
        if user_id:
            stmt = stmt.where(or_(NotificationChannel.user_id == user_id, NotificationChannel.user_id.is_(None)))
        else:
            stmt = stmt.where(NotificationChannel.user_id.is_(None))
        result = await db.execute(stmt)
        return [c for c in result.scalars().all() if event_matches(c.events or [], event)]

    async def _resolve_org_id(self, db: AsyncSession, user_id: str) -> str | None:
        org_id = get_current_org_id()
        if org_id:
            return org_id
        return await get_user_org_id(db, user_id)

    async def _ensure_default_in_app_channel(self, db: AsyncSession, user_id: str) -> None:
        org_id = await self._resolve_org_id(db, user_id)
        if not org_id:
            return
        result = await db.execute(
            select(NotificationChannel.id)
            .where(
                NotificationChannel.user_id == user_id,
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
                user_id=user_id,
                org_id=org_id,
            )
        )
        await db.flush()

    async def _send_in_app(
        self,
        db: AsyncSession,
        channel: NotificationChannel,
        event: str,
        title: str,
        body: Optional[str],
        data: dict[str, Any],
        user_id: Optional[str],
    ) -> Notification:
        notification = Notification(
            channel_id=channel.id,
            event=event,
            title=title,
            body=body,
            data=data,
            user_id=user_id or channel.user_id,
            org_id=channel.org_id,
        )
        db.add(notification)
        await db.flush()
        return notification

    async def _send_telegram(
        self,
        channel: NotificationChannel,
        title: str,
        body: Optional[str],
    ) -> None:
        config = channel.config or {}
        token = str(config.get("bot_token") or "").strip()
        chat_id = str(config.get("chat_id") or "").strip()
        if not token or not chat_id:
            raise ValueError("telegram channel requires bot_token and chat_id")
        text = f"{title}\n{body or ''}".strip()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
                timeout=10,
            )
            resp.raise_for_status()

    async def _send_webhook(
        self,
        channel: NotificationChannel,
        event: str,
        title: str,
        body: Optional[str],
        data: dict[str, Any],
    ) -> None:
        config = channel.config or {}
        url = str(config.get("url") or "").strip()
        if not url:
            raise ValueError("webhook channel requires url")
        headers = config.get("headers") if isinstance(config.get("headers"), dict) else {}
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                json={"event": event, "title": title, "body": body, "data": data},
                headers=headers,
                timeout=10,
            )
            resp.raise_for_status()

    async def _push_in_app(self, notification: Notification) -> None:
        if self._ws_manager is None or not notification.user_id:
            return
        await self._ws_manager.send_to_user(
            notification.user_id,
            {"type": "notification", "data": notification_to_dict(notification)},
        )
