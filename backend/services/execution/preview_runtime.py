"""Preview runtime — Temporal/fallback for isolated scenario runs (DF-T-04-018)."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from db.crud.execution import get_execution
from db.models.enums import ExecutionStatus
from db.models.execution import Execution
from services.campaign.execution_runtime import (
    _mark_runtime_meta,
    _resolve_device_serial,
    _try_start_temporal,
    _temporal_available,
    build_org_scenario_registry,
    build_sequence_steps,
    schedule_fallback_runtime,
    workflow_id_for_execution,
    DISPATCH_SOURCE_FALLBACK,
    DISPATCH_SOURCE_TEMPORAL,
)
from services.execution.preview_collection import PREVIEW_COLLECTION_VAR, preview_collection_name
from temporal.shared import ScenarioInput

log = logging.getLogger(__name__)


async def prepare_preview_scenario_input(
    db: AsyncSession,
    *,
    execution: Execution,
    org_id: str,
    org_scenario_id: str,
    device_serial: str,
    effective_vars: dict[str, Any],
    account_vars: dict[str, Any],
) -> ScenarioInput | None:
    scenario_refs = [{"scenario_id": org_scenario_id}]
    registry = await build_org_scenario_registry(db, org_id, scenario_refs)
    sequence_steps = build_sequence_steps(
        scenario_refs,
        device_index=0,
        effective_vars=effective_vars,
        account_vars=account_vars,
    )
    if not sequence_steps:
        return None

    preview_collection = preview_collection_name(org_id)
    campaign_vars = {
        PREVIEW_COLLECTION_VAR: preview_collection,
        "__USER_ID__": execution.user_id or "",
        "__ORG_ID__": org_id,
    }
    meta = execution.meta if isinstance(execution.meta, dict) else {}
    org_scenario_name = meta.get("org_scenario_name")
    scenario_config: dict[str, Any] = {
        "capture_steps": True,
        "preview_collection": preview_collection,
    }
    if org_scenario_name:
        scenario_config["scenario_name"] = org_scenario_name

    return ScenarioInput(
        campaign_id="",
        device_serial=device_serial,
        steps=sequence_steps,
        variables=dict(effective_vars),
        campaign_vars=campaign_vars,
        scenario_registry=registry,
        capture_steps=True,
        scenario_config=scenario_config,
        execution_id=execution.id,
        run_id=execution.id,
        start_step=0,
    )


async def start_preview_runtime(
    db: AsyncSession,
    *,
    execution: Execution,
    org_id: str,
    org_scenario_id: str,
    actor_user_id: str,
    effective_vars: dict[str, Any],
    account_vars: dict[str, Any],
    temporal_client: Any = None,
    temporal_config: Any = None,
    manager: Any = None,
) -> dict[str, Any]:
    """Start Temporal (or fallback) for a preview execution."""
    if execution.status != ExecutionStatus.RUNNING.value:
        return {"started": False, "reason": "execution_not_running"}

    device_serial = await _resolve_device_serial(db, execution)
    if not device_serial:
        return {"started": False, "reason": "device_serial_missing"}

    scenario_input = await prepare_preview_scenario_input(
        db,
        execution=execution,
        org_id=org_id,
        org_scenario_id=org_scenario_id,
        device_serial=device_serial,
        effective_vars=effective_vars,
        account_vars=account_vars,
    )
    if scenario_input is None:
        return {"started": False, "reason": "scenario_input_empty"}

    use_temporal = _temporal_available(temporal_client, temporal_config)
    workflow_id: str | None = None
    dispatch_source = DISPATCH_SOURCE_FALLBACK

    if use_temporal:
        try:
            workflow_id = await _try_start_temporal(
                temporal_client,
                temporal_config,
                scenario_input,
                execution.id,
            )
            dispatch_source = DISPATCH_SOURCE_TEMPORAL
        except Exception as exc:
            log.error("preview Temporal start failed execution=%s: %s", execution.id, exc)

    await _mark_runtime_meta(
        db,
        execution,
        dispatch_source=dispatch_source,
        workflow_id=workflow_id,
    )

    if dispatch_source == DISPATCH_SOURCE_TEMPORAL:
        return {
            "started": True,
            "dispatch_source": dispatch_source,
            "workflow_id": workflow_id or workflow_id_for_execution(execution.id),
        }

    schedule_fallback_runtime(
        scenario_input=scenario_input,
        execution_id=execution.id,
        org_id=org_id,
        actor_user_id=actor_user_id,
        manager=manager,
    )
    return {
        "started": True,
        "dispatch_source": dispatch_source,
        "workflow_id": workflow_id_for_execution(execution.id),
    }
