"""
api/routes/accounts.py — Account & Profile Manager REST API (DF-007).

Endpoints:
    GET    /api/accounts                             List accounts
    POST   /api/accounts                             Create account
    POST   /api/accounts/import                      Bulk import (JSON)
    POST   /api/accounts/import-csv                  Bulk import (CSV text)
    GET    /api/accounts/{id}                        Get account detail
    PATCH  /api/accounts/{id}                        Update account
    DELETE /api/accounts/{id}                        Delete account
    PATCH  /api/accounts/{id}/status                 Update status (legacy)
    POST   /api/accounts/{id}/state                  FSM state transition
    GET    /api/accounts/{id}/devices                List devices assigned to account
    POST   /api/accounts/{id}/devices                Assign device to account
    DELETE /api/accounts/{id}/devices/{device_id}    Unassign device from account
    POST   /api/accounts/round-robin                 Auto-assign accounts to devices
    GET    /api/devices/{device_id}/accounts         List accounts on device
    POST   /api/devices/{device_id}/accounts/primary Set primary account for device
"""
from __future__ import annotations

import csv
import io
import os
from datetime import datetime, timezone
from typing import List, NoReturn, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import select

from api.deps import CurrentUser, DB, require_permission
from api.org_scope import data_owner_user_id, resource_visible_to_user
from api.schemas.account import (
    AccountCreate,
    AccountOut,
    AccountStatusUpdate,
    AccountVerificationOut,
    AccountUpdate,
    AccountWithLinksOut,
    AssignAccountBody,
    AssignDeviceBody,
    BulkImportBody,
    BulkImportResult,
    DeviceAccountOut,
    RoundRobinBody,
    SetPrimaryBody,
)
from api.schemas.device_platform_session import (
    CancelFacebookLoginAttemptBody,
    ConfirmPlatformSessionBody,
    CompleteFacebookLoginAttemptBody,
    DevicePlatformLoginAttemptOut,
    DevicePlatformSessionOut,
    InvalidatePlatformSessionBody,
    StartFacebookLoginAttemptBody,
)
from api.schemas.account_state import (
    AccountStateTransitionBody,
    AccountStateTransitionOut,
)
from api.schemas.account_event import AccountEventListOut, AccountEventOut
from common.crypto import encrypt_password
from db.crud.account_event import list_account_events
from db.crud.account import (
    _BULK_BATCH_SIZE,
    _insert_batch,
    _prepare_account_row,
    assign_account_to_device,
    bulk_create_accounts,
    create_account,
    delete_account,
    get_account,
    get_account_by_platform_username,
    list_account_devices,
    list_accounts,
    list_active_account_ids,
    list_device_accounts,
    round_robin_assign,
    set_primary_account,
    unassign_account_from_device,
    update_account,
)
from db.crud.device import get_device
from db.models.enums import AccountEventType
from db.models.account import DeviceAccount
from services.account_event_recorder import get_account_event_recorder
from services.account_state import (
    AccountStateError,
    AccountStateService,
    InvalidStateTransitionError,
    InvalidTtlError,
    StateConflictError,
)
from services.device_platform_session import (
    DevicePlatformSessionConflict,
    get_or_create_platform_session,
    invalidate_if_account_holds_provenance,
    invalidate_platform_session,
    list_platform_sessions,
    mark_active,
    mark_login_required_for_primary_change,
)
from services.device_platform_login_attempt import (
    ControlledLoginDisabled,
    DevicePlatformLoginAttemptConflict,
    cancel_facebook_login_attempt,
    get_login_attempt,
    list_login_attempts,
    start_controlled_facebook_login_attempt,
    start_facebook_login_attempt,
    complete_facebook_login_attempt,
)
from services.device_reserve.exceptions import DeviceSessionError

router = APIRouter(tags=["accounts"])

_DEFAULT_COOLDOWN_SECONDS = int(
    float(os.environ.get("ACCOUNT_COOLDOWN_MINUTES", "120")) * 60
)


def _raise_account_state_http(exc: AccountStateError) -> NoReturn:
    if isinstance(exc, StateConflictError):
        code = status.HTTP_409_CONFLICT
    elif isinstance(exc, (InvalidStateTransitionError, InvalidTtlError)):
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
    else:
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
    raise HTTPException(
        status_code=code,
        detail={"code": exc.code, "message": str(exc)},
    ) from exc


async def _commit_and_flush_events(db) -> None:
    await db.commit()
    rec = get_account_event_recorder()
    while rec._pending:
        flushed = await rec.flush(db)
        if flushed == 0:
            break


# ── Helpers ────────────────────────────────────────────────────────────────────


