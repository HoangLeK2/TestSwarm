"""Security-sensitive activity events via ActivityLog (DF-T-01-005)."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from services.activity_logger import log_activity
from services.user_action_audit import sanitize_audit_value

log = logging.getLogger(__name__)


async def emit_security_event(
    db: AsyncSession,
    *,
    action: str,
    user_id: str | None = None,
    org_id: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    safe_details = {
        str(k): sanitize_audit_value(str(k), v) for k, v in (details or {}).items()
    }
    if ip_address:
        safe_details["ip"] = ip_address
    if user_agent:
        safe_details["user_agent"] = user_agent[:255]

    try:
        record = await log_activity(
            db,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            user_id=user_id,
            org_id=org_id,
            ip_address=ip_address,
            user_agent=user_agent,
            outcome="success",
            details=safe_details,
        )
        await db.flush()
    except Exception:
        log.warning("security audit emit failed action=%s", action, exc_info=True)
