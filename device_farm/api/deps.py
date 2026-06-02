from __future__ import annotations

import os
import secrets
from typing import Annotated, AsyncGenerator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import AuthContext, policy
from api.auth.rbac import build_enforcer_for_user_from_db, is_superadmin, permission_domain
from api.auth.context import AuthError, TokenExpiredError, decode_access_token, extract_bearer
from db.database import AsyncSessionLocal
from db.models import Organization, User
from db import crud as repo
from tenancy.context import set_current_org_id
from tenancy.resolve import get_user_default_org_id

_ORG_HEADER = "x-organization-id"

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


def _auth_http_401(exc: AuthError) -> HTTPException:
    detail: str | dict = (
        {"code": exc.code}
        if exc.code in {"TOKEN_EXPIRED", "INVALID_TOKEN", "TOKEN_EXPIRED_KEY_REVOKED"}
        else "Invalid or expired token"
    )
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def _auth_context_from_creds(
    credentials: HTTPAuthorizationCredentials | None,
) -> AuthContext:
    raw = credentials.credentials if credentials else None
    try:
        return decode_access_token(raw or "")
    except AuthError as exc:
        raise _auth_http_401(exc) from exc


async def _get_auth_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthContext:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return _auth_context_from_creds(credentials)


async def _organization_exists(db: AsyncSession, org_id: str) -> bool:
    row = await db.execute(
        select(Organization.id).where(Organization.id == org_id).limit(1)
    )
    return row.scalar_one_or_none() is not None


async def _resolve_effective_org_id(
    request: Request | None,
    db: AsyncSession,
    user: User,
) -> str | None:
    """Org used for tenancy scoping on this request.

    The UI org switcher stores selection in localStorage and sends
    ``X-Organization-Id``. Without it, we fall back to ``users.default_org_id``.
    Superadmin may scope to any existing org; others only orgs they belong to.
    """
    base_org = get_user_default_org_id(user)
    if request is None:
        return base_org

    header_org = (request.headers.get(_ORG_HEADER) or "").strip()
    if not header_org:
        return base_org

    if not await _organization_exists(db, header_org):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "UNKNOWN_ORGANIZATION", "organization_id": header_org},
        )

    if is_superadmin(user):
        return header_org

    role = await repo.get_organization_role_for_user(db, user.id, header_org)
    if role:
        return header_org

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": "ORG_MEMBERSHIP_REQUIRED", "organization_id": header_org},
    )


def _apply_user_org_context(user: User, org_id: str | None) -> None:
    """Align ORM tenant filter with ``User.org_id`` (context var or default workspace)."""
    effective = org_id if org_id is not None else get_user_default_org_id(user)
    set_current_org_id(effective)


async def resolve_effective_org_id_for_user_id(
    request: Request | None,
    db: AsyncSession,
    user_id: str,
) -> str | None:
    """Resolve tenancy org for JWT-only code paths (e.g. ``/api/devices/live``)."""
    user = await repo.get_user(db, user_id)
    if not user:
        return None
    org_id = await _resolve_effective_org_id(request, db, user)
    _apply_user_org_context(user, org_id)
    return org_id


async def _get_current_user(
    request: Request,
    db: DB,
    ctx: AuthContext = Depends(_get_auth_context),
) -> User:
    user = await repo.get_user(db, ctx.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    try:
        org_id = await _resolve_effective_org_id(request, db, user)
        _apply_user_org_context(user, org_id)
        request.state.user_id = str(user.id)
        request.state.org_id = org_id
        user.org_role = await repo.get_organization_role_for_user(  # type: ignore[attr-defined]
            db, user.id, org_id
        )
    except HTTPException:
        raise
    except Exception:
        pass
    return user


async def _get_current_admin(user: User = Depends(_get_current_user)) -> User:
    org_role = str(getattr(user, "org_role", "") or "").strip().lower()
    if not is_superadmin(user) and org_role not in ("owner", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return user


CurrentAuth = Annotated[AuthContext, Depends(_get_auth_context)]
CurrentUser = Annotated[User, Depends(_get_current_user)]
AdminUser = Annotated[User, Depends(_get_current_admin)]


def require_permission(obj: str, act: str):
    async def _require_permission(request: Request, user: CurrentUser, db: DB) -> None:
        domain = permission_domain(user)
        enforcer = await build_enforcer_for_user_from_db(user, db, domain=domain)
        if not enforcer.enforce(str(user.id), domain, obj, act):
            try:
                from services.security_audit import emit_security_event

                await emit_security_event(
                    db,
                    action="admin.access.denied",
                    user_id=user.id,
                    org_id=getattr(user, "org_id", None),
                    entity_type="route",
                    entity_id=f"{obj}:{act}",
                    ip_address=request.client.host if request.client else None,
                    user_agent=request.headers.get("user-agent"),
                    details={"path": request.url.path},
                )
            except Exception:
                pass
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "FORBIDDEN_ROLE", "required": f"{obj}:{act}"},
            )

    return _require_permission


