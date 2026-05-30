from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from api.deps import CurrentUser, DB, require_permission
from api.auth.rbac import is_superadmin
from api.schemas.organization import (
  OrganizationCreate,
  OrganizationInvitationAccept,
  OrganizationInvitationAcceptOut,
  OrganizationInvitationPreview,
  OrganizationListOut,
  OrganizationMemberInvite,
  OrganizationMemberInviteOut,
  OrganizationMemberOut,
  OrganizationMemberUpdate,
  OrganizationOut,
)
from db import crud as repo
from db.crud import organization_invite as invite_repo
from services.organization_invite import (
  accept_organization_invitation,
  create_and_email_invitation,
  invitation_is_expired,
)
from auth.lockout import admin_unlock
from services.security_audit import emit_security_event

router = APIRouter(prefix="/organizations", tags=["organizations"])


def _client_meta(request: Request) -> tuple[str | None, str | None]:
  ip = request.client.host if request.client else None
  ua = request.headers.get("user-agent")
  return ip, ua


def _org_to_out(org) -> OrganizationOut:
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


async def _current_org_id(db: DB, user: CurrentUser) -> str:
  org_id = getattr(user, "org_id", None)
  if not org_id:
    org = await repo.get_current_org_for_user(db, user.id)
    org_id = org.id if org else None
  if not org_id:
    raise HTTPException(status_code=404, detail={"code": "NO_ORGANIZATION"})
  return str(org_id)


@router.get(
  "",
  response_model=OrganizationListOut,
  dependencies=[Depends(require_permission("organizations", "read"))],
)
async def list_my_organizations(
  db: DB,
  user: CurrentUser,
  search: str | None = None,
  offset: int = Query(0, ge=0),
  limit: int = Query(50, ge=1, le=100),
  ensure_id: str | None = Query(None, description="Always include this org if accessible"),
):
  scope_user_id = None if is_superadmin(user) else user.id
  orgs, total = await repo.query_organizations(
    db,
    user_id=scope_user_id,
    search=search,
    offset=offset,
    limit=limit,
    ensure_id=ensure_id,
  )
  return OrganizationListOut(
    items=[_org_to_out(o) for o in orgs],
    total=total,
    offset=offset,
    limit=limit,
  )


@router.post(
  "",
  response_model=OrganizationOut,
  status_code=status.HTTP_201_CREATED,
  dependencies=[Depends(require_permission("organizations", "create"))],
)
async def create_organization(body: OrganizationCreate, db: DB, user: CurrentUser):
  org = await repo.create_organization(
    db,
    owner_id=user.id,
    business_name=body.businessName,
    business_email=body.businessEmail,
    business_logo=body.businessLogo,
  )
  return _org_to_out(org)


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
  dependencies=[Depends(require_permission("organizations", "read"))],
)
async def list_organization_members(db: DB, user: CurrentUser):
  org_id = await _current_org_id(db, user)
  rows = await repo.list_organization_members(db, org_id)
  return [_member_out(member, u) for member, u in rows]


@router.post(
  "/members",
  response_model=OrganizationMemberInviteOut,
  status_code=status.HTTP_201_CREATED,
  dependencies=[Depends(require_permission("organizations", "manage"))],
)
async def invite_organization_member(
  body: OrganizationMemberInvite, request: Request, db: DB, user: CurrentUser
):
  org_id = await _current_org_id(db, user)
  ip, ua = _client_meta(request)
  email = (body.email or "").strip().lower()
  if not email:
    raise HTTPException(status_code=400, detail={"code": "INVALID_EMAIL"})

  invite_role = (body.role or "member").strip().lower()
  if invite_role not in ("member", "supervisor"):
    raise HTTPException(status_code=400, detail={"code": "INVALID_ROLE"})

  try:
    invitation, existing_user, email_sent = await create_and_email_invitation(
      db,
      organization_id=org_id,
      email=email,
      role=invite_role,
      invited_by_user_id=user.id,
      inviter_name=getattr(user, "name", None),
    )
  except ValueError as exc:
    code = str(exc)
    if code == "ALREADY_MEMBER":
      raise HTTPException(status_code=409, detail={"code": "ALREADY_MEMBER"})
    if code == "ORG_NOT_FOUND":
      raise HTTPException(status_code=404, detail={"code": "NO_ORGANIZATION"})
    raise

  await emit_security_event(
    db,
    action="member.invited",
    user_id=user.id,
    org_id=org_id,
    entity_type="user",
    entity_id=None,
    ip_address=ip,
    user_agent=ua,
    details={"email": invitation.email, "role": invitation.role},
  )

  return OrganizationMemberInviteOut(
    email=invitation.email,
    status="invited",
    existingUser=existing_user,
    emailSent=email_sent,
  )


