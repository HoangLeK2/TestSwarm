
from __future__ import annotations

import asyncio
import re as _re
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

_SERIAL_RE = _re.compile(r"^[\w.:_\-]{1,128}$")

from api.deps import CurrentUser, DB, require_permission
from api.org_scope import (
    campaign_visible_to_user,
    data_owner_user_id,
    device_visible_to_user,
    resource_visible_to_user,
)
from db.models import User
from api.schemas.campaign import (
    CampaignCreate, CampaignDeviceOut, CampaignOut,
    ScenarioCreate, ScenarioUpdate, ScenarioOut,
    ScenarioDeviceVariablesBody, ScenarioDeviceVariablesOut,
)
from api.schemas.scenario_validation import ScenarioValidationOut, ValidationIssueOut
from api.schemas.execution import CampaignControlOut, ExecutionCancelBody
from db import crud as repo
from db.crud.default_scenario import (
    ensure_default_scenario,
    get_default_scenario,
    merge_scenario_variables_for_row,
    scenario_row_to_embedded_dict,
)
from db.crud.device import get_device_by_serial
from db.crud.scenario_device_variable import (
    delete_scenario_device_variable_key,
    get_scenario_device_variables,
    merge_scenario_device_variables,
    replace_scenario_device_variables,
)
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


class ReorderScenariosBody(BaseModel):
    ordered_ids: list[str]
    scenario_id: str | None = None  # if provided, save to specific scenario


# ── Helper ──────────────────────────────────────────────────────────────────

async def _lookup_account_group_name(db, group_id: str | None) -> str | None:
    """Resolve a group's display name for ScenarioOut enrichment.

    Returns None on miss so the response is still well-formed when the group
    has been deleted (its FK on the scenario is set to NULL by the DB).
    """
    if not group_id:
        return None
    from db.crud.account_group import get_group as _get_group
    grp = await _get_group(db, group_id)
    return grp.name if grp is not None else None


def _scenario_to_out(s, *, account_group_name: str | None = None) -> ScenarioOut:
    summary = getattr(s, "last_validation_summary", None) or None
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
        account_group_id=getattr(s, "account_group_id", None),
        account_group_name=account_group_name,
        last_validation_summary=summary,
        last_validated_at=getattr(s, "last_validated_at", None),
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


def _validation_to_out(result, *, last_validated_at=None) -> ScenarioValidationOut:
    def _issues(items):
        return [
            ValidationIssueOut(
                level=i.level,
                code=i.code,
                message=i.message,
                location=i.location,
                hint=i.hint,
            )
            for i in items
        ]

    return ScenarioValidationOut(
        status=result.status,
        errors=_issues(result.errors),
        warnings=_issues(result.warnings),
        infos=_issues(result.infos),
        last_validated_at=last_validated_at,
    )


def _merge_scenario_body_for_validation(scenario, updates: dict) -> dict:
    from services.scenario_validation.validator import build_scenario_body_from_row

    body = build_scenario_body_from_row(scenario)
    for key in ("instructions", "steps", "nodes", "edges", "variables"):
        if key in updates:
            body[key] = updates[key]
    return body


async def _validate_before_save(
    db,
    campaign,
    scenario,
    updates: dict,
    *,
    force: bool = False,
) -> None:
    """Run validation pipeline; block save on errors unless force=true."""
    if not any(k in updates for k in ("steps", "nodes", "edges", "variables")):
        return
    from services.scenario_validation.validator import (
        persist_validation_summary,
        validate_scenario_body,
    )

    body = _merge_scenario_body_for_validation(scenario, updates)
    result = await validate_scenario_body(
        db,
        scenario,
        body=body,
        campaign_variables=campaign.variables or {},
    )
    await persist_validation_summary(db, scenario.id, result)
    if result.has_errors and not force:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Scenario validation failed",
                **_validation_to_out(result).model_dump(mode="json"),
            },
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


