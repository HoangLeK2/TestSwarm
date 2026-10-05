from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ValidationIssueOut(BaseModel):
    level: Literal["error", "warning", "info"]
    code: str
    message: str
    location: str = ""
    hint: Optional[str] = None


class ScenarioValidationOut(BaseModel):
    status: Literal["valid", "invalid"]
    errors: list[ValidationIssueOut] = Field(default_factory=list)
    warnings: list[ValidationIssueOut] = Field(default_factory=list)
    infos: list[ValidationIssueOut] = Field(default_factory=list)
    last_validated_at: Optional[datetime] = None


class ScenarioValidationSummaryOut(BaseModel):
    status: Literal["valid", "invalid"]
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    codes: list[str] = Field(default_factory=list)
