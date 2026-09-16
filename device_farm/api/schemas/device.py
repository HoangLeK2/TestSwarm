from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class DeviceCreate(BaseModel):
    serial: str
    name: str = ""
    user_id: Optional[str] = None


class DeviceNameUpdate(BaseModel):
    name: str = Field(default="", max_length=255)


class DeviceOut(BaseModel):
    id: str
    db_id: str | None = None
    serial: str
    device_serial: str = ""
    name: str
    device_key: str
    user_id: Optional[str]
    brand: str
    model: str
    android_version: str
    sdk_version: int
    screen_width: int
    screen_height: int
    last_seen: Optional[datetime]
    created_at: datetime
    adb_serial: Optional[str] = None
    relay_serial: Optional[str] = None
    managed_by_org_id: Optional[str] = None
    managed_by_relay_id: Optional[str] = None
    adb_ip: Optional[str] = None
    adb_port: int = 5555
    tags: str = ""
    relay_id: Optional[str] = None
    # Whether a live transport currently reaches this serial. A pool phone is
    # served by the managing workspace's agent, which a tenant may not list
    # (`/relay-agents` is org-scoped), so the client cannot derive this from the
    # agent list — it would render every allocated phone as "no transport".
    transport_online: bool = False
    state: str = "unknown"
    status: str = "paired"
    paired_at: Optional[datetime] = None
    unpaired_at: Optional[datetime] = None
    notes: str = ""


class DeviceListOut(BaseModel):
    items: list[DeviceOut] = Field(default_factory=list)
    total: int
    page: int
    page_size: int
    page_count: int


class SessionOut(BaseModel):
    id: str
    client_ip: str
    connected_at: datetime
    disconnected_at: Optional[datetime]
