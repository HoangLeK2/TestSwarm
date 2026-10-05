from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class RelayDeviceConnectionOut(BaseModel):
    registered: bool = False
    device_id: Optional[str] = None
    device_agent_connected: bool = False


class RelayAgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    relay_id: str
    user_id: Optional[str] = None
    enrollment_token_id: Optional[str] = None
    name: str = ""
    hostname: str
    ip: str
    version: str
    serials: list[str]
    device_names: dict[str, str] = Field(default_factory=dict)
    status: str
    live_connected: bool = False
    device_connections: dict[str, RelayDeviceConnectionOut] = Field(
        default_factory=dict
    )
    connected_at: datetime
    last_heartbeat_at: Optional[datetime] = None
    disconnected_at: Optional[datetime] = None


class RelayCommandOut(BaseModel):
    ok:        bool
    output:    str = ""
    exit_code: int = -1
    error:     str = ""


class BootstrapAllResult(BaseModel):
    relay_id: str
    total:    int
    ok:       int
    failed:   int
    results:  list[dict]


class RelayAgentTokenCreate(BaseModel):
    name: str = ""


class RelayAgentTokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    prefix: str
    status: str
    created_at: datetime
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None


class RelayAgentTokenCreated(RelayAgentTokenOut):
    token: str


class RelayBatchJobCreate(BaseModel):
    serials: list[str] = Field(default_factory=list)
    mode: Literal["selected", "all_visible"] = "selected"
    connect: bool = True


class RelayBatchJobItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    serial: str
    device_id: Optional[str] = None
    status: str
    step: str = ""
    attempts: int = 0
    error: str = ""
    result: dict = Field(default_factory=dict)


class RelayBatchJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    relay_id: str
    kind: str
    status: str
    total: int
    ok: int
    failed: int
    pending: int
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    updated_at: datetime
    items: list[RelayBatchJobItemOut] = Field(default_factory=list)
