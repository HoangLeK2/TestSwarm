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
  created_at: datetime

