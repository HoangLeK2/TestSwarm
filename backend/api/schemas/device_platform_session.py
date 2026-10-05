from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class DevicePlatformSessionOut(BaseModel):
    id: str
    org_id: str
    device_id: str
    platform: str
    account_id: Optional[str] = None
    state: str
    state_reason: Optional[str] = None
    established_at: Optional[datetime] = None
    last_ready_at: Optional[datetime] = None
    last_checked_at: Optional[datetime] = None
    invalidated_at: Optional[datetime] = None
    login_attempt_id: Optional[str] = None
    establishment_method: Optional[str] = None
    app_package: str
    app_version: Optional[str] = None
    display_name_observed: Optional[str] = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    version: int
    created_at: datetime
    updated_at: datetime

