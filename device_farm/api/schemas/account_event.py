from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class AccountEventOut(BaseModel):
    id: str
    account_id: str
    event_type: str
    device_serial: Optional[str] = None
    platform: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    model_config = {"from_attributes": True}


class AccountEventListOut(BaseModel):
    items: list[AccountEventOut]
    next_cursor: Optional[str] = None
    has_more: bool = False
