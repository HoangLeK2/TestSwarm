"""Fleet list query schemas (DF-T-02-007 / DF-T-02-014)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class FleetDeviceItemOut(BaseModel):
    db_id: str
    device_serial: str
    adb_serial: Optional[str] = None
    relay_serial: Optional[str] = None
    adb_ip: Optional[str] = None
    adb_port: int = 5555
    name: str
    state: str
    group_ids: list[str] = Field(default_factory=list)
    current_session_id: Optional[str] = None
    owner_type: Optional[str] = None
    owner_id: Optional[str] = None
    last_seen_at: Optional[datetime] = None
    model: str = ""
    android_version: str = ""


class FleetDeviceListOut(BaseModel):
    items: list[FleetDeviceItemOut]
    next_cursor: Optional[str] = None
    total: int
