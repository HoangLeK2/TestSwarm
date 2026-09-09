from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import os
import time
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse

from api.auth.rbac import is_superadmin
from api.deps import CurrentUser, DB, require_permission
from api.org_scope import device_visible_to_user
from api.schemas.platform_app import (
    PlatformAppDownloadOut,
    PlatformAppInstallOut,
    PlatformAppInstallRequest,
    PlatformAppPublishOut,
    PlatformAppReleaseListOut,
    PlatformAppReleaseOut,
)
from db import crud as repo
from core.security import jwt_secret_key
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
INSTALL_URL_TTL_SECONDS = 3600
INSTALL_DOWNLOAD_TOKEN_TTL_SECONDS = 900


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


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _sign_install_download_token(row, *, expires_at: int) -> str:
    payload = f"{row.id}.{row.sha256}.{int(expires_at)}"
    signature = _b64url(hmac.new(jwt_secret_key().encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def _verify_install_download_token(token: str) -> tuple[str, str]:
    parts = (token or "").split(".")
    if len(parts) != 4:
        raise HTTPException(status_code=403, detail={"code": "INVALID_INSTALL_DOWNLOAD_TOKEN"})
    release_id, sha256, expires_raw, signature = parts
    try:
        expires_at = int(expires_raw)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail={"code": "INVALID_INSTALL_DOWNLOAD_TOKEN"}) from exc
    if expires_at < int(time.time()):
        raise HTTPException(status_code=403, detail={"code": "INSTALL_DOWNLOAD_TOKEN_EXPIRED"})
    payload = f"{release_id}.{sha256}.{expires_at}"
    expected = _b64url(hmac.new(jwt_secret_key().encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest())
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=403, detail={"code": "INVALID_INSTALL_DOWNLOAD_TOKEN"})
    return release_id, sha256


def _install_download_base_url(request: Request) -> str:
    configured = (os.environ.get("DEVICE_FARM_PLATFORM_APP_INSTALL_BASE_URL") or "").strip().rstrip("/")
    if configured:
        return configured
    base = str(request.base_url).rstrip("/")
    return base.replace("://localhost:", "://127.0.0.1:")


def _install_download_url(request: Request, row) -> str:
    token = _sign_install_download_token(
        row,
        expires_at=int(time.time()) + INSTALL_DOWNLOAD_TOKEN_TTL_SECONDS,
    )
    return f"{_install_download_base_url(request)}/api/platform-apps/facebook/install-download?token={quote(token)}"


async def _install_release_apk(runtime_device, row, download_url: str | None, *, timeout_seconds: float) -> None:
    del row
    if not download_url:
        raise RuntimeError("install download URL unavailable")
    await asyncio.to_thread(runtime_device.install, download_url, timeout=timeout_seconds)


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


@router.post(
    "/platform-apps/facebook/current/install",
    response_model=PlatformAppInstallOut,
    dependencies=[Depends(require_permission("devices", "execute"))],
)
async def install_current_facebook_app(
    body: PlatformAppInstallRequest,
    request: Request,
    db: DB,
    user: CurrentUser,
):
    serial = body.serial.strip()
    if not serial:
        raise HTTPException(status_code=400, detail={"code": "DEVICE_SERIAL_REQUIRED"})
    manager = getattr(request.app.state, "manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail={"code": "DEVICE_MANAGER_UNAVAILABLE"})

    db_device = await repo.get_device_by_serial(db, serial)
    if db_device is None or not await device_visible_to_user(db, user, db_device):
        raise HTTPException(status_code=404, detail={"code": "DEVICE_NOT_FOUND"})
    runtime_device = manager.get_device(db_device.serial)
    if runtime_device is None:
        raise HTTPException(status_code=404, detail={"code": "DEVICE_NOT_CONNECTED"})

    row = await _active_facebook_release_or_404(db)
    download_url = _install_download_url(request, row)

    timeout_seconds = min(600.0, max(10.0, float(body.timeout_seconds or 600)))
    release = _release_out(row)
    await db.commit()
    try:
        await _install_release_apk(
            runtime_device,
            row,
            download_url,
            timeout_seconds=timeout_seconds,
        )
        package_path = await asyncio.to_thread(
            runtime_device.shell_sync,
            f"pm path {FACEBOOK_PACKAGE}",
            10.0,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "PLATFORM_APP_INSTALL_FAILED", "message": str(exc)},
        ) from exc
    if not str(package_path or "").strip().startswith("package:"):
        raise HTTPException(
            status_code=502,
            detail={
                "code": "PLATFORM_APP_INSTALL_VERIFY_FAILED",
                "message": f"{FACEBOOK_PACKAGE} not found after install",
            },
        )
    return PlatformAppInstallOut(ok=True, serial=db_device.serial, release=release)


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


@router.get("/platform-apps/facebook/install-download")
async def install_download_facebook_app(token: str, db: DB):
    release_id, sha256 = _verify_install_download_token(token)
    row = await get_platform_app_release(db, release_id)
    if row is None or row.platform != FACEBOOK_PLATFORM or row.package_name != FACEBOOK_PACKAGE or row.sha256 != sha256 or row.status != "active":
        raise HTTPException(status_code=404, detail={"code": "PLATFORM_APP_RELEASE_NOT_FOUND"})
    stream = await asyncio.to_thread(iter_release_object_bytes, row)
    if stream is None:
        raise HTTPException(status_code=404, detail={"code": "PLATFORM_APP_RELEASE_OBJECT_NOT_FOUND"})
    filename = f"facebook-{row.version_name}-{row.sha256[:12]}.apk"
    return StreamingResponse(
        stream,
        media_type=APK_CONTENT_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, max-age=900",
        },
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
