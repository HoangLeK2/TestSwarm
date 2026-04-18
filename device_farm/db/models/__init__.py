"""
db.models package — SQLAlchemy ORM models grouped by domain.

Previously all models lived in a single db/models.py file. They are now
split into smaller modules for easier maintenance:

- user.py          — User
- organization.py  — Organization, OrganizationMember
- device.py        — Device, DeviceSession
- campaign.py      — Campaign, CampaignDevice
- account.py       — Account, DeviceAccount  (DF-007)
- content.py       — ContentItem, ContentCollection, ContentExport
- execution.py     — Execution, ExecutionDevice, ExecutionResult  (DF-011)
"""

from .enums import (  # noqa: F401 — re-export for convenient access
    UserRole, CampaignStatus, ExecutionStatus, ExecutionResultStatus,
    AccountStatus, DLQStatus, RunStatus, ScheduleTargetType,
    McpSessionStatus, ContentExportStatus,
)
from .user import User
from .organization import Organization, OrganizationMember
from .device import Device, DeviceSession
from .device_group import DeviceGroup, DeviceGroupMember
from .campaign import Campaign, CampaignDevice, Scenario
from .mcp_session import McpSession
from .scenario_template import ScenarioTemplate
from .account import Account, DeviceAccount
from .content import ContentItem, ContentCollection, ContentExport
from .schedule import Schedule, ScheduleRun
from .execution import Execution, ExecutionDevice, ExecutionResult
from .scenario_version import ScenarioVersion
from .execution_dlq import ExecutionDLQ
from .u2_recovery import U2RecoveryEvent
from .device_event import DeviceEvent

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
    "ContentItem",
    "ContentCollection",
    "ContentExport",
    "Schedule",
    "ScheduleRun",
    "Execution",
    "ExecutionDevice",
    "ExecutionResult",
    "ScenarioVersion",
    "ExecutionDLQ",
    "U2RecoveryEvent",
    "DeviceEvent",
]

