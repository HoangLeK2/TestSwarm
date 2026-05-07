"""DF-010: Content Pipeline — API endpoints for content CRUD, collections, exports, stats."""
from __future__ import annotations

import csv
import io
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from api.deps import CurrentUser, DB
from api.schemas.content import (
    CollectionCreate, CollectionOut, ContentItemOut, ContentStatsOut,
    SaveContentBody,
)
from db.crud import content as content_crud

log = logging.getLogger(__name__)

router = APIRouter(prefix="/content", tags=["content"])

# Fields written to CSV / XLSX exports
_EXPORT_FIELDS = [
    "id", "collection", "platform", "content_type", "author", "author_id",
    "title", "body", "url",
    "likes_count", "comments_count", "shares_count", "views_count",
    "tags", "device_serial", "campaign_id", "execution_id",
    "scenario_name", "item_level", "parent_id",
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


@router.get("/export/stream")
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
            "user_id": user.id,
        }.items() if v is not None
    }

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


# ── Content Items ─────────────────────────────────────────────────────────────


@router.get("")
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
        user_id=user.id,
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
async def get_stats(db: DB, user: CurrentUser):
    return await content_crud.content_stats(db, user_id=user.id)


@router.post("/save")
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


@router.get("/{item_id}")
async def get_content_item(item_id: str, db: DB, user: CurrentUser):
    item = await content_crud.get_content_item(db, item_id, user_id=user.id)
    if not item:
        raise HTTPException(404, "Content item not found")
    return _item_to_out(item)


@router.delete("/{item_id}")
async def delete_content_item(item_id: str, db: DB, user: CurrentUser):
    ok = await content_crud.delete_content_item(db, item_id, user_id=user.id)
    if not ok:
        raise HTTPException(404, "Content item not found")
    await db.commit()
    return {"ok": True}


# ── Collections ───────────────────────────────────────────────────────────────


@router.get("/collections/list", response_model=list[CollectionOut])
async def list_collections(db: DB, user: CurrentUser):
    colls = await content_crud.list_collections(db, user_id=user.id)
    return [
        CollectionOut(
            id=c.id, name=c.name, description=c.description,
            platform=c.platform, item_count=c.item_count, created_at=c.created_at,
        )
        for c in colls
    ]


@router.post("/collections")
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


@router.delete("/collections/{name}")
async def delete_collection(name: str, db: DB, user: CurrentUser):
    count = await content_crud.delete_collection(db, name, user_id=user.id)
    await db.commit()
    return {"ok": True, "items_deleted": count}


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
        "execution_id": item.execution_id,
        "extracted_at": item.extracted_at.isoformat() if item.extracted_at else None,
        "content_hash": item.content_hash,
        "parent_id": item.parent_id,
        "item_level": item.item_level,
    }
