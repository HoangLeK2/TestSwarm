from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class OrganizationCreate(BaseModel):
  businessName: str
  businessEmail: Optional[str] = None
  businessLogo: Optional[str] = None


class OrganizationOut(BaseModel):
  id: str
  businessName: str
  businessEmail: Optional[str]
  businessLogo: Optional[str]
  slug: Optional[str] = None
  status: Optional[str] = None
  plan: Optional[str] = None
  created_at: datetime


class OrganizationListOut(BaseModel):
  items: list[OrganizationOut]
  total: int
  offset: int
  limit: int


class OrganizationMemberOut(BaseModel):
  id: str
  userId: str
  email: str
  name: str
  role: str
  created_at: datetime


class OrganizationMemberInvite(BaseModel):
  email: str
  role: str = "member"


class OrganizationMemberUpdate(BaseModel):
  role: str


class OrganizationMemberInviteOut(BaseModel):
  email: str
  status: str
  existingUser: bool
  emailSent: bool


class OrganizationInvitationPreview(BaseModel):
  organizationName: str
  email: str
  status: str
  expired: bool
  existingUser: bool


class OrganizationInvitationAccept(BaseModel):
  token: str


class OrganizationInvitationAcceptOut(BaseModel):
  organizationId: str
  organizationName: str