async def _get_campaign_or_404(campaign_id: str, user: User, db):
    campaign = await repo.get_campaign(db, campaign_id)
    if not campaign or not await campaign_visible_to_user(db, user, campaign):
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


# ── Campaign CRUD ────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=list[CampaignOut],
    dependencies=[Depends(require_permission("campaigns", "read"))],
)
async def list_campaigns(db: DB, user: CurrentUser):
    campaigns = await repo.list_campaigns(
        db,
        org_id=getattr(user, "org_id", None),
        user_id=data_owner_user_id(user),
    )
    result = []
    for c in campaigns:
        scenarios = await repo.list_scenarios(db, c.id)
        result.append(_to_out(c, scenarios))
    return result


@router.post(
    "",
    response_model=CampaignOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("campaigns", "create"))],
)
async def create_campaign(body: CampaignCreate, db: DB, user: CurrentUser):
    existing = await repo.get_campaign_by_name(
        db, org_id=getattr(user, "org_id", None), name=body.name
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Campaign name already exists",
        )

    valid_device_ids: list[str] = []
    for device_id in body.device_ids:
        device = await repo.get_device(db, device_id)
        if not device or device.org_id != getattr(user, "org_id", None):
            raise HTTPException(status_code=404, detail=f"Device not found: {device_id}")
        valid_device_ids.append(device_id)

    campaign = await repo.create_campaign(
        db,
        body.name,
        user.id,
        getattr(user, "org_id", None),
        body.description,
        body.variables,
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


@router.get(
    "/{campaign_id}",
    response_model=CampaignOut,
    dependencies=[Depends(require_permission("campaigns", "read"))],
)
async def get_campaign(campaign_id: str, db: DB, user: CurrentUser):
    campaign = await _get_campaign_or_404(campaign_id, user, db)
    scenarios = await repo.list_scenarios(db, campaign_id)
    return _to_out(campaign, scenarios)


@router.delete(
    "/{campaign_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("campaigns", "delete"))],
)
async def delete_campaign(campaign_id: str, db: DB, user: CurrentUser):
    campaign = await _get_campaign_or_404(campaign_id, user, db)
    from sqlalchemy import delete
    from db.models import Campaign as CampaignModel
    await db.execute(delete(CampaignModel).where(CampaignModel.id == campaign_id))
    await db.commit()


@router.patch(
    "/{campaign_id}/status",
    dependencies=[Depends(require_permission("campaigns", "execute"))],
)
async def update_status(campaign_id: str, body: StatusUpdate, db: DB, user: CurrentUser, request: Request):
    await _get_campaign_or_404(campaign_id, user, db)
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


async def _campaign_temporal_client(request: Request):
    config = getattr(request.app.state, "config", None)
    if config is None or not getattr(config, "temporal", None) or not config.temporal.enabled:
        return None
    from temporal.worker import get_temporal_client

    return await get_temporal_client(config.temporal)


@router.post(
    "/{campaign_id}/pause",
    response_model=CampaignControlOut,
    dependencies=[Depends(require_permission("campaigns", "execute"))],
)
async def pause_campaign(
    campaign_id: str, request: Request, db: DB, user: CurrentUser,
):
    await _get_campaign_or_404(campaign_id, user, db)
    from services.execution_control import ExecutionControlError, pause_campaign_executions

    try:
        client = await _campaign_temporal_client(request)
        data = await pause_campaign_executions(
            db, campaign_id, user_id=user.id, temporal_client=client,
        )
        await db.commit()
        return CampaignControlOut(**data)
    except ExecutionControlError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@router.post(
    "/{campaign_id}/resume",
    response_model=CampaignControlOut,
    dependencies=[Depends(require_permission("campaigns", "execute"))],
)
async def resume_campaign(
    campaign_id: str, request: Request, db: DB, user: CurrentUser,
):
    await _get_campaign_or_404(campaign_id, user, db)
    from services.execution_control import ExecutionControlError, resume_campaign_executions

    try:
        client = await _campaign_temporal_client(request)
        data = await resume_campaign_executions(
            db, campaign_id, user_id=user.id, temporal_client=client,
        )
        await db.commit()
        return CampaignControlOut(**data)
    except ExecutionControlError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@router.post(
    "/{campaign_id}/cancel",
    response_model=CampaignControlOut,
    dependencies=[Depends(require_permission("campaigns", "execute"))],
)
async def cancel_campaign(
    campaign_id: str,
    request: Request,
    db: DB,
    user: CurrentUser,
    body: ExecutionCancelBody | None = None,
):
    await _get_campaign_or_404(campaign_id, user, db)
    from services.execution_control import ExecutionControlError, cancel_campaign_executions

    reason = (body.reason if body else "") or None
    session_store = getattr(request.app.state, "session_store", None)
    try:
        client = await _campaign_temporal_client(request)
        data = await cancel_campaign_executions(
            db,
            campaign_id,
            user_id=user.id,
            reason=reason,
            temporal_client=client,
            session_store=session_store,
        )
        await db.commit()
        return CampaignControlOut(**data)
    except ExecutionControlError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@router.post(
    "/{campaign_id}/step-action",
    dependencies=[Depends(require_permission("campaigns", "execute"))],
)
async def step_action(campaign_id: str, body: StepActionBody, db: DB, user: CurrentUser, request: Request):
    """Send retry_step or skip_step signal to workflows paused on error.

    When a step fails and its on_error policy is "pause", the workflow blocks
    waiting for this signal.
      - action="retry": re-execute the failed step from the beginning
      - action="skip":  skip the failed step and continue with the next one

    device_serial: if provided, only signal the workflow for that device.
                   if None, signal all paused-on-error workflows for this campaign.
    """
    await _get_campaign_or_404(campaign_id, user, db)
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


@router.get(
    "/{campaign_id}/devices",
    response_model=list[CampaignDeviceOut],
    dependencies=[Depends(require_permission("campaigns", "read"))],
)
async def campaign_devices(campaign_id: str, db: DB, user: CurrentUser):
    await _get_campaign_or_404(campaign_id, user, db)
    devices = await repo.list_campaign_devices(db, campaign_id)
    return [CampaignDeviceOut(id=d.id, serial=d.serial, name=d.name) for d in devices]


@router.post(
    "/{campaign_id}/devices",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("campaigns", "update"))],
)
async def add_device(campaign_id: str, body: AddDeviceBody, db: DB, user: CurrentUser):
    await _get_campaign_or_404(campaign_id, user, db)
    device = await repo.get_device(db, body.device_id)
    if not await device_visible_to_user(db, user, device):
        raise HTTPException(status_code=404, detail="Device not found")
    await repo.add_device_to_campaign(db, campaign_id, body.device_id)
    await db.commit()
    return {"ok": True}


