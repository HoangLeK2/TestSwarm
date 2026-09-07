from __future__ import annotations

import hashlib
import json
import logging
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


log = logging.getLogger(__name__)


def ledger_mode() -> str:
    value = os.getenv("ACCOUNT_ACTION_LEDGER_MODE", "disabled").strip().lower()
    return value if value in {"disabled", "observe", "enabled"} else "disabled"


def identity_target(target: dict[str, Any] | None) -> Any:
    """Reduce a target to what identifies it, for keying.

    A target carries the person's display name as read off the screen. That text
    is not stable — truncation, an emoji, a rename between two dumps — so hashing
    it produced a second ledger row for an action that had already been recorded.
    Key on the id when there is one; without an id the full target is all we have
    to tell two targets apart, so keep the old behaviour there.
    """
    data = target or {}
    target_id = str(data.get("target_id") or "").strip()
    if not target_id:
        return redact(data)
    return {
        "action": data.get("action"),
        "target_type": data.get("target_type"),
        "target_id": target_id,
    }


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
        [org_id, account_id, execution_id, step_id, action_type, identity_target(target)],
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


async def _lookup_device_id(db, *, serial: str | None) -> str | None:
    """Map a device serial to its row id. Never raises — a missing device must
    not lose the action record; device_serial alone still identifies the phone.

    Serial is globally unique on `devices`, so no tenant filter is needed here.
    """
    if not serial:
        return None
    try:
        from db.models.device import Device

        return (
            await db.execute(select(Device.id).where(Device.serial == serial))
        ).scalar_one_or_none()
    except Exception as exc:  # pragma: no cover - lookup is best effort
        log.debug("account action device lookup failed serial=%s: %s", serial, exc)
        return None


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
    device_serial: str | None = None,
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
    # device_serial is authoritative (it is what the runtime knows); device_id is
    # a best-effort lookup so the row still joins to the device table when it can.
    device_id = await _lookup_device_id(db, serial=device_serial)
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
        device_id=device_id,
        device_serial=device_serial or None,
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


async def _attach_action_artifacts(
    db, *, org_id: str, action_id: str, artifact_refs: list[dict[str, Any]]
) -> int:
    row = (
        await db.execute(
            select(AccountAction)
            .where(AccountAction.id == action_id, AccountAction.org_id == org_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        return 0
    row.artifact_refs = redact(artifact_refs)
    row.updated_at = datetime.now(UTC)
    attempt = (
        await db.execute(
            select(AccountActionAttempt)
            .where(
                AccountActionAttempt.org_id == org_id,
                AccountActionAttempt.action_id == action_id,
            )
            .order_by(AccountActionAttempt.attempt_no.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if attempt is not None and not attempt.artifact_refs:
        attempt.artifact_refs = redact(artifact_refs)
    await db.flush()
    return len(artifact_refs)


def attach_action_artifacts(
    *, org_id: str, action_id: str, artifact_refs: list[dict[str, Any]]
) -> int:
    """Attach capture evidence to an action that has already been recorded.

    The failure screenshot is taken after the step handler returns, so the
    ledger row is already written and closed by then. Without this the
    ``artifact_refs`` column stayed empty on every row ever recorded and the log
    could say an account tried something but never show what the screen looked
    like when it failed.

    Best effort: a missing action or a write error must never turn into a step
    failure, because the action itself already happened.
    """
    if not org_id or not action_id or not artifact_refs:
        return 0
    from db.database import activity_session, run_activity_coro_blocking

    async def attach() -> int:
        async with activity_session() as db:
            with tenant_context(org_id):
                return await _attach_action_artifacts(
                    db,
                    org_id=org_id,
                    action_id=action_id,
                    artifact_refs=artifact_refs,
                )

    try:
        return run_activity_coro_blocking(attach())
    except Exception as exc:
        log.warning(
            "account action artifact attach failed action=%s: %s", action_id, exc
        )
        return 0


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
