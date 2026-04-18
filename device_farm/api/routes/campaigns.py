
from __future__ import annotations

import asyncio
import re as _re
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

_SERIAL_RE = _re.compile(r"^[\w.:_\-]{1,128}$")

from api.deps import CurrentUser, DB
from api.schemas.campaign import (
    CampaignCreate, CampaignDeviceOut, CampaignOut,
    ScenarioCreate, ScenarioUpdate, ScenarioOut,
)
from db import crud as repo
from db.crud.default_scenario import (
    ensure_default_scenario,
    get_default_scenario,
    merge_scenario_variables_for_row,
    scenario_row_to_embedded_dict,
)
from db.crud.device import get_device_by_serial
from services.image_store import save_step_images, delete_scenario_images

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


class StatusUpdate(BaseModel):
    status: str  # draft | running | paused | completed


class StepActionBody(BaseModel):
    action: str           # "retry" | "skip"
    device_serial: str | None = None  # None = apply to all paused-on-error workflows


class AddDeviceBody(BaseModel):
    device_id: str


class ScenarioUpdateBody(BaseModel):
    scenario: dict


class CompileScenarioBody(BaseModel):
    instructions: str | None = None
    ui_xml: str | None = None
    device_serial: str | None = None
    device_context: dict | None = None
    scenario_id: str | None = None  # if provided, save to specific scenario


# ── Helper ──────────────────────────────────────────────────────────────────

