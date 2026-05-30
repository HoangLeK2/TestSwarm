from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from api.deps import CurrentUser, DB, require_permission
from api.schemas.auth import ChangePasswordRequest
from auth.password_policy import (
    assert_password_not_reused,
    record_password_history,
    validate_password_strength,
)
from auth.password_service import hash_password, verify_password
from db import crud as repo
from api.schemas.organization import OrganizationOut
from services.security_audit import emit_security_event

router = APIRouter(prefix="/me", tags=["me"])


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    return ip, ua


@router.get(
    "/organization",
    response_model=OrganizationOut,
    dependencies=[Depends(require_permission("me", "read"))],
)
async def my_organization(db: DB, user: CurrentUser):
    org = await repo.get_current_org_for_user(db, user.id)
    if org is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    return OrganizationOut(
        id=org.id,
        businessName=org.business_name,
        businessEmail=org.business_email,
        businessLogo=org.business_logo,
        slug=getattr(org, "slug", None),
        status=getattr(org, "status", None),
        plan=getattr(org, "plan", None),
        created_at=org.created_at,
    )


@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("me", "read"))],
)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    db: DB,
    user: CurrentUser,
):
    ip, ua = _client_meta(request)
    if not verify_password(body.current_password, user.hashed_password):
        raise HTTPException(status_code=401, detail={"code": "INVALID_CREDENTIALS"})

    violations = validate_password_strength(body.new_password)
    if violations:
        await emit_security_event(
            db,
            action="password.policy_violation",
            user_id=user.id,
            org_id=getattr(user, "org_id", None),
            entity_type="user",
            entity_id=user.id,
            ip_address=ip,
            user_agent=ua,
            details={"violations": violations},
        )
        raise HTTPException(
            status_code=400,
            detail={"code": "WEAK_PASSWORD", "violations": violations},
        )

    if await assert_password_not_reused(
        db, user.id, body.new_password, current_hash=user.hashed_password
    ):
        await emit_security_event(
            db,
            action="password.policy_violation",
            user_id=user.id,
            org_id=getattr(user, "org_id", None),
            entity_type="user",
            entity_id=user.id,
            ip_address=ip,
            user_agent=ua,
            details={"reason": "reused"},
        )
        raise HTTPException(status_code=400, detail={"code": "PASSWORD_REUSED"})

    await record_password_history(db, user.id, user.hashed_password)
    user.hashed_password = hash_password(body.new_password)
    await db.flush()

    await emit_security_event(
        db,
        action="password.changed",
        user_id=user.id,
        org_id=getattr(user, "org_id", None),
        entity_type="user",
        entity_id=user.id,
        ip_address=ip,
        user_agent=ua,
    )
