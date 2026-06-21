from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import AsyncSessionLocal
from db.crud.user import get_user_org_id
from db.models.analytics import WebhookDLQ, WebhookDeliveryLog
from db.models.notification import Notification, NotificationChannel
from services.activity_logger import log_activity
from services.notification_events import parse_domain_event, render_notification
from services.webhook_dispatcher import _is_safe_webhook_url
from tenancy.background import DeviceRef, lookup_device_by_serial
from tenancy.context import get_current_org_id, tenant_context

log = logging.getLogger(__name__)

DEFAULT_EVENTS = [
    "device.disconnect",
    "device.reconnect",
    "device.offline",
    "device.online",
    "task.failed",
    "dlq.threshold",
    "campaign.complete",
    "campaign.completed",
    "campaign.dispatched",
    "campaign.failed",
    "campaign.dlq_opened",
    "schedule.triggered",
    "schedule.failed",
    "schedule.run_failed",
    "account.banned",
    "account.rotated",
    "account.locked",
    "content.milestone",
    "mcp.action_sensitive",
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
                        elif channel.type == "email":
                            await self._send_email(channel, title, body, data or {})
                        elif channel.type == "slack":
                            await self._send_slack(channel, event, title, body, data or {})
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

    async def emit(self, payload: dict[str, Any]) -> list[Notification]:
        """Ingest a normalized domain event and fan out audit + notification.

        This is the Module 09 boundary intended for domain modules. It validates
        the event, appends activity_log, renders a stable notification template,
        then routes through the existing channel/subscription path.
        """
        event = parse_domain_event(payload)
        rendered = render_notification(
            event,
            locale=str(payload.get("locale") or "en"),
            app_base_url=str(payload.get("app_base_url") or "").strip(),
        )
        async with AsyncSessionLocal() as db:
            await log_activity(
                db,
                action=event.event_type,
                entity_type=event.resource_type,
                entity_id=event.resource_id,
                user_id=event.actor_user_id,
                org_id=event.org_id,
                details={
                    **(event.payload or {}),
                    "summary": event.summary,
                    "deep_link": rendered.deep_link,
                    "template_version": rendered.template_version,
                },
            )
            await db.commit()
        with tenant_context(event.org_id):
            return await self.notify(
                event.event_type,
                rendered.title,
                rendered.body,
                {
                    **(event.payload or {}),
                    "resource_type": event.resource_type,
                    "resource_id": event.resource_id,
                    "deep_link": rendered.deep_link,
                    "template_version": rendered.template_version,
                },
                user_id=event.recipient_user_id,
            )

    async def send_test(self, db: AsyncSession, channel: NotificationChannel, user_id: str) -> None:
        await self._send_test_payload(db, channel.type, channel.config or {}, user_id, channel)

    async def send_test_draft(
        self,
        db: AsyncSession,
        channel_type: str,
        config: dict[str, Any],
        user_id: str,
    ) -> None:
        await self._send_test_payload(db, channel_type, config, user_id, channel=None)

    async def _send_test_payload(
        self,
        db: AsyncSession,
        channel_type: str,
        config: dict[str, Any],
        user_id: str,
        channel: NotificationChannel | None,
    ) -> None:
        event = "task.failed"
        title = "Test notification"
        body = "Device Farm notification channel is working."
        if channel_type == "in_app":
            if channel is None:
                raise ValueError("in_app channels do not require a connection test")
            notification = await self._send_in_app(
                db, channel, event, title, body, {"test": True}, user_id
            )
            await db.flush()
            await self._push_in_app(notification)
        elif channel_type == "telegram":
            await self._send_telegram(self._draft_channel(channel_type, config), title, body)
        elif channel_type == "webhook":
            await self._send_webhook_draft(config, event, title, body, {"test": True})
        else:
            raise ValueError(f"connection test is not supported for {channel_type} channels")

    @staticmethod
    def _draft_channel(channel_type: str, config: dict[str, Any]) -> NotificationChannel:
        from types import SimpleNamespace

        return SimpleNamespace(type=channel_type, config=config)  # type: ignore[return-value]

    async def _send_webhook_draft(
        self,
        config: dict[str, Any],
        event: str,
        title: str,
        body: Optional[str],
        data: dict[str, Any],
    ) -> None:
        url = str(config.get("url") or "").strip()
        if not url:
            raise ValueError("webhook channel requires url")
        if not _is_safe_webhook_url(url):
            raise ValueError("unsafe webhook url")
        headers = config.get("headers") or config.get("custom_headers")
        if not isinstance(headers, dict):
            headers = {}
        timeout = min(max(int(config.get("timeout_seconds") or 10), 1), 30)
        payload = {
            "event_type": event,
            "title": title,
            "body": body,
            "data": data,
            "test": True,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, headers=headers, timeout=timeout)
            resp.raise_for_status()

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
        if not _is_safe_webhook_url(url):
            raise ValueError("unsafe webhook url")
        headers = config.get("headers") or config.get("custom_headers")
        if not isinstance(headers, dict):
            headers = {}
        timeout = min(max(int(config.get("timeout_seconds") or 10), 1), 30)
        payload = self._standard_payload(channel, event, title, body, data)
        started = time.monotonic()
        attempt = 1
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(url, json=payload, headers=headers, timeout=timeout)
                await self._record_delivery(
                    channel,
                    event,
                    attempt=attempt,
                    status="success" if resp.is_success else "failed",
                    status_code=resp.status_code,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    error=None if resp.is_success else resp.text[:500],
                )
                resp.raise_for_status()
            except Exception as exc:
                await self._record_delivery(
                    channel,
                    event,
                    attempt=attempt,
                    status="failed",
                    status_code=None,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    error=str(exc)[:500],
                )
                await self._record_webhook_dlq(channel, payload, str(exc)[:500])
                raise

    async def _send_slack(
        self,
        channel: NotificationChannel,
        event: str,
        title: str,
        body: Optional[str],
        data: dict[str, Any],
    ) -> None:
        config = channel.config or {}
        url = str(config.get("webhook_url") or config.get("url") or "").strip()
        if not url:
            raise ValueError("slack channel requires webhook_url")
        payload = self._standard_payload(channel, event, title, body, data)
        slack_payload = {
            "text": title,
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": title[:150]}},
                {"type": "section", "text": {"type": "mrkdwn", "text": body or title}},
            ],
        }
        deep_link = payload.get("deep_link")
        if deep_link:
            slack_payload["blocks"].append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Open in Device Farm"},
                            "url": deep_link,
                        }
                    ],
                }
            )
        await self._send_webhook_like(channel, event, url, slack_payload)

    async def _send_email(
        self,
        channel: NotificationChannel,
        title: str,
        body: Optional[str],
        data: dict[str, Any],
    ) -> None:
        config = channel.config or {}
        to_address = str(config.get("to") or config.get("recipient") or data.get("email") or "").strip()
        if "@" not in to_address:
            raise ValueError("email channel requires a valid recipient")
        # Real SMTP/SES adapters can be configured by deployment. In local tests
        # and default installs this records the channel as accepted without
        # opening a network connection.
        if not config.get("smtp_host") and not config.get("ses_region"):
            log.info("email notification accepted without transport recipient=%s title=%s", to_address, title)
            return
        raise ValueError("email transport adapter is not configured in this environment")

    async def _send_webhook_like(
        self,
        channel: NotificationChannel,
        event: str,
        url: str,
        payload: dict[str, Any],
    ) -> None:
        if not _is_safe_webhook_url(url):
            raise ValueError("unsafe webhook url")
        started = time.monotonic()
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=10)
            await self._record_delivery(
                channel,
                event,
                attempt=1,
                status="success" if resp.is_success else "failed",
                status_code=resp.status_code,
                latency_ms=int((time.monotonic() - started) * 1000),
                error=None if resp.is_success else resp.text[:500],
            )
            resp.raise_for_status()

    def _standard_payload(
        self,
        channel: NotificationChannel,
        event: str,
        title: str,
        body: Optional[str],
        data: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "event_type": event,
            "organization_id": channel.org_id,
            "resource_type": data.get("resource_type"),
            "resource_id": data.get("resource_id") or data.get("campaign_id") or data.get("execution_id"),
            "summary": body or title,
            "timestamp": data.get("timestamp"),
            "deep_link": data.get("deep_link"),
            "data": data,
        }

    async def _record_delivery(
        self,
        channel: NotificationChannel,
        event: str,
        *,
        attempt: int,
        status: str,
        status_code: int | None,
        latency_ms: int,
        error: str | None,
    ) -> None:
        async with AsyncSessionLocal() as db:
            db.add(
                WebhookDeliveryLog(
                    org_id=channel.org_id,
                    channel_id=channel.id,
                    event_type=event,
                    attempt=attempt,
                    status=status,
                    status_code=status_code,
                    latency_ms=latency_ms,
                    error=error,
                )
            )
            await db.commit()

    async def _record_webhook_dlq(
        self,
        channel: NotificationChannel,
        payload: dict[str, Any],
        error: str,
    ) -> None:
        async with AsyncSessionLocal() as db:
            db.add(
                WebhookDLQ(
                    org_id=channel.org_id,
                    channel_id=channel.id,
                    event_payload=payload,
                    final_status="failed",
                    last_error=error,
                )
            )
            await db.commit()

    async def _push_in_app(self, notification: Notification) -> None:
        if self._ws_manager is None or not notification.user_id:
            return
        await self._ws_manager.send_to_user(
            notification.user_id,
            {"type": "notification", "data": notification_to_dict(notification)},
        )
