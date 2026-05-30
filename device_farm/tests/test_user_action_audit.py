from __future__ import annotations

import asyncio

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from api.routes.auth import _make_access_token
from services.user_action_audit import (
    AuditWriteDispatcher,
    UserActionAuditMiddleware,
    build_user_action_payload,
    sanitize_audit_value,
    should_audit_request,
)


def test_should_audit_only_mutating_api_requests():
    assert should_audit_request("POST", "/api/campaigns") is True
    assert should_audit_request("PATCH", "/api/devices/dev-1/tags") is True
    assert should_audit_request("DELETE", "/api/content/item-1") is True

    assert should_audit_request("GET", "/api/campaigns") is False
    assert should_audit_request("OPTIONS", "/api/campaigns") is False
    assert should_audit_request("POST", "/api/analytics/activity") is False
    assert should_audit_request("POST", "/health") is False


def test_build_user_action_payload_uses_stable_route_template():
    payload = build_user_action_payload(
        method="PATCH",
        path="/api/campaigns/camp-123/status",
        route_template="/api/campaigns/{campaign_id}/status",
        status_code=200,
        duration_ms=17,
        request_id="req-1",
        user_id="user-1",
        org_id="org-1",
        query_params={"token": "secret-token", "view": "full"},
        path_params={"campaign_id": "camp-123"},
        client_host="127.0.0.1",
        user_agent="pytest",
    )

    assert payload.action == "user.campaigns.status"
    assert payload.entity_type == "campaigns"
    assert payload.entity_id == "camp-123"
    assert payload.user_id == "user-1"
    assert payload.org_id == "org-1"
    assert payload.method == "PATCH"
    assert payload.path == "/api/campaigns/camp-123/status"
    assert payload.route_template == "/api/campaigns/{campaign_id}/status"
    assert payload.outcome == "success"
    assert payload.details["query"] == {"token": "[REDACTED]", "view": "full"}


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("password", "super-secret"),
        ("refresh_token", "jwt"),
        ("api_key", "key"),
        ("authorization", "Bearer abc"),
    ],
)
def test_sanitize_audit_value_redacts_sensitive_keys(key, value):
    assert sanitize_audit_value(key, value) == "[REDACTED]"


def test_sanitize_audit_value_bounds_large_values():
    assert sanitize_audit_value("note", "x" * 600) == ("x" * 500) + "...[truncated]"


def _payload(path: str = "/api/devices/dev-1/tags"):
    return build_user_action_payload(
        method="PATCH",
        path=path,
        route_template="/api/devices/{device_id}/tags",
        status_code=200,
        duration_ms=5,
        request_id="req-1",
        user_id="user-1",
        org_id="org-1",
        query_params={},
        path_params={"device_id": "dev-1"},
        client_host="127.0.0.1",
        user_agent="pytest",
    )


@pytest.mark.asyncio
async def test_audit_dispatcher_batches_writes():
    batches = []

    async def _batch_writer(payloads):
        batches.append(list(payloads))

    dispatcher = AuditWriteDispatcher(
        batch_writer=_batch_writer,
        max_queue_size=10,
        batch_size=2,
        flush_interval_seconds=0.1,
    )
    try:
        assert dispatcher.enqueue(_payload("/api/devices/dev-1/tags")) is True
        assert dispatcher.enqueue(_payload("/api/devices/dev-2/tags")) is True
        await asyncio.wait_for(dispatcher.drain(), timeout=1)
    finally:
        await dispatcher.close()

    assert len(batches) == 1
    assert len(batches[0]) == 2


@pytest.mark.asyncio
async def test_audit_dispatcher_bounds_queue_without_blocking():
    async def _slow_batch_writer(payloads):
        await asyncio.sleep(0.2)

    dispatcher = AuditWriteDispatcher(
        batch_writer=_slow_batch_writer,
        max_queue_size=1,
        batch_size=10,
        flush_interval_seconds=0.1,
    )
    try:
        assert dispatcher.enqueue(_payload("/api/devices/dev-1/tags")) is True
        assert dispatcher.enqueue(_payload("/api/devices/dev-2/tags")) is False
    finally:
        await dispatcher.close()

    assert dispatcher.dropped_total == 1


@pytest.mark.asyncio
async def test_user_action_middleware_schedules_authenticated_mutation():
    captured = []

    async def _writer(payload):
        captured.append(payload)

    app = FastAPI()
    app.add_middleware(UserActionAuditMiddleware, writer=_writer)

    @app.patch("/api/devices/{device_id}/tags")
    async def update_tags(device_id: str):
        return {"id": device_id}

    token = _make_access_token("user-1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(
            "/api/devices/dev-1/tags?token=secret&view=full",
            headers={
                "authorization": f"Bearer {token}",
                "x-organization-id": "org-1",
                "x-request-id": "req-1",
                "user-agent": "pytest",
            },
        )

    await asyncio.sleep(0)

    assert response.status_code == 200
    assert len(captured) == 1
    payload = captured[0]
    assert payload.action == "user.devices.tags"
    assert payload.entity_id == "dev-1"
    assert payload.user_id == "user-1"
    assert payload.org_id == "org-1"
    assert payload.request_id == "req-1"
    assert payload.details["query"]["token"] == "[REDACTED]"
