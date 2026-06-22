"""Campaign fan-out dispatcher (DF-T-04-008)."""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from db.crud import campaign_entity as campaign_repo
from db.crud import campaign_target as target_repo
from db.crud.execution import (
    add_device_to_execution,
    create_execution,
    finish_execution,
    get_execution,
    upsert_execution_result,
)
from db.models.campaign import Campaign
from db.models.device import Device
from db.models.enums import CampaignStatus, DeviceReserveOwnerType, ExecutionStatus
from db.models.execution import Execution
from services.campaign.constants import MAX_DISPATCH_TARGETS
from services.campaign.device_validator import (
    DispatchValidationError,
    ResolvedTargetEntry,
    resolve_dispatch_targets,
    validate_devices_for_dispatch,
)
from services.campaign.account_resolver import (
    AccountBindingError,
    ResolvedDeviceAccount,
    assert_dispatch_account_guard,
    resolve_accounts_for_devices,
)
from services.campaign.override_resolver import (
    merge_effective_vars,
    validate_per_device_accounts_size,
    validate_per_device_overrides_size,
)
from services.device_reserve.exceptions import DeviceBusyError, DeviceSessionError
from services.device_reserve.service import claim_device_session, release_device_session
from web.metrics import (
    campaign_dispatch_claim_fail_count,
    campaign_dispatch_duration_seconds,
    campaign_dispatch_targets_count,
)

log = logging.getLogger(__name__)

DispatchStrategy = Literal["parallel", "sequential"]


class CampaignDispatchError(Exception):
    def __init__(self, message: str, *, code: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True, slots=True)
