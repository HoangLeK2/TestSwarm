"""API contracts for the reusable external entity catalog."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ExternalEntityObserveIn(BaseModel):
    platform: str = Field(min_length=1, max_length=32)
    entity_type: str = Field(min_length=1, max_length=32)
    display_name: str = Field(min_length=1, max_length=500)
    external_id: str | None = Field(default=None, max_length=255)
    canonical_url: str | None = Field(default=None, max_length=1000)
    status: str = Field(default="candidate", max_length=24)
    attributes: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime | None = None
    query: str | None = Field(default=None, max_length=500)
    rank: int | None = Field(default=None, ge=1)
    discovery_context: dict[str, Any] = Field(default_factory=dict)
    raw_data: dict[str, Any] = Field(default_factory=dict)
    account_id: str | None = None
    execution_id: str | None = None


class ExternalEntityBulkObserveIn(BaseModel):
    items: list[ExternalEntityObserveIn] = Field(min_length=1, max_length=500)


class ExternalEntityOut(BaseModel):
    id: str
    org_id: str
    platform: str
    entity_type: str
    identity_key: str
    identity_confidence: str
    external_id: str | None = None
    canonical_url: str | None = None
    display_name: str
    status: str
    current_attributes: dict[str, Any] = Field(default_factory=dict)
    current_metrics: dict[str, Any] = Field(default_factory=dict)
    first_seen_at: datetime
    last_seen_at: datetime
    created_at: datetime
    updated_at: datetime


class ExternalEntityObserveOut(BaseModel):
    entity: ExternalEntityOut
    created: bool


class ExternalEntityBulkObserveOut(BaseModel):
    items: list[ExternalEntityObserveOut]
    observed_count: int
    created_count: int


class ExternalEntityListOut(BaseModel):
    items: list[ExternalEntityOut]
    total: int
    limit: int
    offset: int
