"""FastAPI dependency factory for per-route rate limits (DF-T-01-013)."""

import hashlib
import logging
import os
import secrets
from typing import Any

from fastapi import Depends, HTTPException, Request, Response, status
from starlette.responses import JSONResponse

from rate_limit.budget import RateBudget, parse_budget
from rate_limit import counters
from rate_limit.store import RateLimitState, get_rate_limit_store

log = logging.getLogger(__name__)

_BYPASS_HEADER = "x-bypass-rate-limit"


def _bypass_token() -> str:
    return (os.environ.get("RATE_LIMIT_BYPASS_TOKEN") or os.environ.get("ADMIN_BYPASS_TOKEN") or "").strip()


def _client_ip(request: Request) -> str:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _resolve_key(request: Request, strategy: str, user: Any | None, endpoint: str) -> str:
    strategy = (strategy or "ip").strip().lower()
    parts: list[str] = []
    if "user" in strategy:
        uid = getattr(user, "id", None) if user is not None else None
        if not uid:
            body = getattr(request.state, "rate_limit_body", None)
            refresh = ""
            if isinstance(body, dict):
                refresh = str(body.get("refresh_token") or "")
            elif body is not None and hasattr(body, "refresh_token"):
                refresh = str(getattr(body, "refresh_token", "") or "")
            if refresh:
                uid = hashlib.sha256(refresh.encode("utf-8")).hexdigest()[:16]
        parts.append(f"user:{uid or _client_ip(request)}")
    if "ip" in strategy:
        parts.append(f"ip:{_client_ip(request)}")
    if "org" in strategy:
        org_id = getattr(user, "org_id", None) if user is not None else None
        parts.append(f"org:{org_id or 'none'}")
    if "endpoint" in strategy:
        parts.append(f"endpoint:{endpoint}")
    if not parts:
        parts.append(f"ip:{_client_ip(request)}")
    return ":".join(parts)


def _apply_headers(response: Response, state: RateLimitState) -> None:
    response.headers["X-RateLimit-Limit"] = str(state.limit)
    response.headers["X-RateLimit-Remaining"] = str(state.remaining)
    response.headers["X-RateLimit-Reset"] = str(state.reset_at)
    if not state.allowed:
        response.headers["Retry-After"] = str(state.retry_after)


async def _emit_exceeded(request: Request, endpoint: str, key: str) -> None:
    try:
        from db.database import AsyncSessionLocal
        from services.security_audit import emit_security_event

        async with AsyncSessionLocal() as db:
            await emit_security_event(
                db,
                action="rate_limit.exceeded",
                entity_type="route",
                entity_id=endpoint,
                ip_address=_client_ip(request),
                user_agent=request.headers.get("user-agent"),
                details={"key": key},
            )
            await db.commit()
    except Exception:
        log.debug("rate_limit audit emit skipped", exc_info=True)


def rate_limit(budget: str, *, key: str = "ip", enabled: bool | None = None):
    """Return a FastAPI dependency enforcing a fixed-window rate limit."""
    parsed = parse_budget(budget)
    needs_user = any(part in (key or "") for part in ("user", "org"))

    async def _enforce(
        request: Request,
        response: Response,
        user: Any | None = None,
    ) -> None:
        if enabled is False:
            return
        if os.environ.get("RATE_LIMIT_ENABLED", "1").strip().lower() in {"0", "false", "no"}:
            return

        endpoint = request.url.path
        bypass = request.headers.get(_BYPASS_HEADER, "").strip()
        expected = _bypass_token()
        if expected and bypass:
            if secrets.compare_digest(bypass, expected):
                counters.inc_bypassed()
                return
            counters.inc_bypass_failed()

        store = get_rate_limit_store()
        bucket_key = _resolve_key(request, key, user, endpoint)
        state = await store.consume(
            bucket_key,
            limit=parsed.limit,
            window_seconds=parsed.window_seconds,
        )
        request.state.rate_limit_state = state
        _apply_headers(response, state)
        if not state.allowed:
            await _emit_exceeded(request, endpoint, bucket_key)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"code": "TOO_MANY_REQUESTS"},
                headers={
                    "Retry-After": str(state.retry_after),
                    "X-RateLimit-Limit": str(state.limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(state.reset_at),
                },
            )

    if needs_user:
        from typing import Annotated

        from fastapi import Depends

        from api.deps import _get_current_user
        from db.models import User

        async def _dependency(
            request: Request,
            response: Response,
            user: Annotated[User, Depends(_get_current_user)],
        ) -> None:
            await _enforce(request, response, user)

        return _dependency

    async def _dependency(request: Request, response: Response) -> None:
        await _enforce(request, response, None)

    return _dependency


def attach_rate_limit_headers(request: Request, response: Response) -> None:
    state = getattr(request.state, "rate_limit_state", None)
    if isinstance(state, RateLimitState):
        _apply_headers(response, state)
