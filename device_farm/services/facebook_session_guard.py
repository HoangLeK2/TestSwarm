from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from db.models.device_platform_session import DevicePlatformSession
from db.models.enums import DevicePlatformSessionState
from services.device_platform_session import (
    FACEBOOK_APP_PACKAGE,
    FACEBOOK_PLATFORM,
    get_platform_session,
    mark_readiness_observed,
)
from services.facebook_readiness import FacebookReadinessResult, FacebookReadinessStatus, resolve_facebook_readiness

log = logging.getLogger(__name__)
_DEVICE_LOCKS: dict[str, asyncio.Lock] = {}
_DEVICE_LOCKS_GUARD = asyncio.Lock()


class FacebookSessionGuardMode(StrEnum):
    OFF = "off"
    SHADOW = "shadow"
    ENFORCE = "enforce"


class FacebookSessionGuardOutcome(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"
    SHADOW_BLOCK = "shadow_block"


@dataclass(frozen=True, slots=True)
class FacebookSessionGuardDecision:
    mode: FacebookSessionGuardMode
    outcome: FacebookSessionGuardOutcome
    reason: str
    checked_at: datetime
    session_id: str | None = None
    session_state: str | None = None
    expected_account_id: str | None = None
    observed_account_id: str | None = None
    readiness_status: str | None = None
    evidence: dict[str, Any] | None = None

    @property
    def blocks_execution(self) -> bool:
        return self.outcome == FacebookSessionGuardOutcome.BLOCK

    def to_meta(self) -> dict[str, Any]:
        data = asdict(self)
        data["mode"] = self.mode.value
        data["outcome"] = self.outcome.value
        data["checked_at"] = self.checked_at.isoformat()
        return {key: value for key, value in data.items() if value not in (None, {})}


def facebook_session_guard_mode() -> FacebookSessionGuardMode:
    raw = os.environ.get(
        "FACEBOOK_SESSION_GUARD_MODE",
        os.environ.get("ACCOUNT_VERIFICATION_MODE", FacebookSessionGuardMode.SHADOW.value),
    ).strip().lower()
    try:
        return FacebookSessionGuardMode(raw)
    except ValueError:
        log.warning("invalid FACEBOOK_SESSION_GUARD_MODE=%r; using shadow", raw)
        return FacebookSessionGuardMode.SHADOW


def _ready_ttl_seconds() -> int:
    try:
        return max(0, min(3600, int(os.environ.get("FACEBOOK_SESSION_READY_TTL_SECONDS", "300"))))
    except ValueError:
        return 300


def _check_timeout_seconds() -> float:
    try:
        return max(1.0, min(30.0, float(os.environ.get("FACEBOOK_SESSION_CHECK_TIMEOUT_SECONDS", "6"))))
    except ValueError:
        return 6.0


async def _device_lock(serial: str) -> asyncio.Lock:
    async with _DEVICE_LOCKS_GUARD:
        return _DEVICE_LOCKS.setdefault(serial, asyncio.Lock())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _is_fresh(ts: datetime | None, *, now: datetime) -> bool:
    if ts is None:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (now - ts).total_seconds() <= _ready_ttl_seconds()


def _decision(
    *,
    mode: FacebookSessionGuardMode,
    would_block: bool,
    reason: str,
    session: DevicePlatformSession | None,
    expected_account_id: str | None,
    readiness: FacebookReadinessResult | None = None,
    evidence: dict[str, Any] | None = None,
) -> FacebookSessionGuardDecision:
    outcome = (
        FacebookSessionGuardOutcome.BLOCK
        if would_block and mode == FacebookSessionGuardMode.ENFORCE
        else FacebookSessionGuardOutcome.SHADOW_BLOCK
        if would_block
        else FacebookSessionGuardOutcome.ALLOW
    )
    decision = FacebookSessionGuardDecision(
        mode=mode,
        outcome=outcome,
        reason=reason,
        checked_at=_utcnow(),
        session_id=session.id if session else None,
        session_state=session.state if session else None,
        expected_account_id=expected_account_id,
        observed_account_id=session.account_id if session else None,
        readiness_status=readiness.status.value if readiness else None,
        evidence=evidence,
    )
    try:
        from web.metrics import facebook_session_guard_decisions_total

        facebook_session_guard_decisions_total.labels(
            mode=decision.mode.value,
            outcome=decision.outcome.value,
            reason=decision.reason,
        ).inc()
    except Exception:
        pass
    return decision


def _provenance_decision(
    *,
    session: DevicePlatformSession | None,
    account_id: str | None,
    mode: FacebookSessionGuardMode,
    now: datetime,
) -> FacebookSessionGuardDecision:
    if mode == FacebookSessionGuardMode.OFF or not account_id:
        return _decision(mode=mode, would_block=False, reason="guard_disabled_or_no_account", session=session, expected_account_id=account_id)
    if session is None:
        return _decision(mode=mode, would_block=True, reason="facebook_session_missing", session=None, expected_account_id=account_id)
    if session.account_id and session.account_id != account_id:
        return _decision(mode=mode, would_block=True, reason="facebook_session_account_mismatch", session=session, expected_account_id=account_id)
    state = session.state
    if state == DevicePlatformSessionState.ACTIVE.value and session.account_id == account_id:
        if _is_fresh(session.last_ready_at, now=now):
            return _decision(mode=mode, would_block=False, reason="facebook_session_ready_cache", session=session, expected_account_id=account_id)
        return _decision(mode=mode, would_block=False, reason="facebook_session_active_needs_readiness_refresh", session=session, expected_account_id=account_id)
    blocking_states = {
        DevicePlatformSessionState.UNKNOWN.value,
        DevicePlatformSessionState.LOGGED_OUT.value,
        DevicePlatformSessionState.LOGIN_REQUIRED.value,
        DevicePlatformSessionState.LOGGING_IN.value,
        DevicePlatformSessionState.SUSPECTED_MISMATCH.value,
        DevicePlatformSessionState.CHECKPOINT.value,
        DevicePlatformSessionState.EXPIRED.value,
        DevicePlatformSessionState.FAILED.value,
    }
    if state in blocking_states:
        return _decision(mode=mode, would_block=True, reason=f"facebook_session_{state}", session=session, expected_account_id=account_id)
    return _decision(mode=mode, would_block=True, reason="facebook_session_unrecognized_state", session=session, expected_account_id=account_id)


async def observe_facebook_readiness_for_device(
    *,
    device_serial: str,
    manager: Any,
    package: str = FACEBOOK_APP_PACKAGE,
    app_version: str | None = None,
) -> FacebookReadinessResult:
    started = time.perf_counter()
    client = manager.get_device(device_serial) if manager is not None else None
    if client is None:
        return FacebookReadinessResult(
            FacebookReadinessStatus.INCONCLUSIVE,
            "device_offline",
            _utcnow(),
            app_package=package,
            app_version=app_version,
        )
    lock = await _device_lock(device_serial)

    def inspect() -> FacebookReadinessResult:
        client.launch_app(package)
        hierarchy = client.hierarchy_xml(force_refresh=True) or ""
        result = resolve_facebook_readiness(hierarchy, package=package, app_version=app_version)
        return FacebookReadinessResult(
            status=result.status,
            reason=result.reason,
            attempted_at=result.attempted_at,
            hierarchy_sha256=result.hierarchy_sha256,
            app_package=result.app_package,
            app_version=result.app_version,
            matched_markers=(*result.matched_markers, f"duration_ms:{int((time.perf_counter() - started) * 1000)}"),
        )

    await lock.acquire()
    inspection = asyncio.create_task(asyncio.to_thread(inspect))
    inspection.add_done_callback(lambda _task: lock.release() if lock.locked() else None)
    try:
        result = await asyncio.wait_for(asyncio.shield(inspection), timeout=_check_timeout_seconds())
    except TimeoutError:
        result = FacebookReadinessResult(FacebookReadinessStatus.INCONCLUSIVE, "inspection_timeout", _utcnow(), app_package=package, app_version=app_version)
    except Exception as exc:
        log.warning("facebook readiness inspection failed device=%s: %s", device_serial, exc)
        result = FacebookReadinessResult(FacebookReadinessStatus.INCONCLUSIVE, "inspection_failed", _utcnow(), app_package=package, app_version=app_version)
    try:
        from web.metrics import facebook_readiness_checks_total

        facebook_readiness_checks_total.labels(status=result.status.value, reason=result.reason).inc()
    except Exception:
        pass
    return result


def _live_probe_required(
    provenance: FacebookSessionGuardDecision,
    *,
    mode: FacebookSessionGuardMode,
    account_id: str | None,
) -> bool:
    """True when the provenance decision alone cannot settle the guard.

    Mirrors the short-circuit ladder in guard_facebook_session so callers can
    plan (and parallelise) device probes before entering a DB-bound loop.
    """
    if mode == FacebookSessionGuardMode.OFF or not account_id:
        return False
    if provenance.reason == "facebook_session_ready_cache" or provenance.blocks_execution:
        return False
    return True


async def facebook_session_live_probe_required(
    db: AsyncSession,
    *,
    org_id: str,
    device_id: str,
    account_id: str | None,
    mode: FacebookSessionGuardMode | None = None,
) -> bool:
    """Whether guard_facebook_session(live_check=True) would hit the device.

    Lets a caller batch the expensive readiness probes concurrently and then
    feed them back via guard_facebook_session(readiness=...), instead of
    serialising one 6s device round-trip per device.
    """
    selected_mode = mode or facebook_session_guard_mode()
    session = await get_platform_session(
        db, org_id=org_id, device_id=device_id, platform=FACEBOOK_PLATFORM
    )
    provenance = _provenance_decision(
        session=session, account_id=account_id, mode=selected_mode, now=_utcnow()
    )
    return _live_probe_required(provenance, mode=selected_mode, account_id=account_id)


async def guard_facebook_session(
    db: AsyncSession,
    *,
    org_id: str,
    device_id: str,
    account_id: str | None,
    mode: FacebookSessionGuardMode | None = None,
    manager: Any = None,
    device_serial: str | None = None,
    live_check: bool = False,
    readiness: FacebookReadinessResult | None = None,
) -> FacebookSessionGuardDecision:
    selected_mode = mode or facebook_session_guard_mode()
    session = await get_platform_session(db, org_id=org_id, device_id=device_id, platform=FACEBOOK_PLATFORM)
    now = _utcnow()
    provenance = _provenance_decision(session=session, account_id=account_id, mode=selected_mode, now=now)
    if not live_check or not _live_probe_required(
        provenance, mode=selected_mode, account_id=account_id
    ):
        return provenance
    if readiness is None and (manager is None or not device_serial):
        return provenance

    if readiness is None:
        readiness = await observe_facebook_readiness_for_device(device_serial=device_serial, manager=manager)
    evidence = readiness.evidence()
    updated = session
    if readiness.status == FacebookReadinessStatus.READY:
        if session and session.state == DevicePlatformSessionState.ACTIVE.value and session.account_id == account_id:
            updated = await mark_readiness_observed(
                db,
                org_id=org_id,
                device_id=device_id,
                account_id=account_id,
                state=DevicePlatformSessionState.ACTIVE,
                reason="facebook_readiness_ready",
                evidence=evidence,
            )
            return _decision(mode=selected_mode, would_block=False, reason="facebook_readiness_ready", session=updated, expected_account_id=account_id, readiness=readiness, evidence=evidence)
        updated = await mark_readiness_observed(
            db,
            org_id=org_id,
            device_id=device_id,
            state=DevicePlatformSessionState.SUSPECTED_MISMATCH,
            reason="facebook_ready_without_matching_provenance",
            evidence=evidence,
        )
        return _decision(mode=selected_mode, would_block=True, reason="facebook_ready_without_matching_provenance", session=updated, expected_account_id=account_id, readiness=readiness, evidence=evidence)
    state_by_readiness = {
        FacebookReadinessStatus.LOGGED_OUT: DevicePlatformSessionState.LOGGED_OUT,
        FacebookReadinessStatus.CHECKPOINT: DevicePlatformSessionState.CHECKPOINT,
        FacebookReadinessStatus.UNRESPONSIVE: DevicePlatformSessionState.FAILED,
        FacebookReadinessStatus.UNSUPPORTED_BUILD: DevicePlatformSessionState.FAILED,
    }
    next_state = state_by_readiness.get(readiness.status)
    if next_state is not None:
        updated = await mark_readiness_observed(
            db,
            org_id=org_id,
            device_id=device_id,
            account_id=account_id if readiness.status == FacebookReadinessStatus.CHECKPOINT else None,
            state=next_state,
            reason=readiness.reason,
            evidence=evidence,
        )
        return _decision(mode=selected_mode, would_block=True, reason=readiness.reason, session=updated, expected_account_id=account_id, readiness=readiness, evidence=evidence)
    return _decision(mode=selected_mode, would_block=False, reason="facebook_readiness_inconclusive", session=session, expected_account_id=account_id, readiness=readiness, evidence=evidence)
