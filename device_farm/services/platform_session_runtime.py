"""Runtime bridge for establishing an account-scoped Facebook session."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.crud.account import lookup_account_org_id
from db.models.device import Device
from db.models.enums import DevicePlatformSessionState
from db.models.execution import Execution, ExecutionDevice
from services.device_platform_session import (
    get_platform_session,
    mark_active,
    mark_login_required,
    mark_readiness_observed,
)
from services.platform_readiness import PlatformReadinessResult, PlatformReadinessStatus
from tenancy.context import tenant_context

# Guard reasons are ``f"{platform}_session_{state}"`` (services/platform_session_guard.py),
# so match the suffix instead of a per-platform literal.
_LOGIN_RECOVERABLE_GUARD_SUFFIXES = (
    "_session_missing",
    "_session_unknown",
    "_session_logged_out",
    "_session_login_required",
    "_session_logging_in",
    "_session_expired",
    "_session_failed",
)


def guard_reason_allows_login_recovery(reason: str | None) -> bool:
    return str(reason or "").endswith(_LOGIN_RECOVERABLE_GUARD_SUFFIXES)


def platform_session_requirement_platforms(scenario: dict[str, Any]) -> set[str]:
    """Return platforms whose session is a precondition for this scenario.

    Canonical org-scenario shape:
        {"requirements": {"platform_session": {"required": true, "platform": "facebook"}}}

    Builtin ScenarioTemplate has no requirements column yet, so templates use a
    tag token: ``requires-platform-session:<platform>``. This keeps the model
    platform-neutral without a database migration.
    """
    platforms: set[str] = set()
    requirements = scenario.get("requirements")
    if isinstance(requirements, dict):
        raw = requirements.get("platform_session") or requirements.get(
            "platformSession"
        )
        entries = raw if isinstance(raw, list) else [raw]
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("required") is False:
                continue
            platform = str(
                entry.get("platform") or scenario.get("platform") or ""
            ).strip()
            if platform:
                platforms.add(platform)

    tags = str(scenario.get("tags") or "")
    for token in tags.replace(",", " ").split():
        marker = "requires-platform-session:"
        if token.startswith(marker):
            platform = token[len(marker) :].strip()
            if platform:
                platforms.add(platform)
    return platforms


def scenario_registry_platform_session_requirements(
    registry: dict[str, Any],
    scenario_refs: list[dict[str, Any]],
) -> set[str]:
    """Follow selected scenarios and dependencies, collecting required platforms."""
    by_id = registry.get("by_id") or {}
    by_campaign_name = registry.get("by_campaign_name") or {}
    by_template_name = registry.get("by_template_name") or {}
    pending = [
        by_id.get(str(ref.get("scenario_id") or ""))
        for ref in scenario_refs
        if ref.get("scenario_id")
    ]
    seen: set[int] = set()
    platforms: set[str] = set()

    def walk_steps(steps: list[Any]) -> list[dict[str, Any]]:
        nested_refs: list[dict[str, Any]] = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            if step.get("type") == "run_scenario":
                nested_refs.append(step)
            for key in ("steps", "then", "else"):
                nested_refs.extend(walk_steps(step.get(key) or []))
            for branch in step.get("branches") or []:
                if isinstance(branch, dict):
                    nested_refs.extend(walk_steps(branch.get("steps") or []))
        return nested_refs

    while pending:
        scenario = pending.pop()
        if not isinstance(scenario, dict) or id(scenario) in seen:
            continue
        seen.add(id(scenario))
        platforms.update(platform_session_requirement_platforms(scenario))
        for step in walk_steps(scenario.get("steps") or []):
            nested = None
            scenario_id = str(step.get("scenario_id") or "").strip()
            scenario_name = str(step.get("scenario_name") or "").strip()
            if scenario_id:
                nested = by_id.get(scenario_id)
            if nested is None and scenario_name:
                nested = by_campaign_name.get(scenario_name) or by_template_name.get(
                    scenario_name
                )
            pending.append(nested)
    return platforms


def scenario_registry_has_platform_login_gate(
    registry: dict[str, Any],
    scenario_refs: list[dict[str, Any]],
) -> bool:
    """Follow only selected scenarios and their run_scenario dependencies."""
    by_id = registry.get("by_id") or {}
    by_campaign_name = registry.get("by_campaign_name") or {}
    by_template_name = registry.get("by_template_name") or {}
    pending = [
        by_id.get(str(ref.get("scenario_id") or ""))
        for ref in scenario_refs
        if ref.get("scenario_id")
    ]
    seen: set[int] = set()

    def walk_steps(steps: list[Any]) -> tuple[bool, list[dict[str, Any]]]:
        nested_refs: list[dict[str, Any]] = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            if (
                step.get("type") == "platform_session_gate"
                and step.get("phase", "preflight") == "preflight"
            ):
                return True, nested_refs
            if step.get("type") == "run_scenario":
                nested_refs.append(step)
            for key in ("steps", "then", "else"):
                found, refs = walk_steps(step.get(key) or [])
                nested_refs.extend(refs)
                if found:
                    return True, nested_refs
            for branch in step.get("branches") or []:
                if isinstance(branch, dict):
                    found, refs = walk_steps(branch.get("steps") or [])
                    nested_refs.extend(refs)
                    if found:
                        return True, nested_refs
        return False, nested_refs

    while pending:
        scenario = pending.pop()
        if not isinstance(scenario, dict) or id(scenario) in seen:
            continue
        seen.add(id(scenario))
        found, nested_refs = walk_steps(scenario.get("steps") or [])
        if found:
            return True
        for step in nested_refs:
            nested = None
            scenario_id = str(step.get("scenario_id") or "").strip()
            scenario_name = str(step.get("scenario_name") or "").strip()
            if scenario_id:
                nested = by_id.get(scenario_id)
            if nested is None and scenario_name:
                nested = by_campaign_name.get(scenario_name) or by_template_name.get(
                    scenario_name
                )
            pending.append(nested)
    return False


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _session_cache_is_fresh(last_ready_at: datetime | None) -> bool:
    if last_ready_at is None:
        return False
    if last_ready_at.tzinfo is None:
        last_ready_at = last_ready_at.replace(tzinfo=timezone.utc)
    try:
        ttl = max(
            0,
            min(3600, int(os.environ.get("PLATFORM_SESSION_READY_TTL_SECONDS", "300"))),
        )
    except ValueError:
        ttl = 300
    return (_utcnow() - last_ready_at).total_seconds() <= ttl


async def _resolve_runtime_target(
    db: AsyncSession,
    *,
    identity: dict[str, str | None],
    device_serial: str,
) -> tuple[str, str, str]:
    account_id = str(identity.get("account_id") or "").strip()
    execution_id = str(identity.get("execution_id") or "").strip()
    if execution_id:
        row = (
            await db.execute(
                select(
                    Execution.org_id, Execution.account_id, ExecutionDevice.device_id
                )
                .join(ExecutionDevice, ExecutionDevice.execution_id == Execution.id)
                .join(Device, Device.id == ExecutionDevice.device_id)
                .where(Execution.id == execution_id, Device.serial == device_serial)
            )
        ).one_or_none()
        if row is None:
            raise ValueError(
                "Facebook session gate device is not part of the execution"
            )
        execution_account_id = str(row.account_id or "").strip()
        if account_id and execution_account_id and account_id != execution_account_id:
            raise ValueError(
                "Facebook session gate account conflicts with execution account"
            )
        account_id = account_id or execution_account_id
        if not account_id:
            raise ValueError("Facebook session gate requires an execution account")
        return str(row.org_id), str(row.device_id), account_id

    if not account_id:
        raise ValueError("Facebook session gate requires account_id or execution_id")
    org_id = await lookup_account_org_id(db, account_id)
    if not org_id:
        raise ValueError("Facebook session gate account was not found")
    with tenant_context(str(org_id)):
        device_id = (
            await db.execute(
                select(Device.id).where(
                    Device.org_id == org_id, Device.serial == device_serial
                )
            )
        ).scalar_one_or_none()
    if not device_id:
        raise ValueError(
            "Facebook session gate device was not found in the account organization"
        )
    return str(org_id), str(device_id), account_id


def _decision(
    *,
    allowed: bool,
    ready: bool,
    reason: str,
    org_id: str,
    device_id: str,
    account_id: str,
    state: str | None,
) -> dict[str, Any]:
    return {
        "allowed": allowed,
        "ready": ready,
        "reason": reason,
        "org_id": org_id,
        "device_id": device_id,
        "account_id": account_id,
        "state": state,
    }


async def apply_platform_session_gate(
    db: AsyncSession,
    *,
    org_id: str,
    device_id: str,
    account_id: str,
    phase: str,
    readiness: PlatformReadinessResult,
    login_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    session = await get_platform_session(db, org_id=org_id, device_id=device_id)
    evidence = {"source": "scenario_session_gate", "readiness": readiness.evidence()}

    if phase == "preflight":
        if readiness.status == PlatformReadinessStatus.READY:
            if (
                session is not None
                and session.state == DevicePlatformSessionState.ACTIVE.value
                and session.account_id == account_id
            ):
                session = await mark_readiness_observed(
                    db,
                    org_id=org_id,
                    device_id=device_id,
                    account_id=account_id,
                    state=DevicePlatformSessionState.ACTIVE,
                    reason="scenario_preflight_ready",
                    evidence=evidence,
                )
                return _decision(
                    allowed=True,
                    ready=True,
                    reason="facebook_session_ready",
                    org_id=org_id,
                    device_id=device_id,
                    account_id=account_id,
                    state=session.state,
                )
            reason = (
                "facebook_session_account_mismatch"
                if session is not None
                and session.account_id
                and session.account_id != account_id
                else "facebook_ready_without_matching_provenance"
            )
            session = await mark_readiness_observed(
                db,
                org_id=org_id,
                device_id=device_id,
                state=DevicePlatformSessionState.SUSPECTED_MISMATCH,
                reason=reason,
                evidence=evidence,
            )
            return _decision(
                allowed=False,
                ready=False,
                reason=reason,
                org_id=org_id,
                device_id=device_id,
                account_id=account_id,
                state=session.state,
            )

        if readiness.status == PlatformReadinessStatus.LOGGED_OUT:
            session = await mark_login_required(
                db,
                org_id=org_id,
                device_id=device_id,
                reason="scenario_login_surface_visible",
                expected_account_id=account_id,
                evidence=evidence,
            )
            return _decision(
                allowed=True,
                ready=False,
                reason="facebook_login_required",
                org_id=org_id,
                device_id=device_id,
                account_id=account_id,
                state=session.state,
            )

        if (
            readiness.status == PlatformReadinessStatus.INCONCLUSIVE
            and session is not None
            and session.state == DevicePlatformSessionState.ACTIVE.value
            and session.account_id == account_id
            and _session_cache_is_fresh(session.last_ready_at)
        ):
            return _decision(
                allowed=True,
                ready=True,
                reason="facebook_session_ready_cache",
                org_id=org_id,
                device_id=device_id,
                account_id=account_id,
                state=session.state,
            )
        if (
            readiness.status == PlatformReadinessStatus.INCONCLUSIVE
            and session is not None
            and session.state
            in {
                DevicePlatformSessionState.LOGGED_OUT.value,
                DevicePlatformSessionState.LOGIN_REQUIRED.value,
            }
        ):
            return _decision(
                allowed=True,
                ready=False,
                reason="facebook_login_required",
                org_id=org_id,
                device_id=device_id,
                account_id=account_id,
                state=session.state,
            )

    provenance_matches = bool(
        login_provenance
        and login_provenance.get("org_id") == org_id
        and login_provenance.get("device_id") == device_id
        and login_provenance.get("account_id") == account_id
        and login_provenance.get("login_required") is True
    )
    if (
        phase == "confirm"
        and readiness.status == PlatformReadinessStatus.READY
        and provenance_matches
    ):
        session = await mark_active(
            db,
            org_id=org_id,
            device_id=device_id,
            account_id=account_id,
            establishment_method="scenario_login",
            reason="scenario_login_confirmed",
            evidence=evidence,
        )
        return _decision(
            allowed=True,
            ready=True,
            reason="facebook_login_confirmed",
            org_id=org_id,
            device_id=device_id,
            account_id=account_id,
            state=session.state,
        )

    state_by_status = {
        PlatformReadinessStatus.CHECKPOINT: DevicePlatformSessionState.CHECKPOINT,
        PlatformReadinessStatus.LOGGED_OUT: DevicePlatformSessionState.LOGGED_OUT,
        PlatformReadinessStatus.UNRESPONSIVE: DevicePlatformSessionState.FAILED,
        PlatformReadinessStatus.UNSUPPORTED_BUILD: DevicePlatformSessionState.FAILED,
    }
    next_state = state_by_status.get(readiness.status)
    if next_state is not None:
        session = await mark_readiness_observed(
            db,
            org_id=org_id,
            device_id=device_id,
            account_id=account_id
            if next_state == DevicePlatformSessionState.CHECKPOINT
            else None,
            state=next_state,
            reason=readiness.reason,
            evidence=evidence,
        )
    reason = (
        "facebook_login_provenance_missing"
        if phase == "confirm" and readiness.status == PlatformReadinessStatus.READY
        else readiness.reason
    )
    return _decision(
        allowed=False,
        ready=False,
        reason=reason,
        org_id=org_id,
        device_id=device_id,
        account_id=account_id,
        state=session.state if session is not None else None,
    )


def run_platform_session_gate(
    *,
    identity: dict[str, str | None],
    device_serial: str,
    phase: str,
    readiness: PlatformReadinessResult,
    login_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from db.database import activity_session, run_activity_coro_blocking

    async def run() -> dict[str, Any]:
        async with activity_session() as db:
            org_id, device_id, account_id = await _resolve_runtime_target(
                db,
                identity=identity,
                device_serial=device_serial,
            )
            with tenant_context(org_id):
                return await apply_platform_session_gate(
                    db,
                    org_id=org_id,
                    device_id=device_id,
                    account_id=account_id,
                    phase=phase,
                    readiness=readiness,
                    login_provenance=login_provenance,
                )

    return run_activity_coro_blocking(run())
