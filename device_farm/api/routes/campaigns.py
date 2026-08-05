from __future__ import annotations

import asyncio
import re as _re
import time
from datetime import datetime
from typing import Union
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select

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
from api.schemas.campaign_entity import (
    CampaignEntityOut,
    CampaignEntityUpdate,
    CampaignAccountBindIn,
    CampaignDispatchIn,
    CampaignDispatchOut,
    CampaignDispatchExecutionOut,
    CampaignDispatchPreviewAssignmentOut,
    CampaignDispatchPreviewOut,
    CampaignScenarioRefOut,
    CampaignForceTransitionIn,
    CampaignForceTransitionOut,
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
    delete_campaign_org_scenario_device_variable_key,
    delete_scenario_device_variable_key,
    get_campaign_org_scenario_device_variables,
    get_scenario_device_variables,
    merge_campaign_org_scenario_device_variables,
    merge_scenario_device_variables,
    replace_campaign_org_scenario_device_variables,
    replace_scenario_device_variables,
)
from db.models.org_scenario import CampaignOrgScenarioRef
from services.image_store import save_step_images, delete_scenario_images
from services.campaign.scenario_ref_resolver import CampaignScenarioRefError
from services.campaign.service import (
    CampaignError,
    CampaignNotFoundError,
    CampaignView,
    archive_campaign as archive_campaign_entity,
    create_campaign as create_campaign_entity,
    get_campaign_for_org,
    list_campaigns_for_org,
    map_scenario_ref_error,
    update_campaign as update_campaign_entity,
)

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


def _map_campaign_error(exc: CampaignError) -> HTTPException:
    from services.campaign.lifecycle import CampaignInvalidTransitionError, CampaignLockedError
    from services.campaign.service import (
        CampaignDuplicateNameError,
        CampaignNotFoundError,
        CampaignRunningError,
        CampaignValidationError,
    )

    if isinstance(exc, CampaignNotFoundError):
        return HTTPException(status_code=404, detail={"code": exc.code})
    if isinstance(exc, CampaignDuplicateNameError):
        return HTTPException(status_code=409, detail={"code": exc.code})
    if isinstance(exc, (CampaignRunningError, CampaignInvalidTransitionError)):
        return HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)})
    if isinstance(exc, CampaignLockedError):
        return HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)})
    if isinstance(exc, CampaignValidationError):
        return HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)})
    return HTTPException(status_code=400, detail={"code": exc.code, "message": str(exc)})


def _entity_out(view: CampaignView) -> CampaignEntityOut:
    return CampaignEntityOut(
        id=view.id,
        organization_id=view.organization_id,
        name=view.name,
        description=view.description,
        status=view.status,
        vars=view.vars,
        per_device_overrides=view.per_device_overrides,
        recovery_policy=view.recovery_policy,
        account_group_id=view.account_group_id,
        scenario_account_id=view.scenario_account_id,
        per_device_accounts=view.per_device_accounts,
        tags=view.tags,
        scenario_refs=[
            CampaignScenarioRefOut(
                scenario_id=ref.scenario_id,
                scenario_version=ref.scenario_version,
                repeat_count=ref.repeat_count,
            )
            for ref in view.scenario_refs
        ],
        created_by=view.created_by,
        created_at=datetime.fromisoformat(view.created_at),
        updated_at=datetime.fromisoformat(view.updated_at),
        started_at=datetime.fromisoformat(view.started_at) if view.started_at else None,
        completed_at=datetime.fromisoformat(view.completed_at) if view.completed_at else None,
        cancelled_at=datetime.fromisoformat(view.cancelled_at) if view.cancelled_at else None,
    )


async def _get_campaign_or_404(campaign_id: str, user: User, db):
    from contextlib import nullcontext

    from db.crud import campaign_entity as campaign_entity_repo
    from tenancy.context import get_current_org_id, tenant_context

    org_scope = get_current_org_id() or getattr(user, "org_id", None)
    if not org_scope:
        camp_org = await campaign_entity_repo.lookup_campaign_org_id(db, campaign_id)
        org_scope = camp_org
    tenant_ctx = tenant_context(org_scope) if org_scope else nullcontext()
    with tenant_ctx:
        campaign = await repo.get_campaign(db, campaign_id)
    if not campaign or not await campaign_visible_to_user(db, user, campaign):
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


