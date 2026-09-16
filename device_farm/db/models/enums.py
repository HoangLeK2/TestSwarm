"""Centralized StrEnum definitions for all status/role fields.

Usage in models:  default=CampaignStatus.IDLE
Usage in CRUD:    .where(Campaign.status == CampaignStatus.RUNNING)
"""
from __future__ import annotations

from enum import StrEnum


class SystemUserRole(StrEnum):

    SUPERADMIN = "superadmin"
    SUPPORT = "support"
    SYSTEM = "system"


UserRole = SystemUserRole


class OrgMemberRole(StrEnum):

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    SUPERVISOR = "supervisor"


class OrgMemberStatus(StrEnum):
    ACTIVE = "active"
    INVITED = "invited"
    SUSPENDED = "suspended"


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    ARCHIVED = "archived"


class ExecutionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DLQ_OPEN = "dlq_open"
    DLQ_CLOSED = "dlq_closed"


class ExecutionResultStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


class AccountState(StrEnum):
    """Account lifecycle FSM (DF-T-07-005). Canonical field: ``accounts.state``.

    ``cooldown`` is deliberately not a state: resting is an eligibility gate on
    ``accounts.cooldown_until``, checked independently of ``state`` by the
    campaign resolver and group pickers. Legacy ``cooldown`` rows normalize to
    ``active`` and keep their ``cooldown_until``.

    ``unassigned`` → ``assigned`` → ``active`` is the acquisition ladder:
    no device link → device linked → a verified platform session exists.
    ``active`` means logged in, not merely usable — use ``DISPATCHABLE_STATES``
    to pick accounts a run may drive.
    """

    UNASSIGNED = "unassigned"
    ASSIGNED = "assigned"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    BANNED = "banned"
    RETIRED = "retired"


AccountStatus = AccountState

#: States a campaign/scenario run may pick an account in. ``assigned`` belongs
#: here: an account has to be dispatchable *before* it can log in, otherwise the
#: login scenario never receives its ``__ACCOUNT_*`` variables.
DISPATCHABLE_STATES = frozenset({AccountState.ASSIGNED.value, AccountState.ACTIVE.value})


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
    SESSION_LOGIN_REQUIRED = "account.session.login_required"
    SESSION_CONFIRMED = "account.session.confirmed"
    SESSION_INVALIDATED = "account.session.invalidated"
    BANNED = "account.banned"


class DevicePlatformSessionState(StrEnum):
    UNKNOWN = "unknown"
    LOGGED_OUT = "logged_out"
    LOGIN_REQUIRED = "login_required"
    LOGGING_IN = "logging_in"
    ACTIVE = "active"
    SUSPECTED_MISMATCH = "suspected_mismatch"
    CHECKPOINT = "checkpoint"
    EXPIRED = "expired"
    FAILED = "failed"


class DevicePlatformLoginAttemptState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    READY_TO_CONFIRM = "ready_to_confirm"
    COMPLETED = "completed"
    CHECKPOINT = "checkpoint"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class DLQStatus(StrEnum):
    PENDING = "pending"
    RETRYING = "retrying"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"
    CLOSED = "closed"
    REPLAYED = "replayed"


class RunStatus(StrEnum):
    """Used by ScheduleRun."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"
    DEFERRED = "deferred"
    DEFERRED_ACCOUNT_RATE = "deferred_account_rate"
    THROTTLED_REJECTED = "throttled_rejected"
    THROTTLED_ACCOUNT_RATE_REJECTED = "throttled_account_rate_rejected"
    THROTTLED_EXPIRED = "throttled_expired"


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


class ExecutionKind(StrEnum):
    """Execution surface marker (DF-T-04-018)."""

    CAMPAIGN = "campaign"
    PREVIEW = "preview"
    SESSION = "session"


class DeviceReserveOwnerType(StrEnum):
    """Reserve session owner (DF-T-02-003)."""

    MANUAL = "manual"
    SCENARIO = "scenario"
    MCP = "mcp"
    CAMPAIGN = "campaign"
    LOGIN = "login"


class CampaignTargetSourceKind(StrEnum):
    """How a device entered a dispatch snapshot (DF-T-04-008)."""

    EXPLICIT = "explicit"
    DEVICE_GROUP = "device_group"


class DeviceReserveReleaseReason(StrEnum):
    MANUAL = "manual"
    TIMEOUT = "timeout"
    FORCE = "force"


class DeviceRegistryStatus(StrEnum):
    PAIRED = "paired"
    UNPAIRED = "unpaired"


class ScenarioKind(StrEnum):
    """Org-scoped scenario layout (DF-T-04-001)."""

    SEQUENCE = "sequence"
    GRAPH = "graph"


class OrgScenarioStatus(StrEnum):
    """Lifecycle of org-scoped scenario library entries (DF-T-04-001)."""

    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"
