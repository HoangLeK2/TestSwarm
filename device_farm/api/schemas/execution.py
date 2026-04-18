"""
api/schemas/execution.py — Pydantic schemas for Execution API (DF-011).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from db.models.enums import ExecutionStatus, ExecutionResultStatus


# ── Step result validation ───────────────────────────────────────────────────


class StepResult(BaseModel):
    """Schema for items in passed_steps / failed_steps arrays."""
    index: int = Field(..., ge=0, description="Step index in scenario")
    name: Optional[str] = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None


# ── Request schemas ───────────────────────────────────────────────────────────


class ExecutionCreate(BaseModel):
    run_type: str = Field(..., min_length=1, max_length=50)
    campaign_id: Optional[str] = None
    scenario_id: Optional[str] = None
    device_ids: list[str] = Field(default_factory=list)
    device_config: dict[str, Any] = Field(default_factory=dict)
    loop_config: dict[str, Any] = Field(default_factory=dict)
    error_config: dict[str, Any] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)


class ExecutionPatch(BaseModel):
    status: Optional[str] = None
    device_config: Optional[dict[str, Any]] = None
    loop_config: Optional[dict[str, Any]] = None
    error_config: Optional[dict[str, Any]] = None
    meta: Optional[dict[str, Any]] = None


class AddDeviceBody(BaseModel):
    device_id: str


class FinishBody(BaseModel):
    status: str = Field(default="completed", pattern="^(completed|failed|cancelled)$")


class UpsertResultBody(BaseModel):
    status: ExecutionResultStatus = Field(default=ExecutionResultStatus.PENDING)
    passed_steps: list[Any] = Field(default_factory=list)
    failed_steps: list[Any] = Field(default_factory=list)
    error_detail: Optional[str] = None
    run_time_sec: Optional[float] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


# ── Response schemas ──────────────────────────────────────────────────────────


class ExecutionResultOut(BaseModel):
    id: str
    execution_id: str
    device_id: str
    status: str
    run_time_sec: Optional[float]
    passed_steps: list[Any]
    failed_steps: list[Any]
    error_detail: Optional[str]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class ExecutionOut(BaseModel):
    id: str
    run_type: str
    status: str
    campaign_id: Optional[str]
    scenario_id: Optional[str]
    scenario_version_id: Optional[str] = None
    device_config: dict[str, Any]
    loop_config: dict[str, Any]
    error_config: dict[str, Any]
    meta: dict[str, Any]
    user_id: Optional[str]
    created_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]

    model_config = {"from_attributes": True}


class ExecutionListOut(BaseModel):
    total: int
    items: list[ExecutionOut]


class SummaryOut(BaseModel):
    total_devices: int
    passed: int
    failed: int
    running: int
    pending: int
    error: int
    total_content_items: int
