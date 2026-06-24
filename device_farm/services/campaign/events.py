"""Domain events + metrics for org-scoped campaigns (DF-T-04-006)."""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from db.models.enums import CampaignStatus, ExecutionStatus
from db.models.execution import Execution
from services.activity_logger import log_activity
from tenancy.context import tenant_context

log = logging.getLogger(__name__)

_STATUS_NOTIFICATION_EVENTS = {
    CampaignStatus.RUNNING.value: "campaign.dispatched",
    CampaignStatus.COMPLETED.value: "campaign.completed",
    CampaignStatus.FAILED.value: "campaign.failed",
}
_POST_COMMIT_NOTIFICATION_TASKS = "campaign_notification_payloads"
_NOTIFICATION_QUEUE_MAX_SIZE = 500
_NOTIFICATION_WORKER_COUNT = 4
_NOTIFICATION_WORKER_IDLE_TIMEOUT_SECONDS = 30.0
_notification_queue: asyncio.Queue[dict] | None = None
_notification_queue_loop: asyncio.AbstractEventLoop | None = None
_notification_workers: set[asyncio.Task] = set()


@event.listens_for(Session, "after_commit")
def _schedule_campaign_notifications_after_commit(session: Session) -> None:
    payloads = session.info.pop(_POST_COMMIT_NOTIFICATION_TASKS, [])
    for payload in payloads:
        _schedule_campaign_notification(payload)


@event.listens_for(Session, "after_rollback")
def _discard_campaign_notifications_after_rollback(session: Session) -> None:
    session.info.pop(_POST_COMMIT_NOTIFICATION_TASKS, None)


async def emit_campaign_domain_event(
    db: AsyncSession,
    *,
    event: str,
    org_id: str,
    campaign_id: str,
    user_id: str | None = None,
    details: dict | None = None,
    before_state: dict | None = None,
    after_state: dict | None = None,
    reason: str | None = None,
    ip_address: str | None = None,
) -> None:
    payload = {"campaign_id": campaign_id, "organization_id": org_id, **(details or {})}
    await log_activity(
        db,
        action=event,
        entity_type="campaign",
        entity_id=campaign_id,
        user_id=user_id,
        org_id=org_id,
        ip_address=ip_address,
        before_state=before_state,
        after_state=after_state,
        reason=reason,
        details=payload,
    )
    try:
        from services.webhook_dispatcher import dispatch_webhook

        await dispatch_webhook(org_id, event, payload)
    except Exception as exc:
        log.debug("campaign webhook %s: %s", event, exc)

    try:
        from web.metrics import (
            campaign_archived_total,
            campaign_created_total,
            campaign_status_transition_total,
        )

        if event == "campaign.created":
            campaign_created_total.inc()
        elif event == "campaign.archived":
            campaign_archived_total.inc()
        elif event == "campaign.status.changed":
            campaign_status_transition_total.labels(
                from_status=details.get("from", "unknown"),
                to_status=details.get("to", "unknown"),
            ).inc()
    except Exception as exc:
        log.debug("campaign metrics %s: %s", event, exc)


async def emit_campaign_status_changed(
    db: AsyncSession,
    *,
    org_id: str,
    campaign_id: str,
    campaign_name: str | None = None,
    from_status: str,
    to_status: str,
    user_id: str | None = None,
    reason: str | None = None,
    force: bool = False,
) -> None:
    details = {
        "from": from_status,
        "to": to_status,
        "reason": reason,
        "force": force,
    }
    await emit_campaign_domain_event(
        db,
        event="campaign.status.changed",
        org_id=org_id,
        campaign_id=campaign_id,
        user_id=user_id,
        before_state={"status": from_status},
        after_state={"status": to_status},
        reason=reason,
        details=details,
    )
    await _emit_campaign_status_notification(
        db,
        org_id=org_id,
        campaign_id=campaign_id,
        campaign_name=campaign_name,
        to_status=to_status,
        user_id=user_id,
        reason=reason,
    )


