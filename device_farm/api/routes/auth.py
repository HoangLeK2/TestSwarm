"""
api/routes/auth.py

POST /api/auth/register  — tạo tài khoản mới
POST /api/auth/login     — đăng nhập, nhận JWT
GET  /api/auth/me        — thông tin user hiện tại
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, status
from jose import jwt
from passlib.context import CryptContext

from api.deps import CurrentUser, DB
from core.env import access_expire_hours, refresh_expire_days
from core.security import jwt_algorithm, jwt_secret_key
from api.schemas.auth import LoginRequest, RefreshRequest, RegisterRequest, TokenResponse, UserOut
from db import crud as repo

router = APIRouter(prefix="/auth", tags=["auth"])

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
    user = await repo.create_user(
        db, body.email, body.name, _pwd.hash(body.password), body.role
    )
    await repo.create_personal_org_for_user(db, user)
    return UserOut(
        id=user.id, email=user.email, name=user.name,
        role=user.role, api_key=user.api_key,
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: DB):
    user = await repo.get_user_by_email(db, body.email)
    if not user or not _pwd.verify(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
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


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser):
    return UserOut(
        id=user.id, email=user.email, name=user.name,
        role=user.role, api_key=user.api_key,
    )
