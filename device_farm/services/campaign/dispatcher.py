"""Campaign fan-out dispatcher (DF-T-04-008)."""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.crud import campaign_entity as campaign_repo
from db.crud import campaign_target as target_repo
from db.crud.execution import (
    finish_execution,
    get_execution,
    upsert_execution_result,
)
from db.models.activity import ActivityLog
from db.models.campaign import Campaign
from db.models.device import Device
from db.models.device_fsm import DeviceFsmSnapshot, DeviceStateTransition
from db.models.device_reserve_session import DeviceReserveSession
from db.models.enums import (
    CampaignStatus,
    DeviceFsmEvent,
    DeviceFsmState,
    DeviceRegistryStatus,
    DeviceReserveOwnerType,
    ExecutionStatus,
)
from db.models.execution import Execution, ExecutionDevice, ExecutionResult
from db.models.external_entity import ExecutionEntityAssignment, ExternalEntity
from services.campaign.constants import MAX_DISPATCH_TARGETS
from services.campaign.device_validator import (
    DispatchValidationError,
    ResolvedTargetEntry,
    resolve_dispatch_targets,
    validate_devices_for_dispatch,
)
from services.campaign.entity_allocation import (
    EntityAllocationError,
    EntityAllocationPlan,
    SourcePoolSpec,
    load_source_pool_snapshot,
    plan_from_source_pool,
    plan_one_per_device,
)
from services.campaign.scenario_sources import build_campaign_scenario_registry
from services.campaign.source_pool_steps import source_pool_from_scenario_registry
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
from services.device_reserve.service import (
    DEFAULT_TTL_SEC,
    claim_device_session,
    release_device_session,
)
from services.device_state.events import (
    DeviceStateChangedEvent,
    publish_device_state_changed,
)
from web.metrics import fsm_transition_count
from web.metrics import (
    campaign_dispatch_claim_fail_count,
    campaign_dispatch_duration_seconds,
    campaign_dispatch_targets_count,
)

log = logging.getLogger(__name__)

DispatchStrategy = Literal["parallel", "sequential"]
DISPATCH_PERSIST_CHUNK_SIZE = 100


def _external_entity_snapshot(entity: ExternalEntity) -> dict[str, Any]:
    return {
        "id": entity.id,
        "platform": entity.platform,
        "entity_type": entity.entity_type,
        "external_id": entity.external_id,
        "canonical_url": entity.canonical_url,
        "display_name": entity.display_name,
        "identity_key": entity.identity_key,
        "attributes": dict(entity.current_attributes or {}),
        "metrics": dict(entity.current_metrics or {}),
        "last_seen_at": entity.last_seen_at.isoformat() if entity.last_seen_at else None,
    }


def _normalize_output_prefix(raw: str | None) -> str:
    prefix = "".join(
        char if char.isascii() and (char.isalnum() or char == "_") else "_"
        for char in str(raw or "").strip().upper()
    ).strip("_")
    return prefix[:32]


def _prefixed_entity_vars(prefix: str, entity: ExternalEntity) -> dict[str, Any]:
    if not prefix:
        return {}
    return {
        f"{prefix}_ENTITY_ID": entity.id,
        f"{prefix}_PLATFORM": entity.platform,
        f"{prefix}_ENTITY_TYPE": entity.entity_type,
        f"{prefix}_EXTERNAL_ID": entity.external_id or "",
        f"{prefix}_URL": entity.canonical_url or "",
        f"{prefix}_NAME": entity.display_name,
    }


def _with_external_entity_vars(
    effective_vars: dict[str, Any],
    entity: ExternalEntity | None,
    *,
    source_pool: SourcePoolSpec | None = None,
) -> dict[str, Any]:
    if entity is None:
        return effective_vars
    output_prefix = _normalize_output_prefix(
        source_pool.output_prefix if source_pool is not None else None
    )
    target_vars = {
        **effective_vars,
        "TARGET_ENTITY_ID": entity.id,
        "TARGET_PLATFORM": entity.platform,
        "TARGET_ENTITY_TYPE": entity.entity_type,
        "TARGET_EXTERNAL_ID": entity.external_id or "",
        "TARGET_URL": entity.canonical_url or "",
        "TARGET_NAME": entity.display_name,
        **_prefixed_entity_vars(output_prefix, entity),
    }
    attributes = (
        entity.current_attributes
        if isinstance(entity.current_attributes, dict)
        else {}
    )
    locator = (
        attributes.get("locator")
        if isinstance(attributes.get("locator"), dict)
        else {}
    )
    selector = (
        locator.get("selector")
        if isinstance(locator.get("selector"), dict)
        else {}
    )
    fallback_selector = (
        locator.get("fallback_selector")
        if isinstance(locator.get("fallback_selector"), dict)
        else {}
    )
    name = entity.display_name
    is_facebook_group = entity.platform == "facebook" and entity.entity_type == "group"
    default_selector_by = "descriptionStartsWith" if is_facebook_group else "text"
    default_selector_value = f"{name}," if is_facebook_group else name
    default_fallback_by = "descriptionContains" if is_facebook_group else "textContains"
    prefixed_locator_vars = (
        {
            f"{output_prefix}_SEARCH_QUERY": str(locator.get("search_query") or name),
            f"{output_prefix}_SELECTOR_BY": str(
                selector.get("by") or default_selector_by
            ),
            f"{output_prefix}_SELECTOR_VALUE": str(
                selector.get("value") or default_selector_value
            ),
            f"{output_prefix}_FALLBACK_SELECTOR_BY": str(
                fallback_selector.get("by") or default_fallback_by
            ),
            f"{output_prefix}_FALLBACK_SELECTOR_VALUE": str(
                fallback_selector.get("value") or name
            ),
        }
        if output_prefix
        else {}
    )
    return {
        **target_vars,
        "TARGET_SEARCH_QUERY": str(locator.get("search_query") or name),
        "TARGET_SELECTOR_BY": str(selector.get("by") or default_selector_by),
        "TARGET_SELECTOR_VALUE": str(selector.get("value") or default_selector_value),
        "TARGET_FALLBACK_SELECTOR_BY": str(
            fallback_selector.get("by") or default_fallback_by
        ),
        "TARGET_FALLBACK_SELECTOR_VALUE": str(
            fallback_selector.get("value") or name
        ),
        "TARGET_LOCATOR": locator,
        **prefixed_locator_vars,
        **(
            {"GROUP_NAME": name, "TARGET_GROUP_NAME": name}
            if is_facebook_group
            else {}
        ),
    }