async def _campaign_execution_counts(
    db: AsyncSession,
    campaign_id: str,
    *,
    dispatch_id: str | None = None,
) -> dict[str, int]:
    stmt = select(Execution.status, func.count()).where(Execution.campaign_id == campaign_id)
    if dispatch_id:
        stmt = stmt.where(Execution.meta["dispatch_id"].as_string() == dispatch_id)
    result = await db.execute(
        stmt.group_by(Execution.status)
    )
    return {str(status): int(count) for status, count in result.all()}


async def _latest_campaign_dispatch_id(
    db: AsyncSession,
    campaign_id: str,
) -> str | None:
    result = await db.execute(
        select(Execution.meta["dispatch_id"].as_string())
        .where(
            Execution.campaign_id == campaign_id,
            Execution.meta["dispatch_id"].as_string().is_not(None),
        )
        .order_by(Execution.created_at.desc())
        .limit(1)
    )
    value = result.scalar_one_or_none()
    return str(value).strip() if value else None


async def _emit_campaign_status_notification(
    db: AsyncSession,
    *,
    org_id: str,
    campaign_id: str,
    campaign_name: str | None,
    to_status: str,
    user_id: str | None,
    reason: str | None,
) -> None:
    event_type = _STATUS_NOTIFICATION_EVENTS.get(to_status)
    if not event_type:
        return
    try:
        dispatch_id = await _latest_campaign_dispatch_id(db, campaign_id)
        counts = await _campaign_execution_counts(
            db,
            campaign_id,
            dispatch_id=dispatch_id,
        )
        execution_total = sum(counts.values())
        execution_completed = counts.get(ExecutionStatus.COMPLETED.value, 0)
        execution_failed = counts.get(ExecutionStatus.FAILED.value, 0)
        execution_cancelled = counts.get(ExecutionStatus.CANCELLED.value, 0)
        collected_count = 0
        if event_type in {"campaign.completed", "campaign.failed"}:
            from db.crud.content import count_by_campaign

            collected_count = await count_by_campaign(
                db,
                campaign_id,
                user_id=user_id,
                dispatch_id=dispatch_id,
            )

        if event_type == "campaign.dispatched":
            summary = f"Campaign dispatched to {execution_total} execution(s)"
        elif event_type == "campaign.completed":
            summary = f"Campaign completed with {collected_count} collected item(s)"
        else:
            summary = f"Campaign failed: {reason or 'unknown'}"

        from core.env import device_farm_frontend_url

        _enqueue_campaign_notification_after_commit(
            db,
            {
                "type": event_type,
                "org_id": org_id,
                "campaign_id": campaign_id,
                "resource_name": campaign_name or campaign_id,
                "summary": summary,
                "status": to_status,
                "collected_count": collected_count,
                "execution_total": execution_total,
                "execution_completed": execution_completed,
                "execution_failed": execution_failed,
                "execution_cancelled": execution_cancelled,
                "dispatch_id": dispatch_id,
                "error_message": reason,
                "actor_user_id": user_id,
                "recipient_user_id": user_id,
                "app_base_url": device_farm_frontend_url(),
            },
        )
    except Exception as exc:
        log.warning(
            "campaign notification skipped event=%s campaign_id=%s: %s",
            event_type,
            campaign_id,
            exc,
        )


async def emit_campaign_step_warning(
    db: AsyncSession,
    *,
    org_id: str,
    campaign_id: str,
    campaign_name: str | None = None,
    execution_id: str | None = None,
    device_serial: str | None = None,
    step_index: int | str | None = None,
    step_type: str | None = None,
    message: str | None = None,
    user_id: str | None = None,
) -> None:
    error_message = str(message or "step warning").strip()
    payload = {
        "campaign_id": campaign_id,
        "resource_name": campaign_name or campaign_id,
        "status": "warning",
        "execution_id": execution_id,
        "device_serial": device_serial,
        "step_index": step_index,
        "step_type": step_type or "unknown",
        "error_message": error_message,
    }
    await emit_campaign_domain_event(
        db,
        event="campaign.step_warning",
        org_id=org_id,
        campaign_id=campaign_id,
        user_id=user_id,
        reason=error_message,
        details=payload,
    )
    try:
        from core.env import device_farm_frontend_url

        _enqueue_campaign_notification_after_commit(
            db,
            {
                "type": "campaign.step_warning",
                "org_id": org_id,
                "campaign_id": campaign_id,
                "resource_name": campaign_name or campaign_id,
                "summary": f"Step {step_type or 'unknown'} warning: {error_message}",
                "status": "warning",
                "execution_id": execution_id,
                "device_serial": device_serial,
                "step_index": step_index,
                "step_type": step_type or "unknown",
                "error_message": error_message,
                "actor_user_id": user_id,
                "recipient_user_id": user_id,
                "app_base_url": device_farm_frontend_url(),
            },
        )
    except Exception as exc:
        log.warning(
            "campaign step warning notification skipped campaign_id=%s execution_id=%s: %s",
            campaign_id,
            execution_id,
            exc,
        )


