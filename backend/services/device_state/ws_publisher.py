"""Bridge device FSM events to authenticated lifecycle WebSocket stream (DF-T-02-015)."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Callable, Optional

from sqlalchemy import select

from db.database import AsyncSessionLocal
from db.models.device import Device
from db.models.device_fsm import DeviceFsmSnapshot
from db.models.enums import DeviceFsmState
from services.device_state.events import DeviceStateChangedEvent, add_device_state_listener
from services.device_state.lifecycle_schema import (
    LifecycleEventType,
    LifecycleSnapshot,
    LifecycleSnapshotDevice,
    map_fsm_event_type,
    new_lifecycle_event,
)
from services.device_state.replay_store import replay_store
from tenancy.context import tenant_context

log = logging.getLogger(__name__)

DEBOUNCE_MS = max(10, int(os.environ.get("DEVICE_LIFECYCLE_DEBOUNCE_MS", "75")))


class DeviceLifecyclePublisher:
    """Debounced org-scoped publisher for lifecycle WebSocket consumers."""

    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws_manager: Any = None
        self._org_device_cache: dict[str, tuple[str, float]] = {}
        self._pending_by_org: dict[str, dict[str, dict[str, Any]]] = {}
        self._flush_tasks: dict[str, asyncio.Task] = {}
        self._enqueue_lock = asyncio.Lock()
        self._unsubscribe: Optional[Callable[[], None]] = None

    def bind_ws_manager(self, ws_manager: Any) -> None:
        self._ws_manager = ws_manager

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def start(self) -> None:
        if self._unsubscribe is not None:
            return
        self._unsubscribe = add_device_state_listener(self._on_fsm_event)
        log.info("device lifecycle WS publisher started (debounce=%sms)", DEBOUNCE_MS)

    def stop(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        for task in list(self._flush_tasks.values()):
            if not task.done():
                task.cancel()
        self._flush_tasks.clear()

    def _on_fsm_event(self, event: DeviceStateChangedEvent) -> None:
        if self._loop is None or self._ws_manager is None:
            return
        try:
            running = asyncio.get_running_loop()
            if running is self._loop:
                running.create_task(self._enqueue_fsm_event(event))
                return
        except RuntimeError:
            pass
        asyncio.run_coroutine_threadsafe(self._enqueue_fsm_event(event), self._loop)

    async def publish_unpaired(
        self,
        *,
        device_id: str,
        organization_id: str,
        from_state: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        lifecycle = new_lifecycle_event(
            event_type=LifecycleEventType.DEVICE_UNPAIRED,
            organization_id=organization_id,
            device_id=device_id,
            from_state=from_state,
            to_state=None,
            session_id=session_id,
        )
        self._org_device_cache.pop(device_id, None)
        await self._publish_now(lifecycle)

    async def build_snapshot(self, organization_id: str) -> LifecycleSnapshot:
        devices: list[LifecycleSnapshotDevice] = []
        try:
            async with AsyncSessionLocal() as db:
                with tenant_context(organization_id):
                    dev_rows = await db.execute(
                        select(Device.id).where(Device.org_id == organization_id)
                    )
                    device_ids = [row[0] for row in dev_rows.all()]
                    if device_ids:
                        snap_rows = await db.execute(
                            select(DeviceFsmSnapshot).where(
                                DeviceFsmSnapshot.device_id.in_(device_ids)
                            )
                        )
                        for row in snap_rows.scalars():
                            devices.append(
                                LifecycleSnapshotDevice(
                                    device_id=row.device_id,
                                    state=row.state,
                                    session_id=row.session_id,
                                    updated_at=row.updated_at,
                                )
                            )
                    known = {d.device_id for d in devices}
                    for device_id in device_ids:
                        if device_id not in known:
                            devices.append(
                                LifecycleSnapshotDevice(
                                    device_id=device_id,
                                    state=DeviceFsmState.UNKNOWN.value,
                                )
                            )
        except Exception as exc:
            log.warning("lifecycle snapshot build failed org=%s: %s", organization_id, exc)

        return LifecycleSnapshot(
            organization_id=organization_id,
            devices=devices,
            replay=replay_store.recent(organization_id),
        )

    async def _enqueue_fsm_event(self, event: DeviceStateChangedEvent) -> None:
        org_id = await self._resolve_org_id(event.device_id)
        if not org_id:
            log.debug("lifecycle publish skipped: unknown org for device=%s", event.device_id)
            return

        session_id = event.session_id
        if not session_id and event.payload:
            session_id = event.payload.get("session_id")

        lifecycle = new_lifecycle_event(
            event_type=map_fsm_event_type(event.event),
            organization_id=org_id,
            device_id=event.device_id,
            from_state=event.from_state,
            to_state=event.to_state,
            session_id=session_id,
            source=event.source,
            event_id=event.event_id,
            payload=event.payload,
        )
        async with self._enqueue_lock:
            org_bucket = self._pending_by_org.setdefault(org_id, {})
            org_bucket[event.device_id] = lifecycle.to_dict()
            existing = self._flush_tasks.get(org_id)
            if existing is None or existing.done():
                self._flush_tasks[org_id] = asyncio.create_task(self._debounced_flush(org_id))

    async def _debounced_flush(self, org_id: str) -> None:
        await asyncio.sleep(DEBOUNCE_MS / 1000.0)
        batch = list(self._pending_by_org.pop(org_id, {}).values())
        self._flush_tasks.pop(org_id, None)
        if not batch:
            return
        try:
            if len(batch) == 1:
                await self._publish_dict(org_id, batch[0])
            else:
                await self._publish_batch(org_id, batch)
        except Exception as exc:
            log.warning("lifecycle debounced flush failed org=%s count=%s: %s", org_id, len(batch), exc)

    async def _publish_now(self, lifecycle: Any) -> None:
        await self._publish_dict(lifecycle.organization_id, lifecycle.to_dict())

    async def _publish_dict(self, org_id: str, payload: dict[str, Any]) -> None:
        if not self._ws_manager:
            return
        replay_store.append(org_id, payload)
        await self._ws_manager.broadcast_to_org(org_id, {"type": "lifecycle.event", "event": payload})

    async def _publish_batch(self, org_id: str, events: list[dict[str, Any]]) -> None:
        if not self._ws_manager:
            return
        for event in events:
            replay_store.append(org_id, event)
        await self._ws_manager.broadcast_to_org(
            org_id,
            {"type": "lifecycle.batch", "events": events, "organization_id": org_id},
        )

    async def _resolve_org_id(self, device_id: str) -> Optional[str]:
        cached = self._org_device_cache.get(device_id)
        if cached is not None:
            return cached[0]
        try:
            async with AsyncSessionLocal() as db:
                device_table = Device.__table__
                result = await db.execute(
                    select(device_table.c.org_id).where(device_table.c.id == device_id)
                )
                org_id = result.scalar_one_or_none()
                if org_id:
                    self._org_device_cache[device_id] = (org_id, time.monotonic())
                return org_id
        except Exception as exc:
            log.debug("resolve org for device=%s failed: %s", device_id, exc)
            return None


publisher = DeviceLifecyclePublisher()
