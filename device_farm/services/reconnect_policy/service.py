"""Reconnect policy validation and resolution (DF-T-02-006)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from db.crud import reconnect_policy as repo
from db.models.reconnect_policy import ReconnectPolicy


class ReconnectPolicyValidationError(ValueError):
    def __init__(self, message: str, *, code: str = "INVALID_RANGE") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ReconnectPolicyView:
    org_id: str
    interval_base_ms: int
    max_interval_ms: int
    max_attempts: int
    jitter_factor: float
    updated_at: str
    updated_by: str | None
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "org_id": self.org_id,
            "interval_base_ms": self.interval_base_ms,
            "max_interval_ms": self.max_interval_ms,
            "max_attempts": self.max_attempts,
            "jitter_factor": self.jitter_factor,
            "updated_at": self.updated_at,
            "updated_by": self.updated_by,
            "source": self.source,
        }


def validate_policy_fields(
    *,
    interval_base_ms: int,
    max_interval_ms: int,
    max_attempts: int,
    jitter_factor: float,
) -> None:
    if interval_base_ms < 1:
        raise ReconnectPolicyValidationError("interval_base_ms must be >= 1")
    if max_interval_ms < interval_base_ms:
        raise ReconnectPolicyValidationError("max_interval_ms must be >= interval_base_ms")
    if max_attempts < 1 or max_attempts > 100:
        raise ReconnectPolicyValidationError("max_attempts must be between 1 and 100")
    if jitter_factor < 0 or jitter_factor > 1:
        raise ReconnectPolicyValidationError("jitter_factor must be between 0 and 1")


def _view_from_row(row: ReconnectPolicy, *, source: str) -> ReconnectPolicyView:
    return ReconnectPolicyView(
        org_id=row.org_id,
        interval_base_ms=row.interval_base_ms,
        max_interval_ms=row.max_interval_ms,
        max_attempts=row.max_attempts,
        jitter_factor=row.jitter_factor,
        updated_at=row.updated_at.isoformat(),
        updated_by=row.updated_by,
        source=source,
    )


async def get_org_reconnect_policy(db: AsyncSession, org_id: str) -> ReconnectPolicyView:
    row = await repo.get_reconnect_policy(db, org_id)
    if row is None:
        return _view_from_row(repo.default_policy(org_id), source="default")
    return _view_from_row(row, source="configured")


async def update_org_reconnect_policy(
    db: AsyncSession,
    *,
    org_id: str,
    interval_base_ms: int,
    max_interval_ms: int,
    max_attempts: int,
    jitter_factor: float,
    updated_by: str,
) -> ReconnectPolicyView:
    validate_policy_fields(
        interval_base_ms=interval_base_ms,
        max_interval_ms=max_interval_ms,
        max_attempts=max_attempts,
        jitter_factor=jitter_factor,
    )
    row = await repo.upsert_reconnect_policy(
        db,
        org_id=org_id,
        interval_base_ms=interval_base_ms,
        max_interval_ms=max_interval_ms,
        max_attempts=max_attempts,
        jitter_factor=jitter_factor,
        updated_by=updated_by,
    )
    return _view_from_row(row, source="configured")


async def heartbeat_policy_payload(db: AsyncSession, org_id: str) -> dict[str, Any]:
    """Policy block for agent heartbeat consumers (DF-T-03-006)."""
    view = await get_org_reconnect_policy(db, org_id)
    return {
        "interval_base_ms": view.interval_base_ms,
        "max_interval_ms": view.max_interval_ms,
        "max_attempts": view.max_attempts,
        "jitter_factor": view.jitter_factor,
        "updated_at": view.updated_at,
    }
