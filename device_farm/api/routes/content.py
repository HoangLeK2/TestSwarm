"""DF-010: Content Pipeline — API endpoints for content CRUD, collections, exports, stats."""
from __future__ import annotations

import csv
import io
import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import or_, select

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
from db.models.content import ContentItem
from services.content_artifacts import (
    collect_primary_content_artifacts,
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
    parent_items = await _resolve_parent_items_for_list(db, items)
    out_items = [
        _item_to_out_with_parent(item, parent_item=parent_items.get(item.id))
        for item in items
    ]
    return {
        "items": out_items,
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


@router.get(
    "/types",
    dependencies=[Depends(require_permission("content", "read"))],
)
async def list_content_types(db: DB):
    """Platform-qualified content type registry (DF-T-06-001)."""
    from services.content.registry import get_registry

    registry = get_registry()
    await registry.ensure_fresh(db)
    items = [entry.to_dict() for entry in registry.list()]
    return Response(
        content=json.dumps({"items": items, "total": len(items)}),
        media_type="application/json",
        headers={"Cache-Control": "max-age=300"},
    )


@router.post("/types/refresh", dependencies=[Depends(require_permission("content", "create"))])
async def refresh_content_types(db: DB):
    from services.content.registry import get_registry

    count = await get_registry().refresh(db)
    return {"refreshed": count}


@router.post("/save", dependencies=[Depends(require_permission("content", "create"))])
async def save_content(body: SaveContentBody, db: DB, user: CurrentUser):
    """Save extracted content with deduplication (used by scenarios and MCP)."""
    import json

    from services.content.errors import ContentError, ContentTypeError, NormalizationError, RawDataSizeError
    from services.content_store import save_content_item
    from tenancy.context import set_current_org_id

    if user.org_id:
        set_current_org_id(user.org_id)
    try:
        result = await save_content_item(
            data=body.data,
            collection=body.collection,
            platform=body.platform,
            content_type=body.content_type,
            dedupe_field=body.dedupe_field,
            dedup_action=getattr(body, "dedup_action", "skip") or "skip",
            tags=body.tags,
            device_serial=body.device_serial,
            campaign_id=body.campaign_id,
            execution_id=getattr(body, "execution_id", None),
            user_id=user.id,
            org_id=user.org_id,
            db=db,
        )
        return result
    except ContentTypeError as exc:
        raise HTTPException(422, detail={"error_code": exc.code, **exc.details}) from exc
    except NormalizationError as exc:
        raise HTTPException(422, detail={"error_code": exc.code, **exc.details}) from exc
    except RawDataSizeError as exc:
        raise HTTPException(422, detail={"error_code": exc.code, **exc.details}) from exc
    except ContentError as exc:
        if exc.code == "CONTENT_DEDUP_CONFLICT":
            raise HTTPException(409, detail={"error_code": exc.code, **exc.details}) from exc
        raise HTTPException(422, detail={"error_code": exc.code, **exc.details}) from exc


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
    from api.routes.executions import (
        _extract_step_artifacts,
        _get_or_404,
        _legacy_step_dicts_for_artifacts,
    )
    from db.crud.device import get_device
    from db.crud.execution import list_execution_results

    try:
        await _get_or_404(db, item.execution_id, user)
    except HTTPException:
        return []

    pairs: list[tuple[str, str | None]] = []
    results = await list_execution_results(db, item.execution_id)
    step_dicts = await _legacy_step_dicts_for_artifacts(db, item.execution_id)
    for er in results:
        device = await get_device(db, er.device_id)
        serial = device.serial if device else None
        steps_for_device = step_dicts or ((er.passed_steps or []) + (er.failed_steps or []))
        for step_art in _extract_step_artifacts(
            item.execution_id,
            serial or "unknown",
            steps_for_device,
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
    "/{item_id}/children",
    dependencies=[Depends(require_permission("content", "read"))],
)
async def list_content_children(
    item_id: str,
    db: DB,
    user: CurrentUser,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Comments for a post — matches parent_id hash variants and parser post ids."""
    owner_id = data_owner_user_id(user)
    item = await content_crud.get_content_item(db, item_id, user_id=owner_id)
    if item is None:
        raise HTTPException(404, "Content item not found")
    children, total = await content_crud.query_content_children(
        db,
        item,
        user_id=owner_id,
        limit=limit,
        offset=offset,
    )
    parent_items = await _resolve_parent_items_for_list(db, children)
    out_items = [
        _item_to_out_with_parent(child, parent_item=parent_items.get(child.id))
        for child in children
    ]
    return {
        "items": out_items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


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
    except Exception as exc:
        # Defensive: misconfigured storage URLs must not surface as opaque 500s.
        exc_name = type(exc).__name__
        if exc_name in {"ConnectError", "ConnectTimeout", "ReadTimeout"} or (
            exc.__class__.__module__.startswith("httpx")
            and exc_name.endswith("Error")
        ):
            log.warning(
                "content artifact_download fetch failed item_id=%s artifact_id=%s: %s",
                item_id,
                artifact_id,
                exc,
            )
            raise HTTPException(410, "Artifact expired or unavailable") from exc
        raise
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
    return _item_to_out_with_parent(item, include_raw=include_raw, parent_item=None)


def _item_to_out_with_parent(item, *, include_raw: bool = False, parent_item=None) -> dict:
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
        parent_item_id=parent_item.id if parent_item is not None else None,
        parent_item_hash=parent_item.content_hash if parent_item is not None else None,
        parent_item_author=parent_item.author if parent_item is not None else None,
        parent_item_body=parent_item.body if parent_item is not None else None,
        parent_item_content_type=parent_item.content_type if parent_item is not None else None,
        item_level=int(item.item_level or 0),
    ).model_dump(mode="json", exclude_none=include_raw is False)


def _raw_dict(item) -> dict:
    raw = item.raw_data
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _parent_post_identifiers(item) -> list[tuple[str, str]]:
    raw = _raw_dict(item)
    anchor = raw.get("parent_post_anchor") if isinstance(raw.get("parent_post_anchor"), dict) else {}
    pairs = [
        ("post_key", anchor.get("post_key") or raw.get("parent_post_key")),
        ("_pid", anchor.get("pid") or raw.get("parent_post_id")),
        ("stable_post_id", anchor.get("stable_post_id") or raw.get("parent_stable_post_id")),
        ("fb_post_id", anchor.get("fb_post_id") or raw.get("parent_fb_post_id")),
    ]
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for key, value in pairs:
        text = str(value or "").strip()
        pair = (key, text)
        if not text or pair in seen:
            continue
        seen.add(pair)
        out.append(pair)
    return out


async def _resolve_parent_item(db, item):
    if not (
        item.parent_id
        or int(item.item_level or 0) > 0
        or str(item.content_type or "").endswith("comment")
    ):
        return None

    base_filters = [ContentItem.deleted_at.is_(None)]
    if item.user_id:
        base_filters.append(ContentItem.user_id == item.user_id)
    if item.org_id:
        base_filters.append(ContentItem.org_id == item.org_id)

    async def _fetch(stmt):
        row = await db.execute(stmt.limit(1))
        return row.scalar_one_or_none()

    if item.parent_id:
        same_execution = list(base_filters)
        same_execution.append(ContentItem.content_hash == item.parent_id)
        if item.execution_id:
            same_execution.append(ContentItem.execution_id == item.execution_id)
        parent = await _fetch(select(ContentItem).where(*same_execution))
        if parent is not None:
            return parent
        parent = await _fetch(
            select(ContentItem).where(
                *base_filters,
                ContentItem.content_hash == item.parent_id,
            )
        )
        if parent is not None:
            return parent

    identifiers = _parent_post_identifiers(item)
    post_filters = [
        *base_filters,
        ContentItem.collection == item.collection,
        or_(
            ContentItem.content_type == "fb_post",
            ContentItem.content_type == "fb_group_posts",
            ContentItem.content_type == "post",
            ContentItem.content_type == "group_post",
            ContentItem.content_type.like("%post"),
        ),
    ]
    if identifiers:
        identifier_filters = []
        for key, value in identifiers:
            identifier_filters.append(ContentItem.raw_data[key].as_string() == value)
        anchored_filters = [*post_filters, or_(*identifier_filters)]
        if item.execution_id:
            parent = await _fetch(
                select(ContentItem)
                .where(*anchored_filters, ContentItem.execution_id == item.execution_id)
                .order_by(ContentItem.extracted_at.desc().nullslast(), ContentItem.created_at.desc())
            )
            if parent is not None:
                return parent
        parent = await _fetch(
            select(ContentItem)
            .where(*anchored_filters)
            .order_by(ContentItem.extracted_at.desc().nullslast(), ContentItem.created_at.desc())
        )
        if parent is not None:
            return parent

    return None


async def _resolve_parent_items_for_list(db, items: list[ContentItem]) -> dict[str, ContentItem]:
    comments = [item for item in items if _is_comment_content_item(item)]
    if not comments:
        return {}

    resolved: dict[str, ContentItem] = {}

    parent_hashes = {item.parent_id for item in comments if item.parent_id}
    if parent_hashes:
        direct_rows = (
            await db.execute(
                select(ContentItem).where(
                    ContentItem.deleted_at.is_(None),
                    ContentItem.content_hash.in_(parent_hashes),
                )
            )
        ).scalars().all()
        by_hash: dict[str, list[ContentItem]] = {}
        for parent in direct_rows:
            by_hash.setdefault(parent.content_hash, []).append(parent)

        for item in comments:
            if not item.parent_id:
                continue
            parent = _best_parent_candidate(item, by_hash.get(item.parent_id, []))
            if parent is not None:
                resolved[item.id] = parent

    unresolved = [item for item in comments if item.id not in resolved and item.execution_id]
    if not unresolved:
        return resolved

    executions = {item.execution_id for item in unresolved if item.execution_id}
    collections = {item.collection for item in unresolved if item.collection}
    org_ids = {item.org_id for item in unresolved if item.org_id}
    user_ids = {item.user_id for item in unresolved if item.user_id}

    post_filters = [
        ContentItem.deleted_at.is_(None),
        ContentItem.execution_id.in_(executions),
        ContentItem.collection.in_(collections),
        or_(
            ContentItem.content_type == "fb_post",
            ContentItem.content_type == "fb_group_posts",
            ContentItem.content_type == "post",
            ContentItem.content_type == "group_post",
            ContentItem.content_type.like("%post"),
        ),
    ]
    if org_ids:
        post_filters.append(ContentItem.org_id.in_(org_ids))
    if user_ids:
        post_filters.append(ContentItem.user_id.in_(user_ids))

    posts = (
        await db.execute(
            select(ContentItem)
            .where(*post_filters)
            .order_by(ContentItem.extracted_at.desc().nullslast(), ContentItem.created_at.desc())
        )
    ).scalars().all()

    by_scope: dict[tuple[str | None, str, str | None, str | None], list[ContentItem]] = {}
    for post in posts:
        key = (post.execution_id, post.collection, post.org_id, post.user_id)
        by_scope.setdefault(key, []).append(post)

    for item in unresolved:
        key = (item.execution_id, item.collection, item.org_id, item.user_id)
        parent = _match_parent_by_identifiers(item, by_scope.get(key, []))
        if parent is not None:
            resolved[item.id] = parent

    return resolved


def _match_parent_by_identifiers(item, posts: list[ContentItem]) -> ContentItem | None:
    identifiers = _parent_post_identifiers(item)
    if not identifiers:
        return None
    for post in posts:
        raw = _raw_dict(post)
        for key, value in identifiers:
            if str(raw.get(key) or "").strip() == value:
                return post
    return None


def _best_parent_candidate(item, candidates: list[ContentItem]) -> ContentItem | None:
    if not candidates:
        return None
    same_execution = [p for p in candidates if item.execution_id and p.execution_id == item.execution_id]
    scoped = same_execution or candidates
    for parent in scoped:
        if item.org_id and parent.org_id != item.org_id:
            continue
        if item.user_id and parent.user_id != item.user_id:
            continue
        return parent
    return None


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


def _is_comment_content_item(item) -> bool:
    ct = str(item.content_type or "").lower()
    return int(item.item_level or 0) > 0 or ct.endswith("comment")


async def _collect_all_artifacts(db, item, user: CurrentUser) -> list[dict]:
    """Content detail: only crawl-time screenshot + hierarchy_xml (no execution/parent dupes)."""
    del db, user  # kept for call-site stability
    return collect_primary_content_artifacts(item)


async def _item_detail_out(db, item, user: CurrentUser) -> dict:
    parent_item = await _resolve_parent_item(db, item)
    base = _item_to_out_with_parent(item, include_raw=True, parent_item=parent_item)
    artifacts = [
        ContentArtifactOut(**a) for a in await _collect_all_artifacts(db, item, user)
    ]
    return {
        **base,
        "artifacts": [a.model_dump(mode="json") for a in artifacts],
        "payload": _build_payload(item),
    }
