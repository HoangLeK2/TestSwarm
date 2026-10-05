from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


SCHEMA_VERSION = "ai-phone-agent.v1"
PROMPT_POLICY_VERSION = "adl-ai-agent-policy.v1"
ALLOWED_OPERATIONS = {"observe", "tap", "swipe", "type", "key", "launch", "wait", "finish"}


NonEmptyStr = Annotated[str, Field(min_length=1)]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlanStatus(StrEnum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    canceled = "canceled"


class SessionStatus(StrEnum):
    active = "active"
    canceled = "canceled"
    finished = "finished"


class PlanRequest(StrictModel):
    org_id: NonEmptyStr
    intake_id: NonEmptyStr
    intake_version: int = Field(ge=1)
    intake_hash: NonEmptyStr
    app_package: NonEmptyStr
    goal: NonEmptyStr = Field(max_length=4000)
    capability_snapshot: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: NonEmptyStr = Field(max_length=200)
    correlation_id: NonEmptyStr = Field(max_length=200)


class ScenarioStep(StrictModel):
    type: NonEmptyStr
    label: NonEmptyStr
    params: dict[str, Any] = Field(default_factory=dict)
    assertion: dict[str, Any] | None = None


class ScenarioDraft(StrictModel):
    name: NonEmptyStr
    app_package: NonEmptyStr
    steps: list[ScenarioStep] = Field(min_length=1)
    denied_operations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PlanResponse(StrictModel):
    schema_version: Literal["ai-phone-agent.v1"]
    job_id: NonEmptyStr
    status: PlanStatus
    correlation_id: NonEmptyStr
    model: NonEmptyStr
    model_revision: NonEmptyStr
    prompt_policy_version: NonEmptyStr
    input_hash: NonEmptyStr
    draft: ScenarioDraft | None = None
    reason_code: NonEmptyStr
    created_at: datetime
    updated_at: datetime


class Budget(StrictModel):
    max_steps: int = Field(ge=1, le=200)
    deadline_epoch_ms: int = Field(gt=0)
    max_model_calls: int = Field(ge=1, le=100)
    max_cost_usd: float = Field(ge=0, le=1000)


class SessionRequest(StrictModel):
    org_id: NonEmptyStr
    execution_id: NonEmptyStr
    approved_scenario_hash: NonEmptyStr
    policy_version: NonEmptyStr
    lease_id: NonEmptyStr
    fencing_token: NonEmptyStr
    app_package: NonEmptyStr
    allowed_operations: list[str] = Field(min_length=1)
    budget: Budget
    idempotency_key: NonEmptyStr = Field(max_length=200)
    correlation_id: NonEmptyStr = Field(max_length=200)

    @field_validator("allowed_operations")
    @classmethod
    def allowed_operations_must_be_safe(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - ALLOWED_OPERATIONS)
        if unknown:
            raise ValueError(f"unsupported operations: {', '.join(unknown)}")
        return value


class SessionResponse(StrictModel):
    schema_version: Literal["ai-phone-agent.v1"]
    session_id: NonEmptyStr
    status: SessionStatus
    correlation_id: NonEmptyStr
    model: NonEmptyStr
    model_revision: NonEmptyStr
    prompt_policy_version: NonEmptyStr
    budget: Budget
    created_at: datetime
    updated_at: datetime


class ObservationRequest(StrictModel):
    correlation_id: NonEmptyStr = Field(max_length=200)
    observation_id: NonEmptyStr = Field(max_length=200)
    ui_tree: dict[str, Any] = Field(default_factory=dict)
    screenshot_ref: str | None = Field(default=None, max_length=500)
    evidence_ref: str | None = Field(default=None, max_length=500)
    app_package: NonEmptyStr


class ActionProposal(StrictModel):
    action_id: NonEmptyStr
    operation: Literal["tap", "swipe", "type", "key", "launch", "wait", "finish"]
    params: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0, le=1)
    reason_code: NonEmptyStr
    expires_at: datetime


class ObservationResponse(StrictModel):
    schema_version: Literal["ai-phone-agent.v1"]
    session_id: NonEmptyStr
    correlation_id: NonEmptyStr
    model: NonEmptyStr
    model_revision: NonEmptyStr
    prompt_policy_version: NonEmptyStr
    input_hash: NonEmptyStr
    action: ActionProposal


class ActionResultRequest(StrictModel):
    correlation_id: NonEmptyStr = Field(max_length=200)
    action_id: NonEmptyStr
    status: Literal["succeeded", "failed", "blocked", "unknown"]
    observed_at: datetime = Field(default_factory=utc_now)
    evidence_ref: str | None = Field(default=None, max_length=500)
    error_code: str | None = Field(default=None, max_length=120)


class ActionResultResponse(StrictModel):
    schema_version: Literal["ai-phone-agent.v1"]
    session_id: NonEmptyStr
    status: SessionStatus
    accepted: bool
    correlation_id: NonEmptyStr
    updated_at: datetime


class CancelResponse(StrictModel):
    schema_version: Literal["ai-phone-agent.v1"]
    session_id: NonEmptyStr
    status: SessionStatus
    correlation_id: NonEmptyStr
    updated_at: datetime


class HealthResponse(StrictModel):
    status: Literal["ok", "degraded"]
    service: Literal["ai-phone-agent-service"]
    schema_version: Literal["ai-phone-agent.v1"]
    planner: NonEmptyStr
