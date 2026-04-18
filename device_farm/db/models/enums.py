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


class ContentExportStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    READY = "ready"
