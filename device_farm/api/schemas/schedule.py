"""
api/schemas/schedule.py — Pydantic schemas for Schedule API (DF-008).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


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
    cron_expression: str = Field(..., min_length=1, max_length=100)
    timezone: str = "Asia/Ho_Chi_Minh"
    random_delay_min: int = Field(default=0, ge=0)
    random_delay_max: int = Field(default=0, ge=0)
    stagger_devices: bool = False
    stagger_interval_seconds: int = Field(default=60, ge=1, le=3600)
    is_enabled: bool = True

    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, v: str) -> str:
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
    random_delay_min: Optional[int] = Field(default=None, ge=0)
    random_delay_max: Optional[int] = Field(default=None, ge=0)
    stagger_devices: Optional[bool] = None
    stagger_interval_seconds: Optional[int] = Field(default=None, ge=1, le=3600)
    is_enabled: Optional[bool] = None

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
    cron_expression: str
    timezone: str
    random_delay_min: int
    random_delay_max: int
    stagger_devices: bool
    stagger_interval_seconds: int
    is_enabled: bool
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
    started_at: datetime
    finished_at: Optional[datetime]
    devices_dispatched: int
    devices_succeeded: int
    devices_failed: int
    task_ids: list[str]
    error_message: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class TriggerResponse(BaseModel):
    run_id: str
    message: str = "Schedule triggered"
