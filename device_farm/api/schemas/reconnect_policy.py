"""Admin reconnect policy schemas (DF-T-02-006)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ReconnectPolicyOut(BaseModel):
    org_id: str
    interval_base_ms: int
    max_interval_ms: int
    max_attempts: int
    jitter_factor: float
    updated_at: str
    updated_by: Optional[str] = None
    source: str = Field(description="default or configured")


class ReconnectPolicyUpdate(BaseModel):
    interval_base_ms: int
    max_interval_ms: int
    max_attempts: int
    jitter_factor: float
