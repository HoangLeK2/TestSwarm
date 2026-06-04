"""Epic 04 execution runtime — Temporal workflow per fan-out execution (DF-T-04-010)."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.crud.execution import get_execution, list_execution_devices
from db.models.campaign import Campaign
from db.models.device import Device
from db.models.enums import ExecutionStatus
from db.models.execution import Execution
from services.campaign.dispatcher import FanOutResult, finish_fan_out_execution
from services.campaign.scenario_sources import (
    build_campaign_scenario_registry,
    resolve_campaign_scenario_refs,
)
from temporal.shared import ScenarioInput, TASK_QUEUE_NAME

log = logging.getLogger(__name__)

DISPATCH_SOURCE_TEMPORAL = "temporal"
DISPATCH_SOURCE_FALLBACK = "fallback"


def workflow_id_for_execution(execution_id: str) -> str:
    """Deterministic Temporal workflow id (DF-T-04-010)."""
    return f"exec_{execution_id}"


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
) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for scenario_idx, ref in enumerate(scenario_refs):
        merged_vars = {
            **effective_vars,
            **account_vars,
            "DEVICE_INDEX": str(device_index),
            "SCENARIO_INDEX": str(scenario_idx),
        }
        steps.append(
            {
                "type": "run_scenario",
                "scenario_id": ref["scenario_id"],
                "variables": merged_vars,
            }
        )
    return steps


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
    device_index: int = 0,
) -> ScenarioInput | None:
    refs = scenario_refs if scenario_refs is not None else await resolve_campaign_scenario_refs(
        db, campaign
    )
    if not refs:
        return None
    registry = await build_campaign_scenario_registry(
        db,
        campaign=campaign,
        org_id=org_id,
        scenario_refs=refs,
    )
    sequence_steps = build_sequence_steps(
        refs,
        device_index=device_index,
        effective_vars=effective_vars,
        account_vars=account_vars,
    )
    if not sequence_steps:
        return None

    campaign_vars = dict(campaign.variables or {})
    owner = campaign.created_by or campaign.user_id
    if owner:
        campaign_vars.setdefault("__USER_ID__", str(owner))

    start_step = int((execution.meta or {}).get("start_step") or execution.checkpoint_step or 0)

    return ScenarioInput(
        campaign_id=campaign.id,
        device_serial=device_serial,
        steps=sequence_steps,
        variables=dict(effective_vars),
        campaign_vars=campaign_vars,
        scenario_registry=registry,
        execution_id=execution.id,
        run_id=execution.id,
        start_step=max(0, start_step),
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
) -> None:
    meta = dict(execution.meta or {})
    meta["dispatch_source"] = dispatch_source
    if workflow_id:
        meta["workflow_id"] = workflow_id
        meta["workflow_ids"] = [workflow_id]
    execution.meta = meta
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
        "settle_timeout_ms",
        "preview_collection",
    ):
        if key in scenario_config:
            scenario[key] = scenario_config[key]

    if getattr(scenario_input, "capture_steps", False) or scenario_config.get("capture_steps"):
        scenario["capture_steps"] = True
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
    device_index = 0

    for view in fan_out.executions:
        if view.status != ExecutionStatus.RUNNING.value:
            stats["skipped"] += 1
            continue

        execution = await get_execution(db, view.execution_id)
        if execution is None:
            stats["failed"] += 1
            continue

        device_serial = await _resolve_device_serial(db, execution)
        if not device_serial:
            stats["failed"] += 1
            continue

        effective_vars = view.effective_vars or dict((execution.device_config or {}).get("effective_vars") or {})
        account_vars = dict((execution.device_config or {}).get("account_vars") or {})

        scenario_input = await prepare_scenario_input(
            db,
            execution=execution,
            campaign=campaign,
            org_id=org_id,
            device_serial=device_serial,
            effective_vars=effective_vars,
            account_vars=account_vars,
            scenario_refs=scenario_refs,
            device_index=device_index,
        )
        if scenario_input is None:
            stats["failed"] += 1
            continue

        started = False
        if use_temporal:
            try:
                wf_id = await _try_start_temporal(
                    temporal_client,
                    temporal_config,
                    scenario_input,
                    execution.id,
                )
                await _mark_runtime_meta(
                    db,
                    execution,
                    dispatch_source=DISPATCH_SOURCE_TEMPORAL,
                    workflow_id=wf_id,
                )
                stats["temporal"] += 1
                started = True
            except Exception as exc:
                log.error(
                    "Temporal workflow start failed execution=%s: %s",
                    execution.id,
                    exc,
                )

        if not started:
            await _mark_runtime_meta(
                db,
                execution,
                dispatch_source=DISPATCH_SOURCE_FALLBACK,
            )
            schedule_fallback_runtime(
                scenario_input=scenario_input,
                execution_id=execution.id,
                org_id=org_id,
                actor_user_id=actor_user_id,
                manager=manager,
            )
            stats["fallback"] += 1

        device_index += 1

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
