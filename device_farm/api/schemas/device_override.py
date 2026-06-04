"""Admin manual override schemas (DF-T-02-011)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class AdminForceReleaseBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    session_id: Optional[str] = None


class AdminResetStateBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    target_state: Optional[str] = Field(
        default=None,
        description="connecting or online; default depends on current state",
    )


class AdminOverrideOut(BaseModel):
    device_id: str
    from_state: str
    to_state: str
    old_owner_type: Optional[str] = None
    old_owner_id: Optional[str] = None
    session_id: Optional[str] = None
    reason: str
    actor: str
