"""Device FSM transition errors (DF-T-02-002)."""
from __future__ import annotations


class DeviceStateError(Exception):
    code: str = "DEVICE_STATE_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class IllegalDeviceTransitionError(DeviceStateError):
    code = "ILLEGAL_TRANSITION"


class DeviceNotAvailableError(DeviceStateError):
    code = "DEVICE_NOT_AVAILABLE"