def _account_to_out(account) -> AccountOut:
    state = getattr(account, "state", None) or account.status
    return AccountOut(
        id=account.id,
        platform=account.platform,
        username=account.username,
        display_name=account.display_name or "",
        status=account.status,
        state=state,
        state_reason=getattr(account, "state_reason", None),
        state_changed_at=getattr(account, "state_changed_at", None),
        cooldown_until=account.cooldown_until,
        proxy_id=account.proxy_id,
        notes=account.notes or "",
        tags=account.tags or "",
        user_id=account.user_id,
        created_at=account.created_at,
        updated_at=account.updated_at,
        last_used_at=account.last_used_at,
        total_usage_minutes=account.total_usage_minutes or 0.0,
        usage_today_minutes=account.usage_today_minutes or 0.0,
        usage_reset_date=account.usage_reset_date,
    )


def _account_to_detail_out(account) -> AccountWithLinksOut:
    links = [
        DeviceAccountOut(
            id=lnk.id,
            device_id=lnk.device_id,
            account_id=lnk.account_id,
            is_primary=lnk.is_primary,
            assigned_at=lnk.assigned_at,
            verification_status=lnk.verification_status,
            verified_at=lnk.verified_at,
            verification_attempted_at=lnk.verification_attempted_at,
            verification_evidence=lnk.verification_evidence or {},
        )
        for lnk in (account.device_links or [])
    ]
    return AccountWithLinksOut(**_account_to_out(account).model_dump(), device_links=links)


def _link_to_out(lnk) -> DeviceAccountOut:
    return DeviceAccountOut(
        id=lnk.id,
        device_id=lnk.device_id,
        account_id=lnk.account_id,
        is_primary=lnk.is_primary,
        assigned_at=lnk.assigned_at,
        verification_status=lnk.verification_status,
        verified_at=lnk.verified_at,
        verification_attempted_at=lnk.verification_attempted_at,
        verification_evidence=lnk.verification_evidence or {},
    )