async def _get_org_scenario_ref_row(
    db,
    campaign_id: str,
    scenario_id: str,
) -> CampaignOrgScenarioRef | None:
    result = await db.execute(
        select(CampaignOrgScenarioRef).where(
            CampaignOrgScenarioRef.campaign_id == campaign_id,
            CampaignOrgScenarioRef.org_scenario_id == scenario_id,
        )
    )
    return result.scalar_one_or_none()


async def _campaign_org_id(db, campaign) -> str | None:
    org_id = getattr(campaign, "org_id", None)
    if org_id:
        return str(org_id)
    from db.crud import campaign_entity as campaign_entity_repo

    return await campaign_entity_repo.lookup_campaign_org_id(db, campaign.id)


async def _org_scenario_to_campaign_scenario_out(
    db,
    *,
    campaign_id: str,
    ref: CampaignOrgScenarioRef,
    org_id: str | None,
) -> ScenarioOut | None:
    from db.crud import org_scenario as org_scenario_repo

    row = await org_scenario_repo.get_org_scenario(
        db, ref.org_scenario_id, org_id=org_id
    )
    if row is None:
        return None
    body = row.body_json if isinstance(row.body_json, dict) else {}
    account_group_id = body.get("account_group_id")
    account_group_name = None
    if account_group_id:
        account_group_name = await _lookup_account_group_name(db, account_group_id)
    return ScenarioOut(
        id=ref.org_scenario_id,
        campaign_id=campaign_id,
        name=row.name,
        instructions=str(body.get("instructions") or ""),
        steps=body.get("steps") or [],
        variables=body.get("variables") or {},
        order=int(ref.order_index or 0),
        nodes=body.get("nodes") or [],
        edges=body.get("edges") or [],
        account_group_id=account_group_id,
        account_group_name=account_group_name,
        last_validation_summary=row.last_validation_summary,
        last_validated_at=row.last_validated_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _list_org_scenario_outs_for_campaign(db, campaign) -> list[ScenarioOut]:
    from db.crud import campaign_entity as campaign_entity_repo
    from db.crud.campaign_entity import loaded_org_scenario_refs

    entity = campaign
    if "org_scenario_refs" not in campaign.__dict__:
        entity = await campaign_entity_repo.get_campaign_entity(
            db, campaign.id, include_refs=True
        )
    if entity is None:
        return []
    refs = sorted(
        loaded_org_scenario_refs(entity),
        key=lambda r: int(r.order_index or 0),
    )
    if not refs:
        return []
    org_id = await _campaign_org_id(db, entity)
    outs: list[ScenarioOut] = []
    for ref in refs:
        out = await _org_scenario_to_campaign_scenario_out(
            db,
            campaign_id=entity.id,
            ref=ref,
            org_id=org_id,
        )
        if out is not None:
            outs.append(out)
    return outs


async def _org_scenario_id_to_campaign_scenario_out(
    db,
    *,
    campaign_id: str,
    org_scenario_id: str,
    org_id: str | None,
    order: int = 0,
) -> ScenarioOut | None:
    from db.crud import org_scenario as org_scenario_repo

    row = await org_scenario_repo.get_org_scenario(db, org_scenario_id, org_id=org_id)
    if row is None:
        return None
    body = row.body_json if isinstance(row.body_json, dict) else {}
    account_group_id = body.get("account_group_id")
    account_group_name = None
    if account_group_id:
        account_group_name = await _lookup_account_group_name(db, account_group_id)
    return ScenarioOut(
        id=org_scenario_id,
        campaign_id=campaign_id,
        name=row.name,
        instructions=str(body.get("instructions") or ""),
        steps=body.get("steps") or [],
        variables=body.get("variables") or {},
        order=order,
        nodes=body.get("nodes") or [],
        edges=body.get("edges") or [],
        account_group_id=account_group_id,
        account_group_name=account_group_name,
        last_validation_summary=row.last_validation_summary,
        last_validated_at=row.last_validated_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _campaign_recovery_scenario_ids(campaign) -> set[str]:
    from services.execution.recovery_policy import recovery_scenario_ids_from_policy

    return recovery_scenario_ids_from_policy(
        getattr(campaign, "recovery_policy", None) or {}
    )


async def _scenario_variable_scope_or_404(db, campaign_id: str, scenario_id: str) -> str:
    scenario = await repo.get_scenario(db, scenario_id)
    if scenario and scenario.campaign_id == campaign_id:
        return "legacy"

    if await _get_org_scenario_ref_row(db, campaign_id, scenario_id):
        return "org"

    from db.crud import campaign_entity as campaign_entity_repo

    campaign = await campaign_entity_repo.get_campaign_entity(db, campaign_id)
    if campaign and scenario_id in _campaign_recovery_scenario_ids(campaign):
        return "org"

    raise HTTPException(status_code=404, detail="Scenario not found")


# ── Campaign CRUD ────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=list[Union[CampaignEntityOut, CampaignOut]],
    dependencies=[Depends(require_permission("campaigns", "read"))],
)
async def list_campaigns(
    db: DB,
    user: CurrentUser,
    include_archived: bool = Query(default=False),
):
    org_id = getattr(user, "org_id", None)
    if org_id:
        views = await list_campaigns_for_org(
            db, org_id, include_archived=include_archived
        )
        return [_entity_out(view) for view in views]

    campaigns = await repo.list_campaigns(
        db,
        org_id=None,
        user_id=data_owner_user_id(user),
        include_archived=include_archived,
    )
    result = []
    for c in campaigns:
        scenarios = await repo.list_scenarios(db, c.id)
        result.append(_to_out(c, scenarios))
    return result


def _inline_scenario_steps(scenario: dict | None) -> list | None:
    if not isinstance(scenario, dict):
        return None
    steps = scenario.get("steps")
    return steps if isinstance(steps, list) else None


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=Union[CampaignEntityOut, CampaignOut],
    dependencies=[Depends(require_permission("campaigns", "create"))],
)
async def create_campaign(body: CampaignCreate, db: DB, user: CurrentUser):
    org_id = getattr(user, "org_id", None)
    inline_steps = _inline_scenario_steps(body.scenario)
    if org_id and body.scenario_refs is None and not inline_steps:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "SCENARIO_REQUIRED",
                "message": "At least one org scenario is required",
            },
        )
    if body.scenario_refs is not None:
        if not org_id:
            raise HTTPException(status_code=404, detail={"code": "NO_ORGANIZATION"})
        refs = [ref.model_dump(exclude_none=True) for ref in body.scenario_refs]
        vars_payload = body.vars if body.vars is not None else (body.variables or {})
        try:
            view = await create_campaign_entity(
                db,
                org_id=org_id,
                name=body.name,
                description=body.description,
                vars=vars_payload,
                per_device_overrides=body.per_device_overrides or None,
                recovery_policy=body.recovery_policy or {},
                account_group_id=body.account_group_id,
                scenario_account_id=body.scenario_account_id,
                per_device_accounts=body.per_device_accounts or None,
                tags=body.tags or [],
                scenario_refs=refs,
                created_by=user.id,
            )
        except CampaignScenarioRefError as exc:
            raise _map_campaign_error(map_scenario_ref_error(exc)) from exc
        except CampaignError as exc:
            raise _map_campaign_error(exc) from exc
        await db.commit()
        return _entity_out(view)

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
        recovery_policy=body.recovery_policy or {},
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
    response_model=Union[CampaignOut, CampaignEntityOut],
    dependencies=[Depends(require_permission("campaigns", "read"))],
)
async def get_campaign(campaign_id: str, db: DB, user: CurrentUser):
    org_id = getattr(user, "org_id", None)
    if org_id:
        try:
            view = await get_campaign_for_org(db, campaign_id, org_id)
            return _entity_out(view)
        except CampaignNotFoundError:
            pass
        except CampaignError:
            pass
    campaign = await _get_campaign_or_404(campaign_id, user, db)
    scenarios = await repo.list_scenarios(db, campaign_id)
    return _to_out(campaign, scenarios)


