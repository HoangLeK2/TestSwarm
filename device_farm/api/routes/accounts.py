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
    PATCH  /api/accounts/{id}/status                 Update status
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
from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status

from api.deps import CurrentUser, DB
from api.schemas.account import (
    AccountCreate,
    AccountOut,
    AccountStatusUpdate,
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
from common.crypto import encrypt_password
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
    list_device_accounts,
    round_robin_assign,
    set_primary_account,
    unassign_account_from_device,
    update_account,
)

router = APIRouter(tags=["accounts"])


# ── Helpers ────────────────────────────────────────────────────────────────────


def _account_to_out(account) -> AccountOut:
    return AccountOut(
        id=account.id,
        platform=account.platform,
        username=account.username,
        display_name=account.display_name or "",
        status=account.status,
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
    )


async def _get_account_or_404(account_id: str, db):
    account = await get_account(db, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


# ── Account endpoints ──────────────────────────────────────────────────────────


@router.get("/accounts", response_model=List[AccountOut])
async def list_accounts_endpoint(
    db: DB,
    user: CurrentUser,
    platform: Optional[str] = Query(None),
    account_status: Optional[str] = Query(None, alias="status"),
    tags: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List accounts owned by the current user with optional filters."""
    accounts = await list_accounts(
        db,
        platform=platform,
        status=account_status,
        tags=tags,
        user_id=user.id,
        limit=limit,
        offset=offset,
    )
    return [_account_to_out(a) for a in accounts]


@router.post("/accounts", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
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
        account_metadata=body.account_metadata,
    )
    await db.commit()
    account = await get_account(db, account.id)
    return _account_to_out(account)


@router.post("/accounts/import", response_model=BulkImportResult, status_code=status.HTTP_200_OK)
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
)
async def bulk_import_csv(
    db: DB,
    user: CurrentUser,
    file: UploadFile = File(..., description="CSV file with columns: platform, username, password, display_name, tags, notes"),
):
    """
    Stream-import accounts from a CSV file upload.

    Reads the upload in 64 KB chunks, parses CSV incrementally, and flushes
    batches of up to 500 rows to the DB via INSERT ON CONFLICT DO NOTHING —
    so memory usage stays flat regardless of file size.

    Expected CSV columns: platform, username, password, display_name, tags, notes
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
                        plain_pw = (row.get("password") or "").strip()
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


@router.post("/accounts/round-robin", response_model=dict)
async def round_robin_assign_endpoint(body: RoundRobinBody, db: DB, user: CurrentUser):
    """Auto-assign accounts to devices in round-robin order."""
    created = await round_robin_assign(db, body.account_ids, body.device_ids)
    await db.commit()
    return {
        "created": created,
        "accounts": len(body.account_ids),
        "devices": len(body.device_ids),
    }


@router.get("/accounts/{account_id}", response_model=AccountWithLinksOut)
async def get_account_endpoint(account_id: str, db: DB, user: CurrentUser):
    """Get account details including device links."""
    account = await _get_account_or_404(account_id, db)
    return _account_to_detail_out(account)


@router.patch("/accounts/{account_id}", response_model=AccountOut)
async def update_account_endpoint(
    account_id: str, body: AccountUpdate, db: DB, user: CurrentUser
):
    """Update account fields. Password (if provided) is re-encrypted before storage."""
    await _get_account_or_404(account_id, db)
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
    await db.commit()
    return _account_to_out(account)


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account_endpoint(account_id: str, db: DB, user: CurrentUser):
    """Delete account and all its device links (cascade)."""
    await _get_account_or_404(account_id, db)
    await delete_account(db, account_id)
    await db.commit()


@router.patch("/accounts/{account_id}/status", response_model=AccountOut)
async def update_account_status(
    account_id: str, body: AccountStatusUpdate, db: DB, user: CurrentUser
):
    """Manually set account status (active / banned / cooldown / disabled)."""
    await _get_account_or_404(account_id, db)
    # Clear cooldown_until when manually resetting to active.
    extra: dict = {}
    if body.status == "active":
        extra["cooldown_until"] = None
        extra["usage_today_minutes"] = 0.0
    account = await update_account(db, account_id, status=body.status, **extra)
    await db.commit()
    return _account_to_out(account)


# ── Account ↔ Device assignment endpoints ─────────────────────────────────────


@router.get("/accounts/{account_id}/devices", response_model=List[DeviceAccountOut])
async def list_account_devices_endpoint(account_id: str, db: DB, user: CurrentUser):
    """List all device-account links for an account."""
    await _get_account_or_404(account_id, db)
    links = await list_account_devices(db, account_id)
    return [_link_to_out(lnk) for lnk in links]


@router.post(
    "/accounts/{account_id}/devices",
    response_model=DeviceAccountOut,
    status_code=status.HTTP_201_CREATED,
)
async def assign_device_to_account(
    account_id: str, body: AssignDeviceBody, db: DB, user: CurrentUser
):
    """Assign a device to an account."""
    await _get_account_or_404(account_id, db)
    link = await assign_account_to_device(
        db, body.device_id, account_id, is_primary=body.is_primary
    )
    await db.commit()
    return _link_to_out(link)


@router.delete(
    "/accounts/{account_id}/devices/{device_id}",
    status_code=status.HTTP_200_OK,
)
async def unassign_device_from_account(
    account_id: str, device_id: str, db: DB, user: CurrentUser
):
    """Remove a device-account link."""
    await _get_account_or_404(account_id, db)
    removed = await unassign_account_from_device(db, device_id, account_id)
    await db.commit()
    return {"ok": removed, "account_id": account_id, "device_id": device_id}


# ── Device-centric account endpoints ──────────────────────────────────────────


@router.get("/devices/{device_id}/accounts", response_model=List[DeviceAccountOut])
async def list_device_accounts_endpoint(device_id: str, db: DB, user: CurrentUser):
    """List all accounts assigned to a device."""
    links = await list_device_accounts(db, device_id)
    return [_link_to_out(lnk) for lnk in links]


@router.post(
    "/devices/{device_id}/accounts",
    response_model=DeviceAccountOut,
    status_code=status.HTTP_201_CREATED,
)
async def assign_account_to_device_endpoint(
    device_id: str, body: AssignAccountBody, db: DB, user: CurrentUser
):
    """Assign an account to a device."""
    account = await get_account(db, body.account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    link = await assign_account_to_device(
        db, device_id, body.account_id, is_primary=body.is_primary
    )
    await db.commit()
    return _link_to_out(link)


@router.post("/devices/{device_id}/accounts/primary", response_model=DeviceAccountOut)
async def set_primary_account_endpoint(
    device_id: str, body: SetPrimaryBody, db: DB, user: CurrentUser
):
    """Set the primary account for a device (demotes existing primary)."""
    link = await set_primary_account(db, device_id, body.account_id)
    if not link:
        raise HTTPException(
            status_code=404,
            detail="Device-account link not found — assign the account first",
        )
    await db.commit()
    return _link_to_out(link)
