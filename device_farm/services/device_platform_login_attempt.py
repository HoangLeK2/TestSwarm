from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.device_platform_login_attempt import DevicePlatformLoginAttempt
from db.models.enums import DevicePlatformLoginAttemptState, DevicePlatformSessionState
from services.device_platform_session import (
    FACEBOOK_APP_PACKAGE,
    FACEBOOK_PLATFORM,
    mark_active,
    mark_logging_in,
    mark_readiness_observed,
    sanitize_session_evidence,
)
from services.device_reserve.service import claim_device_session, release_device_session
from services.platform_readiness import PlatformReadinessStatus
from services.facebook_session_guard import observe_facebook_readiness_for_device


class DevicePlatformLoginAttemptError(Exception):
    code = "device_platform_login_attempt_error"


class DevicePlatformLoginAttemptConflict(DevicePlatformLoginAttemptError):
    code = "device_platform_login_attempt_conflict"


class ControlledLoginDisabled(DevicePlatformLoginAttemptError):
    code = "controlled_login_disabled"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def controlled_login_enabled() -> bool:
    enabled = os.environ.get("FACEBOOK_CONTROLLED_LOGIN_ENABLED", "false").strip().lower()
    kill_switch = os.environ.get("FACEBOOK_CONTROLLED_LOGIN_KILL_SWITCH", "1").strip().lower()
    return enabled in {"1", "true", "yes", "on"} and kill_switch in {"0", "false", "off", "no"}


def _record_attempt_metric(state: str, reason: str | None) -> None:
    try:
        from web.metrics import facebook_login_attempts_total

        facebook_login_attempts_total.labels(state=state, reason=reason or "unknown").inc()
    except Exception:
        pass


async def get_login_attempt(
    db: AsyncSession,
    *,
    org_id: str,
    attempt_id: str,
) -> DevicePlatformLoginAttempt | None:
    result = await db.execute(
        select(DevicePlatformLoginAttempt).where(
            DevicePlatformLoginAttempt.org_id == org_id,
            DevicePlatformLoginAttempt.id == attempt_id,
        )
    )
    return result.scalar_one_or_none()


async def list_login_attempts(
    db: AsyncSession,
    *,
    org_id: str,
    device_id: str,
    platform: str = FACEBOOK_PLATFORM,
    limit: int = 20,
) -> list[DevicePlatformLoginAttempt]:
    rows = await db.execute(
        select(DevicePlatformLoginAttempt)
        .where(
            DevicePlatformLoginAttempt.org_id == org_id,
            DevicePlatformLoginAttempt.device_id == device_id,
            DevicePlatformLoginAttempt.platform == platform,
        )
        .order_by(DevicePlatformLoginAttempt.created_at.desc())
        .limit(limit)
    )
    return list(rows.scalars().all())


async def start_facebook_login_attempt(
    db: AsyncSession,
    *,
    org_id: str,
    device_id: str,
    account_id: str,
    actor_user_id: str,
    owner_id: str,
    evidence: dict[str, Any] | None = None,
) -> DevicePlatformLoginAttempt:
    now = _utcnow()
    attempt = DevicePlatformLoginAttempt(
        org_id=org_id,
        device_id=device_id,
        platform=FACEBOOK_PLATFORM,
        account_id=account_id,
        state=DevicePlatformLoginAttemptState.PENDING.value,
        reason="operator_login_started",
        created_by_user_id=actor_user_id,
        evidence=sanitize_session_evidence(evidence or {}),
        started_at=now,
    )
    db.add(attempt)
    await db.flush()
    claim = await claim_device_session(
        db,
        device_id=device_id,
        org_id=org_id,
        actor_user_id=actor_user_id,
        owner_type="login",
        owner_id=owner_id,
        ctx={"login_attempt_id": attempt.id, "platform": FACEBOOK_PLATFORM, "account_id": account_id},
    )
    attempt.reserve_session_id = claim.session_id
    attempt.state = DevicePlatformLoginAttemptState.RUNNING.value
    attempt.version = int(attempt.version or 0) + 1
    _record_attempt_metric(attempt.state, attempt.reason)
    await mark_logging_in(
        db,
        org_id=org_id,
        device_id=device_id,
        account_id=account_id,
        reason="operator_login_running",
        login_attempt_id=attempt.id,
        evidence={"reserve_session_id": claim.session_id},
    )
    await db.flush()
    return attempt