@router.post(
    "/{campaign_id}/dispatch-preview",
    response_model=CampaignDispatchPreviewOut,
    dependencies=[Depends(require_permission("campaigns", "execute"))],
)
async def preview_campaign_dispatch_route(
    campaign_id: str,
    body: CampaignDispatchIn,
    db: DB,
    user: CurrentUser,
):
    """Resolve devices and sources without creating executions or claims."""
    org_id = getattr(user, "org_id", None)
    if not org_id:
        raise HTTPException(status_code=404, detail={"code": "NO_ORGANIZATION"})

    from api.schemas.campaign_entity import _dispatch_http_status
    from services.campaign.dispatcher import (
        CampaignDispatchError,
        preview_campaign_dispatch,
    )
    from services.campaign.entity_allocation import SourcePoolSpec

    source_pool = (
        SourcePoolSpec(
            platform=body.source_pool.platform,
            entity_type=body.source_pool.entity_type,
            search=body.source_pool.search,
            statuses=tuple(status.strip().lower() for status in body.source_pool.statuses),
            output_prefix=body.source_pool.output_prefix,
        )
        if body.source_pool is not None
        else None
    )
    try:
        preview = await preview_campaign_dispatch(
            db,
            campaign_id=campaign_id,
            org_id=org_id,
            device_ids=body.target.device_ids,
            device_group_ids=body.target.device_group_ids,
            external_entity_ids=body.target.external_entity_ids,
            source_pool=source_pool,
            allocation_snapshot=[
                (item.device_id, item.external_entity_id)
                for item in body.allocation_snapshot
            ],
            allocation_policy=body.allocation_policy,
            allow_partial=body.allow_partial,
            require_online=body.require_online,
        )
    except CampaignDispatchError as exc:
        raise HTTPException(
            status_code=_dispatch_http_status(exc.code),
            detail={"code": exc.code, "message": str(exc), **exc.details},
        ) from exc

    return CampaignDispatchPreviewOut(
        campaign_id=preview.campaign_id,
        allocation_policy=preview.allocation_policy,
        device_count=len(preview.device_ids),
        available_source_count=preview.allocation.available_count,
        assignments=[
            CampaignDispatchPreviewAssignmentOut(
                device_id=assignment.device_id,
                device_serial=(
                    preview.devices_by_id[assignment.device_id].serial
                    if assignment.device_id in preview.devices_by_id
                    else assignment.device_id
                ),
                device_name=(
                    preview.devices_by_id[assignment.device_id].name
                    if assignment.device_id in preview.devices_by_id
                    else None
                ),
                external_entity_id=assignment.entity.id,
                display_name=assignment.entity.display_name,
                platform=assignment.entity.platform,
                entity_type=assignment.entity.entity_type,
            )
            for assignment in preview.allocation.assignments
        ],
    )


