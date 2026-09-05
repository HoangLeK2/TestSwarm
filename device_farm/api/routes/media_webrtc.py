from __future__ import annotations

import logging
import math
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from api.deps import caller_auth_from_request
from core.config import Config
from runtime.core import DeviceManager

log = logging.getLogger(__name__)
MEDIA_ADAPTER_TIMEOUT = httpx.Timeout(1.2, connect=0.25)
MEDIA_ADAPTER_CLIENT_LIMITS = httpx.Limits(
    max_connections=512,
    max_keepalive_connections=128,
    keepalive_expiry=30.0,
)
GO2RTC_SIGNALING_TIMEOUT_SECONDS = 8.0
GO2RTC_CONNECT_TIMEOUT_SECONDS = 1.0


class WebRTCSessionCreate(BaseModel):
    serial: str = Field(min_length=1)
    viewer_id: str = Field(min_length=1)
    ttl_seconds: int = Field(default=300, ge=1, le=1800)
    control: bool | None = None
    profile: str | None = None
    max_fps: int | None = Field(default=None, ge=1, le=60)
    max_width: int | None = Field(default=None, ge=120, le=2160)
    bitrate: int | None = Field(default=None, ge=50_000, le=8_000_000)


class SessionDescription(BaseModel):
    type: str = Field(pattern="^offer$")
    sdp: str = Field(min_length=1)


class WebRTCSessionHeartbeat(BaseModel):
    ttl_seconds: int = Field(default=300, ge=1, le=1800)


