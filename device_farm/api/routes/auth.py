"""
api/routes/auth.py

POST /api/auth/register  — tạo tài khoản mới
POST /api/auth/login     — đăng nhập, nhận JWT + refresh (opaque, stored hashed)
POST /api/auth/refresh   — rotate refresh token
POST /api/auth/logout    — revoke refresh token
GET  /api/auth/me        — thông tin user hiện tại
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status

from api.deps import CurrentUser, DB, require_permission
from api.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserOut,
)
from rate_limit import rate_limit
from auth.jwt_service import issue_access_token
from auth.lockout import (
    admin_unlock,
    clear_lockout_state,
    is_account_locked,
    lock_expires_at,
    record_failed_login,
)
from auth.password_policy import record_password_history, validate_password_strength
from auth.password_service import hash_password, verify_password, verify_with_timing_safe
from auth.refresh_token_service import (
    RefreshTokenError,
    issue_refresh_token,
    revoke_refresh_token,
    rotate_refresh_token,
)
from auth.session_service import device_fingerprint
from db import crud as repo
from services.organization_invite import accept_organization_invitation
from services.security_audit import emit_security_event

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger(__name__)


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    return ip, ua


def _roles_for_user(user, org_role: str | None) -> list[str]:
    roles: list[str] = []
    if org_role:
        roles.append(org_role)
    app_role = getattr(user, "role", None)
    if app_role and app_role not in roles:
        roles.append(str(app_role))
    return roles



@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: DB):
    violations = validate_password_strength(body.password)
    if violations:
        raise HTTPException(
            status_code=400,
            detail={"code": "WEAK_PASSWORD", "violations": violations},
        )
    existing = await repo.get_user_by_email(db, body.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    hashed = hash_password(body.password)
    user = await repo.create_user_with_default_org(
        db, body.email, body.name, hashed, "operator"
    )
    await record_password_history(db, user.id, hashed)
    invite_token = (body.inviteToken or "").strip()
    if invite_token:
        try:
            await accept_organization_invitation(db, token=invite_token, user=user)
        except ValueError as exc:
            log.warning(
                "register invite accept failed email=%s code=%s",
                body.email,
                exc,
            )

    org_role = await repo.get_organization_role_for_user(
        db, user.id, getattr(user, "org_id", None)
    )
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        api_key=user.api_key,
        orgRole=org_role,
    )


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(rate_limit("30/min", key="ip"))])
async def login(body: LoginRequest, request: Request, db: DB):
    ip, ua = _client_meta(request)
    user = await repo.get_user_by_email(db, body.email)
    password_ok = verify_with_timing_safe(
        body.password,
        user.hashed_password if user else None,
    )

    if not password_ok:
        if user is not None and user.is_active:
            org_id = getattr(user, "org_id", None)
            locked_now, skip_admin = await record_failed_login(db, user, org_id)
            if skip_admin:
                await emit_security_event(
                    db,
                    action="account.lock_skipped_last_admin",
                    user_id=user.id,
                    org_id=org_id,
                    entity_type="user",
                    entity_id=user.id,
                    ip_address=ip,
                    user_agent=ua,
                )
            elif locked_now:
                await emit_security_event(
                    db,
                    action="account.locked",
                    user_id=user.id,
                    org_id=org_id,
                    entity_type="user",
                    entity_id=user.id,
                    ip_address=ip,
                    user_agent=ua,
                )
        await emit_security_event(
            db,
            action="auth.login.failed",
            user_id=user.id if user else None,
            org_id=getattr(user, "org_id", None) if user else None,
            entity_type="user",
            entity_id=user.id if user else None,
            ip_address=ip,
            user_agent=ua,
            details={"email": (body.email or "").strip().lower()},
        )
        await db.commit()
        raise HTTPException(status_code=401, detail={"code": "INVALID_CREDENTIALS"})

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")

    org_id = getattr(user, "org_id", None)
    org_role = await repo.get_organization_role_for_user(db, user.id, org_id)

    if is_account_locked(user):
        unlock_at = lock_expires_at(user)
        raise HTTPException(
            status_code=423,
            detail={
                "code": "ACCOUNT_LOCKED",
                "unlock_at": unlock_at.isoformat() if unlock_at else None,
            },
        )

    try:
        org = await repo.get_current_org_for_user(db, user.id)
        if org is not None and getattr(org, "status", "active") == "disabled":
            await emit_security_event(
                db,
                action="auth.login.org_disabled",
                user_id=user.id,
                org_id=org.id,
                entity_type="organization",
                entity_id=org.id,
                ip_address=ip,
                user_agent=ua,
            )
            raise HTTPException(status_code=403, detail={"code": "ORG_DISABLED"})
    except HTTPException:
        raise
    except Exception:
        pass

    auto_unlocked = await clear_lockout_state(db, user)
    if auto_unlocked:
        await emit_security_event(
            db,
            action="account.auto_unlocked",
            user_id=user.id,
            org_id=org_id,
            entity_type="user",
            entity_id=user.id,
            ip_address=ip,
            user_agent=ua,
        )

    fp = device_fingerprint(user_agent=ua, ip=ip)
    refresh, session_id = await issue_refresh_token(
        db,
        user.id,
        device_fingerprint=fp,
        last_ip=ip,
        user_agent=ua,
    )
    access, expires_in, jti = issue_access_token(
        user_id=user.id,
        org_id=org_id,
        roles=_roles_for_user(user, org_role),
        session_id=session_id,
    )
    await emit_security_event(
        db,
        action="auth.login.success",
        user_id=user.id,
        org_id=org_id,
        entity_type="user",
        entity_id=user.id,
        ip_address=ip,
        user_agent=ua,
        details={"jti": jti},
    )
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=expires_in,
        session_id=session_id,
    )


@router.post("/refresh", response_model=TokenResponse, dependencies=[Depends(rate_limit("60/min", key="ip"))])
async def refresh(body: RefreshRequest, request: Request, db: DB):
    ip, ua = _client_meta(request)
    try:
        user, new_refresh, session_id = await rotate_refresh_token(
            db,
            body.refresh_token,
            last_ip=ip,
            user_agent=ua,
        )
    except RefreshTokenError as exc:
        if exc.code == "REFRESH_REVOKED":
            await emit_security_event(
                db,
                action="auth.refresh.replay_attempt",
                ip_address=ip,
                user_agent=ua,
            )
            raise HTTPException(status_code=401, detail={"code": "REFRESH_REVOKED"})
        raise HTTPException(status_code=401, detail={"code": "INVALID_REFRESH"})

    org_id = getattr(user, "org_id", None)
    org_role = await repo.get_organization_role_for_user(db, user.id, org_id)
    access, expires_in, jti = issue_access_token(
        user_id=user.id,
        org_id=org_id,
        roles=_roles_for_user(user, org_role),
        session_id=session_id,
    )
    await emit_security_event(
        db,
        action="auth.refresh",
        user_id=user.id,
        org_id=org_id,
        entity_type="user",
        entity_id=user.id,
        ip_address=ip,
        user_agent=ua,
        details={"jti": jti},
    )
    return TokenResponse(
        access_token=access,
        refresh_token=new_refresh,
        expires_in=expires_in,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_permission("me", "read"))])
async def logout(body: LogoutRequest, request: Request, db: DB, user: CurrentUser):
    ip, ua = _client_meta(request)
    if body.refresh_token:
        await revoke_refresh_token(db, body.refresh_token)
    await emit_security_event(
        db,
        action="auth.logout",
        user_id=user.id,
        org_id=getattr(user, "org_id", None),
        entity_type="user",
        entity_id=user.id,
        ip_address=ip,
        user_agent=ua,
    )


@router.get(
    "/me",
    response_model=UserOut,
    dependencies=[Depends(require_permission("me", "read"))],
)
async def me(db: DB, user: CurrentUser):
    org_role = await repo.get_organization_role_for_user(
        db, user.id, getattr(user, "org_id", None)
    )
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        api_key=user.api_key,
        orgRole=org_role,
        defaultOrgId=getattr(user, "default_org_id", None),
    )
