"""Fleet health summary helpers (DF-T-02-013)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from db.models.enums import DeviceFsmState, SessionOwnerType


def derive_session_owner_type(
    *,
    session_id: str,
    user_id: Optional[str] = None,
) -> SessionOwnerType:
    """Classify an active session owner without exposing sensitive ids."""
    sid = (session_id or "").strip()
    if user_id:
        return SessionOwnerType.USER
    lowered = sid.lower()
    if lowered.startswith("exec:") or lowered.startswith("execution:"):
        return SessionOwnerType.EXECUTION
    if lowered.startswith("camp:") or lowered.startswith("campaign:"):
        return SessionOwnerType.CAMPAIGN
    if lowered.startswith("sys:") or lowered.startswith("system:"):
        return SessionOwnerType.SYSTEM
    return SessionOwnerType.UNKNOWN


def empty_state_counts() -> dict[str, int]:
    return {state.value: 0 for state in DeviceFsmState}


def empty_owner_counts() -> dict[str, int]:
    return {owner.value: 0 for owner in SessionOwnerType}


@dataclass
class FleetStatsFilters:
    organization_id: str
    group_id: Optional[str] = None
    relay_host: Optional[str] = None


@dataclass
class SessionOwnerAnomaly:
    session_id: str
    device_id: str
    device_serial: str
    owner_type: str
    owner_id: Optional[str] = None
    reason: str = ""


@dataclass
class FleetStatsResult:
    filters: FleetStatsFilters
    devices_by_state: dict[str, int] = field(default_factory=empty_state_counts)
    active_sessions_by_owner: dict[str, int] = field(default_factory=empty_owner_counts)
    owner_anomalies: list[SessionOwnerAnomaly] = field(default_factory=list)

    @property
    def device_total(self) -> int:
        return sum(self.devices_by_state.values())

    @property
    def active_session_total(self) -> int:
        return sum(self.active_sessions_by_owner.values())