@router.post(
    "/{campaign_id}/dispatch",
    response_model=CampaignDispatchOut,
    dependencies=[Depends(require_permission("campaigns", "execute"))],
)
async def dispatch_campaign_route(
    campaign_id: str,
    body: CampaignDispatchIn,
    db: DB,
    user: CurrentUser,
    request: Request,
    include_vars: bool = Query(
        False,
        description="Include effective_vars per execution (large fleets: keep false)",
    ),
):
    """Fan-out campaign dispatch to explicit devices or device groups (DF-T-04-008)."""
    dispatch_http_started = time.perf_counter()
    phase_started = dispatch_http_started
    org_id = getattr(user, "org_id", None)
    if not org_id:
        raise HTTPException(status_code=404, detail={"code": "NO_ORGANIZATION"})

    from api.schemas.campaign_entity import _dispatch_http_status
    from services.campaign.dispatcher import CampaignDispatchError, dispatch_campaign
    from services.campaign.entity_allocation import SourcePoolSpec

    source_pool = (
        SourcePoolSpec(
            platform=body.source_pool.platform,
            entity_type=body.source_pool.entity_type,
            search=body.source_pool.search,
            statuses=tuple(status.strip().lower() for status in body.source_pool.statuses),
            output_prefix=body.source_pool.output_prefix,
        )
        if body.source_pool is not None
        else None
    )

    try:
        result = await dispatch_campaign(
            db,
            campaign_id=campaign_id,
            org_id=org_id,
            actor_user_id=user.id,
            device_ids=body.target.device_ids,
            device_group_ids=body.target.device_group_ids,
            external_entity_ids=body.target.external_entity_ids,
            source_pool=source_pool,
            allocation_snapshot=[
                (item.device_id, item.external_entity_id)
                for item in body.allocation_snapshot
            ],
            allocation_policy=body.allocation_policy,
            dispatch_strategy=body.dispatch_strategy,  # type: ignore[arg-type]
            allow_partial=body.allow_partial,
            require_online=body.require_online,
        )
    except CampaignDispatchError as exc:
        raise HTTPException(
            status_code=_dispatch_http_status(exc.code),
            detail={"code": exc.code, "message": str(exc), **exc.details},
        ) from exc

    from web.metrics import (
        campaign_dispatch_http_duration_seconds,
        campaign_dispatch_phase_duration_seconds,
    )

    campaign_dispatch_phase_duration_seconds.labels(phase="fan_out").observe(
        time.perf_counter() - phase_started
    )
    phase_started = time.perf_counter()

    from db.crud import campaign_entity as campaign_entity_repo
    from services.campaign.execution_runtime import start_execution_runtime

    campaign = await campaign_entity_repo.get_campaign_entity(
        db, campaign_id, org_id=org_id
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail={"code": "CAMPAIGN_NOT_FOUND"})
    config = getattr(request.app.state, "config", None)
    temporal_client = await _campaign_temporal_client(request)
    temporal_config = getattr(config, "temporal", None) if config else None
    manager = getattr(request.app.state, "manager", None)
    _runtime_stats = await start_execution_runtime(
        db,
        fan_out=result,
        campaign=campaign,
        org_id=org_id,
        actor_user_id=user.id,
        temporal_client=temporal_client,
        temporal_config=temporal_config,
        manager=manager,
        commit_before_start=True,
    )

    await db.commit()

    campaign_dispatch_phase_duration_seconds.labels(phase="runtime_start").observe(
        time.perf_counter() - phase_started
    )
    phase_started = time.perf_counter()

    from db.crud.execution import get_executions_by_ids

    payload = result.to_dict(include_vars=include_vars)
    executions_by_id = await get_executions_by_ids(
        db,
        [item["execution_id"] for item in payload["executions"]],
    )
    execution_rows: list[CampaignDispatchExecutionOut] = []
    for item in payload["executions"]:
        ex = executions_by_id.get(item["execution_id"])
        meta = (ex.meta or {}) if ex else {}
        execution_rows.append(
            CampaignDispatchExecutionOut(
                **item,
                dispatch_source=meta.get("dispatch_source"),
                workflow_id=meta.get("workflow_id"),
            )
        )
    response = CampaignDispatchOut(
        dispatch_id=payload["dispatch_id"],
        campaign_id=payload["campaign_id"],
        dispatch_strategy=payload["dispatch_strategy"],
        target_count=payload["target_count"],
        executions=execution_rows,
    )
    campaign_dispatch_phase_duration_seconds.labels(phase="response_hydration").observe(
        time.perf_counter() - phase_started
    )
    campaign_dispatch_http_duration_seconds.observe(
        time.perf_counter() - dispatch_http_started
    )
    return response


