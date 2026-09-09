from datetime import datetime
from typing import Any, List, Optional
import re
from pydantic import BaseModel, Field, field_validator

from api.schemas.scenario import FlowNodeModel, FlowEdgeModel
from api.schemas.scenario_validation import ScenarioValidationSummaryOut
from api.schemas.campaign_entity import CampaignScenarioRefIn


class ScenarioCreate(BaseModel):
    name: str = "Scenario"
    instructions: str = ""
    steps: list = []
    variables: dict = {}
    requirements: dict = {}
    order: int = 0
    nodes: List[FlowNodeModel] = []
    edges: List[FlowEdgeModel] = []
    # Optional account group binding. When set, the dispatcher rotates
    # accounts across devices from this group instead of using each device's
    # primary account.
    account_group_id: Optional[str] = None

    @field_validator("steps")
    @classmethod
    def validate_steps(cls, v: list) -> list:
        if not v:
            return v  # empty is allowed at create time
        from common.scenario_schema import validate_scenario
        errors = validate_scenario({"steps": v})
        if errors:
            raise ValueError(f"Step validation failed: {'; '.join(errors[:5])}")
        return v


class ScenarioUpdate(BaseModel):
    name: str | None = None
    instructions: str | None = None
    steps: list | None = None
    variables: dict | None = None
    requirements: dict | None = None
    order: int | None = None
    nodes: Optional[List[FlowNodeModel]] = None
    edges: Optional[List[FlowEdgeModel]] = None
    # Use an empty string to explicitly clear an existing binding; None means
    # "leave the existing value untouched" (standard PATCH semantics).
    account_group_id: Optional[str] = None

    @field_validator("steps")
    @classmethod
    def validate_steps(cls, v: list | None) -> list | None:
        if not v:
            return v
        from common.scenario_schema import validate_scenario
        errors = validate_scenario({"steps": v})
        if errors:
            raise ValueError(f"Step validation failed: {'; '.join(errors[:5])}")
        return v


class ScenarioOut(BaseModel):
    id: str
    campaign_id: str
    name: str
    instructions: str
    steps: list
    variables: dict
    requirements: dict = {}
    order: int
    nodes: list = []
    edges: list = []
    account_group_id: Optional[str] = None
    account_group_name: Optional[str] = None
    last_validation_summary: Optional[ScenarioValidationSummaryOut] = None
    last_validated_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class CampaignCreate(BaseModel):
    name: str
    description: str = ""
    scenario: dict = {}
    variables: dict = {}
    vars: dict | None = None
    per_device_overrides: dict[str, dict] | None = None
    recovery_policy: dict[str, Any] = Field(default_factory=dict)
    account_group_id: Optional[str] = None
    scenario_account_id: Optional[str] = None
    per_device_accounts: dict[str, str] = Field(default_factory=dict)
    tags: list[str] | None = None
    scenario_refs: list[CampaignScenarioRefIn] | None = None
    device_ids: list[str] = []
    target_group_id: Optional[str] = None  # DF-004


class CampaignOut(BaseModel):
    id: str
    name: str
    description: str
    status: str
    scenario: Optional[dict] = None
    variables: dict = {}
    scenarios: list[ScenarioOut] = []
    user_id: Optional[str]
    created_at: datetime
    target_group_id: Optional[str] = None  # DF-004


class CampaignDeviceOut(BaseModel):
    id: str
    serial: str
    name: str


_SCENARIO_DEVICE_VARIABLE_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")


class ScenarioDeviceVariablesBody(BaseModel):
    vars: dict[str, Any] = Field(default_factory=dict)

    @field_validator("vars")
    @classmethod
    def _validate_keys(cls, value: dict[str, Any]) -> dict[str, Any]:
        for key in value.keys():
            if not _SCENARIO_DEVICE_VARIABLE_KEY_RE.match(key):
                raise ValueError(
                    f"invalid variable key: {key!r} "
                    "(must match ^[A-Za-z][A-Za-z0-9_]{0,63}$)"
                )
        return value


class ScenarioDeviceVariablesOut(BaseModel):
    scenario_id: str
    device_id: str
    vars: dict[str, Any]
