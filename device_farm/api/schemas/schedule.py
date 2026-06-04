"""
api/schemas/schedule.py — Pydantic schemas for Schedule API (DF-008).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ── Request schemas ───────────────────────────────────────────────────────────


class ScheduleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    target_type: str = Field(..., pattern="^(campaign|template|fleet)$")
    target_id: Optional[str] = None
    inline_steps: Optional[list[dict[str, Any]]] = None
    inline_variables: dict[str, Any] = Field(default_factory=dict)
    device_group_id: Optional[str] = None
    filter_state: str = "READY"
    filter_model: Optional[str] = None
    max_devices: Optional[int] = Field(default=None, gt=0)
    cron_expression: Optional[str] = Field(default=None, min_length=1, max_length=100)
    timezone: str = "Asia/Ho_Chi_Minh"
    run_at: Optional[datetime] = None
    skip_dates: list[str] = Field(default_factory=list)
    skip_windows: list[dict[str, Any]] = Field(default_factory=list)
    misfire_policy: str = Field(default="skip", pattern="^(skip|latest_only|catch_up)$")
    random_delay_min: int = Field(default=0, ge=0)
    random_delay_max: int = Field(default=0, ge=0)
    stagger_devices: bool = False
    stagger_interval_seconds: int = Field(default=60, ge=1, le=3600)
    is_enabled: bool = True
    priority: str = Field(default="normal", pattern="^(low|normal|high)$")
    max_concurrent_per_device: int = Field(default=1, ge=1, le=10)
    account_rate_limit_per_hour: Optional[int] = Field(default=None, ge=1, le=10000)
    quota_policy: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_schedule_shape(self) -> "ScheduleCreate":
        if self.cron_expression and self.run_at:
            raise ValueError("CRON_AND_RUN_AT_MUTUALLY_EXCLUSIVE")
        if not self.cron_expression and not self.run_at:
            raise ValueError("CRON_OR_RUN_AT_REQUIRED")
        return self

    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        try:
            from croniter import croniter
            if not croniter.is_valid(v):
                raise ValueError(f"Invalid cron expression: {v!r}")
        except ImportError:
            pass  # croniter not installed — skip validation
        return v

    @field_validator("random_delay_max")
    @classmethod
    def validate_delay_range(cls, v: int, info) -> int:
        min_val = info.data.get("random_delay_min", 0)
        if v > 0 and v < min_val:
            raise ValueError("random_delay_max must be >= random_delay_min")
        return v

    @field_validator("target_type")
    @classmethod
    def validate_target_consistency(cls, v: str, info) -> str:
        if v in ("campaign", "template") and not info.data.get("target_id"):
            # Will be caught in route handler — schema can't access other fields here easily
            pass
        return v


class SchedulePatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    target_type: Optional[str] = Field(default=None, pattern="^(campaign|template|fleet)$")
    target_id: Optional[str] = None
    inline_steps: Optional[list[dict[str, Any]]] = None
    inline_variables: Optional[dict[str, Any]] = None
    device_group_id: Optional[str] = None
    filter_state: Optional[str] = None
    filter_model: Optional[str] = None
    max_devices: Optional[int] = Field(default=None, gt=0)
    cron_expression: Optional[str] = Field(default=None, min_length=1, max_length=100)
    timezone: Optional[str] = None
    run_at: Optional[datetime] = None
    skip_dates: Optional[list[str]] = None
    skip_windows: Optional[list[dict[str, Any]]] = None
    misfire_policy: Optional[str] = Field(default=None, pattern="^(skip|latest_only|catch_up)$")
    random_delay_min: Optional[int] = Field(default=None, ge=0)
    random_delay_max: Optional[int] = Field(default=None, ge=0)
    stagger_devices: Optional[bool] = None
    stagger_interval_seconds: Optional[int] = Field(default=None, ge=1, le=3600)
    is_enabled: Optional[bool] = None
    priority: Optional[str] = Field(default=None, pattern="^(low|normal|high)$")
    max_concurrent_per_device: Optional[int] = Field(default=None, ge=1, le=10)
    account_rate_limit_per_hour: Optional[int] = Field(default=None, ge=1, le=10000)
    quota_policy: Optional[dict[str, Any]] = None

    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        try:
            from croniter import croniter
            if not croniter.is_valid(v):
                raise ValueError(f"Invalid cron expression: {v!r}")
        except ImportError:
            pass
        return v


# ── Response schemas ──────────────────────────────────────────────────────────


class ScheduleOut(BaseModel):
    id: str
    name: str
    description: str
    target_type: str
    target_id: Optional[str]
    inline_steps: Optional[list[dict[str, Any]]]
    inline_variables: dict[str, Any]
    device_group_id: Optional[str]
    filter_state: str
    filter_model: Optional[str]
    max_devices: Optional[int]
    cron_expression: Optional[str]
    timezone: str
    schedule_kind: str
    run_at: Optional[datetime]
    skip_dates: list[str]
    skip_windows: list[dict[str, Any]]
    misfire_policy: str
    random_delay_min: int
    random_delay_max: int
    stagger_devices: bool
    stagger_interval_seconds: int
    is_enabled: bool
    status: str
    priority: str
    max_concurrent_per_device: int
    account_rate_limit_per_hour: Optional[int]
    quota_policy: dict[str, Any]
    deleted_at: Optional[datetime]
    last_run_at: Optional[datetime]
    next_run_at: Optional[datetime]
    run_count: int
    user_id: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ScheduleRunOut(BaseModel):
    id: str
    schedule_id: str
    status: str
    trigger_source: str
    scheduled_at: Optional[datetime]
    started_at: datetime
    finished_at: Optional[datetime]
    deferred_until: Optional[datetime]
    was_catch_up: bool
    execution_id: Optional[str]
    devices_dispatched: int
    devices_succeeded: int
    devices_failed: int
    task_ids: list[str]
    workflow_ids: list[str]
    error_code: Optional[str]
    error_message: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class TriggerResponse(BaseModel):
    run_id: str
    message: str = "Schedule triggered"


class BulkScheduleToggleIn(BaseModel):
    schedule_ids: list[str] = Field(..., min_length=1, max_length=500)


class BulkScheduleToggleItemOut(BaseModel):
    schedule_id: str
    status: str
    enabled: Optional[bool] = None
    error_code: Optional[str] = None


class BulkScheduleToggleOut(BaseModel):
    success_count: int
    fail_count: int
    skipped_count: int
    items: list[BulkScheduleToggleItemOut]


class ScheduleConflictOut(BaseModel):
    conflict_id: str
    type: str
    severity: str
    impacted_target: str
    suggested_action: str


class SchedulePreviewIn(BaseModel):
    target_type: str = Field(..., pattern="^(campaign|template|fleet)$")
    target_id: Optional[str] = None
    cron_expression: Optional[str] = Field(default=None, min_length=1, max_length=100)
    timezone: str = "Asia/Ho_Chi_Minh"
    run_at: Optional[datetime] = None
    device_group_id: Optional[str] = None
    max_devices: Optional[int] = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_preview_shape(self) -> "SchedulePreviewIn":
        if self.cron_expression and self.run_at:
            raise ValueError("CRON_AND_RUN_AT_MUTUALLY_EXCLUSIVE")
        if not self.cron_expression and not self.run_at:
            raise ValueError("CRON_OR_RUN_AT_REQUIRED")
        return self


class SchedulePreviewOut(BaseModel):
    conflicts: list[ScheduleConflictOut]
    next_runs: list[datetime]


class ScheduleStatusOut(BaseModel):
    temporal_available: bool
    fallback_active: bool
    banner: Optional[str]
    metrics: dict[str, Any]
