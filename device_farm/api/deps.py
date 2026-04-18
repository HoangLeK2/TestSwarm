from __future__ import annotations

import os
import secrets
from typing import Annotated, AsyncGenerator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import jwt_algorithm, jwt_secret_key
from db.database import AsyncSessionLocal
from db.models import User
from db import crud as repo

_bearer = HTTPBearer(auto_error=False)


async def _get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


DB = Annotated[AsyncSession, Depends(_get_db)]


def _decode_token(token: str) -> str:
    try:
        payload = jwt.decode(token, jwt_secret_key(), algorithms=[jwt_algorithm()])
        user_id: str | None = payload.get("sub")
        token_type: str | None = payload.get("type")
        if not user_id:
            raise ValueError("missing sub")
        # Reject refresh tokens being used as access tokens
        if token_type == "refresh":
            raise ValueError("refresh token not allowed here")
        return user_id
    except (JWTError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )


async def _get_current_user(
    db: DB,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> User:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    user_id = _decode_token(credentials.credentials)
    user = await repo.get_user(db, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


async def _get_current_admin(user: User = Depends(_get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return user


CurrentUser = Annotated[User, Depends(_get_current_user)]
AdminUser = Annotated[User, Depends(_get_current_admin)]


def make_device_auth_dependency(db_enabled: bool):
    """
    Return a FastAPI dependency that enforces JWT authentication for device-control
    routes when DB/multi-user mode is active.

    In lab mode (db_enabled=False) the dependency is a no-op so existing setups
    without a database continue to work unchanged.
    """
    if not db_enabled:
        fallback_key = os.environ.get("DEVICE_CONTROL_API_KEY", "").strip()
        env_name = os.environ.get("DEVICE_FARM_ENV", "").strip().lower()
        is_prod_like = env_name in {"prod", "production", "staging"}
        if is_prod_like and not fallback_key:
            raise RuntimeError(
                "DEVICE_CONTROL_API_KEY is required when database is disabled in production/staging."
            )

        if not fallback_key:
            async def _no_auth() -> None:
                return
            return _no_auth

        async def _require_fallback_api_key(request: Request) -> None:
            provided = (
                request.headers.get("x-device-control-key")
                or request.query_params.get("device_control_key")
                or ""
            ).strip()
            if not provided or not secrets.compare_digest(provided, fallback_key):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid device control key",
                )

        return _require_fallback_api_key

    async def _require_auth(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    ) -> None:
        raw_token: str | None = None
        if credentials:
            raw_token = credentials.credentials
        else:
            raw_token = request.query_params.get("token") or None

        if not raw_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
            )
        try:
            payload = jwt.decode(raw_token, jwt_secret_key(), algorithms=[jwt_algorithm()])
            user_id = str(payload.get("sub") or "").strip()
            token_type = payload.get("type")
            if not user_id or token_type == "refresh":
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired token",
                )
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
            )

        # Serial ownership check: if the route has a {serial} path parameter,
        # verify the authenticated user owns that device.
        serial = request.path_params.get("serial")
        if serial:
            async with AsyncSessionLocal() as db:
                db_devices = await repo.list_devices(db, user_id=user_id)
                allowed = {d.serial for d in db_devices if d.serial}
                if serial not in allowed:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Not authorized to control this device",
                    )

    return _require_auth