def build_media_webrtc_router(
    manager: DeviceManager,
    config: Config,
    *,
    db_enabled: bool,
) -> APIRouter:
    del manager
    router = APIRouter()
    adapter_client: httpx.AsyncClient | None = None
    go2rtc_client: httpx.AsyncClient | None = None

    def _adapter_base() -> str:
        if not config.streaming.webrtc_enabled:
            raise HTTPException(status_code=503, detail="WebRTC streaming is disabled")
        base = (config.streaming.media_adapter_url or "").strip().rstrip("/")
        if not base:
            raise HTTPException(status_code=503, detail="media adapter URL is not configured")
        return base

    def _adapter_http() -> httpx.AsyncClient:
        nonlocal adapter_client
        if adapter_client is None:
            adapter_client = httpx.AsyncClient(
                timeout=MEDIA_ADAPTER_TIMEOUT,
                limits=MEDIA_ADAPTER_CLIENT_LIMITS,
            )
        return adapter_client

    def _go2rtc_base() -> str:
        return (
            os.environ.get("DEVICE_FARM_GO2RTC_URL")
            or os.environ.get("GO2RTC_URL")
            or ""
        ).strip().rstrip("/")

    def _go2rtc_http() -> httpx.AsyncClient:
        nonlocal go2rtc_client
        if go2rtc_client is None:
            go2rtc_client = httpx.AsyncClient(
                timeout=_go2rtc_signaling_timeout(),
                limits=MEDIA_ADAPTER_CLIENT_LIMITS,
            )
        return go2rtc_client

    def _caller_identity(request: Request) -> tuple[str, str]:
        auth = caller_auth_from_request(request) if db_enabled else None
        user_id = (
            getattr(auth, "user_id", None)
            or getattr(request.state, "user_id", None)
            or "local-user"
        )
        org_id = (
            getattr(auth, "org_id", None)
            or getattr(request.state, "org_id", None)
            or "local-org"
        )
        return str(org_id), str(user_id)

    async def _adapter_json(method: str, path: str, *, body: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = await _adapter_http().request(
                method,
                f"{_adapter_base()}{path}",
                json=body,
            )
        except httpx.TimeoutException as exc:
            raise HTTPException(
                status_code=425,
                detail="media adapter stream is not ready",
                headers={"Retry-After": "0.25"},
            ) from exc
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"media adapter unavailable: {exc}") from exc
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="WebRTC session not found")
        if response.status_code == 425:
            raise HTTPException(
                status_code=425,
                detail=_adapter_error_detail(response, "media adapter stream is not ready"),
                headers={"Retry-After": response.headers.get("Retry-After", "0.25")},
            )
        if response.status_code >= 400:
            raise HTTPException(
                status_code=502,
                detail=f"media adapter rejected WebRTC request: {response.status_code} {_adapter_error_detail(response, '')}".strip(),
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise HTTPException(status_code=502, detail="media adapter returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise HTTPException(status_code=502, detail="media adapter returned invalid payload")
        return data

    async def _go2rtc_answer(stream_name: str, offer: dict[str, Any]) -> dict[str, Any]:
        base = _go2rtc_base()
        if not base:
            raise HTTPException(status_code=503, detail="go2rtc URL is not configured")
        started = time.perf_counter()
        try:
            response = await _go2rtc_http().post(
                f"{base}/api/webrtc",
                params={"src": stream_name},
                json=offer,
            )
        except httpx.TimeoutException as exc:
            _log_go2rtc_answer(stream_name, status_code=None, elapsed_ms=_elapsed_ms(started), error="timeout")
            raise HTTPException(
                status_code=425,
                detail="go2rtc media source is not ready",
                headers={"Retry-After": "0.20"},
            ) from exc
        except httpx.RequestError as exc:
            _log_go2rtc_answer(stream_name, status_code=None, elapsed_ms=_elapsed_ms(started), error=type(exc).__name__)
            raise HTTPException(status_code=502, detail=f"go2rtc unavailable: {exc}") from exc
        elapsed_ms = _elapsed_ms(started)
        if response.status_code >= 400:
            # 500 is retryable here, not a hard failure. The stream is declared
            # before the adapter is told to start publishing, so between those
            # two moments it holds only the inert placeholder source; go2rtc
            # tries to dial that, gets connection refused, and answers 500. A
            # viewer whose offer lands in that window must retry, not give up —
            # mapping it to 502 turned a normal startup race into a dead player.
            retryable = response.status_code in {404, 408, 425, 500, 502, 503}
            _log_go2rtc_answer(
                stream_name,
                status_code=response.status_code,
                elapsed_ms=elapsed_ms,
                error="retryable" if retryable else "rejected",
            )
            raise HTTPException(
                status_code=425 if retryable else 502,
                detail=f"go2rtc rejected WebRTC request: {response.status_code} {response.text.strip()}".strip(),
                headers={"Retry-After": "0.20"},
            )
        _log_go2rtc_answer(stream_name, status_code=response.status_code, elapsed_ms=elapsed_ms)
        try:
            data = response.json()
        except ValueError:
            data = {"type": "answer", "sdp": response.text.strip()}
        if not isinstance(data, dict) or not data.get("sdp"):
            raise HTTPException(status_code=502, detail="go2rtc returned invalid WebRTC answer")
        return {"type": str(data.get("type") or "answer"), "sdp": str(data["sdp"])}

    def _control_plane_mode() -> str:
        mode = os.environ.get("MEDIA_ADAPTER_CONTROL_PLANE", "auto").strip().lower()
        return mode if mode in {"auto", "grpc", "http"} else "auto"

    def _signaling_plane_mode() -> str:
        mode = os.environ.get("MEDIA_WEBRTC_SIGNALING_PLANE", "auto").strip().lower()
        return mode if mode in {"auto", "backend", "adapter"} else "auto"

    def _media_adapter_servicer():
        try:
            from runtime.transports.media_adapter_control_servicer import (
                get_media_adapter_servicer,
            )
        except Exception:
            return None
        return get_media_adapter_servicer()

    def _grpc_result_or_error(data: dict[str, Any]) -> dict[str, Any]:
        if data.get("ok"):
            return data
        detail = str(data.get("error") or "media adapter stream is not ready")
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail)
        retry_after_ms = int(data.get("retry_after_ms") or 250)
        raise HTTPException(
            status_code=425,
            detail=detail,
            headers={"Retry-After": f"{max(1, retry_after_ms) / 1000:.2f}"},
        )

    async def _go2rtc_ensure_stream(stream_name: str) -> None:
        """Create the stream in go2rtc before the adapter publishes into it.

        go2rtc will not accept an RTSP ANNOUNCE for a name it does not already
        know: the publish is refused and the stream never appears, with nothing
        in the log to say why. Something must declare the name first.

        That job belongs here rather than in the adapter. The adapter sits on the
        customer's machine, so letting it register would mean exposing go2rtc's
        API to the internet; the backend reaches it over the compose network, so
        :1984 stays private.
        """
        base = _go2rtc_base()
        if not base:
            return
        client = _go2rtc_http()
        try:
            existing = await client.get(f"{base}/api/streams")
            if existing.status_code < 400 and stream_name in (existing.json() or {}):
                return
        except (httpx.RequestError, ValueError):
            pass  # fall through to the PUT; a duplicate declaration is harmless
        try:
            # go2rtc has no "declare an empty stream" call — every source it
            # accepts is one it will dial. Point it at the discard port so the
            # dial fails instantly and leaves an inert placeholder; the real
            # video arrives as a second producer when the adapter publishes.
            # go2rtc answers 400 because that probe failed, but the stream is
            # created, which is the part we need.
            await client.put(
                f"{base}/api/streams",
                params={"name": stream_name, "src": "rtsp://127.0.0.1:9/placeholder"},
            )
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"go2rtc unavailable: {exc}") from exc

    async def _create_session_grpc(payload: dict[str, Any]) -> dict[str, Any]:
        servicer = _media_adapter_servicer()
        serial = str(payload.get("serial") or "")
        if servicer is None or not servicer.has_serial(serial):
            raise HTTPException(status_code=503, detail="no media adapter control channel for serial")
        # Must happen before the adapter is told to start: create_session is what
        # makes it publish, and a publish into an unknown name is dropped.
        await _go2rtc_ensure_stream(_go2rtc_stream_name(serial))
        data = _grpc_result_or_error(await servicer.create_session(payload))
        return _session_payload_from_grpc(data)

    async def _answer_session_grpc(session_id: str, offer: dict[str, Any]) -> dict[str, Any]:
        servicer = _media_adapter_servicer()
        if servicer is None:
            raise HTTPException(status_code=503, detail="media adapter control channel is unavailable")
        signaling_mode = _signaling_plane_mode()
        session = getattr(servicer, "session_info", lambda _session_id: None)(session_id)
        if signaling_mode == "backend" and not _go2rtc_base():
            raise HTTPException(status_code=503, detail="go2rtc URL is not configured")
        if signaling_mode == "backend" and (not session or not session.get("stream_name")):
            raise HTTPException(status_code=404, detail="WebRTC session source not found")
        if signaling_mode != "adapter" and session and session.get("stream_name") and _go2rtc_base():
            try:
                return await _go2rtc_answer(str(session["stream_name"]), offer)
            except HTTPException:
                if signaling_mode == "backend":
                    raise
        data = _grpc_result_or_error(await servicer.answer_session(session_id, offer))
        if not data.get("sdp"):
            raise HTTPException(status_code=502, detail="media adapter returned invalid WebRTC answer")
        return {"type": str(data.get("type") or "answer"), "sdp": str(data["sdp"])}

    async def _heartbeat_session_grpc(session_id: str, ttl_seconds: int) -> dict[str, Any]:
        servicer = _media_adapter_servicer()
        if servicer is None:
            raise HTTPException(status_code=503, detail="media adapter control channel is unavailable")
        data = _grpc_result_or_error(await servicer.heartbeat_session(session_id, ttl_seconds))
        return _session_payload_from_grpc(data, ok=True)

    async def _close_session_grpc(session_id: str) -> dict[str, Any]:
        servicer = _media_adapter_servicer()
        if servicer is None:
            return {"ok": True}
        data = await servicer.close_session(session_id)
        return {"ok": bool(data.get("ok", True))}

    @router.on_event("shutdown")
    async def _close_media_adapter_client() -> None:
        if adapter_client is not None:
            await adapter_client.aclose()
        if go2rtc_client is not None:
            await go2rtc_client.aclose()

    @router.post("/api/media/webrtc/sessions")
    async def create_session(request: Request, body: WebRTCSessionCreate):
        org_id, user_id = _caller_identity(request)
        payload: dict[str, Any] = {
            "org_id": org_id,
            "user_id": user_id,
            "serial": body.serial,
            "viewer_id": body.viewer_id,
            "ttl_seconds": body.ttl_seconds,
        }
        if body.control is not None:
            payload["control"] = body.control
        if body.profile:
            payload["profile"] = body.profile
        if body.max_fps is not None:
            payload["max_fps"] = body.max_fps
        if body.max_width is not None:
            payload["max_width"] = body.max_width
        if body.bitrate is not None:
            payload["bitrate"] = body.bitrate
        mode = _control_plane_mode()
        if mode != "http":
            try:
                return await _create_session_grpc(payload)
            except HTTPException:
                if mode == "grpc":
                    raise
        return await _adapter_json("POST", "/v1/webrtc/sessions", body=payload)

    @router.post("/api/media/webrtc/sessions/{session_id}/answer")
    async def answer_session(session_id: str, body: SessionDescription):
        mode = _control_plane_mode()
        offer = {"type": body.type, "sdp": body.sdp}
        if mode != "http":
            try:
                return JSONResponse(content=await _answer_session_grpc(session_id, offer))
            except HTTPException:
                if mode == "grpc":
                    raise
        data = await _adapter_json(
            "POST",
            f"/v1/webrtc/sessions/{session_id}/answer",
            body=offer,
        )
        if not data.get("sdp"):
            raise HTTPException(status_code=502, detail="media adapter returned invalid WebRTC answer")
        return JSONResponse(content={"type": str(data.get("type") or "answer"), "sdp": str(data["sdp"])})

    @router.post("/api/media/webrtc/sessions/{session_id}/heartbeat")
    async def heartbeat_session(session_id: str, body: WebRTCSessionHeartbeat):
        mode = _control_plane_mode()
        if mode != "http":
            try:
                return await _heartbeat_session_grpc(session_id, body.ttl_seconds)
            except HTTPException:
                if mode == "grpc":
                    raise
        return await _adapter_json(
            "POST",
            f"/v1/webrtc/sessions/{session_id}/heartbeat",
            body={"ttl_seconds": body.ttl_seconds},
        )

    @router.delete("/api/media/webrtc/sessions/{session_id}")
    async def close_session(session_id: str):
        mode = _control_plane_mode()
        if mode != "http":
            try:
                return await _close_session_grpc(session_id)
            except HTTPException:
                if mode == "grpc":
                    raise
        return await _adapter_json("DELETE", f"/v1/webrtc/sessions/{session_id}")

    return router


