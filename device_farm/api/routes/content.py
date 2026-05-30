"""DF-010: Content Pipeline — API endpoints for content CRUD, collections, exports, stats."""
from __future__ import annotations

import csv
import io
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse

from api.auth.content_share import create_content_share_token, verify_content_share_token
from api.deps import CurrentUser, DB, require_permission
from api.org_scope import data_owner_user_id
from api.schemas.content import (
    CollectionCreate,
    CollectionOut,
    ContentArtifactOut,
    ContentDetailOut,
    ContentItemOut,
    ContentPermalinkOut,
    ContentStatsOut,
    SaveContentBody,
)
from db.crud import content as content_crud
from services.content_artifacts import (
    collect_content_artifacts,
    merge_execution_artifacts,
    read_artifact_bytes,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/content", tags=["content"])

# Fields written to CSV / XLSX exports
_EXPORT_FIELDS = [
    "id", "collection", "platform", "content_type", "author", "author_id",
    "title", "body", "url",
    "likes_count", "comments_count", "shares_count", "views_count",
    "tags", "device_serial", "campaign_id", "execution_id",
    "scenario_name", "item_level", "parent_id",
    # Join key (used to validate parent-child correctness)
    "content_hash",
    "extracted_at", "content_date", "created_at",
]

_BATCH = 500  # rows per DB fetch batch


def _item_row(item) -> list:
    return [
        item.id, item.collection, item.platform, item.content_type,
        item.author, item.author_id, item.title, item.body, item.url,
        item.likes_count, item.comments_count, item.shares_count, item.views_count,
        item.tags, item.device_serial, item.campaign_id, item.execution_id,
        item.scenario_name, item.item_level, item.parent_id,
        item.content_hash,
        item.extracted_at.isoformat() if item.extracted_at else None,
        item.content_date.isoformat() if item.content_date else None,
        item.created_at.isoformat() if item.created_at else None,
    ]


async def _csv_generator(db, filters: dict) -> AsyncGenerator[bytes, None]:
    """Yield CSV bytes row-by-row without loading all data into memory."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    # Header
    writer.writerow(_EXPORT_FIELDS)
    yield buf.getvalue().encode()

    offset = 0
    while True:
        items, _ = await content_crud.query_content(db, **filters, limit=_BATCH, offset=offset)
        if not items:
            break
        for item in items:
            buf = io.StringIO()
            csv.writer(buf).writerow(_item_row(item))
            yield buf.getvalue().encode()
        if len(items) < _BATCH:
            break
        offset += _BATCH


async def _xlsx_bytes(db, filters: dict) -> bytes:
    """Build XLSX in-memory using openpyxl write-only mode (low memory)."""
    import openpyxl

    wb = openpyxl.Workbook(write_only=True)
    ws = wb.create_sheet("Content")
    ws.append(_EXPORT_FIELDS)

    offset = 0
    while True:
        items, _ = await content_crud.query_content(db, **filters, limit=_BATCH, offset=offset)
        if not items:
            break
        for item in items:
            ws.append(_item_row(item))
        if len(items) < _BATCH:
            break
        offset += _BATCH

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── Streaming Export ──────────────────────────────────────────────────────────


@router.get(
    "/export/stream",
    dependencies=[Depends(require_permission("content", "read"))],
)
async def stream_export(
    db: DB,
    user: CurrentUser,
    format: str = Query("csv", pattern="^(csv|xlsx)$"),
    collection: str | None = None,
    platform: str | None = None,
    content_type: str | None = None,
    search: str | None = None,
    device_serial: str | None = None,
    campaign_id: str | None = None,
    execution_id: str | None = None,
):
    """Stream content export directly to the client — no temp file, no job queue.

    CSV streams row-by-row via chunked transfer encoding.
    XLSX is built in-memory with openpyxl write-only mode then sent as a single response.
    """
    filters = {
        k: v for k, v in {
            "collection": collection, "platform": platform,
            "content_type": content_type, "search": search,
            "device_serial": device_serial, "campaign_id": campaign_id,
            "execution_id": execution_id,
        }.items() if v is not None
    }
    owner_id = data_owner_user_id(user)
    if owner_id:
        filters["user_id"] = owner_id

    if format == "csv":
        filename = "content-export.csv"
        return StreamingResponse(
            _csv_generator(db, filters),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # xlsx — build in-memory then stream
    data = await _xlsx_bytes(db, filters)
    filename = "content-export.xlsx"
    return StreamingResponse(
        iter([data]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/export", dependencies=[Depends(require_permission("content", "read"))])
async def legacy_export_removed():
    raise HTTPException(404, "Content export endpoint removed")


@router.get(
    "/exports/list",
    dependencies=[Depends(require_permission("content", "read"))],
)
async def legacy_export_list_removed():
    raise HTTPException(404, "Content export endpoint removed")


@router.get(
    "/exports/{export_id}",
    dependencies=[Depends(require_permission("content", "read"))],
)
async def legacy_export_detail_removed(export_id: str):
    raise HTTPException(404, "Content export endpoint removed")


@router.get(
    "/exports/{export_id}/download",
    dependencies=[Depends(require_permission("content", "read"))],
)
async def legacy_export_download_removed(export_id: str):
    raise HTTPException(404, "Content export endpoint removed")


# ── Content Items ─────────────────────────────────────────────────────────────


@router.get("", dependencies=[Depends(require_permission("content", "read"))])
async def list_content(
    db: DB,
    user: CurrentUser,
    collection: str | None = None,
    platform: str | None = None,
    content_type: str | None = None,
    search: str | None = None,
    device_serial: str | None = None,
    campaign_id: str | None = None,
    execution_id: str | None = None,
    content_hash: str | None = None,
    parent_id: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    owner_id = data_owner_user_id(user)
    items, total = await content_crud.query_content(
        db,
        collection=collection,
        platform=platform,
        content_type=content_type,
        search=search,
        device_serial=device_serial,
        campaign_id=campaign_id,
        execution_id=execution_id,
        content_hash=content_hash,
        parent_id=parent_id,
        user_id=owner_id,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [_item_to_out(i) for i in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get(
    "/stats",
    response_model=ContentStatsOut,
    dependencies=[Depends(require_permission("content", "read"))],
)
async def get_stats(db: DB, user: CurrentUser):
    owner_id = data_owner_user_id(user)
    return await content_crud.content_stats(db, user_id=owner_id)


@router.post("/save", dependencies=[Depends(require_permission("content", "create"))])
async def save_content(body: SaveContentBody, db: DB, user: CurrentUser):
    """Save extracted content with deduplication (used by scenarios and MCP)."""
    from services.content_store import save_content_item
    result = await save_content_item(
        data=body.data,
        collection=body.collection,
        platform=body.platform,
        content_type=body.content_type,
        dedupe_field=body.dedupe_field,
        tags=body.tags,
        device_serial=body.device_serial,
        campaign_id=body.campaign_id,
        user_id=user.id,
    )
    return result


async def _load_content_item(
    db: DB,
    item_id: str,
    user: CurrentUser,
    share: str | None,
):
    if share:
        verify_content_share_token(share, content_id=item_id)
        item = await content_crud.get_content_item(db, item_id, user_id=None)
    else:
        owner_id = data_owner_user_id(user)
        item = await content_crud.get_content_item(db, item_id, user_id=owner_id)
    if not item:
        status = 403 if share else 404
        raise HTTPException(status, "Content item not found")
    return item


async def _execution_step_artifact_pairs(
    db: DB,
    item,
    user: CurrentUser,
) -> list[tuple[str, str | None]]:
    if not item.execution_id:
        return []
    from api.routes.executions import _extract_step_artifacts, _get_or_404
    from db.crud.device import get_device
    from db.crud.execution import list_execution_results

    try:
        await _get_or_404(db, item.execution_id, user.id)
    except HTTPException:
        return []

    pairs: list[tuple[str, str | None]] = []
    results = await list_execution_results(db, item.execution_id)
    for er in results:
        device = await get_device(db, er.device_id)
        serial = device.serial if device else None
        for step_art in _extract_step_artifacts(
            item.execution_id,
            serial or "unknown",
            (er.passed_steps or []) + (er.failed_steps or []),
            er.created_at,
        ):
            pairs.append((step_art.artifact_type, step_art.url))
    return pairs


@router.get(
    "/{item_id}",
    response_model=ContentDetailOut,
    dependencies=[Depends(require_permission("content", "read"))],
)
async def get_content_item(
    item_id: str,
    db: DB,
    user: CurrentUser,
    share: str | None = Query(None, description="Content share JWT from permalink"),
):
    item = await _load_content_item(db, item_id, user, share)
    return await _item_detail_out(db, item, user)


@router.get(
    "/{item_id}/artifacts/{artifact_id}/download",
    dependencies=[Depends(require_permission("content", "read"))],
)
async def download_content_artifact(
    item_id: str,
    artifact_id: str,
    db: DB,
    user: CurrentUser,
    share: str | None = Query(None),
):
    item = await _load_content_item(db, item_id, user, share)
    artifacts = await _collect_all_artifacts(db, item, user)
    try:
        payload, filename, mime_type = await read_artifact_bytes(
            item, artifact_id, artifacts
        )
    except FileNotFoundError as exc:
        raise HTTPException(410, "Artifact expired or unavailable") from exc
    log.info(
        "content artifact_download item_id=%s artifact_id=%s user_id=%s bytes=%s",
        item_id,
        artifact_id,
        user.id,
        len(payload),
    )
    return Response(
        content=payload,
        media_type=mime_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/{item_id}/permalink",
    response_model=ContentPermalinkOut,
    dependencies=[Depends(require_permission("content", "create"))],
)
async def create_content_permalink(item_id: str, db: DB, user: CurrentUser):
    owner_id = data_owner_user_id(user)
    item = await content_crud.get_content_item(db, item_id, user_id=owner_id)
    if not item:
        raise HTTPException(404, "Content item not found")
    token = create_content_share_token(user_id=user.id, content_id=item_id)
    path = f"/dashboard/content/{item_id}?share={token}"
    return ContentPermalinkOut(token=token, path=path)


@router.delete("/{item_id}", dependencies=[Depends(require_permission("content", "delete"))])
async def delete_content_item(item_id: str, db: DB, user: CurrentUser):
    owner_id = data_owner_user_id(user)
    ok = await content_crud.delete_content_item(db, item_id, user_id=owner_id)
    if not ok:
        raise HTTPException(404, "Content item not found")
    await db.commit()
    return {"ok": True}


# ── Collections ───────────────────────────────────────────────────────────────


@router.get(
    "/collections/list",
    response_model=list[CollectionOut],
    dependencies=[Depends(require_permission("content", "read"))],
)
async def list_collections(db: DB, user: CurrentUser):
    owner_id = data_owner_user_id(user)
    colls = await content_crud.list_collections(db, user_id=owner_id)
    return [
        CollectionOut(
            id=c.id, name=c.name, description=c.description,
            platform=c.platform, item_count=c.item_count, created_at=c.created_at,
        )
        for c in colls
    ]


@router.post(
    "/collections",
    dependencies=[Depends(require_permission("content", "create"))],
)
async def create_collection(body: CollectionCreate, db: DB, user: CurrentUser):
    coll = await content_crud.get_or_create_collection(
        db,
        name=body.name,
        description=body.description,
        platform=body.platform,
        user_id=user.id,
    )
    await db.commit()
    return {"id": coll.id, "name": coll.name}


@router.delete(
    "/collections/{name}",
    dependencies=[Depends(require_permission("content", "delete"))],
)
async def delete_collection(name: str, db: DB, user: CurrentUser):
    owner_id = data_owner_user_id(user)
    count = await content_crud.delete_collection(db, name, user_id=owner_id)
    await db.commit()
    return {"ok": True, "items_deleted": count}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _item_to_out(item, *, include_raw: bool = False) -> dict:
    raw = item.raw_data if isinstance(item.raw_data, dict) else {}
    return ContentItemOut(
        id=item.id,
        collection=item.collection,
        platform=item.platform,
        content_type=item.content_type,
        title=item.title,
        body=item.body,
        author=item.author,
        author_id=item.author_id,
        url=item.url,
        likes_count=item.likes_count,
        comments_count=item.comments_count,
        shares_count=item.shares_count,
        views_count=item.views_count,
        media_urls=item.media_urls or [],
        screenshot_path=item.screenshot_path,
        tags=item.tags or "",
        raw_data=raw if include_raw else None,
        device_serial=item.device_serial,
        campaign_id=item.campaign_id,
        execution_id=item.execution_id,
        scenario_name=item.scenario_name,
        extracted_at=item.extracted_at,
        content_date=item.content_date,
        created_at=item.created_at,
        content_hash=item.content_hash,
        parent_id=item.parent_id,
        item_level=int(item.item_level or 0),
    ).model_dump(mode="json", exclude_none=include_raw is False)


def _build_payload(item) -> dict:
    raw = item.raw_data if isinstance(item.raw_data, dict) else {}
    payload = {
        "id": item.id,
        "collection": item.collection,
        "platform": item.platform,
        "content_type": item.content_type,
        "title": item.title,
        "body": item.body,
        "author": item.author,
        "author_id": item.author_id,
        "url": item.url,
        "likes_count": item.likes_count,
        "comments_count": item.comments_count,
        "shares_count": item.shares_count,
        "views_count": item.views_count,
        "media_urls": item.media_urls or [],
        "tags": item.tags,
        "device_serial": item.device_serial,
        "campaign_id": item.campaign_id,
        "execution_id": item.execution_id,
        "scenario_name": item.scenario_name,
        "extracted_at": item.extracted_at.isoformat() if item.extracted_at else None,
        "content_date": item.content_date.isoformat() if item.content_date else None,
        "content_hash": item.content_hash,
        "parent_id": item.parent_id,
        "item_level": item.item_level,
        "raw_data": raw,
    }
    return payload


async def _collect_all_artifacts(db, item, user: CurrentUser) -> list[dict]:
    artifacts = collect_content_artifacts(item)
    steps = await _execution_step_artifact_pairs(db, item, user)
    return merge_execution_artifacts(item, artifacts, steps)


async def _item_detail_out(db, item, user: CurrentUser) -> dict:
    base = _item_to_out(item, include_raw=True)
    artifacts = [
        ContentArtifactOut(**a) for a in await _collect_all_artifacts(db, item, user)
    ]
    return {
        **base,
        "artifacts": [a.model_dump(mode="json") for a in artifacts],
        "payload": _build_payload(item),
    }
