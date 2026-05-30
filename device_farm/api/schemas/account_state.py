from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from db.models.enums import AccountState


class AccountStateTransitionBody(BaseModel):
    to: str = Field(..., description="Target FSM state")
    reason: str = Field(..., min_length=1, max_length=2000)
    ttl_seconds: Optional[int] = Field(
        None,
        ge=1,
        description="Required when to=cooldown; cooldown_until = now + ttl_seconds",
    )
    expected_state_changed_at: Optional[datetime] = Field(
        None,
        description="Optimistic lock: must match current state_changed_at",
    )

    @field_validator("to")
    @classmethod
    def _valid_to(cls, v: str) -> str:
        raw = v.strip().lower()
        try:
            AccountState(raw)
        except ValueError as exc:
            allowed = ", ".join(sorted(s.value for s in AccountState))
            raise ValueError(f"to must be one of: {allowed}") from exc
        return raw


class AccountStateTransitionOut(BaseModel):
    id: str
    state: str
    status: str
    state_reason: Optional[str]
    state_changed_at: Optional[datetime]
    cooldown_until: Optional[datetime]