@router.delete(
    "/{campaign_id}/devices/{device_id}",
    dependencies=[Depends(require_permission("campaigns", "update"))],
)
async def remove_device(campaign_id: str, device_id: str, db: DB, user: CurrentUser):
    await _get_campaign_or_404(campaign_id, user, db)
    device = await repo.get_device(db, device_id)
    if not await device_visible_to_user(db, user, device):
        raise HTTPException(status_code=404, detail="Device not found")
    await repo.remove_device_from_campaign(db, campaign_id, device_id)
    await db.commit()
    return {"ok": True}


# ── Content stats for this campaign ──────────────────────────────────────────

@router.get(
    "/{campaign_id}/content/stats",
    dependencies=[Depends(require_permission("campaigns", "read"))],
)
async def campaign_content_stats(campaign_id: str, db: DB, user: CurrentUser):
    """Return number of content items scraped for this campaign."""
    await _get_campaign_or_404(campaign_id, user, db)
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

@router.patch(
    "/{campaign_id}/scenario",
    response_model=CampaignOut,
    dependencies=[Depends(require_permission("campaigns", "update"))],
)
async def update_scenario(
    campaign_id: str,
    body: ScenarioUpdateBody,
    db: DB,
    user: CurrentUser,
    force: bool = Query(False, description="Allow save despite validation errors"),
):
    from common.graph_compiler import compile_graph_to_steps, ensure_step_ids, steps_to_graph

    campaign = await _get_campaign_or_404(campaign_id, user, db)
    patch = body.scenario if isinstance(body.scenario, dict) else {}
    s = await ensure_default_scenario(db, campaign.id, name=campaign.name)
    instructions = str(patch.get("instructions", s.instructions or ""))
    nodes_in = patch.get("nodes")
    edges_in = patch.get("edges")
    steps_in = patch.get("steps")
    patch_vars = patch.get("variables") if isinstance(patch.get("variables"), dict) else {}
    device_context = patch.get("device_context")

    pending_updates: dict = {"instructions": instructions}
    if isinstance(nodes_in, list) and len(nodes_in) > 0:
        compiled = compile_graph_to_steps(nodes_in, edges_in or [])
        saved_steps = ensure_step_ids(save_step_images(compiled, s.id))
        n, e = steps_to_graph(saved_steps)
        vars_merged = merge_scenario_variables_for_row(s.variables, patch_vars, device_context)
        pending_updates.update(steps=saved_steps, nodes=n, edges=e, variables=vars_merged)
    elif isinstance(steps_in, list):
        saved_steps = ensure_step_ids(save_step_images(steps_in, s.id))
        n, e = steps_to_graph(saved_steps) if saved_steps else ([], [])
        vars_merged = merge_scenario_variables_for_row(s.variables, patch_vars, device_context)
        pending_updates.update(steps=saved_steps, nodes=n, edges=e, variables=vars_merged)
    else:
        vars_merged = merge_scenario_variables_for_row(s.variables, patch_vars, device_context)
        pending_updates["variables"] = vars_merged

    await _validate_before_save(db, campaign, s, pending_updates, force=force)
    await repo.update_scenario(db, s.id, **pending_updates)
    await db.commit()
    scenarios = await repo.list_scenarios(db, campaign_id)
    return _to_out(campaign, scenarios)