def _token_from_request(request: Request) -> str:
    token = extract_bearer(request.headers.get("authorization"))
    if token:
        return token

    path = request.url.path or ""
    allow_media_query_token = (
        request.method == "GET"
        and (
            path.startswith("/stream/")
            or path.startswith("/screenshot/")
            or path.startswith("/screenshot-b64/")
        )
    )
    if allow_media_query_token:
        return (request.query_params.get("token") or "").strip()

    return ""


async def _current_user_from_request(request: Request, db: AsyncSession) -> User:
    cached = getattr(getattr(request, "state", None), "auth", None)
    if isinstance(cached, AuthContext):
        ctx = cached
    else:
        raw_token = _token_from_request(request)
        if not raw_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
            )
        try:
            ctx = decode_access_token(raw_token)
        except AuthError as exc:
            raise _auth_http_401(exc) from exc
        try:
            request.state.auth = ctx
        except Exception:
            pass

    user = await repo.get_user(db, ctx.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    try:
        org_id = await _resolve_effective_org_id(request, db, user)
        _apply_user_org_context(user, org_id)
        user.org_role = await repo.get_organization_role_for_user(  # type: ignore[attr-defined]
            db, user.id, org_id
        )
    except HTTPException:
        raise
    except Exception:
        pass
    return user


def require_request_permission(db_enabled: bool, obj: str, act: str):
    """Casbin permission dependency for routes mounted outside the DB api_router.

    Lab mode keeps its existing API-key/no-auth behavior. In DB mode this layers
    app-role authorization on top of route-specific JWT and ownership checks.
    """
    if not db_enabled:
        async def _no_permission() -> None:
            return

        return _no_permission

    async def _require_request_permission(request: Request, db: DB) -> None:
        user = await _current_user_from_request(request, db)
        domain = permission_domain(user)
        enforcer = await build_enforcer_for_user_from_db(user, db, domain=domain)
        if not enforcer.enforce(str(user.id), domain, obj, act):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied",
            )

    return _require_request_permission


def caller_auth_from_request(request: Request) -> AuthContext | None:
    """Best-effort AuthContext recovery for routes behind `device_auth`.

    Reads the context the router dependency cached on `request.state.auth`;
    falls back to one re-decode if missing. Returns None if no valid bearer
    header is present — callers must treat None as 401.
    """
    cached = getattr(getattr(request, "state", None), "auth", None)
    if isinstance(cached, AuthContext):
        return cached
    token = _token_from_request(request)
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
        # Prefer Authorization header. For image-tag media routes (/stream, /screenshot),
        # browsers cannot set custom headers, so we allow `?token=` as fallback.
        # Keep this fallback tightly scoped to media GET endpoints only.
        _raw_token = credentials.credentials if credentials else ""
        if not _raw_token:
            _path = request.url.path or ""
            _allow_query_token = (
                request.method == "GET"
                and (
                    _path.startswith("/stream/")
                    or _path.startswith("/screenshot/")
                    or _path.startswith("/screenshot-b64/")
                )
            )
            if _allow_query_token:
                _raw_token = (request.query_params.get("token") or "").strip()
        if not _raw_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
            )
        try:
            ctx = decode_access_token(_raw_token)
        except AuthError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            ) from exc

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
