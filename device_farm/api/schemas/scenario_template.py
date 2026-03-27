from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ScenarioTemplateCreate(BaseModel):
    name: str
    description: str = ""
    category: str = "general"
    steps: list = []
    variables: dict = {}
    tags: str = ""


class ScenarioTemplateUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    steps: list | None = None
    variables: dict | None = None
    tags: str | None = None


class ScenarioTemplateOut(BaseModel):
    id: str
    name: str
    description: str
    category: str
    steps: list
    variables: dict
    tags: str
    is_builtin: bool
    user_id: Optional[str]
    created_at: datetime
    updated_at: datetime