@router.post(
    "/{campaign_id}/accounts",
    response_model=CampaignEntityOut,
    dependencies=[Depends(require_permission("campaigns", "update"))],
)
async def bind_campaign_accounts_route(
    campaign_id: str,
    body: CampaignAccountBindIn,
    db: DB,
    user: CurrentUser,
):
    """Bind account_group, scenario_account, or per-device account map (DF-T-04-009)."""
    org_id = getattr(user, "org_id", None)
    if not org_id:
        raise HTTPException(status_code=404, detail={"code": "NO_ORGANIZATION"})

    from services.campaign.account_binding import bind_campaign_accounts
    from services.campaign.account_resolver import AccountBindingError
    from services.campaign.service import get_campaign_for_org

    try:
        await bind_campaign_accounts(
            db,
            org_id=org_id,
            campaign_id=campaign_id,
            user_id=user.id,
            account_group_id=body.account_group_id,
            scenario_account_id=body.scenario_account_id,
            per_device_accounts=body.per_device_accounts or None,
        )
    except AccountBindingError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": str(exc), **exc.details},
        ) from exc
    except CampaignError as exc:
        raise _map_campaign_error(exc) from exc

    await db.commit()
    view = await get_campaign_for_org(db, campaign_id, org_id)
    return _entity_out(view)


