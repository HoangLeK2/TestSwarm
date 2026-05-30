from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from api.deps import CurrentAuth, CurrentUser, DB, require_permission
from api.schemas.auth import SessionListOut, SessionOut
from auth.session_service import list_active_sessions, revoke_all_other_sessions, revoke_session
from auth.ws_session_registry import get_ws_session_registry
from services.security_audit import emit_security_event

router = APIRouter(prefix="/me", tags=["me"])


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    return ip, ua


def _current_session_id(auth: CurrentAuth) -> str | None:
    return auth.session_id


@router.get(
    "/sessions",
    response_model=SessionListOut,
    dependencies=[Depends(require_permission("me", "read"))],
)
async def list_my_sessions(db: DB, user: CurrentUser, auth: CurrentAuth):
    rows = await list_active_sessions(
        db,
        user.id,
        current_session_id=_current_session_id(auth),
    )
    return SessionListOut(
        sessions=[
            SessionOut(
                session_id=row["session_id"],
                created_at=row["created_at"],
                last_used_at=row["last_used_at"],
                last_ip=row.get("last_ip"),
                user_agent_summary=row.get("user_agent_summary"),
                is_current=bool(row.get("is_current")),
            )
            for row in rows
        ]
    )


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("me", "read"))],
)
async def revoke_my_session(
    session_id: str,
    request: Request,
    db: DB,
    user: CurrentUser,
    auth: CurrentAuth,
):
    ip, ua = _client_meta(request)
    row = await revoke_session(db, user.id, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    await emit_security_event(
        db,
        action="session.revoked",
        user_id=user.id,
        org_id=getattr(user, "org_id", None),
        entity_type="session",
        entity_id=session_id,
        ip_address=ip,
        user_agent=ua,
        details={"actor_session_id": _current_session_id(auth)},
    )
    await get_ws_session_registry().close_session(session_id, code=4403)


@router.delete(
    "/sessions",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("me", "read"))],
)
async def revoke_other_sessions(
    request: Request,
    db: DB,
    user: CurrentUser,
    auth: CurrentAuth,
):
    ip, ua = _client_meta(request)
    current_sid = _current_session_id(auth)
    revoked = await revoke_all_other_sessions(
        db,
        user.id,
        current_session_id=current_sid,
    )
    for sid in revoked:
        await emit_security_event(
            db,
            action="session.revoked",
            user_id=user.id,
            org_id=getattr(user, "org_id", None),
            entity_type="session",
            entity_id=sid,
            ip_address=ip,
            user_agent=ua,
            details={"bulk": True, "actor_session_id": current_sid},
        )
    if revoked:
        await get_ws_session_registry().close_sessions(revoked, code=4403)