class FanOutExecutionView:
    execution_id: str
    device_id: str
    status: str
    effective_vars: dict[str, Any]
    account_id: str | None = None
    failure_reason: str | None = None
    claim_session_id: str | None = None

    def to_dict(self, *, include_vars: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {
            "execution_id": self.execution_id,
            "device_id": self.device_id,
            "status": self.status,
            "account_id": self.account_id,
            "failure_reason": self.failure_reason,
            "claim_session_id": self.claim_session_id,
        }
        if include_vars:
            out["effective_vars"] = self.effective_vars
        return out


@dataclass(frozen=True, slots=True)
class FanOutResult:
    dispatch_id: str
    campaign_id: str
    dispatch_strategy: DispatchStrategy
    executions: list[FanOutExecutionView]

    def to_dict(self, *, include_vars: bool = True) -> dict[str, Any]:
        return {
            "dispatch_id": self.dispatch_id,
            "campaign_id": self.campaign_id,
            "dispatch_strategy": self.dispatch_strategy,
            "executions": [e.to_dict(include_vars=include_vars) for e in self.executions],
            "target_count": len(self.executions),
        }


class CampaignDispatcher:
    """Resolve targets, validate devices, snapshot membership, and fan-out executions."""

    async def fan_out(
        self,
        db: AsyncSession,
        *,
        campaign: Campaign,
        org_id: str,
        actor_user_id: str,
        device_ids: list[str] | None = None,
        device_group_ids: list[str] | None = None,
        dispatch_strategy: DispatchStrategy = "parallel",
        allow_partial: bool = False,
        require_online: bool = True,
        devices_by_id: dict[str, Device] | None = None,
    ) -> FanOutResult:
        if campaign.org_id != org_id:
            raise CampaignDispatchError("Campaign not found", code="CAMPAIGN_NOT_FOUND")

        try:
            validate_per_device_overrides_size(campaign.per_device_overrides)
            validate_per_device_accounts_size(campaign.per_device_accounts)
        except ValueError as exc:
            raise CampaignDispatchError(str(exc), code=getattr(exc, "code", "INVALID_OVERRIDES")) from exc

        try:
            entries = await resolve_dispatch_targets(
                db,
                org_id=org_id,
                device_ids=device_ids,
                device_group_ids=device_group_ids,
            )
        except DispatchValidationError as exc:
            raise CampaignDispatchError(str(exc), code=exc.code, details=exc.details) from exc

        if not entries:
            raise CampaignDispatchError(
                "Dispatch target is empty",
                code="EMPTY_DISPATCH_TARGET",
            )

        if len(entries) > MAX_DISPATCH_TARGETS:
            raise CampaignDispatchError(
                f"Dispatch target exceeds limit of {MAX_DISPATCH_TARGETS} devices",
                code="DISPATCH_TARGET_TOO_LARGE",
                details={"limit": MAX_DISPATCH_TARGETS, "requested": len(entries)},
            )

        validation = await validate_devices_for_dispatch(
            db,
            org_id=org_id,
            entries=entries,
            require_online=require_online,
            allow_partial=allow_partial,
        )

        if validation.cross_org_ids:
            raise CampaignDispatchError(
                "One or more devices were not found in this organization",
                code="DEVICE_NOT_FOUND",
                details={"device_ids": validation.cross_org_ids},
            )

        if validation.not_found_ids:
            raise CampaignDispatchError(
                "One or more devices were not found",
                code="DEVICE_NOT_FOUND",
                details={"device_ids": validation.not_found_ids},
            )

        if validation.offline_ids and not allow_partial:
            raise CampaignDispatchError(
                "One or more target devices are offline",
                code="DEVICE_OFFLINE",
                details={"device_ids": validation.offline_ids},
            )

        valid_entries = validation.entries
        if not valid_entries:
            raise CampaignDispatchError(
                "Dispatch target is empty after validation",
                code="EMPTY_DISPATCH_TARGET",
            )

        try:
            await assert_dispatch_account_guard(db, campaign=campaign, org_id=org_id)
        except AccountBindingError as exc:
            raise CampaignDispatchError(str(exc), code=exc.code, details=exc.details) from exc

        device_ids_ordered = [e.device_id for e in valid_entries]
        account_by_device = await resolve_accounts_for_devices(
            db,
            campaign=campaign,
            org_id=org_id,
            device_ids=device_ids_ordered,
        )
        try:
            from web.metrics import campaign_account_resolve_batch_size

            unique_accounts = {
                r.account_id for r in account_by_device.values() if r.account_id
            }
            campaign_account_resolve_batch_size.observe(len(unique_accounts))
        except Exception:
            pass

        device_map = devices_by_id if devices_by_id is not None else validation.devices_by_id
        dispatch_id = str(uuid.uuid4())
        campaign_dispatch_targets_count.inc(len(valid_entries))
        scenario_refs = await resolve_campaign_scenario_refs(db, campaign)
        if not scenario_refs:
            raise CampaignDispatchError(
                "Campaign has no scenarios. Link an org scenario or add steps in the flow editor.",
                code="CAMPAIGN_NO_SCENARIOS",
            )

        await target_repo.insert_campaign_targets(
            db,
            campaign_id=campaign.id,
            dispatch_id=dispatch_id,
            rows=[
                (e.device_id, e.source_kind, e.source_ref_id)
                for e in valid_entries
            ],
        )

        executions: list[FanOutExecutionView] = []
        claim_now = valid_entries if dispatch_strategy == "parallel" else valid_entries[:1]
        queue_later = valid_entries[1:] if dispatch_strategy == "sequential" else []

        for entry in claim_now:
            executions.append(
                await self._create_device_execution(
                    db,
                    campaign=campaign,
                    org_id=org_id,
                    actor_user_id=actor_user_id,
                    entry=entry,
                    dispatch_id=dispatch_id,
                    dispatch_strategy=dispatch_strategy,
                    scenario_refs=scenario_refs,
                    device_map=device_map,
                    claim_device=True,
                    resolved_account=account_by_device.get(entry.device_id),
                )
            )

        for entry in queue_later:
            executions.append(
                await self._create_queued_execution(
                    db,
                    campaign=campaign,
                    entry=entry,
                    dispatch_id=dispatch_id,
                    dispatch_strategy=dispatch_strategy,
                    scenario_refs=scenario_refs,
                    resolved_account=account_by_device.get(entry.device_id),
                )
            )

        if dispatch_strategy == "sequential" and not any(
            view.status == ExecutionStatus.RUNNING.value for view in executions
        ):
            for index, view in enumerate(executions):
                if view.status != ExecutionStatus.PENDING.value:
                    continue
                execution = await get_execution(db, view.execution_id)
                if execution is None:
                    continue
                promoted = await self.activate_queued_execution(
                    db,
                    execution=execution,
                    campaign=campaign,
                    org_id=org_id,
                    actor_user_id=actor_user_id,
                )
                if promoted is None:
                    continue
                executions[index] = promoted
                if promoted.status == ExecutionStatus.RUNNING.value:
                    break

        from services.campaign.fsm import can_dispatch

        if can_dispatch(campaign.status):
            from services.campaign.lifecycle import apply_campaign_transition

            await apply_campaign_transition(
                db,
                campaign,
                CampaignStatus.RUNNING,
                org_id=org_id,
                user_id=actor_user_id,
                reason="dispatch",
            )
            has_active_execution = any(
                view.status
                in {
                    ExecutionStatus.PENDING.value,
                    ExecutionStatus.RUNNING.value,
                    ExecutionStatus.PAUSED.value,
                }
                for view in executions
            )
            if not has_active_execution:
                await apply_campaign_transition(
                    db,
                    campaign,
                    CampaignStatus.FAILED,
                    org_id=org_id,
                    user_id=actor_user_id,
                    reason="dispatch_no_runnable_targets",
                )

        await db.flush()
        return FanOutResult(
            dispatch_id=dispatch_id,
            campaign_id=campaign.id,
            dispatch_strategy=dispatch_strategy,
            executions=executions,
        )

    async def _create_device_execution(
        self,
        db: AsyncSession,
        *,
        campaign: Campaign,
        org_id: str,
        actor_user_id: str,
        entry: ResolvedTargetEntry,
        dispatch_id: str,
        dispatch_strategy: DispatchStrategy,
        scenario_refs: list[dict[str, Any]],
        device_map: dict[str, Device],
        claim_device: bool,
        resolved_account: ResolvedDeviceAccount | None = None,
    ) -> FanOutExecutionView:
        effective_vars = merge_effective_vars(
            campaign_vars=campaign.variables,
            per_device_overrides=campaign.per_device_overrides,
            device_id=entry.device_id,
        )
        account_vars = (resolved_account.account_vars if resolved_account else {}) or {}
        if account_vars:
            effective_vars = {**effective_vars, **account_vars}

        device = device_map.get(entry.device_id)
        device_serial = device.serial if device else ""
        account_id = resolved_account.account_id if resolved_account else None

        execution = await create_execution(
            db,
            run_type="campaign_device",
            campaign_id=campaign.id,
            organization_id=campaign.org_id,
            user_id=campaign.created_by or campaign.user_id,
            account_id=account_id,
            status=ExecutionStatus.PENDING.value,
            meta={
                "dispatch_id": dispatch_id,
                "dispatch_strategy": dispatch_strategy,
                "org_scenario_refs": scenario_refs,
                "source_kind": entry.source_kind,
                "source_ref_id": entry.source_ref_id,
            },
            device_config={
                "effective_vars": effective_vars,
                "account_vars": account_vars,
                "device_serial": device_serial,
            },
        )
        await add_device_to_execution(db, execution.id, entry.device_id)

        claim_session_id: str | None = None
        failure_reason: str | None = None
        status = ExecutionStatus.RUNNING.value

        if resolved_account and resolved_account.unavailable:
            failure_reason = resolved_account.failure_reason or "account_unavailable"
            status = ExecutionStatus.FAILED.value
            execution.status = status
            execution.finished_at = datetime.now(timezone.utc)
            execution.device_config = {
                **(execution.device_config or {}),
                "failure_reason": failure_reason,
            }
            await upsert_execution_result(
                db,
                execution_id=execution.id,
                device_id=entry.device_id,
                status="failed",
                error_detail=failure_reason,
                finished_at=execution.finished_at,
            )
            return FanOutExecutionView(
                execution_id=execution.id,
                device_id=entry.device_id,
                status=status,
                effective_vars=effective_vars,
                account_id=account_id,
                failure_reason=failure_reason,
            )

        if claim_device:
            try:
                claim = await claim_device_session(
                    db,
                    device_id=entry.device_id,
                    org_id=org_id,
                    actor_user_id=actor_user_id,
                    owner_type=DeviceReserveOwnerType.CAMPAIGN.value,
                    owner_id=campaign.id,
                    ctx={"dispatch_id": dispatch_id, "execution_id": execution.id},
                )
                claim_session_id = claim.session_id
                execution.device_config = {
                    **(execution.device_config or {}),
                    "claim_session_id": claim_session_id,
                }
                execution.status = ExecutionStatus.RUNNING.value
                execution.started_at = datetime.now(timezone.utc)
                await upsert_execution_result(
                    db,
                    execution_id=execution.id,
                    device_id=entry.device_id,
                    status="running",
                    started_at=execution.started_at,
                )
            except (DeviceBusyError, DeviceSessionError) as exc:
                campaign_dispatch_claim_fail_count.inc()
                failure_reason = "device_claim_failed"
                status = ExecutionStatus.FAILED.value
                execution.status = status
                execution.finished_at = datetime.now(timezone.utc)
                cfg = {
                    **(execution.device_config or {}),
                    "failure_reason": failure_reason,
                }
                if isinstance(exc, DeviceSessionError):
                    cfg["claim_error"] = exc.code
                execution.device_config = cfg
                await upsert_execution_result(
                    db,
                    execution_id=execution.id,
                    device_id=entry.device_id,
                    status="failed",
                    error_detail=failure_reason,
                    finished_at=execution.finished_at,
                )

        return FanOutExecutionView(
            execution_id=execution.id,
            device_id=entry.device_id,
            status=status,
            effective_vars=effective_vars,
            account_id=account_id,
            failure_reason=failure_reason,
            claim_session_id=claim_session_id,
        )

    async def _create_queued_execution(
        self,
        db: AsyncSession,
        *,
        campaign: Campaign,
        entry: ResolvedTargetEntry,
        dispatch_id: str,
        dispatch_strategy: DispatchStrategy,
        scenario_refs: list[dict[str, Any]],
        resolved_account: ResolvedDeviceAccount | None = None,
    ) -> FanOutExecutionView:
        effective_vars = merge_effective_vars(
            campaign_vars=campaign.variables,
            per_device_overrides=campaign.per_device_overrides,
            device_id=entry.device_id,
        )
        account_vars = (resolved_account.account_vars if resolved_account else {}) or {}
        if account_vars:
            effective_vars = {**effective_vars, **account_vars}
        account_id = resolved_account.account_id if resolved_account else None

        execution = await create_execution(
            db,
            run_type="campaign_device",
            campaign_id=campaign.id,
            organization_id=campaign.org_id,
            user_id=campaign.created_by or campaign.user_id,
            account_id=account_id,
            status=ExecutionStatus.PENDING.value,
            meta={
                "dispatch_id": dispatch_id,
                "dispatch_strategy": dispatch_strategy,
                "org_scenario_refs": scenario_refs,
                "source_kind": entry.source_kind,
                "source_ref_id": entry.source_ref_id,
                "queued": True,
            },
            device_config={
                "effective_vars": effective_vars,
                "account_vars": account_vars,
            },
        )
        await add_device_to_execution(db, execution.id, entry.device_id)
        await upsert_execution_result(
            db,
            execution_id=execution.id,
            device_id=entry.device_id,
            status="pending",
        )
        return FanOutExecutionView(
            execution_id=execution.id,
            device_id=entry.device_id,
            status=ExecutionStatus.PENDING.value,
            effective_vars=effective_vars,
            account_id=account_id,
        )

    async def activate_queued_execution(
        self,
        db: AsyncSession,
        *,
        execution: Execution,
        campaign: Campaign,
        org_id: str,
        actor_user_id: str,
    ) -> FanOutExecutionView | None:
        """Claim device and mark a queued sequential execution as running."""
        meta = execution.meta or {}
        if execution.status != ExecutionStatus.PENDING.value or not meta.get("queued"):
            return None

        from db.crud.execution import list_execution_devices

        devices = await list_execution_devices(db, execution.id)
        if not devices:
            return None
        device_id = devices[0].id
        scenario_refs = meta.get("org_scenario_refs")
        if not isinstance(scenario_refs, list) or not scenario_refs:
            scenario_refs = await resolve_campaign_scenario_refs(db, campaign)

        from services.campaign.account_resolver import resolve_accounts_for_devices

        account_by_device = await resolve_accounts_for_devices(
            db,
            campaign=campaign,
            org_id=org_id,
            device_ids=[device_id],
        )

        cfg = execution.device_config or {}
        effective_vars = dict(cfg.get("effective_vars") or {})
        account_id = execution.account_id
        claim_session_id: str | None = cfg.get("claim_session_id")
        failure_reason: str | None = None
        status = ExecutionStatus.RUNNING.value

        try:
            claim = await claim_device_session(
                db,
                device_id=device_id,
                org_id=org_id,
                actor_user_id=actor_user_id,
                owner_type=DeviceReserveOwnerType.CAMPAIGN.value,
                owner_id=campaign.id,
                ctx={
                    "dispatch_id": meta.get("dispatch_id"),
                    "execution_id": execution.id,
                },
            )
            claim_session_id = claim.session_id
            execution.device_config = {
                **cfg,
                "claim_session_id": claim_session_id,
                "device_serial": devices[0].serial,
            }
            execution.status = ExecutionStatus.RUNNING.value
            execution.started_at = datetime.now(timezone.utc)
            meta = dict(meta)
            meta.pop("queued", None)
            execution.meta = meta
            await upsert_execution_result(
                db,
                execution_id=execution.id,
                device_id=device_id,
                status="running",
                started_at=execution.started_at,
            )
            from services.execution.event_publisher import enqueue_execution_event
            from services.execution.event_types import EXECUTION_STARTED

            await enqueue_execution_event(
                db,
                event_type=EXECUTION_STARTED,
                execution_id=execution.id,
                organization_id=org_id,
                campaign_id=campaign.id,
                payload={"dispatch_id": meta.get("dispatch_id")},
                execution=execution,
            )
        except (DeviceBusyError, DeviceSessionError):
            campaign_dispatch_claim_fail_count.inc()
            failure_reason = "device_claim_failed"
            status = ExecutionStatus.FAILED.value
            execution.status = status
            execution.finished_at = datetime.now(timezone.utc)
            await upsert_execution_result(
                db,
                execution_id=execution.id,
                device_id=device_id,
                status="failed",
                error_detail=failure_reason,
                finished_at=execution.finished_at,
            )

        resolved = account_by_device.get(device_id)
        return FanOutExecutionView(
            execution_id=execution.id,
            device_id=device_id,
            status=status,
            effective_vars=effective_vars,
            account_id=account_id or (resolved.account_id if resolved else None),
            failure_reason=failure_reason,
            claim_session_id=claim_session_id,
        )


def _scenario_refs_from_campaign(campaign: Campaign) -> list[dict[str, Any]]:
    from services.campaign.scenario_sources import org_scenario_refs_from_campaign

    return org_scenario_refs_from_campaign(campaign)


async def resolve_campaign_scenario_refs(
    db: AsyncSession,
    campaign: Campaign,
) -> list[dict[str, Any]]:
    from services.campaign.scenario_sources import resolve_campaign_scenario_refs as _resolve

    return await _resolve(db, campaign)


async def dispatch_campaign(
    db: AsyncSession,
    *,
    campaign_id: str,
    org_id: str,
    actor_user_id: str,
    device_ids: list[str] | None = None,
    device_group_ids: list[str] | None = None,
    dispatch_strategy: DispatchStrategy = "parallel",
    allow_partial: bool = False,
    require_online: bool = True,
) -> FanOutResult:
    started = time.perf_counter()
    try:
        campaign = await campaign_repo.get_campaign_entity(
            db, campaign_id, for_update=True
        )
        if campaign is None or campaign.org_id != org_id:
            raise CampaignDispatchError("Campaign not found", code="CAMPAIGN_NOT_FOUND")
        if campaign.status == CampaignStatus.ARCHIVED.value:
            raise CampaignDispatchError("Campaign not found", code="CAMPAIGN_NOT_FOUND")

        from services.campaign.fsm import can_dispatch, is_running_like, normalize_status

        if not can_dispatch(campaign.status):
            code = "INVALID_TRANSITION"
            if is_running_like(campaign.status):
                code = "CAMPAIGN_ALREADY_RUNNING"
            raise CampaignDispatchError(
                f"Cannot dispatch campaign in status {normalize_status(campaign.status).value}",
                code=code,
                details={"status": normalize_status(campaign.status).value},
            )

        dispatcher = CampaignDispatcher()
        return await dispatcher.fan_out(
            db,
            campaign=campaign,
            org_id=org_id,
            actor_user_id=actor_user_id,
            device_ids=device_ids,
            device_group_ids=device_group_ids,
            dispatch_strategy=dispatch_strategy,
            allow_partial=allow_partial,
            require_online=require_online,
        )
    finally:
        campaign_dispatch_duration_seconds.observe(time.perf_counter() - started)


async def release_execution_device_claim(
    db: AsyncSession,
    execution: Execution,
    *,
    org_id: str,
    actor_user_id: str,
) -> None:
    """Release device reserve session when a fan-out execution reaches terminal state."""
    cfg = execution.device_config or {}
    session_id = cfg.get("claim_session_id")
    if not session_id:
        return
    from db.crud.execution import list_execution_devices

    linked = await list_execution_devices(db, execution.id)
    device_id = linked[0].id if linked else None
    if not device_id:
        return
    try:
        await release_device_session(
            db,
            device_id=device_id,
            session_id=session_id,
            org_id=org_id,
            actor_user_id=actor_user_id,
            is_admin=True,
            reason="execution_terminal",
            audit_action="session.released.execution_terminal",
        )
    except Exception:
        log.warning(
            "release_execution_device_claim failed execution=%s device=%s",
            execution.id,
            device_id,
            exc_info=True,
        )


async def finish_fan_out_execution(
    db: AsyncSession,
    execution: Execution,
    *,
    org_id: str,
    actor_user_id: str,
    status: str = "completed",
) -> None:
    """Mark execution terminal and release any campaign dispatch claim."""
    await finish_execution(db, execution.id, status=status)
    await release_execution_device_claim(
        db, execution, org_id=org_id, actor_user_id=actor_user_id
    )
    if execution.campaign_id:
        from services.campaign.aggregator_scheduler import request_campaign_status_evaluation

        await request_campaign_status_evaluation(
            org_id=org_id,
            campaign_id=execution.campaign_id,
            user_id=actor_user_id,
        )
