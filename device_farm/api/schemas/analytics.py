from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class ActivityLogOut(BaseModel):
    id: str
    action: str
    entity_type: Optional[str]
    entity_id: Optional[str]
    device_serial: Optional[str]
    user_id: Optional[str]
    details: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class ActivityLogListOut(BaseModel):
    total: int
    offset: int
    limit: int
    activities: list[ActivityLogOut]