@router.delete(
    "/{campaign_id}/accounts",
    response_model=CampaignEntityOut,
    dependencies=[Depends(require_permission("campaigns", "update"))],
)
async def unbind_campaign_accounts_route(
    campaign_id: str,
    db: DB,
    user: CurrentUser,
):
    org_id = getattr(user, "org_id", None)
    if not org_id:
        raise HTTPException(status_code=404, detail={"code": "NO_ORGANIZATION"})

    from services.campaign.account_binding import clear_campaign_accounts
    from services.campaign.service import get_campaign_for_org

    try:
        await clear_campaign_accounts(
            db,
            org_id=org_id,
            campaign_id=campaign_id,
            user_id=user.id,
        )
    except CampaignError as exc:
        raise _map_campaign_error(exc) from exc

    await db.commit()
    view = await get_campaign_for_org(db, campaign_id, org_id)
    return _entity_out(view)


@router.patch(
    "/{campaign_id}",
    response_model=CampaignEntityOut,
    dependencies=[Depends(require_permission("campaigns", "update"))],
)
async def patch_campaign_entity(
    campaign_id: str,
    body: CampaignEntityUpdate,
    db: DB,
    user: CurrentUser,
):
    org_id = getattr(user, "org_id", None)
    if not org_id:
        raise HTTPException(status_code=404, detail={"code": "NO_ORGANIZATION"})
    refs = (
        [ref.model_dump(exclude_none=True) for ref in body.scenario_refs]
        if body.scenario_refs is not None
        else None
    )
    try:
        view = await update_campaign_entity(
            db,
            org_id=org_id,
            campaign_id=campaign_id,
            user_id=user.id,
            name=body.name,
            description=body.description,
            vars=body.vars,
            per_device_overrides=body.per_device_overrides,
            recovery_policy=body.recovery_policy,
            tags=body.tags,
            scenario_refs=refs,
        )
    except CampaignScenarioRefError as exc:
        raise _map_campaign_error(map_scenario_ref_error(exc)) from exc
    except CampaignError as exc:
        raise _map_campaign_error(exc) from exc
    await db.commit()
    return _entity_out(view)


@router.delete(
    "/{campaign_id}",
    response_model=CampaignEntityOut,
    dependencies=[Depends(require_permission("campaigns", "delete"))],
)
async def delete_campaign(campaign_id: str, db: DB, user: CurrentUser):
    org_id = getattr(user, "org_id", None)
    if not org_id:
        raise HTTPException(status_code=404, detail={"code": "NO_ORGANIZATION"})
    try:
        view = await archive_campaign_entity(
            db,
            org_id=org_id,
            campaign_id=campaign_id,
            user_id=user.id,
        )
    except CampaignError as exc:
        raise _map_campaign_error(exc) from exc
    await db.commit()
    return _entity_out(view)

