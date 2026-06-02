"""Execution event publisher with transactional outbox (DF-T-04-013)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from db.crud.execution import get_execution
from db.crud.execution_events import insert_execution_event
from db.models.execution import Execution
from db.models.execution_event import ExecutionEvent
from services.execution.event_types import SCHEMA_VERSION

log = logging.getLogger(__name__)


async def resolve_execution_org_id(
    db: AsyncSession,
    execution: Execution | str,
) -> str:
    """Resolve org for an execution without requiring request tenant context."""
    row = execution if isinstance(execution, Execution) else await get_execution(db, execution)
    if row is None:
        return ""
    org_id = (row.org_id or "").strip()
    if org_id:
        return org_id
    meta_org = (row.meta or {}).get("org_id")
    if meta_org:
        return str(meta_org)
    if row.campaign_id:
        from db.crud.campaign_entity import lookup_campaign_org_id

        looked = await lookup_campaign_org_id(db, row.campaign_id)
        return looked or ""
    return ""


async def resolve_execution_event_context(
    db: AsyncSession,
    execution: Execution | str,
) -> tuple[Execution | None, str, str | None]:
    row = execution if isinstance(execution, Execution) else await get_execution(db, execution)
    if row is None:
        return None, "", None
    org_id = await resolve_execution_org_id(db, row)
    return row, org_id, row.campaign_id


async def enqueue_execution_event(
    db: AsyncSession,
    *,
    event_type: str,
    execution_id: str,
    payload: Optional[dict[str, Any]] = None,
    organization_id: Optional[str] = None,
    campaign_id: Optional[str] = None,
    step_id: Optional[str] = None,
    occurred_at: Optional[datetime] = None,
    execution: Execution | None = None,
) -> ExecutionEvent | None:
    """Write event to outbox in the current DB transaction (atomic with caller flush/commit)."""
    if execution is None:
        execution = await get_execution(db, execution_id)
    if execution is None:
        log.warning("enqueue_execution_event: execution %s not found", execution_id)
        return None

    org_id = organization_id or ""
    camp_id = campaign_id if campaign_id is not None else execution.campaign_id
    if not org_id:
        org_id = await resolve_execution_org_id(db, execution)
    if not org_id:
        log.debug("enqueue_execution_event: skip %s — no org_id", event_type)
        return None

    row = await insert_execution_event(
        db,
        event_type=event_type,
        organization_id=org_id,
        execution_id=execution_id,
        campaign_id=camp_id,
        step_id=step_id,
        payload=payload or {},
        schema_version=SCHEMA_VERSION,
        occurred_at=occurred_at,
    )
    return row


async def publish_envelope_to_bus(envelope: dict[str, Any]) -> None:
    from services.execution.event_bus import get_execution_event_bus

    await get_execution_event_bus().publish(envelope["execution_id"], envelope)


async def publish_row_to_broker(envelope: dict[str, Any]) -> None:
    """Hook for Kafka/NATS — currently in-process bus only."""
    await publish_envelope_to_bus(envelope)
    try:
        from web.metrics import execution_events_published_total

        execution_events_published_total.labels(event_type=envelope["event_type"]).inc()
    except Exception:
        pass


async def process_outbox_batch(db: AsyncSession, *, limit: int = 100) -> int:
    from db.crud.execution_events import (
        fetch_unpublished_events,
        increment_publish_attempt,
        mark_event_published,
    )

    rows = await fetch_unpublished_events(db, limit=limit)
    published = 0
    for row in rows:
        envelope = row.to_envelope()
        try:
            await publish_row_to_broker(envelope)
            await mark_event_published(db, row.id)
            published += 1
        except Exception as exc:
            await increment_publish_attempt(db, row.id)
            log.warning("outbox publish failed event=%s: %s", row.event_id[:8], exc)
    if published:
        await db.flush()
    return published
