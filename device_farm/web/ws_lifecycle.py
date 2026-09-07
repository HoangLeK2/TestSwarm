"""Authenticated WebSocket stream for device lifecycle events (DF-T-02-015)."""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Any, Dict, Optional

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketDisconnect as StarletteWSDisconnect

from api.auth.context import AuthError, decode_access_token
from api.auth.rbac import build_enforcer_for_user_from_db, permission_domain
from db import crud as repo
from db.database import AsyncSessionLocal
from tenancy.context import set_current_org_id
from web.metrics import (
    lifecycle_ws_backpressure_total,
    lifecycle_ws_clients_connected,
    lifecycle_ws_events_sent_total,
)

log = logging.getLogger(__name__)

QUEUE_MAX = max(8, int(os.environ.get("DEVICE_LIFECYCLE_WS_QUEUE_MAX", "64")))


async def authenticate_lifecycle_ws(ws: WebSocket) -> tuple[str, str]:
    """Validate JWT + devices:read RBAC. Returns (user_id, org_id) or raises AuthError."""
    token = (ws.query_params.get("token") or "").strip()
    if not token:
        raise AuthError("missing token")
    ctx = decode_access_token(token)
    async with AsyncSessionLocal() as db:
        user = await repo.get_user(db, ctx.user_id)
        if not user or not user.is_active:
            raise AuthError("user not found")
        org_id = getattr(user, "org_id", None) or ctx.org_id
        if not org_id:
            raise AuthError("user has no organization")
        set_current_org_id(org_id)
        user.org_role = await repo.get_organization_role_for_user(db, user.id, org_id)  # type: ignore[attr-defined]
        domain = permission_domain(user)
        enforcer = await build_enforcer_for_user_from_db(user, db, domain=domain)
        if not enforcer.enforce(str(user.id), domain, "devices", "read"):
            raise AuthError("permission denied")
        return user.id, org_id


class DeviceLifecycleWsManager:
    """Manages /ws/lifecycle connections scoped by organization."""

    def __init__(self) -> None:
        self._connections: Dict[str, WebSocket] = {}
        self._queues: Dict[str, asyncio.Queue] = {}
        self._send_locks: Dict[str, asyncio.Lock] = {}
        self._org_ids: Dict[str, str] = {}
        self._user_ids: Dict[str, str] = {}
        self._sender_tasks: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()
        self._publisher: Any = None

    def bind_publisher(self, publisher: Any) -> None:
        self._publisher = publisher
        publisher.bind_ws_manager(self)

    async def connect(self, ws: WebSocket) -> None:
        try:
            user_id, org_id = await authenticate_lifecycle_ws(ws)
        except AuthError as exc:
            code = 4403 if "permission" in str(exc).lower() else 4401
            try:
                await ws.close(code=code, reason=str(exc)[:120])
            except Exception:
                pass
            return

        await ws.accept()
        conn_id = str(uuid.uuid4())
        queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAX)
        send_lock = asyncio.Lock()

        async with self._lock:
            self._connections[conn_id] = ws
            self._queues[conn_id] = queue
            self._send_locks[conn_id] = send_lock
            self._org_ids[conn_id] = org_id
            self._user_ids[conn_id] = user_id
            self._sender_tasks[conn_id] = asyncio.create_task(
                self._sender(conn_id, ws, queue, send_lock)
            )
            lifecycle_ws_clients_connected.inc()

        log.info("lifecycle WS connected conn=%s user=%s org=%s", conn_id, user_id, org_id)

        if self._publisher is not None:
            try:
                snapshot = await self._publisher.build_snapshot(org_id)
                await self._enqueue(conn_id, queue, snapshot.to_dict())
            except Exception as exc:
                log.warning("lifecycle snapshot enqueue failed conn=%s: %s", conn_id, exc)

        try:
            while True:
                msg = await ws.receive_text()
                if msg.strip().lower() == "ping":
                    await self._enqueue(conn_id, queue, {"type": "pong"})
        except (WebSocketDisconnect, StarletteWSDisconnect):
            pass
        except Exception as exc:
            log.debug("lifecycle WS receive ended conn=%s: %s", conn_id, exc)
        finally:
            await self._disconnect(conn_id)

    async def _enqueue(
        self,
        conn_id: str,
        queue: asyncio.Queue,
        message: dict[str, Any],
        *,
        org_id: str | None = None,
    ) -> None:
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            bound_org = org_id or self._org_ids.get(conn_id, "")
            try:
                lifecycle_ws_backpressure_total.labels(org_id=bound_org).inc()
            except Exception:
                pass
            log.warning(
                "lifecycle WS backpressure conn=%s org=%s queue=%s",
                conn_id,
                bound_org,
                QUEUE_MAX,
            )
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                log.warning("lifecycle WS drop after coalesce conn=%s", conn_id)

    async def broadcast_to_org(self, org_id: str, message: dict[str, Any]) -> None:
        async with self._lock:
            targets = [
                (conn_id, self._queues[conn_id])
                for conn_id, bound_org in self._org_ids.items()
                if bound_org == org_id and conn_id in self._queues
            ]
        for conn_id, queue in targets:
            await self._enqueue(conn_id, queue, message, org_id=org_id)

    async def _sender(
        self,
        conn_id: str,
        ws: WebSocket,
        queue: asyncio.Queue,
        send_lock: asyncio.Lock,
    ) -> None:
        try:
            while True:
                message = await queue.get()
                event_type = str(message.get("type") or "lifecycle.event")
                async with send_lock:
                    await ws.send_json(message)
                try:
                    lifecycle_ws_events_sent_total.labels(event_type=event_type).inc()
                except Exception:
                    pass
        except (WebSocketDisconnect, StarletteWSDisconnect, asyncio.CancelledError):
            pass
        except Exception as exc:
            log.debug("lifecycle WS sender stopped conn=%s: %s", conn_id, exc)

    async def _disconnect(self, conn_id: str) -> None:
        task: Optional[asyncio.Task] = None
        async with self._lock:
            if conn_id not in self._connections and conn_id not in self._queues:
                return
            self._connections.pop(conn_id, None)
            self._queues.pop(conn_id, None)
            self._send_locks.pop(conn_id, None)
            self._org_ids.pop(conn_id, None)
            self._user_ids.pop(conn_id, None)
            task = self._sender_tasks.pop(conn_id, None)
            lifecycle_ws_clients_connected.dec()
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        log.info("lifecycle WS disconnected conn=%s", conn_id)
