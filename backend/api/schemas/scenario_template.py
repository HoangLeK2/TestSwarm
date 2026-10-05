from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator


class ScenarioTemplateCreate(BaseModel):
    name: str
    display_name: str = ""
    description: str = ""
    category: str = "general"
    steps: list = []
    variables: dict = {}
    tags: str = ""

    @field_validator("steps")
    @classmethod
    def validate_steps(cls, v: list) -> list:
        if not v:
            return v
        from common.scenario_schema import validate_scenario
        errors = validate_scenario({"steps": v})
        if errors:
            raise ValueError(f"Step validation failed: {'; '.join(errors[:5])}")
        return v


class ScenarioTemplateUpdate(BaseModel):
    name: str | None = None
    display_name: str | None = None
    description: str | None = None
    category: str | None = None
    steps: list | None = None
    variables: dict | None = None
    tags: str | None = None

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


class ScenarioTemplateOut(BaseModel):
    id: str
    name: str
    display_name: str = ""
    description: str
    category: str
    steps: list
    variables: dict
    tags: str
    is_builtin: bool
    user_id: Optional[str]
    created_at: datetime
    updated_at: datetime
