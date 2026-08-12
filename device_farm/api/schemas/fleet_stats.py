"""Fleet health summary API schemas (DF-T-02-013)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from db.models.enums import DeviceFsmState, SessionOwnerType


class FleetStatsFiltersOut(BaseModel):
    organization_id: str
    group_id: Optional[str] = None
    relay_host: Optional[str] = None


class DeviceStateCountsOut(BaseModel):
    unknown: int = 0
    connecting: int = 0
    online: int = 0
    busy: int = 0
    reconnecting: int = 0
    dead: int = 0
    total: int = 0


class SessionOwnerCountsOut(BaseModel):
    user: int = 0
    execution: int = 0
    campaign: int = 0
    system: int = 0
    unknown: int = 0
    total: int = 0


class SessionOwnerAnomalyOut(BaseModel):
    session_id: str
    device_id: str
    device_serial: str
    owner_type: SessionOwnerType
    owner_id: Optional[str] = Field(
        default=None,
        description="Sensitive owner identifier; only returned to privileged callers.",
    )
    reason: str


class FleetStatsOut(BaseModel):
    filters: FleetStatsFiltersOut
    devices: DeviceStateCountsOut
    active_sessions: SessionOwnerCountsOut
    owner_anomalies: Optional[list[SessionOwnerAnomalyOut]] = Field(
        default=None,
        description="Null for read-only callers; empty list or anomalies for devices:manage callers.",
    )


class ActiveFleetSessionOut(BaseModel):
    session_id: str
    device_id: str
    device_serial: str
    device_name: str
    owner_type: SessionOwnerType
    source: Literal["active_session", "busy_claim"]
    created_at: datetime
    duplicate_for_device: bool = False


class ActiveFleetSessionListOut(BaseModel):
    total: int
    offset: int
    limit: int
    sessions: list[ActiveFleetSessionOut]


def build_device_state_counts(counts: dict[str, int]) -> DeviceStateCountsOut:
    normalized = {state.value: int(counts.get(state.value, 0)) for state in DeviceFsmState}
    total = sum(normalized.values())
    return DeviceStateCountsOut(**normalized, total=total)


def build_session_owner_counts(counts: dict[str, int]) -> SessionOwnerCountsOut:
    normalized = {owner.value: int(counts.get(owner.value, 0)) for owner in SessionOwnerType}
    total = sum(normalized.values())
    return SessionOwnerCountsOut(**normalized, total=total)
