from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.deps import CurrentUser, DB, require_permission
from db import crud as repo
from api.schemas.organization import OrganizationOut

router = APIRouter(prefix="/me", tags=["me"])


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
