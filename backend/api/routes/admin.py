"""Admin-only routes (DF-T-01-003)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from api.deps import CurrentUser, DB, require_permission
from api.schemas.device_override import (
    AdminForceReleaseBody,
    AdminOverrideOut,
    AdminResetStateBody,
)
from api.schemas.organization import OrganizationMemberOut
from api.schemas.reconnect_policy import ReconnectPolicyOut, ReconnectPolicyUpdate
from db import crud as repo
from services.device_override.service import AdminOverrideError, admin_force_release_device, admin_reset_device_state
from services.device_state.exceptions import IllegalDeviceTransitionError
from services.reconnect_policy.service import (
    ReconnectPolicyValidationError,
    get_org_reconnect_policy,
    update_org_reconnect_policy,
)
from services.security_audit import emit_security_event

router = APIRouter(prefix="/admin", tags=["admin"])


async def _current_org_id(db: DB, user: CurrentUser) -> str:
    org_id = getattr(user, "org_id", None)
    if not org_id:
        org = await repo.get_current_org_for_user(db, user.id)
        org_id = org.id if org else None
    if not org_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    return str(org_id)


def _member_out(member, user) -> OrganizationMemberOut:
    return OrganizationMemberOut(
        id=member.id,
        userId=user.id,
        email=user.email,
        name=user.name,
        role=member.role,
        created_at=member.created_at,
    )


def _override_out(result) -> AdminOverrideOut:
    return AdminOverrideOut(
        device_id=result.device_id,
        from_state=result.from_state,
        to_state=result.to_state,
        old_owner_type=result.old_owner_type,
        old_owner_id=result.old_owner_id,
        session_id=result.session_id,
        reason=result.reason,
        actor=result.actor,
    )


def _map_override_error(exc: Exception) -> HTTPException:
    if isinstance(exc, AdminOverrideError):
        code = getattr(exc, "code", "DEVICE_STATE_ERROR")
        status_code = status.HTTP_404_NOT_FOUND if code == "NOT_FOUND" else status.HTTP_422_UNPROCESSABLE_ENTITY
        if code == "REASON_REQUIRED":
            status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        if code == "INVALID_TRANSITION":
            status_code = status.HTTP_409_CONFLICT
        return HTTPException(status_code=status_code, detail={"code": code, "message": str(exc)})
    if isinstance(exc, IllegalDeviceTransitionError):
        return HTTPException(status_code=409, detail={"code": "ILLEGAL_TRANSITION", "message": str(exc)})
    raise exc


@router.get(
    "/members",
    response_model=list[OrganizationMemberOut],
    dependencies=[Depends(require_permission("organizations", "manage"))],
)
async def admin_list_members(request: Request, db: DB, user: CurrentUser):
    org_id = await _current_org_id(db, user)
    rows = await repo.list_organization_members(db, org_id)
    await emit_security_event(
        db,
        action="admin.access",
        user_id=user.id,
        org_id=org_id,
        entity_type="route",
        entity_id="admin.members",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        details={"path": request.url.path},
    )
    return [_member_out(member, u) for member, u in rows]


@router.get(
    "/reconnect-policy",
    response_model=ReconnectPolicyOut,
    dependencies=[Depends(require_permission("devices", "manage"))],
)
async def get_reconnect_policy(request: Request, response: Response, db: DB, user: CurrentUser):
    org_id = await _current_org_id(db, user)
    view = await get_org_reconnect_policy(db, org_id)
    response.headers["X-Policy-Source"] = view.source
    return ReconnectPolicyOut(**view.to_dict())


@router.put(
    "/reconnect-policy",
    response_model=ReconnectPolicyOut,
    dependencies=[Depends(require_permission("devices", "manage"))],
)
async def put_reconnect_policy(
    body: ReconnectPolicyUpdate,
    request: Request,
    db: DB,
    user: CurrentUser,
):
    org_id = await _current_org_id(db, user)
    try:
        previous = await get_org_reconnect_policy(db, org_id)
        view = await update_org_reconnect_policy(
            db,
            org_id=org_id,
            interval_base_ms=body.interval_base_ms,
            max_interval_ms=body.max_interval_ms,
            max_attempts=body.max_attempts,
            jitter_factor=body.jitter_factor,
            updated_by=user.id,
        )
        await emit_security_event(
            db,
            action="reconnect_policy.updated",
            user_id=user.id,
            org_id=org_id,
            entity_type="reconnect_policy",
            entity_id=org_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            details={"old": previous.to_dict(), "new": view.to_dict()},
        )
        await db.commit()
    except ReconnectPolicyValidationError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    return ReconnectPolicyOut(**view.to_dict())


@router.post(
    "/devices/{device_id}/force-release",
    response_model=AdminOverrideOut,
    dependencies=[Depends(require_permission("devices", "manage"))],
)
async def admin_force_release(
    device_id: str,
    body: AdminForceReleaseBody,
    request: Request,
    db: DB,
    user: CurrentUser,
):
    org_id = await _current_org_id(db, user)
    try:
        result = await admin_force_release_device(
            db,
            device_id=device_id,
            org_id=org_id,
            actor_user_id=user.id,
            reason=body.reason,
            session_id=body.session_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _map_override_error(exc) from exc
    return _override_out(result)


@router.post(
    "/devices/{device_id}/reset-state",
    response_model=AdminOverrideOut,
    dependencies=[Depends(require_permission("devices", "manage"))],
)
async def admin_reset_state(
    device_id: str,
    body: AdminResetStateBody,
    request: Request,
    db: DB,
    user: CurrentUser,
):
    org_id = await _current_org_id(db, user)
    try:
        result = await admin_reset_device_state(
            db,
            device_id=device_id,
            org_id=org_id,
            actor_user_id=user.id,
            reason=body.reason,
            target_state=body.target_state,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _map_override_error(exc) from exc
    return _override_out(result)