@router.post(
    "/{campaign_id}/compile-scenario",
    response_model=CampaignOut,
    dependencies=[Depends(require_permission("campaigns", "execute"))],
)
async def compile_scenario(
    request: Request,
    campaign_id: str,
    body: CompileScenarioBody,
    db: DB,
    user: CurrentUser,
):
    from runtime.ai.ai_client import build_scenario_from_instructions

    campaign = await _get_campaign_or_404(campaign_id, user, db)

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
        if not await device_visible_to_user(db, user, device_row):
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

@router.get(
    "/{campaign_id}/scenarios",
    response_model=list[ScenarioOut],
    dependencies=[Depends(require_permission("campaigns", "read"))],
)
async def list_scenarios(campaign_id: str, db: DB, user: CurrentUser):
    await _get_campaign_or_404(campaign_id, user, db)
    scenarios = await repo.list_scenarios(db, campaign_id)
    return [_scenario_to_out(s) for s in scenarios]


@router.post(
    "/{campaign_id}/scenarios",
    response_model=ScenarioOut,
    status_code=201,
    dependencies=[Depends(require_permission("campaigns", "create"))],
)
async def create_scenario(campaign_id: str, body: ScenarioCreate, db: DB, user: CurrentUser):
    await _get_campaign_or_404(campaign_id, user, db)
    # auto-order: append after last
    existing = await repo.list_scenarios(db, campaign_id)
    order = body.order if body.order else len(existing)
    # Validate account_group_id (must belong to the current user).
    if body.account_group_id:
        from db.crud.account_group import get_group as _get_group
        grp = await _get_group(db, body.account_group_id, user_id=data_owner_user_id(user))
        if grp is None:
            raise HTTPException(status_code=400, detail="Account group not found or not owned by user")
    s = await repo.create_scenario(
        db, campaign_id,
        name=body.name,
        instructions=body.instructions,
        steps=[],
        variables=body.variables,
        order=order,
        account_group_id=body.account_group_id or None,
    )
    await db.flush()
    from common.graph_compiler import ensure_step_ids, steps_to_graph
    saved_steps = save_step_images(body.steps or [], s.id)
    saved_steps = ensure_step_ids(saved_steps)
    nodes, edges = steps_to_graph(saved_steps)
    await repo.update_scenario(db, s.id, steps=saved_steps, nodes=nodes, edges=edges)
    await db.commit()
    s = await repo.get_scenario(db, s.id)
    return _scenario_to_out(
        s,
        account_group_name=await _lookup_account_group_name(db, s.account_group_id),
    )


