"""Domain events + metrics for org-scoped scenarios (DF-T-04-001)."""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from services.activity_logger import log_activity

log = logging.getLogger(__name__)


async def emit_scenario_domain_event(
    db: AsyncSession,
    *,
    event: str,
    org_id: str,
    scenario_id: str,
    user_id: str | None = None,
    details: dict | None = None,
) -> None:
    payload = {"scenario_id": scenario_id, "organization_id": org_id, **(details or {})}
    await log_activity(
        db,
        action=event,
        entity_type="org_scenario",
        entity_id=scenario_id,
        user_id=user_id,
        org_id=org_id,
        details=payload,
    )
    try:
        from services.webhook_dispatcher import dispatch_webhook

        await dispatch_webhook(org_id, event, payload)
    except Exception as exc:
        log.debug("scenario webhook %s: %s", event, exc)

    try:
        from web.metrics import scenario_archived_total, scenario_created_total

        if event == "scenario.created":
            scenario_created_total.inc()
        elif event == "scenario.archived":
            scenario_archived_total.inc()
    except Exception as exc:
        log.debug("scenario metrics %s: %s", event, exc)
