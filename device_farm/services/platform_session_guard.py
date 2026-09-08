"""Platform-neutral device session guard.

Same shape as ``services/platform_readiness.py``: the vocabulary and the decision
ladder live here, the per-platform knowledge (readiness markers, app package)
lives in the platform module. Adding a platform = register a readiness resolver
and one entry in :data:`PLATFORM_APP_PACKAGES`. No caller changes.

``services/facebook_session_guard.py`` is a thin alias layer over this module.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from functools import partial
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
from services.platform_readiness import (
    PlatformReadinessResult,
    PlatformReadinessStatus,
    get_readiness_resolver,
    resolve_platform_readiness,
)

log = logging.getLogger(__name__)
_DEVICE_LOCKS: dict[str, asyncio.Lock] = {}
_DEVICE_LOCKS_GUARD = asyncio.Lock()

DEFAULT_PLATFORM = FACEBOOK_PLATFORM
PLATFORM_APP_PACKAGES: dict[str, str] = {FACEBOOK_PLATFORM: FACEBOOK_APP_PACKAGE}


def platform_app_package(platform: str) -> str | None:
    return PLATFORM_APP_PACKAGES.get((platform or "").strip().casefold())


class PlatformSessionGuardMode(StrEnum):
    OFF = "off"
    SHADOW = "shadow"
    ENFORCE = "enforce"


class PlatformSessionGuardOutcome(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"
    SHADOW_BLOCK = "shadow_block"


@dataclass(frozen=True, slots=True)
class PlatformSessionGuardDecision:
    mode: PlatformSessionGuardMode
    outcome: PlatformSessionGuardOutcome
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
        return self.outcome == PlatformSessionGuardOutcome.BLOCK

    def to_meta(self) -> dict[str, Any]:
        data = asdict(self)
        data["mode"] = self.mode.value
        data["outcome"] = self.outcome.value
        data["checked_at"] = self.checked_at.isoformat()
        return {key: value for key, value in data.items() if value not in (None, {})}


def platform_session_guard_mode() -> PlatformSessionGuardMode:
    raw = os.environ.get(
        "FACEBOOK_SESSION_GUARD_MODE",
        os.environ.get("ACCOUNT_VERIFICATION_MODE", PlatformSessionGuardMode.SHADOW.value),
    ).strip().lower()
    try:
        return PlatformSessionGuardMode(raw)
    except ValueError:
        log.warning("invalid FACEBOOK_SESSION_GUARD_MODE=%r; using shadow", raw)
        return PlatformSessionGuardMode.SHADOW


def _ready_ttl_seconds() -> int:
    try:
        return max(0, min(3600, int(os.environ.get("PLATFORM_SESSION_READY_TTL_SECONDS", "300"))))
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
    platform: str,
    mode: PlatformSessionGuardMode,
    would_block: bool,
    reason: str,
    session: DevicePlatformSession | None,
    expected_account_id: str | None,
    readiness: PlatformReadinessResult | None = None,
    evidence: dict[str, Any] | None = None,
) -> PlatformSessionGuardDecision:
    outcome = (
        PlatformSessionGuardOutcome.BLOCK
        if would_block and mode == PlatformSessionGuardMode.ENFORCE
        else PlatformSessionGuardOutcome.SHADOW_BLOCK
        if would_block
        else PlatformSessionGuardOutcome.ALLOW
    )
    decision = PlatformSessionGuardDecision(
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
            platform=platform,
            mode=decision.mode.value,
            outcome=decision.outcome.value,
            reason=decision.reason,
        ).inc()
    except Exception:
        pass
    return decision


def _provenance_decision(
    *,
    platform: str,
    session: DevicePlatformSession | None,
    account_id: str | None,
    mode: PlatformSessionGuardMode,
    now: datetime,
) -> PlatformSessionGuardDecision:
    decide = partial(_decision, platform=platform, mode=mode, expected_account_id=account_id)
    if mode == PlatformSessionGuardMode.OFF or not account_id:
        return decide(would_block=False, reason="guard_disabled_or_no_account", session=session)
    if session is None:
        return decide(would_block=True, reason=f"{platform}_session_missing", session=None)
    if session.account_id and session.account_id != account_id:
        return decide(would_block=True, reason=f"{platform}_session_account_mismatch", session=session)
    state = session.state
    if state == DevicePlatformSessionState.ACTIVE.value and session.account_id == account_id:
        if _is_fresh(session.last_ready_at, now=now):
            return decide(would_block=False, reason=f"{platform}_session_ready_cache", session=session)
        return decide(would_block=False, reason=f"{platform}_session_active_needs_readiness_refresh", session=session)
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
        return decide(would_block=True, reason=f"{platform}_session_{state}", session=session)
    return decide(would_block=True, reason=f"{platform}_session_unrecognized_state", session=session)


async def observe_platform_readiness_for_device(
    *,
    device_serial: str,
    manager: Any,
    platform: str = DEFAULT_PLATFORM,
    package: str | None = None,
    app_version: str | None = None,
) -> PlatformReadinessResult:
    started = time.perf_counter()
    package = package or platform_app_package(platform) or FACEBOOK_APP_PACKAGE
    client = manager.get_device(device_serial) if manager is not None else None
    if client is None:
        return PlatformReadinessResult(
            PlatformReadinessStatus.INCONCLUSIVE,
            "device_offline",
            _utcnow(),
            app_package=package,
            app_version=app_version,
        )
    lock = await _device_lock(device_serial)
    # Warm the resolver registry here, on this thread: get_readiness_resolver
    # imports services/<platform>_readiness.py on a miss, and importing from
    # the worker thread below can deadlock against an import on the main one.
    get_readiness_resolver(platform)

    def inspect() -> PlatformReadinessResult:
        client.launch_app(package)
        hierarchy = client.hierarchy_xml(force_refresh=True) or ""
        result = resolve_platform_readiness(
            hierarchy, platform=platform, package=package, app_version=app_version
        )
        return PlatformReadinessResult(
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
        result = PlatformReadinessResult(PlatformReadinessStatus.INCONCLUSIVE, "inspection_timeout", _utcnow(), app_package=package, app_version=app_version)
    except Exception as exc:
        log.warning("%s readiness inspection failed device=%s: %s", platform, device_serial, exc)
        result = PlatformReadinessResult(PlatformReadinessStatus.INCONCLUSIVE, "inspection_failed", _utcnow(), app_package=package, app_version=app_version)
    try:
        from web.metrics import facebook_readiness_checks_total

        facebook_readiness_checks_total.labels(
            platform=platform, status=result.status.value, reason=result.reason
        ).inc()
    except Exception:
        pass
    return result


def _live_probe_required(
    provenance: PlatformSessionGuardDecision,
    *,
    mode: PlatformSessionGuardMode,
    account_id: str | None,
) -> bool:
    """True when the provenance decision alone cannot settle the guard.

    Mirrors the short-circuit ladder in guard_platform_session so callers can
    plan (and parallelise) device probes before entering a DB-bound loop.
    """
    if mode == PlatformSessionGuardMode.OFF or not account_id:
        return False
    if provenance.reason.endswith("_session_ready_cache") or provenance.blocks_execution:
        return False
    return True


async def platform_session_live_probe_required(
    db: AsyncSession,
    *,
    org_id: str,
    device_id: str,
    account_id: str | None,
    platform: str = DEFAULT_PLATFORM,
    mode: PlatformSessionGuardMode | None = None,
) -> bool:
    """Whether guard_platform_session(live_check=True) would hit the device.

    Lets a caller batch the expensive readiness probes concurrently and then
    feed them back via guard_platform_session(readiness=...), instead of
    serialising one 6s device round-trip per device.
    """
    selected_mode = mode or platform_session_guard_mode()
    session = await get_platform_session(
        db, org_id=org_id, device_id=device_id, platform=platform
    )
    provenance = _provenance_decision(
        platform=platform, session=session, account_id=account_id, mode=selected_mode, now=_utcnow()
    )
    return _live_probe_required(provenance, mode=selected_mode, account_id=account_id)


async def guard_platform_session(
    db: AsyncSession,
    *,
    org_id: str,
    device_id: str,
    account_id: str | None,
    platform: str = DEFAULT_PLATFORM,
    mode: PlatformSessionGuardMode | None = None,
    manager: Any = None,
    device_serial: str | None = None,
    live_check: bool = False,
    readiness: PlatformReadinessResult | None = None,
) -> PlatformSessionGuardDecision:
    selected_mode = mode or platform_session_guard_mode()
    session = await get_platform_session(db, org_id=org_id, device_id=device_id, platform=platform)
    now = _utcnow()
    provenance = _provenance_decision(
        platform=platform, session=session, account_id=account_id, mode=selected_mode, now=now
    )
    if not live_check or not _live_probe_required(
        provenance, mode=selected_mode, account_id=account_id
    ):
        return provenance
    if readiness is None and (manager is None or not device_serial):
        return provenance

    if readiness is None:
        readiness = await observe_platform_readiness_for_device(
            device_serial=device_serial, manager=manager, platform=platform
        )
    evidence = readiness.evidence()
    decide = partial(
        _decision,
        platform=platform,
        mode=selected_mode,
        expected_account_id=account_id,
        readiness=readiness,
        evidence=evidence,
    )
    updated = session
    if readiness.status == PlatformReadinessStatus.READY:
        if session and session.state == DevicePlatformSessionState.ACTIVE.value and session.account_id == account_id:
            updated = await mark_readiness_observed(
                db,
                org_id=org_id,
                device_id=device_id,
                account_id=account_id,
                state=DevicePlatformSessionState.ACTIVE,
                reason=f"{platform}_readiness_ready",
                evidence=evidence,
            )
            return decide(would_block=False, reason=f"{platform}_readiness_ready", session=updated)
        updated = await mark_readiness_observed(
            db,
            org_id=org_id,
            device_id=device_id,
            state=DevicePlatformSessionState.SUSPECTED_MISMATCH,
            reason=f"{platform}_ready_without_matching_provenance",
            evidence=evidence,
        )
        return decide(would_block=True, reason=f"{platform}_ready_without_matching_provenance", session=updated)
    state_by_readiness = {
        PlatformReadinessStatus.LOGGED_OUT: DevicePlatformSessionState.LOGGED_OUT,
        PlatformReadinessStatus.CHECKPOINT: DevicePlatformSessionState.CHECKPOINT,
        PlatformReadinessStatus.UNRESPONSIVE: DevicePlatformSessionState.FAILED,
        PlatformReadinessStatus.UNSUPPORTED_BUILD: DevicePlatformSessionState.FAILED,
    }
    next_state = state_by_readiness.get(readiness.status)
    if next_state is not None:
        updated = await mark_readiness_observed(
            db,
            org_id=org_id,
            device_id=device_id,
            account_id=account_id if readiness.status == PlatformReadinessStatus.CHECKPOINT else None,
            state=next_state,
            reason=readiness.reason,
            evidence=evidence,
        )
        return decide(would_block=True, reason=readiness.reason, session=updated)
    return decide(would_block=False, reason=f"{platform}_readiness_inconclusive", session=session)
