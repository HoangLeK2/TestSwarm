"""Epic 04 execution runtime — Temporal workflow per fan-out execution (DF-T-04-010)."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.crud.execution import get_execution, list_execution_devices
from db.models.campaign import Campaign
from db.models.device import Device
from db.models.enums import ExecutionStatus
from db.models.execution import Execution, ExecutionDevice
from services.campaign.dispatcher import (
    FanOutExecutionView,
    FanOutResult,
    finish_fan_out_execution,
)
from services.campaign.scenario_sources import (
    build_campaign_scenario_registry,
    resolve_campaign_scenario_refs,
)
from common.variable_resolver import normalize_device_vars
from temporal.shared import ScenarioInput, TASK_QUEUE_NAME

log = logging.getLogger(__name__)

DISPATCH_SOURCE_TEMPORAL = "temporal"
DISPATCH_SOURCE_FALLBACK = "fallback"
DEFAULT_RUNTIME_START_CONCURRENCY = 50


def workflow_id_for_execution(execution_id: str) -> str:
    """Deterministic Temporal workflow id (DF-T-04-010)."""
    return f"exec_{execution_id}"


def _scenario_refs_with_recovery_refs(
    scenario_refs: list[dict[str, Any]],
    recovery_policy: dict[str, Any],
) -> list[dict[str, Any]]:
    merged = list(scenario_refs)
    seen = {str(ref.get("scenario_id") or "") for ref in merged}
    raw_rules = recovery_policy.get("rules")
    if not isinstance(raw_rules, list):
        return merged
    for rule in raw_rules:
        if not isinstance(rule, dict):
            continue
        scenario_id = str(rule.get("scenario_id") or "").strip()
        if not scenario_id or scenario_id in seen:
            continue
        merged.append({"scenario_id": scenario_id})
        seen.add(scenario_id)
    return merged


def _runtime_start_concurrency_limit() -> int:
    raw = os.getenv("CAMPAIGN_RUNTIME_START_CONCURRENCY", "").strip()
    if not raw:
        return DEFAULT_RUNTIME_START_CONCURRENCY
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_RUNTIME_START_CONCURRENCY
    return max(1, min(value, 200))


async def build_org_scenario_registry(
    db: AsyncSession,
    org_id: str,
    scenario_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    from db.crud import org_scenario as org_scenario_repo

    registry: dict[str, Any] = {
        "by_id": {},
        "by_campaign_name": {},
        "by_template_name": {},
    }
    if not scenario_refs:
        return registry

    scenario_ids = [str(ref["scenario_id"]) for ref in scenario_refs]
    bodies = await org_scenario_repo.get_org_scenario_bodies_by_ids(db, org_id, scenario_ids)
    names = await org_scenario_repo.get_org_scenario_names_by_ids(db, org_id, scenario_ids)

    for scenario_id, _kind, body in bodies:
        payload = body if isinstance(body, dict) else {}
        name = names.get(scenario_id, scenario_id)
        entry = {
            "steps": payload.get("steps") or [],
            "variables": dict(payload.get("variables") or {}),
            "name": name,
        }
        registry["by_id"][scenario_id] = entry
        registry["by_campaign_name"][name] = entry
    return registry


def build_sequence_steps(
    scenario_refs: list[dict[str, Any]],
    *,
    device_index: int,
    effective_vars: dict[str, Any],
    account_vars: dict[str, Any],
    campaign_vars: dict[str, Any] | None = None,
    scenario_device_vars: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    campaign_defaults = dict(campaign_vars or {})
    campaign_override_vars = {
        key: value
        for key, value in campaign_defaults.items()
        if not str(key).startswith("__")
    }
    device_override_vars = (
        {
            key: value
            for key, value in (effective_vars or {}).items()
            if campaign_defaults.get(key) != value
        }
        if campaign_vars is not None
        else dict(effective_vars or {})
    )
    for scenario_idx, ref in enumerate(scenario_refs):
        scenario_id = str(ref["scenario_id"])
        scoped_vars = dict((scenario_device_vars or {}).get(scenario_id) or {})
        merged_vars = {
            **campaign_override_vars,
            **device_override_vars,
            **scoped_vars,
            **account_vars,
            "DEVICE_INDEX": str(device_index),
            "SCENARIO_INDEX": str(scenario_idx),
        }
        steps.append(
            {
                "type": "run_scenario",
                "scenario_id": scenario_id,
                "variables": merged_vars,
            }
        )
    return steps


async def _load_scenario_device_vars_for_execution(
    db: AsyncSession,
    *,
    campaign_id: str,
    scenario_refs: list[dict[str, Any]],
    device_id: str | None,
) -> dict[str, dict[str, Any]]:
    if not device_id or not scenario_refs:
        return {}
    from db.crud.scenario_device_variable import (
        get_campaign_org_scenario_device_variables_bulk,
    )

    scenario_ids = [str(ref["scenario_id"]) for ref in scenario_refs if ref.get("scenario_id")]
    bulk = await get_campaign_org_scenario_device_variables_bulk(
        db,
        campaign_id,
        scenario_ids,
        [device_id],
    )
    return {
        scenario_id: normalize_device_vars(bulk.get((scenario_id, device_id), {}))
        for scenario_id in scenario_ids
    }


def _runtime_campaign_vars(campaign: Campaign) -> dict[str, Any]:
    campaign_vars = dict(campaign.variables or {})
    owner = campaign.created_by or campaign.user_id
    if owner:
        campaign_vars.setdefault("__USER_ID__", str(owner))
    return campaign_vars


def _build_prepared_scenario_input(
    *,
    execution: Execution,
    campaign: Campaign,
    org_id: str,
    device_serial: str,
    effective_vars: dict[str, Any],
    account_vars: dict[str, Any],
    scenario_refs: list[dict[str, Any]],
    scenario_registry: dict[str, Any],
    campaign_vars: dict[str, Any],
    recovery_policy: dict[str, Any],
    scenario_device_vars: dict[str, dict[str, Any]] | None = None,
    device_index: int = 0,
) -> ScenarioInput | None:
    sequence_steps = build_sequence_steps(
        scenario_refs,
        device_index=device_index,
        effective_vars=effective_vars,
        account_vars=account_vars,
        campaign_vars=campaign_vars,
        scenario_device_vars=scenario_device_vars,
    )
    if not sequence_steps:
        return None

    start_step = int((execution.meta or {}).get("start_step") or execution.checkpoint_step or 0)
    scenario_config: dict[str, Any] = {"capture_mode": "error_only"}
    if recovery_policy:
        scenario_config["recovery_policy"] = recovery_policy

    return ScenarioInput(
        campaign_id=campaign.id,
        device_serial=device_serial,
        steps=sequence_steps,
        variables=dict(effective_vars),
        campaign_vars=campaign_vars,
        scenario_registry=scenario_registry,
        execution_id=execution.id,
        run_id=execution.id,
        start_step=max(0, start_step),
        scenario_config=scenario_config,
    )


async def prepare_scenario_input(
    db: AsyncSession,
    *,
    execution: Execution,
    campaign: Campaign,
    org_id: str,
    device_serial: str,
    effective_vars: dict[str, Any],
    account_vars: dict[str, Any],
    scenario_refs: list[dict[str, Any]] | None = None,
    device_id: str | None = None,
    device_index: int = 0,
) -> ScenarioInput | None:
    refs = scenario_refs if scenario_refs is not None else await resolve_campaign_scenario_refs(
        db, campaign
    )
    if not refs:
        return None
    recovery_policy = dict(getattr(campaign, "recovery_policy", None) or {})
    registry_refs = _scenario_refs_with_recovery_refs(refs, recovery_policy)
    registry = await build_campaign_scenario_registry(
        db,
        campaign=campaign,
        org_id=org_id,
        scenario_refs=registry_refs,
    )
    return _build_prepared_scenario_input(
        execution=execution,
        campaign=campaign,
        org_id=org_id,
        device_serial=device_serial,
        effective_vars=effective_vars,
        account_vars=account_vars,
        scenario_refs=refs,
        scenario_registry=registry,
        campaign_vars=_runtime_campaign_vars(campaign),
        recovery_policy=recovery_policy,
        scenario_device_vars=await _load_scenario_device_vars_for_execution(
            db,
            campaign_id=campaign.id,
            scenario_refs=registry_refs,
            device_id=device_id,
        ),
        device_index=device_index,
    )


async def _resolve_device_serial(db: AsyncSession, execution: Execution) -> str:
    cfg = execution.device_config or {}
    serial = str(cfg.get("device_serial") or "").strip()
    if serial:
        return serial
    devices = await list_execution_devices(db, execution.id)
    if devices:
        return devices[0].serial or ""
    return ""


async def _try_start_temporal(
    temporal_client: Any,
    temporal_config: Any,
    scenario_input: ScenarioInput,
    execution_id: str,
) -> str | None:
    from temporal.workflows import ScenarioWorkflow
    from temporalio.common import WorkflowIDReusePolicy

    wf_id = workflow_id_for_execution(execution_id)
    task_queue = TASK_QUEUE_NAME
    if temporal_config is not None:
        task_queue = getattr(temporal_config, "task_queue", None) or task_queue

    await temporal_client.start_workflow(
        ScenarioWorkflow.run,
        scenario_input,
        id=wf_id,
        task_queue=task_queue,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
    )
    return wf_id


async def _mark_runtime_meta(
    db: AsyncSession,
    execution: Execution,
    *,
    dispatch_source: str,
    workflow_id: str | None = None,
    flush: bool = True,
) -> None:
    meta = dict(execution.meta or {})
    meta["dispatch_source"] = dispatch_source
    if workflow_id:
        meta["workflow_id"] = workflow_id
        meta["workflow_ids"] = [workflow_id]
    execution.meta = meta
    if flush:
        await db.flush()


def _temporal_available(temporal_client: Any, temporal_config: Any) -> bool:
    if temporal_client is None or temporal_config is None:
        return False
    return bool(getattr(temporal_config, "enabled", False))


def build_runtime_scenario_dict(
    scenario_input: ScenarioInput,
    execution_id: str,
    *,
    org_id: str | None = None,
    scenario_name: str | None = None,
) -> dict[str, Any]:
    """Build full scenario dict for in-process run_scenario_task (fallback runtime).

    Mirrors temporal ``_build_activity_mini_scenario`` fields so edge extra_data ingest,
    step capture, and preview collection behave the same as the Temporal path.
    """
    exec_id = str(execution_id).strip()
    scenario: dict[str, Any] = {
        "steps": scenario_input.steps,
        "variables": dict(scenario_input.variables or {}),
        "execution_id": exec_id,
        "run_id": exec_id,
        "_execution_id": exec_id,
        "_run_hash_scope": exec_id,
        "start_step": int(getattr(scenario_input, "start_step", 0) or 0),
    }
    registry = getattr(scenario_input, "scenario_registry", None)
    if registry:
        scenario["_scenario_registry"] = registry

    if org_id:
        scenario["_org_id"] = org_id

    name = scenario_name or (getattr(scenario_input, "scenario_config", None) or {}).get(
        "scenario_name"
    )
    if name:
        scenario["scenario_name"] = name
        scenario["name"] = name

    campaign_vars = dict(getattr(scenario_input, "campaign_vars", None) or {})
    if org_id:
        campaign_vars.setdefault("__ORG_ID__", org_id)
    if campaign_vars:
        scenario["_campaign_vars"] = campaign_vars

    scenario_config = getattr(scenario_input, "scenario_config", None) or {}
    for key in (
        "visual_anchor",
        "implicit_wait",
        "capture_steps",
        "capture_throttle",
        "capture_mode",
        "settle_timeout_ms",
        "preview_collection",
        "recovery_policy",
    ):
        if key in scenario_config:
            scenario[key] = scenario_config[key]

    explicit_capture = scenario_config.get("capture_steps")
    if getattr(scenario_input, "capture_steps", False) or explicit_capture is True:
        scenario["capture_steps"] = True
    elif explicit_capture is False:
        # Crawl fast-path: an explicit False must win over the campaign default
        # so step capture (and its settle/stale-wait transition cost) is skipped.
        scenario["capture_steps"] = False
    elif exec_id:
        scenario.setdefault("capture_steps", True)

    return scenario


def schedule_fallback_runtime(
    *,
    scenario_input: ScenarioInput,
    execution_id: str,
    org_id: str,
    actor_user_id: str,
    manager: Any,
) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        log.warning("no event loop — cannot schedule fallback runtime for %s", execution_id)
        return
    loop.create_task(
        _run_fallback_runtime(
            scenario_input=scenario_input,
            execution_id=execution_id,
            org_id=org_id,
            actor_user_id=actor_user_id,
            manager=manager,
        ),
        name=f"fallback-exec-{execution_id}",
    )


async def _run_fallback_runtime(
    *,
    scenario_input: ScenarioInput,
    execution_id: str,
    org_id: str,
    actor_user_id: str,
    manager: Any,
) -> None:
    from db.database import AsyncSessionLocal
    from tasks.scenario_task import run_scenario_task

    device = manager.get_device(scenario_input.device_serial) if manager else None
    success = False
    if device is not None:
        scenario_name: str | None = None
        try:
            async with AsyncSessionLocal() as db:
                execution_row = await get_execution(db, execution_id)
                meta = execution_row.meta if execution_row else None
                if isinstance(meta, dict):
                    scenario_name = meta.get("org_scenario_name")
        except Exception:
            log.debug("fallback runtime: could not load execution meta for %s", execution_id)

        scenario = build_runtime_scenario_dict(
            scenario_input,
            execution_id,
            org_id=org_id,
            scenario_name=str(scenario_name) if scenario_name else None,
        )
        from common.variable_resolver import VariableContext

        var_ctx = VariableContext(
            scenario_vars=scenario.get("variables", {}),
            campaign_vars=scenario.get("_campaign_vars", {}),
            device_serial=device.serial,
            device_model=getattr(device, "model", ""),
        )
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: run_scenario_task(device, scenario, _var_ctx=var_ctx),
            )
            success = bool(result.get("success"))
        except Exception:
            log.exception("fallback runtime failed execution=%s", execution_id)
    else:
        log.warning(
            "fallback runtime: device %s offline — failing execution %s",
            scenario_input.device_serial,
            execution_id,
        )

    async with AsyncSessionLocal() as db:
        execution = await get_execution(db, execution_id)
        if execution is None:
            return
        await finish_fan_out_execution(
            db,
            execution,
            org_id=org_id,
            actor_user_id=actor_user_id,
            status="completed" if success else "failed",
        )
        campaign = await _load_campaign(db, execution.campaign_id, org_id)
        if campaign is not None:
            await maybe_promote_sequential_execution(
                db,
                execution,
                campaign=campaign,
                org_id=org_id,
                actor_user_id=actor_user_id,
                temporal_client=None,
                temporal_config=None,
                manager=manager,
            )
        await db.commit()


async def _load_campaign(
    db: AsyncSession,
    campaign_id: str | None,
    org_id: str,
) -> Campaign | None:
    if not campaign_id:
        return None
    from db.crud import campaign_entity as campaign_repo

    campaign = await campaign_repo.get_campaign_entity(db, campaign_id)
    if campaign is None or campaign.org_id != org_id:
        return None
    return campaign


async def _load_runtime_executions_by_id(
    db: AsyncSession,
    execution_ids: list[str],
) -> dict[str, Execution]:
    ids = [execution_id for execution_id in dict.fromkeys(execution_ids) if execution_id]
    if not ids:
        return {}
    result = await db.execute(select(Execution).where(Execution.id.in_(ids)))
    return {execution.id: execution for execution in result.scalars().all()}


async def _load_runtime_device_serials_by_execution(
    db: AsyncSession,
    execution_ids: list[str],
) -> dict[str, str]:
    ids = [execution_id for execution_id in dict.fromkeys(execution_ids) if execution_id]
    if not ids:
        return {}
    result = await db.execute(
        select(ExecutionDevice.execution_id, Device.serial)
        .join(Device, Device.id == ExecutionDevice.device_id)
        .where(ExecutionDevice.execution_id.in_(ids))
    )
    serials: dict[str, str] = {}
    for execution_id, serial in result.all():
        if execution_id not in serials and serial:
            serials[str(execution_id)] = str(serial)
    return serials


def _runtime_device_serial(
    execution: Execution,
    linked_serials: dict[str, str],
) -> str:
    cfg = execution.device_config or {}
    serial = str(cfg.get("device_serial") or "").strip()
    if serial:
        return serial
    return linked_serials.get(execution.id, "")


async def start_execution_runtime(
    db: AsyncSession,
    *,
    fan_out: FanOutResult,
    campaign: Campaign,
    org_id: str,
    actor_user_id: str,
    temporal_client: Any = None,
    temporal_config: Any = None,
    manager: Any = None,
) -> dict[str, Any]:
    """Start Temporal (or fallback) runtime for each running fan-out execution."""
    scenario_refs = await resolve_campaign_scenario_refs(db, campaign)
    stats: dict[str, Any] = {
        "temporal": 0,
        "fallback": 0,
        "failed": 0,
        "skipped": 0,
    }
    if not scenario_refs:
        stats["skipped"] = len(fan_out.executions)
        return stats

    use_temporal = _temporal_available(temporal_client, temporal_config)

    running_views = [
        view
        for view in fan_out.executions
        if view.status == ExecutionStatus.RUNNING.value
    ]
    stats["skipped"] += len(fan_out.executions) - len(running_views)
    if not running_views:
        return stats

    execution_ids = [view.execution_id for view in running_views]
    executions_by_id = await _load_runtime_executions_by_id(db, execution_ids)
    linked_serials = await _load_runtime_device_serials_by_execution(db, execution_ids)
    recovery_policy = dict(getattr(campaign, "recovery_policy", None) or {})
    registry_refs = _scenario_refs_with_recovery_refs(scenario_refs, recovery_policy)
    scenario_registry = await build_campaign_scenario_registry(
        db,
        campaign=campaign,
        org_id=org_id,
        scenario_refs=registry_refs,
    )
    campaign_vars = _runtime_campaign_vars(campaign)
    scenario_ids = [
        str(ref["scenario_id"])
        for ref in registry_refs
        if ref.get("scenario_id")
    ]
    device_ids = [str(view.device_id) for view in running_views if view.device_id]
    scenario_device_vars_bulk: dict[tuple[str, str], dict[str, Any]] = {}
    if scenario_ids and device_ids:
        from db.crud.scenario_device_variable import (
            get_campaign_org_scenario_device_variables_bulk,
        )

        scenario_device_vars_bulk = await get_campaign_org_scenario_device_variables_bulk(
            db,
            campaign.id,
            scenario_ids,
            device_ids,
        )

    device_index = 0
    prepared: list[tuple[FanOutExecutionView, Execution, ScenarioInput]] = []
    for view in running_views:
        execution = executions_by_id.get(view.execution_id)
        if execution is None:
            stats["failed"] += 1
            continue

        device_serial = _runtime_device_serial(execution, linked_serials)
        if not device_serial:
            stats["failed"] += 1
            continue

        effective_vars = view.effective_vars or dict((execution.device_config or {}).get("effective_vars") or {})
        account_vars = dict((execution.device_config or {}).get("account_vars") or {})
        scenario_device_vars = {
            scenario_id: normalize_device_vars(
                scenario_device_vars_bulk.get((scenario_id, view.device_id), {})
            )
            for scenario_id in scenario_ids
        }
        scenario_input = _build_prepared_scenario_input(
            execution=execution,
            campaign=campaign,
            org_id=org_id,
            device_serial=device_serial,
            effective_vars=effective_vars,
            account_vars=account_vars,
            scenario_refs=scenario_refs,
            scenario_registry=scenario_registry,
            campaign_vars=campaign_vars,
            recovery_policy=recovery_policy,
            scenario_device_vars=scenario_device_vars,
            device_index=device_index,
        )
        if scenario_input is None:
            stats["failed"] += 1
            continue

        prepared.append((view, execution, scenario_input))
        device_index += 1

    if not prepared:
        return stats

    async def _start_temporal_item(
        item: tuple[FanOutExecutionView, Execution, ScenarioInput],
        sem: asyncio.Semaphore,
    ) -> tuple[FanOutExecutionView, Execution, ScenarioInput, str | None, Exception | None]:
        view, execution, scenario_input = item
        async with sem:
            try:
                wf_id = await _try_start_temporal(
                    temporal_client,
                    temporal_config,
                    scenario_input,
                    execution.id,
                )
            except Exception as exc:
                return view, execution, scenario_input, None, exc
            return view, execution, scenario_input, wf_id, None

    if use_temporal:
        sem = asyncio.Semaphore(_runtime_start_concurrency_limit())
        temporal_results = await asyncio.gather(
            *(_start_temporal_item(item, sem) for item in prepared)
        )
    else:
        temporal_results = [
            (view, execution, scenario_input, None, None)
            for view, execution, scenario_input in prepared
        ]

    meta_changed = False
    for _view, execution, scenario_input, wf_id, exc in temporal_results:
        if wf_id:
            await _mark_runtime_meta(
                db,
                execution,
                dispatch_source=DISPATCH_SOURCE_TEMPORAL,
                workflow_id=wf_id,
                flush=False,
            )
            stats["temporal"] += 1
            meta_changed = True
            continue

        if exc is not None:
            log.error(
                "Temporal workflow start failed execution=%s: %s",
                execution.id,
                exc,
            )

        await _mark_runtime_meta(
            db,
            execution,
            dispatch_source=DISPATCH_SOURCE_FALLBACK,
            flush=False,
        )
        meta_changed = True
        schedule_fallback_runtime(
            scenario_input=scenario_input,
            execution_id=execution.id,
            org_id=org_id,
            actor_user_id=actor_user_id,
            manager=manager,
        )
        stats["fallback"] += 1

    if meta_changed:
        await db.flush()

    return stats


async def maybe_promote_sequential_execution(
    db: AsyncSession,
    finished_execution: Execution,
    *,
    campaign: Campaign,
    org_id: str,
    actor_user_id: str,
    temporal_client: Any = None,
    temporal_config: Any = None,
    manager: Any = None,
) -> bool:
    """After a sequential dispatch execution finishes, claim and start the next queued one."""
    meta = finished_execution.meta or {}
    if meta.get("dispatch_strategy") != "sequential":
        return False
    dispatch_id = meta.get("dispatch_id")
    if not dispatch_id or not finished_execution.campaign_id:
        return False

    stmt = (
        select(Execution)
        .where(
            Execution.campaign_id == finished_execution.campaign_id,
            Execution.status == ExecutionStatus.PENDING.value,
        )
        .order_by(Execution.created_at)
    )
    result = await db.execute(stmt)
    next_exec: Execution | None = None
    for candidate in result.scalars().all():
        cmeta = candidate.meta or {}
        if cmeta.get("dispatch_id") == dispatch_id and cmeta.get("queued"):
            next_exec = candidate
            break
    if next_exec is None:
        return False

    from services.campaign.dispatcher import CampaignDispatcher

    dispatcher = CampaignDispatcher()
    view = await dispatcher.activate_queued_execution(
        db,
        execution=next_exec,
        campaign=campaign,
        org_id=org_id,
        actor_user_id=actor_user_id,
    )
    if view is None or view.status != ExecutionStatus.RUNNING.value:
        return False

    single = FanOutResult(
        dispatch_id=str(dispatch_id),
        campaign_id=campaign.id,
        dispatch_strategy="sequential",
        executions=[view],
    )
    await start_execution_runtime(
        db,
        fan_out=single,
        campaign=campaign,
        org_id=org_id,
        actor_user_id=actor_user_id,
        temporal_client=temporal_client,
        temporal_config=temporal_config,
        manager=manager,
    )
    return True
