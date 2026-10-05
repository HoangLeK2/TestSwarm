from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from db.models.enums import AccountState
from services.account_verification_hold import (
    AccountVerificationHoldBody,
    AccountVerificationHoldOut,
)


class AccountStateTransitionBody(BaseModel):
    to: str = Field(..., description="Target FSM state")
    reason: str = Field(..., min_length=1, max_length=2000)
    expected_state_changed_at: Optional[datetime] = Field(
        None,
        description="Optimistic lock: must match current state_changed_at",
    )
    verification_hold: Optional[AccountVerificationHoldBody] = Field(
        default=None,
        description=(
            "Optional reminder window when moving an account into suspended/"
            "verification-required state."
        ),
    )

    @field_validator("to")
    @classmethod
    def _valid_to(cls, v: str) -> str:
        raw = v.strip().lower()
        try:
            return AccountState(raw).value
        except ValueError as exc:
            allowed = ", ".join(sorted(s.value for s in AccountState))
            raise ValueError(f"to must be one of: {allowed}") from exc


class AccountStateTransitionOut(BaseModel):
    id: str
    state: str
    status: str
    state_reason: Optional[str]
    state_changed_at: Optional[datetime]
    cooldown_until: Optional[datetime]
    verification_hold: Optional[AccountVerificationHoldOut] = None
