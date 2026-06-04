from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from api.auth.rbac import is_superadmin
from api.deps import CurrentUser, DB, require_permission
from api.org_scope import org_member_user_ids
from api.schemas.scenario_template import (
    ScenarioTemplateCreate,
    ScenarioTemplateOut,
    ScenarioTemplateUpdate,
)
from db.crud.scenario_template import (
    create_template,
    delete_template,
    duplicate_template,
    get_template,
    list_templates,
    update_template,
)

router = APIRouter(prefix="/scenario-templates", tags=["scenario-templates"])


def _to_out(t) -> ScenarioTemplateOut:
    return ScenarioTemplateOut(
        id=t.id,
        name=t.name,
        display_name=getattr(t, "display_name", None) or "",
        description=t.description or "",
        category=t.category or "general",
        steps=t.steps or [],
        variables=t.variables or {},
        tags=t.tags or "",
        is_builtin=t.is_builtin,
        user_id=t.user_id,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


@router.get(
    "",
    response_model=list[ScenarioTemplateOut],
    dependencies=[Depends(require_permission("scenario-templates", "read"))],
)
async def list_scenario_templates(
    db: DB,
    user: CurrentUser,
    category: str | None = None,
    tags: str | None = None,
):
    org_id = getattr(user, "org_id", None)
    user_ids = await org_member_user_ids(db, org_id) if org_id else [user.id]
    templates = await list_templates(
        db,
        category=category,
        tags=tags,
        user_ids=user_ids,
    )
    return [_to_out(t) for t in templates]


@router.post(
    "",
    response_model=ScenarioTemplateOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("scenario-templates", "create"))],
)
async def create_scenario_template(
    body: ScenarioTemplateCreate,
    db: DB,
    user: CurrentUser,
):
    if not is_superadmin(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN",
                "message": "Only superadmin can create system scenario templates",
            },
        )
    tmpl = await create_template(
        db,
        name=body.name,
        display_name=body.display_name,
        description=body.description,
        category=body.category,
        steps=body.steps,
        variables=body.variables,
        tags=body.tags,
        is_builtin=True,
        user_id=user.id,
    )
    await db.commit()
    return _to_out(tmpl)


@router.get(
    "/{template_id}",
    response_model=ScenarioTemplateOut,
    dependencies=[Depends(require_permission("scenario-templates", "read"))],
)
async def get_scenario_template(template_id: str, db: DB, _: CurrentUser):
    tmpl = await get_template(db, template_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return _to_out(tmpl)


@router.patch(
    "/{template_id}",
    response_model=ScenarioTemplateOut,
    dependencies=[Depends(require_permission("scenario-templates", "update"))],
)
async def update_scenario_template(
    template_id: str,
    body: ScenarioTemplateUpdate,
    db: DB,
    _: CurrentUser,
):
    tmpl = await get_template(db, template_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="Template not found")
    if tmpl.is_builtin:
        raise HTTPException(status_code=403, detail="Builtin templates cannot be modified")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if updates:
        await update_template(db, template_id, **updates)
    await db.commit()
    tmpl = await get_template(db, template_id)
    return _to_out(tmpl)


@router.delete(
    "/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("scenario-templates", "delete"))],
)
async def delete_scenario_template(template_id: str, db: DB, _: CurrentUser):
    tmpl = await get_template(db, template_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="Template not found")
    if tmpl.is_builtin:
        raise HTTPException(status_code=403, detail="Builtin templates cannot be deleted")
    await delete_template(db, template_id)
    await db.commit()


@router.post(
    "/{template_id}/duplicate",
    response_model=ScenarioTemplateOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("scenario-templates", "create"))],
)
async def duplicate_scenario_template(
    template_id: str,
    db: DB,
    user: CurrentUser,
):
    copy = await duplicate_template(db, template_id, user_id=user.id)
    if copy is None:
        raise HTTPException(status_code=404, detail="Template not found")
    await db.commit()
    return _to_out(copy)
