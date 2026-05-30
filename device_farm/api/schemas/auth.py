from datetime import datetime

from pydantic import BaseModel, EmailStr


class RegisterRequest(BaseModel):
    email: str
    name: str
    password: str
    role: str = "operator"
    inviteToken: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    session_id: str | None = None


class SessionOut(BaseModel):
    session_id: str
    created_at: datetime
    last_used_at: datetime
    last_ip: str | None = None
    user_agent_summary: str | None = None
    is_current: bool = False


class SessionListOut(BaseModel):
    sessions: list[SessionOut]


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    role: str
    api_key: str
    orgRole: str | None = None
