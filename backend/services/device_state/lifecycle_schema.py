"""Device lifecycle WebSocket event contract (DF-T-02-015)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Optional
from uuid import uuid4

from db.models.enums import DeviceFsmEvent


class LifecycleEventType(StrEnum):
    DEVICE_STATE_CHANGED = "device.state_changed"
    SESSION_CLAIMED = "session.claimed"
    SESSION_RELEASED = "session.released"
    DEVICE_UNPAIRED = "device.unpaired"


@dataclass(frozen=True, slots=True)
class DeviceLifecycleEvent:
    """Wire payload for lifecycle stream consumers."""

    type: str
    event_id: str
    organization_id: str
    device_id: str
    from_state: Optional[str]
    to_state: Optional[str]
    timestamp: datetime
    session_id: Optional[str] = None
    source: Optional[str] = None
    payload: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data


def map_fsm_event_type(fsm_event: str) -> LifecycleEventType:
    if fsm_event == DeviceFsmEvent.SESSION_CLAIM.value:
        return LifecycleEventType.SESSION_CLAIMED
    if fsm_event == DeviceFsmEvent.SESSION_RELEASED.value:
        return LifecycleEventType.SESSION_RELEASED
    return LifecycleEventType.DEVICE_STATE_CHANGED


def new_lifecycle_event(
    *,
    event_type: LifecycleEventType | str,
    organization_id: str,
    device_id: str,
    from_state: Optional[str],
    to_state: Optional[str],
    session_id: Optional[str] = None,
    source: Optional[str] = None,
    event_id: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
    timestamp: Optional[datetime] = None,
) -> DeviceLifecycleEvent:
    return DeviceLifecycleEvent(
        type=str(event_type),
        event_id=event_id or str(uuid4()),
        organization_id=organization_id,
        device_id=device_id,
        from_state=from_state,
        to_state=to_state,
        timestamp=timestamp or datetime.now(timezone.utc),
        session_id=session_id,
        source=source,
        payload=payload,
    )


@dataclass
class LifecycleSnapshotDevice:
    device_id: str
    state: str
    session_id: Optional[str] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "state": self.state,
            "session_id": self.session_id,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


@dataclass
class LifecycleSnapshot:
    organization_id: str
    devices: list[LifecycleSnapshotDevice] = field(default_factory=list)
    replay: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "lifecycle.snapshot",
            "organization_id": self.organization_id,
            "devices": [d.to_dict() for d in self.devices],
            "replay": self.replay,
        }
