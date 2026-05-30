"""Device reserve session HTTP routes (DF-T-02-003 / DF-T-02-004)."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from api.deps import CurrentUser, DB, require_permission
from api.schemas.device_session import (
    DeviceClaimBody,
    DeviceClaimOut,
    DeviceReleaseBody,
    DeviceReserveSessionOut,
    PairRegistryBody,
    PairRegistryOut,
    UnpairDeviceOut,
)
from db.crud.device_state import get_device_state
from db.models.enums import DeviceFsmState
from services.device_registry.pairing import pair_device, unpair_device
from services.device_reserve.exceptions import (
    DeviceBusyError,
    DeviceInSessionError,
    DeviceSessionError,
    NotSessionOwnerError,
    SessionNotFoundError,
    TtlOutOfRangeError,
)
from services.device_reserve.service import (
    claim_device_session,
    get_active_session_view,
    heartbeat_device_session,
    release_device_session,
)
from services.device_state.exceptions import DeviceNotAvailableError, DeviceStateError

router = APIRouter(tags=["devices"])


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    return ip, ua


def _is_device_admin(user) -> bool:
    from api.auth.rbac import build_enforcer_for_user, permission_domain

    if getattr(user, "org_role", None) == "owner":
        return True
    domain = permission_domain(user)
    enforcer = build_enforcer_for_user(user, domain=domain)
    return bool(enforcer.enforce(str(user.id), domain, "devices", "manage"))


def _session_out(view) -> DeviceReserveSessionOut:
    return DeviceReserveSessionOut(
        session_id=view.session_id,
        device_id=view.device_id,
        owner_type=view.owner_type,
        owner_id=view.owner_id,
        claimed_at=datetime.fromisoformat(view.claimed_at.replace("Z", "+00:00")),
        last_heartbeat=datetime.fromisoformat(view.last_heartbeat.replace("Z", "+00:00")),
        ttl_sec=view.ttl_sec,
        ctx=view.ctx,
    )


def _map_session_error(exc: Exception) -> HTTPException:
    if isinstance(exc, DeviceBusyError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": exc.code,
                "current_session_id": exc.current_session_id,
                "owner_id": exc.owner_id,
                "owner_type": exc.owner_type,
            },
        )
    if isinstance(exc, DeviceNotAvailableError):
        state = "unknown"
        if "state=" in str(exc):
            state = str(exc).split("state=")[-1].rstrip(")")
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "DEVICE_NOT_AVAILABLE", "state": state},
        )
    if isinstance(exc, TtlOutOfRangeError):
        return HTTPException(status_code=400, detail={"code": exc.code})
    if isinstance(exc, NotSessionOwnerError):
        return HTTPException(status_code=403, detail={"code": exc.code})
    if isinstance(exc, SessionNotFoundError):
        return HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    if isinstance(exc, DeviceInSessionError):
        return HTTPException(
            status_code=409,
            detail={
                "code": exc.code,
                "session_id": exc.session_id,
            },
        )
    if isinstance(exc, DeviceStateError):
        code = getattr(exc, "code", "DEVICE_STATE_ERROR")
        status_code = 404 if code == "NOT_FOUND" else 409
        return HTTPException(status_code=status_code, detail={"code": code})
    if isinstance(exc, DeviceSessionError):
        return HTTPException(status_code=400, detail={"code": exc.code, "message": str(exc)})
    return HTTPException(status_code=500, detail={"code": "INTERNAL_ERROR"})


@router.post(
    "/devices/registry/pair",
    response_model=PairRegistryOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("devices", "create"))],
)
async def registry_pair_device(
    body: PairRegistryBody, request: Request, db: DB, user: CurrentUser
):
    ip, ua = _client_meta(request)
    try:
        result = await pair_device(
            db,
            org_id=getattr(user, "org_id", None),
            actor_user_id=user.id,
            device_serial=body.device_serial,
            adb_serial=body.adb_serial,
            relay_serial=body.relay_serial,
            name=body.name,
            model=body.model,
            android_version=body.android_version,
            ip_address=ip,
            user_agent=ua,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _map_session_error(exc) from exc

    device = result.device
    out = PairRegistryOut(
        db_id=device.id,
        device_serial=device.device_serial or device.serial,
        adb_serial=device.adb_serial,
        relay_serial=device.relay_serial,
        status=device.status,
        created=result.created,
        device_key=result.device_key_plaintext,
        device_key_disclaimer=(
            "device_key is returned only once; store it securely"
            if result.device_key_plaintext
            else None
        ),
    )
    if not result.created:
        return JSONResponse(status_code=status.HTTP_200_OK, content=out.model_dump(mode="json"))
    return out


@router.post(
    "/devices/{device_id}/unpair",
    response_model=UnpairDeviceOut,
    dependencies=[Depends(require_permission("devices", "delete"))],
)
async def registry_unpair_device(
    device_id: str, request: Request, db: DB, user: CurrentUser
):
    ip, ua = _client_meta(request)
    try:
        device = await unpair_device(
            db,
            device_id=device_id,
            org_id=getattr(user, "org_id", None),
            actor_user_id=user.id,
            ip_address=ip,
            user_agent=ua,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _map_session_error(exc) from exc
    return UnpairDeviceOut(
        db_id=device.id,
        status=device.status,
        unpaired_at=device.unpaired_at,
    )


@router.post(
    "/devices/{device_id}/claim",
    response_model=DeviceClaimOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("devices", "execute"))],
)
async def claim_device(
    device_id: str, body: DeviceClaimBody, request: Request, db: DB, user: CurrentUser
):
    ip, ua = _client_meta(request)
    owner_id = body.owner_id.strip() or user.id
    try:
        view = await claim_device_session(
            db,
            device_id=device_id,
            org_id=getattr(user, "org_id", None),
            actor_user_id=user.id,
            owner_type=body.owner_type,
            owner_id=owner_id,
            ttl_sec=body.ttl_sec,
            ctx=body.ctx,
            ip_address=ip,
            user_agent=ua,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _map_session_error(exc) from exc
    return DeviceClaimOut(**_session_out(view).model_dump())


@router.post(
    "/devices/{device_id}/release",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_permission("devices", "execute"))],
)
async def release_device(
    device_id: str, body: DeviceReleaseBody, request: Request, db: DB, user: CurrentUser
):
    ip, ua = _client_meta(request)
    try:
        await release_device_session(
            db,
            device_id=device_id,
            session_id=body.session_id,
            org_id=getattr(user, "org_id", None),
            actor_user_id=user.id,
            is_admin=_is_device_admin(user),
            ip_address=ip,
            user_agent=ua,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _map_session_error(exc) from exc
    return {"ok": True}


@router.get(
    "/devices/{device_id}/session",
    responses={
        200: {"model": DeviceReserveSessionOut},
        204: {"description": "No active session"},
    },
    dependencies=[Depends(require_permission("devices", "read"))],
)
async def get_device_active_session(device_id: str, db: DB, user: CurrentUser):
    from db import crud as repo

    device = await repo.get_device(db, device_id)
    if not device or device.org_id != getattr(user, "org_id", None):
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    view = await get_active_session_view(db, device_id)
    if view is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return _session_out(view)


@router.post(
    "/sessions/{session_id}/heartbeat",
    response_model=DeviceReserveSessionOut,
    dependencies=[Depends(require_permission("devices", "execute"))],
)
async def heartbeat_session(session_id: str, db: DB, user: CurrentUser):
    try:
        view = await heartbeat_device_session(
            db,
            session_id=session_id,
            org_id=getattr(user, "org_id", None),
            actor_user_id=user.id,
            is_admin=_is_device_admin(user),
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _map_session_error(exc) from exc
    return _session_out(view)
