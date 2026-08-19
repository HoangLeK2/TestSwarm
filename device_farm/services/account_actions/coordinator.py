from __future__ import annotations

from typing import Any

from sqlalchemy import select

from db.crud.account import lookup_account_org_id
from db.models.execution import Execution
from services.account_actions.contract import AccountActionStatus
from services.account_actions.service import (
    create_action,
    finish_attempt,
    redact,
    start_attempt,
    transition_action,
)
from tenancy.context import tenant_context


def resolve_action_identity(
    *,
    step: dict[str, Any],
    scenario: dict[str, Any],
    variables: dict[str, Any],
    execution_id: str | None,
    device_serial: str | None = None,
) -> dict[str, str | None]:
    """Identify who/where an action belongs to.

    ``device_serial`` is which phone ran it — without it the activity feed
    cannot answer "what did this device do", and the ledger cannot be filtered
    by device at all.
    """
    sources = (
        ("step", step.get("account_id")),
        ("scenario", scenario.get("account_id")),
        ("campaign", (scenario.get("_campaign_vars") or {}).get("__ACCOUNT_ID__")),
        ("scenario_variables", (scenario.get("variables") or {}).get("__ACCOUNT_ID__")),
        ("variables", variables.get("__ACCOUNT_ID__")),
    )
    values = {
        str(value).strip()
        for _, value in sources
        if value is not None and str(value).strip()
    }
    if len(values) > 1:
        raise ValueError(
            "Conflicting account identities: "
            + ", ".join(
                name
                for name, value in sources
                if value is not None and str(value).strip()
            )
        )
    step_id = step.get("id") or step.get("_id")
    serial = device_serial or step.get("device_serial") or scenario.get("device_serial")
    return {
        "account_id": next(iter(values), None),
        "execution_id": str(execution_id).strip() if execution_id else None,
        "step_id": str(step_id).strip() if step_id else None,
        "device_serial": str(serial).strip() if serial else None,
    }


def stable_target(
    *, action: str, verified_target: dict[str, Any] | None
) -> dict[str, Any]:
    target = {"action": action}
    for key in ("name", "target_type", "target_id", "source"):
        value = (verified_target or {}).get(key)
        if value is not None and not isinstance(value, (dict, list, tuple)):
            target[key] = value
    return target


async def _resolve_tenant(
    db: Any, identity: dict[str, str | None], *, require_ids: bool
) -> tuple[str, str, str | None, str]:
    execution_id = identity["execution_id"]
    step_id = identity["step_id"]
    account_id = identity["account_id"]
    if require_ids and (not execution_id or not step_id):
        raise ValueError(
            "Enabled account action ledger requires execution id and stable step id/id/_id"
        )
    execution = None
    if execution_id:
        execution = (
            await db.execute(select(Execution).where(Execution.id == execution_id))
        ).scalar_one_or_none()
        if execution is None:
            raise ValueError("Account action execution not found")
        if account_id is None:
            account_id = execution.account_id
        elif execution.account_id and execution.account_id != account_id:
            raise ValueError("Account identity conflicts with execution account")
    if not account_id:
        raise ValueError("Account action account id could not be resolved")
    account_org_id = await lookup_account_org_id(db, account_id)
    if not account_org_id:
        raise ValueError("Account action account not found")
    if execution is not None and account_org_id != execution.org_id:
        raise ValueError("Account action account does not belong to execution tenant")
    org_id = execution.org_id if execution is not None else account_org_id
    return org_id, account_id, execution_id, step_id or "observed"


