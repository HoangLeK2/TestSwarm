"""Worker-facing lifecycle endpoints for platform-neutral account discovery."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import DB, CurrentUser, require_permission
from api.schemas.account_discovery import (
    AccountDiscoveryCompleteIn,
    AccountDiscoveryFailedIn,
    AccountDiscoveryStateOut,
)
from db.models.account_discovery import AccountDiscoveryState
from services.account_discovery import (
    get_account_discovery_state,
    mark_account_discovery_completed,
    mark_account_discovery_failed,
    mark_account_discovery_started,
    request_account_discovery,
)

router = APIRouter(tags=["account-discovery"])


def _org_id(user: CurrentUser) -> str:
    org_id = str(getattr(user, "org_id", None) or "").strip()
    if not org_id:
        raise HTTPException(status_code=404, detail={"code": "NO_ORGANIZATION"})
    return org_id


def _out(
    state: AccountDiscoveryState, *, request_created: bool | None = None
) -> AccountDiscoveryStateOut:
    return AccountDiscoveryStateOut(
        id=state.id,
        org_id=state.org_id,
        account_id=state.account_id,
        platform=state.platform,
        status=state.status,
        initialized_at=state.initialized_at,
        discovery_requested_at=state.discovery_requested_at,
        discovery_started_at=state.discovery_started_at,
        last_discovery_at=state.last_discovery_at,
        next_discovery_at=state.next_discovery_at,
        last_error=state.last_error,
        created_at=state.created_at,
        updated_at=state.updated_at,
        request_created=request_created,
    )


def _service_error(exc: ValueError | LookupError) -> HTTPException:
    return HTTPException(
        status_code=404 if isinstance(exc, LookupError) else 400,
        detail={"code": "ACCOUNT_DISCOVERY_ERROR", "message": str(exc)},
    )


@router.get(
    "/accounts/{account_id}/discovery",
    response_model=AccountDiscoveryStateOut,
    dependencies=[Depends(require_permission("accounts", "read"))],
)
async def get_account_discovery_route(
    account_id: str,
    db: DB,
    user: CurrentUser,
    platform: str = Query(min_length=1, max_length=32),
) -> AccountDiscoveryStateOut:
    try:
        state = await get_account_discovery_state(
            db, org_id=_org_id(user), account_id=account_id, platform=platform
        )
    except (ValueError, LookupError) as exc:
        raise _service_error(exc) from exc
    if state is None:
        raise HTTPException(
            status_code=404, detail={"code": "ACCOUNT_DISCOVERY_NOT_INITIALIZED"}
        )
    return _out(state)


@router.post(
    "/accounts/{account_id}/discovery/request",
    response_model=AccountDiscoveryStateOut,
    dependencies=[Depends(require_permission("accounts", "update"))],
)
async def request_account_discovery_route(
    account_id: str,
    db: DB,
    user: CurrentUser,
    platform: str = Query(min_length=1, max_length=32),
) -> AccountDiscoveryStateOut:
    try:
        state, created = await request_account_discovery(
            db, org_id=_org_id(user), account_id=account_id, platform=platform
        )
    except (ValueError, LookupError) as exc:
        raise _service_error(exc) from exc
    return _out(state, request_created=created)


@router.post(
    "/accounts/{account_id}/discovery/start",
    response_model=AccountDiscoveryStateOut,
    dependencies=[Depends(require_permission("accounts", "update"))],
)
async def start_account_discovery_route(
    account_id: str,
    db: DB,
    user: CurrentUser,
    platform: str = Query(min_length=1, max_length=32),
) -> AccountDiscoveryStateOut:
    try:
        state = await mark_account_discovery_started(
            db, org_id=_org_id(user), account_id=account_id, platform=platform
        )
    except (ValueError, LookupError) as exc:
        raise _service_error(exc) from exc
    return _out(state)


@router.post(
    "/accounts/{account_id}/discovery/complete",
    response_model=AccountDiscoveryStateOut,
    dependencies=[Depends(require_permission("accounts", "update"))],
)
async def complete_account_discovery_route(
    account_id: str,
    body: AccountDiscoveryCompleteIn,
    db: DB,
    user: CurrentUser,
    platform: str = Query(min_length=1, max_length=32),
) -> AccountDiscoveryStateOut:
    try:
        state = await mark_account_discovery_completed(
            db,
            org_id=_org_id(user),
            account_id=account_id,
            platform=platform,
            candidate_count=body.candidate_count,
        )
    except (ValueError, LookupError) as exc:
        raise _service_error(exc) from exc
    return _out(state)


@router.post(
    "/accounts/{account_id}/discovery/fail",
    response_model=AccountDiscoveryStateOut,
    dependencies=[Depends(require_permission("accounts", "update"))],
)
async def fail_account_discovery_route(
    account_id: str,
    body: AccountDiscoveryFailedIn,
    db: DB,
    user: CurrentUser,
    platform: str = Query(min_length=1, max_length=32),
) -> AccountDiscoveryStateOut:
    try:
        state = await mark_account_discovery_failed(
            db,
            org_id=_org_id(user),
            account_id=account_id,
            platform=platform,
            error=body.error,
        )
    except (ValueError, LookupError) as exc:
        raise _service_error(exc) from exc
    return _out(state)
