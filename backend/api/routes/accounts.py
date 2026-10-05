"""
api/routes/accounts.py — Account & Profile Manager REST API (DF-007).

Endpoints:
    GET    /api/accounts                             List accounts
    POST   /api/accounts                             Create account
    POST   /api/accounts/import                      Bulk import (JSON)
    POST   /api/accounts/import-csv                  Bulk import (CSV text)
    GET    /api/accounts/import-formats              List TXT import formats
    POST   /api/accounts/import-txt                  Bulk import (TXT format)
    POST   /api/admin/account-import-formats         Create TXT import format
    PATCH  /api/admin/account-import-formats/{id}    Update TXT import format
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
from typing import Any, List, NoReturn, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import and_, func, or_, select

from api.auth.rbac import is_superadmin
from api.deps import CurrentUser, DB, require_permission
from api.org_scope import data_owner_user_id, resource_visible_to_user
from api.schemas.account import (
    AccountCreate,
    AccountAvailableDevicesOut,
    AccountImportFormatCreate,
    AccountImportFormatListOut,
    AccountImportFormatOut,
    AccountImportFormatUpdate,
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
from api.schemas.device import DeviceOut
from api.schemas.device_platform_session import (
    DevicePlatformSessionOut,
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
from db.crud.organization import get_organization_role_for_user, list_organization_members
from db.models.enums import AccountEventType
from db.models.account import DeviceAccount
from db.models.device import Device
from db.models.enums import AccountState
from services.account_event_recorder import get_account_event_recorder
from services.account_import_formats import (
    AccountImportFormatError,
    count_account_import_formats_by_slug,
    create_account_import_format,
    get_account_import_format,
    list_account_import_formats,
    parse_txt_accounts,
    update_account_import_format,
    validate_account_import_slug,
)
from services.account_state import (
    AccountStateError,
    AccountStateService,
    StateConflictError,
)
from services.account_verification_hold import (
    build_verification_hold_payload,
    clear_verification_hold,
    get_verification_hold,
    set_verification_hold,
)
from services.device_platform_session import (
    list_platform_sessions,
)
from services.notification_service import NotificationService

router = APIRouter(tags=["accounts"])

def _raise_account_state_http(exc: AccountStateError) -> NoReturn:
    code = (
        status.HTTP_409_CONFLICT
        if isinstance(exc, StateConflictError)
        else status.HTTP_422_UNPROCESSABLE_ENTITY
    )
    raise HTTPException(
        status_code=code,
        detail={"code": exc.code, "message": str(exc)},
    ) from exc


def _raise_account_import_format_http(exc: AccountImportFormatError) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": exc.code, "message": str(exc)},
    ) from exc


def _require_superadmin(user: CurrentUser) -> None:
    if not is_superadmin(user):
        raise HTTPException(status_code=403, detail={"code": "SUPERADMIN_ONLY"})


async def _commit_and_flush_events(db) -> None:
    await db.commit()
    rec = get_account_event_recorder()
    while rec._pending:
        flushed = await rec.flush(db)
        if flushed == 0:
            break


def _account_import_format_to_out(row) -> AccountImportFormatOut:
    return AccountImportFormatOut.model_validate(row)


# ── Helpers ────────────────────────────────────────────────────────────────────


async def _observations_for(db, accounts) -> dict[str, dict[str, Any]]:
    """Latest profile reading per account: observed name and friend count.

    Batched rather than per row — a page of 50 accounts would otherwise be 100
    round trips. Failure here must not fail the listing: these are decorations
    on an account, and losing them is better than a 500 on the accounts page.
    """
    from services.device_platform_session import observed_display_names

    ids = [a.id for a in accounts]
    if not ids:
        return {}
    org_id = getattr(accounts[0], "org_id", None)
    if not org_id:
        return {}
    try:
        names = await observed_display_names(db, org_id=org_id, account_ids=ids)
    except Exception:
        return {}
    return {
        account_id: {
            "observed_display_name": names.get(account_id),
            "friends_count": None,
            "friends_observed_at": None,
        }
        for account_id in ids
    }


async def _assigned_device_names_for(db, accounts) -> dict[str, str]:
    ids = [account.id for account in accounts]
    if not ids:
        return {}
    rows = await db.execute(
        select(DeviceAccount.account_id, Device.name)
        .join(Device, Device.id == DeviceAccount.device_id)
        .where(DeviceAccount.account_id.in_(ids))
        .order_by(
            DeviceAccount.account_id,
            DeviceAccount.is_primary.desc(),
            DeviceAccount.assigned_at.desc(),
        )
    )
    names: dict[str, str] = {}
    for account_id, device_name in rows:
        name = (device_name or "").strip()
        if name and account_id not in names:
            names[account_id] = name
    return names


def _account_to_out(
    account,
    observed: dict[str, Any] | None = None,
    assigned_device_name: str | None = None,
) -> AccountOut:
    state = getattr(account, "state", None) or account.status
    seen = observed or {}
    verification_hold = get_verification_hold(account)
    return AccountOut(
        observed_display_name=seen.get("observed_display_name"),
        friends_count=seen.get("friends_count"),
        friends_observed_at=seen.get("friends_observed_at"),
        assigned_device_name=assigned_device_name,
        verification_hold=verification_hold,
        verification_hold_until=(
            verification_hold.remind_at if verification_hold is not None else None
        ),
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


def _device_to_out(device) -> DeviceOut:
    return DeviceOut(
        id=device.id,
        db_id=device.id,
        serial=device.serial,
        device_serial=getattr(device, "device_serial", None) or device.serial,
        name=device.name,
        device_key=device.device_key,
        user_id=device.user_id,
        brand=device.brand,
        model=device.model,
        android_version=device.android_version,
        sdk_version=device.sdk_version,
        screen_width=device.screen_width,
        screen_height=device.screen_height,
        last_seen=device.last_seen,
        created_at=device.created_at,
        adb_serial=getattr(device, "adb_serial", None),
        relay_serial=getattr(device, "relay_serial", None),
        managed_by_org_id=getattr(device, "managed_by_org_id", None),
        managed_by_relay_id=getattr(device, "managed_by_relay_id", None),
        adb_ip=getattr(device, "adb_ip", None),
        adb_port=getattr(device, "adb_port", 5555),
        tags=getattr(device, "tags", "") or "",
        relay_id=getattr(device, "managed_by_relay_id", None),
        transport_online=False,
        state="unknown",
        status=getattr(device, "status", "paired") or "paired",
        paired_at=getattr(device, "paired_at", None),
        unpaired_at=getattr(device, "unpaired_at", None),
        notes=getattr(device, "notes", "") or "",
    )


async def _can_include_managed_devices(db: DB, user: CurrentUser) -> bool:
    org_id = getattr(user, "org_id", None)
    if not org_id:
        return False
    role = str(getattr(user, "org_role", "") or "").strip().lower()
    if role != "admin":
        role = (await get_organization_role_for_user(db, user.id, str(org_id))) or ""
    return role == "admin"


async def _list_available_account_devices(
    db: DB,
    *,
    account_id: str,
    user: CurrentUser,
    search: str | None,
    offset: int,
    limit: int,
) -> tuple[list[Device], int]:
    linked_device_ids = select(DeviceAccount.device_id).where(
        DeviceAccount.account_id == account_id
    )
    filters = [Device.id.not_in(linked_device_ids)]

    org_id = getattr(user, "org_id", None)
    if org_id:
        member_rows = await list_organization_members(db, str(org_id))
        member_ids = [
            str(member.user_id)
            for member, _ in member_rows
            if getattr(member, "user_id", None)
        ]
        org_conditions = [Device.org_id == org_id]
        if member_ids:
            org_conditions.append(
                and_(Device.org_id.is_(None), Device.user_id.in_(member_ids))
            )
        if await _can_include_managed_devices(db, user):
            org_conditions.append(Device.managed_by_org_id == org_id)
        filters.append(or_(*org_conditions))
    else:
        owner_id = data_owner_user_id(user)
        if owner_id:
            filters.append(Device.user_id == owner_id)

    term = (search or "").strip()
    if term:
        pattern = f"%{term}%"
        filters.append(
            or_(
                Device.name.ilike(pattern),
                Device.serial.ilike(pattern),
                Device.device_serial.ilike(pattern),
                Device.adb_serial.ilike(pattern),
                Device.relay_serial.ilike(pattern),
                Device.brand.ilike(pattern),
                Device.model.ilike(pattern),
            )
        )

    total = int(
        (
            await db.execute(
                select(func.count()).select_from(Device).where(*filters)
            )
        ).scalar_one()
        or 0
    )
    result = await db.execute(
        select(Device)
        .where(*filters)
        .order_by(Device.created_at, Device.id)
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all()), total


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


def _notification_service(request: Request) -> NotificationService:
    svc = getattr(request.app.state, "notification_service", None)
    if isinstance(svc, NotificationService):
        return svc
    return NotificationService(getattr(request.app.state, "ws_manager", None))


async def _notify_verification_hold(
    request: Request,
    *,
    account,
    hold,
    user: CurrentUser,
) -> None:
    channel_types: set[str] = set()
    if hold.notify_web:
        channel_types.add("in_app")
    if hold.notify_telegram:
        channel_types.add("telegram")
    if not channel_types:
        return
    recipient_user_id = account.user_id or user.id
    remind_at = hold.remind_at.isoformat()
    try:
        await _notification_service(request).notify(
            "account.verification_required",
            f"Account {account.username} needs verification",
            (
                f"{account.platform}:{account.username} is held in verification "
                f"until {remind_at}."
            ),
            {
                "resource_type": "account",
                "resource_id": account.id,
                "account_id": account.id,
                "resource_name": account.username,
                "platform": account.platform,
                "status": account.state,
                "remind_at": remind_at,
                "deep_link": "/dashboard/accounts",
            },
            user_id=recipient_user_id,
            channel_types=channel_types,
        )
    except Exception:
        # Account state is the source of truth; external notification delivery is
        # best-effort and already records per-channel warnings in the service.
        pass


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
    observed = await _observations_for(db, accounts)
    assigned_device_names = await _assigned_device_names_for(db, accounts)
    return [
        _account_to_out(
            account,
            observed.get(account.id),
            assigned_device_names.get(account.id),
        )
        for account in accounts
    ]


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
    created, skipped = await bulk_create_accounts(
        db,
        rows,
        user_id=user.id,
        org_id=getattr(user, "org_id", None),
    )
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
                prepared = _prepare_account_row(
                    row,
                    user.id,
                    org_id=getattr(user, "org_id", None),
                )
                if prepared is None:
                    invalid += 1
                    total += 1
                    continue

                plain_pw = (
                    row.get("password") or row.get("password_plain") or ""
                ).strip()
                prepared["password_encrypted"] = (
                    encrypt_password(plain_pw) if plain_pw else None
                )

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
                    prepared = _prepare_account_row(
                        row,
                        user.id,
                        org_id=getattr(user, "org_id", None),
                    )
                    if prepared:
                        plain_pw = (
                            row.get("password") or row.get("password_plain") or ""
                        ).strip()
                        prepared["password_encrypted"] = (
                            encrypt_password(plain_pw) if plain_pw else None
                        )
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


@router.get(
    "/accounts/import-formats",
    response_model=AccountImportFormatListOut,
    dependencies=[Depends(require_permission("accounts", "read"))],
)
async def list_account_import_formats_endpoint(
    db: DB,
    user: CurrentUser,
    include_inactive: bool = Query(False),
):
    if include_inactive:
        _require_superadmin(user)
    rows = await list_account_import_formats(db, include_inactive=include_inactive)
    return AccountImportFormatListOut(
        items=[_account_import_format_to_out(row) for row in rows]
    )


@router.post(
    "/accounts/import-txt",
    response_model=BulkImportResult,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_permission("accounts", "create"))],
)
async def bulk_import_txt(
    db: DB,
    user: CurrentUser,
    file: UploadFile = File(
        ...,
        description="TXT file containing one account per line",
    ),
    format_id: str | None = Form(default=None),
    format_slug: str | None = Form(default=None),
):
    if not format_id and not format_slug:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "IMPORT_FORMAT_REQUIRED"},
        )
    fmt = await get_account_import_format(db, format_id=format_id, slug=format_slug)
    if fmt is None:
        raise HTTPException(status_code=404, detail={"code": "IMPORT_FORMAT_NOT_FOUND"})
    content = (await file.read()).decode("utf-8", errors="replace")
    try:
        parsed = parse_txt_accounts(content, fmt)
    except AccountImportFormatError as exc:
        _raise_account_import_format_http(exc)
    finally:
        await file.close()
    created, skipped = await bulk_create_accounts(
        db,
        parsed.rows,
        user_id=user.id,
        org_id=getattr(user, "org_id", None),
    )
    await db.commit()
    return BulkImportResult(
        created=created,
        skipped=skipped + parsed.invalid,
        total=parsed.total,
    )


@router.post(
    "/admin/account-import-formats",
    response_model=AccountImportFormatOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("accounts", "manage"))],
)
async def admin_create_account_import_format(
    body: AccountImportFormatCreate,
    db: DB,
    user: CurrentUser,
):
    _require_superadmin(user)
    try:
        slug = validate_account_import_slug(body.slug)
        if await count_account_import_formats_by_slug(db, slug):
            raise HTTPException(
                status_code=409,
                detail={"code": "IMPORT_FORMAT_SLUG_EXISTS"},
            )
        row = await create_account_import_format(
            db,
            slug=slug,
            name=body.name,
            description=body.description,
            delimiter=body.delimiter,
            platform=body.platform,
            fields=body.fields,
            is_active=body.is_active,
            created_by_user_id=user.id,
        )
    except AccountImportFormatError as exc:
        _raise_account_import_format_http(exc)
    await db.commit()
    await db.refresh(row)
    return _account_import_format_to_out(row)


@router.patch(
    "/admin/account-import-formats/{format_id}",
    response_model=AccountImportFormatOut,
    dependencies=[Depends(require_permission("accounts", "manage"))],
)
async def admin_update_account_import_format(
    format_id: str,
    body: AccountImportFormatUpdate,
    db: DB,
    user: CurrentUser,
):
    _require_superadmin(user)
    row = await get_account_import_format(db, format_id=format_id, active_only=False)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "IMPORT_FORMAT_NOT_FOUND"})
    try:
        row = await update_account_import_format(
            db,
            row,
            name=body.name,
            description=body.description,
            delimiter=body.delimiter,
            platform=body.platform,
            fields=body.fields,
            is_active=body.is_active,
        )
    except AccountImportFormatError as exc:
        _raise_account_import_format_http(exc)
    await db.commit()
    await db.refresh(row)
    return _account_import_format_to_out(row)


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


@router.get(
    "/accounts/{account_id}/available-devices",
    response_model=AccountAvailableDevicesOut,
    dependencies=[Depends(require_permission("accounts", "read"))],
)
async def list_account_available_devices_endpoint(
    account_id: str,
    db: DB,
    user: CurrentUser,
    q: str | None = Query(default=None, max_length=200),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
):
    """List visible devices that are not yet linked to this account."""
    await _get_account_for_user_or_404(account_id, db, user)
    devices, total = await _list_available_account_devices(
        db,
        account_id=account_id,
        user=user,
        search=q,
        offset=offset,
        limit=limit,
    )
    return AccountAvailableDevicesOut(
        items=[_device_to_out(device) for device in devices],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/accounts/{account_id}/state",
    response_model=AccountStateTransitionOut,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_permission("accounts", "update"))],
)
async def transition_account_state(
    account_id: str,
    body: AccountStateTransitionBody,
    request: Request,
    db: DB,
    user: CurrentUser,
):
    """Transition account FSM state with validation, audit, and domain event."""
    await _get_account_or_404(account_id, db)
    if body.verification_hold is not None and body.to != AccountState.SUSPENDED.value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "VERIFICATION_HOLD_REQUIRES_SUSPENDED",
                "message": "verification hold can only be set for suspended accounts",
            },
        )
    verification_hold_payload = None
    if body.verification_hold is not None:
        try:
            verification_hold_payload = build_verification_hold_payload(
                body.verification_hold,
                actor_user_id=user.id,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "INVALID_VERIFICATION_HOLD",
                    "message": str(exc),
                },
            ) from exc
    svc = AccountStateService()
    try:
        account = await svc.transition(
            db,
            account_id,
            to=body.to,
            reason=body.reason,
            actor=user.id,
            expected_state_changed_at=body.expected_state_changed_at,
        )
    except AccountStateError as exc:
        _raise_account_state_http(exc)

    if verification_hold_payload is not None:
        set_verification_hold(account, verification_hold_payload)
        await db.flush()
    elif account.state != AccountState.SUSPENDED.value:
        clear_verification_hold(account)
        await db.flush()

    hold = get_verification_hold(account)
    await _commit_and_flush_events(db)
    if hold is not None and account.state == AccountState.SUSPENDED.value:
        await _notify_verification_hold(
            request,
            account=account,
            hold=hold,
            user=user,
        )
    return AccountStateTransitionOut(
        id=account.id,
        state=account.state,
        status=account.status,
        state_reason=account.state_reason,
        state_changed_at=account.state_changed_at,
        cooldown_until=account.cooldown_until,
        verification_hold=hold,
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
    svc = AccountStateService()
    try:
        account = await svc.transition(
            db,
            account_id,
            to=body.status,
            reason=body.reason,
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
    await _get_account_for_user_or_404(account_id, db, user)
    await _get_device_for_user_or_404(body.device_id, db, user)
    link = await assign_account_to_device(
        db, body.device_id, account_id, is_primary=body.is_primary
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
    await _get_account_for_user_or_404(account_id, db, user)
    await _get_device_for_user_or_404(device_id, db, user)
    removed = await unassign_account_from_device(db, device_id, account_id)
    if removed:
        get_account_event_recorder().record(
            account_id=account_id,
            event_type=AccountEventType.DEVICE_UNASSIGNED,
            user_id=user.id,
            entity_type="device",
            entity_id=device_id,
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
    await _get_device_for_user_or_404(device_id, db, user)
    await _get_account_for_user_or_404(body.account_id, db, user)
    link = await assign_account_to_device(
        db, device_id, body.account_id, is_primary=body.is_primary
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
    await _get_device_for_user_or_404(device_id, db, user)
    await _get_account_for_user_or_404(body.account_id, db, user)
    link = await set_primary_account(db, device_id, body.account_id)
    if not link:
        raise HTTPException(
            status_code=404,
            detail="Device-account link not found — assign the account first",
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

