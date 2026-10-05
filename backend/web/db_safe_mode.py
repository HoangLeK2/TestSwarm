"""Middleware gate for DB-degraded safe mode (DF-T-01-007)."""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

_ALLOWED_PREFIXES = (
    "/health",
    "/api/live",
    "/api/ready",
    "/api/health",
    "/api/server/",
    "/docs",
    "/openapi.json",
    "/redoc",
)


def _is_allowed(path: str) -> bool:
    return any(path.startswith(p) for p in _ALLOWED_PREFIXES)


class DbSafeModeMiddleware(BaseHTTPMiddleware):
    """Return SERVICE_DEGRADED for business CRUD routes when DB safe mode is active."""

    async def dispatch(self, request: Request, call_next):
        monitor = getattr(request.app.state, "db_health", None)
        if monitor is None or not getattr(monitor, "safe_mode", False):
            return await call_next(request)

        path = request.url.path or ""
        if not path.startswith("/api/") or _is_allowed(path):
            return await call_next(request)

        return JSONResponse(
            {
                "code": "SERVICE_DEGRADED",
                "safe_mode": True,
                "retry_after": 30,
            },
            status_code=503,
            headers={"Retry-After": "30"},
        )
