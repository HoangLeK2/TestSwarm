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


class RefreshRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    role: str
    api_key: str
    orgRole: str | None = None
