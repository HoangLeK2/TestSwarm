from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _app(*, enabled: bool, token: str = "") -> FastAPI:
    from web.metrics_endpoint import build_metrics_router

    app = FastAPI()
    app.include_router(build_metrics_router(enabled=enabled, token=token))
    return app


@pytest.mark.asyncio
async def test_metrics_endpoint_is_hidden_when_disabled():
    async with AsyncClient(
        transport=ASGITransport(app=_app(enabled=False)), base_url="http://test"
    ) as client:
        response = await client.get("/metrics")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_metrics_endpoint_requires_matching_bearer_token():
    async with AsyncClient(
        transport=ASGITransport(app=_app(enabled=True, token="metrics-secret")),
        base_url="http://test",
    ) as client:
        missing = await client.get("/metrics")
        wrong = await client.get(
            "/metrics", headers={"Authorization": "Bearer wrong"}
        )
        allowed = await client.get(
            "/metrics", headers={"Authorization": "Bearer metrics-secret"}
        )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert allowed.status_code == 200
    assert "text/plain" in allowed.headers["content-type"]
    assert "campaign_dispatch_duration_seconds" in allowed.text


@pytest.mark.asyncio
async def test_metrics_endpoint_refuses_enabled_mode_without_token():
    async with AsyncClient(
        transport=ASGITransport(app=_app(enabled=True, token="")),
        base_url="http://test",
    ) as client:
        response = await client.get("/metrics")

    assert response.status_code == 503
