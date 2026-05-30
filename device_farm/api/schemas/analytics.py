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
    device_display: Optional[str] = None
    org_id: Optional[str] = None
    user_id: Optional[str]
    user_name: Optional[str] = None
    method: Optional[str] = None
    path: Optional[str] = None
    route_template: Optional[str] = None
    status_code: Optional[int] = None
    request_id: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    outcome: Optional[str] = None
    duration_ms: Optional[int] = None
    details: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class ActivityLogListOut(BaseModel):
    total: int
    offset: int
    limit: int
    activities: list[ActivityLogOut]
