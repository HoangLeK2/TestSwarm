"""Account state transitions with optimistic locking and audit (DF-T-07-005)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.account import Account
from db.models.enums import AccountState
from services.account_state.events import AccountStateChangedEvent, publish_account_state_changed
from services.account_state.exceptions import (
    InvalidStateTransitionError,
    StateConflictError,
)
from services.account_state.fsm import can_transition, normalize_state, transition_error_message
from services.account_state.reason_codes import reason_code
from web.metrics import account_state_gauge, state_transition_total

log = logging.getLogger(__name__)


class AccountStateService:
    """Apply FSM transitions on ``accounts.state`` (``status`` kept in sync)."""

    async def transition(
        self,
        db: AsyncSession,
        account_id: str,
        *,
        to: str | AccountState,
        reason: str,
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

        values: dict = {
            "state": to_state.value,
            "status": to_state.value,
            "state_reason": (reason or "").strip() or None,
            "state_changed_at": now,
            "updated_at": now,
        }
        if to_state == AccountState.ACTIVE:
            # Resuming an account clears any rest timer and its usage budget.
            values["cooldown_until"] = None
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

        _emit_transition(updated, from_state.value, to_state.value, reason, actor)
        return updated

    async def _load_for_update(
        self, db: AsyncSession, account_id: str
    ) -> Optional[Account]:
        result = await db.execute(
            select(Account).where(Account.id == account_id).with_for_update()
        )
        return result.scalar_one_or_none()


def _emit_transition(
    account: Account,
    from_state: str,
    to_state: str,
    reason: str,
    actor: str,
) -> None:
    publish_account_state_changed(
        AccountStateChangedEvent(
            account_id=account.id,
            from_state=from_state,
            to_state=to_state,
            reason=reason,
            actor=actor,
            platform=account.platform,
        )
    )
    _record_transition_metrics(account.platform or "unknown", from_state, to_state, reason)
    _adjust_gauge(account.platform, from_state, to_state)


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
