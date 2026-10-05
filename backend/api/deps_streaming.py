"""Short-lived DB dependencies for long-running streaming routes.

Streaming handlers must not use the yielding ``DB`` dependency: FastAPI keeps
that session checked out until the ``StreamingResponse`` generator finishes.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.rbac import build_enforcer_for_user_from_db, permission_domain
from api.deps import _current_user_from_request, _release_request_read_transaction
from db.database import AsyncSessionLocal
from db.models import User


async def resolve_user_for_streaming(request: Request) -> User:
    """Load and scope the current user, then release the DB connection immediately."""
    async with AsyncSessionLocal() as db:
        try:
            user = await _current_user_from_request(request, db)
            await _release_request_read_transaction(db)
            await db.commit()
            return user
        except Exception:
            await db.rollback()
            raise


StreamingUser = Annotated[User, Depends(resolve_user_for_streaming)]


def require_streaming_permission(obj: str, act: str):
    """Permission check that does not hold a request-scoped DB session open."""

    async def _require(
        request: Request,
        user: StreamingUser,
    ) -> None:
        async with AsyncSessionLocal() as db:
            try:
                domain = permission_domain(user)
                enforcer = await build_enforcer_for_user_from_db(user, db, domain=domain)
                if not enforcer.enforce(str(user.id), domain, obj, act):
                    try:
                        from services.security_audit import emit_security_event

                        await emit_security_event(
                            db,
                            action="admin.access.denied",
                            user_id=user.id,
                            org_id=getattr(user, "org_id", None),
                            entity_type="route",
                            entity_id=f"{obj}:{act}",
                            ip_address=request.client.host if request.client else None,
                            user_agent=request.headers.get("user-agent"),
                            details={"path": request.url.path},
                        )
                    except Exception:
                        pass
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail={"code": "FORBIDDEN_ROLE", "required": f"{obj}:{act}"},
                    )
                await _release_request_read_transaction(db)
                await db.commit()
            except HTTPException:
                await db.rollback()
                raise
            except Exception:
                await db.rollback()
                raise

    return _require


async def verify_execution_access(db: AsyncSession, execution_id: str, user: User) -> None:
    from api.execution_access import get_execution_for_user

    await get_execution_for_user(db, execution_id, user)


async def load_execution_access(user: User, execution_id: str) -> None:
    """Short-lived execution visibility check for streaming routes."""
    async with AsyncSessionLocal() as db:
        try:
            await verify_execution_access(db, execution_id, user)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
