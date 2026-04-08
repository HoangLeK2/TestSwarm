"""
services/account_manager.py — Account usage tracking and cooldown management.

Usage lifecycle:
    start_account_usage(account_id)  → marks last_used_at = now
    end_account_usage(account_id, duration_minutes)  → accumulates usage, triggers cooldown if limit hit
    check_and_reset_cooldowns()  → background task: flip expired cooldowns back to active
    reset_daily_usage()  → background task (midnight): zero usage_today_minutes

Cooldown thresholds are read from env vars:
    ACCOUNT_DAILY_USAGE_LIMIT   (minutes/day, default 30)
    ACCOUNT_COOLDOWN_MINUTES    (cooldown duration, default 120)
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from db.database import AsyncSessionLocal
from db.crud.account import (
    get_account,
    get_expired_cooldown_accounts,
    update_account,
)

logger = logging.getLogger(__name__)

_DAILY_USAGE_LIMIT = float(os.environ.get("ACCOUNT_DAILY_USAGE_LIMIT", "30"))
_COOLDOWN_MINUTES = float(os.environ.get("ACCOUNT_COOLDOWN_MINUTES", "120"))


async def start_account_usage(account_id: str) -> None:
    """Mark the account as actively in use (sets last_used_at to now)."""
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        await update_account(db, account_id, last_used_at=now)
        await db.commit()


async def end_account_usage(account_id: str, duration_minutes: float) -> None:
    """
    Record a completed usage session.

    Accumulates total_usage_minutes and usage_today_minutes. If usage_today_minutes
    reaches or exceeds ACCOUNT_DAILY_USAGE_LIMIT, the account is put into cooldown
    for ACCOUNT_COOLDOWN_MINUTES minutes.
    """
    if duration_minutes <= 0:
        return

    async with AsyncSessionLocal() as db:
        account = await get_account(db, account_id)
        if not account:
            logger.warning("end_account_usage: account %s not found", account_id)
            return

        now = datetime.now(timezone.utc)
        today = now.date()

        # Reset daily counter if we've crossed midnight since last reset.
        new_today = account.usage_today_minutes
        if account.usage_reset_date != today:
            new_today = 0.0

        new_total = (account.usage_today_minutes or 0) + duration_minutes
        new_today = new_today + duration_minutes
        total = (account.total_usage_minutes or 0) + duration_minutes

        kwargs: dict = {
            "total_usage_minutes": total,
            "usage_today_minutes": new_today,
            "usage_reset_date": today,
        }

        if new_today >= _DAILY_USAGE_LIMIT and account.status == "active":
            cooldown_until = now + timedelta(minutes=_COOLDOWN_MINUTES)
            kwargs["status"] = "cooldown"
            kwargs["cooldown_until"] = cooldown_until
            logger.info(
                "Account %s entered cooldown (%.1f min used today). Resumes at %s",
                account_id,
                new_today,
                cooldown_until.isoformat(),
            )

        await update_account(db, account_id, **kwargs)
        await db.commit()


async def check_and_reset_cooldowns() -> int:
    """
    Background task: reset accounts whose cooldown_until has passed back to active.
    Returns the number of accounts reset.
    """
    async with AsyncSessionLocal() as db:
        expired = await get_expired_cooldown_accounts(db)
        if not expired:
            return 0

        now = datetime.now(timezone.utc)
        reset_count = 0
        for account in expired:
            await update_account(
                db,
                account.id,
                status="active",
                cooldown_until=None,
                usage_today_minutes=0.0,
                usage_reset_date=now.date(),
            )
            reset_count += 1
            logger.info("Account %s cooldown expired — reset to active", account.id)

        await db.commit()
        return reset_count


async def reset_daily_usage() -> int:
    """
    Background task (run at midnight): zero out usage_today_minutes for all accounts
    whose usage_reset_date is before today.
    Returns number of accounts reset.
    """
    from sqlalchemy import select, update
    from db.database import AsyncSessionLocal
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
