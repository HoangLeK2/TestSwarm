"""Refresh account_state_total gauge from DB."""
from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.account import Account
from web.metrics import account_state_gauge

log = logging.getLogger(__name__)


async def refresh_account_state_gauges(db: AsyncSession) -> None:
    """Set ``account_state_gauge{platform,state}`` to current row counts."""
    try:
        rows = (
            await db.execute(
                select(Account.platform, Account.state, func.count())
                .group_by(Account.platform, Account.state)
            )
        ).all()
        for platform, state, count in rows:
            account_state_gauge.labels(
                platform=platform or "unknown",
                state=state or "active",
            ).set(int(count or 0))
    except Exception as exc:
        log.debug("account_state_gauge refresh skipped: %s", exc)
