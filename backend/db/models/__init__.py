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
    UserRole,
    SystemUserRole,
    OrgMemberRole,
    OrgMemberStatus,
    CampaignStatus,
    ExecutionStatus,
    ExecutionResultStatus,
    AccountStatus, AccountEventType, DLQStatus, RunStatus, ScheduleTargetType,
    McpSessionStatus, DeviceFsmState, DeviceFsmEvent, DevicePlatformSessionState,
    DevicePlatformLoginAttemptState,
)
from .user import User
from .organization import Organization, OrganizationMember
from .organization_invitation import OrganizationInvitation
from .tenant_settings import TenantSettings
from .device import Device, DeviceSession
from .device_reserve_session import DeviceReserveSession
from .reconnect_policy import ReconnectPolicy
from .device_key import DeviceKey
from .device_fsm import DeviceFsmSnapshot, DeviceStateTransition
from .device_group import DeviceGroup, DeviceGroupMember
from .campaign import Campaign, CampaignDevice, CampaignTag, CampaignTarget, Scenario
from .org_scenario import CampaignOrgScenarioRef, OrgScenario, OrgScenarioTag
from .mcp_session import McpSession
from .mcp_token import McpToken
from .scenario_template import ScenarioTemplate
from .account import Account, DeviceAccount
from .account_import_format import AccountImportFormat
from .account_discovery import ACCOUNT_DISCOVERY_STATUSES, AccountDiscoveryState
from .account_action import AccountAction, AccountActionAttempt, AccountActionTransition
from .device_platform_session import DevicePlatformSession
from .device_platform_login_attempt import DevicePlatformLoginAttempt
from .account_event import AccountEvent
from .account_group import AccountGroup, AccountGroupMember
from .content import ContentItem, ContentCollection, ContentType, ExecutionArtifact
from .schedule import Schedule, ScheduleRun
from .execution import Execution, ExecutionDevice, ExecutionResult
from .execution_step import ExecutionStep
from .scenario_version import ScenarioVersion
from .execution_dlq import ExecutionDLQ
from .execution_event import ExecutionEvent
from .external_entity import (
    DeviceTargetGroup,
    ExecutionEntityAssignment,
    ExternalEntity,
    ExternalEntityDiscovery,
    ExternalEntityObservation,
)
from .u2_recovery import U2RecoveryEvent
from .device_event import DeviceEvent
from .relay_agent import RelayAgent, RelayAgentJob, RelayAgentJobItem, RelayAgentToken
from .scenario_device_variable import CampaignOrgScenarioDeviceVariable, ScenarioDeviceVariable
from .notification import Notification, NotificationChannel
from .activity import ActivityLog
from .analytics import (
    Alert,
    AlertDecision,
    AlertRule,
    MetricRollupDaily,
    MetricRollupWeekly,
    NotificationPreference,
    NotificationRule,
    RetentionPolicyModel,
    WebhookDLQ,
    WebhookDeliveryLog,
)
from .refresh_token import RefreshToken
from .password_history import PasswordHistory
from .ai_device_lab import (
    AiLabIntake,
    AppBuild,
    RunAttempt,
    RunSlot,
    ScenarioApproval,
    ScenarioGenerationOperation,
    ServiceCampaign,
    ServiceLane,
)
from .ai_device_lab_participation import ParticipationEvent, TrackParticipation
from .ai_device_lab_fleet import (
    DeviceHygieneAudit,
    DeviceHygieneState,
    DeviceReservation,
    ReservationAudit,
)
from .ai_device_lab_billing import (
    PaymentEvent,
    PaymentIntent,
    PaymentReconciliationJob,
    RefundDispatchJob,
    ServiceEntitlement,
    ServiceOrder,
    ServiceRefund,
)
from .ai_device_lab_runtime import (
    QuotaLedgerEntry,
    ReadinessCheck,
    ReadinessSnapshot,
    SchedulingIntent,
)
from .ai_device_lab_secrets import JobSecretCapability, SecretAccessAudit, SecretRecord
from .ai_device_lab_delivery import (
    EvidenceItem,
    FarmEventInbox,
    FarmJob,
    FarmJobOutbox,
)
from .ai_device_lab_quality import AppIssue, IssueTransition, RetestRequest
from .ai_device_lab_report import ReportSnapshot
from .ai_device_lab_lifecycle import (
    FleetLifecycleOperation,
    LaneDeviceAssignment,
    ServiceExtension,
)
from .ai_device_lab_kpi import (
    KpiAssistanceEvent,
    KpiCohort,
    KpiCohortMember,
    KpiMeasurementDefinition,
    KpiSnapshot,
)
from .ai_device_lab_acceptance import (
    AcceptanceCandidate,
    AcceptanceDecision,
    AcceptanceRequirement,
)
from .ai_device_lab_operations import OperationalReadinessAssessment, OperationalTarget
from .ai_device_lab_funnel import AiLabFunnelEvent