async def _apply_facebook_session_guard_to_accounts(
    db: AsyncSession,
    *,
    org_id: str,
    account_by_device: dict[str, ResolvedDeviceAccount],
    device_map: dict[str, Device],
    allow_login_recovery: bool = False,
) -> dict[str, ResolvedDeviceAccount]:
    guarded: dict[str, ResolvedDeviceAccount] = dict(account_by_device)
    from services.facebook_session_guard import guard_facebook_session
    from services.facebook_session_runtime import guard_reason_allows_login_recovery

    for device_id, resolved in account_by_device.items():
        if not resolved.account_id:
            continue
        decision = await guard_facebook_session(
            db,
            org_id=org_id,
            device_id=device_id,
            account_id=resolved.account_id,
            device_serial=getattr(device_map.get(device_id), "serial", None),
            live_check=False,
        )
        deferred_to_login = (
            allow_login_recovery
            and decision.blocks_execution
            and guard_reason_allows_login_recovery(decision.reason)
        )
        session_guard = {
            **decision.to_meta(),
            **({"deferred_to_scenario_login": True} if deferred_to_login else {}),
        }
        guarded[device_id] = replace(
            resolved,
            unavailable=resolved.unavailable or (decision.blocks_execution and not deferred_to_login),
            failure_reason=(
                resolved.failure_reason
                if resolved.unavailable
                else decision.reason
                if decision.blocks_execution and not deferred_to_login
                else resolved.failure_reason
            ),
            session_guard=session_guard,
        )
    return guarded


