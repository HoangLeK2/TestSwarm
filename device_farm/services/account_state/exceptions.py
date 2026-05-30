"""Account state transition errors (DF-T-07-005)."""
from __future__ import annotations


class AccountStateError(Exception):
    code: str = "ACCOUNT_STATE_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class InvalidStateTransitionError(AccountStateError):
    code = "INVALID_STATE_TRANSITION"


class InvalidTtlError(AccountStateError):
    code = "INVALID_TTL"


class StateConflictError(AccountStateError):
    code = "STATE_CONFLICT"
