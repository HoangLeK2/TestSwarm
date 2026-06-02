"""DLQ domain errors (DF-T-04-012)."""
from __future__ import annotations


class DLQError(Exception):
    def __init__(self, message: str, *, code: str, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status


class DLQNotFoundError(DLQError):
    def __init__(self, message: str = "DLQ entry not found") -> None:
        super().__init__(message, code="DLQ_NOT_FOUND", http_status=404)


class DLQRetryInProgressError(DLQError):
    def __init__(self, message: str = "DLQ retry already in progress") -> None:
        super().__init__(message, code="DLQ_RETRY_IN_PROGRESS", http_status=409)


class DLQAlreadyClosedError(DLQError):
    def __init__(self, message: str = "DLQ entry is already closed") -> None:
        super().__init__(message, code="DLQ_ALREADY_CLOSED", http_status=409)


class DLQPermissionDeniedError(DLQError):
    def __init__(self, message: str = "Permission denied for DLQ entry") -> None:
        super().__init__(message, code="DLQ_PERMISSION_DENIED", http_status=403)
