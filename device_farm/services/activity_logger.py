from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import AsyncSessionLocal, activity_session
from db.models.activity import ActivityLog
from db.models.device import Device

log = logging.getLogger(__name__)


async def log_activity(
    db: AsyncSession,
    *,
    action: str,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    device_serial: Optional[str] = None,
    user_id: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
) -> ActivityLog:
    record = ActivityLog(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        device_serial=device_serial,
        user_id=user_id,
        details=details or {},
    )
    db.add(record)
    await db.flush()
    return record


async def _resolve_device_user(db: AsyncSession, serial: str | None) -> Optional[str]:
    if not serial:
        return None
    result = await db.execute(select(Device.user_id).where(Device.serial == serial))
    return result.scalar_one_or_none()


def _device_event_to_activity(entry: dict[str, Any]) -> Optional[tuple[str, dict[str, Any]]]:
    raw_event = str(entry.get("event") or "")
    if raw_event in {"connected", "reconnected"}:
        return "device.connect", {
            "raw_event": raw_event,
            "brand": entry.get("device_brand"),
            "model": entry.get("device_model"),
        }
    if raw_event in {"disconnected", "dead"}:
        return "device.disconnect", {
            "raw_event": raw_event,
            "reason": entry.get("reason"),
            "old_state": entry.get("old_state"),
            "new_state": entry.get("new_state"),
            "brand": entry.get("device_brand"),
            "model": entry.get("device_model"),
        }
    if raw_event == "error":
        return "device.error", {
            "reason": entry.get("reason"),
            "old_state": entry.get("old_state"),
            "new_state": entry.get("new_state"),
            "brand": entry.get("device_brand"),
            "model": entry.get("device_model"),
        }
    return None


def activity_to_dict(row: ActivityLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "action": row.action,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "device_serial": row.device_serial,
        "user_id": row.user_id,
        "details": row.details or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


class ActivityLogger:
    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def bind_device_events(self, recorder) -> None:
        recorder.add_listener(self._on_device_event)

    def _on_device_event(self, entry: dict[str, Any]) -> None:
        if self._loop is None:
            return
        mapped = _device_event_to_activity(entry)
        if mapped is None:
            return
        action, details = mapped
        asyncio.run_coroutine_threadsafe(
            self._log_device_event(entry, action, details),
            self._loop,
        )

    async def _log_device_event(
        self,
        entry: dict[str, Any],
        action: str,
        details: dict[str, Any],
    ) -> None:
        serial = str(entry.get("serial") or "")
        try:
            async with AsyncSessionLocal() as db:
                user_id = await _resolve_device_user(db, serial)
                await log_activity(
                    db,
                    action=action,
                    entity_type="device",
                    entity_id=None,
                    device_serial=serial,
                    user_id=user_id,
                    details={
                        **details,
                        "device_event_id": entry.get("id"),
                    },
                )
                await db.commit()
        except Exception as exc:
            log.warning("activity device-event write failed serial=%s action=%s: %s", serial, action, exc)


def log_task_activity_sync(task, serial: str, duration_seconds: float | None) -> None:
    """Best-effort task activity logging from dispatcher worker threads."""
    if not getattr(task, "status", None):
        return
    status = str(getattr(task.status, "value", task.status))
    if status not in {"DONE", "FAILED"}:
        return

    async def _write() -> None:
        async with activity_session() as db:
            user_id = await _resolve_device_user(db, serial)
            await log_activity(
                db,
                action="task.done" if status == "DONE" else "task.failed",
                entity_type="task",
                entity_id=getattr(task, "id", None),
                device_serial=serial,
                user_id=user_id,
                details={
                    "name": getattr(task, "name", "") or getattr(getattr(task, "fn", None), "__name__", "task"),
                    "priority": getattr(task, "priority", None),
                    "retry_count": getattr(task, "retry_count", None),
                    "max_retries": getattr(task, "max_retries", None),
                    "duration_seconds": duration_seconds,
                    "error": getattr(task, "error", None),
                    "started_at": (
                        task.started_at.isoformat()
                        if getattr(task, "started_at", None)
                        else None
                    ),
                    "finished_at": (
                        task.finished_at.isoformat()
                        if getattr(task, "finished_at", None)
                        else datetime.now(timezone.utc).isoformat()
                    ),
                },
            )

    try:
        asyncio.run(_write())
    except Exception as exc:
        log.warning("activity task write failed task=%s serial=%s: %s", getattr(task, "id", None), serial, exc)
