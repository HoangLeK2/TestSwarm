"""Periodic reconciliation for stale account action ledger entries."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import AsyncSessionLocal
from services.account_actions.service import ledger_mode, reconcile_stale_actions
from web.metrics import (
    account_action_reconcile_duration_seconds,
    account_action_reconcile_runs_total,
    account_actions_reconciled_total,
)

log = logging.getLogger(__name__)

ACCOUNT_ACTION_RECONCILE_ADVISORY_LOCK_KEY = 90207011


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        log.warning("invalid %s=%r; using %s", name, raw, default)
        return default
    return min(max(value, minimum), maximum)


def reconcile_interval_seconds() -> int:
    return _bounded_env_int("ACCOUNT_ACTION_RECONCILE_INTERVAL_SECONDS", 60, 5, 86400)


def reconcile_stale_after_seconds() -> int:
    return _bounded_env_int(
        "ACCOUNT_ACTION_RECONCILE_STALE_AFTER_SECONDS", 3600, 60, 2592000
    )


async def _try_advisory_lock(db: AsyncSession) -> bool:
    if db.get_bind().dialect.name != "postgresql":
        return True
    result = await db.execute(
        text("SELECT pg_try_advisory_lock(:key)"),
        {"key": ACCOUNT_ACTION_RECONCILE_ADVISORY_LOCK_KEY},
    )
    return bool(result.scalar())


async def _advisory_unlock(db: AsyncSession) -> None:
    if db.get_bind().dialect.name == "postgresql":
        await db.execute(
            text("SELECT pg_advisory_unlock(:key)"),
            {"key": ACCOUNT_ACTION_RECONCILE_ADVISORY_LOCK_KEY},
        )


async def run_account_action_reconcile_once() -> int:
    """Mark stale active ledger actions, once per cluster."""
    if ledger_mode() == "disabled":
        account_action_reconcile_runs_total.labels(status="disabled").inc()
        log.debug("account action reconciliation skipped: ledger disabled")
        return 0

    started = time.perf_counter()
    status = "success"
    reconciled = 0
    async with AsyncSessionLocal() as db:
        locked = False
        try:
            async with db.begin():
                locked = await _try_advisory_lock(db)
                if not locked:
                    account_action_reconcile_runs_total.labels(status="locked").inc()
                    log.debug("account action reconciliation skipped: advisory lock held by peer")
                    return 0
                reconciled = await reconcile_stale_actions(
                    db,
                    older_than=timedelta(seconds=reconcile_stale_after_seconds()),
                )
        except BaseException:
            status = "error"
            raise
        finally:
            try:
                if locked:
                    unlock = asyncio.create_task(_advisory_unlock(db))
                    try:
                        await asyncio.shield(unlock)
                    except asyncio.CancelledError:
                        await unlock
                        raise
            finally:
                account_action_reconcile_duration_seconds.observe(
                    time.perf_counter() - started
                )
                account_action_reconcile_runs_total.labels(status=status).inc()

    if reconciled:
        account_actions_reconciled_total.inc(reconciled)
        log.info("account action reconciliation marked %s action(s) stale", reconciled)
    return reconciled


async def account_action_reconcile_loop(*, interval_seconds: int | None = None) -> None:
    """Run reconciliation immediately and then at the configured cadence."""
    interval = interval_seconds or reconcile_interval_seconds()
    while True:
        started = time.perf_counter()
        try:
            await run_account_action_reconcile_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("account action reconciliation failed")
        elapsed = time.perf_counter() - started
        await asyncio.sleep(max(0.0, interval - elapsed))
