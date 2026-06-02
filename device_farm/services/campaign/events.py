"""Domain events + metrics for org-scoped campaigns (DF-T-04-006)."""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from services.activity_logger import log_activity

log = logging.getLogger(__name__)


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