@router.post(
    "/{campaign_id}/scenarios/reorder",
    response_model=list[ScenarioOut],
    dependencies=[Depends(require_permission("campaigns", "update"))],
)
async def reorder_scenarios_route(
    campaign_id: str, body: ReorderScenariosBody, db: DB, user: CurrentUser
):
    await _get_campaign_or_404(campaign_id, user, db)
    try:
        scenarios = await repo.reorder_scenarios(db, campaign_id, body.ordered_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await db.commit()
    return [
        _scenario_to_out(
            s,
            account_group_name=await _lookup_account_group_name(db, s.account_group_id),
        )
        for s in scenarios
    ]


@router.get(
    "/{campaign_id}/scenarios/{scenario_id}",
    response_model=ScenarioOut,
    dependencies=[Depends(require_permission("campaigns", "read"))],
)
async def get_scenario(campaign_id: str, scenario_id: str, db: DB, user: CurrentUser):
    await _get_campaign_or_404(campaign_id, user, db)
    s = await repo.get_scenario(db, scenario_id)
    if not s or s.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return _scenario_to_out(
        s,
        account_group_name=await _lookup_account_group_name(db, s.account_group_id),
    )


@router.get(
    "/{campaign_id}/scenarios/{scenario_id}/devices/{device_id}/variables",
    response_model=ScenarioDeviceVariablesOut,
    dependencies=[Depends(require_permission("campaigns", "read"))],
)
async def get_scenario_device_variables_endpoint(
    campaign_id: str,
    scenario_id: str,
    device_id: str,
    db: DB,
    user: CurrentUser,
):
    await _get_campaign_or_404(campaign_id, user, db)
    scenario = await repo.get_scenario(db, scenario_id)
    if not scenario or scenario.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Scenario not found")
    device = await repo.get_device(db, device_id)
    if not await device_visible_to_user(db, user, device):
        raise HTTPException(status_code=404, detail="Device not found")
    vars_map = await get_scenario_device_variables(db, scenario_id, device_id)
    return ScenarioDeviceVariablesOut(
        scenario_id=scenario_id,
        device_id=device_id,
        vars=vars_map,
    )


@router.put(
    "/{campaign_id}/scenarios/{scenario_id}/devices/{device_id}/variables",
    response_model=ScenarioDeviceVariablesOut,
    dependencies=[Depends(require_permission("campaigns", "update"))],
)
async def replace_scenario_device_variables_endpoint(
    campaign_id: str,
    scenario_id: str,
    device_id: str,
    body: ScenarioDeviceVariablesBody,
    db: DB,
    user: CurrentUser,
):
    await _get_campaign_or_404(campaign_id, user, db)
    scenario = await repo.get_scenario(db, scenario_id)
    if not scenario or scenario.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Scenario not found")
    device = await repo.get_device(db, device_id)
    if not await device_visible_to_user(db, user, device):
        raise HTTPException(status_code=404, detail="Device not found")
    vars_map = await replace_scenario_device_variables(db, scenario_id, device_id, body.vars)
    await db.commit()
    return ScenarioDeviceVariablesOut(
        scenario_id=scenario_id,
        device_id=device_id,
        vars=vars_map,
    )


@router.patch(
    "/{campaign_id}/scenarios/{scenario_id}/devices/{device_id}/variables",
    response_model=ScenarioDeviceVariablesOut,
    dependencies=[Depends(require_permission("campaigns", "update"))],
)
async def merge_scenario_device_variables_endpoint(
    campaign_id: str,
    scenario_id: str,
    device_id: str,
    body: ScenarioDeviceVariablesBody,
    db: DB,
    user: CurrentUser,
):
    await _get_campaign_or_404(campaign_id, user, db)
    scenario = await repo.get_scenario(db, scenario_id)
    if not scenario or scenario.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Scenario not found")
    device = await repo.get_device(db, device_id)
    if not await device_visible_to_user(db, user, device):
        raise HTTPException(status_code=404, detail="Device not found")
    vars_map = await merge_scenario_device_variables(db, scenario_id, device_id, body.vars)
    await db.commit()
    return ScenarioDeviceVariablesOut(
        scenario_id=scenario_id,
        device_id=device_id,
        vars=vars_map,
    )


@router.delete(
    "/{campaign_id}/scenarios/{scenario_id}/devices/{device_id}/variables/{key}",
    response_model=dict,
    dependencies=[Depends(require_permission("campaigns", "update"))],
)
async def delete_scenario_device_variable_key_endpoint(
    campaign_id: str,
    scenario_id: str,
    device_id: str,
    key: str,
    db: DB,
    user: CurrentUser,
):
    await _get_campaign_or_404(campaign_id, user, db)
    scenario = await repo.get_scenario(db, scenario_id)
    if not scenario or scenario.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Scenario not found")
    device = await repo.get_device(db, device_id)
    if not await device_visible_to_user(db, user, device):
        raise HTTPException(status_code=404, detail="Device not found")
    removed = await delete_scenario_device_variable_key(db, scenario_id, device_id, key)
    await db.commit()
    return {
        "ok": True,
        "removed": bool(removed),
        "scenario_id": scenario_id,
        "device_id": device_id,
        "key": key,
    }


@router.patch(
    "/{campaign_id}/scenarios/{scenario_id}",
    response_model=ScenarioOut,
    dependencies=[Depends(require_permission("campaigns", "update"))],
)
async def update_scenario_route(
    campaign_id: str,
    scenario_id: str,
    body: ScenarioUpdate,
    db: DB,
    user: CurrentUser,
    force: bool = Query(False, description="Allow save despite validation errors"),
):
    campaign = await _get_campaign_or_404(campaign_id, user, db)
    s = await repo.get_scenario(db, scenario_id)
    if not s or s.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Scenario not found")
    updates = {k: v for k, v in body.model_dump(exclude_unset=True).items()}

    # account_group_id: empty string clears the binding; a non-empty value must
    # reference a group owned by the caller. None was already filtered out by
    # exclude_unset above.
    if "account_group_id" in updates:
        agid = updates["account_group_id"]
        if not agid:
            updates["account_group_id"] = None
        else:
            from db.crud.account_group import get_group as _get_group
            grp = await _get_group(db, agid, user_id=data_owner_user_id(user))
            if grp is None:
                raise HTTPException(
                    status_code=400,
                    detail="Account group not found or not owned by user",
                )

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

    await _validate_before_save(db, campaign, s, updates, force=force)
    if updates:
        await repo.update_scenario(db, scenario_id, **updates)
    await db.commit()
    s = await repo.get_scenario(db, scenario_id)
    return _scenario_to_out(
        s,
        account_group_name=await _lookup_account_group_name(db, s.account_group_id),
    )


@router.post(
    "/{campaign_id}/scenarios/{scenario_id}/validate",
    response_model=ScenarioValidationOut,
    dependencies=[Depends(require_permission("campaigns", "read"))],
)
async def validate_scenario_route(
    campaign_id: str,
    scenario_id: str,
    db: DB,
    user: CurrentUser,
):
    """Run full scenario validation (shape + semantic + lint) and persist summary."""
    from services.scenario_validation.validator import (
        persist_validation_summary,
        validate_scenario_body,
    )

    campaign = await _get_campaign_or_404(campaign_id, user, db)
    s = await repo.get_scenario(db, scenario_id)
    if not s or s.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Scenario not found")

    result = await validate_scenario_body(
        db,
        s,
        campaign_variables=campaign.variables or {},
    )
    await persist_validation_summary(db, scenario_id, result)
    await db.commit()
    s = await repo.get_scenario(db, scenario_id)
    return _validation_to_out(result, last_validated_at=getattr(s, "last_validated_at", None))


@router.delete(
    "/{campaign_id}/scenarios/{scenario_id}",
    status_code=204,
    dependencies=[Depends(require_permission("campaigns", "delete"))],
)
async def delete_scenario_route(
    campaign_id: str, scenario_id: str, db: DB, user: CurrentUser
):
    await _get_campaign_or_404(campaign_id, user, db)
    s = await repo.get_scenario(db, scenario_id)
    if not s or s.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Scenario not found")
    await repo.delete_scenario(db, scenario_id)
    await db.commit()
    delete_scenario_images(scenario_id)


# ── Compile scenario for a specific scenario row ──────────────────────────────

@router.post(
    "/{campaign_id}/scenarios/{scenario_id}/compile",
    response_model=ScenarioOut,
    dependencies=[Depends(require_permission("campaigns", "execute"))],
)
async def compile_scenario_row(
    request: Request,
    campaign_id: str,
    scenario_id: str,
    body: CompileScenarioBody,
    db: DB,
    user: CurrentUser,
):
    from runtime.ai.ai_client import build_scenario_from_instructions

    await _get_campaign_or_404(campaign_id, user, db)
    s = await repo.get_scenario(db, scenario_id)
    if not s or s.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Scenario not found")

    instructions = body.instructions or s.instructions or ""
    if not instructions:
        raise HTTPException(status_code=400, detail="No instructions provided")

    ui_xml = (body.ui_xml or "").strip() or None
    if not ui_xml and body.device_serial:
        device_row = await get_device_by_serial(db, body.device_serial.strip())
        if not await device_visible_to_user(db, user, device_row):
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


@router.get(
    "/{campaign_id}/runs",
    dependencies=[Depends(require_permission("campaigns", "read"))],
)
async def list_runs(
    campaign_id: str,
    db: DB,
    user: CurrentUser,
    limit: int = 20,
    offset: int = 0,
):
    await _get_campaign_or_404(campaign_id, user, db)
    from db.crud.execution import list_executions
    runs, total = await list_executions(
        db, campaign_id=campaign_id, run_type="campaign_run", limit=limit, offset=offset,
    )
    return {"total": total, "items": [_execution_to_run_dict(r) for r in runs]}


@router.get(
    "/{campaign_id}/runs/{run_id}",
    dependencies=[Depends(require_permission("campaigns", "read"))],
)
async def get_run(campaign_id: str, run_id: str, db: DB, user: CurrentUser):
    await _get_campaign_or_404(campaign_id, user, db)
    from api.execution_access import get_execution_for_user

    try:
        run = await get_execution_for_user(db, run_id, user)
    except HTTPException:
        raise HTTPException(status_code=404, detail="Run not found") from None
    if run.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Run not found")
    return _execution_to_run_dict(run)


@router.get(
    "/{campaign_id}/runs/{run_id}/content/stats",
    dependencies=[Depends(require_permission("campaigns", "read"))],
)
async def run_content_stats(campaign_id: str, run_id: str, db: DB, user: CurrentUser):
    await _get_campaign_or_404(campaign_id, user, db)
    from api.execution_access import get_execution_for_user

    try:
        run = await get_execution_for_user(db, run_id, user)
    except HTTPException:
        raise HTTPException(status_code=404, detail="Run not found") from None
    if run.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Run not found")
    from db.crud.execution import execution_summary
    return await execution_summary(db, run_id)
