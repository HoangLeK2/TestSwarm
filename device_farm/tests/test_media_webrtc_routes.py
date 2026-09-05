from __future__ import annotations

import logging

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.routes.media_webrtc import (
    _go2rtc_signaling_timeout,
    _go2rtc_stream_name,
    _redact_stream_source,
    build_media_webrtc_router,
)
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


def test_go2rtc_stream_name_matches_the_go_adapter_rules():
    # Must stay identical to stream.StreamName in
    # agent-boot/media-adapter/internal/domain/stream/packet.go. If the two
    # drift, the backend declares one name and the adapter publishes to another
    # — go2rtc drops the publish without logging a reason.
    assert _go2rtc_stream_name("10AE7S00HD002JK") == "device-10AE7S00HD002JK"
    assert _go2rtc_stream_name("emulator-5554") == "device-emulator-5554"
    assert _go2rtc_stream_name(" 1.2_3 ") == "device-1.2_3"
    assert _go2rtc_stream_name("a/b:c") == "device-a_b_c"
    assert _go2rtc_stream_name("") == "device-unknown"
    assert _go2rtc_stream_name("!!!") == "device-_"


def test_go2rtc_signaling_timeout_defaults_to_whep_answer_budget(monkeypatch):
    monkeypatch.delenv("DEVICE_FARM_GO2RTC_SIGNALING_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("DEVICE_FARM_GO2RTC_CONNECT_TIMEOUT_SECONDS", raising=False)

    timeout = _go2rtc_signaling_timeout()

    assert timeout.read == 8.0
    assert timeout.connect == 1.0


def test_go2rtc_signaling_timeout_can_be_overridden(monkeypatch):
    monkeypatch.setenv("DEVICE_FARM_GO2RTC_SIGNALING_TIMEOUT_SECONDS", "6.5")
    monkeypatch.setenv("DEVICE_FARM_GO2RTC_CONNECT_TIMEOUT_SECONDS", "0.75")

    timeout = _go2rtc_signaling_timeout()

    assert timeout.read == 6.5
    assert timeout.connect == 0.75


@pytest.mark.anyio
async def test_create_session_declares_go2rtc_stream_before_starting_adapter(monkeypatch):
    # go2rtc refuses an ANNOUNCE for a name it does not know, so the stream has
    # to exist before the adapter is told to start publishing.
    events: list[str] = []

    class _Servicer:
        def has_serial(self, serial: str) -> bool:
            return serial == "SERIAL-1"

        async def create_session(self, payload: dict):
            events.append("start_session")
            return {"ok": True, "session_id": "session-1", "stream_name": "device-SERIAL-1"}

    class _Response:
        def __init__(self, status_code: int, payload):
            self.status_code = status_code
            self._payload = payload
            self.headers: dict[str, str] = {}
            self.text = ""

        def json(self):
            return self._payload

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def get(self, url, **kwargs):
            events.append(f"GET {url}")
            return _Response(200, {})

        async def put(self, url, **kwargs):
            events.append(f"PUT {url} {kwargs.get('params')}")
            # go2rtc answers 400 because it probes the placeholder source and
            # fails; the stream is still created, so this must not raise.
            return _Response(400, {})

    monkeypatch.setenv("MEDIA_ADAPTER_CONTROL_PLANE", "grpc")
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
            "/api/media/webrtc/sessions",
            json={"serial": "SERIAL-1", "viewer_id": "viewer-1", "ttl_seconds": 120},
        )

    assert response.status_code == 200
    assert events == [
        "GET http://go2rtc:1984/api/streams",
        "PUT http://go2rtc:1984/api/streams "
        "{'name': 'device-SERIAL-1', 'src': 'rtsp://127.0.0.1:9/placeholder'}",
        "start_session",
    ]


@pytest.mark.anyio
async def test_create_session_skips_declaration_when_stream_already_exists(monkeypatch):
    events: list[str] = []

    class _Servicer:
        def has_serial(self, serial: str) -> bool:
            return True

        async def create_session(self, payload: dict):
            events.append("start_session")
            return {"ok": True, "session_id": "session-1"}

    class _Response:
        def __init__(self, payload):
            self.status_code = 200
            self._payload = payload
            self.headers: dict[str, str] = {}
            self.text = ""

        def json(self):
            return self._payload

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def get(self, url, **kwargs):
            events.append("GET")
            return _Response({"device-SERIAL-1": {"producers": []}})

        async def put(self, url, **kwargs):
            raise AssertionError("must not re-declare an existing stream")

    monkeypatch.setenv("MEDIA_ADAPTER_CONTROL_PLANE", "grpc")
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
            "/api/media/webrtc/sessions",
            json={"serial": "SERIAL-1", "viewer_id": "viewer-1", "ttl_seconds": 120},
        )

    assert response.status_code == 200
    assert events == ["GET", "start_session"]


