"""DLQ domain events (DF-T-04-012)."""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from services.activity_logger import log_activity

log = logging.getLogger(__name__)


async def emit_dlq_domain_event(
    db: AsyncSession,
    *,
    event: str,
    org_id: str,
    execution_id: str,
    user_id: str | None = None,
    details: dict | None = None,
    before_state: dict | None = None,
    after_state: dict | None = None,
    reason: str | None = None,
    ip_address: str | None = None,
) -> None:
    payload = {
        "execution_id": execution_id,
        "organization_id": org_id,
        **(details or {}),
    }
    await log_activity(
        db,
        action=event,
        entity_type="execution",
        entity_id=execution_id,
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
        log.debug("dlq webhook %s: %s", event, exc)

    try:
        from web.metrics import (
            dlq_closed_total,
            dlq_opened_total,
            dlq_replayed_total,
        )

        if event == "execution.dlq.opened":
            dlq_opened_total.inc()
        elif event == "execution.dlq.replayed":
            dlq_replayed_total.inc()
        elif event == "execution.dlq.closed":
            dlq_closed_total.inc()
    except Exception as exc:
        log.debug("dlq metrics %s: %s", event, exc)