def _enqueue_campaign_notification_after_commit(
    db: AsyncSession,
    payload: dict,
) -> None:
    sync_session = getattr(db, "sync_session", None)
    if sync_session is None:
        _schedule_campaign_notification(payload)
        return
    sync_session.info.setdefault(_POST_COMMIT_NOTIFICATION_TASKS, []).append(payload)


def _schedule_campaign_notification(payload: dict) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        log.warning(
            "campaign notification skipped after commit event=%s campaign_id=%s: no running loop",
            payload.get("type"),
            payload.get("campaign_id"),
        )
        return
    queue = _notification_queue_for_loop(loop)
    try:
        queue.put_nowait(payload)
    except asyncio.QueueFull:
        log.warning(
            "campaign notification queue full, dropped event=%s campaign_id=%s",
            payload.get("type"),
            payload.get("campaign_id"),
        )


def _notification_queue_for_loop(
    loop: asyncio.AbstractEventLoop,
) -> asyncio.Queue[dict]:
    global _notification_queue, _notification_queue_loop, _notification_workers

    if _notification_queue is None or _notification_queue_loop is not loop:
        _notification_queue = asyncio.Queue(maxsize=_NOTIFICATION_QUEUE_MAX_SIZE)
        _notification_queue_loop = loop
        _notification_workers = set()

    _notification_workers = {
        task for task in _notification_workers if not task.done()
    }
    while len(_notification_workers) < _NOTIFICATION_WORKER_COUNT:
        task = loop.create_task(
            _campaign_notification_worker(_notification_queue),
            name="campaign-notification-worker",
        )
        task.add_done_callback(_log_campaign_notification_worker_result)
        _notification_workers.add(task)
    return _notification_queue


async def _campaign_notification_worker(queue: asyncio.Queue[dict]) -> None:
    while True:
        try:
            payload = await asyncio.wait_for(
                queue.get(),
                timeout=_NOTIFICATION_WORKER_IDLE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            return
        try:
            await _deliver_campaign_notification(payload)
        except Exception as exc:
            log.warning(
                "campaign notification delivery failed event=%s campaign_id=%s: %s",
                payload.get("type"),
                payload.get("campaign_id"),
                exc,
            )
        finally:
            queue.task_done()


def _log_campaign_notification_worker_result(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    try:
        task.result()
    except Exception as exc:
        log.warning("campaign notification worker stopped: %s", exc)


async def _deliver_campaign_notification(payload: dict) -> None:
    from services.notification_events import parse_domain_event, render_notification

    domain_event = parse_domain_event(payload)
    rendered = render_notification(
        domain_event,
        locale=str(payload.get("locale") or "en"),
        app_base_url=str(payload.get("app_base_url") or "").strip(),
    )
    data = {
        **(domain_event.payload or {}),
        "resource_type": domain_event.resource_type,
        "resource_id": domain_event.resource_id,
        "deep_link": rendered.deep_link,
        "template_version": rendered.template_version,
    }
    with tenant_context(domain_event.org_id):
        await _notification_service_for_background().notify(
            domain_event.event_type,
            rendered.title,
            rendered.body,
            data,
            user_id=domain_event.recipient_user_id,
        )


def _notification_service_for_background():
    from services.notification_service import NotificationService

    return NotificationService()
