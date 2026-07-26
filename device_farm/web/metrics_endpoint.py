"""Opt-in, bearer-protected Prometheus exposition endpoint."""

from __future__ import annotations

import os
import secrets

from fastapi import APIRouter, Header
from fastapi.responses import PlainTextResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest


def _env_enabled(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def build_metrics_router(
    *,
    enabled: bool | None = None,
    token: str | None = None,
) -> APIRouter:
    router = APIRouter()
    expose = _env_enabled("METRICS_ENABLED") if enabled is None else enabled
    if not expose:
        return router

    expected_token = os.getenv("METRICS_TOKEN", "") if token is None else token

    @router.get("/metrics", include_in_schema=False)
    async def prometheus_metrics(
        authorization: str | None = Header(default=None),
    ) -> Response:
        if not expected_token:
            return PlainTextResponse("metrics token is not configured", status_code=503)
        supplied = ""
        if authorization and authorization.startswith("Bearer "):
            supplied = authorization.removeprefix("Bearer ").strip()
        if not supplied or not secrets.compare_digest(supplied, expected_token):
            return PlainTextResponse(
                "unauthorized",
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Import registers the application's collectors before exposition.
        from web import metrics as _metrics  # noqa: F401

        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return router