# api endpoint for archive campaign
# used to archive campaign
# this is used to archive campaign
# this is used to archive campaigns
@router.post(
    "/{campaign_id}/archive",
    response_model=CampaignEntityOut,
    dependencies=[Depends(require_permission("campaigns", "delete"))],
)
async def archive_campaign_route(campaign_id: str, db: DB, user: CurrentUser):
    org_id = getattr(user, "org_id", None)
    if not org_id:
        raise HTTPException(status_code=404, detail={"code": "NO_ORGANIZATION"})
    try:
        view = await archive_campaign_entity(
            db,
            org_id=org_id,
            campaign_id=campaign_id,
            user_id=user.id,
        )
    except CampaignError as exc:
        raise _map_campaign_error(exc) from exc
    await db.commit()
    return _entity_out(view)

# api endpoint for force transition campaign
# used to force transition campaign to a specific status
# this is used to force transition campaign to a specific status
# this is used to force transition campaign to a specific status
@router.post(
    "/{campaign_id}/force-transition",
    response_model=CampaignForceTransitionOut,
    dependencies=[Depends(require_permission("campaigns", "manage"))],
)
async def force_transition_campaign(
    campaign_id: str,
    body: CampaignForceTransitionIn,
    db: DB,
    user: CurrentUser,
):
    from api.auth.rbac import is_superadmin
    from services.campaign.lifecycle import transition_campaign_for_org

    if not is_superadmin(user):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN"})

    org_id = getattr(user, "org_id", None)
    if not org_id:
        raise HTTPException(status_code=404, detail={"code": "NO_ORGANIZATION"})

    try:
        result = await transition_campaign_for_org(
            db,
            org_id=org_id,
            campaign_id=campaign_id,
            to_status=body.to_status,
            user_id=user.id,
            reason=body.reason,
            force=True,
        )
    except CampaignError as exc:
        raise _map_campaign_error(exc) from exc
    await db.commit()
    return CampaignForceTransitionOut(
        campaign_id=result.campaign_id,
        from_status=result.from_status,
        to_status=result.to_status,
        changed=result.changed,
        reason=result.reason,
    )


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
            from temporal.workflows import ScenarioStepsWorkflow, ScenarioWorkflow
            from services.execution_control import _resolve_workflow_ids_for_campaign
            from db.crud.execution import list_running_executions_for_campaign

            t_client = await _campaign_temporal_client(request)
            if t_client is not None:
                wf_ids: set[str] = set()
                wf_query = (
                    f'WorkflowId STARTS_WITH "campaign:{campaign_id}:" '
                    f'AND ExecutionStatus="Running"'
                )
                async for wf in t_client.list_workflows(wf_query):
                    wf_ids.add(wf.id)
                    wf_ids.add(f"{wf.id}:steps")

                executions = await list_running_executions_for_campaign(db, campaign_id)
                wf_ids.update(
                    await _resolve_workflow_ids_for_campaign(
                        db, campaign_id, executions, t_client,
                    )
                )

                for wf_id in wf_ids:
                    try:
                        handle = t_client.get_workflow_handle(wf_id)
                        if cancel_trigger:
                            is_parent = not wf_id.endswith(":steps")
                            await handle.signal(
                                ScenarioWorkflow.cancel_scenario
                                if is_parent
                                else ScenarioStepsWorkflow.cancel_scenario
                            )
                        elif pause_trigger:
                            is_parent = not wf_id.endswith(":steps")
                            await handle.signal(
                                ScenarioWorkflow.pause
                                if is_parent
                                else ScenarioStepsWorkflow.pause
                            )
                        elif resume_trigger:
                            is_parent = not wf_id.endswith(":steps")
                            await handle.signal(
                                ScenarioWorkflow.resume
                                if is_parent
                                else ScenarioStepsWorkflow.resume
                            )
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
    cached = getattr(request.app.state, "temporal_client", None)
    if cached is not None:
        return cached
    from temporal.worker import get_temporal_client

    client = await get_temporal_client(config.temporal)
    request.app.state.temporal_client = client
    return client


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


# ── Cumulative run stats for this campaign ───────────────────────────────────

