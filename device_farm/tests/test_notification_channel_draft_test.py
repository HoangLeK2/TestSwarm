from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.notification_service import NotificationService


@pytest.mark.asyncio
async def test_send_test_draft_telegram_posts_message(monkeypatch):
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(
        "services.notification_service.httpx.AsyncClient",
        lambda: FakeClient(),
    )

    svc = NotificationService()
    await svc.send_test_draft(
        db=None,  # type: ignore[arg-type]
        channel_type="telegram",
        config={"bot_token": "123:abc", "chat_id": "-1001"},
        user_id="user-1",
    )

    assert captured["url"] == "https://api.telegram.org/bot123:abc/sendMessage"
    assert captured["json"]["chat_id"] == "-1001"
    assert captured["json"]["parse_mode"] == "HTML"
    assert captured["json"]["disable_web_page_preview"] is True
    assert captured["json"]["text"].startswith("❌ <b>Test notification</b>")
    assert "Device Farm notification channel is working." in captured["json"]["text"]


@pytest.mark.asyncio
async def test_send_test_draft_requires_telegram_credentials():
    svc = NotificationService()
    with pytest.raises(ValueError, match="bot_token and chat_id"):
        await svc.send_test_draft(
            db=None,  # type: ignore[arg-type]
            channel_type="telegram",
            config={"bot_token": "", "chat_id": ""},
            user_id="user-1",
        )


@pytest.mark.asyncio
async def test_send_test_draft_rejects_in_app():
    svc = NotificationService()
    with pytest.raises(ValueError, match="in_app"):
        await svc.send_test_draft(
            db=None,  # type: ignore[arg-type]
            channel_type="in_app",
            config={},
            user_id="user-1",
        )


@pytest.mark.asyncio
async def test_notify_uses_loop_scoped_activity_session(monkeypatch):
    from db import database

    class FakeDb:
        async def commit(self) -> None:
            return None

        async def rollback(self) -> None:
            return None

    fake_db = FakeDb()
    entered = False

    @asynccontextmanager
    async def fake_activity_session():
        nonlocal entered
        entered = True
        yield fake_db

    monkeypatch.setattr(database, "activity_session", fake_activity_session)

    svc = NotificationService()

    async def fake_channels(db, event, user_id):
        assert db is fake_db
        assert event == "campaign.completed"
        assert user_id == "user-1"
        return [
            SimpleNamespace(
                id="telegram-1",
                type="telegram",
                config={"bot_token": "123:abc", "chat_id": "-1001"},
            )
        ]

    send_telegram = AsyncMock()
    monkeypatch.setattr(svc, "_channels_for_event", fake_channels)
    monkeypatch.setattr(svc, "_send_telegram", send_telegram)

    await svc.notify("campaign.completed", "Campaign done", "Collected: 1 item", user_id="user-1")

    assert entered is True
    send_telegram.assert_awaited_once()
