from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.routes.media_webrtc import build_media_webrtc_router
from core.config import Config


class _Manager:
    def get_device(self, serial: str):
        return None


def _config() -> Config:
    cfg = Config()
    cfg.streaming.webrtc_enabled = True
    cfg.streaming.media_adapter_url = "http://adapter"
    return cfg


@pytest.mark.anyio
async def test_create_session_posts_to_media_adapter(monkeypatch):
    requests: list[dict] = []

    class _Response:
        status_code = 202
        headers: dict[str, str] = {}
        text = ""

        def json(self):
            return {
                "id": "session-1",
                "serial": "SERIAL-1",
                "viewer_id": "viewer-1",
                "stream_name": "device-SERIAL-1",
                "expires_at": "2026-08-04T00:00:00Z",
            }

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def request(self, method: str, url: str, json=None):
            requests.append({"method": method, "url": url, "json": json})
            return _Response()

        async def aclose(self):
            return None

    monkeypatch.setattr("api.routes.media_webrtc.httpx.AsyncClient", _Client)
    app = FastAPI()
    app.include_router(build_media_webrtc_router(_Manager(), _config(), db_enabled=False))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/media/webrtc/sessions",
            json={
                "serial": "SERIAL-1",
                "viewer_id": "viewer-1",
                "ttl_seconds": 120,
                "control": False,
                "profile": "degraded",
                "max_fps": 1,
                "max_width": 320,
                "bitrate": 150000,
            },
        )

    assert response.status_code == 200
    assert response.json()["stream_name"] == "device-SERIAL-1"
    assert requests == [
        {
            "method": "POST",
            "url": "http://adapter/v1/webrtc/sessions",
            "json": {
                "org_id": "local-org",
                "user_id": "local-user",
                "serial": "SERIAL-1",
                "viewer_id": "viewer-1",
                "ttl_seconds": 120,
                "control": False,
                "profile": "degraded",
                "max_fps": 1,
                "max_width": 320,
                "bitrate": 150000,
            },
        }
    ]


@pytest.mark.anyio
async def test_session_answer_posts_offer_to_media_adapter(monkeypatch):
    requests: list[dict] = []

    class _Response:
        status_code = 200
        headers: dict[str, str] = {}
        text = ""

        def json(self):
            return {"type": "answer", "sdp": "v=0 answer"}

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def request(self, method: str, url: str, json=None):
            requests.append({"method": method, "url": url, "json": json})
            return _Response()

        async def aclose(self):
            return None

    monkeypatch.setattr("api.routes.media_webrtc.httpx.AsyncClient", _Client)
    app = FastAPI()
    app.include_router(build_media_webrtc_router(_Manager(), _config(), db_enabled=False))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/media/webrtc/sessions/session-1/answer",
            json={"type": "offer", "sdp": "v=0 offer"},
        )

    assert response.status_code == 200
    assert response.json() == {"type": "answer", "sdp": "v=0 answer"}
    assert requests == [
        {
            "method": "POST",
            "url": "http://adapter/v1/webrtc/sessions/session-1/answer",
            "json": {"type": "offer", "sdp": "v=0 offer"},
        }
    ]


@pytest.mark.anyio
async def test_session_heartbeat_posts_to_media_adapter(monkeypatch):
    requests: list[dict] = []

    class _Response:
        status_code = 200
        headers: dict[str, str] = {}
        text = ""

        def json(self):
            return {
                "ok": True,
                "id": "session-1",
                "serial": "SERIAL-1",
                "viewer_id": "viewer-1",
                "expires_at": "2026-08-04T00:05:00Z",
            }

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def request(self, method: str, url: str, json=None):
            requests.append({"method": method, "url": url, "json": json})
            return _Response()

        async def aclose(self):
            return None

    monkeypatch.setattr("api.routes.media_webrtc.httpx.AsyncClient", _Client)
    app = FastAPI()
    app.include_router(build_media_webrtc_router(_Manager(), _config(), db_enabled=False))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/media/webrtc/sessions/session-1/heartbeat",
            json={"ttl_seconds": 300},
        )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert requests == [
        {
            "method": "POST",
            "url": "http://adapter/v1/webrtc/sessions/session-1/heartbeat",
            "json": {"ttl_seconds": 300},
        }
    ]


@pytest.mark.anyio
async def test_session_answer_returns_retryable_status_when_adapter_is_not_ready(monkeypatch):
    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def request(self, method: str, url: str, json=None):
            raise httpx.ReadTimeout("source not ready")

        async def aclose(self):
            return None

    monkeypatch.setattr("api.routes.media_webrtc.httpx.AsyncClient", _Client)
    app = FastAPI()
    app.include_router(build_media_webrtc_router(_Manager(), _config(), db_enabled=False))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/media/webrtc/sessions/session-1/answer",
            json={"type": "offer", "sdp": "v=0 offer"},
        )

    assert response.status_code == 425
    assert response.headers["retry-after"] == "0.25"
    assert response.json()["detail"] == "media adapter stream is not ready"
