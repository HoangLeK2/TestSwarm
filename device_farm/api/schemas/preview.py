"""Preview execution API schemas (DF-T-04-018)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PreviewStartRequest(BaseModel):
    device_id: str
    scenario_version: int | None = None
    vars: dict[str, Any] = Field(default_factory=dict)
    account_id: str | None = None
    force: bool = False


class PreviewStartResponse(BaseModel):
    execution_id: str
    status: str
    kind: str = "preview"
    warnings: list[str] = Field(default_factory=list)
    workflow_id: str | None = None
    dispatch_source: str | None = None
    org_scenario_id: str
    device_id: str


class PreviewListItem(BaseModel):
    execution_id: str
    status: str
    kind: str = "preview"
    org_scenario_id: str | None = None
    org_scenario_name: str | None = None
    device_id: str | None = None
    created_at: datetime
    finished_at: datetime | None = None
    artifact_count: int = 0
    artifacts_purged: bool = False
    warnings: list[str] = Field(default_factory=list)


class PreviewListResponse(BaseModel):
    total: int
    items: list[PreviewListItem]
