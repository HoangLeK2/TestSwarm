from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from api.auth.context import extract_bearer, try_decode_access_token
from db.database import AsyncSessionLocal
from db.models.activity import ActivityLog
from services.activity_presenter import resolve_device_label_for_audit

log = logging.getLogger(__name__)

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
SKIPPED_PREFIXES = (
    "/api/analytics/activity",
    "/api/live",
    "/api/ready",
    "/api/health",
)
DEVICE_SCREEN_CONTROL_PATH_PARTS = (
    "/scrcpy",
    "/control",
    "/touch",
    "/tap",
    "/swipe",
    "/key",
    "/text",
    "/hierarchy",
    "/screenshot",
    "/interrupt",
)
SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "session",
    "credential",
)
MAX_VALUE_CHARS = 500
MAX_ACTION_CHARS = 50
DEFAULT_QUEUE_SIZE = 10_000
DEFAULT_BATCH_SIZE = 100
DEFAULT_FLUSH_INTERVAL_SECONDS = 0.25


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, str(default))))
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return max(0.01, float(os.environ.get(name, str(default))))
    except Exception:
        return default


@dataclass(frozen=True)
class UserActionAuditPayload:
    action: str
    entity_type: str | None
    entity_id: str | None
    user_id: str | None
    org_id: str | None
    method: str
    path: str
    route_template: str | None
    status_code: int
    request_id: str | None
    ip_address: str | None
    user_agent: str | None
    outcome: str
    duration_ms: int
    details: dict[str, Any]


def _clip(value: str, max_chars: int = MAX_VALUE_CHARS) -> str:
    if len(value) <= max_chars:
        return value
    return value[:max_chars] + "...[truncated]"


def _short(value: str | None, max_chars: int) -> str | None:
    if value is None:
        return None
    value = str(value)
    return value[:max_chars] if len(value) > max_chars else value


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def sanitize_audit_value(key: str, value: Any) -> Any:
    if _is_sensitive_key(key):
        return "[REDACTED]"
    if isinstance(value, str):
        return _clip(value)
    if isinstance(value, Mapping):
        return {
            str(child_key): sanitize_audit_value(str(child_key), child_value)
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [sanitize_audit_value(key, item) for item in value[:50]]
    return value


def _sanitize_mapping(values: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): sanitize_audit_value(str(key), value)
        for key, value in values.items()
    }


def should_audit_request(method: str, path: str) -> bool:
    method = method.upper()
    if method not in MUTATING_METHODS:
        return False
    if not path.startswith("/api/"):
        return False
    if any(path.startswith(prefix) for prefix in SKIPPED_PREFIXES):
        return False
    if path.startswith("/api/devices/") and any(
        part in path for part in DEVICE_SCREEN_CONTROL_PATH_PARTS
    ):
        return False
    return True


def _route_segments(route_template: str | None, path: str) -> list[str]:
    source = route_template or path
    return [
        segment
        for segment in source.strip("/").split("/")
        if segment and segment != "api" and not segment.startswith("{")
    ]


def _path_param_entity_id(path_params: Mapping[str, Any]) -> str | None:
    for key, value in path_params.items():
        if key.endswith("_id") or key == "id":
            return str(value)
    return None


def _action_for(method: str, segments: list[str]) -> str:
    resource = segments[0] if segments else "api"
    operation = segments[-1] if len(segments) > 1 else {
        "POST": "create",
        "PUT": "replace",
        "PATCH": "update",
        "DELETE": "delete",
    }.get(method.upper(), method.lower())
    action = f"user.{resource}.{operation}"
    return action[:MAX_ACTION_CHARS]


def _outcome(status_code: int) -> str:
    if status_code >= 500:
        return "error"
    if status_code >= 400:
        return "rejected"
    return "success"