async def _prepare_action(
    db: Any,
    *,
    identity: dict[str, str | None],
    action_type: str,
    platform: str,
    target: dict[str, Any],
    action_id: str | None = None,
) -> dict[str, Any]:
    org_id, account_id, execution_id, step_id = await _resolve_tenant(
        db, identity, require_ids=True
    )
    with tenant_context(org_id):
        if action_id:
            from db.models.account_action import AccountAction

            row = (
                await db.execute(
                    select(AccountAction)
                    .where(
                        AccountAction.id == action_id,
                        AccountAction.org_id == org_id,
                        AccountAction.account_id == account_id,
                        AccountAction.action_type == action_type,
                        AccountAction.platform == platform,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if row is None:
                raise ValueError("Reserved account action not found")
            reserved_target_id = str((row.target or {}).get("target_id") or "")
            requested_target_id = str((target or {}).get("target_id") or "")
            if (
                reserved_target_id
                and requested_target_id
                and reserved_target_id != requested_target_id
            ):
                raise ValueError("Reserved account action target does not match UI target")
        else:
            row = await create_action(
                db,
                org_id=org_id,
                account_id=account_id,
                execution_id=execution_id,
                step_id=step_id,
                action_type=action_type,
                platform=platform,
                target=target,
                device_serial=identity.get("device_serial"),
            )
        if row.status == AccountActionStatus.SUCCEEDED.value:
            return {
                "action_id": str(row.id),
                "org_id": org_id,
                "account_id": account_id,
                "claimed": False,
                "status": row.status,
            }
        if row.status == AccountActionStatus.OBSERVED.value:
            row = await transition_action(
                db,
                org_id=org_id,
                action_id=row.id,
                to_status=AccountActionStatus.QUEUED,
                reason="account_action_enabled",
            )
        if row is not None and row.status == AccountActionStatus.QUEUED.value:
            row = await transition_action(
                db,
                org_id=org_id,
                action_id=row.id,
                to_status=AccountActionStatus.RUNNING,
                reason="social_action_claimed",
            )
        if row is None or row.status != AccountActionStatus.RUNNING.value:
            status = row.status if row is not None else "missing"
            raise RuntimeError(f"Account action already completed ({status})")
        attempt = await start_attempt(db, org_id=org_id, action_id=row.id)
        return {
            "action_id": str(row.id),
            "org_id": org_id,
            "account_id": account_id,
            "attempt_no": attempt.attempt_no,
            "claimed": True,
            "status": row.status,
        }


def prepare_action(
    *,
    identity: dict[str, str | None],
    action_type: str,
    platform: str,
    target: dict[str, Any],
    action_id: str | None = None,
) -> dict[str, Any]:
    from db.database import activity_session, run_activity_coro_blocking

    async def prepare() -> dict[str, Any]:
        async with activity_session() as db:
            return await _prepare_action(
                db,
                identity=identity,
                action_type=action_type,
                platform=platform,
                target=target,
                action_id=action_id,
            )

    return run_activity_coro_blocking(prepare())


async def _observe_action(
    db: Any,
    *,
    identity: dict[str, str | None],
    action_type: str,
    platform: str,
    target: dict[str, Any],
    outcome: str,
) -> dict[str, Any]:
    org_id, account_id, execution_id, step_id = await _resolve_tenant(
        db, identity, require_ids=False
    )
    result = {
        "outcome": outcome,
        "action_performed": outcome == "applied",
    }
    with tenant_context(org_id):
        row = await create_action(
            db,
            org_id=org_id,
            account_id=account_id,
            execution_id=execution_id,
            step_id=step_id,
            action_type=action_type,
            platform=platform,
            target=target,
            device_serial=identity.get("device_serial"),
            result=result,
            observed=True,
        )
        if row.status == AccountActionStatus.OBSERVED.value:
            row.result = redact(result)
            await db.flush()
        return {
            "action_id": str(row.id),
            "org_id": org_id,
            "outcome": outcome,
            "status": row.status,
        }


def observe_action(
    *,
    identity: dict[str, str | None],
    action_type: str,
    platform: str,
    target: dict[str, Any],
    outcome: str,
) -> dict[str, Any]:
    from db.database import activity_session, run_activity_coro_blocking

    async def observe() -> dict[str, Any]:
        async with activity_session() as db:
            return await _observe_action(
                db,
                identity=identity,
                action_type=action_type,
                platform=platform,
                target=target,
                outcome=outcome,
            )

    return run_activity_coro_blocking(observe())


async def _finalize_action(
    db: Any,
    *,
    claim: dict[str, Any],
    succeeded: bool,
    terminal: bool,
    reason: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    org_id = str(claim["org_id"])
    action_id = str(claim["action_id"])
    attempt_no = int(claim["attempt_no"])
    outcome = "succeeded" if succeeded else "failed"
    action_performed = bool(result.get("action_performed", False))
    error_message = None if succeeded else str(result.get("message") or reason)
    details = {
        "reason": reason,
        "outcome": result.get("outcome"),
        "action_performed": action_performed,
    }
    for key in ("state", "action_bounds", "matched_label"):
        if result.get(key) is not None:
            details[key] = result.get(key)
    if error_message:
        details["error_message"] = error_message

    with tenant_context(org_id):
        await finish_attempt(
            db,
            org_id=org_id,
            action_id=action_id,
            attempt_no=attempt_no,
            outcome=outcome,
            error_code=None if succeeded else reason,
            details=details,
        )
        row = None
        if succeeded or terminal:
            projection = {
                **details,
                "error_code": None if succeeded else reason,
                "error_message": error_message,
            }
            row = await transition_action(
                db,
                org_id=org_id,
                action_id=action_id,
                to_status=(
                    AccountActionStatus.SUCCEEDED
                    if succeeded
                    else AccountActionStatus.FAILED
                ),
                reason=reason,
                result=projection,
            )
        if row is None:
            from db.models.account_action import AccountAction

            row = (
                await db.execute(
                    select(AccountAction).where(
                        AccountAction.id == action_id,
                        AccountAction.org_id == org_id,
                    )
                )
            ).scalar_one_or_none()
        expected = (
            outcome if succeeded or terminal else AccountActionStatus.RUNNING.value
        )
        if row is None or row.status != expected:
            raise RuntimeError("Account action finalization reached an invalid state")
        return {
            "action_id": str(row.id),
            "status": row.status,
            "attempt_no": attempt_no,
        }


def finalize_action(
    *,
    claim: dict[str, Any],
    succeeded: bool,
    reason: str,
    result: dict[str, Any],
    terminal: bool = True,
) -> dict[str, Any]:
    from db.database import activity_session, run_activity_coro_blocking

    async def finalize() -> dict[str, Any]:
        async with activity_session() as db:
            return await _finalize_action(
                db,
                claim=claim,
                succeeded=succeeded,
                terminal=terminal,
                reason=reason,
                result=result,
            )

    return run_activity_coro_blocking(finalize())