def _assignment_values(
    *,
    campaign: Campaign,
    dispatch_id: str,
    execution_id: str,
    device_id: str,
    entity: ExternalEntity | None,
    assigned_at: datetime,
) -> dict[str, Any] | None:
    if entity is None:
        return None
    return {
        "id": str(uuid.uuid4()),
        "org_id": campaign.org_id,
        "dispatch_id": dispatch_id,
        "execution_id": execution_id,
        "device_id": device_id,
        "external_entity_id": entity.id,
        "assignment_key": "primary",
        "status": "assigned",
        "snapshot": _external_entity_snapshot(entity),
        "assigned_at": assigned_at,
        "completed_at": None,
    }


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
    external_entity_id: str | None = None

    def to_dict(self, *, include_vars: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {
            "execution_id": self.execution_id,
            "device_id": self.device_id,
            "status": self.status,
            "account_id": self.account_id,
            "failure_reason": self.failure_reason,
            "claim_session_id": self.claim_session_id,
            "external_entity_id": self.external_entity_id,
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
    # Carried forward so start_execution_runtime does not re-resolve and
    # re-build the very same scenario bodies in the same request. Both stay
    # out of to_dict() — they are internal handoff state, not API payload.
    scenario_refs: list[dict[str, Any]] | None = None
    scenario_registry: dict[str, Any] | None = None

    def to_dict(self, *, include_vars: bool = True) -> dict[str, Any]:
        return {
            "dispatch_id": self.dispatch_id,
            "campaign_id": self.campaign_id,
            "dispatch_strategy": self.dispatch_strategy,
            "executions": [e.to_dict(include_vars=include_vars) for e in self.executions],
            "target_count": len(self.executions),
        }


@dataclass(frozen=True, slots=True)
class DispatchPreview:
    campaign_id: str
    allocation_policy: str
    device_ids: list[str]
    devices_by_id: dict[str, Device]
    allocation: EntityAllocationPlan


@dataclass(frozen=True, slots=True)
class _PreparedFanOutExecution:
    execution_values: dict[str, Any]
    link_values: dict[str, Any]
    result_values: dict[str, Any]
    assignment_values: dict[str, Any] | None
    view: FanOutExecutionView


@dataclass(frozen=True, slots=True)
class _CampaignClaimRequest:
    device_id: str
    execution_id: str


@dataclass(frozen=True, slots=True)
class _CampaignClaimResult:
    session_id: str | None = None
    failure_reason: str | None = None
    claim_error: str | None = None


async def _plan_entity_assignments(
    db: AsyncSession,
    *,
    org_id: str,
    device_ids: list[str],
    device_group_ids: list[str] | None,
    external_entity_ids: list[str] | None,
    source_pool: SourcePoolSpec | None,
    allocation_snapshot: list[tuple[str, str]] | None,
    allocation_policy: str,
    lock_sources: bool,
) -> EntityAllocationPlan:
    snapshot = list(allocation_snapshot or [])
    if snapshot:
        if source_pool is None:
            raise CampaignDispatchError(
                "Allocation snapshot requires a source pool",
                code="ENTITY_ALLOCATION_SNAPSHOT_INVALID",
            )
        snapshot_device_ids = [device_id for device_id, _ in snapshot]
        snapshot_entity_ids = [entity_id for _, entity_id in snapshot]
        if (
            snapshot_device_ids != device_ids
            or len(snapshot_entity_ids) != len(set(snapshot_entity_ids))
        ):
            raise CampaignDispatchError(
                "Allocation preview is stale; preview the mapping again",
                code="ENTITY_ALLOCATION_SNAPSHOT_STALE",
                details={
                    "device_ids": device_ids,
                    "snapshot_device_ids": snapshot_device_ids,
                },
            )
        entities = await load_source_pool_snapshot(
            db,
            org_id=org_id,
            spec=source_pool,
            entity_ids=snapshot_entity_ids,
            lock_sources=lock_sources,
        )
        if len(entities) != len(snapshot_entity_ids):
            raise CampaignDispatchError(
                "Allocation preview is stale; preview the mapping again",
                code="ENTITY_ALLOCATION_SNAPSHOT_STALE",
                details={"external_entity_ids": snapshot_entity_ids},
            )
        return plan_one_per_device(device_ids=device_ids, entities=entities)

    requested_entity_ids = list(external_entity_ids or [])
    if requested_entity_ids:
        if device_group_ids:
            raise CampaignDispatchError(
                "External entity assignment requires explicit device IDs",
                code="ENTITY_ASSIGNMENT_REQUIRES_EXPLICIT_DEVICES",
            )
        if len(requested_entity_ids) != len(set(requested_entity_ids)):
            raise CampaignDispatchError(
                "External entities must be unique within one dispatch",
                code="DUPLICATE_EXTERNAL_ENTITY",
            )
        if len(requested_entity_ids) != len(device_ids):
            raise CampaignDispatchError(
                "External entity count must match the valid device count",
                code="ENTITY_ASSIGNMENT_COUNT_MISMATCH",
                details={
                    "entity_count": len(requested_entity_ids),
                    "device_count": len(device_ids),
                },
            )
        from db.crud.external_entity import get_external_entities_by_ids

        entities = await get_external_entities_by_ids(
            db,
            org_id=org_id,
            entity_ids=requested_entity_ids,
        )
        if len(entities) != len(requested_entity_ids):
            found = {entity.id for entity in entities}
            raise CampaignDispatchError(
                "One or more external entities were not found in this organization",
                code="EXTERNAL_ENTITY_NOT_FOUND",
                details={
                    "entity_ids": [
                        entity_id
                        for entity_id in requested_entity_ids
                        if entity_id not in found
                    ]
                },
            )
        try:
            return plan_one_per_device(device_ids=device_ids, entities=entities)
        except EntityAllocationError as exc:
            raise CampaignDispatchError(
                str(exc), code=exc.code, details=exc.details
            ) from exc

    if source_pool is None:
        return EntityAllocationPlan(assignments=[], available_count=0)

    try:
        return await plan_from_source_pool(
            db,
            org_id=org_id,
            device_ids=device_ids,
            spec=source_pool,
            policy=allocation_policy,
            lock_sources=lock_sources,
        )
    except EntityAllocationError as exc:
        raise CampaignDispatchError(
            str(exc), code=exc.code, details=exc.details
        ) from exc


async def _derive_source_pool_from_scenarios(
    db: AsyncSession,
    *,
    campaign: Campaign,
    org_id: str,
    scenario_refs: list[dict[str, Any]],
) -> SourcePoolSpec | None:
    if not scenario_refs:
        return None
    registry = await build_campaign_scenario_registry(
        db,
        campaign=campaign,
        org_id=org_id,
        scenario_refs=scenario_refs,
    )
    return source_pool_from_scenario_registry(registry)


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
        external_entity_ids: list[str] | None = None,
        source_pool: SourcePoolSpec | None = None,
        allocation_snapshot: list[tuple[str, str]] | None = None,
        allocation_policy: str = "one_per_device",
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

        scenario_refs = await resolve_campaign_scenario_refs(db, campaign)
        scenario_registry = (
            await build_campaign_scenario_registry(
                db,
                campaign=campaign,
                org_id=org_id,
                scenario_refs=scenario_refs,
            )
            if scenario_refs
            else {"by_id": {}, "by_campaign_name": {}, "by_template_name": {}}
        )
        from services.facebook_session_runtime import scenario_registry_has_facebook_login_gate

        allows_facebook_login_recovery = scenario_registry_has_facebook_login_gate(
            scenario_registry,
            scenario_refs,
        )
        effective_source_pool = source_pool
        if effective_source_pool is None and not external_entity_ids:
            effective_source_pool = source_pool_from_scenario_registry(scenario_registry)

        allocation = await _plan_entity_assignments(
            db,
            org_id=org_id,
            device_ids=[entry.device_id for entry in valid_entries],
            device_group_ids=device_group_ids,
            external_entity_ids=external_entity_ids,
            source_pool=effective_source_pool,
            allocation_snapshot=allocation_snapshot,
            allocation_policy=allocation_policy,
            lock_sources=True,
        )
        entity_by_device = allocation.entity_by_device

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
        device_map = devices_by_id if devices_by_id is not None else validation.devices_by_id
        account_by_device = await _apply_facebook_session_guard_to_accounts(
            db,
            org_id=org_id,
            account_by_device=account_by_device,
            device_map=device_map,
            allow_login_recovery=allows_facebook_login_recovery,
        )
        try:
            from web.metrics import campaign_account_resolve_batch_size

            unique_accounts = {
                r.account_id for r in account_by_device.values() if r.account_id
            }
            campaign_account_resolve_batch_size.observe(len(unique_accounts))
        except Exception:
            pass

        dispatch_id = str(uuid.uuid4())
        campaign_dispatch_targets_count.inc(len(valid_entries))
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

        claim_now = valid_entries if dispatch_strategy == "parallel" else valid_entries[:1]
        queue_later = valid_entries[1:] if dispatch_strategy == "sequential" else []
        device_index_by_id = {
            entry.device_id: index for index, entry in enumerate(valid_entries)
        }
        ordered_claims = (
            sorted(claim_now, key=lambda entry: entry.device_id)
            if dispatch_strategy == "parallel"
            else claim_now
        )
        execution_id_by_device: dict[str, str] = {}
        bulk_claims_by_device: dict[str, _CampaignClaimResult] = {}
        if dispatch_strategy == "parallel" and ordered_claims:
            execution_id_by_device = {
                entry.device_id: str(uuid.uuid4()) for entry in ordered_claims
            }
            claimable_entries = [
                entry
                for entry in ordered_claims
                if not (
                    account_by_device.get(entry.device_id)
                    and account_by_device[entry.device_id].unavailable
                )
            ]
            bulk_claims_by_device = await self._claim_campaign_devices_batch(
                db,
                campaign=campaign,
                org_id=org_id,
                actor_user_id=actor_user_id,
                dispatch_id=dispatch_id,
                claims=[
                    _CampaignClaimRequest(
                        device_id=entry.device_id,
                        execution_id=execution_id_by_device[entry.device_id],
                    )
                    for entry in claimable_entries
                ],
            )
        prepared_by_device: dict[str, _PreparedFanOutExecution] = {}

        for offset in range(0, len(ordered_claims), DISPATCH_PERSIST_CHUNK_SIZE):
            claim_slice = ordered_claims[
                offset : offset + DISPATCH_PERSIST_CHUNK_SIZE
            ]
            prepared_batch = [
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
                    device_index=device_index_by_id[entry.device_id],
                    execution_id=execution_id_by_device.get(entry.device_id),
                    claim_session_id=(
                        bulk_claims_by_device.get(entry.device_id).session_id
                        if entry.device_id in bulk_claims_by_device
                        else None
                    ),
                    claim_failure_reason=(
                        bulk_claims_by_device.get(entry.device_id).failure_reason
                        if entry.device_id in bulk_claims_by_device
                        else None
                    ),
                    claim_error=(
                        bulk_claims_by_device.get(entry.device_id).claim_error
                        if entry.device_id in bulk_claims_by_device
                        else None
                    ),
                    resolved_account=account_by_device.get(entry.device_id),
                    external_entity=entity_by_device.get(entry.device_id),
                    source_pool=effective_source_pool,
                )
                for entry in claim_slice
            ]
            await self._persist_execution_batch(db, prepared_batch)
            prepared_by_device.update(
                {prepared.view.device_id: prepared for prepared in prepared_batch}
            )

        for offset in range(0, len(queue_later), DISPATCH_PERSIST_CHUNK_SIZE):
            prepared_batch = [
                await self._create_queued_execution(
                    campaign=campaign,
                    entry=entry,
                    dispatch_id=dispatch_id,
                    dispatch_strategy=dispatch_strategy,
                    scenario_refs=scenario_refs,
                    device_index=device_index_by_id[entry.device_id],
                    resolved_account=account_by_device.get(entry.device_id),
                    external_entity=entity_by_device.get(entry.device_id),
                    source_pool=effective_source_pool,
                )
                for entry in queue_later[
                    offset : offset + DISPATCH_PERSIST_CHUNK_SIZE
                ]
            ]
            await self._persist_execution_batch(db, prepared_batch)
            prepared_by_device.update(
                {prepared.view.device_id: prepared for prepared in prepared_batch}
            )

        executions = [
            prepared_by_device[entry.device_id].view for entry in valid_entries
        ]

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
            scenario_refs=scenario_refs,
            scenario_registry=scenario_registry,
        )

    @staticmethod
    async def _claim_campaign_devices_batch(
        db: AsyncSession,
        *,
        campaign: Campaign,
        org_id: str,
        actor_user_id: str,
        dispatch_id: str,
        claims: list[_CampaignClaimRequest],
    ) -> dict[str, _CampaignClaimResult]:
        if not claims:
            return {}

        device_ids = [claim.device_id for claim in claims]
        locked_devices = (
            await db.scalars(
                select(Device)
                .where(Device.id.in_(device_ids))
                .order_by(Device.id)
                .with_for_update()
            )
        ).all()
        devices_by_id = {device.id: device for device in locked_devices}

        active_sessions = (
            await db.scalars(
                select(DeviceReserveSession)
                .where(
                    DeviceReserveSession.device_id.in_(device_ids),
                    DeviceReserveSession.released_at.is_(None),
                )
                .with_for_update()
            )
        ).all()
        active_by_device = {session.device_id: session for session in active_sessions}

        state_rows = (
            await db.scalars(
                select(DeviceFsmSnapshot)
                .where(DeviceFsmSnapshot.device_id.in_(device_ids))
                .with_for_update()
            )
        ).all()
        states_by_device = {state.device_id: state for state in state_rows}

        now = datetime.now(timezone.utc)
        owner_type = DeviceReserveOwnerType.CAMPAIGN.value
        owner_id = (campaign.id or actor_user_id or "").strip()
        results: dict[str, _CampaignClaimResult] = {}
        publish_events: list[DeviceStateChangedEvent] = []

        for claim in claims:
            device = devices_by_id.get(claim.device_id)
            active = active_by_device.get(claim.device_id)
            state = states_by_device.get(claim.device_id)
            if device is None or device.org_id != org_id:
                results[claim.device_id] = _CampaignClaimResult(
                    failure_reason="device_claim_failed",
                    claim_error="SESSION_NOT_FOUND",
                )
                continue
            if (
                getattr(device, "status", DeviceRegistryStatus.PAIRED.value)
                == DeviceRegistryStatus.UNPAIRED.value
            ):
                results[claim.device_id] = _CampaignClaimResult(
                    failure_reason="device_claim_failed",
                    claim_error="DEVICE_UNPAIRED",
                )
                continue
            if active is not None:
                results[claim.device_id] = _CampaignClaimResult(
                    failure_reason="device_claim_failed",
                    claim_error="DEVICE_BUSY",
                )
                continue
            if state is None or state.state != DeviceFsmState.ONLINE.value:
                results[claim.device_id] = _CampaignClaimResult(
                    failure_reason="device_claim_failed",
                    claim_error="DEVICE_NOT_AVAILABLE",
                )
                continue

            session_id = str(uuid.uuid4())
            event_id = str(uuid.uuid4())
            payload = {
                "owner_type": owner_type,
                "owner_id": owner_id,
                "session_id": session_id,
            }
            db.add(
                DeviceReserveSession(
                    id=session_id,
                    device_id=claim.device_id,
                    org_id=org_id,
                    owner_type=owner_type,
                    owner_id=owner_id,
                    claimed_at=now,
                    last_heartbeat=now,
                    ttl_sec=DEFAULT_TTL_SEC,
                    ctx={
                        "dispatch_id": dispatch_id,
                        "execution_id": claim.execution_id,
                    },
                    created_by_user_id=actor_user_id,
                )
            )
            state.state = DeviceFsmState.BUSY.value
            state.updated_at = now
            state.last_event_id = event_id
            state.session_id = session_id
            db.add(
                DeviceStateTransition(
                    device_id=claim.device_id,
                    from_state=DeviceFsmState.ONLINE.value,
                    to_state=DeviceFsmState.BUSY.value,
                    event=DeviceFsmEvent.SESSION_CLAIM.value,
                    source="claim",
                    event_id=event_id,
                    timestamp=now,
                    payload=payload,
                )
            )
            db.add(
                ActivityLog(
                    action="session.claimed",
                    entity_type="device",
                    entity_id=claim.device_id,
                    user_id=actor_user_id,
                    org_id=org_id,
                    outcome="success",
                    details={
                        "session_id": session_id,
                        "owner_type": owner_type,
                        "owner_id": owner_id,
                        "ttl_sec": DEFAULT_TTL_SEC,
                    },
                )
            )
            results[claim.device_id] = _CampaignClaimResult(session_id=session_id)
            publish_events.append(
                DeviceStateChangedEvent(
                    device_id=claim.device_id,
                    from_state=DeviceFsmState.ONLINE.value,
                    to_state=DeviceFsmState.BUSY.value,
                    event=DeviceFsmEvent.SESSION_CLAIM.value,
                    source="claim",
                    event_id=event_id,
                    session_id=session_id,
                    payload=payload,
                )
            )

        for event in publish_events:
            publish_device_state_changed(event)
            try:
                fsm_transition_count.labels(
                    from_state=event.from_state,
                    to_state=event.to_state,
                ).inc()
            except Exception:
                pass
        return results

    @staticmethod
    async def _persist_execution_batch(
        db: AsyncSession,
        prepared_batch: list[_PreparedFanOutExecution],
    ) -> None:
        if not prepared_batch:
            return
        await db.execute(
            insert(Execution),
            [prepared.execution_values for prepared in prepared_batch],
        )
        await db.execute(
            insert(ExecutionDevice),
            [prepared.link_values for prepared in prepared_batch],
        )
        await db.execute(
            insert(ExecutionResult),
            [prepared.result_values for prepared in prepared_batch],
        )
        terminal_statuses = {
            ExecutionStatus.COMPLETED.value,
            ExecutionStatus.FAILED.value,
            ExecutionStatus.CANCELLED.value,
            ExecutionStatus.DLQ_CLOSED.value,
        }
        assignments = []
        for prepared in prepared_batch:
            if prepared.assignment_values is None:
                continue
            assignment = dict(prepared.assignment_values)
            if prepared.view.status in terminal_statuses:
                assignment["status"] = prepared.view.status
                assignment["completed_at"] = datetime.now(timezone.utc)
            assignments.append(assignment)
        if assignments:
            await db.execute(insert(ExecutionEntityAssignment), assignments)

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
        device_index: int,
        execution_id: str | None = None,
        claim_session_id: str | None = None,
        claim_failure_reason: str | None = None,
        claim_error: str | None = None,
        resolved_account: ResolvedDeviceAccount | None = None,
        external_entity: ExternalEntity | None = None,
        source_pool: SourcePoolSpec | None = None,
    ) -> _PreparedFanOutExecution:
        effective_vars = merge_effective_vars(
            campaign_vars=campaign.variables,
            per_device_overrides=campaign.per_device_overrides,
            device_id=entry.device_id,
        )
        account_vars = (resolved_account.account_vars if resolved_account else {}) or {}
        if account_vars:
            effective_vars = {**effective_vars, **account_vars}
        effective_vars = _with_external_entity_vars(
            effective_vars,
            external_entity,
            source_pool=source_pool,
        )

        device = device_map.get(entry.device_id)
        device_serial = device.serial if device else ""
        account_id = resolved_account.account_id if resolved_account else None
        execution_id = execution_id or str(uuid.uuid4())
        created_at = datetime.now(timezone.utc)
        execution_values: dict[str, Any] = {
            "id": execution_id,
            "run_type": "campaign_device",
            "kind": "campaign",
            "status": ExecutionStatus.PENDING.value,
            "org_id": campaign.org_id,
            "campaign_id": campaign.id,
            "scenario_id": None,
            "scenario_version_id": None,
            "device_config": {
                "effective_vars": effective_vars,
                "account_vars": account_vars,
                "device_serial": device_serial,
            },
            "loop_config": {},
            "error_config": {},
            "meta": {
                "dispatch_id": dispatch_id,
                "dispatch_strategy": dispatch_strategy,
                "org_scenario_refs": scenario_refs,
                "source_kind": entry.source_kind,
                "source_ref_id": entry.source_ref_id,
                "device_index": device_index,
                "external_entity_id": external_entity.id if external_entity else None,
            },
            "user_id": campaign.created_by or campaign.user_id,
            "account_id": account_id,
            "priority": 0,
            "checkpoint_step": 0,
            "created_at": created_at,
            "started_at": None,
            "finished_at": None,
        }
        if resolved_account and resolved_account.session_guard:
            execution_values["meta"] = {
                **execution_values["meta"],
                "facebook_session_guard": resolved_account.session_guard,
            }

        active_claim_session_id = claim_session_id
        failure_reason: str | None = None
        status = (
            ExecutionStatus.RUNNING.value
            if claim_device
            else ExecutionStatus.PENDING.value
        )

        if resolved_account and resolved_account.unavailable:
            failure_reason = resolved_account.failure_reason or "account_unavailable"
            status = ExecutionStatus.FAILED.value
            finished_at = datetime.now(timezone.utc)
            execution_values["status"] = status
            execution_values["finished_at"] = finished_at
            execution_values["device_config"] = {
                **execution_values["device_config"],
                "failure_reason": failure_reason,
            }
            return self._prepared_execution(
                execution_values=execution_values,
                device_id=entry.device_id,
                result_status="failed",
                error_detail=failure_reason,
                finished_at=finished_at,
                view=FanOutExecutionView(
                    execution_id=execution_id,
                    device_id=entry.device_id,
                    status=status,
                    effective_vars=effective_vars,
                    account_id=account_id,
                    failure_reason=failure_reason,
                    external_entity_id=external_entity.id if external_entity else None,
                ),
                assignment_values=_assignment_values(
                    campaign=campaign,
                    dispatch_id=dispatch_id,
                    execution_id=execution_id,
                    device_id=entry.device_id,
                    entity=external_entity,
                    assigned_at=created_at,
                ),
            )

        if claim_device:
            if active_claim_session_id:
                started_at = datetime.now(timezone.utc)
                execution_values["device_config"] = {
                    **execution_values["device_config"],
                    "claim_session_id": active_claim_session_id,
                }
                execution_values["status"] = ExecutionStatus.RUNNING.value
                execution_values["started_at"] = started_at
            elif claim_failure_reason:
                campaign_dispatch_claim_fail_count.inc()
                failure_reason = claim_failure_reason
                status = ExecutionStatus.FAILED.value
                finished_at = datetime.now(timezone.utc)
                execution_values["status"] = status
                execution_values["finished_at"] = finished_at
                cfg = {
                    **execution_values["device_config"],
                    "failure_reason": failure_reason,
                }
                if claim_error:
                    cfg["claim_error"] = claim_error
                execution_values["device_config"] = cfg
            else:
                try:
                    claim = await claim_device_session(
                        db,
                        device_id=entry.device_id,
                        org_id=org_id,
                        actor_user_id=actor_user_id,
                        owner_type=DeviceReserveOwnerType.CAMPAIGN.value,
                        owner_id=campaign.id,
                        ctx={
                            "dispatch_id": dispatch_id,
                            "execution_id": execution_id,
                        },
                    )
                    active_claim_session_id = claim.session_id
                    started_at = datetime.now(timezone.utc)
                    execution_values["device_config"] = {
                        **execution_values["device_config"],
                        "claim_session_id": active_claim_session_id,
                    }
                    execution_values["status"] = ExecutionStatus.RUNNING.value
                    execution_values["started_at"] = started_at
                except (DeviceBusyError, DeviceSessionError) as exc:
                    campaign_dispatch_claim_fail_count.inc()
                    failure_reason = "device_claim_failed"
                    status = ExecutionStatus.FAILED.value
                    finished_at = datetime.now(timezone.utc)
                    execution_values["status"] = status
                    execution_values["finished_at"] = finished_at
                    cfg = {
                        **execution_values["device_config"],
                        "failure_reason": failure_reason,
                    }
                    if isinstance(exc, DeviceSessionError):
                        cfg["claim_error"] = exc.code
                    execution_values["device_config"] = cfg

        return self._prepared_execution(
            execution_values=execution_values,
            device_id=entry.device_id,
            result_status=(
                "failed"
                if status == ExecutionStatus.FAILED.value
                else "running"
                if status == ExecutionStatus.RUNNING.value
                else "pending"
            ),
            error_detail=failure_reason,
            started_at=execution_values["started_at"],
            finished_at=execution_values["finished_at"],
            view=FanOutExecutionView(
                execution_id=execution_id,
                device_id=entry.device_id,
                status=status,
                effective_vars=effective_vars,
                account_id=account_id,
                failure_reason=failure_reason,
                claim_session_id=active_claim_session_id,
                external_entity_id=external_entity.id if external_entity else None,
            ),
            assignment_values=_assignment_values(
                campaign=campaign,
                dispatch_id=dispatch_id,
                execution_id=execution_id,
                device_id=entry.device_id,
                entity=external_entity,
                assigned_at=created_at,
            ),
        )

    async def _create_queued_execution(
        self,
        *,
        campaign: Campaign,
        entry: ResolvedTargetEntry,
        dispatch_id: str,
        dispatch_strategy: DispatchStrategy,
        scenario_refs: list[dict[str, Any]],
        device_index: int,
        resolved_account: ResolvedDeviceAccount | None = None,
        external_entity: ExternalEntity | None = None,
        source_pool: SourcePoolSpec | None = None,
    ) -> _PreparedFanOutExecution:
        effective_vars = merge_effective_vars(
            campaign_vars=campaign.variables,
            per_device_overrides=campaign.per_device_overrides,
            device_id=entry.device_id,
        )
        account_vars = (resolved_account.account_vars if resolved_account else {}) or {}
        if account_vars:
            effective_vars = {**effective_vars, **account_vars}
        effective_vars = _with_external_entity_vars(
            effective_vars,
            external_entity,
            source_pool=source_pool,
        )
        account_id = resolved_account.account_id if resolved_account else None
        execution_id = str(uuid.uuid4())
        execution_values: dict[str, Any] = {
            "id": execution_id,
            "run_type": "campaign_device",
            "kind": "campaign",
            "status": ExecutionStatus.PENDING.value,
            "org_id": campaign.org_id,
            "campaign_id": campaign.id,
            "scenario_id": None,
            "scenario_version_id": None,
            "device_config": {
                "effective_vars": effective_vars,
                "account_vars": account_vars,
            },
            "loop_config": {},
            "error_config": {},
            "meta": {
                "dispatch_id": dispatch_id,
                "dispatch_strategy": dispatch_strategy,
                "org_scenario_refs": scenario_refs,
                "source_kind": entry.source_kind,
                "source_ref_id": entry.source_ref_id,
                "queued": True,
                "device_index": device_index,
                "external_entity_id": external_entity.id if external_entity else None,
            },
            "user_id": campaign.created_by or campaign.user_id,
            "account_id": account_id,
            "priority": 0,
            "checkpoint_step": 0,
            "created_at": datetime.now(timezone.utc),
            "started_at": None,
            "finished_at": None,
        }
        if resolved_account and resolved_account.unavailable:
            failure_reason = (
                resolved_account.failure_reason or "account_unavailable"
            )
            finished_at = datetime.now(timezone.utc)
            execution_values["status"] = ExecutionStatus.FAILED.value
            execution_values["finished_at"] = finished_at
            execution_values["device_config"] = {
                **execution_values["device_config"],
                "failure_reason": failure_reason,
            }
            return self._prepared_execution(
                execution_values=execution_values,
                device_id=entry.device_id,
                result_status="failed",
                error_detail=failure_reason,
                finished_at=finished_at,
                view=FanOutExecutionView(
                    execution_id=execution_id,
                    device_id=entry.device_id,
                    status=ExecutionStatus.FAILED.value,
                    effective_vars=effective_vars,
                    account_id=account_id,
                    failure_reason=failure_reason,
                    external_entity_id=external_entity.id if external_entity else None,
                ),
                assignment_values=_assignment_values(
                    campaign=campaign,
                    dispatch_id=dispatch_id,
                    execution_id=execution_id,
                    device_id=entry.device_id,
                    entity=external_entity,
                    assigned_at=execution_values["created_at"],
                ),
            )

        return self._prepared_execution(
            execution_values=execution_values,
            device_id=entry.device_id,
            result_status="pending",
            view=FanOutExecutionView(
                execution_id=execution_id,
                device_id=entry.device_id,
                status=ExecutionStatus.PENDING.value,
                effective_vars=effective_vars,
                account_id=account_id,
                external_entity_id=external_entity.id if external_entity else None,
            ),
            assignment_values=_assignment_values(
                campaign=campaign,
                dispatch_id=dispatch_id,
                execution_id=execution_id,
                device_id=entry.device_id,
                entity=external_entity,
                assigned_at=execution_values["created_at"],
            ),
        )

    @staticmethod
    def _prepared_execution(
        *,
        execution_values: dict[str, Any],
        device_id: str,
        result_status: str,
        view: FanOutExecutionView,
        error_detail: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        assignment_values: dict[str, Any] | None = None,
    ) -> _PreparedFanOutExecution:
        execution_id = str(execution_values["id"])
        created_at = execution_values["created_at"]
        return _PreparedFanOutExecution(
            execution_values=execution_values,
            link_values={
                "id": str(uuid.uuid4()),
                "execution_id": execution_id,
                "device_id": device_id,
            },
            result_values={
                "id": str(uuid.uuid4()),
                "org_id": execution_values["org_id"],
                "execution_id": execution_id,
                "device_id": device_id,
                "status": result_status,
                "run_time_sec": None,
                "passed_steps": [],
                "failed_steps": [],
                "error_detail": error_detail,
                "started_at": started_at,
                "finished_at": finished_at,
                "created_at": created_at,
            },
            assignment_values=assignment_values,
            view=view,
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
        scenario_registry = await build_campaign_scenario_registry(
            db,
            campaign=campaign,
            org_id=org_id,
            scenario_refs=scenario_refs,
        )
        from services.facebook_session_runtime import (
            guard_reason_allows_login_recovery,
            scenario_registry_has_facebook_login_gate,
        )

        allows_facebook_login_recovery = scenario_registry_has_facebook_login_gate(
            scenario_registry,
            scenario_refs,
        )

        from services.campaign.account_resolver import (
            campaign_has_account_binding,
            revalidate_persisted_account,
        )

        resolved = await revalidate_persisted_account(
            db,
            account_id=execution.account_id,
            org_id=org_id,
            required=campaign_has_account_binding(campaign),
        )
        if resolved.account_id:
            from services.facebook_session_guard import guard_facebook_session

            decision = await guard_facebook_session(
                db,
                org_id=org_id,
                device_id=device_id,
                account_id=resolved.account_id,
                device_serial=devices[0].serial,
                live_check=False,
            )
            deferred_to_login = (
                allows_facebook_login_recovery
                and decision.blocks_execution
                and guard_reason_allows_login_recovery(decision.reason)
            )
            meta = {
                **meta,
                "facebook_session_guard": {
                    **decision.to_meta(),
                    **({"deferred_to_scenario_login": True} if deferred_to_login else {}),
                },
            }
            execution.meta = meta
            if decision.blocks_execution and not deferred_to_login and not resolved.unavailable:
                resolved = replace(
                    resolved,
                    unavailable=True,
                    failure_reason=decision.reason,
                    session_guard=decision.to_meta(),
                )
            elif not resolved.session_guard:
                resolved = replace(resolved, session_guard=decision.to_meta())

        cfg = execution.device_config or {}
        effective_vars = dict(cfg.get("effective_vars") or {})
        account_id = execution.account_id
        claim_session_id: str | None = cfg.get("claim_session_id")
        failure_reason: str | None = None
        status = ExecutionStatus.RUNNING.value

        if resolved.unavailable:
            failure_reason = resolved.failure_reason or "account_unavailable"
            status = ExecutionStatus.FAILED.value
            execution.status = status
            execution.finished_at = datetime.now(timezone.utc)
            execution.device_config = {
                **cfg,
                "failure_reason": failure_reason,
            }
            await upsert_execution_result(
                db,
                execution_id=execution.id,
                device_id=device_id,
                status="failed",
                error_detail=failure_reason,
                finished_at=execution.finished_at,
            )
            return FanOutExecutionView(
                execution_id=execution.id,
                device_id=device_id,
                status=status,
                effective_vars=effective_vars,
                account_id=account_id or resolved.account_id,
                failure_reason=failure_reason,
                claim_session_id=claim_session_id,
            )

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

        return FanOutExecutionView(
            execution_id=execution.id,
            device_id=device_id,
            status=status,
            effective_vars=effective_vars,
            account_id=account_id or (resolved.account_id if resolved else None),
            failure_reason=failure_reason,
            claim_session_id=claim_session_id,
            external_entity_id=(
                str(effective_vars.get("TARGET_ENTITY_ID"))
                if effective_vars.get("TARGET_ENTITY_ID")
                else None
            ),
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


async def preview_campaign_dispatch(
    db: AsyncSession,
    *,
    campaign_id: str,
    org_id: str,
    device_ids: list[str] | None = None,
    device_group_ids: list[str] | None = None,
    external_entity_ids: list[str] | None = None,
    source_pool: SourcePoolSpec | None = None,
    allocation_snapshot: list[tuple[str, str]] | None = None,
    allocation_policy: str = "one_per_device",
    allow_partial: bool = False,
    require_online: bool = True,
) -> DispatchPreview:
    campaign = await campaign_repo.get_campaign_entity(db, campaign_id)
    if (
        campaign is None
        or campaign.org_id != org_id
        or campaign.status == CampaignStatus.ARCHIVED.value
    ):
        raise CampaignDispatchError("Campaign not found", code="CAMPAIGN_NOT_FOUND")

    try:
        entries = await resolve_dispatch_targets(
            db,
            org_id=org_id,
            device_ids=device_ids,
            device_group_ids=device_group_ids,
        )
    except DispatchValidationError as exc:
        raise CampaignDispatchError(
            str(exc), code=exc.code, details=exc.details
        ) from exc
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
    if validation.cross_org_ids or validation.not_found_ids:
        raise CampaignDispatchError(
            "One or more devices were not found in this organization",
            code="DEVICE_NOT_FOUND",
            details={
                "device_ids": validation.cross_org_ids
                or validation.not_found_ids
            },
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

    scenario_refs = await resolve_campaign_scenario_refs(db, campaign)
    effective_source_pool = source_pool
    if effective_source_pool is None and not external_entity_ids:
        effective_source_pool = await _derive_source_pool_from_scenarios(
            db,
            campaign=campaign,
            org_id=org_id,
            scenario_refs=scenario_refs,
        )

    device_ids_ordered = [entry.device_id for entry in valid_entries]
    allocation = await _plan_entity_assignments(
        db,
        org_id=org_id,
        device_ids=device_ids_ordered,
        device_group_ids=device_group_ids,
        external_entity_ids=external_entity_ids,
        source_pool=effective_source_pool,
        allocation_snapshot=allocation_snapshot,
        allocation_policy=allocation_policy,
        lock_sources=False,
    )
    return DispatchPreview(
        campaign_id=campaign.id,
        allocation_policy=allocation_policy,
        device_ids=device_ids_ordered,
        devices_by_id=validation.devices_by_id,
        allocation=allocation,
    )


async def dispatch_campaign(
    db: AsyncSession,
    *,
    campaign_id: str,
    org_id: str,
    actor_user_id: str,
    device_ids: list[str] | None = None,
    device_group_ids: list[str] | None = None,
    external_entity_ids: list[str] | None = None,
    source_pool: SourcePoolSpec | None = None,
    allocation_snapshot: list[tuple[str, str]] | None = None,
    allocation_policy: str = "one_per_device",
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
            external_entity_ids=external_entity_ids,
            source_pool=source_pool,
            allocation_snapshot=allocation_snapshot,
            allocation_policy=allocation_policy,
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
    device_id: str | None = None,
) -> None:
    """Release device reserve session when a fan-out execution reaches terminal state."""
    cfg = execution.device_config or {}
    session_id = cfg.get("claim_session_id")
    if not session_id:
        return
    if device_id is None:
        from db.crud.execution import list_execution_devices

        linked = await list_execution_devices(db, execution.id)
        device_id = linked[0].id if linked else None
    if not device_id:
        return
    try:
        released = await _release_execution_device_claim_fast(
            db,
            device_id=device_id,
            session_id=str(session_id),
            org_id=org_id,
            actor_user_id=actor_user_id,
        )
        if not released:
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


async def _release_execution_device_claim_fast(
    db: AsyncSession,
    *,
    device_id: str,
    session_id: str,
    org_id: str,
    actor_user_id: str,
) -> bool:
    session = await db.scalar(
        select(DeviceReserveSession)
        .where(
            DeviceReserveSession.id == session_id,
            DeviceReserveSession.device_id == device_id,
            DeviceReserveSession.org_id == org_id,
        )
        .with_for_update()
    )
    if session is None:
        return False
    if session.released_at is not None:
        return True

    now = datetime.now(timezone.utc)
    reason = "execution_terminal"
    session.released_at = now
    session.release_reason = reason

    state = await db.scalar(
        select(DeviceFsmSnapshot)
        .where(DeviceFsmSnapshot.device_id == device_id)
        .with_for_update()
    )
    event: DeviceStateChangedEvent | None = None
    if state is not None and state.state == DeviceFsmState.BUSY.value:
        previous_session_id = state.session_id
        if not previous_session_id or previous_session_id == session_id:
            event_id = str(uuid.uuid4())
            payload = {"release_reason": reason, "session_id": session_id}
            state.state = DeviceFsmState.ONLINE.value
            state.updated_at = now
            state.last_event_id = event_id
            state.session_id = None
            state.reconnecting_since = None
            db.add(
                DeviceStateTransition(
                    device_id=device_id,
                    from_state=DeviceFsmState.BUSY.value,
                    to_state=DeviceFsmState.ONLINE.value,
                    event=DeviceFsmEvent.SESSION_RELEASED.value,
                    source="claim",
                    event_id=event_id,
                    timestamp=now,
                    payload=payload,
                )
            )
            event = DeviceStateChangedEvent(
                device_id=device_id,
                from_state=DeviceFsmState.BUSY.value,
                to_state=DeviceFsmState.ONLINE.value,
                event=DeviceFsmEvent.SESSION_RELEASED.value,
                source="claim",
                event_id=event_id,
                session_id=None,
                payload=payload,
            )

    db.add(
        ActivityLog(
            action="session.released.execution_terminal",
            entity_type="device",
            entity_id=device_id,
            user_id=actor_user_id,
            org_id=org_id,
            outcome="success",
            details={
                "session_id": session_id,
                "release_reason": reason,
                "owner_type": session.owner_type,
                "owner_id": session.owner_id,
            },
        )
    )
    await db.flush()
    if event is not None:
        publish_device_state_changed(event)
        try:
            fsm_transition_count.labels(
                from_state=event.from_state,
                to_state=event.to_state,
            ).inc()
        except Exception:
            pass
    return True


async def finish_fan_out_execution(
    db: AsyncSession,
    execution: Execution,
    *,
    org_id: str,
    actor_user_id: str,
    status: str = "completed",
    execution_already_finished: bool = False,
    device_id: str | None = None,
) -> None:
    """Mark execution terminal and release any campaign dispatch claim."""
    if not execution_already_finished:
        await finish_execution(db, execution.id, status=status)
    await db.execute(
        update(ExecutionEntityAssignment)
        .where(
            ExecutionEntityAssignment.org_id == org_id,
            ExecutionEntityAssignment.execution_id == execution.id,
            ExecutionEntityAssignment.completed_at.is_(None),
        )
        .values(
            status=status,
            completed_at=datetime.now(timezone.utc),
        )
    )
    await release_execution_device_claim(
        db,
        execution,
        org_id=org_id,
        actor_user_id=actor_user_id,
        device_id=device_id,
    )
    if execution.campaign_id:
        from services.campaign.aggregator_scheduler import request_campaign_status_evaluation

        await request_campaign_status_evaluation(
            org_id=org_id,
            campaign_id=execution.campaign_id,
            user_id=actor_user_id,
        )
