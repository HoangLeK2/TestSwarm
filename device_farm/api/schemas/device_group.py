from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator

from api.schemas.device import DeviceOut


class DeviceGroupCreate(BaseModel):
    name: str
    description: str = ""
    color: str = "#6366f1"

    @field_validator("color")
    @classmethod
    def _validate_color(cls, v: str) -> str:
        v = v.strip()
        if v and (len(v) != 7 or not v.startswith("#")):
            raise ValueError("color must be a 7-char hex string like #6366f1")
        return v or "#6366f1"


class DeviceGroupUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    color: str | None = None

    @field_validator("color")
    @classmethod
    def _validate_color(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if v and (len(v) != 7 or not v.startswith("#")):
                raise ValueError("color must be a 7-char hex string like #6366f1")
        return v


class AddDevicesToGroupBody(BaseModel):
    device_ids: list[str]


class DeviceGroupOut(BaseModel):
    id: str
    name: str
    description: str
    color: str
    user_id: Optional[str]
    device_count: int
    created_at: datetime
    updated_at: datetime


class DeviceGroupDetailOut(DeviceGroupOut):
    """Extended response that includes the full device list (for GET /device-groups/{id})."""
    devices: list[DeviceOut] = []


class UpdateTagsBody(BaseModel):
    tags: str  # comma-separated e.g. "fast,wifi,samsung"