def build_user_action_payload(
    *,
    method: str,
    path: str,
    route_template: str | None,
    status_code: int,
    duration_ms: int,
    request_id: str | None,
    user_id: str | None,
    org_id: str | None,
    query_params: Mapping[str, Any],
    path_params: Mapping[str, Any],
    client_host: str | None,
    user_agent: str | None,
) -> UserActionAuditPayload:
    method = method.upper()
    segments = _route_segments(route_template, path)
    entity_type = segments[0][:50] if segments else None
    entity_id = _path_param_entity_id(path_params)
    safe_query = _sanitize_mapping(query_params)
    safe_path_params = _sanitize_mapping(path_params)
    normalized_route = route_template or path

    return UserActionAuditPayload(
        action=_action_for(method, segments),
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user_id,
        org_id=org_id,
        method=method,
        path=_short(path, 255) or "",
        route_template=_short(normalized_route, 255),
        status_code=int(status_code),
        request_id=_short(request_id, 100),
        ip_address=_short(client_host, 64),
        user_agent=_short(user_agent, 255),
        outcome=_outcome(status_code),
        duration_ms=max(0, int(duration_ms)),
        details={
            "route_template": normalized_route,
            "path_params": safe_path_params,
            "query": safe_query,
        },
    )


def _user_id_from_request(request: Request) -> str | None:
    state_user = getattr(request.state, "user_id", None)
    if state_user:
        return str(state_user)
    token = extract_bearer(request.headers.get("authorization"))
    ctx = try_decode_access_token(token)
    return ctx.user_id if ctx else None


def _org_id_from_request(request: Request) -> str | None:
    state_org = getattr(request.state, "org_id", None)
    if state_org:
        return str(state_org)
    header_org = (request.headers.get("x-organization-id") or "").strip()
    return header_org or None


async def _activity_row_from_payload(
    db,
    payload: UserActionAuditPayload,
) -> ActivityLog | None:
    if not payload.user_id:
        return None
    path_params = payload.details.get("path_params")
    safe_path_params = path_params if isinstance(path_params, dict) else {}
    device_serial, device_label = await resolve_device_label_for_audit(
        db,
        path_params=safe_path_params,
    )
    details = dict(payload.details)
    if device_label:
        details["device_label"] = device_label
    return ActivityLog(
        action=payload.action,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        user_id=payload.user_id,
        device_serial=device_serial,
        details=details,
        org_id=payload.org_id,
        method=payload.method,
        path=payload.path,
        route_template=payload.route_template,
        status_code=payload.status_code,
        request_id=payload.request_id,
        ip_address=payload.ip_address,
        user_agent=payload.user_agent,
        outcome=payload.outcome,
        duration_ms=payload.duration_ms,
    )


async def write_user_action_activity(
    payload: UserActionAuditPayload,
    *,
    session_factory=AsyncSessionLocal,
) -> None:
    try:
        async with session_factory() as db:
            row = await _activity_row_from_payload(db, payload)
            if row is None:
                return
            db.add(row)
            await db.commit()
    except Exception as exc:
        log.warning("user action audit write failed action=%s path=%s: %s", payload.action, payload.path, exc)


async def write_user_action_activities(
    payloads: list[UserActionAuditPayload],
    *,
    session_factory=AsyncSessionLocal,
) -> None:
    rows: list[ActivityLog] = []
    if not payloads:
        return
    try:
        async with session_factory() as db:
            for payload in payloads:
                row = await _activity_row_from_payload(db, payload)
                if row is not None:
                    rows.append(row)
            if not rows:
                return
            db.add_all(rows)
            await db.commit()
    except Exception as exc:
        log.warning("user action audit batch write failed rows=%s: %s", len(rows), exc)


