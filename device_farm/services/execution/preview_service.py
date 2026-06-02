"""Preview execution surface — isolated scenario runs (DF-T-04-018)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from db.crud.device import get_devices_by_ids
from db.crud.device_state import get_device_states_map
from db.crud.execution import add_device_to_execution, create_execution, upsert_execution_result
from db.models.enums import DeviceFsmState, DeviceReserveOwnerType, ExecutionKind, ExecutionStatus
from services.campaign.account_resolver import account_to_vars, validate_account_in_org
from services.device_reserve.exceptions import DeviceBusyError, DeviceSessionError
from services.device_reserve.service import claim_device_session
from services.execution.preview_introspection import (
    collect_preview_warnings,
    preview_has_side_effects,
    preview_requires_account,
)
from services.execution.preview_runtime import start_preview_runtime
from services.org_scenario.service import OrgScenarioNotFoundError, get_scenario_body

log = logging.getLogger(__name__)


class PreviewError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        status: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.details = details or {}


@dataclass(slots=True)
class PreviewStartResult:
    execution_id: str
    status: str
    warnings: list[str]
    workflow_id: str | None
    dispatch_source: str | None
    org_scenario_id: str
    device_id: str


async def _load_scenario_steps(
    db: AsyncSession,
    *,
    org_id: str,
    scenario_id: str,
) -> tuple[list[dict], str]:
    try:
        view = await get_scenario_body(db, org_id=org_id, scenario_id=scenario_id)
    except OrgScenarioNotFoundError as exc:
        raise PreviewError("Scenario not found", code="SCENARIO_NOT_FOUND", status=404) from exc

    body = view.body_json if isinstance(view.body_json, dict) else {}
    steps = body.get("steps") or []
    if not isinstance(steps, list) or not steps:
        raise PreviewError(
            "Scenario has no runnable steps",
            code="SCENARIO_NOT_RUNNABLE",
            status=422,
        )
    return steps, view.name


async def _validate_preview_device(
    db: AsyncSession,
    *,
    device_id: str,
    org_id: str,
) -> Any:
    devices = await get_devices_by_ids(db, [device_id])
    device = devices.get(device_id)
    if device is None or device.org_id != org_id:
        raise PreviewError("Device not found", code="DEVICE_NOT_FOUND", status=404)

    snapshots = await get_device_states_map(db, [device_id])
    snapshot = snapshots.get(device_id)
    state = snapshot.state if snapshot else None
    if state != DeviceFsmState.ONLINE.value:
        raise PreviewError("Device is not online", code="DEVICE_OFFLINE", status=409)
    return device


async def start_preview(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    scenario_id: str,
    device_id: str,
    vars: dict[str, Any] | None = None,
    account_id: str | None = None,
    force: bool = False,
    temporal_client: Any = None,
    temporal_config: Any = None,
    manager: Any = None,
) -> PreviewStartResult:
    steps, scenario_name = await _load_scenario_steps(db, org_id=org_id, scenario_id=scenario_id)
    warnings = collect_preview_warnings(steps)

    if preview_requires_account(steps) and not account_id:
        raise PreviewError(
            "Preview requires account for login/social-auth steps",
            code="ACCOUNT_REQUIRED_FOR_PREVIEW",
        )

    if preview_has_side_effects(steps) and not force:
        raise PreviewError(
            "Scenario contains social-effect steps; pass force=true to proceed",
            code="PREVIEW_HAS_SIDE_EFFECT_REQUIRES_FORCE",
            details={"warnings": warnings},
        )

    device = await _validate_preview_device(db, device_id=device_id, org_id=org_id)

    effective_vars = dict(vars or {})
    account_vars: dict[str, Any] = {}
    resolved_account_id: str | None = None
    if account_id:
        from services.campaign.account_resolver import AccountBindingError

        try:
            account = await validate_account_in_org(db, account_id, org_id)
        except AccountBindingError as exc:
            raise PreviewError(str(exc), code=exc.code, status=404) from exc
        account_vars = account_to_vars(account)
        effective_vars = {**effective_vars, **account_vars}
        resolved_account_id = str(account.id)

    execution = await create_execution(
        db,
        run_type="preview",
        kind=ExecutionKind.PREVIEW.value,
        organization_id=org_id,
        campaign_id=None,
        user_id=user_id,
        account_id=resolved_account_id,
        status=ExecutionStatus.PENDING.value,
        meta={
            "preview": True,
            "org_scenario_id": scenario_id,
            "org_scenario_name": scenario_name,
            "preview_warnings": warnings,
        },
        device_config={
            "effective_vars": effective_vars,
            "account_vars": account_vars,
            "device_serial": device.serial or "",
        },
    )
    await add_device_to_execution(db, execution.id, device.id)

    try:
        claim = await claim_device_session(
            db,
            device_id=device.id,
            org_id=org_id,
            actor_user_id=user_id,
            owner_type=DeviceReserveOwnerType.SCENARIO.value,
            owner_id=execution.id,
            ctx={"execution_id": execution.id, "preview": True},
        )
    except DeviceBusyError as exc:
        raise PreviewError(
            "Device is already claimed",
            code="DEVICE_BUSY",
            status=409,
        ) from exc
    except DeviceSessionError as exc:
        raise PreviewError(
            str(exc),
            code=getattr(exc, "code", "DEVICE_CLAIM_FAILED"),
            status=409,
        ) from exc

    started_at = datetime.now(timezone.utc)
    execution.status = ExecutionStatus.RUNNING.value
    execution.started_at = started_at
    execution.device_config = {
        **(execution.device_config or {}),
        "claim_session_id": claim.session_id,
    }
    await upsert_execution_result(
        db,
        execution_id=execution.id,
        device_id=device.id,
        status="running",
        started_at=started_at,
    )

    runtime = await start_preview_runtime(
        db,
        execution=execution,
        org_id=org_id,
        org_scenario_id=scenario_id,
        actor_user_id=user_id,
        effective_vars=effective_vars,
        account_vars=account_vars,
        temporal_client=temporal_client,
        temporal_config=temporal_config,
        manager=manager,
    )

    if not runtime.get("started"):
        execution.status = ExecutionStatus.FAILED.value
        execution.finished_at = datetime.now(timezone.utc)
        execution.device_config = {
            **(execution.device_config or {}),
            "failure_reason": runtime.get("reason") or "runtime_start_failed",
        }
        await upsert_execution_result(
            db,
            execution_id=execution.id,
            device_id=device.id,
            status="failed",
            error_detail=runtime.get("reason"),
            finished_at=execution.finished_at,
        )
        raise PreviewError(
            "Failed to start preview runtime",
            code="PREVIEW_RUNTIME_START_FAILED",
            status=500,
            details={"reason": runtime.get("reason")},
        )

    return PreviewStartResult(
        execution_id=execution.id,
        status=execution.status,
        warnings=warnings,
        workflow_id=runtime.get("workflow_id"),
        dispatch_source=runtime.get("dispatch_source"),
        org_scenario_id=scenario_id,
        device_id=device.id,
    )