def _adapter_error_detail(response: httpx.Response, fallback: str) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text.strip() or fallback
    if isinstance(data, dict):
        detail = data.get("detail") or data.get("error")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
    return fallback


def _positive_float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if math.isfinite(value) and value > 0 else default


def _go2rtc_signaling_timeout() -> httpx.Timeout:
    total = _positive_float_env(
        "DEVICE_FARM_GO2RTC_SIGNALING_TIMEOUT_SECONDS",
        GO2RTC_SIGNALING_TIMEOUT_SECONDS,
    )
    connect = _positive_float_env(
        "DEVICE_FARM_GO2RTC_CONNECT_TIMEOUT_SECONDS",
        GO2RTC_CONNECT_TIMEOUT_SECONDS,
    )
    return httpx.Timeout(total, connect=min(connect, total))


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


def _log_go2rtc_answer(
    stream_name: str,
    *,
    status_code: int | None,
    elapsed_ms: int,
    error: str | None = None,
) -> None:
    slow_ms = int(_positive_float_env("DEVICE_FARM_GO2RTC_SLOW_ANSWER_MS", 1500))
    if error or elapsed_ms >= slow_ms:
        log.warning(
            "go2rtc WebRTC answer stream=%s status=%s elapsed_ms=%d error=%s",
            stream_name,
            status_code,
            elapsed_ms,
            error or "",
        )


