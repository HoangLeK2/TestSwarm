"""Observe-only / low-bandwidth middleware.

Gates write methods and the UI hierarchy stream based on `config.safe_mode`.

- read_only=True: reject POST/PUT/PATCH/DELETE on mutating API paths.
  Auth endpoints stay open so the UI can still log in and issue GETs.
- stream_hierarchy=False: return 503 on hierarchy/ui_elements/hit_test
  so the front-end drops the costly dump/stream without probing.

A /api/server/safe-mode endpoint exposes the live flags so the front-end
can hide buttons/pages it has no permission to exercise.
"""
from __future__ import annotations

import logging
from typing import Iterable

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

log = logging.getLogger(__name__)

_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_HIERARCHY_SUFFIXES = ("/hierarchy", "/ui_elements", "/hit_test")

# Paths that must stay reachable even in read_only mode so the UI
# authentication loop keeps working. Trailing slash prevents `/api/authfoo`
# from matching via startswith.
_AUTH_PREFIXES = ("/api/auth/",)


def _is_hierarchy_path(path: str) -> bool:
    return any(path.endswith(s) for s in _HIERARCHY_SUFFIXES)


def _is_auth_allowed_write(path: str) -> bool:
    return any(path.startswith(p) for p in _AUTH_PREFIXES)


class SafeModeMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        read_only: bool,
        stream_hierarchy: bool,
        extra_allowed_write_prefixes: Iterable[str] = (),
    ) -> None:
        super().__init__(app)
        self.read_only = read_only
        self.stream_hierarchy = stream_hierarchy
        self._allowed = tuple(extra_allowed_write_prefixes) + _AUTH_PREFIXES

    async def dispatch(self, request: Request, call_next):
        path = request.url.path or ""

        # Hierarchy gate — applies to any method on those endpoints.
        if not self.stream_hierarchy and _is_hierarchy_path(path):
            return JSONResponse(
                {
                    "error": "UI hierarchy stream disabled by safe_mode",
                    "safe_mode": "stream_hierarchy=false",
                },
                status_code=503,
            )

        # Write gate.
        if self.read_only and request.method.upper() in _WRITE_METHODS:
            if not any(path.startswith(p) for p in self._allowed):
                return JSONResponse(
                    {
                        "error": "Farm is in read-only mode",
                        "safe_mode": "read_only=true",
                    },
                    status_code=403,
                )

        return await call_next(request)


def build_safe_mode_router(read_only: bool, stream_hierarchy: bool) -> APIRouter:
    """Expose flags to the front-end so UI can hide write controls."""
    router = APIRouter()

    @router.get("/server/safe-mode")
    async def api_safe_mode():
        return {
            "read_only": bool(read_only),
            "stream_hierarchy": bool(stream_hierarchy),
        }

    return router