__all__ = [
    "User",
    "Organization",
    "OrganizationMember",
    "OrganizationInvitation",
    "TenantSettings",
    "Device",
    "DeviceSession",
    "DeviceReserveSession",
    "ReconnectPolicy",
    "DeviceKey",
    "DeviceFsmSnapshot",
    "DeviceStateTransition",
    "DeviceGroup",
    "DeviceGroupMember",
    "Campaign",
    "CampaignDevice",
    "CampaignTarget",
    "Scenario",
    "McpSession",
    "McpToken",
    "ScenarioTemplate",
    "Account",
    "DeviceAccount",
    "AccountImportFormat",
    "ACCOUNT_DISCOVERY_STATUSES",
    "AccountDiscoveryState",
    "AccountAction",
    "AccountActionAttempt",
    "AccountActionTransition",
    "DevicePlatformSession",
    "DevicePlatformSessionState",
    "DevicePlatformLoginAttempt",
    "DevicePlatformLoginAttemptState",
    "AccountEvent",
    "AccountEventType",
    "AccountGroup",
    "AccountGroupMember",
    "ContentItem",
    "ContentCollection",
    "ContentType",
    "ExecutionArtifact",
    "Schedule",
    "ScheduleRun",
    "Execution",
    "ExecutionDevice",
    "ExecutionResult",
    "ExecutionStep",
    "ScenarioVersion",
    "ExecutionDLQ",
    "ExecutionEvent",
    "ExternalEntity",
    "DeviceTargetGroup",
    "ExternalEntityObservation",
    "ExternalEntityDiscovery",
    "ExecutionEntityAssignment",
    "U2RecoveryEvent",
    "DeviceEvent",
    "RelayAgent",
    "RelayAgentJob",
    "RelayAgentJobItem",
    "RelayAgentToken",
    "ScenarioDeviceVariable",
    "CampaignOrgScenarioDeviceVariable",
    "Notification",
    "NotificationChannel",
    "ActivityLog",
    "Alert",
    "AlertDecision",
    "AlertRule",
    "MetricRollupDaily",
    "MetricRollupWeekly",
    "NotificationPreference",
    "NotificationRule",
    "RetentionPolicyModel",
    "WebhookDLQ",
    "WebhookDeliveryLog",
    "RefreshToken",
    "PasswordHistory",
    "ServiceCampaign",
    "ServiceLane",
    "AppBuild",
    "RunSlot",
    "RunAttempt",
    "AiLabIntake",
    "ScenarioApproval",
    "ScenarioGenerationOperation",
    "TrackParticipation",
    "ParticipationEvent",
    "DeviceHygieneState",
    "DeviceHygieneAudit",
    "DeviceReservation",
    "ReservationAudit",
    "ServiceOrder",
    "PaymentIntent",
    "PaymentEvent",
    "PaymentReconciliationJob",
    "RefundDispatchJob",
    "ServiceEntitlement",
    "ServiceRefund",
    "ReadinessSnapshot",
    "ReadinessCheck",
    "SchedulingIntent",
    "QuotaLedgerEntry",
    "SecretRecord",
    "JobSecretCapability",
    "SecretAccessAudit",
    "FarmJob",
    "FarmJobOutbox",
    "FarmEventInbox",
    "EvidenceItem",
    "AppIssue",
    "RetestRequest",
    "IssueTransition",
    "ReportSnapshot",
    "LaneDeviceAssignment",
    "FleetLifecycleOperation",
    "ServiceExtension",
    "KpiMeasurementDefinition",
    "KpiCohort",
    "KpiCohortMember",
    "KpiAssistanceEvent",
    "KpiSnapshot",
    "AcceptanceCandidate",
    "AcceptanceRequirement",
    "AcceptanceDecision",
    "OperationalTarget",
    "OperationalReadinessAssessment",
    "AiLabFunnelEvent",
]
