from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse

from api.auth.rbac import is_superadmin
from api.deps import CurrentUser, DB, require_permission
from api.schemas.platform_app import (
    PlatformAppDownloadOut,
    PlatformAppPublishOut,
    PlatformAppReleaseListOut,
    PlatformAppReleaseOut,
)
from services.platform_app_release import (
    APK_CONTENT_TYPE,
    FACEBOOK_PACKAGE,
    FACEBOOK_PLATFORM,
    PlatformAppReleaseError,
    archive_platform_app_release,
    create_platform_app_release_from_file,
    delete_platform_app_release,
    get_active_platform_app_release,
    get_platform_app_release,
    iter_release_object_bytes,
    list_platform_app_releases,
    publish_platform_app_release,
    release_download_url,
)

router = APIRouter(tags=["platform-apps"])

DOWNLOAD_URL_TTL_SECONDS = 3600


def _require_superadmin(user: CurrentUser) -> None:
    if not is_superadmin(user):
        raise HTTPException(status_code=403, detail={"code": "SUPERADMIN_ONLY"})


def _map_release_error(exc: PlatformAppReleaseError) -> HTTPException:
    return HTTPException(
        status_code=getattr(exc, "status_code", status.HTTP_422_UNPROCESSABLE_ENTITY),
        detail={"code": getattr(exc, "code", "PLATFORM_APP_RELEASE_ERROR"), "message": str(exc)},
    )


def _release_out(row) -> PlatformAppReleaseOut:
    return PlatformAppReleaseOut.model_validate(row)


async def _active_facebook_release_or_404(db: DB):
    row = await get_active_platform_app_release(
        db,
        platform=FACEBOOK_PLATFORM,
        package_name=FACEBOOK_PACKAGE,
    )
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "PLATFORM_APP_RELEASE_NOT_FOUND"})
    return row


@router.get(
    "/admin/platform-apps/facebook/releases",
    response_model=PlatformAppReleaseListOut,
    dependencies=[Depends(require_permission("devices", "manage"))],
)
async def admin_list_facebook_app_releases(
    db: DB,
    user: CurrentUser,
    status_: str | None = Query(None, alias="status", pattern="^(draft|active|archived)$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    _require_superadmin(user)
    rows, total = await list_platform_app_releases(
        db,
        platform=FACEBOOK_PLATFORM,
        status=status_,
        offset=offset,
        limit=limit,
    )
    return PlatformAppReleaseListOut(
        items=[_release_out(row) for row in rows],
        total=total,
        offset=max(0, offset),
        limit=max(1, min(limit, 100)),
    )


@router.post(
    "/admin/platform-apps/facebook/releases",
    response_model=PlatformAppReleaseOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("devices", "manage"))],
)
async def admin_upload_facebook_app_release(
    db: DB,
    user: CurrentUser,
    file: UploadFile = File(...),
    notes: str | None = Form(default=None),
):
    _require_superadmin(user)
    try:
        row = await create_platform_app_release_from_file(
            db,
            platform=FACEBOOK_PLATFORM,
            file_obj=file.file,
            filename=file.filename,
            uploaded_by_user_id=user.id,
            notes=notes,
        )
    except PlatformAppReleaseError as exc:
        raise _map_release_error(exc) from exc
    await db.commit()
    await db.refresh(row)
    return _release_out(row)


@router.post(
    "/admin/platform-apps/facebook/releases/{release_id}/publish",
    response_model=PlatformAppPublishOut,
    dependencies=[Depends(require_permission("devices", "manage"))],
)
async def admin_publish_facebook_app_release(release_id: str, db: DB, user: CurrentUser):
    _require_superadmin(user)
    try:
        row = await publish_platform_app_release(db, release_id=release_id)
    except PlatformAppReleaseError as exc:
        raise _map_release_error(exc) from exc
    await db.commit()
    await db.refresh(row)
    return PlatformAppPublishOut(release=_release_out(row))


@router.post(
    "/admin/platform-apps/facebook/releases/{release_id}/archive",
    response_model=PlatformAppPublishOut,
    dependencies=[Depends(require_permission("devices", "manage"))],
)
async def admin_archive_facebook_app_release(release_id: str, db: DB, user: CurrentUser):
    _require_superadmin(user)
    try:
        row = await archive_platform_app_release(db, release_id=release_id)
    except PlatformAppReleaseError as exc:
        raise _map_release_error(exc) from exc
    await db.commit()
    await db.refresh(row)
    return PlatformAppPublishOut(release=_release_out(row))


@router.delete(
    "/admin/platform-apps/facebook/releases/{release_id}",
    response_model=PlatformAppPublishOut,
    dependencies=[Depends(require_permission("devices", "manage"))],
)
async def admin_delete_facebook_app_release(release_id: str, db: DB, user: CurrentUser):
    _require_superadmin(user)
    try:
        row = await delete_platform_app_release(db, release_id=release_id)
    except PlatformAppReleaseError as exc:
        raise _map_release_error(exc) from exc
    release = _release_out(row)
    await db.commit()
    return PlatformAppPublishOut(release=release)


@router.get(
    "/platform-apps/facebook/current",
    response_model=PlatformAppReleaseOut,
    dependencies=[Depends(require_permission("devices", "read"))],
)
async def get_current_facebook_app_release(db: DB):
    row = await _active_facebook_release_or_404(db)
    return _release_out(row)


@router.get(
    "/platform-apps/facebook/current/download-url",
    response_model=PlatformAppDownloadOut,
    dependencies=[Depends(require_permission("devices", "read"))],
)
async def get_current_facebook_app_download_url(db: DB):
    row = await _active_facebook_release_or_404(db)
    download_url = release_download_url(row, expires_seconds=DOWNLOAD_URL_TTL_SECONDS)
    if not download_url:
        raise HTTPException(status_code=503, detail={"code": "OBJECT_STORAGE_UNAVAILABLE"})
    return PlatformAppDownloadOut(
        release=_release_out(row),
        download_url=download_url,
        expires_seconds=DOWNLOAD_URL_TTL_SECONDS,
    )


@router.get(
    "/platform-apps/facebook/current/download",
    dependencies=[Depends(require_permission("devices", "read"))],
)
async def download_current_facebook_app(db: DB):
    row = await _active_facebook_release_or_404(db)
    stream = await asyncio.to_thread(iter_release_object_bytes, row)
    if stream is None:
        raise HTTPException(status_code=404, detail={"code": "PLATFORM_APP_RELEASE_OBJECT_NOT_FOUND"})
    filename = f"facebook-{row.version_name}-{row.sha256[:12]}.apk"
    return StreamingResponse(
        stream,
        media_type=APK_CONTENT_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/admin/platform-apps/facebook/releases/{release_id}/download-url",
    response_model=PlatformAppDownloadOut,
    dependencies=[Depends(require_permission("devices", "manage"))],
)
async def admin_get_facebook_app_release_download_url(release_id: str, db: DB, user: CurrentUser):
    _require_superadmin(user)
    row = await get_platform_app_release(db, release_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "PLATFORM_APP_RELEASE_NOT_FOUND"})
    download_url = release_download_url(row, expires_seconds=DOWNLOAD_URL_TTL_SECONDS)
    if not download_url:
        raise HTTPException(status_code=503, detail={"code": "OBJECT_STORAGE_UNAVAILABLE"})
    return PlatformAppDownloadOut(
        release=_release_out(row),
        download_url=download_url,
        expires_seconds=DOWNLOAD_URL_TTL_SECONDS,
    )
