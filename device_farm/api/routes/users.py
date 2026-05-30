"""
api/routes/users.py  (admin only)

GET  /api/users      — danh sách users
POST /api/users      — tạo user (admin)
GET  /api/users/{id} — chi tiết user
"""
from __future__ import annotations

from passlib.context import CryptContext
from fastapi import APIRouter, Depends, HTTPException, status

from api.deps import AdminUser, DB, require_permission
from api.schemas.user import UserCreate, UserOut
from db import crud as repo

router = APIRouter(prefix="/users", tags=["users"])

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


@router.get(
    "",
    response_model=list[UserOut],
    dependencies=[Depends(require_permission("users", "read"))],
)
async def list_users(db: DB, _: AdminUser):
    users = await repo.list_users(db)
    return [_to_out(u) for u in users]


@router.post(
    "",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("users", "create"))],
)
async def create_user(body: UserCreate, db: DB, _: AdminUser):
    existing = await repo.get_user_by_email(db, body.email)
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")
    user = await repo.create_user_with_default_org(
        db, body.email, body.name, _pwd.hash(body.password), body.role
    )
    return _to_out(user)


@router.get(
    "/{user_id}",
    response_model=UserOut,
    dependencies=[Depends(require_permission("users", "read"))],
)
async def get_user(user_id: str, db: DB, _: AdminUser):
    user = await repo.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return _to_out(user)


def _to_out(u) -> UserOut:
    return UserOut(
        id=u.id, email=u.email, name=u.name,
        role=u.role, api_key=u.api_key,
        is_active=u.is_active, created_at=u.created_at,
    )
