"""Temporal activities for account cooldown FSM tick (DF-T-07-005)."""
from __future__ import annotations

import logging

from temporalio import activity

log = logging.getLogger(__name__)


class AccountStateActivities:
    @activity.defn(name="process_expired_account_cooldowns")
    async def process_expired_account_cooldowns(self) -> int:
        from db.database import activity_session
        from services.account_state import process_expired_cooldowns

        async with activity_session() as db:
            count = await process_expired_cooldowns(db)
            from services.account_event_recorder import get_account_event_recorder

            await get_account_event_recorder().flush_all()
        if count:
            log.info("cooldown tick: %d account(s) transitioned to active", count)
        return count
