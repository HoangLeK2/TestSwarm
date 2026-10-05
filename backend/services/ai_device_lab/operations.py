"""Fail-closed operational target and dependency readiness evaluation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.ai_device_lab_operations import (
    OperationalReadinessAssessment,
    OperationalTarget,
)


class OperationalInvariantError(ValueError):
    pass


REQUIRED_DEPENDENCIES = (
    "encryption",
    "payment_provider",
    "object_storage",
    "worker",
    "relay",
)

_SYMBOLIC_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,127}")


@dataclass(frozen=True, slots=True)
class SignOperationalTarget:
    org_id: str
    version: str
    capacity: dict
    slo: dict
    recovery: dict
    alerting: dict
    signed_by: str
    signed_at: datetime


@dataclass(frozen=True, slots=True)
class DependencyObservation:
    ready: bool
    reason_code: str
    observed_at: datetime
    source_type: str
    source_ref: str
    source_version: str | None
    latency_ms: float


@dataclass(frozen=True, slots=True)
class AssessOperationalReadiness:
    org_id: str
    target_id: str
    dependency_states: dict[str, bool | DependencyObservation]
    build_ref: str
    schema_version: str
    observed_at: datetime
    ttl_seconds: int = 60


def _positive_fields(payload: dict, names: tuple[str, ...]) -> bool:
    return all(isinstance(payload.get(name), (int, float)) and payload[name] > 0 for name in names)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _dependency_check(
    dependency: str,
    state: bool | DependencyObservation | None,
) -> dict:
    unavailable = f"{dependency.upper()}_UNAVAILABLE"
    if not isinstance(state, DependencyObservation):
        ready = state is True
        return {
            "ready": ready,
            "reason_code": "PASS" if ready else unavailable,
        }
    reason_code = state.reason_code.strip().upper()
    if _SYMBOLIC_CODE.fullmatch(reason_code) is None:
        raise OperationalInvariantError("dependency reason must be a symbolic code")
    if state.ready != (reason_code == "PASS"):
        raise OperationalInvariantError(
            "dependency readiness and reason code are inconsistent"
        )
    if not 1 <= len(state.source_type) <= 64:
        raise OperationalInvariantError("dependency source type must contain 1..64 characters")
    if not 1 <= len(state.source_ref) <= 128:
        raise OperationalInvariantError("dependency source ref must contain 1..128 characters")
    if any(ord(char) < 32 for char in state.source_type + state.source_ref):
        raise OperationalInvariantError("dependency source metadata contains control characters")
    if state.source_version is not None and not 1 <= len(state.source_version) <= 128:
        raise OperationalInvariantError(
            "dependency source version must contain 1..128 characters"
        )
    if state.source_version is not None and any(
        ord(char) < 32 for char in state.source_version
    ):
        raise OperationalInvariantError(
            "dependency source version contains control characters"
        )
    if state.latency_ms < 0 or state.latency_ms > 300_000:
        raise OperationalInvariantError("dependency latency must be within 0..300000 ms")
    return {
        "ready": state.ready,
        "reason_code": reason_code,
        "observed_at": _utc(state.observed_at).isoformat(),
        "source_type": state.source_type,
        "source_ref": state.source_ref,
        "source_version": state.source_version,
        "latency_ms": round(state.latency_ms, 3),
    }


async def sign_operational_target(
    db: AsyncSession,
    command: SignOperationalTarget,
) -> OperationalTarget:
    existing = (
        await db.execute(
            select(OperationalTarget).where(
                OperationalTarget.org_id == command.org_id,
                OperationalTarget.version == command.version,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if (
            existing.capacity != command.capacity
            or existing.slo != command.slo
            or existing.recovery != command.recovery
            or existing.alerting != command.alerting
            or existing.signed_by != command.signed_by
        ):
            raise OperationalInvariantError("operational target version is immutable")
        return existing
    if not _positive_fields(
        command.capacity,
        ("concurrent_campaigns", "devices", "jobs_per_minute", "artifact_bytes"),
    ):
        raise OperationalInvariantError("signed capacity values must be positive")
    if not _positive_fields(command.slo, ("api_p95_ms", "dispatch_lag_p95_seconds")):
        raise OperationalInvariantError("signed SLO values must be positive")
    if not _positive_fields(command.recovery, ("rpo_seconds", "rto_seconds")):
        raise OperationalInvariantError("signed RPO and RTO must be positive")
    if not command.alerting.get("owner") or not command.alerting.get("escalation_ref"):
        raise OperationalInvariantError("alert owner and escalation reference are required")
    target = OperationalTarget(
        org_id=command.org_id,
        version=command.version,
        capacity=dict(command.capacity),
        slo=dict(command.slo),
        recovery=dict(command.recovery),
        alerting=dict(command.alerting),
        status="signed",
        signed_by=command.signed_by,
        signed_at=command.signed_at,
    )
    db.add(target)
    await db.flush()
    return target


async def assess_operational_readiness(
    db: AsyncSession,
    command: AssessOperationalReadiness,
) -> OperationalReadinessAssessment:
    if command.ttl_seconds <= 0 or command.ttl_seconds > 300:
        raise OperationalInvariantError("operational assessment TTL must be within 1..300 seconds")
    target = (
        await db.execute(
            select(OperationalTarget).where(
                OperationalTarget.id == command.target_id,
                OperationalTarget.org_id == command.org_id,
                OperationalTarget.status == "signed",
            )
        )
    ).scalar_one_or_none()
    if target is None:
        raise OperationalInvariantError("signed operational target not found")
    checks = {
        dependency: _dependency_check(
            dependency,
            command.dependency_states.get(dependency),
        )
        for dependency in REQUIRED_DEPENDENCIES
    }
    assessment = OperationalReadinessAssessment(
        org_id=command.org_id,
        target_id=target.id,
        status="ready" if all(item["ready"] for item in checks.values()) else "blocked",
        checks=checks,
        build_ref=command.build_ref,
        schema_version=command.schema_version,
        observed_at=command.observed_at,
        valid_until=command.observed_at + timedelta(seconds=command.ttl_seconds),
    )
    db.add(assessment)
    await db.flush()
    return assessment
