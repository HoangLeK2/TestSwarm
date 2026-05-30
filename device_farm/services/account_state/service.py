"""Account state transitions with optimistic locking and audit (DF-T-07-005)."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.account import Account
from tenancy.context import get_current_org_id, tenant_context
from db.models.enums import AccountState
from services.account_state.events import AccountStateChangedEvent, publish_account_state_changed
from services.account_state.exceptions import (
    InvalidStateTransitionError,
    InvalidTtlError,
    StateConflictError,
)
from services.account_state.fsm import can_transition, normalize_state, transition_error_message
from services.account_state.reason_codes import reason_code
from web.metrics import account_state_gauge, state_transition_total

log = logging.getLogger(__name__)

_COOLDOWN_BATCH = 500


class AccountStateService:
    """Apply FSM transitions on ``accounts.state`` (``status`` kept in sync)."""

    async def transition(
        self,
        db: AsyncSession,
        account_id: str,
        *,
        to: str | AccountState,
        reason: str,
        ttl_seconds: Optional[int] = None,
        actor: str = "system",
        expected_state_changed_at: Optional[datetime] = None,
        skip_row_lock: bool = False,
    ) -> Account:
        if not skip_row_lock:
            account = await self._load_for_update(db, account_id)
        else:
            result = await db.execute(select(Account).where(Account.id == account_id))
            account = result.scalar_one_or_none()

        if account is None:
            raise ValueError(f"account not found: {account_id}")

        if (
            expected_state_changed_at is not None
            and account.state_changed_at is not None
            and account.state_changed_at != expected_state_changed_at
        ):
            raise StateConflictError(
                "account state was modified by another request; retry with fresh state_changed_at"
            )

        from_state = normalize_state(account.state or account.status)
        to_state = normalize_state(to)

        if not can_transition(from_state, to_state):
            raise InvalidStateTransitionError(
                transition_error_message(from_state, to_state)
            )

        now = datetime.now(timezone.utc)
        cooldown_until: Optional[datetime] = account.cooldown_until

        if to_state == AccountState.COOLDOWN:
            if ttl_seconds is None or ttl_seconds <= 0:
                raise InvalidTtlError("ttl_seconds must be a positive integer for cooldown")
            cooldown_until = now + timedelta(seconds=int(ttl_seconds))
        elif to_state == AccountState.ACTIVE:
            cooldown_until = None
        elif from_state == AccountState.COOLDOWN and to_state != AccountState.ACTIVE:
            cooldown_until = None

        values: dict = {
            "state": to_state.value,
            "status": to_state.value,
            "state_reason": (reason or "").strip() or None,
            "state_changed_at": now,
            "cooldown_until": cooldown_until,
            "updated_at": now,
        }
        if to_state == AccountState.ACTIVE and from_state == AccountState.COOLDOWN:
            values["usage_today_minutes"] = 0.0
            values["usage_reset_date"] = now.date()

        stmt = (
            update(Account)
            .where(Account.id == account_id)
            .values(**values)
            .returning(Account)
        )
        if expected_state_changed_at is not None:
            stmt = stmt.where(Account.state_changed_at == expected_state_changed_at)

        result = await db.execute(stmt)
        updated = result.scalar_one_or_none()
        if updated is None:
            if expected_state_changed_at is not None:
                raise StateConflictError(
                    "account state was modified by another request; retry with fresh state_changed_at"
                )
            raise ValueError(f"account not found: {account_id}")

        _emit_transition(updated, from_state.value, to_state.value, reason, ttl_seconds, actor)
        return updated

    async def _load_for_update(
        self, db: AsyncSession, account_id: str
    ) -> Optional[Account]:
        result = await db.execute(
            select(Account).where(Account.id == account_id).with_for_update()
        )
        return result.scalar_one_or_none()


async def _orgs_with_expired_cooldowns(db: AsyncSession) -> list[str]:
    """Distinct org_ids with expired cooldown rows (raw SQL — no tenant context)."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        text(
            """
            SELECT DISTINCT org_id
            FROM accounts
            WHERE state = :state
              AND cooldown_until IS NOT NULL
              AND cooldown_until <= :now
            """
        ),
        {"state": AccountState.COOLDOWN.value, "now": now},
    )
    return [row[0] for row in result.all() if row[0]]


