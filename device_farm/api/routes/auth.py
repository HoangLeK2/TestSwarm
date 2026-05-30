"""
api/routes/auth.py

POST /api/auth/register  — tạo tài khoản mới
POST /api/auth/login     — đăng nhập, nhận JWT
GET  /api/auth/me        — thông tin user hiện tại
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from jose import jwt
from passlib.context import CryptContext

from api.deps import CurrentUser, DB, require_permission
from core.env import access_expire_hours, refresh_expire_days
from core.security import jwt_algorithm, jwt_secret_key
from api.schemas.auth import LoginRequest, RefreshRequest, RegisterRequest, TokenResponse, UserOut
from db import crud as repo
from services.organization_invite import accept_organization_invitation

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger(__name__)

_pwd = CryptContext(schemes=["bcrypt_sha256"], deprecated="auto")
ACCESS_EXPIRE_HOURS = access_expire_hours()
REFRESH_EXPIRE_DAYS = refresh_expire_days()


def _make_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_EXPIRE_HOURS)
    return jwt.encode(
        {"sub": user_id, "type": "access", "exp": expire},
        jwt_secret_key(),
        algorithm=jwt_algorithm(),
    )


def _make_refresh_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_EXPIRE_DAYS)
    return jwt.encode(
        {"sub": user_id, "type": "refresh", "exp": expire},
        jwt_secret_key(),
        algorithm=jwt_algorithm(),
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: DB):
    existing = await repo.get_user_by_email(db, body.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = await repo.create_user_with_default_org(
        db, body.email, body.name, _pwd.hash(body.password), "operator"
    )
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
        id=user.id, email=user.email, name=user.name,
        role=user.role, api_key=user.api_key, orgRole=org_role,
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: DB):
    user = await repo.get_user_by_email(db, body.email)
    if not user or not _pwd.verify(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    # Block login when the current org is disabled.
    try:
        org = await repo.get_current_org_for_user(db, user.id)
        if org is not None and getattr(org, "status", "active") == "disabled":
            raise HTTPException(status_code=403, detail={"code": "ORG_DISABLED"})
    except HTTPException:
        raise
    except Exception:
        # If org lookup fails, do not block login (keeps legacy behavior).
        pass
    return TokenResponse(
        access_token=_make_access_token(user.id),
        refresh_token=_make_refresh_token(user.id),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: DB):
    try:
        payload = jwt.decode(
            body.refresh_token, jwt_secret_key(), algorithms=[jwt_algorithm()]
        )
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")
    user = await repo.get_user(db, payload["sub"])
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or disabled")
    return TokenResponse(
        access_token=_make_access_token(user.id),
        refresh_token=_make_refresh_token(user.id),
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
        id=user.id, email=user.email, name=user.name,
        role=user.role, api_key=user.api_key, orgRole=org_role,
    )
