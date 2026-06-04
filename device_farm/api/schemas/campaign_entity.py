"""Epic 04 org-scoped campaign entity schemas (DF-T-04-006)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class CampaignScenarioRefIn(BaseModel):
    scenario_id: str
    scenario_version: Optional[int] = Field(default=None, ge=1)


class CampaignScenarioRefOut(BaseModel):
    scenario_id: str
    scenario_version: int


class CampaignEntityCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    vars: dict[str, Any] = Field(default_factory=dict)
    per_device_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)
    account_group_id: Optional[str] = None
    scenario_account_id: Optional[str] = None
    per_device_accounts: dict[str, str] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    scenario_refs: list[CampaignScenarioRefIn] = Field(default_factory=list)


class CampaignEntityUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    vars: Optional[dict[str, Any]] = None
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


class CampaignDispatchIn(BaseModel):
    target: CampaignDispatchTargetIn
    dispatch_strategy: str = Field(default="parallel", pattern="^(parallel|sequential)$")
    allow_partial: bool = False
    require_online: bool = True


class CampaignDispatchExecutionOut(BaseModel):
    execution_id: str
    device_id: str
    status: str
    effective_vars: dict[str, Any] = Field(default_factory=dict)
    account_id: Optional[str] = None
    failure_reason: Optional[str] = None
    claim_session_id: Optional[str] = None
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


class CampaignEntityOut(BaseModel):
    id: str
    organization_id: str
    name: str
    description: str
    status: str
    vars: dict[str, Any] = Field(default_factory=dict)
    per_device_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)
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
