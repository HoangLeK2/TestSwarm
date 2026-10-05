from datetime import datetime
from pydantic import BaseModel


class UserCreate(BaseModel):
    email: str
    name: str
    password: str
    role: str = "operator"


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    role: str
    api_key: str
    is_active: bool
    created_at: datetime
