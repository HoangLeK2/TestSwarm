"""CRUD routes for account groups and their members.

Security model: every path carries the authenticated user id and scopes all
DB lookups to groups owned by that user. Cross-user access returns 404 so we
do not leak the existence of a group to an outsider.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError

from api.deps import CurrentUser, DB, require_permission
from api.org_scope import data_owner_user_id
from api.schemas.account_group import (
    AccountGroupCreate,
    AccountGroupMemberBatchAdd,
    AccountGroupMemberBatchResult,
    AccountGroupMemberOut,
    AccountGroupOut,
    AccountGroupUpdate,
)
from db.crud.account_group import (
    add_members,
    create_group,
    delete_group,
    get_group,
    list_groups,
    list_members,
    remove_member,
    update_group,
)
from common.totp import account_metadata_value, generate_totp


router = APIRouter(prefix="/account-groups", tags=["account-groups"])


def _to_out(group, member_count: int = 0) -> AccountGroupOut:
    return AccountGroupOut(
        id=group.id,
        user_id=group.user_id,
        name=group.name,
        description=group.description or "",
        platform=group.platform,
        rotation_strategy=group.rotation_strategy,
        rotation_cursor=int(group.rotation_cursor or 0),
        member_count=int(member_count or 0),
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


@router.get(
    "",
    response_model=list[AccountGroupOut],
    dependencies=[Depends(require_permission("account-groups", "read"))],
)
async def list_account_groups(
    db: DB,
    user: CurrentUser,
    platform: Optional[str] = Query(default=None),
):
    rows = await list_groups(db, user_id=data_owner_user_id(user), platform=platform)
    return [_to_out(g, c) for g, c in rows]


@router.post(
    "",
    response_model=AccountGroupOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("account-groups", "create"))],
)
async def create_account_group(
    body: AccountGroupCreate,
    db: DB,
    user: CurrentUser,
):
    try:
        group = await create_group(
            db,
            user_id=user.id,
            name=body.name,
            description=body.description,
            platform=body.platform,
            rotation_strategy=body.rotation_strategy,
            org_id=getattr(user, "org_id", None),
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Group '{body.name}' already exists for this user",
        )
    return _to_out(group, member_count=0)


@router.get(
    "/{group_id}",
    response_model=AccountGroupOut,
    dependencies=[Depends(require_permission("account-groups", "read"))],
)
async def get_account_group(group_id: str, db: DB, user: CurrentUser):
    owner_id = data_owner_user_id(user)
    group = await get_group(db, group_id, user_id=owner_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Account group not found")
    # Cheap exact count via the member list (Phase 2 groups are typically < 500 members).
    members = await list_members(db, group_id)
    return _to_out(group, member_count=len(members))


@router.patch(
    "/{group_id}",
    response_model=AccountGroupOut,
    dependencies=[Depends(require_permission("account-groups", "update"))],
)
async def update_account_group(
    group_id: str,
    body: AccountGroupUpdate,
    db: DB,
    user: CurrentUser,
):
    owner_id = data_owner_user_id(user)
    group = await get_group(db, group_id, user_id=owner_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Account group not found")
    try:
        await update_group(
            db,
            group_id,
            name=body.name,
            description=body.description,
            rotation_strategy=body.rotation_strategy,
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Another group with this name already exists",
        )
    owner_id = data_owner_user_id(user)
    group = await get_group(db, group_id, user_id=owner_id)
    assert group is not None
    members = await list_members(db, group_id)
    return _to_out(group, member_count=len(members))


@router.delete(
    "/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("account-groups", "delete"))],
)
async def delete_account_group(group_id: str, db: DB, user: CurrentUser):
    owner_id = data_owner_user_id(user)
    group = await get_group(db, group_id, user_id=owner_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Account group not found")
    await delete_group(db, group_id)
    await db.commit()


@router.get(
    "/{group_id}/members",
    response_model=list[AccountGroupMemberOut],
    dependencies=[Depends(require_permission("account-groups", "read"))],
)
async def list_account_group_members(
    group_id: str,
    db: DB,
    user: CurrentUser,
):
    owner_id = data_owner_user_id(user)
    group = await get_group(db, group_id, user_id=owner_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Account group not found")
    members = await list_members(db, group_id)
    return [
        AccountGroupMemberOut(
            account_id=m["account_id"],
            username=m["username"],
            display_name=m["display_name"],
            status=m["status"],
            position=m["position"],
            last_used_at=m["last_used_at"],
            added_at=m["added_at"],
        )
        for m in members
    ]


@router.post(
    "/{group_id}/members",
    response_model=AccountGroupMemberBatchResult,
    dependencies=[Depends(require_permission("account-groups", "update"))],
)
async def add_account_group_members(
    group_id: str,
    body: AccountGroupMemberBatchAdd,
    db: DB,
    user: CurrentUser,
):
    owner_id = data_owner_user_id(user)
    group = await get_group(db, group_id, user_id=owner_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Account group not found")
    added, skipped = await add_members(db, group=group, account_ids=body.account_ids)
    await db.commit()
    return AccountGroupMemberBatchResult(added=added, skipped=skipped)


@router.delete(
    "/{group_id}/members/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("account-groups", "update"))],
)
async def remove_account_group_member(
    group_id: str,
    account_id: str,
    db: DB,
    user: CurrentUser,
):
    owner_id = data_owner_user_id(user)
    group = await get_group(db, group_id, user_id=owner_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Account group not found")
    removed = await remove_member(db, group_id=group_id, account_id=account_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Account is not a member of this group")
    await db.commit()


@router.post(
    "/{group_id}/resolve",
    dependencies=[Depends(require_permission("account-groups", "execute"))],
)
async def resolve_account_group(
    group_id: str,
    db: DB,
    user: CurrentUser,
):
    """Pick one usable account and return the ``__ACCOUNT_*`` variable bundle.

    Used by the Control Record "Run test" / step-by-step flow so the same
    account is reused across multiple preview calls in one session — avoids
    login-step mismatch where step 2 (username) and step 3 (password) would
    otherwise be satisfied from two different accounts. Advances the group's
    rotation cursor just like a real dispatch so repeated sessions rotate.
    """
    owner_id = data_owner_user_id(user)
    group = await get_group(db, group_id, user_id=owner_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Account group not found")
    from db.crud.account_group import pick_next_batch
    from common.crypto import decrypt_password

    accounts = await pick_next_batch(db, group_id, 1)
    if not accounts:
        await db.commit()
        raise HTTPException(
            status_code=409,
            detail="Account group is empty or all members are banned/cooling down",
        )
    account = accounts[0]
    vars_: dict = {
        "__ACCOUNT_ID__": str(account.id),
        "__ACCOUNT_USERNAME__": account.username,
        "__ACCOUNT_DISPLAY_NAME__": account.display_name or "",
        "__ACCOUNT_PLATFORM__": account.platform,
    }
    if account.password_encrypted:
        try:
            vars_["__ACCOUNT_PASSWORD__"] = decrypt_password(account.password_encrypted)
        except Exception:
            vars_["__ACCOUNT_PASSWORD__"] = ""
    metadata = account.account_metadata or {}
    email = account_metadata_value(metadata, "email", "login_email", "account_email")
    if email:
        vars_["__ACCOUNT_EMAIL__"] = email
    totp_secret = account_metadata_value(
        metadata,
        "totp_secret",
        "two_factor_secret",
        "authenticator_secret",
        "otp_secret",
        "2fa_secret",
    )
    if totp_secret:
        try:
            vars_["__ACCOUNT_TOTP_CODE__"] = generate_totp(totp_secret)
        except Exception:
            vars_["__ACCOUNT_TOTP_CODE__"] = ""
    await db.commit()
    return {"variables": vars_, "account_id": str(account.id)}
