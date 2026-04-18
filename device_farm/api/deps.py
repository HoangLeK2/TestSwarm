from __future__ import annotations

import os
import secrets
from typing import Annotated, AsyncGenerator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import AuthContext, policy
from api.auth.context import AuthError, decode_access_token, extract_bearer
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


def _auth_context_from_creds(
    credentials: HTTPAuthorizationCredentials | None,
) -> AuthContext:
    raw = credentials.credentials if credentials else None
    try:
        return decode_access_token(raw or "")
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc


async def _get_auth_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthContext:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return _auth_context_from_creds(credentials)


async def _get_current_user(
    db: DB,
    ctx: AuthContext = Depends(_get_auth_context),
) -> User:
    user = await repo.get_user(db, ctx.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


async def _get_current_admin(user: User = Depends(_get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return user


CurrentAuth = Annotated[AuthContext, Depends(_get_auth_context)]
CurrentUser = Annotated[User, Depends(_get_current_user)]
AdminUser = Annotated[User, Depends(_get_current_admin)]


def caller_auth_from_request(request: Request) -> AuthContext | None:
    """Best-effort AuthContext recovery for routes behind `device_auth`.

    Reads the context the router dependency cached on `request.state.auth`;
    falls back to one re-decode if missing. Returns None if no valid bearer
    header is present — callers must treat None as 401.
    """
    cached = getattr(getattr(request, "state", None), "auth", None)
    if isinstance(cached, AuthContext):
        return cached
    token = extract_bearer(request.headers.get("authorization"))
    if not token:
        return None
    try:
        ctx = decode_access_token(token)
    except AuthError:
        return None
    try:
        request.state.auth = ctx
    except Exception:
        pass
    return ctx


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
        # Header-only bearer; query tokens leak via logs/referrer/proxy caches.
        if not credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
            )
        ctx = _auth_context_from_creds(credentials)

        # Serial ownership check: if the route declares {serial}, require
        # the authenticated caller to own it. Centralized in policy.py.
        serial = request.path_params.get("serial")
        if serial:
            await policy.assert_owns_device(ctx, serial)

        # Stash the context on request.state so downstream routes can read
        # it via `deps.caller_auth_from_request` without re-parsing.
        try:
            request.state.auth = ctx
        except Exception:
            pass

    return _require_auth