async def process_expired_cooldowns(db: AsyncSession) -> int:
    """Bulk cooldown → active when TTL elapsed (single UPDATE per batch).

    When no request tenant context is set (Temporal worker, background loop),
    discovers affected orgs and processes each in ``tenant_context`` so
    ``TENANCY_STRICT_MODE`` ORM guards are satisfied.
    """
    if get_current_org_id() is None:
        total = 0
        for org_id in await _orgs_with_expired_cooldowns(db):
            with tenant_context(org_id):
                total += await _process_expired_cooldowns_scoped(db)
        return total
    return await _process_expired_cooldowns_scoped(db)


async def _process_expired_cooldowns_scoped(db: AsyncSession) -> int:
    """Process expired cooldowns for the active tenant context."""
    now = datetime.now(timezone.utc)
    today: date = now.date()
    total = 0

    while True:
        id_rows = (
            await db.execute(
                select(Account.id)
                .where(
                    Account.state == AccountState.COOLDOWN.value,
                    Account.cooldown_until.is_not(None),
                    Account.cooldown_until <= now,
                )
                .limit(_COOLDOWN_BATCH)
            )
        ).scalars().all()
        if not id_rows:
            break

        result = await db.execute(
            update(Account)
            .where(Account.id.in_(id_rows))
            .where(Account.state == AccountState.COOLDOWN.value)
            .where(Account.cooldown_until <= now)
            .values(
                state=AccountState.ACTIVE.value,
                status=AccountState.ACTIVE.value,
                state_reason="cooldown TTL expired",
                state_changed_at=now,
                cooldown_until=None,
                usage_today_minutes=0.0,
                usage_reset_date=today,
                updated_at=now,
            )
            .returning(Account.id, Account.platform)
        )
        rows = list(result.all())
        if not rows:
            break

        reason = "cooldown TTL expired"
        for account_id, platform in rows:
            _emit_transition_raw(
                account_id=account_id,
                platform=platform,
                from_state=AccountState.COOLDOWN.value,
                to_state=AccountState.ACTIVE.value,
                reason=reason,
                ttl_seconds=None,
                actor="system",
            )
        total += len(rows)
        await db.flush()

    if total:
        try:
            from services.account_state.metrics_sync import refresh_account_state_gauges

            await refresh_account_state_gauges(db)
        except Exception:
            pass

    return total


def _emit_transition(
    account: Account,
    from_state: str,
    to_state: str,
    reason: str,
    ttl_seconds: Optional[int],
    actor: str,
) -> None:
    _emit_transition_raw(
        account_id=account.id,
        platform=account.platform,
        from_state=from_state,
        to_state=to_state,
        reason=reason,
        ttl_seconds=ttl_seconds,
        actor=actor,
    )
    _adjust_gauge(account.platform, from_state, to_state)


def _emit_transition_raw(
    *,
    account_id: str,
    platform: str | None,
    from_state: str,
    to_state: str,
    reason: str,
    ttl_seconds: Optional[int],
    actor: str,
) -> None:
    publish_account_state_changed(
        AccountStateChangedEvent(
            account_id=account_id,
            from_state=from_state,
            to_state=to_state,
            reason=reason,
            ttl_seconds=ttl_seconds if to_state == AccountState.COOLDOWN.value else None,
            actor=actor,
            platform=platform,
        )
    )
    _record_transition_metrics(platform or "unknown", from_state, to_state, reason)


def _adjust_gauge(platform: str | None, from_state: str, to_state: str) -> None:
    try:
        plat = platform or "unknown"
        if from_state != to_state:
            account_state_gauge.labels(platform=plat, state=from_state).dec()
            account_state_gauge.labels(platform=plat, state=to_state).inc()
    except Exception:
        pass


def _record_transition_metrics(
    platform: str, from_state: str, to_state: str, reason: str
) -> None:
    try:
        state_transition_total.labels(
            from_state=from_state,
            to_state=to_state,
            reason_code=reason_code(reason),
        ).inc()
    except Exception:
        pass
