from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.routes.analytics import _exclude_device_screen_control_logs, _load_account_feed_page
from auth.jwt_service import issue_access_token
from db.database import Base
from db.models.activity import ActivityLog
from db.models.account import Account
from db.models.account_action import AccountAction
from db.models.account_event import AccountEvent
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
    assert should_audit_request("POST", "/api/media/webrtc/sessions") is False
    assert (
        should_audit_request(
            "POST",
            "/api/media/webrtc/sessions/session-1/answer",
        )
        is False
    )
    assert should_audit_request("POST", "/health") is False


@pytest.mark.parametrize(
    "path",
    [
        "/api/devices/serial-1/scrcpy/attach",
        "/api/devices/serial-1/scrcpy/detach",
        "/api/devices/serial-1/control/tap",
        "/api/devices/serial-1/control/swipe",
        "/api/devices/serial-1/touch",
        "/api/devices/serial-1/tap",
        "/api/devices/serial-1/swipe",
        "/api/devices/serial-1/key",
        "/api/devices/serial-1/text",
        "/api/devices/serial-1/hierarchy",
        "/api/devices/serial-1/screenshot",
        "/api/devices/serial-1/interrupt",
    ],
)
def test_should_not_audit_realtime_device_screen_control(path):
    assert should_audit_request("POST", path) is False


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

    token, _, _ = issue_access_token(user_id="user-1", org_id="org-1", roles=["owner"])
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


@pytest.mark.asyncio
async def test_activity_history_query_hides_old_realtime_device_control_logs():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    try:
        async with session_factory() as db:
            db.add_all(
                [
                    ActivityLog(
                        id="control-1",
                        action="user.devices.attach",
                        entity_type="devices",
                        entity_id="serial-1",
                        route_template="/api/devices/{serial}/scrcpy/attach",
                        path="/api/devices/serial-1/scrcpy/attach",
                        details={},
                    ),
                    ActivityLog(
                        id="campaign-1",
                        action="campaign.dispatched",
                        entity_type="campaign",
                        entity_id="camp-1",
                        details={},
                    ),
                    ActivityLog(
                        id="media-1",
                        action="user.media.answer",
                        entity_type="media",
                        entity_id="session-1",
                        route_template="/api/media/webrtc/sessions/{session_id}/answer",
                        path="/api/media/webrtc/sessions/session-1/answer",
                        details={},
                    ),
                    ActivityLog(
                        id="ws-1",
                        action="ws.connected",
                        entity_type="session",
                        entity_id="session-1",
                        details={},
                    ),
                ]
            )
            await db.commit()

        async with session_factory() as db:
            result = await db.execute(
                _exclude_device_screen_control_logs(select(ActivityLog))
                .order_by(ActivityLog.id)
            )
            rows = list(result.scalars().all())
    finally:
        await engine.dispose()

    assert [row.id for row in rows] == ["campaign-1"]


@pytest.mark.asyncio
async def test_activity_history_unifies_account_events_and_actions():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    now = datetime(2026, 1, 1, 12, tzinfo=UTC)
    try:
        async with session_factory() as db:
            db.add(
                Account(
                    id="account-1",
                    org_id="org-1",
                    user_id="user-1",
                    platform="instagram",
                    username="platform-user",
                    display_name="Platform User",
                )
            )
            db.add_all(
                [
                    ActivityLog(
                        id="activity-1",
                        org_id="org-1",
                        user_id="user-1",
                        action="campaign.dispatched",
                        entity_type="campaign",
                        entity_id="campaign-1",
                        details={"campaign_name": "Campaign"},
                        created_at=now - timedelta(minutes=3),
                    ),
                    AccountEvent(
                        id="event-1",
                        account_id="account-1",
                        user_id="user-1",
                        event_type="account.usage_started",
                        device_serial="serial-1",
                        platform="instagram",
                        details={"token": "secret"},
                        created_at=now - timedelta(minutes=2),
                    ),
                    AccountAction(
                        id="action-1",
                        org_id="org-1",
                        account_id="account-1",
                        action_key="key-1",
                        action_type="connection_request",
                        platform="instagram",
                        status="succeeded",
                        status_rank=40,
                        target={"type": "profile", "label": "Lead A"},
                        result={"ok": True},
                        created_at=now - timedelta(minutes=1),
                        updated_at=now - timedelta(minutes=1),
                    ),
                ]
            )
            await db.commit()

        async with session_factory() as db:
            total, rows = await _load_account_feed_page(
                db,
                SimpleNamespace(id="user-1", org_id="org-1"),
                action=None,
                device_serial=None,
                account_id=None,
                offset=0,
                limit=50,
                activity_stmt=select(ActivityLog).where(ActivityLog.org_id == "org-1"),
            )

        assert total == 3
        assert [row.id for row in rows] == [
            "account_action:action-1",
            "account_event:event-1",
            "activity-1",
        ]
        assert rows[0].action == "account.action.connection_request"
        assert rows[0].entity_type == "account"
        assert rows[0].details["account_label"] == "Platform User (platform-user)"
        assert rows[0].details["target_label"] == "Lead A"
        assert rows[1].details["token"] == "[REDACTED]"
    finally:
        await engine.dispose()
