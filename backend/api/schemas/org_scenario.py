"""Org-scoped scenario API schemas (DF-T-04-001)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class OrgScenarioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    kind: Literal["sequence", "graph"] = "sequence"
    description: str = ""
    body_json: Optional[dict[str, Any]] = None
    tags: list[str] = Field(default_factory=list)


class AccountLoginScenarioEnsureIn(BaseModel):
    platform: str = Field(min_length=1, max_length=100)


class OrgScenarioUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    kind: Optional[Literal["sequence", "graph"]] = None
    description: Optional[str] = None
    status: Optional[Literal["draft", "active", "archived"]] = None
    body_json: Optional[dict[str, Any]] = None
    tags: Optional[list[str]] = None


class OrgScenarioSummaryOut(BaseModel):
    id: str
    organization_id: str
    is_system_template: bool = False
    name: str
    description: str
    kind: str
    status: str
    scenario_version: int
    tags: list[str] = Field(default_factory=list)
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    is_runnable: bool = False
    is_recovery_scenario: bool = False
    recovery_usage_count: int = 0
    last_validation_summary: Optional[dict[str, Any]] = None
    last_validated_at: Optional[datetime] = None


class OrgScenarioOut(OrgScenarioSummaryOut):
    body_json: Optional[dict[str, Any]] = None


class OrgScenarioBodyIn(BaseModel):
    steps: Optional[list[dict[str, Any]]] = None
    nodes: Optional[list[dict[str, Any]]] = None
    edges: Optional[list[dict[str, Any]]] = None
    variables: Optional[dict[str, Any]] = None
    requirements: Optional[dict[str, Any]] = None


class OrgScenarioBodyOut(BaseModel):
    scenario_id: str
    kind: str
    scenario_version: int
    body_json: dict[str, Any]
    is_runnable: bool
    validation: dict[str, Any] = Field(default_factory=dict)


class OrgScenarioInUseOut(BaseModel):
    code: str = "SCENARIO_IN_USE"
    referenced_by: list[dict[str, Any]]


class ValidationIssueOut(BaseModel):
    level: str
    code: str
    message: str
    location: str = ""
    hint: Optional[str] = None


class OrgScenarioValidateIn(BaseModel):
    steps: Optional[list[dict[str, Any]]] = None
    nodes: Optional[list[dict[str, Any]]] = None
    edges: Optional[list[dict[str, Any]]] = None
    variables: Optional[dict[str, Any]] = None
    requirements: Optional[dict[str, Any]] = None
    campaign_variables: Optional[dict[str, Any]] = None


class OrgScenarioValidationOut(BaseModel):
    scenario_id: str
    status: str
    errors: list[ValidationIssueOut] = Field(default_factory=list)
    warnings: list[ValidationIssueOut] = Field(default_factory=list)
    infos: list[ValidationIssueOut] = Field(default_factory=list)
    last_validated_at: Optional[datetime] = None
    last_validation_summary: Optional[dict[str, Any]] = None


class OrgScenarioImportOut(BaseModel):
    scenario_id: str
    name: str
    kind: str
    status: str
    scenario_version: int
    warnings: list[str] = Field(default_factory=list)
    created_stub_names: list[str] = Field(default_factory=list)


class OrgScenarioCloneTemplateIn(BaseModel):
    name_override: Optional[str] = Field(default=None, min_length=1, max_length=255)
