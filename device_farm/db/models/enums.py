"""Centralized StrEnum definitions for all status/role fields.

Usage in models:  default=CampaignStatus.IDLE
Usage in CRUD:    .where(Campaign.status == CampaignStatus.RUNNING)
"""
from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    SUPERADMIN = "superadmin"
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
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionResultStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


class AccountState(StrEnum):
    """Account lifecycle FSM (DF-T-07-005). Canonical field: ``accounts.state``."""

    ACTIVE = "active"
    COOLDOWN = "cooldown"
    SUSPENDED = "suspended"
    BANNED = "banned"
    RETIRED = "retired"


# Backward-compatible alias — prefer AccountState for new code.
AccountStatus = AccountState


class AccountEventType(StrEnum):
    CREATED = "account.created"
    UPDATED = "account.updated"
    STATUS_CHANGED = "account.status_changed"
    STATE_CHANGED = "account.state.changed"
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


class DeviceFsmState(StrEnum):
    """Device lifecycle FSM at control plane (DF-T-02-002)."""

    UNKNOWN = "unknown"
    CONNECTING = "connecting"
    ONLINE = "online"
    BUSY = "busy"
    RECONNECTING = "reconnecting"
    DEAD = "dead"


class DeviceFsmEvent(StrEnum):
    """Events that drive device FSM transitions."""

    ATTACHED = "device.attached"
    ONLINE = "device.online"
    BUSY = "device.busy"
    RECONNECTING = "device.reconnecting"
    DEAD = "device.dead"
    RELEASED = "device.released"
    REVIVED = "device.revived"
    SESSION_CLAIM = "session.claim"
    SESSION_RELEASED = "session.released"
    SESSION_LOST = "session.lost_device"
    ADMIN_RESET = "admin.reset"
    ADMIN_FORCE_ONLINE = "admin.force_online"


class SessionOwnerType(StrEnum):
    """Owner classification for active control-plane sessions (DF-T-02-013)."""

    USER = "user"
    EXECUTION = "execution"
    CAMPAIGN = "campaign"
    SYSTEM = "system"
    UNKNOWN = "unknown"


class DeviceReserveOwnerType(StrEnum):
    """Reserve session owner (DF-T-02-003)."""

    MANUAL = "manual"
    SCENARIO = "scenario"
    MCP = "mcp"


class DeviceReserveReleaseReason(StrEnum):
    MANUAL = "manual"
    TIMEOUT = "timeout"
    FORCE = "force"


class DeviceRegistryStatus(StrEnum):
    PAIRED = "paired"
    UNPAIRED = "unpaired"
