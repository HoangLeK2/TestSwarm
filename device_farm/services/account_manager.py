"""
services/account_manager.py — Account usage tracking and cooldown management.

Usage lifecycle:
    start_account_usage(account_id)  → marks last_used_at = now
    end_account_usage(account_id, duration_minutes)  → accumulates usage, triggers cooldown if limit hit
    check_and_reset_cooldowns()  → background task: flip expired cooldowns back to active
    reset_daily_usage()  → background task (midnight): zero usage_today_minutes
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from db.database import AsyncSessionLocal
from db.crud.account import get_account, update_account
from db.models.enums import AccountEventType, AccountState
from services.account_state import AccountStateService
from services.account_event_recorder import get_account_event_recorder

logger = logging.getLogger(__name__)

_DAILY_USAGE_LIMIT = float(os.environ.get("ACCOUNT_DAILY_USAGE_LIMIT", "30"))
_COOLDOWN_MINUTES = float(os.environ.get("ACCOUNT_COOLDOWN_MINUTES", "120"))


async def start_account_usage(
    account_id: str,
    *,
    user_id: str | None = None,
    device_serial: str | None = None,
    platform: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    session_id: str | None = None,
) -> None:
    """Mark the account as actively in use (sets last_used_at to now)."""
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        account = await update_account(
            db, account_id, last_used_at=now, reload=False
        )
        await db.commit()
        if not account:
            return
        plat = platform or account.platform
        uid = user_id or account.user_id
    get_account_event_recorder().record(
        account_id=account_id,
        event_type=AccountEventType.USAGE_STARTED,
        user_id=uid,
        device_serial=device_serial,
        platform=plat,
        entity_type=entity_type,
        entity_id=entity_id,
        details={"session_id": session_id} if session_id else {},
    )
    await get_account_event_recorder().flush_all()


async def end_account_usage(
    account_id: str,
    duration_minutes: float,
    *,
    user_id: str | None = None,
    device_serial: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    end_reason: str | None = None,
) -> None:
    """
    Record a completed usage session.

    Accumulates total_usage_minutes and usage_today_minutes. If usage_today_minutes
    reaches or exceeds ACCOUNT_DAILY_USAGE_LIMIT, the account is put into cooldown
    for ACCOUNT_COOLDOWN_MINUTES minutes.
    """
    if duration_minutes <= 0:
        duration_minutes = 0.0

    entered_cooldown = False
    async with AsyncSessionLocal() as db:
        account = await get_account(db, account_id)
        if not account:
            logger.warning("end_account_usage: account %s not found", account_id)
            return

        now = datetime.now(timezone.utc)
        today = now.date()

        new_today = account.usage_today_minutes
        if account.usage_reset_date != today:
            new_today = 0.0

        new_today = new_today + duration_minutes
        total = (account.total_usage_minutes or 0) + duration_minutes

        kwargs: dict = {
            "total_usage_minutes": total,
            "usage_today_minutes": new_today,
            "usage_reset_date": today,
        }

        await update_account(db, account_id, reload=False, **kwargs)

        effective_state = getattr(account, "state", None) or account.status
        if new_today >= _DAILY_USAGE_LIMIT and effective_state == AccountState.ACTIVE.value:
            try:
                svc = AccountStateService()
                await svc.transition(
                    db,
                    account_id,
                    to=AccountState.COOLDOWN,
                    reason="daily usage limit reached",
                    ttl_seconds=int(_COOLDOWN_MINUTES * 60),
                    actor="system",
                )
                entered_cooldown = True
                logger.info(
                    "Account %s entered cooldown (%.1f min used today)",
                    account_id,
                    new_today,
                )
            except Exception as exc:
                logger.warning("account cooldown FSM transition failed: %s", exc)

        await db.commit()

        rec = get_account_event_recorder()
        rec.record(
            account_id=account_id,
            event_type=AccountEventType.USAGE_ENDED,
            user_id=user_id or account.user_id,
            device_serial=device_serial,
            platform=account.platform,
            entity_type=entity_type,
            entity_id=entity_id,
            details={
                "duration_minutes": round(duration_minutes, 2),
                "end_reason": end_reason,
            },
        )
        if entered_cooldown:
            rec.record(
                account_id=account_id,
                event_type=AccountEventType.COOLDOWN_ENTERED,
                user_id=user_id or account.user_id,
                platform=account.platform,
                details={
                    "usage_today_minutes": new_today,
                    "cooldown_minutes": _COOLDOWN_MINUTES,
                },
            )
        async with AsyncSessionLocal() as flush_db:
            while rec._pending:
                n = await rec.flush(flush_db)
                if n == 0:
                    break


async def check_and_reset_cooldowns() -> int:
    """
    Background task: FSM transition cooldown → active when TTL elapsed.
    Returns the number of accounts reset.
    """
    from services.account_state import process_expired_cooldowns

    async with AsyncSessionLocal() as db:
        reset_count = await process_expired_cooldowns(db)
        await db.commit()
        rec = get_account_event_recorder()
        while rec._pending:
            if await rec.flush(db) == 0:
                break
        return reset_count


async def reset_daily_usage() -> int:
    """
    Background task (run at midnight): zero out usage_today_minutes for all accounts
    whose usage_reset_date is before today.
    Returns number of accounts reset.
    """
    from sqlalchemy import update
    from db.models.account import Account

    today = datetime.now(timezone.utc).date()
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(Account)
            .where(Account.usage_reset_date < today)
            .values(usage_today_minutes=0.0, usage_reset_date=today)
            .returning(Account.id)
        )
        rows = list(result.scalars().all())
        await db.commit()
        if rows:
            logger.info("Daily usage reset for %d accounts", len(rows))
        return len(rows)
