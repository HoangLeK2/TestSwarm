"""Epic 04 org-scoped campaign entity schemas (DF-T-04-006)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from common.campaign_scenario_refs import MAX_SCENARIO_REPEAT_COUNT


class CampaignScenarioRefIn(BaseModel):
    scenario_id: str
    scenario_version: Optional[int] = Field(default=None, ge=1)
    repeat_count: int = Field(default=1, ge=1, le=MAX_SCENARIO_REPEAT_COUNT)


class CampaignScenarioRefOut(BaseModel):
    scenario_id: str
    scenario_version: int
    repeat_count: int = Field(default=1)


class CampaignEntityCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    vars: dict[str, Any] = Field(default_factory=dict)
    per_device_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)
    recovery_policy: dict[str, Any] = Field(default_factory=dict)
    account_group_id: Optional[str] = None
    scenario_account_id: Optional[str] = None
    per_device_accounts: dict[str, str] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    scenario_refs: list[CampaignScenarioRefIn] = Field(default_factory=list)


class CampaignEntityUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    vars: Optional[dict[str, Any]] = None
    recovery_policy: Optional[dict[str, Any]] = None
    tags: Optional[list[str]] = None
    scenario_refs: Optional[list[CampaignScenarioRefIn]] = None
    per_device_overrides: Optional[dict[str, dict[str, Any]]] = None


class CampaignAccountBindIn(BaseModel):
    account_group_id: Optional[str] = None
    scenario_account_id: Optional[str] = None
    per_device_accounts: dict[str, str] = Field(default_factory=dict)


class CampaignDispatchTargetIn(BaseModel):
    device_ids: list[str] = Field(default_factory=list)
    device_group_ids: list[str] = Field(default_factory=list)
    external_entity_ids: list[str] = Field(default_factory=list)


class CampaignSourcePoolIn(BaseModel):
    platform: str = Field(min_length=1, max_length=32)
    entity_type: str = Field(min_length=1, max_length=32)
    search: Optional[str] = Field(default=None, max_length=500)
    output_prefix: Optional[str] = Field(default=None, max_length=32)
    statuses: list[str] = Field(
        default_factory=lambda: ["candidate", "active", "available"],
        min_length=1,
        max_length=10,
    )


class CampaignAllocationSnapshotItemIn(BaseModel):
    device_id: str = Field(min_length=1, max_length=36)
    external_entity_id: str = Field(min_length=1, max_length=36)


class CampaignDispatchIn(BaseModel):
    target: CampaignDispatchTargetIn
    source_pool: Optional[CampaignSourcePoolIn] = None
    allocation_snapshot: list[CampaignAllocationSnapshotItemIn] = Field(
        default_factory=list
    )
    allocation_policy: Literal["one_per_device"] = "one_per_device"
    dispatch_strategy: str = Field(default="parallel", pattern="^(parallel|sequential)$")
    allow_partial: bool = False
    require_online: bool = True

    @model_validator(mode="after")
    def validate_source_selection(self):
        if self.source_pool is not None and self.target.external_entity_ids:
            raise ValueError(
                "source_pool and target.external_entity_ids are mutually exclusive"
            )
        return self


class CampaignDispatchPreviewAssignmentOut(BaseModel):
    device_id: str
    device_serial: str
    device_name: Optional[str] = None
    external_entity_id: str
    display_name: str
    platform: str
    entity_type: str


class CampaignDispatchPreviewOut(BaseModel):
    campaign_id: str
    allocation_policy: str
    device_count: int
    available_source_count: int
    assignments: list[CampaignDispatchPreviewAssignmentOut] = Field(
        default_factory=list
    )


class CampaignDispatchExecutionOut(BaseModel):
    execution_id: str
    device_id: str
    status: str
    effective_vars: dict[str, Any] = Field(default_factory=dict)
    account_id: Optional[str] = None
    failure_reason: Optional[str] = None
    claim_session_id: Optional[str] = None
    external_entity_id: Optional[str] = None
    dispatch_source: Optional[str] = None
    workflow_id: Optional[str] = None


def _dispatch_http_status(code: str) -> int:
    if code == "CAMPAIGN_NOT_FOUND":
        return 404
    if code in {"INVALID_TRANSITION", "CAMPAIGN_ALREADY_RUNNING", "CAMPAIGN_LOCKED"}:
        return 409
    return 400


class CampaignDispatchOut(BaseModel):
    dispatch_id: str
    campaign_id: str
    dispatch_strategy: str
    target_count: int
    executions: list[CampaignDispatchExecutionOut] = Field(default_factory=list)


class CampaignForceTransitionIn(BaseModel):
    to_status: str = Field(min_length=1, max_length=32)
    reason: str = Field(min_length=1, max_length=2000)


class CampaignForceTransitionOut(BaseModel):
    campaign_id: str
    from_status: str
    to_status: str
    changed: bool
    reason: Optional[str] = None


class ContinuousCrawlDeviceLaneOut(BaseModel):
    device_serial: str
    status: Literal["idle", "running", "paused", "offline", "failed"]
    target_id: Optional[str] = None
    target_label: Optional[str] = None
    completed: int = 0
    failed: int = 0
    message: Optional[str] = None


class ContinuousCrawlTargetSummaryOut(BaseModel):
    target_id: str
    label: Optional[str] = None
    status: Literal["queued", "running", "succeeded", "failed"]
    device_serial: Optional[str] = None
    message: Optional[str] = None


class ContinuousCrawlDeviceTargetsOut(BaseModel):
    device_id: str
    device_serial: str
    device_name: str
    target_count: int


class ContinuousCrawlPreflightOut(BaseModel):
    ready: bool
    target_count: Optional[int] = None
    device_count: int
    max_concurrency: int
    device_targets: list[ContinuousCrawlDeviceTargetsOut] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class ContinuousCrawlStartOut(BaseModel):
    campaign_id: str
    dispatch_id: str
    workflow_id: str
    status: str


class ContinuousCrawlProgressOut(BaseModel):
    campaign_id: str
    dispatch_id: Optional[str] = None
    status: str
    health: Literal["healthy", "degraded", "critical"]
    loaded: int = 0
    active: int = 0
    succeeded: int = 0
    failed: int = 0
    consecutive_failures: int = 0
    exhausted: bool = False
    generation: int = 0
    max_targets: Optional[int] = None
    message: Optional[str] = None
    updated_at: Optional[datetime] = None
    device_lanes: list[ContinuousCrawlDeviceLaneOut] = Field(default_factory=list)
    recent_targets: list[ContinuousCrawlTargetSummaryOut] = Field(default_factory=list)


class CampaignEntityOut(BaseModel):
    id: str
    organization_id: str
    name: str
    description: str
    status: str
    vars: dict[str, Any] = Field(default_factory=dict)
    per_device_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)
    recovery_policy: dict[str, Any] = Field(default_factory=dict)
    account_group_id: Optional[str] = None
    scenario_account_id: Optional[str] = None
    per_device_accounts: dict[str, str] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    scenario_refs: list[CampaignScenarioRefOut] = Field(default_factory=list)
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
