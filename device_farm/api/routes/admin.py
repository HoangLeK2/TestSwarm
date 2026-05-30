"""Admin-only routes (DF-T-01-003)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from api.deps import CurrentUser, DB, require_permission
from api.schemas.organization import OrganizationMemberOut
from db import crud as repo
from services.security_audit import emit_security_event

router = APIRouter(prefix="/admin", tags=["admin"])


async def _current_org_id(db: DB, user: CurrentUser) -> str:
    org_id = getattr(user, "org_id", None)
    if not org_id:
        org = await repo.get_current_org_for_user(db, user.id)
        org_id = org.id if org else None
    if not org_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    return str(org_id)


def _member_out(member, user) -> OrganizationMemberOut:
    return OrganizationMemberOut(
        id=member.id,
        userId=user.id,
        email=user.email,
        name=user.name,
        role=member.role,
        created_at=member.created_at,
    )


@router.get(
    "/members",
    response_model=list[OrganizationMemberOut],
    dependencies=[Depends(require_permission("organizations", "manage"))],
)
async def admin_list_members(request: Request, db: DB, user: CurrentUser):
    org_id = await _current_org_id(db, user)
    rows = await repo.list_organization_members(db, org_id)
    await emit_security_event(
        db,
        action="admin.access",
        user_id=user.id,
        org_id=org_id,
        entity_type="route",
        entity_id="admin.members",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        details={"path": request.url.path},
    )
    return [_member_out(member, u) for member, u in rows]
