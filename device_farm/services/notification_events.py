from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from string import Formatter
from typing import Any


class EventSchemaError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class DomainEvent:
    event_type: str
    org_id: str
    resource_type: str
    resource_id: str
    summary: str
    actor_user_id: str | None = None
    recipient_user_id: str | None = None
    execution_id: str | None = None
    timestamp: datetime | None = None
    payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class RenderedNotification:
    title: str
    body: str
    deep_link: str
    locale: str
    template_version: str


_ALIASES = {
    "campaign.complete": "campaign.completed",
    "schedule.failed": "schedule.run_failed",
    "device.disconnect": "device.offline",
    "device.reconnect": "device.online",
    "account.banned": "account.locked",
}

_SCHEMAS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "campaign.dispatched": ("campaign", "campaign_id", ("campaign_id",)),
    "campaign.completed": ("campaign", "campaign_id", ("campaign_id",)),
    "campaign.failed": ("campaign", "campaign_id", ("campaign_id",)),
    "campaign.dlq_opened": ("execution", "execution_id", ("campaign_id", "execution_id")),
    "schedule.run_failed": ("schedule", "schedule_id", ("schedule_id",)),
    "device.offline": ("device", "device_id", ()),
    "device.online": ("device", "device_id", ()),
    "account.rotated": ("account", "account_id", ("account_id",)),
    "account.locked": ("account", "account_id", ("account_id",)),
    "content.milestone": ("content", "content_id", ()),
    "mcp.action_sensitive": ("mcp_session", "mcp_session_id", ("mcp_session_id",)),
    "dlq.threshold": ("dlq", "campaign_id", ()),
}

_PATHS = {
    "campaign": "campaigns",
    "execution": "executions",
    "schedule": "schedules",
    "device": "devices",
    "account": "accounts",
    "content": "content",
    "mcp_session": "mcp/sessions",
    "dlq": "executions/dlq",
}

_TEMPLATES: dict[str, dict[str, tuple[str, str]]] = {
    "campaign.completed": {
        "en": ("Campaign {resource_name} completed", "{summary}. Open: {deep_link}"),
        "vi": ("Campaign {resource_name} da hoan thanh", "{summary}. Mo chi tiet: {deep_link}"),
    },
    "campaign.failed": {
        "en": ("Campaign {resource_name} failed", "{summary}. Open: {deep_link}"),
        "vi": ("Campaign {resource_name} that bai", "{summary}. Mo chi tiet: {deep_link}"),
    },
    "campaign.dispatched": {
        "en": ("Campaign {resource_name} dispatched", "{summary}. Open: {deep_link}"),
        "vi": ("Campaign {resource_name} da dispatch", "{summary}. Mo chi tiet: {deep_link}"),
    },
    "campaign.dlq_opened": {
        "en": ("Campaign DLQ opened", "{summary}. Open: {deep_link}"),
        "vi": ("Campaign co DLQ moi", "{summary}. Mo chi tiet: {deep_link}"),
    },
    "schedule.run_failed": {
        "en": ("Schedule {resource_name} failed", "{summary}. Open: {deep_link}"),
        "vi": ("Schedule {resource_name} chay that bai", "{summary}. Mo chi tiet: {deep_link}"),
    },
    "device.offline": {
        "en": ("Device {resource_name} offline", "{summary}. Open: {deep_link}"),
        "vi": ("Thiet bi {resource_name} offline", "{summary}. Mo chi tiet: {deep_link}"),
    },
    "device.online": {
        "en": ("Device {resource_name} online", "{summary}. Open: {deep_link}"),
        "vi": ("Thiet bi {resource_name} online", "{summary}. Mo chi tiet: {deep_link}"),
    },
    "account.rotated": {
        "en": ("Account {resource_name} rotated", "{summary}. Open: {deep_link}"),
        "vi": ("Tai khoan {resource_name} da rotation", "{summary}. Mo chi tiet: {deep_link}"),
    },
    "account.locked": {
        "en": ("Account {resource_name} locked", "{summary}. Open: {deep_link}"),
        "vi": ("Tai khoan {resource_name} bi khoa", "{summary}. Mo chi tiet: {deep_link}"),
    },
    "content.milestone": {
        "en": ("Content milestone reached", "{summary}. Open: {deep_link}"),
        "vi": ("Content dat moc moi", "{summary}. Mo chi tiet: {deep_link}"),
    },
    "mcp.action_sensitive": {
        "en": ("Sensitive MCP action", "{summary}. Open: {deep_link}"),
        "vi": ("MCP co hanh dong nhay cam", "{summary}. Mo chi tiet: {deep_link}"),
    },
    "dlq.threshold": {
        "en": ("DLQ threshold exceeded", "{summary}. Open: {deep_link}"),
        "vi": ("DLQ vuot nguong", "{summary}. Mo chi tiet: {deep_link}"),
    },
}