@router.post(
  "/invitations/accept",
  response_model=OrganizationInvitationAcceptOut,
  dependencies=[Depends(require_permission("organizations", "read"))],
)
async def accept_organization_invitation_route(
  body: OrganizationInvitationAccept, db: DB, user: CurrentUser
):
  token = (body.token or "").strip()
  if not token:
    raise HTTPException(status_code=400, detail={"code": "INVALID_TOKEN"})

  try:
    org_id, org_name = await accept_organization_invitation(
      db, token=token, user=user
    )
  except ValueError as exc:
    code = str(exc)
    status_code = 400
    if code == "INVITE_NOT_FOUND":
      status_code = 404
    elif code == "INVITE_EXPIRED":
      status_code = 410
    elif code == "INVITE_NOT_PENDING":
      status_code = 409
    elif code == "INVITE_EMAIL_MISMATCH":
      status_code = 403
    elif code == "ORG_DISABLED":
      status_code = 403
    raise HTTPException(status_code=status_code, detail={"code": code})

  return OrganizationInvitationAcceptOut(
    organizationId=org_id,
    organizationName=org_name,
  )


@router.get(
  "/invitations/{token}",
  response_model=OrganizationInvitationPreview,
)
async def preview_organization_invitation(token: str, db: DB):
  invitation = await invite_repo.get_invitation_by_token(db, token)
  if invitation is None:
    raise HTTPException(status_code=404, detail={"code": "INVITE_NOT_FOUND"})

  org = await invite_repo.get_organization_by_id(db, invitation.organization_id)
  if org is None:
    raise HTTPException(status_code=404, detail={"code": "INVITE_NOT_FOUND"})

  target = await repo.get_user_by_email(db, invitation.email)
  expired = invitation_is_expired(invitation) or invitation.status != "pending"

  return OrganizationInvitationPreview(
    organizationName=org.business_name,
    email=invitation.email,
    status=invitation.status,
    expired=expired,
    existingUser=target is not None,
  )


@router.patch(
  "/members/{member_user_id}",
  response_model=OrganizationMemberOut,
  dependencies=[Depends(require_permission("organizations", "manage"))],
)
async def update_organization_member(
  member_user_id: str,
  body: OrganizationMemberUpdate,
  request: Request,
  db: DB,
  user: CurrentUser,
):
  org_id = await _current_org_id(db, user)
  ip, ua = _client_meta(request)
  new_role = (body.role or "").strip().lower()
  if new_role not in ("member", "supervisor"):
    raise HTTPException(status_code=400, detail={"code": "INVALID_ROLE"})
  if member_user_id == user.id:
    raise HTTPException(status_code=400, detail={"code": "CANNOT_CHANGE_OWN_ROLE"})

  member = await repo.get_organization_member(db, org_id, member_user_id)
  if member is None:
    raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
  old_role = member.role
  if member.role == "owner":
    raise HTTPException(status_code=400, detail={"code": "CANNOT_CHANGE_OWNER"})
  if member.role == new_role:
    target_user = await repo.get_user(db, member_user_id)
    if target_user is None:
      raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    return _member_out(member, target_user)

  updated = await repo.update_organization_member_role(
    db,
    organization_id=org_id,
    user_id=member_user_id,
    role=new_role,
  )
  if updated is None:
    raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
  target_user = await repo.get_user(db, member_user_id)
  if target_user is None:
    raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
  await emit_security_event(
    db,
    action="member.role_changed",
    user_id=user.id,
    org_id=org_id,
    entity_type="user",
    entity_id=member_user_id,
    ip_address=ip,
    user_agent=ua,
    details={"old_role": old_role, "new_role": new_role},
  )
  return _member_out(updated, target_user)


@router.post(
  "/members/{member_user_id}/unlock",
  status_code=status.HTTP_204_NO_CONTENT,
  dependencies=[Depends(require_permission("organizations", "manage"))],
)
async def unlock_organization_member(
  member_user_id: str,
  request: Request,
  db: DB,
  user: CurrentUser,
):
  org_id = await _current_org_id(db, user)
  ip, ua = _client_meta(request)
  member = await repo.get_organization_member(db, org_id, member_user_id)
  if member is None:
    raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
  target = await repo.get_user(db, member_user_id)
  if target is None:
    raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
  await admin_unlock(db, target)
  await emit_security_event(
    db,
    action="account.admin_unlocked",
    user_id=user.id,
    org_id=org_id,
    entity_type="user",
    entity_id=member_user_id,
    ip_address=ip,
    user_agent=ua,
  )


@router.delete(
  "/members/{member_user_id}",
  status_code=status.HTTP_204_NO_CONTENT,
  dependencies=[Depends(require_permission("organizations", "manage"))],
)
async def remove_organization_member(
  member_user_id: str, db: DB, user: CurrentUser
):
  org_id = await _current_org_id(db, user)
  member = await repo.get_organization_member(db, org_id, member_user_id)
  if member is None:
    raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
  if member.role == "owner":
    raise HTTPException(status_code=400, detail={"code": "CANNOT_REMOVE_OWNER"})
  if member_user_id == user.id:
    raise HTTPException(status_code=400, detail={"code": "CANNOT_REMOVE_SELF"})
  await repo.remove_organization_member(db, org_id, member_user_id)