class AuditWriteDispatcher:
    def __init__(
        self,
        *,
        batch_writer: Callable[[list[UserActionAuditPayload]], Awaitable[None]] = write_user_action_activities,
        max_queue_size: int = DEFAULT_QUEUE_SIZE,
        batch_size: int = DEFAULT_BATCH_SIZE,
        flush_interval_seconds: float = DEFAULT_FLUSH_INTERVAL_SECONDS,
    ) -> None:
        self._batch_writer = batch_writer
        self._queue: asyncio.Queue[UserActionAuditPayload] = asyncio.Queue(maxsize=max_queue_size)
        self._batch_size = max(1, batch_size)
        self._flush_interval_seconds = max(0.01, flush_interval_seconds)
        self._worker: asyncio.Task | None = None
        self.dropped_total = 0

    def enqueue(self, payload: UserActionAuditPayload) -> bool:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run())
        try:
            self._queue.put_nowait(payload)
            return True
        except asyncio.QueueFull:
            self.dropped_total += 1
            if self.dropped_total == 1 or self.dropped_total % 100 == 0:
                log.warning("user action audit queue full; dropped_total=%s", self.dropped_total)
            return False

    async def drain(self) -> None:
        await self._queue.join()

    async def close(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
            self._worker = None

    async def _run(self) -> None:
        while True:
            first = await self._queue.get()
            batch = [first]
            deadline = time.monotonic() + self._flush_interval_seconds
            try:
                while len(batch) < self._batch_size:
                    timeout = deadline - time.monotonic()
                    if timeout <= 0:
                        break
                    try:
                        batch.append(await asyncio.wait_for(self._queue.get(), timeout))
                    except asyncio.TimeoutError:
                        break
                await self._batch_writer(batch)
            except Exception as exc:
                log.warning("user action audit dispatcher failed batch_size=%s: %s", len(batch), exc)
            finally:
                for _ in batch:
                    self._queue.task_done()


_dispatchers_by_loop: dict[int, AuditWriteDispatcher] = {}


def _default_dispatcher() -> AuditWriteDispatcher:
    loop = asyncio.get_running_loop()
    key = id(loop)
    dispatcher = _dispatchers_by_loop.get(key)
    if dispatcher is None:
        dispatcher = AuditWriteDispatcher(
            max_queue_size=_env_int("DEVICE_FARM_AUDIT_QUEUE_SIZE", DEFAULT_QUEUE_SIZE),
            batch_size=_env_int("DEVICE_FARM_AUDIT_BATCH_SIZE", DEFAULT_BATCH_SIZE),
            flush_interval_seconds=_env_float(
                "DEVICE_FARM_AUDIT_FLUSH_INTERVAL_SECONDS",
                DEFAULT_FLUSH_INTERVAL_SECONDS,
            ),
        )
        _dispatchers_by_loop[key] = dispatcher
    return dispatcher


def schedule_user_action_audit(
    payload: UserActionAuditPayload,
    *,
    writer: Callable[[UserActionAuditPayload], Awaitable[None]] | None = None,
) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if writer is not None:
        loop.create_task(writer(payload))
        return
    _default_dispatcher().enqueue(payload)


class UserActionAuditMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        writer: Callable[[UserActionAuditPayload], Awaitable[None]] | None = None,
        enabled: bool = True,
    ) -> None:
        super().__init__(app)
        self._writer = writer
        self._enabled = enabled

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not self._enabled or not should_audit_request(request.method, path):
            return await call_next(request)

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            self._schedule(request, status_code=500, started=started)
            raise

        self._schedule(request, status_code=response.status_code, started=started)
        return response

    def _schedule(self, request: Request, *, status_code: int, started: float) -> None:
        route = request.scope.get("route")
        route_template = getattr(route, "path", None)
        client_host = request.client.host if request.client else None
        duration_ms = int((time.perf_counter() - started) * 1000)
        payload = build_user_action_payload(
            method=request.method,
            path=request.url.path,
            route_template=route_template,
            status_code=status_code,
            duration_ms=duration_ms,
            request_id=getattr(request.state, "request_id", None) or request.headers.get("x-request-id"),
            user_id=_user_id_from_request(request),
            org_id=_org_id_from_request(request),
            query_params=dict(request.query_params),
            path_params=dict(request.path_params),
            client_host=client_host,
            user_agent=request.headers.get("user-agent"),
        )
        schedule_user_action_audit(payload, writer=self._writer)
