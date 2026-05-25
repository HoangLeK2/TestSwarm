"""
db.models package — SQLAlchemy ORM models grouped by domain.

Previously all models lived in a single db/models.py file. They are now
split into smaller modules for easier maintenance:

- user.py          — User
- organization.py  — Organization, OrganizationMember
- device.py        — Device, DeviceSession
- campaign.py      — Campaign, CampaignDevice
- account.py       — Account, DeviceAccount  (DF-007)
- content.py       — ContentItem, ContentCollection
- execution.py     — Execution, ExecutionDevice, ExecutionResult  (DF-011)
"""

from .enums import (  # noqa: F401 — re-export for convenient access
    UserRole, CampaignStatus, ExecutionStatus, ExecutionResultStatus,
    AccountStatus, AccountEventType, DLQStatus, RunStatus, ScheduleTargetType,
    McpSessionStatus,
)
from .user import User
from .organization import Organization, OrganizationMember
from .device import Device, DeviceSession
from .device_group import DeviceGroup, DeviceGroupMember
from .campaign import Campaign, CampaignDevice, Scenario
from .mcp_session import McpSession
from .scenario_template import ScenarioTemplate
from .account import Account, DeviceAccount
from .account_event import AccountEvent
from .account_group import AccountGroup, AccountGroupMember
from .content import ContentItem, ContentCollection
from .schedule import Schedule, ScheduleRun
from .execution import Execution, ExecutionDevice, ExecutionResult
from .scenario_version import ScenarioVersion
from .execution_dlq import ExecutionDLQ
from .u2_recovery import U2RecoveryEvent
from .device_event import DeviceEvent
from .relay_agent import RelayAgent, RelayAgentJob, RelayAgentJobItem, RelayAgentToken
from .scenario_device_variable import ScenarioDeviceVariable
from .notification import Notification, NotificationChannel
from .activity import ActivityLog

__all__ = [
    "User",
    "Organization",
    "OrganizationMember",
    "Device",
    "DeviceSession",
    "DeviceGroup",
    "DeviceGroupMember",
    "Campaign",
    "CampaignDevice",
    "Scenario",
    "McpSession",
    "ScenarioTemplate",
    "Account",
    "DeviceAccount",
    "AccountEvent",
    "AccountEventType",
    "AccountGroup",
    "AccountGroupMember",
    "ContentItem",
    "ContentCollection",
    "Schedule",
    "ScheduleRun",
    "Execution",
    "ExecutionDevice",
    "ExecutionResult",
    "ScenarioVersion",
    "ExecutionDLQ",
    "U2RecoveryEvent",
    "DeviceEvent",
    "RelayAgent",
    "RelayAgentJob",
    "RelayAgentJobItem",
    "RelayAgentToken",
    "ScenarioDeviceVariable",
    "Notification",
    "NotificationChannel",
    "ActivityLog",
]
