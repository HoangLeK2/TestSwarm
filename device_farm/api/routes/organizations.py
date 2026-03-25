from __future__ import annotations

from fastapi import APIRouter, status

from api.deps import CurrentUser, DB
from api.schemas.organization import OrganizationCreate, OrganizationOut
from db import crud as repo

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("", response_model=list[OrganizationOut])
async def list_my_organizations(db: DB, user: CurrentUser):
  orgs = await repo.list_organizations_for_user(db, user.id)
  return [
    OrganizationOut(
      id=o.id,
      businessName=o.business_name,
      businessEmail=o.business_email,
      businessLogo=o.business_logo,
      created_at=o.created_at,
    )
    for o in orgs
  ]


@router.post("", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
async def create_organization(body: OrganizationCreate, db: DB, user: CurrentUser):
  org = await repo.create_organization(
    db,
    owner_id=user.id,
    business_name=body.businessName,
    business_email=body.businessEmail,
    business_logo=body.businessLogo,
  )
  return OrganizationOut(
    id=org.id,
    businessName=org.business_name,
    businessEmail=org.business_email,
    businessLogo=org.business_logo,
    created_at=org.created_at,
  )