async def complete_facebook_login_attempt(
    db: AsyncSession,
    *,
    attempt: DevicePlatformLoginAttempt,
    actor_user_id: str,
    device_serial: str,
    manager: Any = None,
    operator_confirmed: bool = False,
    evidence: dict[str, Any] | None = None,
) -> DevicePlatformLoginAttempt:
    if attempt.state not in {
        DevicePlatformLoginAttemptState.RUNNING.value,
        DevicePlatformLoginAttemptState.READY_TO_CONFIRM.value,
    }:
        raise DevicePlatformLoginAttemptConflict(f"attempt is not running: {attempt.state}")

    readiness = (
        await observe_facebook_readiness_for_device(
            device_serial=device_serial,
            manager=manager,
            package=FACEBOOK_APP_PACKAGE,
        )
        if manager is not None
        else None
    )
    safe_evidence = sanitize_session_evidence(
        {
            **(evidence or {}),
            "actor": actor_user_id,
            "readiness": readiness.evidence() if readiness else None,
        }
    )
    if readiness and readiness.status == PlatformReadinessStatus.CHECKPOINT:
        attempt.state = DevicePlatformLoginAttemptState.CHECKPOINT.value
        attempt.reason = readiness.reason
        attempt.evidence = safe_evidence
        attempt.version = int(attempt.version or 0) + 1
        _record_attempt_metric(attempt.state, attempt.reason)
        await mark_readiness_observed(
            db,
            org_id=attempt.org_id,
            device_id=attempt.device_id,
            account_id=attempt.account_id,
            state=DevicePlatformSessionState.CHECKPOINT,
            reason=readiness.reason,
            evidence=safe_evidence,
        )
        await db.flush()
        return attempt
    if readiness and readiness.status == PlatformReadinessStatus.LOGGED_OUT:
        attempt.state = DevicePlatformLoginAttemptState.FAILED.value
        attempt.reason = readiness.reason
        attempt.evidence = safe_evidence
        attempt.version = int(attempt.version or 0) + 1
        _record_attempt_metric(attempt.state, attempt.reason)
        await mark_readiness_observed(
            db,
            org_id=attempt.org_id,
            device_id=attempt.device_id,
            state=DevicePlatformSessionState.LOGGED_OUT,
            reason=readiness.reason,
            evidence=safe_evidence,
        )
        await db.flush()
        return attempt
    if readiness and readiness.status not in {PlatformReadinessStatus.READY, PlatformReadinessStatus.INCONCLUSIVE}:
        attempt.state = DevicePlatformLoginAttemptState.FAILED.value
        attempt.reason = readiness.reason
        attempt.evidence = safe_evidence
        attempt.version = int(attempt.version or 0) + 1
        _record_attempt_metric(attempt.state, attempt.reason)
        await mark_readiness_observed(
            db,
            org_id=attempt.org_id,
            device_id=attempt.device_id,
            account_id=attempt.account_id,
            state=DevicePlatformSessionState.FAILED,
            reason=readiness.reason,
            evidence=safe_evidence,
        )
        await db.flush()
        return attempt
    if readiness is None and not operator_confirmed:
        raise DevicePlatformLoginAttemptConflict("completion requires readiness check or operator_confirmed=true")

    now = _utcnow()
    attempt.state = DevicePlatformLoginAttemptState.COMPLETED.value
    attempt.reason = "operator_login_completed"
    attempt.completed_at = now
    attempt.evidence = safe_evidence
    attempt.version = int(attempt.version or 0) + 1
    _record_attempt_metric(attempt.state, attempt.reason)
    await mark_active(
        db,
        org_id=attempt.org_id,
        device_id=attempt.device_id,
        account_id=attempt.account_id,
        platform=attempt.platform,
        establishment_method="operator_login_attempt",
        reason="login_attempt_completed",
        login_attempt_id=attempt.id,
        evidence=safe_evidence,
    )
    if attempt.reserve_session_id:
        await release_device_session(
            db,
            device_id=attempt.device_id,
            session_id=attempt.reserve_session_id,
            org_id=attempt.org_id,
            actor_user_id=actor_user_id,
            is_admin=True,
            reason="manual",
            audit_action="session.released.login_completed",
        )
    await db.flush()
    return attempt


async def cancel_facebook_login_attempt(
    db: AsyncSession,
    *,
    attempt: DevicePlatformLoginAttempt,
    actor_user_id: str,
    reason: str,
) -> DevicePlatformLoginAttempt:
    if attempt.state in {
        DevicePlatformLoginAttemptState.COMPLETED.value,
        DevicePlatformLoginAttemptState.CANCELLED.value,
        DevicePlatformLoginAttemptState.FAILED.value,
        DevicePlatformLoginAttemptState.TIMED_OUT.value,
    }:
        return attempt
    attempt.state = DevicePlatformLoginAttemptState.CANCELLED.value
    attempt.reason = reason
    attempt.cancelled_at = _utcnow()
    attempt.version = int(attempt.version or 0) + 1
    _record_attempt_metric(attempt.state, attempt.reason)
    if attempt.reserve_session_id:
        await release_device_session(
            db,
            device_id=attempt.device_id,
            session_id=attempt.reserve_session_id,
            org_id=attempt.org_id,
            actor_user_id=actor_user_id,
            is_admin=True,
            reason="manual",
            audit_action="session.released.login_cancelled",
        )
    await mark_readiness_observed(
        db,
        org_id=attempt.org_id,
        device_id=attempt.device_id,
        account_id=attempt.account_id,
        state=DevicePlatformSessionState.LOGIN_REQUIRED,
        reason=reason,
        evidence={"login_attempt_id": attempt.id, "actor": actor_user_id},
    )
    await db.flush()
    return attempt


async def start_controlled_facebook_login_attempt(*_args: Any, **_kwargs: Any) -> None:
    if not controlled_login_enabled():
        raise ControlledLoginDisabled("controlled Facebook login is disabled by kill switch")
    raise ControlledLoginDisabled("controlled Facebook login executor is not implemented")
