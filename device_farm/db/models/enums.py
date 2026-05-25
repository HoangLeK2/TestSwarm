"""Centralized StrEnum definitions for all status/role fields.

Usage in models:  default=CampaignStatus.IDLE
Usage in CRUD:    .where(Campaign.status == CampaignStatus.RUNNING)
"""
from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "admin"
    OPERATOR = "operator"


class CampaignStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class ExecutionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionResultStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


class AccountStatus(StrEnum):
    ACTIVE = "active"
    COOLDOWN = "cooldown"
    BANNED = "banned"
    DISABLED = "disabled"


class AccountEventType(StrEnum):
    CREATED = "account.created"
    UPDATED = "account.updated"
    STATUS_CHANGED = "account.status_changed"
    DELETED = "account.deleted"
    DEVICE_ASSIGNED = "account.device_assigned"
    DEVICE_UNASSIGNED = "account.device_unassigned"
    PICKED = "account.picked"
    USAGE_STARTED = "account.usage_started"
    USAGE_ENDED = "account.usage_ended"
    COOLDOWN_ENTERED = "account.cooldown_entered"
    COOLDOWN_CLEARED = "account.cooldown_cleared"
    SESSION_DEATH = "account.session_death"
    BANNED = "account.banned"


class DLQStatus(StrEnum):
    PENDING = "pending"
    RETRYING = "retrying"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class RunStatus(StrEnum):
    """Used by ScheduleRun."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


class ScheduleTargetType(StrEnum):
    CAMPAIGN = "campaign"
    TEMPLATE = "template"
    FLEET = "fleet"


class McpSessionStatus(StrEnum):
    ACTIVE = "active"
    ENDED = "ended"


