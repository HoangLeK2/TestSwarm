from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class DeviceClaimBody(BaseModel):
    owner_type: str = "manual"
    owner_id: str = ""
    ttl_sec: Optional[int] = None
    ctx: Optional[dict[str, Any]] = None


class DeviceReleaseBody(BaseModel):
    session_id: str


class DeviceReserveSessionOut(BaseModel):
    session_id: str
    device_id: str
    owner_type: str
    owner_id: str
    claimed_at: datetime
    last_heartbeat: datetime
    ttl_sec: int
    ctx: Optional[dict[str, Any]] = None


class DeviceClaimOut(DeviceReserveSessionOut):
    pass


class PairRegistryBody(BaseModel):
    device_serial: str
    adb_serial: str = ""
    relay_serial: str = ""
    name: str = ""
    model: str = ""
    android_version: str = ""


class PairRegistryOut(BaseModel):
    db_id: str
    device_serial: str
    adb_serial: Optional[str] = None
    relay_serial: Optional[str] = None
    status: str
    device_key: Optional[str] = Field(
        default=None,
        description="Plaintext device key — returned only on first pair",
    )
    device_key_disclaimer: Optional[str] = None
    created: bool


class UnpairDeviceOut(BaseModel):
    db_id: str
    status: str
    unpaired_at: datetime
