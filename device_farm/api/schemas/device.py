from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class DeviceCreate(BaseModel):
    serial: str
    name: str = ""
    user_id: Optional[str] = None


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
    adb_ip: Optional[str] = None
    adb_port: int = 5555
    tags: str = ""
    relay_id: Optional[str] = None
    state: str = "unknown"
    status: str = "paired"
    paired_at: Optional[datetime] = None
    unpaired_at: Optional[datetime] = None
    notes: str = ""


class SessionOut(BaseModel):
    id: str
    client_ip: str
    connected_at: datetime
    disconnected_at: Optional[datetime]
