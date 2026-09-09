"""Org-scoped scenario library CRUD (DF-T-04-001)."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response

from api.auth.rbac import is_superadmin
from api.deps import CurrentUser, DB, require_permission
from api.http_headers import content_disposition_attachment
from api.org_scope import org_member_user_ids
from api.schemas.preview import PreviewStartRequest, PreviewStartResponse
from api.schemas.org_scenario import (
    OrgScenarioBodyIn,
    OrgScenarioBodyOut,
    OrgScenarioCloneTemplateIn,
    OrgScenarioCreate,
    OrgScenarioImportOut,
    OrgScenarioOut,
    OrgScenarioSummaryOut,
    OrgScenarioUpdate,
    OrgScenarioValidateIn,
    OrgScenarioValidationOut,
    ValidationIssueOut,
)
from services.org_scenario.service import (
    OrgScenarioBodyValidationError,
    OrgScenarioDuplicateNameError,
    OrgScenarioError,
    OrgScenarioInUseError,
    OrgScenarioNotFoundError,
    OrgScenarioValidationError,
    archive_scenario,
    create_scenario,
    restore_scenario,
    get_scenario_body as fetch_org_scenario_body,
    get_scenario_for_org,
    list_scenarios_for_org,
    save_scenario_body as persist_org_scenario_body,
    update_scenario,
    validate_scenario_for_org,
)
from services.org_scenario_io.errors import (
    OrgScenarioIOError,
    OrgScenarioImportValidationError,
    OrgScenarioMissingReferencesError,
)
from services.org_scenario_io.importer import (
    import_scenario_bytes,
    import_scenario_bytes_into_existing,
)
from services.org_scenario_io.service import clone_system_template, export_scenario_for_org
from db.crud.scenario_template import list_templates as list_scenario_template_rows

log = logging.getLogger(__name__)

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


def _resolve_org_id(user: CurrentUser, org: str | None) -> str:
    effective = org or getattr(user, "org_id", None)
    if not effective:
        raise HTTPException(status_code=404, detail={"code": "NO_ORGANIZATION"})
    if org and org != getattr(user, "org_id", None) and not is_superadmin(user):
        raise HTTPException(status_code=404, detail={"code": "SCENARIO_NOT_FOUND"})
    return str(effective)


def _map_error(exc: OrgScenarioError) -> HTTPException:
    if isinstance(exc, OrgScenarioNotFoundError):
        return HTTPException(status_code=404, detail={"code": exc.code})
    if isinstance(exc, OrgScenarioDuplicateNameError):
        return HTTPException(status_code=409, detail={"code": exc.code})
    if isinstance(exc, OrgScenarioInUseError):
        return HTTPException(
            status_code=409,
            detail={"code": exc.code, "referenced_by": exc.referenced_by},
        )
    if isinstance(exc, OrgScenarioValidationError):
        return HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)})
    if isinstance(exc, OrgScenarioBodyValidationError):
        detail: dict = {
            "code": exc.primary_code,
            "message": str(exc),
            "status": exc.result.status,
            "errors": [issue.to_dict() for issue in exc.result.errors],
            "warnings": [issue.to_dict() for issue in exc.result.warnings],
            "infos": [issue.to_dict() for issue in exc.result.infos],
        }
        return HTTPException(status_code=400, detail=detail)
    if isinstance(exc, OrgScenarioImportValidationError):
        detail = {
            "code": exc.primary_code,
            "message": str(exc),
            "status": exc.result.status,
            "errors": exc.issues,
            "warnings": [issue.to_dict() for issue in exc.result.warnings],
            "infos": [issue.to_dict() for issue in exc.result.infos],
        }
        return HTTPException(status_code=400, detail=detail)
    if isinstance(exc, OrgScenarioMissingReferencesError):
        return HTTPException(
            status_code=400,
            detail={
                "code": exc.code,
                "message": str(exc),
                "missing_scenarios": exc.missing_names,
            },
        )
    if isinstance(exc, OrgScenarioIOError):
        return HTTPException(status_code=400, detail={"code": exc.code, "message": str(exc), **exc.details})
    return HTTPException(status_code=400, detail={"code": getattr(exc, "code", "SCENARIO_ERROR")})


def _summary_out(view) -> OrgScenarioSummaryOut:
    return OrgScenarioSummaryOut(
        id=view.id,
        organization_id=view.organization_id,
        is_system_template=False,
        name=view.name,
        description=view.description,
        kind=view.kind,
        status=view.status,
        scenario_version=view.scenario_version,
        tags=view.tags,
        created_by=view.created_by,
        created_at=datetime.fromisoformat(view.created_at),
        updated_at=datetime.fromisoformat(view.updated_at),
        is_runnable=view.is_runnable,
        is_recovery_scenario=getattr(view, "is_recovery_scenario", False),
        recovery_usage_count=int(getattr(view, "recovery_usage_count", 0) or 0),
        last_validation_summary=view.last_validation_summary,
        last_validated_at=(
            datetime.fromisoformat(view.last_validated_at)
            if view.last_validated_at
            else None
        ),
    )


def _detail_out(view) -> OrgScenarioOut:
    return OrgScenarioOut(
        **_summary_out(view).model_dump(),
        body_json=view.body_json,
    )


@router.get(
    "",
    response_model=list[OrgScenarioSummaryOut],
    dependencies=[Depends(require_permission("scenarios", "read"))],
)
async def list_scenarios(
    db: DB,
    user: CurrentUser,
    org: str | None = Query(default=None, description="Organization scope (superadmin only override)"),
    include_archived: bool = Query(default=False),
    tag: str | None = Query(default=None),
):
    org_id = _resolve_org_id(user, org)
    views = await list_scenarios_for_org(
        db, org_id, include_archived=include_archived, tag=tag
    )
    return [_summary_out(v) for v in views]


def _scenario_template_summary_out(t) -> OrgScenarioSummaryOut:
    from services.org_scenario_io.service import _template_kind, _template_tags

    display = str(getattr(t, "display_name", "") or "").strip()
    name = display or str(t.name or "")
    tags = _template_tags(t)
    updated = t.updated_at
    if not isinstance(updated, datetime):
        updated = datetime.fromisoformat(str(updated)) if updated else datetime.utcnow()
    steps = t.steps if isinstance(t.steps, list) else []
    nodes = t.nodes if isinstance(t.nodes, list) else []
    return OrgScenarioSummaryOut(
        id=t.id,
        organization_id="",
        is_system_template=True,
        name=name,
        description=str(t.description or ""),
        kind=_template_kind(t),
        status="active",
        scenario_version=1,
        tags=tags,
        created_by=t.user_id,
        created_at=t.created_at if isinstance(t.created_at, datetime) else updated,
        updated_at=updated,
        is_runnable=bool(steps or nodes),
        last_validation_summary=None,
        last_validated_at=None,
    )


@router.get(
    "/templates",
    response_model=list[OrgScenarioSummaryOut],
    dependencies=[Depends(require_permission("scenarios", "read"))],
)
async def list_scenario_templates(
    db: DB,
    user: CurrentUser,
    platform: str | None = Query(default=None),
):
    org_id = getattr(user, "org_id", None)
    user_ids = await org_member_user_ids(db, org_id) if org_id else [user.id]
    rows = await list_scenario_template_rows(
        db,
        user_ids=user_ids,
    )
    if platform:
        from services.org_scenario_io.service import _template_tags

        platform_tag = platform.strip().lower()
        rows = [
            row
            for row in rows
            if platform_tag
            in {tag.strip().lower() for tag in _template_tags(row)}
        ]
    return [_scenario_template_summary_out(t) for t in rows]


@router.post(
    "/import",
    response_model=OrgScenarioImportOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("scenarios", "create"))],
)
async def import_scenario_route(
    db: DB,
    user: CurrentUser,
    file: UploadFile = File(...),
    resolve: str = Query(default="reject", pattern="^(reject|create_stub)$"),
):
    org_id = _resolve_org_id(user, None)
    content = await file.read()
    try:
        result = await import_scenario_bytes(
            db,
            org_id=org_id,
            content=content,
            filename=file.filename,
            created_by=user.id,
            resolve=resolve,
        )
    except OrgScenarioError as exc:
        raise _map_error(exc) from exc
    except OrgScenarioIOError as exc:
        raise _map_error(exc) from exc
    return OrgScenarioImportOut(
        scenario_id=result.scenario_id,
        name=result.name,
        kind=result.kind,
        status=result.status,
        scenario_version=result.scenario_version,
        warnings=result.warnings,
        created_stub_names=result.created_stub_names,
    )


@router.post(
    "/{scenario_id}/import-body",
    response_model=OrgScenarioImportOut,
    dependencies=[Depends(require_permission("scenarios", "update"))],
)
async def import_scenario_body_into_existing_route(
    scenario_id: str,
    db: DB,
    user: CurrentUser,
    file: UploadFile = File(...),
    resolve: str = Query(default="reject", pattern="^(reject|create_stub)$"),
):
    """Replace steps on an existing scenario from a portable export file."""
    org_id = _resolve_org_id(user, None)
    content = await file.read()
    try:
        result = await import_scenario_bytes_into_existing(
            db,
            org_id=org_id,
            scenario_id=scenario_id,
            content=content,
            filename=file.filename,
            created_by=user.id,
            resolve=resolve,
            is_superadmin=is_superadmin(user),
        )
    except OrgScenarioError as exc:
        raise _map_error(exc) from exc
    except OrgScenarioIOError as exc:
        raise _map_error(exc) from exc
    return OrgScenarioImportOut(
        scenario_id=result.scenario_id,
        name=result.name,
        kind=result.kind,
        status=result.status,
        scenario_version=result.scenario_version,
        warnings=result.warnings,
        created_stub_names=result.created_stub_names,
    )


@router.post(
    "/templates/{template_id}/clone",
    response_model=OrgScenarioImportOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("scenarios", "create"))],
)
async def clone_scenario_template_route(
    template_id: str,
    body: OrgScenarioCloneTemplateIn,
    db: DB,
    user: CurrentUser,
):
    org_id = _resolve_org_id(user, None)
    try:
        result = await clone_system_template(
            db,
            template_id=template_id,
            target_org_id=org_id,
            name_override=body.name_override,
            created_by=user.id,
        )
    except OrgScenarioError as exc:
        raise _map_error(exc) from exc
    except OrgScenarioIOError as exc:
        raise _map_error(exc) from exc
    return OrgScenarioImportOut(
        scenario_id=result.scenario_id,
        name=result.name,
        kind=result.kind,
        status=result.status,
        scenario_version=result.scenario_version,
        warnings=result.warnings,
        created_stub_names=result.created_stub_names,
    )


@router.post(
    "",
    response_model=OrgScenarioOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("scenarios", "create"))],
)
async def create_scenario_route(body: OrgScenarioCreate, db: DB, user: CurrentUser):
    org_id = _resolve_org_id(user, None)
    try:
        view = await create_scenario(
            db,
            org_id=org_id,
            name=body.name,
            kind=body.kind,
            description=body.description,
            body_json=body.body_json,
            tags=body.tags,
            created_by=user.id,
        )
    except OrgScenarioError as exc:
        raise _map_error(exc) from exc
    return _detail_out(view)


@router.get(
    "/{scenario_id}",
    response_model=OrgScenarioOut,
    dependencies=[Depends(require_permission("scenarios", "read"))],
)
async def get_scenario(scenario_id: str, db: DB, user: CurrentUser):
    org_id = _resolve_org_id(user, None)
    try:
        view = await get_scenario_for_org(db, scenario_id, org_id)
    except OrgScenarioError as exc:
        raise _map_error(exc) from exc
    return _detail_out(view)


@router.get(
    "/{scenario_id}/export",
    dependencies=[Depends(require_permission("scenarios", "read"))],
)
async def export_scenario_route(
    scenario_id: str,
    db: DB,
    user: CurrentUser,
    export_format: str = Query(default="yaml", alias="format", pattern="^(yaml|json)$"),
    version: int | None = Query(default=None, ge=1),
):
    org_id = _resolve_org_id(user, None)
    try:
        bundle = await export_scenario_for_org(
            db,
            org_id=org_id,
            scenario_id=scenario_id,
            export_format=export_format,
            version=version,
        )
    except OrgScenarioError as exc:
        raise _map_error(exc) from exc
    return Response(
        content=bundle.content,
        media_type=bundle.media_type,
        headers=content_disposition_attachment(bundle.filename),
    )


def _body_payload(body: OrgScenarioBodyIn) -> dict:
    payload: dict = {}
    if body.steps is not None:
        payload["steps"] = body.steps
    if body.nodes is not None:
        payload["nodes"] = body.nodes
    if body.edges is not None:
        payload["edges"] = body.edges
    if body.variables is not None:
        payload["variables"] = body.variables
    if body.requirements is not None:
        payload["requirements"] = body.requirements
    return payload


def _validation_out(scenario_id: str, result, row) -> OrgScenarioValidationOut:
    return OrgScenarioValidationOut(
        scenario_id=scenario_id,
        status=result.status,
        errors=[ValidationIssueOut(**issue.to_dict()) for issue in result.errors],
        warnings=[ValidationIssueOut(**issue.to_dict()) for issue in result.warnings],
        infos=[ValidationIssueOut(**issue.to_dict()) for issue in result.infos],
        last_validated_at=row.last_validated_at,
        last_validation_summary=row.last_validation_summary,
    )


@router.post(
    "/{scenario_id}/validate",
    response_model=OrgScenarioValidationOut,
    dependencies=[Depends(require_permission("scenarios", "read"))],
)
async def validate_scenario_route(
    scenario_id: str,
    db: DB,
    user: CurrentUser,
    body: OrgScenarioValidateIn | None = None,
):
    org_id = _resolve_org_id(user, None)
    payload = _body_payload(body) if body else None
    campaign_vars = body.campaign_variables if body else None
    try:
        result, row = await validate_scenario_for_org(
            db,
            org_id=org_id,
            scenario_id=scenario_id,
            body=payload if payload else None,
            campaign_variables=campaign_vars,
        )
    except OrgScenarioError as exc:
        raise _map_error(exc) from exc
    return _validation_out(scenario_id, result, row)


@router.get(
    "/{scenario_id}/body",
    response_model=OrgScenarioBodyOut,
    dependencies=[Depends(require_permission("scenarios", "read"))],
)
async def get_scenario_body_route(scenario_id: str, db: DB, user: CurrentUser):
    org_id = _resolve_org_id(user, None)
    try:
        view = await fetch_org_scenario_body(
            db, org_id=org_id, scenario_id=scenario_id
        )
    except OrgScenarioError as exc:
        raise _map_error(exc) from exc
    body_json = view.body_json or {}
    return OrgScenarioBodyOut(
        scenario_id=view.id,
        kind=view.kind,
        scenario_version=view.scenario_version,
        body_json=body_json,
        is_runnable=view.is_runnable,
        validation={"status": "valid" if view.is_runnable else "empty"},
    )


@router.post(
    "/{scenario_id}/body",
    response_model=OrgScenarioBodyOut,
    dependencies=[Depends(require_permission("scenarios", "update"))],
)
async def post_scenario_body_route(
    scenario_id: str,
    body: OrgScenarioBodyIn,
    db: DB,
    user: CurrentUser,
    force: bool = Query(default=False, description="Save despite semantic validation errors"),
):
    org_id = _resolve_org_id(user, None)
    try:
        view = await persist_org_scenario_body(
            db,
            org_id=org_id,
            scenario_id=scenario_id,
            body=_body_payload(body),
            user_id=user.id,
            force=force,
            is_superadmin=is_superadmin(user),
        )
    except OrgScenarioError as exc:
        raise _map_error(exc) from exc
    return OrgScenarioBodyOut(
        scenario_id=view.id,
        kind=view.kind,
        scenario_version=view.scenario_version,
        body_json=view.body_json or {},
        is_runnable=view.is_runnable,
        validation={"status": "valid"},
    )


@router.patch(
    "/{scenario_id}",
    response_model=OrgScenarioOut,
    dependencies=[Depends(require_permission("scenarios", "update"))],
)
async def patch_scenario(
    scenario_id: str,
    body: OrgScenarioUpdate,
    db: DB,
    user: CurrentUser,
):
    org_id = _resolve_org_id(user, None)
    try:
        view = await update_scenario(
            db,
            org_id=org_id,
            scenario_id=scenario_id,
            user_id=user.id,
            name=body.name,
            description=body.description,
            kind=body.kind,
            status=body.status,
            body_json=body.body_json,
            tags=body.tags,
            is_superadmin=is_superadmin(user),
        )
    except OrgScenarioError as exc:
        raise _map_error(exc) from exc
    return _detail_out(view)


@router.delete(
    "/{scenario_id}",
    response_model=OrgScenarioOut,
    dependencies=[Depends(require_permission("scenarios", "delete"))],
)
async def delete_scenario(scenario_id: str, db: DB, user: CurrentUser):
    org_id = _resolve_org_id(user, None)
    try:
        view = await archive_scenario(
            db,
            org_id=org_id,
            scenario_id=scenario_id,
            user_id=user.id,
            is_superadmin=is_superadmin(user),
        )
    except OrgScenarioError as exc:
        raise _map_error(exc) from exc
    return _detail_out(view)


@router.post(
    "/{scenario_id}/restore",
    response_model=OrgScenarioOut,
    dependencies=[Depends(require_permission("scenarios", "update"))],
)
async def restore_scenario_route(scenario_id: str, db: DB, user: CurrentUser):
    org_id = _resolve_org_id(user, None)
    try:
        view = await restore_scenario(
            db,
            org_id=org_id,
            scenario_id=scenario_id,
            user_id=user.id,
            is_superadmin=is_superadmin(user),
        )
    except OrgScenarioError as exc:
        raise _map_error(exc) from exc
    return _detail_out(view)


async def _preview_temporal_client(request: Request):
    config = getattr(request.app.state, "config", None)
    if config is None or not getattr(config, "temporal", None) or not config.temporal.enabled:
        return None
    from temporal.worker import get_temporal_client

    return await get_temporal_client(config.temporal)


@router.post(
    "/{scenario_id}/preview",
    response_model=PreviewStartResponse,
    dependencies=[Depends(require_permission("scenarios", "update"))],
)
async def start_scenario_preview(
    scenario_id: str,
    body: PreviewStartRequest,
    request: Request,
    db: DB,
    user: CurrentUser,
):
    """Run scenario on one device as an isolated preview execution (DF-T-04-018)."""
    from services.execution.preview_service import PreviewError, start_preview

    org_id = _resolve_org_id(user, None)
    temporal_client = await _preview_temporal_client(request)
    config = getattr(request.app.state, "config", None)
    temporal_config = getattr(config, "temporal", None) if config else None
    manager = getattr(request.app.state, "manager", None)

    try:
        result = await start_preview(
            db,
            org_id=org_id,
            user_id=user.id,
            scenario_id=scenario_id,
            device_id=body.device_id,
            vars=body.vars,
            account_id=body.account_id,
            force=body.force,
            temporal_client=temporal_client,
            temporal_config=temporal_config,
            manager=manager,
        )
    except PreviewError as exc:
        raise HTTPException(
            status_code=exc.status,
            detail={"code": exc.code, "message": str(exc), **exc.details},
        ) from exc

    return PreviewStartResponse(
        execution_id=result.execution_id,
        status=result.status,
        warnings=result.warnings,
        workflow_id=result.workflow_id,
        dispatch_source=result.dispatch_source,
        org_scenario_id=result.org_scenario_id,
        device_id=result.device_id,
    )


# ── Image templates for tap_image steps ──────────────────────────────────────
#
# Note: "templates" elsewhere in this router means *scenario* templates. These
# are the cropped screen images a tap_image step matches against.
#
# Templates live in object storage rather than inline in the scenario JSON: a
# scenario with a dozen image steps would otherwise carry a dozen base64 blobs.
# Keyed by org and scenario so deleting a scenario can drop its templates by
# prefix.

_TEMPLATE_MAX_BYTES = 2 * 1024 * 1024


def _template_key(org_id: str, scenario_id: str, digest: str) -> str:
    return f"{org_id}/scenario-templates/{scenario_id}/{digest}.png"


# Not cleaned up on DELETE /scenarios/{id}: that route archives, and there is a
# /restore beside it — dropping the images would leave a restored scenario with
# tap_image steps pointing at nothing. The prefix above is per-scenario so a
# real hard-delete can call minio_store.delete_prefix() when one exists.


@router.post(
    "/{scenario_id}/image-templates",
    dependencies=[Depends(require_permission("scenarios", "update"))],
)
async def upload_step_template_route(
    scenario_id: str,
    user: CurrentUser,
    file: UploadFile = File(...),
    screen_w: int = Query(default=0, ge=0),
    screen_h: int = Query(default=0, ge=0),
):
    """Store a cropped template and report whether it is safe to match on.

    The ambiguity check is the point of doing this server-side: a crop of blank
    background scores 1.000 everywhere, so it would tap the wrong place while
    looking perfectly confident. Better to say so while the user is still
    looking at the crop than to debug it later in a run.
    """
    import hashlib

    from services import minio_store

    org_id = _resolve_org_id(user, None)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail={"code": "TEMPLATE_EMPTY"})
    if len(content) > _TEMPLATE_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail={"code": "TEMPLATE_TOO_LARGE", "max_bytes": _TEMPLATE_MAX_BYTES},
        )

    warning = ""
    try:
        from runtime.image_quality import looks_ambiguous

        # OpenCV decode + stats; off the event loop so one upload cannot stall
        # every other request on this worker.
        ambiguous, reason = await asyncio.to_thread(looks_ambiguous, content)
        if ambiguous:
            warning = reason
    except Exception as exc:  # pragma: no cover - advisory only
        log.debug("template ambiguity check skipped: %s", exc)

    digest = hashlib.sha256(content).hexdigest()[:32]
    key = _template_key(org_id, scenario_id, digest)
    if not minio_store.enabled():
        raise HTTPException(status_code=503, detail={"code": "OBJECT_STORAGE_UNAVAILABLE"})
    # Blocking network I/O to object storage — same reason as above.
    uploaded = await asyncio.to_thread(
        minio_store.upload, content, key, "image/png"
    )
    if not uploaded:
        raise HTTPException(status_code=502, detail={"code": "TEMPLATE_UPLOAD_FAILED"})

    return {
        "template_key": key,
        "size_bytes": len(content),
        "screen_w": screen_w or None,
        "screen_h": screen_h or None,
        "warning": warning,
    }


@router.get(
    "/{scenario_id}/image-templates/url",
    dependencies=[Depends(require_permission("scenarios", "read"))],
)
async def get_step_template_url_route(
    scenario_id: str,
    user: CurrentUser,
    key: str = Query(...),
):
    """Presigned URL so the editor can show the template already attached."""
    from services import minio_store

    org_id = _resolve_org_id(user, None)
    # Never let a caller read another org's objects by passing an arbitrary key.
    if not key.startswith(f"{org_id}/scenario-templates/{scenario_id}/"):
        raise HTTPException(status_code=404, detail={"code": "TEMPLATE_NOT_FOUND"})
    url = minio_store.presigned_get(key, expires_seconds=3600)
    if not url:
        raise HTTPException(status_code=404, detail={"code": "TEMPLATE_NOT_FOUND"})
    return {"url": url}
