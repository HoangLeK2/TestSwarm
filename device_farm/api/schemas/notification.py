from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


NOTIFICATION_EVENTS = [
    "device.disconnect",
    "device.reconnect",
    "device.offline",
    "device.online",
    "task.failed",
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
    "dlq.threshold",
]


def _validate_notification_events(value: list[str]) -> list[str]:
    cleaned = [v.strip() for v in value if v and v.strip()]
    if not cleaned:
        raise ValueError("events must contain at least one event or '*'")
    allowed = set(NOTIFICATION_EVENTS) | {
        "*",
        "device.*",
        "campaign.*",
        "schedule.*",
        "account.*",
        "content.*",
        "mcp.*",
        "dlq.*",
    }
    unknown = [v for v in cleaned if v not in allowed]
    if unknown:
        raise ValueError(f"Unsupported notification events: {', '.join(unknown)}")
    return cleaned


class NotificationChannelCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    type: str = Field(..., pattern="^(in_app|telegram|webhook|email|slack)$")
    config: dict[str, Any] = Field(default_factory=dict)
    events: list[str] = Field(default_factory=lambda: ["*"])
    is_enabled: bool = True

    @field_validator("events")
    @classmethod
    def validate_events(cls, value: list[str]) -> list[str]:
        return _validate_notification_events(value)


class NotificationChannelPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    type: Optional[str] = Field(default=None, pattern="^(in_app|telegram|webhook|email|slack)$")
    config: Optional[dict[str, Any]] = None
    events: Optional[list[str]] = None
    is_enabled: Optional[bool] = None

    @field_validator("events")
    @classmethod
    def validate_events(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        if value is None:
            return value
        return _validate_notification_events(value)


class NotificationChannelOut(BaseModel):
    id: str
    name: str
    type: str
    config: dict[str, Any]
    events: list[str]
    is_enabled: bool
    user_id: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationOut(BaseModel):
    id: str
    channel_id: Optional[str]
    event: str
    title: str
    body: Optional[str]
    data: dict[str, Any]
    is_read: bool
    read_at: Optional[datetime] = None
    sent_at: datetime
    user_id: Optional[str]
    created_at: datetime
    unread_count: Optional[int] = None

    model_config = {"from_attributes": True}


class NotificationListOut(BaseModel):
    total: int
    offset: int
    limit: int
    notifications: list[NotificationOut]


class UnreadCountOut(BaseModel):
    count: int


class NotificationChannelTestRequest(BaseModel):
    type: str = Field(..., pattern="^(in_app|telegram|webhook|email|slack)$")
    config: dict[str, Any] = Field(default_factory=dict)


class TestNotificationOut(BaseModel):
    ok: bool
    message: str
