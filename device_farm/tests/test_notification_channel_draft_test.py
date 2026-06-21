from __future__ import annotations

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
    assert captured["json"] == {
        "chat_id": "-1001",
        "text": "Test notification\nDevice Farm notification channel is working.",
    }


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
