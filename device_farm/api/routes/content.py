"""DF-010: Content Pipeline — API endpoints for content CRUD, collections, exports, stats."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

from api.deps import CurrentUser, DB
from api.schemas.content import (
    CollectionCreate, CollectionOut, ContentItemOut, ContentStatsOut,
    ExportOut, ExportRequest, SaveContentBody,
)
from db.crud import content as content_crud

log = logging.getLogger(__name__)

router = APIRouter(prefix="/content", tags=["content"])


# ── Content Items ─────────────────────────────────────────────────────────────


@router.get("")
async def list_content(
    db: DB,
    collection: str | None = None,
    platform: str | None = None,
    content_type: str | None = None,
    search: str | None = None,
    device_serial: str | None = None,
    campaign_id: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    items, total = await content_crud.query_content(
        db,
        collection=collection,
        platform=platform,
        content_type=content_type,
        search=search,
        device_serial=device_serial,
        campaign_id=campaign_id,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [_item_to_out(i) for i in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/stats", response_model=ContentStatsOut)
async def get_stats(db: DB):
    return await content_crud.content_stats(db)


@router.post("/save")
async def save_content(body: SaveContentBody, db: DB):
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
    )
    return result


@router.get("/{item_id}")
async def get_content_item(item_id: str, db: DB):
    item = await content_crud.get_content_item(db, item_id)
    if not item:
        raise HTTPException(404, "Content item not found")
    return _item_to_out(item)


@router.delete("/{item_id}")
async def delete_content_item(item_id: str, db: DB):
    ok = await content_crud.delete_content_item(db, item_id)
    if not ok:
        raise HTTPException(404, "Content item not found")
    await db.commit()
    return {"ok": True}


# ── Collections ───────────────────────────────────────────────────────────────


@router.get("/collections/list", response_model=list[CollectionOut])
async def list_collections(db: DB):
    colls = await content_crud.list_collections(db)
    return [
        CollectionOut(
            id=c.id, name=c.name, description=c.description,
            platform=c.platform, item_count=c.item_count, created_at=c.created_at,
        )
        for c in colls
    ]


@router.post("/collections")
async def create_collection(body: CollectionCreate, db: DB):
    coll = await content_crud.get_or_create_collection(
        db, name=body.name, description=body.description, platform=body.platform
    )
    await db.commit()
    return {"id": coll.id, "name": coll.name}


@router.delete("/collections/{name}")
async def delete_collection(name: str, db: DB):
    count = await content_crud.delete_collection(db, name)
    await db.commit()
    return {"ok": True, "items_deleted": count}


# ── Exports ───────────────────────────────────────────────────────────────────


@router.post("/export", response_model=ExportOut)
async def create_export(body: ExportRequest, db: DB, background_tasks: BackgroundTasks):
    if body.format not in ("csv", "json"):
        raise HTTPException(400, "format must be 'csv' or 'json'")

    export = await content_crud.create_export(
        db,
        collection=body.collection,
        format=body.format,
        filters=body.filters,
    )
    await db.commit()

    from services.content_export import process_export
    background_tasks.add_task(process_export, export.id)

    return ExportOut(
        id=export.id, collection=export.collection, format=export.format,
        status=export.status, item_count=0, created_at=export.created_at,
    )


@router.get("/exports/list", response_model=list[ExportOut])
async def list_exports(db: DB):
    exports = await content_crud.list_exports(db)
    return [
        ExportOut(
            id=e.id, collection=e.collection, format=e.format,
            status=e.status, item_count=e.item_count,
            file_size_bytes=e.file_size_bytes,
            created_at=e.created_at, completed_at=e.completed_at,
        )
        for e in exports
    ]


@router.get("/exports/{export_id}")
async def get_export(export_id: str, db: DB):
    export = await content_crud.get_export(db, export_id)
    if not export:
        raise HTTPException(404, "Export not found")
    return ExportOut(
        id=export.id, collection=export.collection, format=export.format,
        status=export.status, item_count=export.item_count,
        file_size_bytes=export.file_size_bytes,
        created_at=export.created_at, completed_at=export.completed_at,
    )


@router.get("/exports/{export_id}/download")
async def download_export(export_id: str, db: DB):
    export = await content_crud.get_export(db, export_id)
    if not export:
        raise HTTPException(404, "Export not found")
    if export.status != "ready" or not export.file_path:
        raise HTTPException(422, f"Export not ready (status={export.status})")
    if not os.path.exists(export.file_path):
        raise HTTPException(404, "Export file not found on disk")
    return FileResponse(
        export.file_path,
        filename=f"content-export-{export_id}.{export.format}",
        media_type="text/csv" if export.format == "csv" else "application/json",
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _item_to_out(item) -> dict:
    return {
        "id": item.id,
        "collection": item.collection,
        "platform": item.platform,
        "content_type": item.content_type,
        "title": item.title,
        "body": item.body,
        "author": item.author,
        "url": item.url,
        "likes_count": item.likes_count,
        "comments_count": item.comments_count,
        "shares_count": item.shares_count,
        "views_count": item.views_count,
        "tags": item.tags,
        "device_serial": item.device_serial,
        "campaign_id": item.campaign_id,
        "extracted_at": item.extracted_at.isoformat() if item.extracted_at else None,
    }
