"""Org-scoped reusable external entity catalog API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import CurrentUser, DB, require_permission
from api.schemas.external_entity import (
    ExternalEntityBulkObserveIn,
    ExternalEntityBulkObserveOut,
    ExternalEntityListOut,
    ExternalEntityObserveIn,
    ExternalEntityObserveOut,
    ExternalEntityOut,
)
from db.crud.external_entity import (
    get_external_entity,
    list_external_entities,
    upsert_external_entity,
)
from db.models.external_entity import ExternalEntity

router = APIRouter(prefix="/external-entities", tags=["external-entities"])


def _org_id(user: CurrentUser) -> str:
    value = str(getattr(user, "org_id", None) or "").strip()
    if not value:
        raise HTTPException(status_code=404, detail={"code": "NO_ORGANIZATION"})
    return value


def _entity_out(entity: ExternalEntity) -> ExternalEntityOut:
    return ExternalEntityOut(
        id=entity.id,
        org_id=entity.org_id,
        platform=entity.platform,
        entity_type=entity.entity_type,
        identity_key=entity.identity_key,
        identity_confidence=entity.identity_confidence,
        external_id=entity.external_id,
        canonical_url=entity.canonical_url,
        display_name=entity.display_name,
        status=entity.status,
        current_attributes=entity.current_attributes or {},
        current_metrics=entity.current_metrics or {},
        first_seen_at=entity.first_seen_at,
        last_seen_at=entity.last_seen_at,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


async def _observe(
    db: DB,
    user: CurrentUser,
    item: ExternalEntityObserveIn,
) -> ExternalEntityObserveOut:
    try:
        entity, created = await upsert_external_entity(
            db,
            org_id=_org_id(user),
            created_by=user.id,
            **item.model_dump(),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_EXTERNAL_ENTITY", "message": str(exc)},
        ) from exc
    return ExternalEntityObserveOut(entity=_entity_out(entity), created=created)


@router.get(
    "",
    response_model=ExternalEntityListOut,
    dependencies=[Depends(require_permission("content", "read"))],
)
async def list_external_entities_route(
    db: DB,
    user: CurrentUser,
    platform: str | None = None,
    entity_type: str | None = None,
    status: str | None = None,
    search: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> ExternalEntityListOut:
    rows, total = await list_external_entities(
        db,
        org_id=_org_id(user),
        platform=platform,
        entity_type=entity_type,
        status=status,
        search=search,
        limit=limit,
        offset=offset,
    )
    return ExternalEntityListOut(
        items=[_entity_out(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/observe",
    response_model=ExternalEntityObserveOut,
    dependencies=[Depends(require_permission("content", "create"))],
)
async def observe_external_entity_route(
    body: ExternalEntityObserveIn,
    db: DB,
    user: CurrentUser,
) -> ExternalEntityObserveOut:
    return await _observe(db, user, body)


@router.post(
    "/bulk-observe",
    response_model=ExternalEntityBulkObserveOut,
    dependencies=[Depends(require_permission("content", "create"))],
)
async def bulk_observe_external_entities_route(
    body: ExternalEntityBulkObserveIn,
    db: DB,
    user: CurrentUser,
) -> ExternalEntityBulkObserveOut:
    observed = [await _observe(db, user, item) for item in body.items]
    return ExternalEntityBulkObserveOut(
        items=observed,
        observed_count=len(observed),
        created_count=sum(1 for item in observed if item.created),
    )


@router.get(
    "/{entity_id}",
    response_model=ExternalEntityOut,
    dependencies=[Depends(require_permission("content", "read"))],
)
async def get_external_entity_route(
    entity_id: str,
    db: DB,
    user: CurrentUser,
) -> ExternalEntityOut:
    entity = await get_external_entity(
        db,
        org_id=_org_id(user),
        entity_id=entity_id,
    )
    if entity is None:
        raise HTTPException(status_code=404, detail={"code": "EXTERNAL_ENTITY_NOT_FOUND"})
    return _entity_out(entity)