def _scenario_to_out(s) -> ScenarioOut:
    return ScenarioOut(
        id=s.id,
        campaign_id=s.campaign_id,
        name=s.name,
        instructions=s.instructions or "",
        steps=s.steps or [],
        variables=s.variables or {},
        order=s.order,
        nodes=s.nodes or [],
        edges=s.edges or [],
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


def _to_out(c, scenarios=None) -> CampaignOut:
    scenarios_list = scenarios or []
    embedded = None
    if scenarios_list:
        embedded = scenario_row_to_embedded_dict(scenarios_list[0])
    return CampaignOut(
        id=c.id, name=c.name, description=c.description,
        status=c.status, scenario=embedded,
        variables=c.variables or {},
        scenarios=[_scenario_to_out(s) for s in scenarios_list],
        user_id=c.user_id, created_at=c.created_at,
        target_group_id=getattr(c, "target_group_id", None),
    )


async def _get_campaign_or_404(campaign_id: str, user_id: str, db):
    campaign = await repo.get_campaign(db, campaign_id)
    if not campaign or campaign.user_id != user_id:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


# ── Campaign CRUD ────────────────────────────────────────────────────────────

@router.get("", response_model=list[CampaignOut])
async def list_campaigns(db: DB, user: CurrentUser):
    campaigns = await repo.list_campaigns(db, user_id=user.id)
    result = []
    for c in campaigns:
        scenarios = await repo.list_scenarios(db, c.id)
        result.append(_to_out(c, scenarios))
    return result


@router.post("", response_model=CampaignOut, status_code=status.HTTP_201_CREATED)
async def create_campaign(body: CampaignCreate, db: DB, user: CurrentUser):
    valid_device_ids: list[str] = []
    for device_id in body.device_ids:
        device = await repo.get_device(db, device_id)
        if not device or device.user_id != user.id:
            raise HTTPException(status_code=404, detail=f"Device not found: {device_id}")
        valid_device_ids.append(device_id)

    campaign = await repo.create_campaign(
        db, body.name, user.id, body.description, body.variables,
        target_group_id=body.target_group_id,
    )
    for device_id in valid_device_ids:
        await repo.add_device_to_campaign(db, campaign.id, device_id)
    sc = body.scenario or {}
    steps = sc.get("steps") if isinstance(sc, dict) else None
    if isinstance(steps, list) and len(steps) > 0:
        scenario_template_vars: dict = (sc.get("variables") or {}) if isinstance(sc, dict) else {}
        merged_vars = merge_scenario_variables_for_row(
            {**scenario_template_vars, **(body.variables or {})},
            {},
            sc.get("device_context") if isinstance(sc, dict) else None,
        )
        scenario_row = await repo.create_scenario(
            db,
            campaign.id,
            name=body.name,
            instructions=(sc.get("instructions") or "") if isinstance(sc, dict) else "",
            steps=[],
            variables=merged_vars,
            order=0,
        )
        await db.flush()
        saved_steps = save_step_images(steps, scenario_row.id)
        from common.graph_compiler import steps_to_graph
        nodes, edges = steps_to_graph(saved_steps)
        await repo.update_scenario(db, scenario_row.id, steps=saved_steps, nodes=nodes, edges=edges)
    elif isinstance(sc, dict) and (
        sc.get("instructions")
        or sc.get("variables")
        or sc.get("device_context")
    ):
        scenario_template_vars = (sc.get("variables") or {}) if isinstance(sc.get("variables"), dict) else {}
        merged_vars = merge_scenario_variables_for_row(
            {**scenario_template_vars, **(body.variables or {})},
            {},
            sc.get("device_context"),
        )
        await repo.create_scenario(
            db,
            campaign.id,
            name=body.name,
            instructions=str(sc.get("instructions") or ""),
            steps=[],
            variables=merged_vars,
            order=0,
        )
    await db.commit()
    scenarios = await repo.list_scenarios(db, campaign.id)
    return _to_out(campaign, scenarios)


@router.get("/{campaign_id}", response_model=CampaignOut)
async def get_campaign(campaign_id: str, db: DB, user: CurrentUser):
    campaign = await _get_campaign_or_404(campaign_id, user.id, db)
    scenarios = await repo.list_scenarios(db, campaign_id)
    return _to_out(campaign, scenarios)


@router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_campaign(campaign_id: str, db: DB, user: CurrentUser):
    campaign = await _get_campaign_or_404(campaign_id, user.id, db)
    from sqlalchemy import delete
    from db.models import Campaign as CampaignModel
    await db.execute(delete(CampaignModel).where(CampaignModel.id == campaign_id))
    await db.commit()


@router.patch("/{campaign_id}/status")
async def update_status(campaign_id: str, body: StatusUpdate, db: DB, user: CurrentUser, request: Request):
    await _get_campaign_or_404(campaign_id, user.id, db)
    valid = {"idle", "running", "stopped", "draft", "paused", "completed"}
    if body.status not in valid:
        raise HTTPException(status_code=400, detail=f"status must be one of {valid}")

    cancelled_count = 0
    cancel_trigger = body.status in ("stopped", "idle", "completed")
    pause_trigger = body.status == "paused"
    resume_trigger = body.status == "running"

    if cancel_trigger:
        queue = getattr(request.app.state, "queue", None)
        if queue is not None:
            prefix = f"campaign:{campaign_id}:"
            cancelled_count = queue.cancel_by_name_prefix(prefix)

    config = getattr(request.app.state, "config", None)
    if config is not None and getattr(config, "temporal", None) and config.temporal.enabled:
        try:
            from temporal.worker import get_temporal_client
            from temporal.workflows import ScenarioStepsWorkflow, ScenarioWorkflow

            t_client = await get_temporal_client(config.temporal)
            wf_query = f'WorkflowId STARTS_WITH "campaign:{campaign_id}:" AND ExecutionStatus="Running"'
            async for wf in t_client.list_workflows(wf_query):
                for wf_id in [wf.id, f"{wf.id}:steps"]:
                    try:
                        handle = t_client.get_workflow_handle(wf_id)
                        if cancel_trigger:
                            await handle.cancel()
                        elif pause_trigger:
                            await handle.signal(ScenarioWorkflow.pause if wf_id == wf.id else ScenarioStepsWorkflow.pause)
                        elif resume_trigger:
                            await handle.signal(ScenarioWorkflow.resume if wf_id == wf.id else ScenarioStepsWorkflow.resume)
                    except Exception as exc:
                        import logging
                        logging.getLogger(__name__).warning(
                            "Failed to update workflow %s: %s", wf_id, exc
                        )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Temporal signal failed: %s", exc)

    if body.status == "running":
        db_status = "running"
    elif body.status == "paused":
        db_status = "paused"
    else:
        db_status = "idle"
    await repo.update_campaign_status(db, campaign_id, db_status)
    await db.commit()
    return {"id": campaign_id, "status": db_status, "tasks_cancelled": cancelled_count}


@router.post("/{campaign_id}/step-action")
async def step_action(campaign_id: str, body: StepActionBody, db: DB, user: CurrentUser, request: Request):
    """Send retry_step or skip_step signal to workflows paused on error.

    When a step fails and its on_error policy is "pause", the workflow blocks
    waiting for this signal.
      - action="retry": re-execute the failed step from the beginning
      - action="skip":  skip the failed step and continue with the next one

    device_serial: if provided, only signal the workflow for that device.
                   if None, signal all paused-on-error workflows for this campaign.
    """
    await _get_campaign_or_404(campaign_id, user.id, db)
    if body.action not in ("retry", "skip"):
        raise HTTPException(status_code=400, detail="action must be 'retry' or 'skip'")
    if body.device_serial and not _SERIAL_RE.match(body.device_serial):
        raise HTTPException(status_code=400, detail="Invalid device_serial format")

    config = getattr(request.app.state, "config", None)
    if config is None or not getattr(config, "temporal", None) or not config.temporal.enabled:
        raise HTTPException(status_code=400, detail="Temporal is not enabled")

    from temporal.worker import get_temporal_client
    from temporal.workflows import ScenarioStepsWorkflow

    signal_name = "retry_step" if body.action == "retry" else "skip_step"
    t_client = await get_temporal_client(config.temporal)

    # Build query: all running workflows for this campaign (optionally filtered by device)
    wf_query = f'WorkflowId STARTS_WITH "campaign:{campaign_id}:" AND ExecutionStatus="Running"'
    if body.device_serial:
        wf_query = (
            f'WorkflowId STARTS_WITH "campaign:{campaign_id}:device:{body.device_serial}:" '
            f'AND ExecutionStatus="Running"'
        )

    import logging
    log = logging.getLogger(__name__)
    signalled: list[str] = []
    errors: list[str] = []

    async for wf in t_client.list_workflows(wf_query):
        # Signal the child ScenarioStepsWorkflow (the one that manages step execution)
        child_id = f"{wf.id}:steps"
        try:
            handle = t_client.get_workflow_handle(child_id)
            await handle.signal(signal_name)
            signalled.append(child_id)
        except Exception as exc:
            log.warning("Failed to signal %s: %s", child_id, exc)
            errors.append(child_id)

    return {
        "action": body.action,
        "signalled": signalled,
        "errors": errors,
        "total": len(signalled),
    }


@router.get("/{campaign_id}/devices", response_model=list[CampaignDeviceOut])
async def campaign_devices(campaign_id: str, db: DB, user: CurrentUser):
    await _get_campaign_or_404(campaign_id, user.id, db)
    devices = await repo.list_campaign_devices(db, campaign_id)
    return [CampaignDeviceOut(id=d.id, serial=d.serial, name=d.name) for d in devices]


@router.post("/{campaign_id}/devices", status_code=status.HTTP_201_CREATED)
async def add_device(campaign_id: str, body: AddDeviceBody, db: DB, user: CurrentUser):
    await _get_campaign_or_404(campaign_id, user.id, db)
    device = await repo.get_device(db, body.device_id)
    if not device or device.user_id != user.id:
        raise HTTPException(status_code=404, detail="Device not found")
    await repo.add_device_to_campaign(db, campaign_id, body.device_id)
    await db.commit()
    return {"ok": True}


@router.delete("/{campaign_id}/devices/{device_id}")
async def remove_device(campaign_id: str, device_id: str, db: DB, user: CurrentUser):
    await _get_campaign_or_404(campaign_id, user.id, db)
    device = await repo.get_device(db, device_id)
    if not device or device.user_id != user.id:
        raise HTTPException(status_code=404, detail="Device not found")
    await repo.remove_device_from_campaign(db, campaign_id, device_id)
    await db.commit()
    return {"ok": True}


# ── Content stats for this campaign ──────────────────────────────────────────

@router.get("/{campaign_id}/content/stats")
async def campaign_content_stats(campaign_id: str, db: DB, user: CurrentUser):
    """Return number of content items scraped for this campaign."""
    await _get_campaign_or_404(campaign_id, user.id, db)
    from sqlalchemy import func, select
    from db.models.content import ContentItem
    total = (
        await db.execute(
            select(func.count(ContentItem.id)).where(ContentItem.campaign_id == campaign_id)
        )
    ).scalar_one()
    latest = (
        await db.execute(
            select(func.max(ContentItem.extracted_at)).where(ContentItem.campaign_id == campaign_id)
        )
    ).scalar_one()
    return {
        "campaign_id": campaign_id,
        "total_items": total,
        "latest_extraction": latest.isoformat() if latest else None,
    }


# ── PATCH full scenario blob → default Scenario row (MCP / legacy clients) ────

@router.patch("/{campaign_id}/scenario", response_model=CampaignOut)
async def update_scenario(
    campaign_id: str, body: ScenarioUpdateBody, db: DB, user: CurrentUser
):
    from common.graph_compiler import compile_graph_to_steps, ensure_step_ids, steps_to_graph

    campaign = await _get_campaign_or_404(campaign_id, user.id, db)
    patch = body.scenario if isinstance(body.scenario, dict) else {}
    s = await ensure_default_scenario(db, campaign.id, name=campaign.name)
    instructions = str(patch.get("instructions", s.instructions or ""))
    nodes_in = patch.get("nodes")
    edges_in = patch.get("edges")
    steps_in = patch.get("steps")
    patch_vars = patch.get("variables") if isinstance(patch.get("variables"), dict) else {}
    device_context = patch.get("device_context")

    if isinstance(nodes_in, list) and len(nodes_in) > 0:
        compiled = compile_graph_to_steps(nodes_in, edges_in or [])
        saved_steps = ensure_step_ids(save_step_images(compiled, s.id))
        n, e = steps_to_graph(saved_steps)
        vars_merged = merge_scenario_variables_for_row(s.variables, patch_vars, device_context)
        await repo.update_scenario(
            db, s.id,
            instructions=instructions, steps=saved_steps, nodes=n, edges=e, variables=vars_merged,
        )
    elif isinstance(steps_in, list):
        saved_steps = ensure_step_ids(save_step_images(steps_in, s.id))
        n, e = steps_to_graph(saved_steps) if saved_steps else ([], [])
        vars_merged = merge_scenario_variables_for_row(s.variables, patch_vars, device_context)
        await repo.update_scenario(
            db, s.id,
            instructions=instructions, steps=saved_steps, nodes=n, edges=e, variables=vars_merged,
        )
    else:
        vars_merged = merge_scenario_variables_for_row(s.variables, patch_vars, device_context)
        await repo.update_scenario(db, s.id, instructions=instructions, variables=vars_merged)
    await db.commit()
    scenarios = await repo.list_scenarios(db, campaign_id)
    return _to_out(campaign, scenarios)


@router.post("/{campaign_id}/compile-scenario", response_model=CampaignOut)
async def compile_scenario(
    request: Request,
    campaign_id: str,
    body: CompileScenarioBody,
    db: DB,
    user: CurrentUser,
):
    from runtime.ai.ai_client import build_scenario_from_instructions

    campaign = await _get_campaign_or_404(campaign_id, user.id, db)

    # Resolve instructions
    instructions = body.instructions
    if not instructions and body.scenario_id:
        s = await repo.get_scenario(db, body.scenario_id)
        if not s or s.campaign_id != campaign_id:
            raise HTTPException(status_code=404, detail="Scenario not found")
        instructions = s.instructions or ""
    if not instructions:
        d0 = await get_default_scenario(db, campaign.id)
        if d0:
            instructions = scenario_row_to_embedded_dict(d0).get("instructions") or ""
    if not instructions:
        raise HTTPException(
            status_code=400,
            detail="No instructions provided",
        )

    device_context = body.device_context
    if device_context is None:
        dctx = await get_default_scenario(db, campaign.id)
        if dctx:
            device_context = scenario_row_to_embedded_dict(dctx).get("device_context")

    ui_xml = (body.ui_xml or "").strip() or None
    if not ui_xml and body.device_serial:
        device_row = await get_device_by_serial(db, body.device_serial.strip())
        if not device_row or device_row.user_id != user.id:
            raise HTTPException(status_code=404, detail="Device not found")
        manager = getattr(request.app.state, "manager", None)
        if manager:
            device = manager.get_device(body.device_serial.strip())
            if device:
                loop = asyncio.get_running_loop()
                ui_xml = await loop.run_in_executor(
                    None, lambda: device.hierarchy_xml(force_refresh=True)
                )
                if not (ui_xml or "").strip():
                    ui_xml = None

    scenario = build_scenario_from_instructions(
        instructions,
        ui_xml=ui_xml,
        device_context=device_context,
    )
    from common.scenario_schema import validate_scenario
    validation_errors = validate_scenario(scenario)
    if validation_errors:
        raise HTTPException(
            status_code=400,
            detail={"message": "Scenario validation failed", "errors": validation_errors},
        )

    if body.scenario_id:
        s = await repo.get_scenario(db, body.scenario_id)
        if not s or s.campaign_id != campaign_id:
            raise HTTPException(status_code=404, detail="Scenario not found")
        from common.graph_compiler import steps_to_graph
        compiled_steps = scenario.get("steps", [])
        nodes, edges = steps_to_graph(compiled_steps)
        vars_merged = merge_scenario_variables_for_row(
            s.variables,
            scenario.get("variables") if isinstance(scenario.get("variables"), dict) else {},
            body.device_context,
        )
        await repo.update_scenario(
            db, body.scenario_id,
            steps=compiled_steps,
            instructions=instructions,
            nodes=nodes,
            edges=edges,
            variables=vars_merged,
        )
    else:
        from common.graph_compiler import steps_to_graph
        tgt = await ensure_default_scenario(db, campaign.id, name=campaign.name)
        compiled_steps = scenario.get("steps", [])
        nodes, edges = steps_to_graph(compiled_steps)
        vars_merged = merge_scenario_variables_for_row(
            tgt.variables,
            scenario.get("variables") if isinstance(scenario.get("variables"), dict) else {},
            body.device_context,
        )
        await repo.update_scenario(
            db, tgt.id,
            steps=compiled_steps,
            instructions=instructions,
            nodes=nodes,
            edges=edges,
            variables=vars_merged,
        )
        await db.flush()

    await db.commit()
    scenarios = await repo.list_scenarios(db, campaign_id)
    return _to_out(campaign, scenarios)


# ── Scenario CRUD ─────────────────────────────────────────────────────────────

@router.get("/{campaign_id}/scenarios", response_model=list[ScenarioOut])
async def list_scenarios(campaign_id: str, db: DB, user: CurrentUser):
    await _get_campaign_or_404(campaign_id, user.id, db)
    scenarios = await repo.list_scenarios(db, campaign_id)
    return [_scenario_to_out(s) for s in scenarios]


@router.post("/{campaign_id}/scenarios", response_model=ScenarioOut, status_code=201)
async def create_scenario(campaign_id: str, body: ScenarioCreate, db: DB, user: CurrentUser):
    await _get_campaign_or_404(campaign_id, user.id, db)
    # auto-order: append after last
    existing = await repo.list_scenarios(db, campaign_id)
    order = body.order if body.order else len(existing)
    s = await repo.create_scenario(
        db, campaign_id,
        name=body.name,
        instructions=body.instructions,
        steps=[],
        variables=body.variables,
        order=order,
    )
    await db.flush()
    from common.graph_compiler import ensure_step_ids, steps_to_graph
    saved_steps = save_step_images(body.steps or [], s.id)
    saved_steps = ensure_step_ids(saved_steps)
    nodes, edges = steps_to_graph(saved_steps)
    await repo.update_scenario(db, s.id, steps=saved_steps, nodes=nodes, edges=edges)
    await db.commit()
    s = await repo.get_scenario(db, s.id)
    return _scenario_to_out(s)


@router.get("/{campaign_id}/scenarios/{scenario_id}", response_model=ScenarioOut)
async def get_scenario(campaign_id: str, scenario_id: str, db: DB, user: CurrentUser):
    await _get_campaign_or_404(campaign_id, user.id, db)
    s = await repo.get_scenario(db, scenario_id)
    if not s or s.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return _scenario_to_out(s)


@router.patch("/{campaign_id}/scenarios/{scenario_id}", response_model=ScenarioOut)
async def update_scenario_route(
    campaign_id: str, scenario_id: str, body: ScenarioUpdate, db: DB, user: CurrentUser
):
    await _get_campaign_or_404(campaign_id, user.id, db)
    s = await repo.get_scenario(db, scenario_id)
    if not s or s.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Scenario not found")
    updates = {k: v for k, v in body.model_dump(exclude_unset=True).items()}

    # Graph model: compile nodes+edges → steps for executor
    if "nodes" in updates:
        from common.graph_compiler import compile_graph_to_steps
        # After model_dump(exclude_unset=True), nodes/edges are already plain dicts
        updates["steps"] = compile_graph_to_steps(updates["nodes"], updates.get("edges", []))
    elif "steps" in updates:
        from common.graph_compiler import ensure_step_ids, steps_to_graph
        updates["steps"] = save_step_images(updates["steps"], scenario_id)
        updates["steps"] = ensure_step_ids(updates["steps"])
        updates["nodes"], updates["edges"] = steps_to_graph(updates["steps"])

    if updates:
        await repo.update_scenario(db, scenario_id, **updates)
    await db.commit()
    s = await repo.get_scenario(db, scenario_id)
    return _scenario_to_out(s)


@router.delete("/{campaign_id}/scenarios/{scenario_id}", status_code=204)
async def delete_scenario_route(
    campaign_id: str, scenario_id: str, db: DB, user: CurrentUser
):
    await _get_campaign_or_404(campaign_id, user.id, db)
    s = await repo.get_scenario(db, scenario_id)
    if not s or s.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Scenario not found")
    await repo.delete_scenario(db, scenario_id)
    await db.commit()
    delete_scenario_images(scenario_id)


# ── Compile scenario for a specific scenario row ──────────────────────────────

@router.post("/{campaign_id}/scenarios/{scenario_id}/compile", response_model=ScenarioOut)
async def compile_scenario_row(
    request: Request,
    campaign_id: str,
    scenario_id: str,
    body: CompileScenarioBody,
    db: DB,
    user: CurrentUser,
):
    from runtime.ai.ai_client import build_scenario_from_instructions

    await _get_campaign_or_404(campaign_id, user.id, db)
    s = await repo.get_scenario(db, scenario_id)
    if not s or s.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Scenario not found")

    instructions = body.instructions or s.instructions or ""
    if not instructions:
        raise HTTPException(status_code=400, detail="No instructions provided")

    ui_xml = (body.ui_xml or "").strip() or None
    if not ui_xml and body.device_serial:
        device_row = await get_device_by_serial(db, body.device_serial.strip())
        if not device_row or device_row.user_id != user.id:
            raise HTTPException(status_code=404, detail="Device not found")
        manager = getattr(request.app.state, "manager", None)
        if manager:
            device = manager.get_device(body.device_serial.strip())
            if device:
                loop = asyncio.get_running_loop()
                ui_xml = await loop.run_in_executor(
                    None, lambda: device.hierarchy_xml(force_refresh=True)
                )
                if not (ui_xml or "").strip():
                    ui_xml = None

    scenario = build_scenario_from_instructions(
        instructions, ui_xml=ui_xml, device_context=body.device_context
    )
    from common.scenario_schema import validate_scenario
    errs = validate_scenario(scenario)
    if errs:
        raise HTTPException(status_code=400, detail={"message": "Validation failed", "errors": errs})

    from common.graph_compiler import steps_to_graph
    compiled_steps = scenario.get("steps", [])
    nodes, edges = steps_to_graph(compiled_steps)
    await repo.update_scenario(
        db, scenario_id,
        steps=compiled_steps,
        instructions=instructions,
        nodes=nodes,
        edges=edges,
    )
    await db.commit()
    s = await repo.get_scenario(db, scenario_id)
    return _scenario_to_out(s)


# ── Campaign Runs (backed by executions table) ───────────────────────────────

def _execution_to_run_dict(ex) -> dict:
    meta = ex.meta or {}
    return {
        "id": ex.id,
        "campaign_id": ex.campaign_id,
        "status": ex.status,
        "workflow_ids": meta.get("workflow_ids", []),
        "scenarios_count": meta.get("scenarios_count", 0),
        "started_at": ex.started_at.isoformat() if ex.started_at else None,
        "finished_at": ex.finished_at.isoformat() if ex.finished_at else None,
    }


@router.get("/{campaign_id}/runs")
async def list_runs(
    campaign_id: str,
    db: DB,
    user: CurrentUser,
    limit: int = 20,
    offset: int = 0,
):
    await _get_campaign_or_404(campaign_id, user.id, db)
    from db.crud.execution import list_executions
    runs, total = await list_executions(
        db, campaign_id=campaign_id, run_type="campaign_run", limit=limit, offset=offset,
    )
    return {"total": total, "items": [_execution_to_run_dict(r) for r in runs]}


@router.get("/{campaign_id}/runs/{run_id}")
async def get_run(campaign_id: str, run_id: str, db: DB, user: CurrentUser):
    await _get_campaign_or_404(campaign_id, user.id, db)
    from db.crud.execution import get_execution
    run = await get_execution(db, run_id)
    if not run or run.campaign_id != campaign_id or run.user_id != user.id:
        raise HTTPException(status_code=404, detail="Run not found")
    return _execution_to_run_dict(run)


@router.get("/{campaign_id}/runs/{run_id}/content/stats")
async def run_content_stats(campaign_id: str, run_id: str, db: DB, user: CurrentUser):
    await _get_campaign_or_404(campaign_id, user.id, db)
    from db.crud.execution import get_execution
    run = await get_execution(db, run_id)
    if not run or run.campaign_id != campaign_id or run.user_id != user.id:
        raise HTTPException(status_code=404, detail="Run not found")
    from db.crud.execution import execution_summary
    return await execution_summary(db, run_id)
