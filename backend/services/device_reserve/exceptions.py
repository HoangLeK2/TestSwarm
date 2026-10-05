"""Device reserve session errors (DF-T-02-003)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from services.device_state.exceptions import DeviceStateError


class DeviceSessionError(DeviceStateError):
    pass


class DeviceBusyError(DeviceSessionError):
    code = "DEVICE_BUSY"

    def __init__(
        self,
        message: str,
        *,
        current_session_id: str,
        owner_id: str,
        owner_type: str,
    ) -> None:
        super().__init__(message)
        self.current_session_id = current_session_id
        self.owner_id = owner_id
        self.owner_type = owner_type


class NotSessionOwnerError(DeviceSessionError):
    code = "NOT_SESSION_OWNER"


class SessionNotFoundError(DeviceSessionError):
    code = "SESSION_NOT_FOUND"


class TtlOutOfRangeError(DeviceSessionError):
    code = "TTL_OUT_OF_RANGE"


class DeviceInSessionError(DeviceSessionError):
    code = "DEVICE_IN_SESSION"

    def __init__(self, message: str, *, session_id: str | None = None) -> None:
        super().__init__(message)
        self.session_id = session_id


@dataclass(frozen=True, slots=True)
class ReserveSessionView:
    session_id: str
    device_id: str
    owner_type: str
    owner_id: str
    claimed_at: str
    last_heartbeat: str
    ttl_sec: int
    ctx: Optional[dict]