_ALLOWED_PLACEHOLDERS = {
    "resource_type",
    "resource_id",
    "resource_name",
    "actor",
    "timestamp",
    "deep_link",
    "summary",
}


def normalize_event_type(event_type: str) -> str:
    cleaned = event_type.strip()
    return _ALIASES.get(cleaned, cleaned)


def parse_domain_event(payload: dict[str, Any]) -> DomainEvent:
    event_type = normalize_event_type(str(payload.get("type") or payload.get("event_type") or ""))
    if not event_type:
        raise EventSchemaError("EVENT_SCHEMA_INVALID", "event type is required")
    org_id = str(payload.get("org_id") or payload.get("organization_id") or "").strip()
    if not org_id:
        raise EventSchemaError("EVENT_SCHEMA_INVALID", "org_id is required")
    schema = _SCHEMAS.get(event_type)
    if schema is None:
        resource_type = str(payload.get("resource_type") or "event").strip()
        resource_id = str(payload.get("resource_id") or payload.get("id") or event_type).strip()
        required: tuple[str, ...] = ()
    else:
        resource_type, id_field, required = schema
        resource_id = str(payload.get(id_field) or payload.get("resource_id") or "").strip()
    missing = [field for field in required if not str(payload.get(field) or "").strip()]
    if missing:
        raise EventSchemaError(
            "EVENT_SCHEMA_INVALID",
            f"{event_type} missing required field(s): {', '.join(missing)}",
        )
    if not resource_id:
        resource_id = str(payload.get("serial") or payload.get("device_serial") or event_type).strip()
    timestamp = payload.get("timestamp")
    parsed_timestamp = timestamp if isinstance(timestamp, datetime) else datetime.now(timezone.utc)
    return DomainEvent(
        event_type=event_type,
        org_id=org_id,
        resource_type=resource_type,
        resource_id=resource_id,
        summary=str(payload.get("summary") or payload.get("body") or event_type),
        actor_user_id=payload.get("actor_user_id") or payload.get("user_id"),
        recipient_user_id=payload.get("recipient_user_id") or payload.get("user_id"),
        execution_id=payload.get("execution_id"),
        timestamp=parsed_timestamp,
        payload=dict(payload),
    )


def build_deep_link(resource_type: str, resource_id: str, app_base_url: str) -> str:
    base = app_base_url.rstrip("/")
    path = _PATHS.get(resource_type, resource_type)
    return f"{base}/{path}/{resource_id}".rstrip("/")


def render_notification(
    event: DomainEvent,
    *,
    locale: str = "en",
    app_base_url: str = "",
) -> RenderedNotification:
    templates = _TEMPLATES.get(event.event_type)
    if not templates:
        raise EventSchemaError("TEMPLATE_NOT_FOUND", f"no template for {event.event_type}")
    effective_locale = locale if locale in templates else "en"
    if effective_locale not in templates:
        raise EventSchemaError("TEMPLATE_NOT_FOUND", f"no locale template for {event.event_type}")
    title_template, body_template = templates[effective_locale]
    deep_link = build_deep_link(event.resource_type, event.resource_id, app_base_url)
    context = {
        "resource_type": event.resource_type,
        "resource_id": event.resource_id,
        "resource_name": (event.payload or {}).get("resource_name") or event.resource_id,
        "actor": event.actor_user_id or "system",
        "timestamp": (event.timestamp or datetime.now(timezone.utc)).isoformat(),
        "deep_link": deep_link,
        "summary": event.summary,
    }
    return RenderedNotification(
        title=title_template.format(**context),
        body=body_template.format(**context),
        deep_link=deep_link,
        locale=effective_locale,
        template_version="v1",
    )


def lint_templates() -> list[str]:
    errors: list[str] = []
    for event_type, locales in _TEMPLATES.items():
        for required_locale in ("en", "vi"):
            if required_locale not in locales:
                errors.append(f"{event_type}.{required_locale} missing")
        for locale, parts in locales.items():
            for template in parts:
                fields = {
                    name for _, name, _, _ in Formatter().parse(template)
                    if name
                }
                unknown = sorted(fields - _ALLOWED_PLACEHOLDERS)
                if unknown:
                    errors.append(f"{event_type}.{locale} unknown placeholders: {unknown}")
    return errors
