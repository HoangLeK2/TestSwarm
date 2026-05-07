from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class DeviceCreate(BaseModel):
    serial: str
    name: str = ""
    user_id: Optional[str] = None


class DeviceOut(BaseModel):
    id: str
    serial: str
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
    adb_ip: Optional[str] = None
    adb_port: int = 5555
    tags: str = ""  # DF-004: comma-separated device tags
    relay_id: Optional[str] = None


class SessionOut(BaseModel):
    id: str
    client_ip: str
    connected_at: datetime
    disconnected_at: Optional[datetime]
