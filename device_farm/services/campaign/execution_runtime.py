"""Epic 04 execution runtime — Temporal workflow per fan-out execution (DF-T-04-010)."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.crud.execution import (
    get_execution,
    list_execution_devices,
    upsert_execution_result,
)
from db.models.campaign import Campaign
from db.models.device import Device
from db.models.enums import ExecutionStatus
from db.models.execution import Execution, ExecutionDevice
from common.campaign_scenario_refs import normalize_scenario_repeat_count
from services.campaign.dispatcher import (
    FanOutExecutionView,
    FanOutResult,
    finish_fan_out_execution,
    resolve_campaign_platform,
)
from services.campaign.scenario_sources import (
    build_campaign_scenario_registry,
    resolve_campaign_scenario_refs,
)
from services.execution.event_publisher import enqueue_execution_event
from services.execution.event_types import EXECUTION_FAILED
from services.execution.reason_codes import NODE_CAPABILITY_PREFLIGHT_FAILED
from services.temporal_orchestrator import (
    TemporalExecutionOrchestrator,
    workflow_id_for_execution as _temporal_workflow_id_for_execution,
)
from common.variable_resolver import normalize_device_vars
from temporal.shared import ScenarioInput, TASK_QUEUE_NAME

log = logging.getLogger(__name__)

DISPATCH_SOURCE_TEMPORAL = "temporal"
DISPATCH_SOURCE_FALLBACK = "fallback"
DEFAULT_RUNTIME_START_CONCURRENCY = 100
DEFAULT_READINESS_PROBE_CONCURRENCY = 8
_TEMPORAL_WORKFLOW_RUN: Any | None = None
_TEMPORAL_WORKFLOW_ID_REUSE_POLICY: Any | None = None


def workflow_id_for_execution(execution_id: str) -> str:
    """Deterministic Temporal workflow id (DF-T-04-010)."""
    return _temporal_workflow_id_for_execution(execution_id)


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


def _readiness_probe_concurrency_limit() -> int:
    """Fan-out cap for the pre-dispatch platform readiness probes.

    Each probe launches an app and dumps the UI hierarchy on a real device, so
    this is deliberately far below CAMPAIGN_RUNTIME_START_CONCURRENCY.
    """
    raw = os.getenv("CAMPAIGN_READINESS_PROBE_CONCURRENCY", "").strip()
    if not raw:
        return DEFAULT_READINESS_PROBE_CONCURRENCY
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_READINESS_PROBE_CONCURRENCY
    return max(1, min(value, 64))


async def _prefetch_platform_readiness(
    db: AsyncSession,
    *,
    org_id: str,
    platform: str,
    probe_plan: list[tuple[str, str, str]],
    manager: Any,
) -> dict[str, Any]:
    """Probe platform readiness for many devices concurrently, keyed by serial.

    The guard itself writes to the shared AsyncSession, which is not
    concurrency-safe, so only the device-bound half is parallelised here. The
    caller then feeds these results back into guard_platform_session so its
    sequential DB pass never touches a device.
    """
    if manager is None or not probe_plan:
        return {}

    from services.platform_session_guard import (
        observe_platform_readiness_for_device,
        platform_session_live_probe_required,
    )

    # Sequential, but these are cheap indexed reads — the point is to avoid
    # probing devices whose provenance already settles the guard.
    serials: list[str] = []
    for device_id, account_id, device_serial in probe_plan:
        try:
            needed = await platform_session_live_probe_required(
                db,
                org_id=org_id,
                device_id=device_id,
                account_id=account_id,
                platform=platform,
            )
        except Exception as exc:
            log.warning(
                "%s readiness pre-plan failed device=%s: %s", platform, device_id, exc
            )
            continue
        if needed and device_serial not in serials:
            serials.append(device_serial)

    if not serials:
        return {}

    sem = asyncio.Semaphore(_readiness_probe_concurrency_limit())

    async def _probe(serial: str) -> tuple[str, Any]:
        async with sem:
            try:
                return serial, await observe_platform_readiness_for_device(
                    device_serial=serial, manager=manager, platform=platform
                )
            except Exception as exc:
                log.warning(
                    "%s readiness probe failed serial=%s: %s", platform, serial, exc
                )
                return serial, None

    started = time.perf_counter()
    probed = dict(await asyncio.gather(*(_probe(serial) for serial in serials)))
    log.info(
        "%s readiness prefetch devices=%d elapsed_ms=%d",
        platform,
        len(serials),
        int((time.perf_counter() - started) * 1000),
    )
    return {serial: result for serial, result in probed.items() if result is not None}


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

    # The pinned refs are only the campaign's top level. A `run_scenario` step
    # inside one of them points at another library scenario that was never
    # loaded, so the runtime resolved nothing and failed with "sub-scenario not
    # found". Walk the refs transitively, same batching + depth bound as
    # org_scenario_validation.build_org_ref_cache.
    from services.scenario_dsl.body_validator import get_org_nesting_depth_limit
    from services.scenario_dsl.ref_cache import extract_run_scenario_id
    from services.scenario_dsl.step_tree import iter_authored_steps

    depth_limit = get_org_nesting_depth_limit(org_id)
    pending = list(dict.fromkeys(str(ref["scenario_id"]) for ref in scenario_refs))
    loaded: set[str] = set()

    for _ in range(depth_limit + 1):
        batch = [sid for sid in pending if sid not in loaded]
        if not batch:
            break
        bodies = await org_scenario_repo.get_org_scenario_bodies_by_ids(db, org_id, batch)
        names = await org_scenario_repo.get_org_scenario_names_by_ids(db, org_id, batch)
        loaded.update(batch)
        pending = []

        for scenario_id, _kind, body in bodies:
            payload = body if isinstance(body, dict) else {}
            name = names.get(scenario_id, scenario_id)
            entry = {
                "steps": payload.get("steps") or [],
                "variables": dict(payload.get("variables") or {}),
                "name": name,
                "requirements": dict(payload.get("requirements") or {}),
                "platform": payload.get("platform"),
                "tags": str(payload.get("tags") or ""),
            }
            registry["by_id"][scenario_id] = entry
            registry["by_campaign_name"][name] = entry
            # Nested, not just top level: a run_scenario can sit inside a loop
            # or an if branch, so walk the whole authored tree.
            for authored in iter_authored_steps(entry["steps"]):
                ref_id = extract_run_scenario_id(authored.step)
                if ref_id and ref_id not in loaded:
                    pending.append(ref_id)
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
    scenario_sequence_index = 0
    for scenario_ref_index, ref in enumerate(scenario_refs):
        scenario_id = str(ref["scenario_id"])
        repeat_count = normalize_scenario_repeat_count(ref.get("repeat_count"))
        scoped_vars = dict((scenario_device_vars or {}).get(scenario_id) or {})
        for repeat_index in range(repeat_count):
            merged_vars = {
                **campaign_override_vars,
                **device_override_vars,
                **scoped_vars,
                **account_vars,
                "DEVICE_INDEX": str(device_index),
                "SCENARIO_INDEX": str(scenario_sequence_index),
                "SCENARIO_REF_INDEX": str(scenario_ref_index),
                "SCENARIO_REPEAT_INDEX": str(repeat_index),
                "SCENARIO_REPEAT_COUNT": str(repeat_count),
            }
            steps.append(
                {
                    "type": "run_scenario",
                    "scenario_id": scenario_id,
                    "variables": merged_vars,
                    "scenario_ref_index": scenario_ref_index,
                    "scenario_sequence_index": scenario_sequence_index,
                    "repeat_index": repeat_index,
                    "repeat_count": repeat_count,
                }
            )
            scenario_sequence_index += 1
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


_CAPTURE_MODES = {"error_only", "extract_only", "all"}


def _resolve_capture_mode(campaign_vars: dict[str, Any]) -> str:
    """Per-campaign capture policy from ``__CAPTURE_MODE__``.

    "all" matches no mode in capture_service, so pre/post capture is allowed on
    successful steps too. Anything unset or unrecognised keeps the historical
    "error_only" behaviour.
    """
    raw = str(campaign_vars.get("__CAPTURE_MODE__") or "").strip().lower()
    return raw if raw in _CAPTURE_MODES else "error_only"


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
    scenario_config: dict[str, Any] = {
        "capture_mode": _resolve_capture_mode(campaign_vars)
    }
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
    scenario_registry: dict[str, Any] | None = None,
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
    registry = scenario_registry
    if registry is None:
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
    *,
    workflow_run: Any | None = None,
    id_reuse_policy: Any | None = None,
) -> str | None:
    if workflow_run is None or id_reuse_policy is None:
        workflow_run, id_reuse_policy = _temporal_workflow_start_symbols()

    task_queue = TASK_QUEUE_NAME
    if temporal_config is not None:
        task_queue = getattr(temporal_config, "task_queue", None) or task_queue

    return await TemporalExecutionOrchestrator(temporal_client).start_scenario_workflow(
        workflow_run=workflow_run,
        scenario_input=scenario_input,
        execution_id=execution_id,
        task_queue=task_queue,
        id_reuse_policy=id_reuse_policy,
    )


def _temporal_workflow_start_symbols() -> tuple[Any, Any]:
    global _TEMPORAL_WORKFLOW_RUN, _TEMPORAL_WORKFLOW_ID_REUSE_POLICY
    if _TEMPORAL_WORKFLOW_RUN is None or _TEMPORAL_WORKFLOW_ID_REUSE_POLICY is None:
        from temporal.workflows import ScenarioWorkflow
        from temporalio.common import WorkflowIDReusePolicy

        _TEMPORAL_WORKFLOW_RUN = ScenarioWorkflow.run
        _TEMPORAL_WORKFLOW_ID_REUSE_POLICY = WorkflowIDReusePolicy.ALLOW_DUPLICATE
    return _TEMPORAL_WORKFLOW_RUN, _TEMPORAL_WORKFLOW_ID_REUSE_POLICY


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
    commit_before_start: bool = False,
) -> dict[str, Any]:
    """Start Temporal (or fallback) runtime for each running fan-out execution."""
    # fan_out already resolved these in the same request; reuse instead of
    # re-querying every scenario body a second time.
    scenario_refs = getattr(fan_out, "scenario_refs", None)
    if scenario_refs is None:
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
    needs_linked_serials = any(
        not str(
            (getattr(execution, "device_config", None) or {}).get("device_serial") or ""
        ).strip()
        for execution in executions_by_id.values()
    )
    linked_serials = (
        await _load_runtime_device_serials_by_execution(db, execution_ids)
        if needs_linked_serials
        else {}
    )
    recovery_policy = dict(getattr(campaign, "recovery_policy", None) or {})
    registry_refs = _scenario_refs_with_recovery_refs(scenario_refs, recovery_policy)
    # fan_out built its registry from scenario_refs alone. Only reuse it when the
    # recovery policy contributed no extra scenario ids, otherwise the registry
    # would be missing the recovery scenarios' step bodies.
    prefetched_registry = getattr(fan_out, "scenario_registry", None)
    if prefetched_registry is not None and len(registry_refs) == len(scenario_refs):
        scenario_registry = prefetched_registry
    else:
        scenario_registry = await build_campaign_scenario_registry(
            db,
            campaign=campaign,
            org_id=org_id,
            scenario_refs=registry_refs,
        )
    from services.platform_session_runtime import (
        guard_reason_allows_login_recovery,
        scenario_registry_has_platform_login_gate,
        scenario_registry_platform_session_requirements,
    )

    allows_login_recovery = scenario_registry_has_platform_login_gate(
        scenario_registry,
        scenario_refs,
    )
    platform_session_requirements = scenario_registry_platform_session_requirements(
        scenario_registry,
        scenario_refs,
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
    from services.account_verification import (
        VerificationMode,
        VerificationStatus,
        load_verification_targets,
        persist_verification_results,
        verification_mode,
        verify_targets,
    )

    mode = verification_mode()
    assignment_pairs = [
        (view.device_id, str(getattr(executions_by_id.get(view.execution_id), "account_id", "")))
        for view in running_views
        if getattr(executions_by_id.get(view.execution_id), "account_id", None)
    ]
    targets = await load_verification_targets(db, assignments=assignment_pairs, org_id=org_id)
    if commit_before_start and db.in_transaction():
        await db.commit()
    verification_results = (
        await verify_targets(targets.values(), manager)
        if mode != VerificationMode.OFF
        else {}
    )
    await persist_verification_results(db, verification_results.values())

    # Probe every device that still needs a live platform readiness check up
    # front and in parallel. Without this the guard call inside the loop below
    # serialises one app-launch + UI dump (up to 6s) per device.
    campaign_platform = resolve_campaign_platform(campaign, scenario_registry)
    requires_platform_session = campaign_platform in platform_session_requirements
    probe_plan: list[tuple[str, str, str]] = []
    if requires_platform_session or allows_login_recovery:
        for view in running_views:
            execution = executions_by_id.get(view.execution_id)
            if execution is None:
                continue
            account_id = getattr(execution, "account_id", None)
            device_serial = _runtime_device_serial(execution, linked_serials)
            if account_id and device_serial and view.device_id:
                probe_plan.append((view.device_id, str(account_id), device_serial))
    readiness_by_serial = await _prefetch_platform_readiness(
        db,
        org_id=org_id,
        platform=campaign_platform,
        probe_plan=probe_plan,
        manager=manager,
    )

    for view in running_views:
        execution = executions_by_id.get(view.execution_id)
        if execution is None:
            stats["failed"] += 1
            continue

        device_serial = _runtime_device_serial(execution, linked_serials)
        if not device_serial:
            stats["failed"] += 1
            continue

        account_id = getattr(execution, "account_id", None)
        target = targets.get((view.device_id, account_id)) if account_id else None
        verification = verification_results.get(target.assignment_id) if target else None
        if account_id and mode != VerificationMode.OFF:
            if verification is None:
                from services.account_verification import AccountVerificationResult
                import uuid
                verification = AccountVerificationResult(
                    None, VerificationStatus.INCONCLUSIVE, "assignment_not_found",
                    datetime.now(timezone.utc), str(uuid.uuid4()),
                )
            execution.meta = {
                **(execution.meta or {}),
                "account_verification": {
                    "mode": mode.value,
                    **verification.evidence(detailed=False),
                    **(
                        {"deferred_to_scenario_login": True}
                        if allows_login_recovery
                        and verification.status == VerificationStatus.INCONCLUSIVE
                        else {}
                    ),
                },
            }
            verification_deferred = (
                allows_login_recovery
                and verification.status == VerificationStatus.INCONCLUSIVE
            )
            if (
                mode == VerificationMode.ENFORCE
                and not verification.allows_enforce
                and not verification_deferred
            ):
                await finish_fan_out_execution(
                    db,
                    execution,
                    org_id=org_id,
                    actor_user_id=actor_user_id,
                    status=ExecutionStatus.FAILED.value,
                    device_id=view.device_id,
                )
                stats["failed"] += 1
                continue

        if account_id and (requires_platform_session or allows_login_recovery):
            from services.platform_session_guard import guard_platform_session

            guard = await guard_platform_session(
                db,
                org_id=org_id,
                device_id=view.device_id,
                account_id=str(account_id),
                platform=campaign_platform,
                manager=manager,
                device_serial=device_serial,
                live_check=True,
                readiness=readiness_by_serial.get(device_serial),
            )
            session_guard_deferred = (
                allows_login_recovery
                and guard.blocks_execution
                and guard_reason_allows_login_recovery(guard.reason)
            )
            execution.meta = {
                **(execution.meta or {}),
                "platform_session_guard": {
                    **guard.to_meta(),
                    **(
                        {"deferred_to_scenario_login": True}
                        if session_guard_deferred
                        else {}
                    ),
                },
            }
            if guard.blocks_execution and not session_guard_deferred:
                await finish_fan_out_execution(
                    db,
                    execution,
                    org_id=org_id,
                    actor_user_id=actor_user_id,
                    status=ExecutionStatus.FAILED.value,
                    device_id=view.device_id,
                )
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
        stored_device_index = (execution.meta or {}).get("device_index")
        try:
            prepared_device_index = int(stored_device_index)
        except (TypeError, ValueError):
            prepared_device_index = device_index
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
            device_index=prepared_device_index,
        )
        if scenario_input is None:
            stats["failed"] += 1
            continue

        runtime_device = manager.get_device(device_serial) if manager else None
        if runtime_device is not None:
            from services.scenario_node_preflight import (
                preflight_scenario_registry_node_capabilities,
                scenario_node_preflight_failure_reason,
            )

            preflight = preflight_scenario_registry_node_capabilities(
                runtime_device,
                registry_refs,
                scenario_registry,
            )
            if not preflight.ok:
                reason = scenario_node_preflight_failure_reason(preflight)
                now = datetime.now(timezone.utc)
                execution.device_config = {
                    **(execution.device_config or {}),
                    "failure_reason": reason,
                }
                execution.meta = {
                    **(execution.meta or {}),
                    "node_capability_preflight": preflight.to_dict(),
                }
                evidence = {
                    "reason_code": NODE_CAPABILITY_PREFLIGHT_FAILED,
                    "operator_summary": reason,
                    "device_id": view.device_id,
                    "device_serial": device_serial,
                    "node_capability_preflight": preflight.to_dict(),
                }
                await enqueue_execution_event(
                    db,
                    event_type=EXECUTION_FAILED,
                    execution_id=execution.id,
                    organization_id=org_id,
                    campaign_id=campaign.id,
                    payload={
                        "reason_code": NODE_CAPABILITY_PREFLIGHT_FAILED,
                        "message": reason,
                        "device_id": view.device_id,
                        "device_serial": device_serial,
                        "node_capability_preflight": preflight.to_dict(),
                        "evidence": evidence,
                    },
                )
                await upsert_execution_result(
                    db,
                    execution_id=execution.id,
                    device_id=view.device_id,
                    status="failed",
                    error_detail=reason,
                    finished_at=now,
                )
                await finish_fan_out_execution(
                    db,
                    execution,
                    org_id=org_id,
                    actor_user_id=actor_user_id,
                    status=ExecutionStatus.FAILED.value,
                    device_id=view.device_id,
                )
                stats["failed"] += 1
                continue

        prepared.append((view, execution, scenario_input))
        device_index += 1

    if not prepared:
        return stats

    # HTTP dispatch persists snapshot + claims before any external RPC so row
    # locks are not held while Temporal accepts up to hundreds of workflows.
    # Other callers retain their existing transaction ownership by default.
    if commit_before_start and db.in_transaction():
        await db.commit()

    async def _start_temporal_item(
        item: tuple[FanOutExecutionView, Execution, ScenarioInput],
        workflow_run: Any,
        id_reuse_policy: Any,
    ) -> tuple[FanOutExecutionView, Execution, ScenarioInput, str | None, Exception | None]:
        view, execution, scenario_input = item
        try:
            wf_id = await _try_start_temporal(
                temporal_client,
                temporal_config,
                scenario_input,
                execution.id,
                workflow_run=workflow_run,
                id_reuse_policy=id_reuse_policy,
            )
        except Exception as exc:
            return view, execution, scenario_input, None, exc
        return view, execution, scenario_input, wf_id, None

    async def _start_temporal_bounded_item(
        item: tuple[FanOutExecutionView, Execution, ScenarioInput],
        sem: asyncio.Semaphore,
        workflow_run: Any,
        id_reuse_policy: Any,
    ) -> tuple[FanOutExecutionView, Execution, ScenarioInput, str | None, Exception | None]:
        async with sem:
            return await _start_temporal_item(item, workflow_run, id_reuse_policy)

    if use_temporal:
        limit = _runtime_start_concurrency_limit()
        workflow_run, id_reuse_policy = _temporal_workflow_start_symbols()
        if len(prepared) <= limit:
            temporal_results = await asyncio.gather(
                *(_start_temporal_item(item, workflow_run, id_reuse_policy) for item in prepared)
            )
        else:
            sem = asyncio.Semaphore(limit)
            temporal_results = await asyncio.gather(
                *(
                    _start_temporal_bounded_item(item, sem, workflow_run, id_reuse_policy)
                    for item in prepared
                )
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
