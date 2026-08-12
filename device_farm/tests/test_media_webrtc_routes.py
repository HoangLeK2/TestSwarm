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
    monkeypatch.setenv("MEDIA_ADAPTER_CONTROL_PLANE", "http")

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
    monkeypatch.setenv("MEDIA_ADAPTER_CONTROL_PLANE", "http")

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
    monkeypatch.setenv("MEDIA_ADAPTER_CONTROL_PLANE", "http")

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
    monkeypatch.setenv("MEDIA_ADAPTER_CONTROL_PLANE", "http")

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


@pytest.mark.anyio
async def test_create_session_uses_grpc_media_adapter_control_plane(monkeypatch):
    calls: list[dict] = []

    class _Servicer:
        def has_serial(self, serial: str) -> bool:
            return serial == "SERIAL-1"

        async def create_session(self, payload: dict):
            calls.append(payload)
            return {
                "ok": True,
                "id": "session-1",
                "session_id": "session-1",
                "serial": payload["serial"],
                "viewer_id": payload["viewer_id"],
                "stream_name": "device-SERIAL-1",
                "stream_source": "rtsp://go2rtc.example.com:8554/device-SERIAL-1",
                "expires_at_unix_ms": 1_785_283_200_000,
            }

    class _HTTPClient:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("HTTP media adapter fallback must not be used in grpc mode")

    monkeypatch.setenv("MEDIA_ADAPTER_CONTROL_PLANE", "grpc")
    monkeypatch.setattr(
        "runtime.transports.media_adapter_control_servicer.get_media_adapter_servicer",
        lambda: _Servicer(),
    )
    monkeypatch.setattr("api.routes.media_webrtc.httpx.AsyncClient", _HTTPClient)
    app = FastAPI()
    app.include_router(build_media_webrtc_router(_Manager(), _config(), db_enabled=False))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/media/webrtc/sessions",
            json={"serial": "SERIAL-1", "viewer_id": "viewer-1", "ttl_seconds": 120},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "session-1"
    assert data["stream_source"] == "rtsp://go2rtc.example.com:8554/device-SERIAL-1"
    assert calls == [
        {
            "org_id": "local-org",
            "user_id": "local-user",
            "serial": "SERIAL-1",
            "viewer_id": "viewer-1",
            "ttl_seconds": 120,
        }
    ]


@pytest.mark.anyio
async def test_session_answer_uses_backend_go2rtc_signaling_when_session_is_known(monkeypatch):
    requests: list[dict] = []

    class _Servicer:
        def session_info(self, session_id: str):
            assert session_id == "session-1"
            return {"stream_name": "device-SERIAL-1"}

        async def answer_session(self, session_id: str, offer: dict):
            raise AssertionError("answer should go directly to go2rtc")

    class _Response:
        status_code = 200
        headers: dict[str, str] = {}
        text = ""

        def json(self):
            return {"type": "answer", "sdp": "v=0 go2rtc-answer"}

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def post(self, url: str, params=None, json=None):
            requests.append({"url": url, "params": params, "json": json})
            return _Response()

        async def aclose(self):
            return None

    monkeypatch.setenv("MEDIA_ADAPTER_CONTROL_PLANE", "grpc")
    monkeypatch.setenv("MEDIA_WEBRTC_SIGNALING_PLANE", "backend")
    monkeypatch.setenv("DEVICE_FARM_GO2RTC_URL", "http://go2rtc:1984")
    monkeypatch.setattr(
        "runtime.transports.media_adapter_control_servicer.get_media_adapter_servicer",
        lambda: _Servicer(),
    )
    monkeypatch.setattr("api.routes.media_webrtc.httpx.AsyncClient", _Client)
    app = FastAPI()
    app.include_router(build_media_webrtc_router(_Manager(), _config(), db_enabled=False))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/media/webrtc/sessions/session-1/answer",
            json={"type": "offer", "sdp": "v=0 offer"},
        )

    assert response.status_code == 200
    assert response.json() == {"type": "answer", "sdp": "v=0 go2rtc-answer"}
    assert requests == [
        {
            "url": "http://go2rtc:1984/api/webrtc",
            "params": {"src": "device-SERIAL-1"},
            "json": {"type": "offer", "sdp": "v=0 offer"},
        }
    ]


@pytest.mark.anyio
async def test_session_answer_can_force_adapter_signaling(monkeypatch):
    calls: list[dict] = []

    class _Servicer:
        def session_info(self, session_id: str):
            return {"stream_name": "device-SERIAL-1"}

        async def answer_session(self, session_id: str, offer: dict):
            calls.append({"session_id": session_id, "offer": offer})
            return {
                "ok": True,
                "session_id": session_id,
                "type": "answer",
                "sdp": "v=0 adapter-answer",
            }

    class _HTTPClient:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("go2rtc HTTP client should not be constructed")

    monkeypatch.setenv("MEDIA_ADAPTER_CONTROL_PLANE", "grpc")
    monkeypatch.setenv("MEDIA_WEBRTC_SIGNALING_PLANE", "adapter")
    monkeypatch.setenv("DEVICE_FARM_GO2RTC_URL", "http://go2rtc:1984")
    monkeypatch.setattr(
        "runtime.transports.media_adapter_control_servicer.get_media_adapter_servicer",
        lambda: _Servicer(),
    )
    monkeypatch.setattr("api.routes.media_webrtc.httpx.AsyncClient", _HTTPClient)
    app = FastAPI()
    app.include_router(build_media_webrtc_router(_Manager(), _config(), db_enabled=False))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/media/webrtc/sessions/session-1/answer",
            json={"type": "offer", "sdp": "v=0 offer"},
        )

    assert response.status_code == 200
    assert response.json() == {"type": "answer", "sdp": "v=0 adapter-answer"}
    assert calls == [
        {
            "session_id": "session-1",
            "offer": {"type": "offer", "sdp": "v=0 offer"},
        }
    ]