@pytest.mark.anyio
async def test_answer_treats_go2rtc_500_as_retryable(monkeypatch):
    # Verified against go2rtc 1.9.14: a stream holding only the placeholder
    # source answers 500 "dial tcp 127.0.0.1:9: connection refused". That is the
    # window between declaring the stream and the adapter attaching its
    # publisher, so the viewer must retry rather than see a hard 502.
    class _Servicer:
        def session_info(self, session_id: str):
            return {"stream_name": "device-SERIAL-1"}

        async def answer_session(self, session_id: str, offer: dict):
            raise AssertionError("backend signaling must not fall back here")

    class _Response:
        status_code = 500
        headers: dict[str, str] = {}
        text = "streams: dial tcp 127.0.0.1:9: connect: connection refused"

        def json(self):
            return {}

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def post(self, url, **kwargs):
            return _Response()

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

    assert response.status_code == 425
    assert response.headers["retry-after"] == "0.20"


def test_redact_stream_source_strips_rtsp_credentials():
    # The adapter publishes into go2rtc, so the source it reports is the ingest
    # URL and carries the credentials for the internet-facing :8554 port. This
    # payload is served to viewers; leaking it would let any of them ANNOUNCE
    # over another device's stream.
    assert (
        _redact_stream_source("rtsp://farm:s3cret@go2rtc.example.com:8554/device-SERIAL-1")
        == "rtsp://go2rtc.example.com:8554/device-SERIAL-1"
    )
    assert (
        _redact_stream_source("rtsp://go2rtc.example.com:8554/device-SERIAL-1")
        == "rtsp://go2rtc.example.com:8554/device-SERIAL-1"
    )
    assert _redact_stream_source("device-SERIAL-1") == "device-SERIAL-1"


@pytest.mark.anyio
async def test_create_session_redacts_credentials_from_stream_source(monkeypatch):
    class _Servicer:
        def has_serial(self, serial: str) -> bool:
            return serial == "SERIAL-1"

        async def create_session(self, payload: dict):
            return {
                "ok": True,
                "session_id": "session-1",
                "serial": payload["serial"],
                "stream_name": "device-SERIAL-1",
                "stream_source": "rtsp://farm:s3cret@go2rtc.example.com:8554/device-SERIAL-1",
            }

    monkeypatch.setenv("MEDIA_ADAPTER_CONTROL_PLANE", "grpc")
    monkeypatch.setattr(
        "runtime.transports.media_adapter_control_servicer.get_media_adapter_servicer",
        lambda: _Servicer(),
    )
    app = FastAPI()
    app.include_router(build_media_webrtc_router(_Manager(), _config(), db_enabled=False))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/media/webrtc/sessions",
            json={"serial": "SERIAL-1", "viewer_id": "viewer-1", "ttl_seconds": 120},
        )

    assert response.status_code == 200
    assert "s3cret" not in response.text
    assert (
        response.json()["stream_source"]
        == "rtsp://go2rtc.example.com:8554/device-SERIAL-1"
    )


@pytest.mark.anyio
async def test_session_answer_uses_backend_go2rtc_signaling_when_session_is_known(monkeypatch, caplog):
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
    monkeypatch.setenv("DEVICE_FARM_GO2RTC_SLOW_ANSWER_MS", "0.1")
    monkeypatch.setattr(
        "runtime.transports.media_adapter_control_servicer.get_media_adapter_servicer",
        lambda: _Servicer(),
    )
    monkeypatch.setattr("api.routes.media_webrtc.httpx.AsyncClient", _Client)
    app = FastAPI()
    app.include_router(build_media_webrtc_router(_Manager(), _config(), db_enabled=False))

    with caplog.at_level(logging.WARNING, logger="api.routes.media_webrtc"):
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
    assert "go2rtc WebRTC answer stream=device-SERIAL-1" in caplog.text
    assert "v=0 offer" not in caplog.text


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