@router.get(
    "/{campaign_id}/run-stats",
    dependencies=[Depends(require_permission("campaigns", "read"))],
)
async def campaign_run_stats_endpoint(campaign_id: str, db: DB, user: CurrentUser):
    """Return cumulative device-run counts (passed/failed/…) across all executions."""
    from api.schemas.execution import SummaryOut
    from db.crud.execution import campaign_run_stats

    await _get_campaign_or_404(campaign_id, user, db)
    data = await campaign_run_stats(db, campaign_id)
    return SummaryOut(**data)


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
    campaign = await _get_campaign_or_404(campaign_id, user, db)
    scenarios = await repo.list_scenarios(db, campaign_id)
    if scenarios:
        result = []
        for s in scenarios:
            result.append(
                _scenario_to_out(
                    s,
                    account_group_name=await _lookup_account_group_name(
                        db, s.account_group_id
                    ),
                )
            )
        return result
    return await _list_org_scenario_outs_for_campaign(db, campaign)


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
    campaign = await _get_campaign_or_404(campaign_id, user, db)
    s = await repo.get_scenario(db, scenario_id)
    if s and s.campaign_id == campaign_id:
        return _scenario_to_out(
            s,
            account_group_name=await _lookup_account_group_name(db, s.account_group_id),
        )
    ref = await _get_org_scenario_ref_row(db, campaign_id, scenario_id)
    org_id = await _campaign_org_id(db, campaign)
    if ref is not None:
        out = await _org_scenario_to_campaign_scenario_out(
            db,
            campaign_id=campaign_id,
            ref=ref,
            org_id=org_id,
        )
        if out is None:
            raise HTTPException(status_code=404, detail="Scenario not found")
        return out
    if scenario_id in _campaign_recovery_scenario_ids(campaign):
        out = await _org_scenario_id_to_campaign_scenario_out(
            db,
            campaign_id=campaign_id,
            org_scenario_id=scenario_id,
            org_id=org_id,
            order=-1,
        )
        if out is None:
            raise HTTPException(status_code=404, detail="Scenario not found")
        return out
    raise HTTPException(status_code=404, detail="Scenario not found")


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
    scope = await _scenario_variable_scope_or_404(db, campaign_id, scenario_id)
    device = await repo.get_device(db, device_id)
    if not await device_visible_to_user(db, user, device):
        raise HTTPException(status_code=404, detail="Device not found")
    if scope == "org":
        vars_map = await get_campaign_org_scenario_device_variables(
            db, campaign_id, scenario_id, device_id
        )
    else:
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
    scope = await _scenario_variable_scope_or_404(db, campaign_id, scenario_id)
    device = await repo.get_device(db, device_id)
    if not await device_visible_to_user(db, user, device):
        raise HTTPException(status_code=404, detail="Device not found")
    if scope == "org":
        vars_map = await replace_campaign_org_scenario_device_variables(
            db, campaign_id, scenario_id, device_id, body.vars
        )
    else:
        vars_map = await replace_scenario_device_variables(
            db, scenario_id, device_id, body.vars
        )
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
    scope = await _scenario_variable_scope_or_404(db, campaign_id, scenario_id)
    device = await repo.get_device(db, device_id)
    if not await device_visible_to_user(db, user, device):
        raise HTTPException(status_code=404, detail="Device not found")
    if scope == "org":
        vars_map = await merge_campaign_org_scenario_device_variables(
            db, campaign_id, scenario_id, device_id, body.vars
        )
    else:
        vars_map = await merge_scenario_device_variables(
            db, scenario_id, device_id, body.vars
        )
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
    scope = await _scenario_variable_scope_or_404(db, campaign_id, scenario_id)
    device = await repo.get_device(db, device_id)
    if not await device_visible_to_user(db, user, device):
        raise HTTPException(status_code=404, detail="Device not found")
    if scope == "org":
        removed = await delete_campaign_org_scenario_device_variable_key(
            db, campaign_id, scenario_id, device_id, key
        )
    else:
        removed = await delete_scenario_device_variable_key(
            db, scenario_id, device_id, key
        )
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