_UNSAFE_STREAM_NAME = re.compile(r"[^A-Za-z0-9_.-]+")


def _go2rtc_stream_name(serial: str) -> str:
    """Mirror of media-adapter's stream.StreamName (Go).

    The backend has to declare the stream in go2rtc before the adapter publishes
    into it, so both sides must derive the same name from a serial. Keep this in
    lockstep with agent-boot/media-adapter/internal/domain/stream/packet.go: a
    divergence means the backend declares one name, the adapter publishes to
    another, and the publish is silently dropped.
    """
    safe = _UNSAFE_STREAM_NAME.sub("_", serial.strip())
    return f"device-{safe or 'unknown'}"


def _redact_stream_source(value: str) -> str:
    """Strip userinfo from an RTSP URL before it reaches a browser.

    Since media-adapter publishes into go2rtc instead of being pulled from, the
    stream_source it reports is the ingest URL, and that URL carries the RTSP
    credentials for the internet-facing :8554 port. This payload is returned by
    the session API, so the raw value would hand every viewer the keys to
    ANNOUNCE over any device's stream.
    """
    scheme, sep, rest = value.partition("://")
    if not sep or "@" not in rest:
        return value
    _userinfo, _, host = rest.rpartition("@")
    return f"{scheme}://{host}"


def _session_payload_from_grpc(data: dict[str, Any], *, ok: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if ok:
        payload["ok"] = True
    session_id = str(data.get("session_id") or data.get("id") or "")
    if session_id:
        payload["id"] = session_id
    for key in ("serial", "viewer_id", "stream_name", "stream_source"):
        value = data.get(key)
        if value is not None:
            if key == "stream_source":
                value = _redact_stream_source(str(value))
            payload[key] = value
    expires = int(data.get("expires_at_unix_ms") or 0)
    if expires > 0:
        payload["expires_at"] = (
            datetime.fromtimestamp(expires / 1000.0, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
    return payload
