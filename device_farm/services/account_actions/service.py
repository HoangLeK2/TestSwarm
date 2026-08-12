from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError

from db.models.account_action import (
    AccountAction,
    AccountActionAttempt,
    AccountActionTransition,
)
from services.account_actions.contract import (
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    AccountActionRank,
    AccountActionStatus,
)
from tenancy.context import tenant_context

_SECRET_KEYS = frozenset(
    {
        "password",
        "token",
        "cookie",
        "cookies",
        "authorization",
        "secret",
        "access_token",
        "refresh_token",
    }
)


def ledger_mode() -> str:
    value = os.getenv("ACCOUNT_ACTION_LEDGER_MODE", "disabled").strip().lower()
    return value if value in {"disabled", "observe", "enabled"} else "disabled"


def stable_action_key(
    *,
    org_id: str,
    account_id: str,
    execution_id: str,
    step_id: str,
    action_type: str,
    target: dict[str, Any] | None = None,
) -> str:
    canonical = json.dumps(
        [org_id, account_id, execution_id, step_id, action_type, redact(target or {})],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def stable_account_target_key(
    *,
    org_id: str,
    account_id: str,
    platform: str,
    action_type: str,
    action: str,
    target_id: str,
) -> str:
    """Return a cross-execution key for one account/action/target tuple."""
    canonical = json.dumps(
        [org_id, account_id, platform, action_type, action, target_id],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(k): "[REDACTED]" if str(k).lower() in _SECRET_KEYS else redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def status_rank(status: AccountActionStatus | str) -> int:
    value = status.value if isinstance(status, AccountActionStatus) else status
    return int(
        AccountActionRank.TERMINAL
        if value in TERMINAL_STATUSES
        else AccountActionRank[value.upper()]
    )


async def create_action(
    db,
    *,
    org_id: str,
    account_id: str,
    execution_id: str,
    step_id: str,
    action_type: str,
    platform: str,
    target: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    observed: bool = False,
    action_key: str | None = None,
) -> AccountAction:
    initial = AccountActionStatus.OBSERVED if observed else AccountActionStatus.QUEUED
    key = action_key or stable_action_key(
        org_id=org_id,
        account_id=account_id,
        execution_id=execution_id,
        step_id=step_id,
        action_type=action_type,
        target=target,
    )
    now = datetime.now(UTC)
    row = AccountAction(
        org_id=org_id,
        account_id=account_id,
        execution_id=execution_id,
        step_id=step_id,
        action_key=key,
        action_type=action_type,
        platform=platform,
        status=initial.value,
        status_rank=status_rank(initial),
        target=redact(target or {}),
        result=redact(result or {}),
        last_transition_at=now,
    )
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        return (
            await db.execute(
                select(AccountAction).where(
                    AccountAction.org_id == org_id, AccountAction.action_key == key
                )
            )
        ).scalar_one()
    db.add(
        AccountActionTransition(
            action_id=row.id,
            org_id=org_id,
            from_status=None,
            to_status=initial.value,
            status_rank=row.status_rank,
            occurred_at=now,
        )
    )
    if execution_id:
        from services.execution.event_publisher import enqueue_execution_event

        event = await enqueue_execution_event(
            db,
            event_type="account_action.created",
            execution_id=execution_id,
            organization_id=org_id,
            step_id=step_id,
            payload={
                "action_id": row.id,
                "account_id": account_id,
                "status": initial.value,
                "action_type": action_type,
            },
        )
        if event is None:
            raise RuntimeError("Account action outbox event could not be enqueued")
    return row


async def transition_action(
    db,
    *,
    org_id: str,
    action_id: str,
    to_status: AccountActionStatus,
    reason: str | None = None,
    result: dict[str, Any] | None = None,
    artifact_refs: list[dict[str, Any]] | None = None,
) -> AccountAction | None:
    rank = status_rank(to_status)
    now = datetime.now(UTC)
    row = (
        await db.execute(
            select(AccountAction)
            .where(AccountAction.id == action_id, AccountAction.org_id == org_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None or row.status_rank >= rank or row.status in TERMINAL_STATUSES:
        return row
    previous = row.status
    row.status = to_status.value
    row.status_rank = rank
    row.last_transition_at = now
    row.updated_at = now
    if result is not None:
        row.result = redact(result)
    if artifact_refs is not None:
        row.artifact_refs = redact(artifact_refs)
    if to_status == AccountActionStatus.RUNNING:
        row.started_at = now
    if to_status.value in TERMINAL_STATUSES:
        row.completed_at = now
    db.add(
        AccountActionTransition(
            action_id=action_id,
            org_id=org_id,
            from_status=previous,
            to_status=to_status.value,
            status_rank=rank,
            reason=reason,
            details=redact(result or {}),
            occurred_at=now,
        )
    )
    if row.execution_id:
        from services.execution.event_publisher import enqueue_execution_event

        event = await enqueue_execution_event(
            db,
            event_type="account_action.transitioned",
            execution_id=row.execution_id,
            organization_id=org_id,
            step_id=row.step_id,
            payload={
                "action_id": row.id,
                "account_id": row.account_id,
                "from_status": previous,
                "to_status": to_status.value,
                "reason": reason,
            },
        )
        if event is None:
            raise RuntimeError("Account action outbox event could not be enqueued")
    return row


async def record_attempt(
    db,
    *,
    org_id: str,
    action_id: str,
    attempt_no: int,
    outcome: str,
    error_code: str | None = None,
    details: dict[str, Any] | None = None,
    artifact_refs: list[dict[str, Any]] | None = None,
) -> AccountActionAttempt:
    action_exists = (
        await db.execute(
            select(AccountAction.id).where(
                AccountAction.id == action_id, AccountAction.org_id == org_id
            )
        )
    ).scalar_one_or_none()
    if action_exists is None:
        raise ValueError("Account action not found")
    row = AccountActionAttempt(
        org_id=org_id,
        action_id=action_id,
        attempt_no=attempt_no,
        outcome=outcome,
        error_code=error_code,
        details=redact(details or {}),
        artifact_refs=redact(artifact_refs or []),
        ended_at=datetime.now(UTC),
    )
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        return (
            await db.execute(
                select(AccountActionAttempt).where(
                    AccountActionAttempt.org_id == org_id,
                    AccountActionAttempt.action_id == action_id,
                    AccountActionAttempt.attempt_no == attempt_no,
                )
            )
        ).scalar_one()
    return row


async def start_attempt(db, *, org_id: str, action_id: str) -> AccountActionAttempt:
    action = (
        await db.execute(
            select(AccountAction)
            .where(AccountAction.id == action_id, AccountAction.org_id == org_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if action is None:
        raise ValueError("Account action not found")
    if action.status != AccountActionStatus.RUNNING.value:
        raise RuntimeError(f"Account action is not running ({action.status})")

    open_attempt = (
        await db.execute(
            select(AccountActionAttempt)
            .where(
                AccountActionAttempt.org_id == org_id,
                AccountActionAttempt.action_id == action_id,
                AccountActionAttempt.ended_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if open_attempt is not None:
        raise RuntimeError(
            f"Account action attempt {open_attempt.attempt_no} is already running"
        )

    latest_attempt_no = (
        await db.execute(
            select(func.max(AccountActionAttempt.attempt_no)).where(
                AccountActionAttempt.org_id == org_id,
                AccountActionAttempt.action_id == action_id,
            )
        )
    ).scalar_one_or_none()
    row = AccountActionAttempt(
        org_id=org_id,
        action_id=action_id,
        attempt_no=int(latest_attempt_no or 0) + 1,
        outcome="running",
    )
    db.add(row)
    await db.flush()
    return row


async def finish_attempt(
    db,
    *,
    org_id: str,
    action_id: str,
    attempt_no: int,
    outcome: str,
    error_code: str | None = None,
    details: dict[str, Any] | None = None,
    artifact_refs: list[dict[str, Any]] | None = None,
) -> AccountActionAttempt:
    row = (
        await db.execute(
            select(AccountActionAttempt)
            .where(
                AccountActionAttempt.org_id == org_id,
                AccountActionAttempt.action_id == action_id,
                AccountActionAttempt.attempt_no == attempt_no,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise ValueError("Account action attempt not found")
    if row.ended_at is not None:
        if row.outcome != outcome:
            raise RuntimeError(
                f"Account action attempt already completed ({row.outcome})"
            )
        return row

    row.outcome = outcome
    row.error_code = error_code
    row.details = redact(details or {})
    row.artifact_refs = redact(artifact_refs or [])
    row.ended_at = datetime.now(UTC)
    await db.flush()
    return row


async def list_actions(
    db,
    *,
    org_id: str,
    account_id: str,
    limit: int = 100,
    before: tuple[datetime, str] | None = None,
) -> list[AccountAction]:
    query = select(AccountAction).where(
        AccountAction.org_id == org_id, AccountAction.account_id == account_id
    )
    if before:
        created_at, action_id = before
        query = query.where(
            or_(
                AccountAction.created_at < created_at,
                and_(
                    AccountAction.created_at == created_at, AccountAction.id < action_id
                ),
            )
        )
    rows = await db.execute(
        query.order_by(AccountAction.created_at.desc(), AccountAction.id.desc()).limit(
            min(max(limit, 1), 201)
        )
    )
    return list(rows.scalars())


async def reconcile_stale_actions(
    db, *, older_than: timedelta, org_id: str | None = None
) -> int:
    cutoff = datetime.now(UTC) - older_than
    table = AccountAction.__table__
    query = select(table.c.id, table.c.org_id).where(
        table.c.status.in_(ACTIVE_STATUSES), table.c.last_transition_at < cutoff
    )
    if org_id:
        query = query.where(table.c.org_id == org_id)
    rows = list(
        (
            await db.execute(
                query.order_by(table.c.last_transition_at, table.c.id)
                .limit(200)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    transitioned = 0
    for action_id, candidate_org_id in rows:
        with tenant_context(candidate_org_id):
            open_attempts = list(
                (
                    await db.execute(
                        select(AccountActionAttempt).where(
                            AccountActionAttempt.org_id == candidate_org_id,
                            AccountActionAttempt.action_id == action_id,
                            AccountActionAttempt.ended_at.is_(None),
                        )
                    )
                ).scalars()
            )
            for attempt in open_attempts:
                attempt.outcome = AccountActionStatus.STALE.value
                attempt.error_code = "reconciliation_timeout"
                attempt.details = {"reason": "reconciliation_timeout"}
                attempt.ended_at = datetime.now(UTC)
            row = await transition_action(
                db,
                org_id=candidate_org_id,
                action_id=action_id,
                to_status=AccountActionStatus.STALE,
                reason="reconciliation_timeout",
            )
            transitioned += int(
                row is not None and row.status == AccountActionStatus.STALE.value
            )
    return transitioned