def _session_to_out(session) -> DevicePlatformSessionOut:
    return DevicePlatformSessionOut(
        id=session.id,
        org_id=session.org_id,
        device_id=session.device_id,
        platform=session.platform,
        account_id=session.account_id,
        state=session.state,
        state_reason=session.state_reason,
        established_at=session.established_at,
        last_ready_at=session.last_ready_at,
        last_checked_at=session.last_checked_at,
        invalidated_at=session.invalidated_at,
        login_attempt_id=session.login_attempt_id,
        establishment_method=session.establishment_method,
        app_package=session.app_package,
        app_version=session.app_version,
        display_name_observed=session.display_name_observed,
        evidence=session.evidence or {},
        version=session.version,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _login_attempt_to_out(attempt) -> DevicePlatformLoginAttemptOut:
    return DevicePlatformLoginAttemptOut(
        id=attempt.id,
        org_id=attempt.org_id,
        device_id=attempt.device_id,
        platform=attempt.platform,
        account_id=attempt.account_id,
        state=attempt.state,
        reason=attempt.reason,
        reserve_session_id=attempt.reserve_session_id,
        created_by_user_id=attempt.created_by_user_id,
        started_at=attempt.started_at,
        completed_at=attempt.completed_at,
        cancelled_at=attempt.cancelled_at,
        evidence=attempt.evidence or {},
        version=attempt.version,
        created_at=attempt.created_at,
        updated_at=attempt.updated_at,
    )


async def _get_account_or_404(account_id: str, db):
    account = await get_account(db, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


async def _get_account_for_user_or_404(account_id: str, db, user):
    account = await get_account(db, account_id)
    user_org_id = getattr(user, "org_id", None)
    if account is None or (user_org_id and account.org_id != user_org_id):
        raise HTTPException(status_code=404, detail="Account not found")
    return account


async def _get_device_for_user_or_404(device_id: str, db, user):
    device = await get_device(db, device_id)
    user_org_id = getattr(user, "org_id", None)
    if device is None or (user_org_id and device.org_id != user_org_id):
        raise HTTPException(status_code=404, detail="Device not found")
    return device


async def _require_assigned_account(device_id: str, account_id: str, db, user):
    account = await _get_account_for_user_or_404(account_id, db, user)
    result = await db.execute(
        select(DeviceAccount).where(
            DeviceAccount.device_id == device_id,
            DeviceAccount.account_id == account_id,
        )
    )
    link = result.scalar_one_or_none()
    if link is None:
        raise HTTPException(status_code=404, detail="Device-account link not found")
    return account, link


# ── Account endpoints ──────────────────────────────────────────────────────────


@router.get(
    "/accounts",
    response_model=List[AccountOut],
    dependencies=[Depends(require_permission("accounts", "read"))],
)
async def list_accounts_endpoint(
    db: DB,
    user: CurrentUser,
    platform: Optional[str] = Query(None),
    account_status: Optional[str] = Query(None, alias="status"),
    state: Optional[str] = Query(None),
    include_states: Optional[List[str]] = Query(
        None,
        description="Override default listing; comma-separated in OpenAPI as repeated params",
    ),
    tags: Optional[str] = Query(None),
    search: Optional[str] = Query(
        None,
        max_length=100,
        description="Substring match on username or display name",
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List accounts owned by the current user with optional filters."""
    accounts = await list_accounts(
        db,
        platform=platform,
        status=account_status,
        state=state,
        include_states=include_states,
        tags=tags,
        search=search,
        user_id=data_owner_user_id(user),
        limit=limit,
        offset=offset,
    )
    return [_account_to_out(a) for a in accounts]


@router.post(
    "/accounts",
    response_model=AccountOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("accounts", "create"))],
)
async def create_account_endpoint(body: AccountCreate, db: DB, user: CurrentUser):
    """Create a new account. Password is encrypted before storage."""
    existing = await get_account_by_platform_username(db, body.platform, body.username)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Account {body.platform}:{body.username} already exists",
        )
    enc_pw = encrypt_password(body.password) if body.password else None
    account = await create_account(
        db,
        platform=body.platform,
        username=body.username,
        password_encrypted=enc_pw,
        display_name=body.display_name,
        notes=body.notes,
        tags=body.tags,
        user_id=user.id,
        org_id=getattr(user, "org_id", None),
        account_metadata=body.account_metadata,
    )
    get_account_event_recorder().record(
        account_id=account.id,
        event_type=AccountEventType.CREATED,
        user_id=user.id,
        platform=account.platform,
        details={"username": account.username},
    )
    await _commit_and_flush_events(db)
    account = await get_account(db, account.id)
    return _account_to_out(account)


@router.post(
    "/accounts/import",
    response_model=BulkImportResult,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_permission("accounts", "create"))],
)
async def bulk_import_json(body: BulkImportBody, db: DB, user: CurrentUser):
    """Bulk import accounts from a JSON array. Duplicate (platform, username) pairs are skipped."""
    rows = [r.model_dump() for r in body.accounts]
    created, skipped = await bulk_create_accounts(db, rows, user_id=user.id)
    await db.commit()
    return BulkImportResult(created=created, skipped=skipped, total=len(rows))


@router.post(
    "/accounts/import-csv",
    response_model=BulkImportResult,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_permission("accounts", "create"))],
)
async def bulk_import_csv(
    db: DB,
    user: CurrentUser,
    file: UploadFile = File(
        ...,
        description=(
            "CSV file with columns: platform, username, password, display_name, "
            "tags, notes, email, totp_secret, cookies, token"
        ),
    ),
):
    """
    Stream-import accounts from a CSV file upload.

    Reads the upload in 64 KB chunks, parses CSV incrementally, and flushes
    batches of up to 500 rows to the DB via INSERT ON CONFLICT DO NOTHING —
    so memory usage stays flat regardless of file size.

    Expected CSV columns: platform, username, password, display_name, tags, notes,
    email, totp_secret, cookies, token
    """
    if not file.content_type or "text" not in file.content_type:
        # Allow text/csv, text/plain, application/octet-stream (browser quirks).
        if file.content_type not in (
            "text/csv", "text/plain", "application/csv",
            "application/octet-stream", None,
        ):
            raise HTTPException(
                status_code=400,
                detail=f"Expected a CSV file, got content-type: {file.content_type}",
            )

    _CHUNK = 64 * 1024  # 64 KB read chunks
    leftover = b""
    header: Optional[List[str]] = None
    batch: List[dict] = []
    created = 0
    total = 0
    invalid = 0

    try:
        while True:
            chunk = await file.read(_CHUNK)
            if not chunk:
                break

            lines_bytes = (leftover + chunk).split(b"\n")
            # Last element may be an incomplete line — hold it for the next chunk.
            leftover = lines_bytes.pop()

            for line_bytes in lines_bytes:
                line = line_bytes.decode("utf-8", errors="replace").rstrip("\r")
                if not line:
                    continue

                reader = csv.reader([line])
                fields = next(reader, None)
                if fields is None:
                    continue

                if header is None:
                    header = [h.strip().lower() for h in fields]
                    continue

                row = dict(zip(header, [f.strip() for f in fields]))
                prepared = _prepare_account_row(row, user.id)
                if prepared is None:
                    invalid += 1
                    total += 1
                    continue

                plain_pw = (row.get("password") or row.get("password_plain") or "").strip()
                prepared["password_encrypted"] = encrypt_password(plain_pw) if plain_pw else None

                batch.append(prepared)
                total += 1

                if len(batch) >= _BULK_BATCH_SIZE:
                    created += await _insert_batch(db, batch)
                    batch.clear()

        # Flush leftover partial line (no trailing newline at EOF).
        if leftover:
            line = leftover.decode("utf-8", errors="replace").rstrip("\r")
            if line and header is not None:
                reader = csv.reader([line])
                fields = next(reader, None)
                if fields:
                    row = dict(zip(header, [f.strip() for f in fields]))
                    prepared = _prepare_account_row(row, user.id)
                    if prepared:
                        plain_pw = (
                            row.get("password") or row.get("password_plain") or ""
                        ).strip()
                        prepared["password_encrypted"] = encrypt_password(plain_pw) if plain_pw else None
                        batch.append(prepared)
                        total += 1
                    else:
                        invalid += 1
                        total += 1

        if batch:
            created += await _insert_batch(db, batch)

    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"CSV parse error: {exc}") from exc
    finally:
        await file.close()

    await db.commit()
    skipped = total - created
    return BulkImportResult(created=created, skipped=skipped, total=total)


@router.post(
    "/accounts/round-robin",
    response_model=dict,
    dependencies=[Depends(require_permission("accounts", "execute"))],
)
async def round_robin_assign_endpoint(body: RoundRobinBody, db: DB, user: CurrentUser):
    """Auto-assign active accounts to devices in round-robin order."""
    active_ids = await list_active_account_ids(db, body.account_ids)
    created = await round_robin_assign(db, active_ids, body.device_ids)
    await db.commit()
    return {
        "created": created,
        "accounts": len(active_ids),
        "accounts_requested": len(body.account_ids),
        "devices": len(body.device_ids),
    }


@router.post(
    "/accounts/{account_id}/state",
    response_model=AccountStateTransitionOut,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_permission("accounts", "update"))],
)
async def transition_account_state(
    account_id: str,
    body: AccountStateTransitionBody,
    db: DB,
    user: CurrentUser,
):
    """Transition account FSM state with validation, audit, and domain event."""
    await _get_account_or_404(account_id, db)
    svc = AccountStateService()
    try:
        account = await svc.transition(
            db,
            account_id,
            to=body.to,
            reason=body.reason,
            ttl_seconds=body.ttl_seconds,
            actor=user.id,
            expected_state_changed_at=body.expected_state_changed_at,
        )
    except AccountStateError as exc:
        _raise_account_state_http(exc)

    await _commit_and_flush_events(db)
    return AccountStateTransitionOut(
        id=account.id,
        state=account.state,
        status=account.status,
        state_reason=account.state_reason,
        state_changed_at=account.state_changed_at,
        cooldown_until=account.cooldown_until,
    )


@router.get(
    "/accounts/{account_id}",
    response_model=AccountWithLinksOut,
    dependencies=[Depends(require_permission("accounts", "read"))],
)
async def get_account_endpoint(account_id: str, db: DB, user: CurrentUser):
    """Get account details including device links."""
    account = await _get_account_or_404(account_id, db)
    return _account_to_detail_out(account)


@router.get(
    "/accounts/{account_id}/events",
    response_model=AccountEventListOut,
    dependencies=[Depends(require_permission("accounts", "read"))],
)
async def list_account_events_endpoint(
    account_id: str,
    db: DB,
    user: CurrentUser,
    limit: int = Query(50, ge=1, le=200),
    cursor: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
):
    """Paginated account profile / session timeline (newest first)."""
    account = await _get_account_or_404(account_id, db)
    if account.user_id and not await resource_visible_to_user(
        db,
        user,
        owner_user_id=account.user_id,
        org_id=getattr(account, "org_id", None),
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    items, next_cursor, has_more = await list_account_events(
        db,
        account_id,
        limit=limit,
        cursor=cursor,
        event_type=event_type,
    )
    return AccountEventListOut(
        items=[AccountEventOut.model_validate(row) for row in items],
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.patch(
    "/accounts/{account_id}",
    response_model=AccountOut,
    dependencies=[Depends(require_permission("accounts", "update"))],
)
async def update_account_endpoint(
    account_id: str, body: AccountUpdate, db: DB, user: CurrentUser
):
    """Update account fields. Password (if provided) is re-encrypted before storage."""
    existing = await _get_account_or_404(account_id, db)
    enc_pw = encrypt_password(body.password) if body.password else None
    account = await update_account(
        db,
        account_id,
        password_encrypted=enc_pw,
        display_name=body.display_name,
        notes=body.notes,
        tags=body.tags,
        proxy_id=body.proxy_id,
        account_metadata=body.account_metadata,
    )
    get_account_event_recorder().record(
        account_id=account_id,
        event_type=AccountEventType.UPDATED,
        user_id=user.id,
        platform=existing.platform,
    )
    await _commit_and_flush_events(db)
    return _account_to_out(account)


@router.delete(
    "/accounts/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("accounts", "delete"))],
)
async def delete_account_endpoint(account_id: str, db: DB, user: CurrentUser):
    """Delete account and all its device links (cascade)."""
    existing = await _get_account_or_404(account_id, db)
    get_account_event_recorder().record(
        account_id=account_id,
        event_type=AccountEventType.DELETED,
        user_id=user.id,
        platform=existing.platform,
        details={"username": existing.username},
    )
    await delete_account(db, account_id)
    await _commit_and_flush_events(db)


@router.patch(
    "/accounts/{account_id}/status",
    response_model=AccountOut,
    dependencies=[Depends(require_permission("accounts", "update"))],
)
async def update_account_status(
    account_id: str, body: AccountStatusUpdate, db: DB, user: CurrentUser
):
    """Set account status via FSM (legacy alias). Prefer POST /state."""
    await _get_account_or_404(account_id, db)
    ttl = body.ttl_seconds
    if body.status == "cooldown" and ttl is None:
        ttl = _DEFAULT_COOLDOWN_SECONDS
    svc = AccountStateService()
    try:
        account = await svc.transition(
            db,
            account_id,
            to=body.status,
            reason=body.reason,
            ttl_seconds=ttl if body.status == "cooldown" else None,
            actor=user.id,
        )
    except AccountStateError as exc:
        _raise_account_state_http(exc)
    await _commit_and_flush_events(db)
    return _account_to_out(account)


# ── Account ↔ Device assignment endpoints ─────────────────────────────────────


@router.get(
    "/accounts/{account_id}/devices",
    response_model=List[DeviceAccountOut],
    dependencies=[Depends(require_permission("accounts", "read"))],
)
async def list_account_devices_endpoint(account_id: str, db: DB, user: CurrentUser):
    """List all device-account links for an account."""
    await _get_account_or_404(account_id, db)
    links = await list_account_devices(db, account_id)
    return [_link_to_out(lnk) for lnk in links]


@router.post(
    "/accounts/{account_id}/devices",
    response_model=DeviceAccountOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("accounts", "update"))],
)
async def assign_device_to_account(
    account_id: str, body: AssignDeviceBody, db: DB, user: CurrentUser
):
    """Assign a device to an account."""
    account = await _get_account_for_user_or_404(account_id, db, user)
    device = await _get_device_for_user_or_404(body.device_id, db, user)
    link = await assign_account_to_device(
        db, body.device_id, account_id, is_primary=body.is_primary
    )
    if body.is_primary and account.platform == "facebook":
        session = await mark_login_required_for_primary_change(
            db,
            org_id=device.org_id,
            device_id=body.device_id,
            account_id=account_id,
            platform=account.platform,
        )
        get_account_event_recorder().record(
            account_id=account_id,
            event_type=AccountEventType.SESSION_LOGIN_REQUIRED,
            user_id=user.id,
            device_serial=device.serial,
            platform=account.platform,
            entity_type="device",
            entity_id=body.device_id,
            details={"reason": session.state_reason, "session_id": session.id},
        )
    get_account_event_recorder().record(
        account_id=account_id,
        event_type=AccountEventType.DEVICE_ASSIGNED,
        user_id=user.id,
        entity_type="device",
        entity_id=body.device_id,
        details={"is_primary": body.is_primary},
    )
    await _commit_and_flush_events(db)
    return _link_to_out(link)


@router.delete(
    "/accounts/{account_id}/devices/{device_id}",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_permission("accounts", "update"))],
)
async def unassign_device_from_account(
    account_id: str, device_id: str, db: DB, user: CurrentUser
):
    """Remove a device-account link."""
    account = await _get_account_for_user_or_404(account_id, db, user)
    device = await _get_device_for_user_or_404(device_id, db, user)
    result = await db.execute(
        select(DeviceAccount).where(
            DeviceAccount.device_id == device_id,
            DeviceAccount.account_id == account_id,
        )
    )
    link = result.scalar_one_or_none()
    invalidated = None
    if link is not None and account.platform == "facebook":
        invalidated = await invalidate_if_account_holds_provenance(
            db,
            org_id=device.org_id,
            device_id=device_id,
            account_id=account_id,
            platform=account.platform,
        )
    removed = await unassign_account_from_device(db, device_id, account_id)
    if removed:
        get_account_event_recorder().record(
            account_id=account_id,
            event_type=AccountEventType.DEVICE_UNASSIGNED,
            user_id=user.id,
            entity_type="device",
            entity_id=device_id,
        )
        if invalidated is not None and invalidated.state_reason == "provenance_account_unassigned":
            get_account_event_recorder().record(
                account_id=account_id,
                event_type=AccountEventType.SESSION_INVALIDATED,
                user_id=user.id,
                device_serial=device.serial,
                platform=account.platform,
                entity_type="device",
                entity_id=device_id,
                details={"reason": invalidated.state_reason, "session_id": invalidated.id},
            )
    await _commit_and_flush_events(db)
    return {"ok": removed, "account_id": account_id, "device_id": device_id}


# ── Device-centric account endpoints ──────────────────────────────────────────


@router.get(
    "/devices/{device_id}/accounts",
    response_model=List[DeviceAccountOut],
    dependencies=[Depends(require_permission("accounts", "read"))],
)
async def list_device_accounts_endpoint(device_id: str, db: DB, user: CurrentUser):
    """List all accounts assigned to a device."""
    await _get_device_for_user_or_404(device_id, db, user)
    links = await list_device_accounts(db, device_id)
    return [_link_to_out(lnk) for lnk in links]


@router.post(
    "/devices/{device_id}/accounts",
    response_model=DeviceAccountOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("accounts", "update"))],
)
async def assign_account_to_device_endpoint(
    device_id: str, body: AssignAccountBody, db: DB, user: CurrentUser
):
    """Assign an account to a device."""
    device = await _get_device_for_user_or_404(device_id, db, user)
    account = await _get_account_for_user_or_404(body.account_id, db, user)
    link = await assign_account_to_device(
        db, device_id, body.account_id, is_primary=body.is_primary
    )
    if body.is_primary and account.platform == "facebook":
        session = await mark_login_required_for_primary_change(
            db,
            org_id=device.org_id,
            device_id=device_id,
            account_id=body.account_id,
            platform=account.platform,
        )
        get_account_event_recorder().record(
            account_id=body.account_id,
            event_type=AccountEventType.SESSION_LOGIN_REQUIRED,
            user_id=user.id,
            device_serial=device.serial,
            platform=account.platform,
            entity_type="device",
            entity_id=device_id,
            details={"reason": session.state_reason, "session_id": session.id},
        )
    await _commit_and_flush_events(db)
    return _link_to_out(link)


@router.post(
    "/devices/{device_id}/accounts/{account_id}/verify",
    response_model=AccountVerificationOut,
    dependencies=[Depends(require_permission("accounts", "update"))],
)
async def verify_account_on_device_endpoint(
    device_id: str,
    account_id: str,
    request: Request,
    db: DB,
    user: CurrentUser,
):
    from services.account_verification import (
        load_verification_targets,
        persist_verification_results,
        verify_targets,
    )

    device = await _get_device_for_user_or_404(device_id, db, user)
    user_org_id = getattr(user, "org_id", None)
    account = await get_account(db, account_id)
    if account is None or (user_org_id and account.org_id != user_org_id):
        raise HTTPException(status_code=404, detail="Account not found")
    targets = await load_verification_targets(
        db, assignments=[(device_id, account_id)], org_id=user_org_id
    )
    target = targets.get((device_id, account_id))
    if target is None:
        raise HTTPException(status_code=404, detail="Device-account link not found")
    await db.commit()
    results = await verify_targets([target], getattr(request.app.state, "manager", None))
    verification = results[target.assignment_id]
    await persist_verification_results(db, [verification])
    await db.commit()
    return AccountVerificationOut(
        assignment_id=verification.assignment_id,
        status=verification.status.value,
        reason=verification.reason,
        attempted_at=verification.attempted_at,
        verified_at=verification.attempted_at if verification.status.value == "verified" else None,
        attempt_id=verification.attempt_id,
        duration_ms=verification.duration_ms,
    )


@router.post(
    "/devices/{device_id}/accounts/primary",
    response_model=DeviceAccountOut,
    dependencies=[Depends(require_permission("accounts", "update"))],
)
async def set_primary_account_endpoint(
    device_id: str, body: SetPrimaryBody, db: DB, user: CurrentUser
):
    """Set the primary account for a device (demotes existing primary)."""
    device = await _get_device_for_user_or_404(device_id, db, user)
    account = await _get_account_for_user_or_404(body.account_id, db, user)
    link = await set_primary_account(db, device_id, body.account_id)
    if not link:
        raise HTTPException(
            status_code=404,
            detail="Device-account link not found — assign the account first",
        )
    if account.platform == "facebook":
        session = await mark_login_required_for_primary_change(
            db,
            org_id=device.org_id,
            device_id=device_id,
            account_id=body.account_id,
            platform=account.platform,
        )
        if session.state_reason == "primary_account_changed":
            get_account_event_recorder().record(
                account_id=body.account_id,
                event_type=AccountEventType.SESSION_LOGIN_REQUIRED,
                user_id=user.id,
                device_serial=device.serial,
                platform=account.platform,
                entity_type="device",
                entity_id=device_id,
                details={"reason": session.state_reason, "session_id": session.id},
            )
    await _commit_and_flush_events(db)
    return _link_to_out(link)


@router.get(
    "/devices/{device_id}/platform-sessions",
    response_model=List[DevicePlatformSessionOut],
    dependencies=[Depends(require_permission("accounts", "read"))],
)
async def list_device_platform_sessions_endpoint(device_id: str, db: DB, user: CurrentUser):
    """List platform session provenance rows for a device."""
    device = await _get_device_for_user_or_404(device_id, db, user)
    sessions = await list_platform_sessions(db, org_id=device.org_id, device_id=device_id)
    return [_session_to_out(session) for session in sessions]


@router.get(
    "/devices/{device_id}/platform-sessions/facebook",
    response_model=DevicePlatformSessionOut,
    dependencies=[Depends(require_permission("accounts", "read"))],
)
async def get_facebook_platform_session_endpoint(device_id: str, db: DB, user: CurrentUser):
    """Return the Facebook session provenance row, creating an unknown row on first read."""
    device = await _get_device_for_user_or_404(device_id, db, user)
    session = await get_or_create_platform_session(db, org_id=device.org_id, device_id=device_id)
    await db.commit()
    return _session_to_out(session)


@router.post(
    "/devices/{device_id}/platform-sessions/facebook/confirm",
    response_model=DevicePlatformSessionOut,
    dependencies=[Depends(require_permission("accounts", "update"))],
)
async def confirm_facebook_platform_session_endpoint(
    device_id: str,
    body: ConfirmPlatformSessionBody,
    db: DB,
    user: CurrentUser,
):
    """Operator-confirm the current Facebook session for migration only."""
    device = await _get_device_for_user_or_404(device_id, db, user)
    account, _link = await _require_assigned_account(device_id, body.account_id, db, user)
    if account.platform != "facebook":
        raise HTTPException(status_code=422, detail="Only facebook platform is supported")
    try:
        session = await mark_active(
            db,
            org_id=device.org_id,
            device_id=device_id,
            account_id=body.account_id,
            platform=account.platform,
            establishment_method="operator_confirmed",
            reason=body.reason,
            expected_version=body.expected_version,
            app_version=body.app_version,
            display_name_observed=body.display_name_observed,
            evidence={**body.evidence, "actor": user.id},
        )
    except DevicePlatformSessionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    get_account_event_recorder().record(
        account_id=body.account_id,
        event_type=AccountEventType.SESSION_CONFIRMED,
        user_id=user.id,
        device_serial=device.serial,
        platform=account.platform,
        entity_type="device",
        entity_id=device_id,
        details={"reason": body.reason, "session_id": session.id, "method": "operator_confirmed"},
    )
    await _commit_and_flush_events(db)
    return _session_to_out(session)


@router.post(
    "/devices/{device_id}/platform-sessions/facebook/invalidate",
    response_model=DevicePlatformSessionOut,
    dependencies=[Depends(require_permission("accounts", "update"))],
)
async def invalidate_facebook_platform_session_endpoint(
    device_id: str,
    body: InvalidatePlatformSessionBody,
    db: DB,
    user: CurrentUser,
):
    """Invalidate the current Facebook provenance row."""
    device = await _get_device_for_user_or_404(device_id, db, user)
    current = await get_or_create_platform_session(db, org_id=device.org_id, device_id=device_id)
    prior_account_id = current.account_id
    try:
        session = await invalidate_platform_session(
            db,
            org_id=device.org_id,
            device_id=device_id,
            reason=body.reason,
            expected_version=body.expected_version,
            evidence={**body.evidence, "actor": user.id},
        )
    except DevicePlatformSessionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if prior_account_id:
        get_account_event_recorder().record(
            account_id=prior_account_id,
            event_type=AccountEventType.SESSION_INVALIDATED,
            user_id=user.id,
            device_serial=device.serial,
            platform="facebook",
            entity_type="device",
            entity_id=device_id,
            details={"reason": body.reason, "session_id": session.id},
        )
    await _commit_and_flush_events(db)
    return _session_to_out(session)


@router.get(
    "/devices/{device_id}/platform-sessions/facebook/login-attempts",
    response_model=List[DevicePlatformLoginAttemptOut],
    dependencies=[Depends(require_permission("accounts", "read"))],
)
async def list_facebook_login_attempts_endpoint(
    device_id: str,
    db: DB,
    user: CurrentUser,
    limit: int = Query(20, ge=1, le=100),
):
    device = await _get_device_for_user_or_404(device_id, db, user)
    attempts = await list_login_attempts(db, org_id=device.org_id, device_id=device_id, limit=limit)
    return [_login_attempt_to_out(attempt) for attempt in attempts]


@router.post(
    "/devices/{device_id}/platform-sessions/facebook/login-attempts",
    response_model=DevicePlatformLoginAttemptOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("accounts", "update"))],
)
async def start_facebook_login_attempt_endpoint(
    device_id: str,
    body: StartFacebookLoginAttemptBody,
    db: DB,
    user: CurrentUser,
):
    device = await _get_device_for_user_or_404(device_id, db, user)
    account, _link = await _require_assigned_account(device_id, body.account_id, db, user)
    if account.platform != "facebook":
        raise HTTPException(status_code=422, detail="Only facebook platform is supported")
    try:
        attempt = await start_facebook_login_attempt(
            db,
            org_id=device.org_id,
            device_id=device_id,
            account_id=body.account_id,
            actor_user_id=user.id,
            owner_id=f"login:{body.account_id}",
            evidence={**body.evidence, "actor": user.id},
        )
    except DeviceSessionError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc
    await _commit_and_flush_events(db)
    return _login_attempt_to_out(attempt)


@router.post(
    "/devices/{device_id}/platform-sessions/facebook/login-attempts/controlled",
    response_model=DevicePlatformLoginAttemptOut,
    dependencies=[Depends(require_permission("accounts", "update"))],
)
async def start_controlled_facebook_login_attempt_endpoint(
    device_id: str,
    body: StartFacebookLoginAttemptBody,
    db: DB,
    user: CurrentUser,
):
    await _get_device_for_user_or_404(device_id, db, user)
    await _require_assigned_account(device_id, body.account_id, db, user)
    try:
        await start_controlled_facebook_login_attempt()
    except ControlledLoginDisabled as exc:
        raise HTTPException(status_code=423, detail={"code": exc.code, "message": str(exc)}) from exc
    raise HTTPException(status_code=501, detail={"code": "controlled_login_unimplemented"})


@router.post(
    "/devices/{device_id}/platform-sessions/facebook/login-attempts/{attempt_id}/complete",
    response_model=DevicePlatformLoginAttemptOut,
    dependencies=[Depends(require_permission("accounts", "update"))],
)
async def complete_facebook_login_attempt_endpoint(
    device_id: str,
    attempt_id: str,
    body: CompleteFacebookLoginAttemptBody,
    request: Request,
    db: DB,
    user: CurrentUser,
):
    device = await _get_device_for_user_or_404(device_id, db, user)
    attempt = await get_login_attempt(db, org_id=device.org_id, attempt_id=attempt_id)
    if attempt is None or attempt.device_id != device_id:
        raise HTTPException(status_code=404, detail="Login attempt not found")
    try:
        completed = await complete_facebook_login_attempt(
            db,
            attempt=attempt,
            actor_user_id=user.id,
            device_serial=device.serial,
            manager=getattr(request.app.state, "manager", None),
            operator_confirmed=body.operator_confirmed,
            evidence=body.evidence,
        )
    except DevicePlatformLoginAttemptConflict as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc
    await _commit_and_flush_events(db)
    return _login_attempt_to_out(completed)


@router.post(
    "/devices/{device_id}/platform-sessions/facebook/login-attempts/{attempt_id}/cancel",
    response_model=DevicePlatformLoginAttemptOut,
    dependencies=[Depends(require_permission("accounts", "update"))],
)
async def cancel_facebook_login_attempt_endpoint(
    device_id: str,
    attempt_id: str,
    body: CancelFacebookLoginAttemptBody,
    db: DB,
    user: CurrentUser,
):
    device = await _get_device_for_user_or_404(device_id, db, user)
    attempt = await get_login_attempt(db, org_id=device.org_id, attempt_id=attempt_id)
    if attempt is None or attempt.device_id != device_id:
        raise HTTPException(status_code=404, detail="Login attempt not found")
    cancelled = await cancel_facebook_login_attempt(
        db,
        attempt=attempt,
        actor_user_id=user.id,
        reason=body.reason,
    )
    await _commit_and_flush_events(db)
    return _login_attempt_to_out(cancelled)
