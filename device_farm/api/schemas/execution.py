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


class ExecutionCancelBody(BaseModel):
    reason: str = Field(default="", max_length=2000)


class ExecutionControlOut(BaseModel):
    execution_id: str
    status: str
    action: str
    effective_transition: bool
    workflows_signalled: int = 0
    warning: Optional[str] = None


class CampaignControlOut(BaseModel):
    campaign_id: str
    status: str
    executions_affected: int
    executions: list[dict[str, Any]] = Field(default_factory=list)
    workflows_signalled: int = 0
    warning: Optional[str] = None


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
    pause_signal_received_at: Optional[datetime] = None
    cancel_signal_received_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    cancel_reason: Optional[str] = None

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
    latest_dispatch_id: Optional[str] = None
    latest_dispatch_target_count: int = 0
    latest_dispatch_finished_count: int = 0
    latest_dispatch_running_count: int = 0
    latest_dispatch_pending_count: int = 0
    latest_dispatch_failed_count: int = 0
    latest_dispatch_workflow_started_count: int = 0
    latest_dispatch_fallback_count: int = 0
    latest_dispatch_created_at: Optional[datetime] = None
    latest_dispatch_first_started_at: Optional[datetime] = None
    latest_dispatch_latest_finished_at: Optional[datetime] = None
    latest_dispatch_elapsed_ms: Optional[float] = None
    latest_dispatch_terminal_ms: Optional[float] = None
    latest_dispatch_to_first_start_ms: Optional[float] = None
    latest_dispatch_to_start_p95_ms: Optional[float] = None


class ExecutionStepOut(BaseModel):
    id: str
    execution_id: str
    step_index: int
    step_id: Optional[str] = None
    step_type: Optional[str] = None
    status: str
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    duration_ms: Optional[float] = None
    error_json: dict[str, Any] = Field(default_factory=dict)
    effective_config_json: dict[str, Any] = Field(default_factory=dict)
    artifacts_json: list[Any] = Field(default_factory=list)
    attempts_json: list[Any] = Field(default_factory=list)
    marked_ignored: bool = False
    message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
