from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from api.deps import caller_auth_from_request
from core.config import Config
from runtime.core import DeviceManager

MEDIA_ADAPTER_TIMEOUT = httpx.Timeout(1.2, connect=0.25)
MEDIA_ADAPTER_CLIENT_LIMITS = httpx.Limits(
    max_connections=512,
    max_keepalive_connections=128,
    keepalive_expiry=30.0,
)


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

    @router.on_event("shutdown")
    async def _close_media_adapter_client() -> None:
        if adapter_client is not None:
            await adapter_client.aclose()

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
        return await _adapter_json("POST", "/v1/webrtc/sessions", body=payload)

    @router.post("/api/media/webrtc/sessions/{session_id}/answer")
    async def answer_session(session_id: str, body: SessionDescription):
        data = await _adapter_json(
            "POST",
            f"/v1/webrtc/sessions/{session_id}/answer",
            body={"type": body.type, "sdp": body.sdp},
        )
        if not data.get("sdp"):
            raise HTTPException(status_code=502, detail="media adapter returned invalid WebRTC answer")
        return JSONResponse(content={"type": str(data.get("type") or "answer"), "sdp": str(data["sdp"])})

    @router.post("/api/media/webrtc/sessions/{session_id}/heartbeat")
    async def heartbeat_session(session_id: str, body: WebRTCSessionHeartbeat):
        return await _adapter_json(
            "POST",
            f"/v1/webrtc/sessions/{session_id}/heartbeat",
            body={"ttl_seconds": body.ttl_seconds},
        )

    @router.delete("/api/media/webrtc/sessions/{session_id}")
    async def close_session(session_id: str):
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
