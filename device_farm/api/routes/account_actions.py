import base64
import binascii
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select

from api.deps import DB, CurrentUser, require_permission
from api.schemas.account_action import AccountActionListOut, AccountActionSummaryOut
from db.crud.account import get_account
from db.models.account_action import AccountAction
from services.account_actions import list_actions
from services.account_actions.contract import ACTIVE_STATUSES

router = APIRouter(tags=["account-actions"])


@router.get(
    "/accounts/{account_id}/actions",
    response_model=AccountActionListOut,
    dependencies=[Depends(require_permission("accounts", "read"))],
)
async def list_account_actions(
    account_id: str,
    db: DB,
    user: CurrentUser,
    limit: int = Query(100, ge=1, le=200),
    cursor: str | None = None,
):
    org_id = getattr(user, "org_id", None)
    account = await get_account(db, account_id)
    if not org_id or account is None or account.org_id != org_id:
        raise HTTPException(status_code=404, detail="Account not found")
    before = None
    if cursor:
        try:
            payload = json.loads(
                base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            )
            if not isinstance(payload, list) or len(payload) != 2:
                raise ValueError("invalid cursor shape")
            before = (datetime.fromisoformat(payload[0]), str(payload[1]))
            if before[0].tzinfo is None or not before[1]:
                raise ValueError("invalid cursor values")
        except (
            ValueError,
            TypeError,
            IndexError,
            KeyError,
            json.JSONDecodeError,
            binascii.Error,
        ):
            raise HTTPException(status_code=400, detail="Invalid cursor") from None
    rows = await list_actions(
        db, org_id=org_id, account_id=account_id, limit=limit + 1, before=before
    )
    has_more = len(rows) > limit
    items = [_action_out(row) for row in rows[:limit]]
    return {
        "items": items,
        "next_cursor": _encode_cursor(rows[limit - 1]) if has_more and items else None,
        "has_more": has_more,
    }


@router.get(
    "/accounts/{account_id}/action-summary",
    response_model=AccountActionSummaryOut,
    dependencies=[Depends(require_permission("accounts", "read"))],
)
async def get_account_action_summary(account_id: str, db: DB, user: CurrentUser):
    org_id = getattr(user, "org_id", None)
    account = await get_account(db, account_id)
    if not org_id or account is None or account.org_id != org_id:
        raise HTTPException(status_code=404, detail="Account not found")

    counts = dict(
        (
            await db.execute(
                select(AccountAction.status, func.count(AccountAction.id))
                .where(
                    AccountAction.org_id == org_id,
                    AccountAction.account_id == account_id,
                )
                .group_by(AccountAction.status)
            )
        ).all()
    )
    current = (
        await db.execute(
            select(AccountAction)
            .where(
                AccountAction.org_id == org_id,
                AccountAction.account_id == account_id,
                AccountAction.status.in_(ACTIVE_STATUSES),
            )
            .order_by(AccountAction.last_transition_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return {
        "total": sum(counts.values()),
        "pending": counts.get("queued", 0),
        "running": counts.get("running", 0),
        "succeeded": counts.get("succeeded", 0),
        "failed": counts.get("failed", 0) + counts.get("stale", 0),
        "current_activity": current.action_type if current else None,
    }


def _action_out(row: AccountAction) -> dict:
    target = row.target or {}
    result = row.result or {}
    details = (
        result
        if len(json.dumps(result, default=str, separators=(",", ":")).encode("utf-8"))
        <= 16_384
        else {}
    )
    target_label = target.get("label") or target.get("name")
    failed = row.status in {"failed", "stale", "cancelled"}
    error_message = (
        result.get("error_message")
        or result.get("error")
        or (result.get("reason") if failed else None)
    )
    return {
        "id": row.id,
        "account_id": row.account_id,
        "status": row.status,
        "action": row.action_type,
        "target_type": target.get("target_type") or target.get("type"),
        "target_id": target.get("target_id") or target.get("id"),
        "target_label": str(target_label)[:512] if target_label is not None else None,
        "current_activity": row.action_type if row.status in ACTIVE_STATUSES else None,
        "error_code": result.get("error_code")
        or (result.get("reason") if failed else None),
        "error_message": str(error_message)[:2048]
        if error_message is not None
        else None,
        "details": details,
        "started_at": row.started_at,
        "completed_at": row.completed_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _encode_cursor(row: AccountAction) -> str:
    payload = json.dumps(
        [row.created_at.isoformat(), row.id], separators=(",", ":")
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")
