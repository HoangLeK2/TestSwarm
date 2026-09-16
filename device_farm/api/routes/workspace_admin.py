from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import case, func, or_, select

from api.auth.rbac import is_superadmin
from api.deps import AdminUser, DB, require_permission
from api.schemas.analytics import ActivityLogListOut, ActivityLogOut
from api.schemas.organization import (
    OrganizationMemberInvite,
    OrganizationMemberInviteOut,
    OrganizationMemberOut,
    OrganizationMemberUpdate,
)
from api.schemas.workspace_admin import (
    AdminAgentTokenCreate,
    AdminAgentTokenCreated,
    AdminAgentTokenOut,
    AdminAgentPhoneAssign,
    AdminAgentPhoneAssignOut,
    AdminAgentPhoneListOut,
    AdminAgentPhoneOut,
    AdminAgentPhoneUnassign,
    AdminAgentListOut,
    AdminAgentOut,
    AdminAgentUpdate,
    AdminAccountListOut,
    AdminAccountOut,
    AdminAssignableWorkspaceListOut,
    AdminAssignableWorkspaceOut,
    AdminContentItemOut,
    AdminContentListOut,
    AdminDashboardSummaryOut,
    AdminDeviceListOut,
    AdminDeviceOut,
    AdminDeviceTransfer,
    AdminOwnerOut,
    AdminOwnerPasswordReset,
    AdminOwnerPasswordResetOut,
    AdminOwnerUpdate,
    AdminUserCreate,
    AdminUserCreated,
    AdminUserListOut,
    AdminUserOut,
    AdminUserPasswordResetOut,
    AdminUserWorkspaceBulkOut,
    AdminUserWorkspaceBulkResult,
    AdminUserWorkspaceBulkUpdate,
    AdminUserWorkspaceOut,
    AdminUserUpdate,
    AdminWorkspaceCreate,
    AdminWorkspaceCreated,
    AdminWorkspaceAccessAdminOut,
    AdminWorkspaceAccessMemberOut,
    AdminWorkspaceAccessOut,
    AdminWorkspaceAdminAssign,
    AdminWorkspaceAdminOut,
    AdminWorkspaceDependenciesOut,
    AdminWorkspaceListOut,
    AdminWorkspaceOut,
    AdminWorkspaceTransferOwner,
    AdminWorkspaceUpdate,
)
from auth.password_policy import record_password_history, validate_password_strength
from auth.password_service import hash_password
from db import crud as repo
from db.models import Account, ActivityLog, ContentItem, Device, DeviceFsmSnapshot, Organization, OrganizationMember, RelayAgent, RelayAgentToken, User
from db.models.utils import _now, _uuid
from services.device_allocation import mark_allocated_unclaimed, move_device_to_workspace
from services.organization_invite import create_and_email_invitation
from services.security_audit import emit_security_event
from tenancy.context import tenant_context

router = APIRouter(prefix="/admin", tags=["admin"])

log = logging.getLogger(__name__)

WORKSPACE_STATUSES = {"active", "suspended", "disabled", "archived"}
WORKSPACE_KINDS = {"pool", "tenant"}
POOL_WORKSPACE_KIND = "pool"
AGENT_STATUSES = {"online", "offline", "disabled", "archived"}
ADMIN_POOL_ROLE = "support"
PHONE_ASSIGN_BATCH_LIMIT = 200
PHONE_LIST_DEFAULT_LIMIT = 100
PHONE_LIST_MAX_LIMIT = 200
UNASSIGNED_PHONE_FILTER = "unassigned"
MANAGEABLE_WORKSPACE_MEMBER_ROLES = {"member", "supervisor"}


def _generate_temporary_password() -> str:
    # Keep generated passwords policy-compliant while remaining unguessable.
    return f"DF-{secrets.token_urlsafe(18)}-9aA!"


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    return ip, request.headers.get("user-agent")


def _is_personal_workspace_for_user(org: Organization | None, user: User) -> bool:
    if org is None:
        return False
    expected_name = repo.make_personal_org_name(user.name, user.email)
    return (
        (org.business_email or "").strip().lower() == user.email.strip().lower()
        and (org.business_name or "").strip() == expected_name
    )


async def _ensure_workspace_admin_default_org(
    db: DB,
    target: User,
    workspace_id: str,
) -> None:
    if target.default_org_id == workspace_id:
        return
    if not target.default_org_id:
        target.default_org_id = workspace_id
        return
    default_org = (
        await db.execute(
            select(Organization).where(Organization.id == target.default_org_id).limit(1)
        )
    ).scalar_one_or_none()
    if _is_personal_workspace_for_user(default_org, target):
        target.default_org_id = workspace_id


def _require_superadmin(user: Any) -> None:
    if not is_superadmin(user):
        raise HTTPException(status_code=403, detail={"code": "SUPERADMIN_ONLY"})


async def _require_visible_workspace_scope(db: DB, user: AdminUser, workspace_id: str) -> None:
    if is_superadmin(user):
        return
    visible_ids = await _workspace_admin_scope_ids(db, user)
    if workspace_id not in visible_ids:
        raise HTTPException(status_code=403, detail={"code": "WORKSPACE_SCOPE_REQUIRED"})


def _search_filter(columns: list[Any], search: str | None):
    if not search:
        return None
    escaped = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    if not escaped:
        return None
    pattern = f"%{escaped}%"
    return or_(*[column.ilike(pattern, escape="\\") for column in columns])


async def _workspace_admin_scope_ids(db: DB, user: AdminUser) -> list[str]:
    rows = (
        await db.execute(
            select(OrganizationMember.organization_id)
            .where(OrganizationMember.user_id == getattr(user, "id", None))
            .where(OrganizationMember.role == "admin")
            .order_by(OrganizationMember.organization_id.asc())
        )
    ).scalars().all()
    ids = [str(row) for row in rows if row]
    fallback = str(getattr(user, "org_id", "") or "")
    if fallback and getattr(user, "org_role", None) == "admin":
        ids.append(fallback)
    return list(dict.fromkeys(ids))


async def _visible_workspace_ids(db: DB, user: AdminUser, workspace_id: str | None = None) -> list[str]:
    if workspace_id:
        if is_superadmin(user):
            return [workspace_id]
        visible_ids = await _workspace_admin_scope_ids(db, user)
        if workspace_id not in visible_ids:
            raise HTTPException(status_code=403, detail={"code": "WORKSPACE_SCOPE_REQUIRED"})
        return [workspace_id]
    if is_superadmin(user):
        rows = (await db.execute(select(Organization.id))).scalars().all()
        return [str(row) for row in rows]
    visible_ids = await _workspace_admin_scope_ids(db, user)
    if not visible_ids:
        raise HTTPException(status_code=400, detail={"code": "WORKSPACE_SCOPE_REQUIRED"})
    return visible_ids


def _owner_out(user: User | None, role: str = "owner") -> AdminOwnerOut | None:
    if user is None:
        return None
    return AdminOwnerOut(
        user_id=user.id,
        email=user.email,
        name=user.name,
        role=role,
        is_active=bool(user.is_active),
        mustChangePassword=bool(getattr(user, "must_change_password", False)),
        created_at=user.created_at,
    )


def _workspace_admin_out(member: OrganizationMember, user: User) -> AdminWorkspaceAdminOut:
    return AdminWorkspaceAdminOut(
        user_id=user.id,
        email=user.email,
        name=user.name,
        role=member.role,
        is_active=bool(user.is_active),
        created_at=user.created_at,
        joined_at=member.joined_at or member.created_at,
    )


def _workspace_member_out(member: OrganizationMember, user: User) -> OrganizationMemberOut:
    return OrganizationMemberOut(
        id=member.id,
        userId=user.id,
        email=user.email,
        name=user.name,
        role=member.role,
        created_at=member.created_at,
    )


def _admin_user_out(
    user: User,
    workspace_count: int = 0,
    admin_workspaces: list[AdminUserWorkspaceOut] | None = None,
) -> AdminUserOut:
    return AdminUserOut(
        user_id=user.id,
        email=user.email,
        name=user.name,
        platformRole=user.role,
        is_active=bool(user.is_active),
        adminWorkspaceCount=workspace_count,
        adminWorkspaces=admin_workspaces or [],
        created_at=user.created_at,
    )


async def _admin_workspace_count(db: DB, user_id: str) -> int:
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(OrganizationMember)
                .where(OrganizationMember.user_id == user_id)
                .where(OrganizationMember.role == "admin")
            )
        ).scalar_one()
        or 0
    )


async def _admin_workspace_ids_for_user(db: DB, user_id: str) -> list[str]:
    rows = (
        await db.execute(
            select(OrganizationMember.organization_id)
            .where(OrganizationMember.user_id == user_id)
            .where(OrganizationMember.role == "admin")
            .order_by(OrganizationMember.organization_id.asc())
        )
    ).scalars().all()
    return [str(row) for row in rows if row]


async def _require_admin_user_scope(db: DB, user: AdminUser, target: User) -> None:
    if is_superadmin(user):
        return
    visible_ids = set(await _visible_workspace_ids(db, user))
    target_ids = set(await _admin_workspace_ids_for_user(db, target.id))
    if not visible_ids.intersection(target_ids):
        raise HTTPException(status_code=403, detail={"code": "WORKSPACE_SCOPE_REQUIRED"})


async def _admin_workspaces_for_users(
    db: DB,
    user_ids: list[str],
    workspace_ids: list[str] | None = None,
) -> dict[str, list[AdminUserWorkspaceOut]]:
    if not user_ids:
        return {}
    stmt = (
        select(
            OrganizationMember.user_id,
            Organization.id,
            Organization.business_name,
            Organization.status,
            OrganizationMember.joined_at,
            OrganizationMember.created_at,
        )
        .join(Organization, Organization.id == OrganizationMember.organization_id)
        .where(OrganizationMember.user_id.in_(user_ids))
        .where(OrganizationMember.role == "admin")
    )
    if workspace_ids is not None:
        stmt = stmt.where(OrganizationMember.organization_id.in_(workspace_ids))
    rows = (await db.execute(stmt.order_by(Organization.business_name.asc()))).all()
    out: dict[str, list[AdminUserWorkspaceOut]] = {}
    for row in rows:
        out.setdefault(str(row.user_id), []).append(
            AdminUserWorkspaceOut(
                id=str(row.id),
                businessName=row.business_name,
                status=row.status,
                joined_at=row.joined_at or row.created_at,
            )
        )
    return out


def _agent_health(row: RelayAgent, now: datetime | None = None) -> str:
    return _agent_health_values(row.status, row.last_heartbeat_at, now)


def _agent_health_values(
    status: str | None,
    last_heartbeat_at: datetime | None,
    now: datetime | None = None,
) -> str:
    status_value = str(status or "").lower()
    if status_value == "disabled":
        return "disabled"
    last = last_heartbeat_at
    if last is None:
        return "offline"
    current = now or datetime.now(timezone.utc)
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    age = current - last
    if status_value == "online" and age <= timedelta(minutes=2):
        return "online"
    if age <= timedelta(minutes=10):
        return "stale"
    return "offline"


async def _workspace_or_404(db: DB, workspace_id: str, user: AdminUser) -> Organization:
    await _require_visible_workspace_scope(db, user, workspace_id)
    row = (
        await db.execute(select(Organization).where(Organization.id == workspace_id).limit(1))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "WORKSPACE_NOT_FOUND"})
    return row


async def _workspace_by_id_or_404(db: DB, workspace_id: str) -> Organization:
    row = (
        await db.execute(select(Organization).where(Organization.id == workspace_id).limit(1))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "WORKSPACE_NOT_FOUND"})
    return row


async def _agent_or_404(db: DB, relay_id: str, user: AdminUser) -> RelayAgent:
    """Look the agent up across workspaces, then decide if the caller may see it.

    RelayAgent is tenant-scoped, so an ORM select only ever returns rows from the
    caller's *current* org. The agent list reads the raw table and therefore
    shows every workspace — which meant the console listed agents whose disable
    button answered 404. Scope is an authorisation decision, made here in the
    open, not a side effect of whichever org the session happens to sit in.
    """
    agent_table = RelayAgent.__table__
    row = (
        await db.execute(
            select(agent_table.c.relay_id, agent_table.c.org_id)
            .where(agent_table.c.relay_id == relay_id)
            .limit(1)
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "AGENT_NOT_FOUND"})
    org_id = str(row["org_id"] or "")
    if not is_superadmin(user):
        visible_ids = await _workspace_admin_scope_ids(db, user)
        if org_id not in visible_ids:
            raise HTTPException(status_code=404, detail={"code": "AGENT_NOT_FOUND"})
    with tenant_context(org_id):
        agent = (
            await db.execute(
                select(RelayAgent).where(RelayAgent.relay_id == relay_id).limit(1)
            )
        ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail={"code": "AGENT_NOT_FOUND"})
    return agent


async def _device_or_404(db: DB, device_id: str, user: AdminUser) -> Device:
    device_table = Device.__table__
    stmt = select(device_table.c.id, device_table.c.org_id).where(device_table.c.id == device_id)
    if not is_superadmin(user):
        visible_ids = await _visible_workspace_ids(db, user)
        stmt = stmt.where(device_table.c.org_id.in_(visible_ids))
    row = (await db.execute(stmt.limit(1))).mappings().first()
    if row is not None:
        with tenant_context(str(row["org_id"])):
            device = await repo.get_device(db, device_id)
        if device is not None:
            return device
    raise HTTPException(status_code=404, detail={"code": "DEVICE_NOT_FOUND"})


async def _managed_device_or_404(db: DB, device_id: str, user: AdminUser) -> Device:
    device_table = Device.__table__
    stmt = select(
        device_table.c.id,
        device_table.c.org_id,
        device_table.c.managed_by_org_id,
    ).where(device_table.c.id == device_id)
    if not is_superadmin(user):
        visible_ids = await _visible_workspace_ids(db, user)
        stmt = stmt.where(
            or_(
                device_table.c.org_id.in_(visible_ids),
                device_table.c.managed_by_org_id.in_(visible_ids),
            )
        )
    row = (await db.execute(stmt.limit(1))).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "DEVICE_NOT_FOUND"})
    with tenant_context(str(row["org_id"])):
        device = await repo.get_device(db, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail={"code": "DEVICE_NOT_FOUND"})
    return device


async def _workspace_counts(db: DB, workspace_ids: list[str]) -> dict[str, dict[str, int]]:
    if not workspace_ids:
        return {}
    counts = {wid: {"agents": 0, "devices": 0, "members": 0} for wid in workspace_ids}
    agent_table = RelayAgent.__table__
    device_table = Device.__table__
    agent_rows = (
        await db.execute(
            select(agent_table.c.org_id, func.count())
            .where(
                agent_table.c.org_id.in_(workspace_ids),
                # Archived rows are superseded duplicates — the agent list hides
                # them, so counting them here shows a total nobody can click to.
                agent_table.c.status != "archived",
            )
            .group_by(agent_table.c.org_id)
        )
    ).all()
    for org_id, count in agent_rows:
        counts[str(org_id)]["agents"] = int(count or 0)
    device_rows = (
        await db.execute(
            select(device_table.c.org_id, func.count())
            .where(device_table.c.org_id.in_(workspace_ids))
            .group_by(device_table.c.org_id)
        )
    ).all()
    for org_id, count in device_rows:
        counts[str(org_id)]["devices"] = int(count or 0)
    member_rows = (
        await db.execute(
            select(OrganizationMember.organization_id, func.count())
            .where(OrganizationMember.organization_id.in_(workspace_ids))
            .group_by(OrganizationMember.organization_id)
        )
    ).all()
    for org_id, count in member_rows:
        counts[str(org_id)]["members"] = int(count or 0)
    return counts


async def _workspace_name_map(
    db: DB,
    workspace_ids: set[str] | list[str] | None = None,
) -> dict[str, str]:
    stmt = select(Organization.id, Organization.business_name)
    if workspace_ids:
        stmt = stmt.where(Organization.id.in_(list(workspace_ids)))
    rows = (await db.execute(stmt)).all()
    return {str(org_id): str(name) for org_id, name in rows}


async def _workspace_owners(db: DB, workspace_ids: list[str]) -> dict[str, AdminOwnerOut]:
    if not workspace_ids:
        return {}
    rows = (
        await db.execute(
            select(OrganizationMember.organization_id, OrganizationMember.role, User)
            .join(User, User.id == OrganizationMember.user_id)
            .where(OrganizationMember.organization_id.in_(workspace_ids))
            .where(OrganizationMember.role == "owner")
            .order_by(OrganizationMember.created_at.asc())
        )
    ).all()
    owners: dict[str, AdminOwnerOut] = {}
    for org_id, role, user in rows:
        if str(org_id) not in owners:
            owner = _owner_out(user, role)
            if owner is not None:
                owners[str(org_id)] = owner
    return owners


async def _workspace_admins(
    db: DB, workspace_ids: list[str]
) -> dict[str, list[AdminWorkspaceAdminOut]]:
    if not workspace_ids:
        return {}
    rows = (
        await db.execute(
            select(OrganizationMember.organization_id, OrganizationMember, User)
            .join(User, User.id == OrganizationMember.user_id)
            .where(OrganizationMember.organization_id.in_(workspace_ids))
            .where(OrganizationMember.role == "admin")
            .order_by(OrganizationMember.created_at.asc())
        )
    ).all()
    out: dict[str, list[AdminWorkspaceAdminOut]] = {wid: [] for wid in workspace_ids}
    for org_id, member, user in rows:
        out.setdefault(str(org_id), []).append(_workspace_admin_out(member, user))
    return out


def _workspace_out(
    org: Organization,
    *,
    owner: AdminOwnerOut | None = None,
    workspace_admins: list[AdminWorkspaceAdminOut] | None = None,
    counts: dict[str, int] | None = None,
) -> AdminWorkspaceOut:
    c = counts or {}
    admins = workspace_admins or []
    return AdminWorkspaceOut(
        id=org.id,
        businessName=org.business_name,
        description=getattr(org, "description", "") or "",
        businessEmail=org.business_email,
        businessLogo=org.business_logo,
        slug=getattr(org, "slug", None),
        status=getattr(org, "status", "active") or "active",
        plan=getattr(org, "plan", "standard") or "standard",
        kind=getattr(org, "kind", "tenant") or "tenant",
        owner=owner,
        workspaceAdmins=admins,
        agentCount=int(c.get("agents", 0)),
        deviceCount=int(c.get("devices", 0)),
        memberCount=int(c.get("members", 0)),
        adminCount=len(admins),
        created_at=org.created_at,
        updated_at=getattr(org, "updated_at", None),
    )


def _admin_account_out_from_mapping(row: Any) -> AdminAccountOut:
    state = row["state"] or row["status"]
    return AdminAccountOut(
        id=row["id"],
        platform=row["platform"],
        username=row["username"],
        display_name=row["display_name"] or "",
        status=row["status"],
        state=state,
        state_reason=row["state_reason"],
        state_changed_at=row["state_changed_at"],
        cooldown_until=row["cooldown_until"],
        proxy_id=row["proxy_id"],
        notes=row["notes"] or "",
        tags=row["tags"] or "",
        user_id=row["user_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_used_at=row["last_used_at"],
        total_usage_minutes=float(row["total_usage_minutes"] or 0.0),
        usage_today_minutes=float(row["usage_today_minutes"] or 0.0),
        usage_reset_date=row["usage_reset_date"],
        workspaceId=str(row["org_id"]),
        workspaceName=row["workspace_name"],
    )


def _admin_content_out_from_mapping(row: Any) -> AdminContentItemOut:
    media_urls = row["media_urls"] if isinstance(row["media_urls"], list) else []
    return AdminContentItemOut(
        id=row["id"],
        collection=row["collection"],
        platform=row["platform"],
        content_type=row["content_type"],
        title=row["title"],
        body=row["body"],
        author=row["author"],
        author_id=row["author_id"],
        url=row["url"],
        likes_count=row["likes_count"],
        comments_count=row["comments_count"],
        shares_count=row["shares_count"],
        views_count=row["views_count"],
        media_urls=media_urls,
        screenshot_path=row["screenshot_path"],
        tags=row["tags"] or "",
        raw_data=None,
        device_serial=row["device_serial"],
        campaign_id=row["campaign_id"],
        execution_id=row["execution_id"],
        scenario_name=row["scenario_name"],
        extracted_at=row["extracted_at"],
        content_date=row["content_date"],
        created_at=row["created_at"],
        content_hash=row["content_hash"],
        parent_id=row["parent_id"],
        item_level=int(row["item_level"] or 0),
        workspaceId=str(row["org_id"]),
        workspaceName=row["workspace_name"],
    )


def _workspace_metrics_from_rows(rows: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "workspaceId": str(row["org_id"]),
            "workspaceName": row["workspace_name"],
            "count": int(row["count"] or 0),
        }
        for row in rows
    ]


async def _workspace_page(
    db: DB,
    user: AdminUser,
    *,
    search: str | None,
    status_filter: str | None,
    workspace_id: str | None,
    offset: int,
    limit: int,
) -> tuple[list[Organization], int]:
    safe_limit = min(max(limit, 1), 100)
    safe_offset = max(offset, 0)
    stmt = select(Organization)
    if workspace_id or not is_superadmin(user):
        visible_ids = await _visible_workspace_ids(db, user, workspace_id)
        stmt = stmt.where(Organization.id.in_(visible_ids))
    search_clause = _search_filter(
        [Organization.business_name, Organization.business_email, Organization.description],
        search,
    )
    if search_clause is not None:
        stmt = stmt.where(search_clause)
    if status_filter:
        stmt = stmt.where(Organization.status == status_filter)
    total = int((await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one() or 0)
    rows = (
        await db.execute(
            stmt.order_by(Organization.created_at.desc()).offset(safe_offset).limit(safe_limit)
        )
    ).scalars().all()
    return list(rows), total


@router.get(
    "/workspace-admins",
    response_model=AdminUserListOut,
    dependencies=[Depends(require_permission("organizations", "manage"))],
)
async def admin_list_admin_users(
    db: DB,
    user: AdminUser,
    search: str | None = None,
    status_: str | None = Query(None, alias="status"),
    workspace_id: str | None = Query(None, alias="workspaceId"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    safe_limit = min(max(limit, 1), 100)
    safe_offset = max(offset, 0)
    visible_workspace_ids: list[str] | None = (
        await _visible_workspace_ids(db, user, workspace_id)
        if workspace_id or not is_superadmin(user)
        else None
    )
    if visible_workspace_ids is None:
        admin_count = func.coalesce(
            func.sum(case((OrganizationMember.role == "admin", 1), else_=0)), 0
        ).label("admin_workspace_count")
        stmt = (
            select(User, admin_count)
            .outerjoin(OrganizationMember, OrganizationMember.user_id == User.id)
            .where(or_(User.role == ADMIN_POOL_ROLE, OrganizationMember.role == "admin"))
            .group_by(User.id)
        )
    else:
        admin_count = func.count(OrganizationMember.organization_id).label(
            "admin_workspace_count"
        )
        stmt = (
            select(User, admin_count)
            .join(OrganizationMember, OrganizationMember.user_id == User.id)
            .where(OrganizationMember.role == "admin")
            .where(OrganizationMember.organization_id.in_(visible_workspace_ids))
            .group_by(User.id)
        )
    search_clause = _search_filter([User.email, User.name, User.id], search)
    if search_clause is not None:
        stmt = stmt.where(search_clause)
    if status_ == "active":
        stmt = stmt.where(User.is_active.is_(True))
    elif status_ in {"disabled", "inactive"}:
        stmt = stmt.where(User.is_active.is_(False))

    total = int((await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one() or 0)
    rows = (
        await db.execute(
            stmt.order_by(User.created_at.desc()).offset(safe_offset).limit(safe_limit)
        )
    ).all()
    admin_workspaces = await _admin_workspaces_for_users(
        db,
        [str(row_user.id) for row_user, _count in rows],
        visible_workspace_ids,
    )
    return AdminUserListOut(
        items=[
            _admin_user_out(
                row_user,
                int(count or 0),
                admin_workspaces.get(str(row_user.id), []),
            )
            for row_user, count in rows
        ],
        total=total,
        offset=safe_offset,
        limit=safe_limit,
    )


@router.get(
    "/accounts",
    response_model=AdminAccountListOut,
    dependencies=[Depends(require_permission("accounts", "read"))],
)
async def admin_list_accounts(
    db: DB,
    user: AdminUser,
    search: str | None = None,
    platform: str | None = None,
    status_: str | None = Query(None, alias="status"),
    state: str | None = None,
    workspace_id: str | None = Query(None, alias="workspaceId"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    safe_limit = min(max(limit, 1), 200)
    safe_offset = max(offset, 0)
    visible_ids = await _visible_workspace_ids(db, user, workspace_id)
    account_table = Account.__table__
    org_table = Organization.__table__
    conditions = [account_table.c.org_id.in_(visible_ids)]
    if platform:
        conditions.append(account_table.c.platform == platform)
    if state:
        conditions.append(account_table.c.state == state)
    elif status_:
        conditions.append(account_table.c.state == status_)
    search_clause = _search_filter(
        [account_table.c.username, account_table.c.display_name, account_table.c.tags],
        search,
    )
    if search_clause is not None:
        conditions.append(search_clause)

    base = account_table.join(org_table, org_table.c.id == account_table.c.org_id)
    stmt = (
        select(
            account_table.c.id,
            account_table.c.org_id,
            org_table.c.business_name.label("workspace_name"),
            account_table.c.platform,
            account_table.c.username,
            account_table.c.display_name,
            account_table.c.status,
            account_table.c.state,
            account_table.c.state_reason,
            account_table.c.state_changed_at,
            account_table.c.cooldown_until,
            account_table.c.proxy_id,
            account_table.c.notes,
            account_table.c.tags,
            account_table.c.user_id,
            account_table.c.created_at,
            account_table.c.updated_at,
            account_table.c.last_used_at,
            account_table.c.total_usage_minutes,
            account_table.c.usage_today_minutes,
            account_table.c.usage_reset_date,
        )
        .select_from(base)
        .where(*conditions)
    )
    total = int((await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one() or 0)
    workspace_rows = (
        await db.execute(
            select(
                account_table.c.org_id,
                org_table.c.business_name.label("workspace_name"),
                func.count().label("count"),
            )
            .select_from(base)
            .where(*conditions)
            .group_by(account_table.c.org_id, org_table.c.business_name)
            .order_by(org_table.c.business_name.asc())
        )
    ).mappings().all()
    rows = (
        await db.execute(
            stmt.order_by(org_table.c.business_name.asc(), account_table.c.created_at.desc())
            .offset(safe_offset)
            .limit(safe_limit)
        )
    ).mappings().all()
    return AdminAccountListOut(
        items=[_admin_account_out_from_mapping(row) for row in rows],
        total=total,
        offset=safe_offset,
        limit=safe_limit,
        byWorkspace=_workspace_metrics_from_rows(list(workspace_rows)),
    )


@router.get(
    "/content",
    response_model=AdminContentListOut,
    dependencies=[Depends(require_permission("content", "read"))],
)
async def admin_list_content(
    db: DB,
    user: AdminUser,
    search: str | None = None,
    collection: str | None = None,
    platform: str | None = None,
    content_type: str | None = None,
    device_serial: str | None = None,
    campaign_id: str | None = None,
    execution_id: str | None = None,
    content_hash: str | None = None,
    parent_id: str | None = None,
    workspace_id: str | None = Query(None, alias="workspaceId"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
):
    safe_limit = min(max(limit, 1), 500)
    safe_offset = max(offset, 0)
    visible_ids = await _visible_workspace_ids(db, user, workspace_id)
    content_table = ContentItem.__table__
    org_table = Organization.__table__
    conditions = [
        content_table.c.org_id.in_(visible_ids),
        content_table.c.deleted_at.is_(None),
    ]
    if collection:
        conditions.append(content_table.c.collection == collection)
    if platform:
        conditions.append(content_table.c.platform == platform)
    if content_type:
        conditions.append(content_table.c.content_type == content_type)
    if device_serial:
        conditions.append(content_table.c.device_serial == device_serial)
    if campaign_id:
        conditions.append(content_table.c.campaign_id == campaign_id)
    if execution_id:
        conditions.append(content_table.c.execution_id == execution_id)
    if content_hash:
        conditions.append(content_table.c.content_hash == content_hash)
    if parent_id:
        conditions.append(content_table.c.parent_id == parent_id)
    search_clause = _search_filter(
        [
            content_table.c.title,
            content_table.c.body,
            content_table.c.author,
            content_table.c.author_id,
            content_table.c.url,
            content_table.c.content_hash,
            content_table.c.tags,
        ],
        search,
    )
    if search_clause is not None:
        conditions.append(search_clause)

    base = content_table.join(org_table, org_table.c.id == content_table.c.org_id)
    stmt = (
        select(
            content_table.c.id,
            content_table.c.org_id,
            org_table.c.business_name.label("workspace_name"),
            content_table.c.collection,
            content_table.c.platform,
            content_table.c.content_type,
            content_table.c.title,
            content_table.c.body,
            content_table.c.author,
            content_table.c.author_id,
            content_table.c.url,
            content_table.c.likes_count,
            content_table.c.comments_count,
            content_table.c.shares_count,
            content_table.c.views_count,
            content_table.c.media_urls,
            content_table.c.screenshot_path,
            content_table.c.tags,
            content_table.c.device_serial,
            content_table.c.campaign_id,
            content_table.c.execution_id,
            content_table.c.scenario_name,
            content_table.c.extracted_at,
            content_table.c.content_date,
            content_table.c.created_at,
            content_table.c.content_hash,
            content_table.c.parent_id,
            content_table.c.item_level,
        )
        .select_from(base)
        .where(*conditions)
    )
    total = int((await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one() or 0)
    workspace_rows = (
        await db.execute(
            select(
                content_table.c.org_id,
                org_table.c.business_name.label("workspace_name"),
                func.count().label("count"),
            )
            .select_from(base)
            .where(*conditions)
            .group_by(content_table.c.org_id, org_table.c.business_name)
            .order_by(org_table.c.business_name.asc())
        )
    ).mappings().all()
    rows = (
        await db.execute(
            stmt.order_by(content_table.c.extracted_at.desc(), content_table.c.created_at.desc())
            .offset(safe_offset)
            .limit(safe_limit)
        )
    ).mappings().all()
    return AdminContentListOut(
        items=[_admin_content_out_from_mapping(row) for row in rows],
        total=total,
        offset=safe_offset,
        limit=safe_limit,
        byWorkspace=_workspace_metrics_from_rows(list(workspace_rows)),
    )


@router.post(
    "/workspace-admins",
    response_model=AdminUserCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("organizations", "manage"))],
)
async def admin_create_admin_user(
    body: AdminUserCreate,
    request: Request,
    db: DB,
    user: AdminUser,
):
    _require_superadmin(user)
    email = body.email.strip().lower()
    name = body.name.strip()
    if not email:
        raise HTTPException(status_code=400, detail={"code": "INVALID_EMAIL"})
    if not name:
        raise HTTPException(status_code=400, detail={"code": "INVALID_NAME"})
    existing = await repo.get_user_by_email(db, email)
    if existing is not None:
        raise HTTPException(status_code=409, detail={"code": "EMAIL_ALREADY_REGISTERED"})
    workspace_ids = _normalized_workspace_ids(body.workspaceIds) if body.workspaceIds else []
    temporary_password = body.password or _generate_temporary_password()
    violations = validate_password_strength(temporary_password)
    if violations:
        raise HTTPException(
            status_code=400,
            detail={"code": "WEAK_PASSWORD", "violations": violations},
        )
    row = await repo.create_user_with_default_org(
        db,
        email=email,
        name=name,
        hashed_password=hash_password(temporary_password),
        role=ADMIN_POOL_ROLE,
    )
    row.is_active = True
    row.must_change_password = True
    await db.flush()
    await record_password_history(db, row.id, row.hashed_password)
    ip, ua = _client_meta(request)
    await emit_security_event(
        db,
        action="workspace_admin.created",
        user_id=user.id,
        org_id=None,
        entity_type="user",
        entity_id=row.id,
        ip_address=ip,
        user_agent=ua,
        details={"email": row.email},
    )
    assigned_admins: list[AdminWorkspaceAdminOut] = []
    for workspace_id in workspace_ids:
        await _workspace_or_404(db, workspace_id, user)
        member, _target = await _assign_workspace_admin(
            db,
            workspace_id=workspace_id,
            admin_user_id=row.id,
        )
        assigned_admins.append(_workspace_admin_out(member, row))
        await emit_security_event(
            db,
            action="workspace_admin.assigned",
            user_id=user.id,
            org_id=workspace_id,
            entity_type="user",
            entity_id=row.id,
            ip_address=ip,
            user_agent=ua,
            details={"workspace_id": workspace_id, "admin_user_id": row.id},
        )
    await db.commit()
    admin_workspaces = await _admin_workspaces_for_users(db, [str(row.id)])
    return AdminUserCreated(
        **_admin_user_out(
            row,
            len(admin_workspaces.get(str(row.id), [])),
            admin_workspaces.get(str(row.id), []),
        ).model_dump(),
        temporaryPassword=temporary_password,
    )


@router.patch(
    "/workspace-admins/{admin_user_id}",
    response_model=AdminUserOut,
    dependencies=[Depends(require_permission("organizations", "manage"))],
)
async def admin_update_admin_user(
    admin_user_id: str,
    body: AdminUserUpdate,
    request: Request,
    db: DB,
    user: AdminUser,
):
    _require_superadmin(user)
    row = await repo.get_user(db, admin_user_id)
    if row is None or row.role not in {ADMIN_POOL_ROLE, "admin"}:
        raise HTTPException(status_code=404, detail={"code": "ADMIN_USER_NOT_FOUND"})
    await _require_admin_user_scope(db, user, row)
    before = {"name": row.name, "is_active": row.is_active}
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail={"code": "INVALID_NAME"})
        row.name = name
    if body.is_active is not None:
        row.is_active = body.is_active
    ip, ua = _client_meta(request)
    await emit_security_event(
        db,
        action=(
            "workspace_admin.enabled"
            if body.is_active is True
            else "workspace_admin.disabled"
            if body.is_active is False
            else "workspace_admin.updated"
        ),
        user_id=user.id,
        org_id=None,
        entity_type="user",
        entity_id=row.id,
        ip_address=ip,
        user_agent=ua,
        details={"before": before, "after": body.model_dump(exclude_none=True)},
    )
    await db.commit()
    visible_workspace_ids = None if is_superadmin(user) else await _visible_workspace_ids(db, user)
    admin_workspaces = await _admin_workspaces_for_users(
        db,
        [str(row.id)],
        visible_workspace_ids,
    )
    return _admin_user_out(
        row,
        len(admin_workspaces.get(str(row.id), [])),
        admin_workspaces.get(str(row.id), []),
    )


@router.post(
    "/workspace-admins/{admin_user_id}/reset-password",
    response_model=AdminUserPasswordResetOut,
    dependencies=[Depends(require_permission("organizations", "manage"))],
)
async def admin_reset_workspace_admin_password(
    admin_user_id: str,
    body: AdminOwnerPasswordReset,
    request: Request,
    db: DB,
    user: AdminUser,
):
    _require_superadmin(user)
    row = await repo.get_user(db, admin_user_id)
    if row is None or row.role not in {ADMIN_POOL_ROLE, "admin"}:
        raise HTTPException(status_code=404, detail={"code": "ADMIN_USER_NOT_FOUND"})
    await _require_admin_user_scope(db, user, row)
    temporary_password = body.password or _generate_temporary_password()
    violations = validate_password_strength(temporary_password)
    if violations:
        raise HTTPException(
            status_code=400,
            detail={"code": "WEAK_PASSWORD", "violations": violations},
        )
    row.hashed_password = hash_password(temporary_password)
    row.must_change_password = True
    await db.flush()
    await record_password_history(db, row.id, row.hashed_password)
    ip, ua = _client_meta(request)
    await emit_security_event(
        db,
        action="workspace_admin.password_reset",
        user_id=user.id,
        org_id=None,
        entity_type="user",
        entity_id=row.id,
        ip_address=ip,
        user_agent=ua,
        details={"email": row.email},
    )
    await db.commit()
    visible_workspace_ids = None if is_superadmin(user) else await _visible_workspace_ids(db, user)
    admin_workspaces = await _admin_workspaces_for_users(
        db,
        [str(row.id)],
        visible_workspace_ids,
    )
    return AdminUserPasswordResetOut(
        admin=_admin_user_out(
            row,
            len(admin_workspaces.get(str(row.id), [])),
            admin_workspaces.get(str(row.id), []),
        ),
        temporaryPassword=temporary_password,
    )


async def _assign_workspace_admin(
    db: DB,
    *,
    workspace_id: str,
    admin_user_id: str,
) -> tuple[OrganizationMember, User]:
    target = await repo.get_user(db, admin_user_id)
    if target is None or not target.is_active:
        raise HTTPException(status_code=404, detail={"code": "ADMIN_USER_NOT_FOUND"})
    if is_superadmin(target):
        raise HTTPException(status_code=409, detail={"code": "CANNOT_ASSIGN_SUPERADMIN"})
    if target.role not in {ADMIN_POOL_ROLE, "admin"}:
        raise HTTPException(status_code=409, detail={"code": "USER_NOT_ADMIN_POOL"})

    existing = await repo.get_organization_member(db, workspace_id, target.id)
    if existing is not None:
        if existing.role == "admin":
            raise HTTPException(status_code=409, detail={"code": "WORKSPACE_ADMIN_EXISTS"})
        if existing.role == "owner":
            raise HTTPException(status_code=409, detail={"code": "CANNOT_PROMOTE_OWNER_TO_ADMIN"})
        existing.role = "admin"
        await db.flush()
        member = existing
    else:
        member = await repo.add_organization_member(
            db,
            organization_id=workspace_id,
            user_id=target.id,
            role="admin",
        )
    await _ensure_workspace_admin_default_org(db, target, workspace_id)
    return member, target


def _normalized_workspace_ids(workspace_ids: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for workspace_id in workspace_ids:
        value = workspace_id.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    if not out:
        raise HTTPException(status_code=400, detail={"code": "WORKSPACE_IDS_REQUIRED"})
    return out


async def _admin_user_or_404(db: DB, admin_user_id: str) -> User:
    target = await repo.get_user(db, admin_user_id)
    if target is None:
        raise HTTPException(status_code=404, detail={"code": "ADMIN_USER_NOT_FOUND"})
    if is_superadmin(target):
        raise HTTPException(status_code=409, detail={"code": "CANNOT_ASSIGN_SUPERADMIN"})
    if target.role not in {ADMIN_POOL_ROLE, "admin"}:
        raise HTTPException(status_code=409, detail={"code": "USER_NOT_ADMIN_POOL"})
    return target


async def _workspace_map(db: DB, workspace_ids: list[str]) -> dict[str, Organization]:
    rows = (
        await db.execute(
            select(Organization).where(Organization.id.in_(workspace_ids))
        )
    ).scalars().all()
    return {str(row.id): row for row in rows}


def _bulk_result(
    workspace_id: str,
    org: Organization | None,
    status_value: str,
    reason: str | None = None,
) -> AdminUserWorkspaceBulkResult:
    return AdminUserWorkspaceBulkResult(
        workspaceId=workspace_id,
        workspaceName=org.business_name if org is not None else None,
        status=status_value,
        reason=reason,
    )


async def _admin_user_bulk_out(
    db: DB,
    target: User,
    *,
    assigned: list[AdminUserWorkspaceBulkResult] | None = None,
    removed: list[AdminUserWorkspaceBulkResult] | None = None,
    skipped: list[AdminUserWorkspaceBulkResult] | None = None,
) -> AdminUserWorkspaceBulkOut:
    workspaces = (await _admin_workspaces_for_users(db, [str(target.id)])).get(
        str(target.id),
        [],
    )
    return AdminUserWorkspaceBulkOut(
        admin=_admin_user_out(target, len(workspaces), workspaces),
        assigned=assigned or [],
        removed=removed or [],
        skipped=skipped or [],
    )


@router.post(
    "/workspace-admins/{admin_user_id}/workspaces",
    response_model=AdminUserWorkspaceBulkOut,
    dependencies=[Depends(require_permission("organizations", "manage"))],
)
async def admin_bulk_assign_workspace_admin(
    admin_user_id: str,
    body: AdminUserWorkspaceBulkUpdate,
    request: Request,
    db: DB,
    user: AdminUser,
):
    _require_superadmin(user)
    target = await _admin_user_or_404(db, admin_user_id)
    if not target.is_active:
        raise HTTPException(status_code=404, detail={"code": "ADMIN_USER_NOT_FOUND"})
    workspace_ids = _normalized_workspace_ids(body.workspaceIds)
    orgs = await _workspace_map(db, workspace_ids)
    ip, ua = _client_meta(request)
    assigned: list[AdminUserWorkspaceBulkResult] = []
    skipped: list[AdminUserWorkspaceBulkResult] = []

    for workspace_id in workspace_ids:
        org = orgs.get(workspace_id)
        if org is None:
            skipped.append(_bulk_result(workspace_id, None, "skipped", "WORKSPACE_NOT_FOUND"))
            continue
        if getattr(org, "status", "active") == "archived":
            skipped.append(_bulk_result(workspace_id, org, "skipped", "WORKSPACE_ARCHIVED"))
            continue
        existing = await repo.get_organization_member(db, workspace_id, target.id)
        if existing is not None:
            if existing.role == "admin":
                skipped.append(_bulk_result(workspace_id, org, "skipped", "WORKSPACE_ADMIN_EXISTS"))
                continue
            if existing.role == "owner":
                skipped.append(_bulk_result(workspace_id, org, "skipped", "CANNOT_PROMOTE_OWNER_TO_ADMIN"))
                continue
            existing.role = "admin"
            await db.flush()
        else:
            await repo.add_organization_member(
                db,
                organization_id=workspace_id,
                user_id=target.id,
                role="admin",
            )
        await _ensure_workspace_admin_default_org(db, target, workspace_id)
        assigned.append(_bulk_result(workspace_id, org, "assigned"))
        await emit_security_event(
            db,
            action="workspace_admin.assigned",
            user_id=user.id,
            org_id=workspace_id,
            entity_type="user",
            entity_id=target.id,
            ip_address=ip,
            user_agent=ua,
            details={"workspace_id": workspace_id, "admin_user_id": target.id},
        )

    await db.commit()
    return await _admin_user_bulk_out(db, target, assigned=assigned, skipped=skipped)


@router.post(
    "/workspace-admins/{admin_user_id}/workspaces/remove",
    response_model=AdminUserWorkspaceBulkOut,
    dependencies=[Depends(require_permission("organizations", "manage"))],
)
async def admin_bulk_remove_workspace_admin(
    admin_user_id: str,
    body: AdminUserWorkspaceBulkUpdate,
    request: Request,
    db: DB,
    user: AdminUser,
):
    _require_superadmin(user)
    target = await _admin_user_or_404(db, admin_user_id)
    workspace_ids = _normalized_workspace_ids(body.workspaceIds)
    orgs = await _workspace_map(db, workspace_ids)
    ip, ua = _client_meta(request)
    removed: list[AdminUserWorkspaceBulkResult] = []
    skipped: list[AdminUserWorkspaceBulkResult] = []

    for workspace_id in workspace_ids:
        org = orgs.get(workspace_id)
        if org is None:
            skipped.append(_bulk_result(workspace_id, None, "skipped", "WORKSPACE_NOT_FOUND"))
            continue
        member = await repo.get_organization_member(db, workspace_id, target.id)
        if member is None or member.role != "admin":
            skipped.append(_bulk_result(workspace_id, org, "skipped", "WORKSPACE_ADMIN_NOT_FOUND"))
            continue
        await repo.remove_organization_member(db, workspace_id, target.id)
        removed.append(_bulk_result(workspace_id, org, "removed"))
        await emit_security_event(
            db,
            action="workspace_admin.removed",
            user_id=user.id,
            org_id=workspace_id,
            entity_type="user",
            entity_id=target.id,
            ip_address=ip,
            user_agent=ua,
            details={"workspace_id": workspace_id, "admin_user_id": target.id},
        )

    if target.default_org_id in workspace_ids:
        next_org = (
            await db.execute(
                select(OrganizationMember.organization_id)
                .where(OrganizationMember.user_id == target.id)
                .order_by(OrganizationMember.created_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        target.default_org_id = next_org

    await db.commit()
    return await _admin_user_bulk_out(db, target, removed=removed, skipped=skipped)


@router.get(
    "/dashboard/summary",
    response_model=AdminDashboardSummaryOut,
    dependencies=[Depends(require_permission("organizations", "read"))],
)
async def admin_workspace_summary(
    db: DB,
    user: AdminUser,
    workspace_id: str | None = Query(None, alias="workspaceId"),
):
    workspace_stmt = select(Organization.id, Organization.business_name, Organization.status)
    if workspace_id or not is_superadmin(user):
        visible_ids = await _visible_workspace_ids(db, user, workspace_id)
        workspace_stmt = workspace_stmt.where(Organization.id.in_(visible_ids))
    workspace_rows = (await db.execute(workspace_stmt.order_by(Organization.created_at.desc()))).all()
    workspace_ids = [str(row.id) for row in workspace_rows]
    counts = await _workspace_counts(db, workspace_ids)
    agent_table = RelayAgent.__table__
    device_table = Device.__table__
    agent_health_rows = []
    total_devices = assigned_devices = 0
    if workspace_ids:
        agent_health_rows = (
            await db.execute(
                select(agent_table.c.status, agent_table.c.last_heartbeat_at).where(
                    agent_table.c.org_id.in_(workspace_ids),
                    agent_table.c.status != "archived",
                )
            )
        ).all()
        device_totals = (
            await db.execute(
                select(
                    func.count(),
                    func.coalesce(
                        func.sum(
                            case(
                                (device_table.c.user_id.is_not(None), 1),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                )
                .select_from(device_table)
                .where(device_table.c.org_id.in_(workspace_ids))
            )
        ).one()
        total_devices = int(device_totals[0] or 0)
        assigned_devices = int(device_totals[1] or 0)
    now = datetime.now(timezone.utc)
    health = [
        _agent_health_values(row.status, row.last_heartbeat_at, now)
        for row in agent_health_rows
    ]
    return AdminDashboardSummaryOut(
        totalWorkspaces=len(workspace_rows),
        activeWorkspaces=sum(
            1 for org in workspace_rows if (org.status or "active") == "active"
        ),
        suspendedWorkspaces=sum(
            1 for org in workspace_rows if (org.status or "") in {"suspended", "disabled"}
        ),
        archivedWorkspaces=sum(
            1 for org in workspace_rows if (org.status or "") == "archived"
        ),
        totalAgents=len(agent_health_rows),
        onlineAgents=sum(1 for item in health if item == "online"),
        offlineAgents=sum(1 for item in health if item == "offline"),
        staleAgents=sum(1 for item in health if item == "stale"),
        totalDevices=total_devices,
        assignedDevices=assigned_devices,
        unassignedDevices=max(0, total_devices - assigned_devices),
        devicesByWorkspace=[
            {
                "workspaceId": org.id,
                "workspaceName": org.business_name,
                "count": counts.get(str(org.id), {}).get("devices", 0),
            }
            for org in workspace_rows
        ],
        agentsByWorkspace=[
            {
                "workspaceId": org.id,
                "workspaceName": org.business_name,
                "count": counts.get(str(org.id), {}).get("agents", 0),
            }
            for org in workspace_rows
        ],
    )


@router.get(
    "/workspaces",
    response_model=AdminWorkspaceListOut,
    dependencies=[Depends(require_permission("organizations", "read"))],
)
async def admin_list_workspaces(
    db: DB,
    user: AdminUser,
    search: str | None = None,
    status_: str | None = Query(None, alias="status"),
    workspace_id: str | None = Query(None, alias="workspaceId"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    rows, total = await _workspace_page(
        db,
        user,
        search=search,
        status_filter=status_,
        workspace_id=workspace_id,
        offset=offset,
        limit=limit,
    )
    ids = [row.id for row in rows]
    owners = await _workspace_owners(db, ids)
    admins = await _workspace_admins(db, ids)
    counts = await _workspace_counts(db, ids)
    return AdminWorkspaceListOut(
        items=[
            _workspace_out(
                row,
                owner=owners.get(row.id),
                workspace_admins=admins.get(row.id),
                counts=counts.get(row.id),
            )
            for row in rows
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/workspaces/assignable",
    response_model=AdminAssignableWorkspaceListOut,
    dependencies=[Depends(require_permission("organizations", "read"))],
)
async def admin_list_assignable_workspaces(
    db: DB,
    user: AdminUser,
    search: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
):
    safe_limit = min(max(limit, 1), 200)
    safe_offset = max(offset, 0)
    stmt = select(Organization).where(Organization.status != "archived")
    if not is_superadmin(user):
        visible_ids = await _visible_workspace_ids(db, user)
        stmt = stmt.where(Organization.id.in_(visible_ids))
    search_clause = _search_filter(
        [Organization.business_name, Organization.business_email, Organization.description],
        search,
    )
    if search_clause is not None:
        stmt = stmt.where(search_clause)
    total = int((await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one() or 0)
    rows = (
        await db.execute(
            stmt.order_by(Organization.business_name.asc())
            .offset(safe_offset)
            .limit(safe_limit)
        )
    ).scalars().all()
    return AdminAssignableWorkspaceListOut(
        items=[
            AdminAssignableWorkspaceOut(
                id=row.id,
                businessName=row.business_name,
                status=row.status,
            )
            for row in rows
        ],
        total=total,
        offset=safe_offset,
        limit=safe_limit,
    )


@router.post(
    "/workspaces",
    response_model=AdminWorkspaceCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("organizations", "create"))],
)
async def admin_create_workspace(
    body: AdminWorkspaceCreate,
    request: Request,
    db: DB,
    user: AdminUser,
):
    workspace_name = body.businessName.strip()
    if not workspace_name.casefold().endswith(" workspace"):
        workspace_name = f"{workspace_name} Workspace"

    owner: User | None = None
    temporary_password: str | None = None
    new_owner_email: str | None = None
    new_owner_name: str | None = None
    new_owner_password_hash: str | None = None
    if body.ownerUserId:
        owner = await repo.get_user(db, body.ownerUserId)
        if owner is None:
            raise HTTPException(status_code=404, detail={"code": "OWNER_NOT_FOUND"})
    elif body.ownerEmail:
        email = body.ownerEmail.strip().lower()
        owner = await repo.get_user_by_email(db, email)
        if owner is None:
            temporary_password = body.ownerPassword or _generate_temporary_password()
            violations = validate_password_strength(temporary_password)
            if violations:
                raise HTTPException(
                    status_code=400,
                    detail={"code": "WEAK_PASSWORD", "violations": violations},
                )
            new_owner_email = email
            new_owner_name = (body.ownerName or email.split("@", 1)[0]).strip()
            new_owner_password_hash = hash_password(temporary_password)
    elif not is_superadmin(user):
        raise HTTPException(status_code=400, detail={"code": "OWNER_REQUIRED"})
    else:
        owner = user

    if owner is None:
        org = Organization(
            id=_uuid(),
            business_name=workspace_name,
            business_email=(body.businessEmail or "").strip() or None,
            business_logo=(body.businessLogo or "").strip() or None,
            description=(body.description or "").strip(),
        )
        db.add(org)
        await db.flush()
        owner = User(
            email=new_owner_email or "",
            name=new_owner_name or new_owner_email or "owner",
            hashed_password=new_owner_password_hash or "",
            role="system",
            is_active=True,
            must_change_password=True,
            default_org_id=org.id,
        )
        db.add(owner)
        await db.flush()
        await record_password_history(db, owner.id, owner.hashed_password)
        db.add(
            OrganizationMember(
                organization_id=org.id,
                user_id=owner.id,
                role="owner",
            )
        )
        await db.flush()
    else:
        org = await repo.create_organization(
            db,
            owner_id=owner.id,
            business_name=workspace_name,
            business_email=body.businessEmail,
            business_logo=body.businessLogo,
        )
        org.description = (body.description or "").strip()
        if not owner.default_org_id:
            owner.default_org_id = org.id
    if body.kind is not None:
        kind = body.kind.strip().lower()
        if kind not in WORKSPACE_KINDS:
            raise HTTPException(status_code=400, detail={"code": "INVALID_WORKSPACE_KIND"})
        org.kind = kind
    assigned_admins: list[AdminWorkspaceAdminOut] = []
    admin_user_ids = [item for item in dict.fromkeys(body.adminUserIds) if item]
    if not is_superadmin(user):
        admin_user_ids = [str(user.id), *admin_user_ids]
    if admin_user_ids and not is_superadmin(user):
        visible_ids = set(await _visible_workspace_ids(db, user))
        existing_admin_user_ids = {
            str(row.user_id)
            for row in (
                await db.execute(
                    select(OrganizationMember.user_id)
                    .where(OrganizationMember.organization_id.in_(visible_ids))
                    .where(OrganizationMember.role == "admin")
                )
            ).all()
        }
        if any(
            admin_user_id != str(user.id) and admin_user_id not in existing_admin_user_ids
            for admin_user_id in admin_user_ids
        ):
            raise HTTPException(status_code=403, detail={"code": "WORKSPACE_SCOPE_REQUIRED"})
    for admin_user_id in admin_user_ids:
        member, admin_user = await _assign_workspace_admin(
            db,
            workspace_id=org.id,
            admin_user_id=admin_user_id,
        )
        assigned_admins.append(_workspace_admin_out(member, admin_user))
    ip, ua = _client_meta(request)
    await emit_security_event(
        db,
        action="workspace.created",
        user_id=user.id,
        org_id=org.id,
        entity_type="organization",
        entity_id=org.id,
        ip_address=ip,
        user_agent=ua,
        details={"owner_user_id": owner.id},
    )
    for admin in assigned_admins:
        await emit_security_event(
            db,
            action="workspace_admin.assigned",
            user_id=user.id,
            org_id=org.id,
            entity_type="user",
            entity_id=admin.user_id,
            ip_address=ip,
            user_agent=ua,
            details={"workspace_id": org.id, "admin_user_id": admin.user_id},
        )
    await db.commit()
    counts = await _workspace_counts(db, [org.id])
    return AdminWorkspaceCreated(
        **_workspace_out(
            org,
            owner=_owner_out(owner),
            workspace_admins=assigned_admins,
            counts=counts.get(org.id),
        ).model_dump(),
        temporaryPassword=temporary_password,
    )


@router.get(
    "/workspaces/{workspace_id}",
    response_model=AdminWorkspaceOut,
    dependencies=[Depends(require_permission("organizations", "read"))],
)
async def admin_get_workspace(workspace_id: str, db: DB, user: AdminUser):
    org = await _workspace_or_404(db, workspace_id, user)
    owners = await _workspace_owners(db, [workspace_id])
    admins = await _workspace_admins(db, [workspace_id])
    counts = await _workspace_counts(db, [workspace_id])
    return _workspace_out(
        org,
        owner=owners.get(workspace_id),
        workspace_admins=admins.get(workspace_id),
        counts=counts.get(workspace_id),
    )


@router.patch(
    "/workspaces/{workspace_id}",
    response_model=AdminWorkspaceOut,
    dependencies=[Depends(require_permission("organizations", "update"))],
)
async def admin_update_workspace(
    workspace_id: str,
    body: AdminWorkspaceUpdate,
    request: Request,
    db: DB,
    user: AdminUser,
):
    org = await _workspace_or_404(db, workspace_id, user)
    before = _workspace_out(org).model_dump(mode="json")
    if body.businessName is not None:
        workspace_name = body.businessName.strip()
        if not workspace_name.casefold().endswith(" workspace"):
            workspace_name = f"{workspace_name} Workspace"
        org.business_name = workspace_name
    if body.businessEmail is not None:
        org.business_email = body.businessEmail.strip() or None
    if body.businessLogo is not None:
        org.business_logo = body.businessLogo.strip() or None
    if body.description is not None:
        org.description = body.description.strip()
    if body.status is not None:
        value = body.status.strip().lower()
        if value not in WORKSPACE_STATUSES:
            raise HTTPException(status_code=400, detail={"code": "INVALID_WORKSPACE_STATUS"})
        org.status = value
    if body.plan is not None:
        org.plan = body.plan.strip() or "standard"
    if body.kind is not None:
        value = body.kind.strip().lower()
        if value not in WORKSPACE_KINDS:
            raise HTTPException(status_code=400, detail={"code": "INVALID_WORKSPACE_KIND"})
        org.kind = value
    org.updated_at = _now()
    ip, ua = _client_meta(request)
    await emit_security_event(
        db,
        action="workspace.updated",
        user_id=user.id,
        org_id=workspace_id,
        entity_type="organization",
        entity_id=workspace_id,
        ip_address=ip,
        user_agent=ua,
        details={"before": before, "after": body.model_dump(exclude_none=True)},
    )
    await db.commit()
    owners = await _workspace_owners(db, [workspace_id])
    admins = await _workspace_admins(db, [workspace_id])
    counts = await _workspace_counts(db, [workspace_id])
    return _workspace_out(
        org,
        owner=owners.get(workspace_id),
        workspace_admins=admins.get(workspace_id),
        counts=counts.get(workspace_id),
    )


@router.get(
    "/workspaces/{workspace_id}/dependencies",
    response_model=AdminWorkspaceDependenciesOut,
    dependencies=[Depends(require_permission("organizations", "read"))],
)
async def admin_workspace_dependencies(workspace_id: str, db: DB, user: AdminUser):
    await _workspace_or_404(db, workspace_id, user)
    counts = (await _workspace_counts(db, [workspace_id])).get(workspace_id, {})
    return AdminWorkspaceDependenciesOut(
        agents=int(counts.get("agents", 0)),
        devices=int(counts.get("devices", 0)),
        members=int(counts.get("members", 0)),
    )


@router.get(
    "/workspace-access",
    response_model=AdminWorkspaceAccessOut,
    dependencies=[Depends(require_permission("organizations", "read"))],
)
async def admin_workspace_access(
    db: DB,
    user: AdminUser,
    workspaceId: str | None = Query(default=None),
):
    """Members and admins for one workspace, or for every visible workspace."""
    workspace_ids = await _visible_workspace_ids(db, user, workspaceId)
    if not workspace_ids:
        return AdminWorkspaceAccessOut()
    names = await _workspace_name_map(db, workspace_ids)
    rows = (
        await db.execute(
            select(OrganizationMember, User)
            .join(User, User.id == OrganizationMember.user_id)
            .where(OrganizationMember.organization_id.in_(workspace_ids))
            .where(OrganizationMember.role.in_(MANAGEABLE_WORKSPACE_MEMBER_ROLES | {"admin"}))
            .order_by(OrganizationMember.created_at.asc())
        )
    ).all()
    members: list[AdminWorkspaceAccessMemberOut] = []
    admins: list[AdminWorkspaceAccessAdminOut] = []
    for member, member_user in rows:
        workspace_id = str(member.organization_id)
        scope = {"workspaceId": workspace_id, "workspaceName": names.get(workspace_id, workspace_id)}
        if member.role == "admin":
            admins.append(
                AdminWorkspaceAccessAdminOut(
                    **_workspace_admin_out(member, member_user).model_dump(), **scope
                )
            )
        else:
            members.append(
                AdminWorkspaceAccessMemberOut(
                    **_workspace_member_out(member, member_user).model_dump(), **scope
                )
            )
    # Stable sort keeps the query's created_at order inside each workspace.
    members.sort(key=lambda m: m.workspaceName)
    admins.sort(key=lambda a: a.workspaceName)
    return AdminWorkspaceAccessOut(members=members, admins=admins)


@router.get(
    "/workspaces/{workspace_id}/admins",
    response_model=list[AdminWorkspaceAdminOut],
    dependencies=[Depends(require_permission("organizations", "read"))],
)
async def admin_list_workspace_admins(workspace_id: str, db: DB, user: AdminUser):
    await _workspace_or_404(db, workspace_id, user)
    return (await _workspace_admins(db, [workspace_id])).get(workspace_id, [])


@router.get(
    "/workspaces/{workspace_id}/members",
    response_model=list[OrganizationMemberOut],
    dependencies=[Depends(require_permission("organizations", "read"))],
)
async def admin_list_workspace_members(workspace_id: str, db: DB, user: AdminUser):
    await _workspace_or_404(db, workspace_id, user)
    rows = await repo.list_organization_members(db, workspace_id)
    return [_workspace_member_out(member, row_user) for member, row_user in rows]


@router.post(
    "/workspaces/{workspace_id}/members",
    response_model=OrganizationMemberInviteOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("organizations", "manage"))],
)
async def admin_invite_workspace_member(
    workspace_id: str,
    body: OrganizationMemberInvite,
    request: Request,
    db: DB,
    user: AdminUser,
):
    org = await _workspace_or_404(db, workspace_id, user)
    email = (body.email or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail={"code": "INVALID_EMAIL"})
    invite_role = (body.role or "member").strip().lower()
    if invite_role not in MANAGEABLE_WORKSPACE_MEMBER_ROLES:
        raise HTTPException(status_code=400, detail={"code": "INVALID_ROLE"})
    try:
        invitation, existing_user, email_sent = await create_and_email_invitation(
            db,
            organization_id=workspace_id,
            email=email,
            role=invite_role,
            invited_by_user_id=user.id,
            inviter_name=getattr(user, "name", None),
        )
    except ValueError as exc:
        code = str(exc)
        if code == "ALREADY_MEMBER":
            raise HTTPException(status_code=409, detail={"code": "ALREADY_MEMBER"}) from exc
        if code == "ORG_NOT_FOUND":
            raise HTTPException(status_code=404, detail={"code": "WORKSPACE_NOT_FOUND"}) from exc
        raise
    ip, ua = _client_meta(request)
    await emit_security_event(
        db,
        action="member.invited",
        user_id=user.id,
        org_id=org.id,
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


@router.patch(
    "/workspaces/{workspace_id}/members/{member_user_id}",
    response_model=OrganizationMemberOut,
    dependencies=[Depends(require_permission("organizations", "manage"))],
)
async def admin_update_workspace_member(
    workspace_id: str,
    member_user_id: str,
    body: OrganizationMemberUpdate,
    request: Request,
    db: DB,
    user: AdminUser,
):
    await _workspace_or_404(db, workspace_id, user)
    new_role = (body.role or "").strip().lower()
    if new_role not in MANAGEABLE_WORKSPACE_MEMBER_ROLES:
        raise HTTPException(status_code=400, detail={"code": "INVALID_ROLE"})
    if member_user_id == user.id:
        raise HTTPException(status_code=400, detail={"code": "CANNOT_CHANGE_OWN_ROLE"})
    member = await repo.get_organization_member(db, workspace_id, member_user_id)
    if member is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    if member.role == "owner":
        raise HTTPException(status_code=400, detail={"code": "CANNOT_CHANGE_OWNER"})
    if member.role == "admin":
        raise HTTPException(status_code=400, detail={"code": "CANNOT_CHANGE_WORKSPACE_ADMIN"})
    old_role = member.role
    if old_role == new_role:
        target = await repo.get_user(db, member_user_id)
        if target is None:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
        return _workspace_member_out(member, target)
    updated = await repo.update_organization_member_role(
        db,
        organization_id=workspace_id,
        user_id=member_user_id,
        role=new_role,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    target = await repo.get_user(db, member_user_id)
    if target is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    ip, ua = _client_meta(request)
    await emit_security_event(
        db,
        action="member.role_changed",
        user_id=user.id,
        org_id=workspace_id,
        entity_type="user",
        entity_id=member_user_id,
        ip_address=ip,
        user_agent=ua,
        details={"old_role": old_role, "new_role": new_role},
    )
    return _workspace_member_out(updated, target)


@router.delete(
    "/workspaces/{workspace_id}/members/{member_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("organizations", "manage"))],
)
async def admin_remove_workspace_member(
    workspace_id: str,
    member_user_id: str,
    request: Request,
    db: DB,
    user: AdminUser,
):
    await _workspace_or_404(db, workspace_id, user)
    if member_user_id == user.id:
        raise HTTPException(status_code=400, detail={"code": "CANNOT_REMOVE_SELF"})
    member = await repo.get_organization_member(db, workspace_id, member_user_id)
    if member is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    if member.role == "owner":
        raise HTTPException(status_code=400, detail={"code": "CANNOT_REMOVE_OWNER"})
    if member.role == "admin":
        raise HTTPException(status_code=400, detail={"code": "CANNOT_REMOVE_WORKSPACE_ADMIN"})
    await repo.remove_organization_member(db, workspace_id, member_user_id)
    ip, ua = _client_meta(request)
    await emit_security_event(
        db,
        action="member.removed",
        user_id=user.id,
        org_id=workspace_id,
        entity_type="user",
        entity_id=member_user_id,
        ip_address=ip,
        user_agent=ua,
    )
    return None


@router.post(
    "/workspaces/{workspace_id}/admins",
    response_model=AdminWorkspaceAdminOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("organizations", "manage"))],
)
async def admin_assign_workspace_admin(
    workspace_id: str,
    body: AdminWorkspaceAdminAssign,
    request: Request,
    db: DB,
    user: AdminUser,
):
    _require_superadmin(user)
    await _workspace_or_404(db, workspace_id, user)
    member, target = await _assign_workspace_admin(
        db,
        workspace_id=workspace_id,
        admin_user_id=body.userId,
    )
    ip, ua = _client_meta(request)
    await emit_security_event(
        db,
        action="workspace_admin.assigned",
        user_id=user.id,
        org_id=workspace_id,
        entity_type="user",
        entity_id=target.id,
        ip_address=ip,
        user_agent=ua,
        details={"workspace_id": workspace_id, "admin_user_id": target.id},
    )
    await db.commit()
    return _workspace_admin_out(member, target)


@router.delete(
    "/workspaces/{workspace_id}/admins/{admin_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("organizations", "manage"))],
)
async def admin_remove_workspace_admin(
    workspace_id: str,
    admin_user_id: str,
    request: Request,
    db: DB,
    user: AdminUser,
):
    _require_superadmin(user)
    await _workspace_or_404(db, workspace_id, user)
    member = await repo.get_organization_member(db, workspace_id, admin_user_id)
    if member is None or member.role != "admin":
        raise HTTPException(status_code=404, detail={"code": "WORKSPACE_ADMIN_NOT_FOUND"})
    target = await repo.get_user(db, admin_user_id)
    if target is None:
        raise HTTPException(status_code=404, detail={"code": "ADMIN_USER_NOT_FOUND"})
    await repo.remove_organization_member(db, workspace_id, admin_user_id)
    if target.default_org_id == workspace_id:
        next_org = (
            await db.execute(
                select(OrganizationMember.organization_id)
                .where(OrganizationMember.user_id == admin_user_id)
                .order_by(OrganizationMember.created_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        target.default_org_id = next_org
    ip, ua = _client_meta(request)
    await emit_security_event(
        db,
        action="workspace_admin.removed",
        user_id=user.id,
        org_id=workspace_id,
        entity_type="user",
        entity_id=admin_user_id,
        ip_address=ip,
        user_agent=ua,
        details={"workspace_id": workspace_id, "admin_user_id": admin_user_id},
    )
    await db.commit()
    return None


@router.post(
    "/workspaces/{workspace_id}/suspend",
    response_model=AdminWorkspaceOut,
    dependencies=[Depends(require_permission("organizations", "manage"))],
)
async def admin_suspend_workspace(workspace_id: str, request: Request, db: DB, user: AdminUser):
    return await admin_update_workspace(
        workspace_id,
        AdminWorkspaceUpdate(status="suspended"),
        request,
        db,
        user,
    )


@router.post(
    "/workspaces/{workspace_id}/reactivate",
    response_model=AdminWorkspaceOut,
    dependencies=[Depends(require_permission("organizations", "manage"))],
)
async def admin_reactivate_workspace(workspace_id: str, request: Request, db: DB, user: AdminUser):
    return await admin_update_workspace(
        workspace_id,
        AdminWorkspaceUpdate(status="active"),
        request,
        db,
        user,
    )


@router.post(
    "/workspaces/{workspace_id}/archive",
    response_model=AdminWorkspaceOut,
    dependencies=[Depends(require_permission("organizations", "delete"))],
)
async def admin_archive_workspace(workspace_id: str, request: Request, db: DB, user: AdminUser):
    return await admin_update_workspace(
        workspace_id,
        AdminWorkspaceUpdate(status="archived"),
        request,
        db,
        user,
    )


@router.post(
    "/workspaces/{workspace_id}/transfer-owner",
    response_model=AdminWorkspaceOut,
    dependencies=[Depends(require_permission("organizations", "manage"))],
)
async def admin_transfer_workspace_owner(
    workspace_id: str,
    body: AdminWorkspaceTransferOwner,
    request: Request,
    db: DB,
    user: AdminUser,
):
    org = await _workspace_or_404(db, workspace_id, user)
    target = await repo.get_user(db, body.userId)
    if target is None or not target.is_active:
        raise HTTPException(status_code=404, detail={"code": "OWNER_NOT_FOUND"})
    members = await repo.list_organization_members(db, workspace_id)
    if all(member.user_id != target.id for member, _ in members):
        await repo.add_organization_member(
            db, organization_id=workspace_id, user_id=target.id, role="owner"
        )
    for member, _member_user in members:
        if member.user_id == target.id:
            member.role = "owner"
        elif member.role == "owner":
            member.role = "member"
    target.default_org_id = target.default_org_id or workspace_id
    org.updated_at = _now()
    ip, ua = _client_meta(request)
    await emit_security_event(
        db,
        action="workspace.owner_transferred",
        user_id=user.id,
        org_id=workspace_id,
        entity_type="organization",
        entity_id=workspace_id,
        ip_address=ip,
        user_agent=ua,
        details={"new_owner_user_id": target.id},
    )
    await db.commit()
    owners = await _workspace_owners(db, [workspace_id])
    admins = await _workspace_admins(db, [workspace_id])
    counts = await _workspace_counts(db, [workspace_id])
    return _workspace_out(
        org,
        owner=owners.get(workspace_id),
        workspace_admins=admins.get(workspace_id),
        counts=counts.get(workspace_id),
    )


@router.patch(
    "/workspaces/{workspace_id}/owner",
    response_model=AdminOwnerOut,
    dependencies=[Depends(require_permission("organizations", "manage"))],
)
async def admin_update_workspace_owner(
    workspace_id: str,
    body: AdminOwnerUpdate,
    request: Request,
    db: DB,
    user: AdminUser,
):
    await _workspace_or_404(db, workspace_id, user)
    owner_row = (
        await db.execute(
            select(User)
            .join(OrganizationMember, OrganizationMember.user_id == User.id)
            .where(OrganizationMember.organization_id == workspace_id)
            .where(OrganizationMember.role == "owner")
            .limit(1)
        )
    ).scalar_one_or_none()
    if owner_row is None:
        raise HTTPException(status_code=404, detail={"code": "OWNER_NOT_FOUND"})
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status_code=400, detail={"code": "NO_OWNER_CHANGES"})
    before = {
        "is_active": bool(owner_row.is_active),
        "must_change_password": bool(getattr(owner_row, "must_change_password", False)),
    }
    if body.is_active is not None:
        owner_row.is_active = body.is_active
    if body.mustChangePassword is not None:
        owner_row.must_change_password = body.mustChangePassword
    ip, ua = _client_meta(request)
    await emit_security_event(
        db,
        action=(
            "owner.disabled"
            if body.is_active is False
            else "owner.enabled"
            if body.is_active is True
            else "owner.force_password_change"
            if body.mustChangePassword is True
            else "owner.updated"
        ),
        user_id=user.id,
        org_id=workspace_id,
        entity_type="user",
        entity_id=owner_row.id,
        ip_address=ip,
        user_agent=ua,
        details={"before": before, "after": changes},
    )
    await db.commit()
    owner = _owner_out(owner_row)
    if owner is None:
        raise HTTPException(status_code=404, detail={"code": "OWNER_NOT_FOUND"})
    return owner


@router.post(
    "/workspaces/{workspace_id}/owner/reset-password",
    response_model=AdminOwnerPasswordResetOut,
    dependencies=[Depends(require_permission("organizations", "manage"))],
)
async def admin_reset_workspace_owner_password(
    workspace_id: str,
    body: AdminOwnerPasswordReset,
    request: Request,
    db: DB,
    user: AdminUser,
):
    await _workspace_or_404(db, workspace_id, user)
    owners = await _workspace_owners(db, [workspace_id])
    owner = owners.get(workspace_id)
    if owner is None:
        raise HTTPException(status_code=404, detail={"code": "OWNER_NOT_FOUND"})
    owner_row = await repo.get_user(db, owner.user_id)
    if owner_row is None or not owner_row.is_active:
        raise HTTPException(status_code=404, detail={"code": "OWNER_NOT_FOUND"})
    temporary_password = body.password or _generate_temporary_password()
    violations = validate_password_strength(temporary_password)
    if violations:
        raise HTTPException(
            status_code=400,
            detail={"code": "WEAK_PASSWORD", "violations": violations},
        )
    owner_row.hashed_password = hash_password(temporary_password)
    owner_row.must_change_password = True
    await record_password_history(db, owner_row.id, owner_row.hashed_password)
    ip, ua = _client_meta(request)
    await emit_security_event(
        db,
        action="owner.password_reset",
        user_id=user.id,
        org_id=workspace_id,
        entity_type="user",
        entity_id=owner_row.id,
        ip_address=ip,
        user_agent=ua,
        details={"workspace_id": workspace_id},
    )
    await db.commit()
    return AdminOwnerPasswordResetOut(
        owner=_owner_out(owner_row, owner.role),
        temporaryPassword=temporary_password,
    )


def _agent_token_out(
    row: RelayAgentToken,
    *,
    workspace_name: str | None = None,
) -> AdminAgentTokenOut:
    return AdminAgentTokenOut(
        id=row.id,
        workspaceId=row.org_id,
        workspaceName=workspace_name,
        user_id=row.user_id,
        name=row.name,
        prefix=row.prefix,
        status=row.status,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        revoked_at=row.revoked_at,
    )


def _agent_token_out_from_mapping(
    row: Any,
    *,
    workspace_id: str,
    workspace_name: str | None = None,
) -> AdminAgentTokenOut:
    return AdminAgentTokenOut(
        id=row["id"],
        workspaceId=workspace_id,
        workspaceName=workspace_name,
        user_id=row["user_id"],
        name=row["name"],
        prefix=row["prefix"],
        status=row["status"],
        created_at=row["created_at"],
        last_used_at=row["last_used_at"],
        revoked_at=row["revoked_at"],
    )


@router.get(
    "/agent-activation-tokens",
    response_model=list[AdminAgentTokenOut],
    dependencies=[Depends(require_permission("relay-agents", "read"))],
)
async def admin_list_agent_activation_tokens(
    db: DB,
    user: AdminUser,
    workspace_id: str | None = Query(None, alias="workspaceId"),
):
    token_table = RelayAgentToken.__table__
    user_table = User.__table__
    member_table = OrganizationMember.__table__
    first_member_org = (
        select(member_table.c.organization_id)
        .where(member_table.c.user_id == token_table.c.user_id)
        .order_by(member_table.c.created_at.asc())
        .limit(1)
        .scalar_subquery()
    )
    resolved_workspace_id = func.coalesce(
        token_table.c.org_id,
        user_table.c.default_org_id,
        first_member_org,
    ).label("_resolved_workspace_id")
    stmt = select(token_table, resolved_workspace_id).select_from(
        token_table.outerjoin(user_table, user_table.c.id == token_table.c.user_id)
    )
    if workspace_id:
        visible_ids = await _visible_workspace_ids(db, user, workspace_id)
        stmt = stmt.where(resolved_workspace_id.in_(visible_ids))
    elif not is_superadmin(user):
        org_id = getattr(user, "org_id", None)
        if not org_id:
            raise HTTPException(status_code=400, detail={"code": "WORKSPACE_SCOPE_REQUIRED"})
        stmt = stmt.where(resolved_workspace_id == org_id)
    rows = (
        await db.execute(
            stmt.order_by(token_table.c.created_at.desc()).limit(200)
        )
    ).mappings().all()
    resolved_rows = [
        (row, str(row["_resolved_workspace_id"]))
        for row in rows
        if row["_resolved_workspace_id"]
    ]
    orgs = await _workspace_name_map(
        db, {workspace_id for _row, workspace_id in resolved_rows}
    )
    return [
        _agent_token_out_from_mapping(
            row,
            workspace_id=workspace_id,
            workspace_name=orgs.get(workspace_id),
        )
        for row, workspace_id in resolved_rows
    ]


@router.post(
    "/agent-activation-tokens",
    response_model=AdminAgentTokenCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("relay-agents", "create"))],
)
async def admin_create_agent_activation_token(
    body: AdminAgentTokenCreate,
    request: Request,
    db: DB,
    user: AdminUser,
):
    workspace_id = body.workspaceId.strip()
    # Any workspace may hold a code — a tenant running its own relay host is a
    # normal case. What the workspace kind decides is whether those phones can
    # be allocated *out* to other workspaces; that guard lives on allocation.
    target = await _workspace_or_404(db, workspace_id, user)
    owner_id = body.ownerUserId
    if owner_id:
        owner_user = await repo.get_user(db, owner_id)
        if owner_user is None:
            raise HTTPException(status_code=404, detail={"code": "USER_NOT_FOUND"})
        if await repo.get_organization_role_for_user(db, owner_user.id, workspace_id) is None:
            raise HTTPException(status_code=409, detail={"code": "USER_NOT_IN_WORKSPACE"})
        token_user_id = owner_user.id
    else:
        owners = await _workspace_owners(db, [workspace_id])
        owner = owners.get(workspace_id)
        token_user_id = owner.user_id if owner else user.id
    raw_token, row = await repo.create_relay_agent_token(
        db,
        user_id=token_user_id,
        name=body.name,
        org_id=workspace_id,
    )
    ip, ua = _client_meta(request)
    await emit_security_event(
        db,
        action="agent.activation_created",
        user_id=user.id,
        org_id=workspace_id,
        entity_type="relay_agent_token",
        entity_id=row.id,
        ip_address=ip,
        user_agent=ua,
        details={"workspace_id": workspace_id, "prefix": row.prefix},
    )
    await db.commit()
    return AdminAgentTokenCreated(
        **_agent_token_out(row, workspace_name=target.business_name).model_dump(),
        token=raw_token,
    )


@router.delete(
    "/agent-activation-tokens/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("relay-agents", "delete"))],
)
async def admin_revoke_agent_activation_token(
    token_id: str,
    request: Request,
    db: DB,
    user: AdminUser,
):
    stmt = select(RelayAgentToken).where(RelayAgentToken.id == token_id)
    if not is_superadmin(user):
        visible_ids = await _visible_workspace_ids(db, user)
        stmt = stmt.where(RelayAgentToken.org_id.in_(visible_ids))
    row = (await db.execute(stmt.limit(1))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "TOKEN_NOT_FOUND"})
    await _require_visible_workspace_scope(db, user, str(row.org_id))
    row.status = "revoked"
    row.revoked_at = _now()
    ip, ua = _client_meta(request)
    await emit_security_event(
        db,
        action="agent.activation_revoked",
        user_id=user.id,
        org_id=row.org_id,
        entity_type="relay_agent_token",
        entity_id=row.id,
        ip_address=ip,
        user_agent=ua,
        details={"workspace_id": row.org_id, "prefix": row.prefix},
    )
    await db.commit()
    return None


@router.post(
    "/agent-activation-tokens/{token_id}/replace",
    response_model=AdminAgentTokenCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("relay-agents", "create"))],
)
async def admin_replace_agent_activation_token(
    token_id: str,
    request: Request,
    db: DB,
    user: AdminUser,
):
    stmt = select(RelayAgentToken).where(RelayAgentToken.id == token_id)
    if not is_superadmin(user):
        visible_ids = await _visible_workspace_ids(db, user)
        stmt = stmt.where(RelayAgentToken.org_id.in_(visible_ids))
    current = (await db.execute(stmt.limit(1))).scalar_one_or_none()
    if current is None:
        raise HTTPException(status_code=404, detail={"code": "TOKEN_NOT_FOUND"})

    workspace_id = str(current.org_id)
    target = await _workspace_or_404(db, workspace_id, user)
    current.status = "revoked"
    current.revoked_at = _now()
    raw_token, replacement = await repo.create_relay_agent_token(
        db,
        user_id=current.user_id,
        name=current.name,
        org_id=workspace_id,
    )
    ip, ua = _client_meta(request)
    await emit_security_event(
        db,
        action="agent.activation_replaced",
        user_id=user.id,
        org_id=workspace_id,
        entity_type="relay_agent_token",
        entity_id=replacement.id,
        ip_address=ip,
        user_agent=ua,
        details={
            "workspace_id": workspace_id,
            "replaced_token_id": current.id,
            "prefix": replacement.prefix,
        },
    )
    await db.commit()
    return AdminAgentTokenCreated(
        **_agent_token_out(
            replacement, workspace_name=target.business_name
        ).model_dump(),
        token=raw_token,
    )


def _kick_relay_control_stream(relay_id: str) -> bool:
    """Best-effort: the DB row is the source of truth, the kick is the speed-up."""
    try:
        from runtime.transports.agent_control_servicer import get_control_servicer

        servicer = get_control_servicer()
    except Exception:  # pragma: no cover - transport not wired (tests, CLI)
        return False
    if servicer is None:
        return False
    try:
        return bool(servicer.kick(relay_id))
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("could not kick relay control stream %s: %s", relay_id, exc)
        return False


def _live_relay_ids() -> set[str]:
    """Relay ids with an open control stream right now.

    `status` in the row is intent ("an admin turned this on"); this is fact. The
    console needs both, because enabling cannot take effect until the agent
    itself comes back and saying "done" before that misleads the operator.
    """
    try:
        from runtime.transports.agent_control_servicer import get_control_servicer

        servicer = get_control_servicer()
    except Exception:  # pragma: no cover - transport not wired
        return set()
    if servicer is None:
        return set()
    try:
        return {str(relay_id) for relay_id in servicer.online_relay_ids()}
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("could not read live relay ids: %s", exc)
        return set()


def _apply_agent_suspension(relay_id: str, serials: list[str], *, suspend: bool) -> None:
    """Park or resume an agent across all three transports, in place.

    One call site, because an agent that is dark on the control plane but still
    publishing video is not off — and because three transports drifting apart is
    how this bug survived so long.
    """
    try:
        from runtime.transports.agent_suspension import get_agent_suspension_registry

        registry = get_agent_suspension_registry()
    except Exception:  # pragma: no cover - transports not wired (tests, CLI)
        return
    if suspend:
        registry.suspend(relay_id, serials)
    else:
        registry.resume(relay_id, serials)

    try:
        from runtime.transports.agent_control_servicer import get_control_servicer

        control = get_control_servicer()
        if control is not None:
            control.suspend(relay_id) if suspend else control.resume(relay_id)
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("control plane suspension failed for %s: %s", relay_id, exc)

    try:
        from runtime.transports.media_adapter_control_servicer import (
            get_media_adapter_servicer,
        )

        media = get_media_adapter_servicer()
        if media is not None:
            media.reindex_serials()
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("media plane suspension failed for %s: %s", relay_id, exc)

    try:
        from runtime.transports.adb_relay_server import get_relay_manager

        manager = get_relay_manager()
    except Exception:  # pragma: no cover - defensive
        manager = None
    if manager is not None:
        coro = (
            manager.suspend_relay(relay_id) if suspend else manager.resume_relay(relay_id)
        )
        try:
            asyncio.get_running_loop().create_task(coro)
        except RuntimeError:  # pragma: no cover - no loop (sync tests)
            coro.close()


def _agent_out(
    row: RelayAgent,
    workspace_name: str | None = None,
    live_relay_ids: set[str] | None = None,
    workspace_kind: str = "tenant",
) -> AdminAgentOut:
    live = _live_relay_ids() if live_relay_ids is None else live_relay_ids
    return AdminAgentOut(
        connected=str(row.relay_id) in live,
        relay_id=row.relay_id,
        workspaceId=row.org_id,
        workspaceName=workspace_name,
        workspaceKind=workspace_kind,
        user_id=row.user_id,
        enrollment_token_id=row.enrollment_token_id,
        name=row.name or "",
        hostname=row.hostname,
        ip=row.ip,
        version=row.version,
        serials=list(row.serials or []),
        status=row.status,
        health=_agent_health(row),
        deviceCount=len(row.serials or []),
        connected_at=row.connected_at,
        last_heartbeat_at=row.last_heartbeat_at,
        disconnected_at=row.disconnected_at,
        created_at=row.created_at,
    )


def _agent_out_from_mapping(
    row: Any,
    workspace_name: str | None = None,
    live_relay_ids: set[str] | None = None,
    workspace_kind: str = "tenant",
) -> AdminAgentOut:
    serials = list(row["serials"] or [])
    live = _live_relay_ids() if live_relay_ids is None else live_relay_ids
    return AdminAgentOut(
        connected=str(row["relay_id"]) in live,
        relay_id=row["relay_id"],
        workspaceId=row["org_id"],
        workspaceName=workspace_name,
        workspaceKind=workspace_kind,
        user_id=row["user_id"],
        enrollment_token_id=row["enrollment_token_id"],
        name=row["name"] or "",
        hostname=row["hostname"],
        ip=row["ip"],
        version=row["version"],
        serials=serials,
        status=row["status"],
        health=_agent_health_values(row["status"], row["last_heartbeat_at"]),
        deviceCount=len(serials),
        connected_at=row["connected_at"],
        last_heartbeat_at=row["last_heartbeat_at"],
        disconnected_at=row["disconnected_at"],
        created_at=row["created_at"],
    )


@router.get(
    "/agents",
    response_model=AdminAgentListOut,
    dependencies=[Depends(require_permission("relay-agents", "read"))],
)
async def admin_list_agents(
    db: DB,
    user: AdminUser,
    search: str | None = None,
    workspace_id: str | None = Query(None, alias="workspaceId"),
    status_: str | None = Query(None, alias="status"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    safe_limit = min(max(limit, 1), 100)
    safe_offset = max(offset, 0)
    agent_table = RelayAgent.__table__
    stmt = select(agent_table)
    if workspace_id or not is_superadmin(user):
        visible_ids = await _visible_workspace_ids(db, user, workspace_id)
        stmt = stmt.where(agent_table.c.org_id.in_(visible_ids))
    search_clause = _search_filter(
        [
            agent_table.c.relay_id,
            agent_table.c.name,
            agent_table.c.hostname,
            agent_table.c.ip,
            agent_table.c.version,
        ],
        search,
    )
    if search_clause is not None:
        stmt = stmt.where(search_clause)
    if status_:
        stmt = stmt.where(agent_table.c.status == status_)
    else:
        # Archived rows are superseded duplicates — surface them only on request.
        stmt = stmt.where(agent_table.c.status != "archived")
    total = int(
        (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        or 0
    )
    rows = (
        await db.execute(
            stmt.order_by(agent_table.c.connected_at.desc())
            .offset(safe_offset)
            .limit(safe_limit)
        )
    ).mappings().all()
    org_ids = {str(row["org_id"]) for row in rows}
    orgs = await _workspace_name_map(db, org_ids)
    pool_ids = {
        str(org_id)
        for org_id in (
            await db.execute(
                select(Organization.id)
                .where(Organization.id.in_(org_ids))
                .where(Organization.kind == POOL_WORKSPACE_KIND)
            )
        ).scalars()
    }
    live_relay_ids = _live_relay_ids()
    return AdminAgentListOut(
        items=[
            _agent_out_from_mapping(
                row,
                orgs.get(str(row["org_id"])),
                live_relay_ids,
                workspace_kind=(
                    POOL_WORKSPACE_KIND if str(row["org_id"]) in pool_ids else "tenant"
                ),
            )
            for row in rows
        ],
        total=total,
        offset=safe_offset,
        limit=safe_limit,
    )


def _reported_agent_phone_serials(agent: RelayAgent) -> list[str]:
    return [
        str(serial).strip()
        for serial in (agent.serials or [])
        if str(serial).strip() and not str(serial).startswith("pending-")
    ]


async def _agent_phone_device_rows(db: DB, serials: list[str]) -> dict[str, Any]:
    cleaned = [serial.strip() for serial in serials if serial and serial.strip()]
    if not cleaned:
        return {}
    device_table = Device.__table__
    state_table = DeviceFsmSnapshot.__table__
    rows: list[Any] = []
    chunk_size = 500
    for start in range(0, len(cleaned), chunk_size):
        chunk = cleaned[start : start + chunk_size]
        rows.extend(
            (
                await db.execute(
                    select(device_table, state_table.c.state.label("state"))
                    .select_from(
                        device_table.outerjoin(
                            state_table,
                            state_table.c.device_id == device_table.c.id,
                        )
                    )
                    .where(
                        or_(
                            device_table.c.serial.in_(chunk),
                            device_table.c.adb_serial.in_(chunk),
                        )
                    )
                    .order_by(device_table.c.created_at.asc())
                )
            )
            .mappings()
            .all()
        )
    out: dict[str, Any] = {}
    for row in rows:
        aliases = [
            str(row["serial"] or ""),
            str(row["adb_serial"] or ""),
        ]
        for alias in aliases:
            if alias in cleaned and alias not in out:
                out[alias] = row
    return out


def _phone_matches_filter(
    serial: str,
    row: Any | None,
    *,
    search: str | None,
    status_filter: str | None,
    assigned_workspace_id: str | None,
    manager_workspace_id: str,
) -> bool:
    if search:
        needle = search.strip().lower()
        haystack = [
            serial,
            str(row["name"] or "") if row else "",
            str(row["brand"] or "") if row else "",
            str(row["model"] or "") if row else "",
            str(row["device_serial"] or "") if row else "",
            str(row["adb_serial"] or "") if row else "",
        ]
        if not any(needle in value.lower() for value in haystack if value):
            return False
    if status_filter:
        row_status = str(row["status"] or "paired").lower() if row else "ready"
        row_state = str(row["state"] or "unknown").lower() if row else "unknown"
        value = status_filter.strip().lower()
        if value not in {row_status, row_state}:
            return False
    if assigned_workspace_id:
        assigned_id = str(row["org_id"]) if row and row["org_id"] else None
        value = assigned_workspace_id.strip()
        if value == UNASSIGNED_PHONE_FILTER:
            if assigned_id and assigned_id != manager_workspace_id:
                return False
        elif assigned_id != value:
            return False
    return True


async def _agent_phone_outs(
    db: DB,
    agent: RelayAgent,
    serials: list[str] | None = None,
    device_rows: dict[str, Any] | None = None,
) -> list[AdminAgentPhoneOut]:
    visible_serials = (
        [
            str(serial).strip()
            for serial in serials
            if str(serial).strip() and not str(serial).startswith("pending-")
        ]
        if serials is not None
        else _reported_agent_phone_serials(agent)
    )
    if device_rows is None:
        device_rows = await _agent_phone_device_rows(db, visible_serials)
    org_ids = {str(agent.org_id)}
    for row in device_rows.values():
        if row["org_id"]:
            org_ids.add(str(row["org_id"]))
        if row["managed_by_org_id"]:
            org_ids.add(str(row["managed_by_org_id"]))
    orgs = await _workspace_name_map(db, org_ids)

    phones: list[AdminAgentPhoneOut] = []
    for serial in visible_serials:
        row = device_rows.get(serial)
        managed_id = str(row["managed_by_org_id"] or agent.org_id) if row else str(agent.org_id)
        assigned_id = str(row["org_id"]) if row and row["org_id"] else None
        phones.append(
            AdminAgentPhoneOut(
                serial=serial,
                deviceId=str(row["id"]) if row else None,
                registered=row is not None,
                name=str(row["name"] or "") if row else "",
                brand=str(row["brand"] or "") if row else "",
                model=str(row["model"] or "") if row else "",
                status=str(row["status"] or "paired") if row else "ready",
                state=str(row["state"] or "unknown") if row else "unknown",
                last_seen=row["last_seen"] if row else None,
                managedByWorkspaceId=managed_id,
                managedByWorkspaceName=orgs.get(managed_id),
                assignedWorkspaceId=assigned_id,
                assignedWorkspaceName=orgs.get(assigned_id) if assigned_id else None,
                pooled=assigned_id is None or assigned_id == managed_id,
            )
        )
    return phones


async def _agent_phone_page(
    db: DB,
    agent: RelayAgent,
    *,
    search: str | None = None,
    status_filter: str | None = None,
    assigned_workspace_id: str | None = None,
    offset: int = 0,
    limit: int = PHONE_LIST_DEFAULT_LIMIT,
) -> tuple[list[AdminAgentPhoneOut], int, int, int]:
    safe_offset = max(offset, 0)
    safe_limit = min(max(limit, 1), PHONE_LIST_MAX_LIMIT)
    serials = _reported_agent_phone_serials(agent)
    has_filters = bool(
        (search and search.strip()) or status_filter or assigned_workspace_id
    )
    if not has_filters:
        page_serials = serials[safe_offset : safe_offset + safe_limit]
        return await _agent_phone_outs(db, agent, page_serials), len(serials), safe_offset, safe_limit

    device_rows = await _agent_phone_device_rows(db, serials)
    manager_workspace_id = str(agent.org_id)
    filtered = [
        serial
        for serial in serials
        if _phone_matches_filter(
            serial,
            device_rows.get(serial),
            search=search,
            status_filter=status_filter,
            assigned_workspace_id=assigned_workspace_id,
            manager_workspace_id=manager_workspace_id,
        )
    ]
    page_serials = filtered[safe_offset : safe_offset + safe_limit]
    return (
        await _agent_phone_outs(db, agent, page_serials, device_rows=device_rows),
        len(filtered),
        safe_offset,
        safe_limit,
    )


def _clean_phone_serials(
    serials: list[str], agent: RelayAgent, *, require_reported: bool
) -> list[str]:
    reported = {
        str(serial).strip()
        for serial in (agent.serials or [])
        if str(serial).strip() and not str(serial).startswith("pending-")
    }
    cleaned = list(
        dict.fromkeys(str(serial).strip() for serial in serials if str(serial).strip())
    )
    if not cleaned:
        raise HTTPException(status_code=400, detail={"code": "NO_SERIALS_SELECTED"})
    if len(cleaned) > PHONE_ASSIGN_BATCH_LIMIT:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "PHONE_BATCH_TOO_LARGE",
                "limit": PHONE_ASSIGN_BATCH_LIMIT,
                "count": len(cleaned),
            },
        )
    # `agent.serials` is the heartbeat snapshot, not a ledger: a phone that was
    # unplugged or died drops off it. Requiring it is right for assignment (the
    # admin picks from what the agent sees) and wrong for release — it would
    # strand the device in the workspace it was lent to, forever.
    if require_reported:
        missing = [serial for serial in cleaned if serial not in reported]
        if missing:
            raise HTTPException(
                status_code=409,
                detail={"code": "SERIAL_NOT_REPORTED_BY_AGENT", "serials": missing},
            )
    return cleaned


async def _assign_agent_phone_serials(
    db: DB,
    *,
    agent: RelayAgent,
    serials: list[str],
    target_workspace_id: str,
    create_missing: bool,
) -> list[AdminAgentPhoneOut]:
    manager_org_id = str(agent.org_id)
    manager = await _workspace_by_id_or_404(db, manager_org_id)
    if (getattr(manager, "kind", "tenant") or "tenant") != POOL_WORKSPACE_KIND:
        # Agent enrolled with a tenant's activation code: its phones belong to
        # that tenant alone. Re-issue the code from a pool workspace instead.
        raise HTTPException(
            status_code=409,
            detail={
                "code": "AGENT_NOT_IN_POOL_WORKSPACE",
                "workspaceId": manager_org_id,
            },
        )
    target = await _workspace_by_id_or_404(db, target_workspace_id)
    if target.status == "archived":
        raise HTTPException(
            status_code=409,
            detail={"code": "TARGET_WORKSPACE_ARCHIVED"},
        )
    device_rows = await _agent_phone_device_rows(db, serials)

    for serial in serials:
        row = device_rows.get(serial)
        if row is None:
            if not create_missing:
                # Only assignment may register a phone the agent just reported.
                # On release an unknown serial is a typo, and inventing a row
                # for it would plant a ghost device nobody can clean up.
                raise HTTPException(
                    status_code=404,
                    detail={"code": "DEVICE_NOT_FOUND", "serial": serial},
                )
            with tenant_context(target.id):
                device = await repo.create_device(
                    db,
                    serial,
                    serial,
                    None,
                    org_id=target.id,
                )
                device.relay_serial = serial
                await mark_allocated_unclaimed(
                    db,
                    device,
                    target_org_id=target.id,
                    manager_org_id=manager_org_id,
                    relay_id=agent.relay_id,
                    flush=False,
                )
            continue

        managed_by = str(row["managed_by_org_id"] or manager_org_id)
        if managed_by != manager_org_id:
            raise HTTPException(
                status_code=409,
                detail={"code": "DEVICE_MANAGED_BY_ANOTHER_WORKSPACE", "serial": serial},
            )
        with tenant_context(str(row["org_id"])):
            device = await repo.get_device(db, str(row["id"]))
        if device is None:
            raise HTTPException(status_code=404, detail={"code": "DEVICE_NOT_FOUND", "serial": serial})
        device.relay_serial = serial
        await mark_allocated_unclaimed(
            db,
            device,
            target_org_id=target.id,
            manager_org_id=manager_org_id,
            relay_id=agent.relay_id,
            flush=False,
        )

    await db.flush()
    return await _agent_phone_outs(db, agent, serials)


@router.get(
    "/agents/{relay_id}/phone-allocations",
    response_model=AdminAgentPhoneListOut,
    dependencies=[Depends(require_permission("relay-agents", "read"))],
)
async def admin_list_agent_phones(
    relay_id: str,
    db: DB,
    user: AdminUser,
    search: str | None = None,
    status_: str | None = Query(None, alias="status"),
    assigned_workspace_id: str | None = Query(None, alias="assignedWorkspaceId"),
    offset: int = Query(0, ge=0),
    limit: int = Query(PHONE_LIST_DEFAULT_LIMIT, ge=1, le=PHONE_LIST_MAX_LIMIT),
):
    agent = await _agent_or_404(db, relay_id, user)
    phones, total, safe_offset, safe_limit = await _agent_phone_page(
        db,
        agent,
        search=search,
        status_filter=status_,
        assigned_workspace_id=assigned_workspace_id,
        offset=offset,
        limit=limit,
    )
    return AdminAgentPhoneListOut(
        items=phones,
        total=total,
        offset=safe_offset,
        limit=safe_limit,
    )


@router.post(
    "/agents/{relay_id}/phone-allocations",
    response_model=AdminAgentPhoneAssignOut,
    dependencies=[Depends(require_permission("devices", "manage"))],
)
async def admin_assign_agent_phones(
    relay_id: str,
    body: AdminAgentPhoneAssign,
    request: Request,
    db: DB,
    user: AdminUser,
):
    agent = await _agent_or_404(db, relay_id, user)
    await _require_visible_workspace_scope(db, user, str(agent.org_id))
    serials = _clean_phone_serials(body.serials, agent, require_reported=True)
    phones = await _assign_agent_phone_serials(
        db,
        agent=agent,
        serials=serials,
        target_workspace_id=body.targetWorkspaceId,
        create_missing=True,
    )
    ip, ua = _client_meta(request)
    await emit_security_event(
        db,
        action="device.assigned_from_agent_pool",
        user_id=user.id,
        org_id=body.targetWorkspaceId,
        entity_type="relay_agent",
        entity_id=relay_id,
        ip_address=ip,
        user_agent=ua,
        details={
            "managed_by_workspace_id": agent.org_id,
            "target_workspace_id": body.targetWorkspaceId,
            "serial_count": len(serials),
            "serials": serials,
        },
    )
    await db.commit()
    return AdminAgentPhoneAssignOut(items=phones, total=len(phones))


@router.delete(
    "/agents/{relay_id}/phone-allocations",
    response_model=AdminAgentPhoneAssignOut,
    dependencies=[Depends(require_permission("devices", "manage"))],
)
async def admin_unassign_agent_phones(
    relay_id: str,
    body: AdminAgentPhoneUnassign,
    request: Request,
    db: DB,
    user: AdminUser,
):
    agent = await _agent_or_404(db, relay_id, user)
    await _require_visible_workspace_scope(db, user, str(agent.org_id))
    # A phone the agent no longer reports is exactly the one that most needs
    # releasing, so release resolves the device row instead of the snapshot.
    serials = _clean_phone_serials(body.serials, agent, require_reported=False)
    phones = await _assign_agent_phone_serials(
        db,
        agent=agent,
        serials=serials,
        target_workspace_id=str(agent.org_id),
        create_missing=False,
    )
    ip, ua = _client_meta(request)
    await emit_security_event(
        db,
        action="device.returned_to_agent_pool",
        user_id=user.id,
        org_id=agent.org_id,
        entity_type="relay_agent",
        entity_id=relay_id,
        ip_address=ip,
        user_agent=ua,
        details={
            "managed_by_workspace_id": agent.org_id,
            "serial_count": len(serials),
            "serials": serials,
        },
    )
    await db.commit()
    return AdminAgentPhoneAssignOut(items=phones, total=len(phones))


@router.patch(
    "/agents/{relay_id}",
    response_model=AdminAgentOut,
    dependencies=[Depends(require_permission("relay-agents", "update"))],
)
async def admin_update_agent(
    relay_id: str,
    body: AdminAgentUpdate,
    request: Request,
    db: DB,
    user: AdminUser,
):
    row = await _agent_or_404(db, relay_id, user)
    if body.workspaceId is not None and str(body.workspaceId) != str(row.org_id):
        # The activation code decides the agent's workspace, and
        # `upsert_relay_agent` writes it back from the token on every reconnect,
        # so a move made here would silently revert. Move it by revoking the
        # code and re-enrolling with one minted from the target workspace.
        # Echoing the current value back stays allowed — edit forms do it.
        raise HTTPException(
            status_code=409, detail={"code": "AGENT_WORKSPACE_IS_IMMUTABLE"}
        )
    if body.name is not None:
        row.name = body.name.strip()
    if body.status is not None:
        value = body.status.strip().lower()
        if value not in AGENT_STATUSES:
            raise HTTPException(status_code=400, detail={"code": "INVALID_AGENT_STATUS"})
        row.status = value
        if value == "offline":
            row.disconnected_at = _now()
        # Park or resume the transports in place. `serials` is deliberately kept
        # on the row: it is the serial → agent map the media plane needs, and the
        # only one left once the agent stops reporting.
        if value in {"disabled", "archived"}:
            row.disconnected_at = _now()
            _apply_agent_suspension(
                row.relay_id, list(row.serials or []), suspend=True
            )
        else:
            _apply_agent_suspension(
                row.relay_id, list(row.serials or []), suspend=False
            )
            if str(row.relay_id) in _live_relay_ids():
                # Resuming does not make the agent re-register — that is the
                # point — so nothing else would ever move the row back to
                # online, and health read "stale" on a perfectly live agent.
                row.status = "online"
                row.disconnected_at = None
                row.connected_at = row.connected_at or _now()
                row.last_heartbeat_at = _now()
    ip, ua = _client_meta(request)
    await emit_security_event(
        db,
        action="agent.updated",
        user_id=user.id,
        org_id=row.org_id,
        entity_type="relay_agent",
        entity_id=row.relay_id,
        ip_address=ip,
        user_agent=ua,
        details=body.model_dump(exclude_none=True),
    )
    await db.commit()
    org = await db.get(Organization, row.org_id)
    return _agent_out(
        row,
        org.business_name if org else None,
        workspace_kind=(getattr(org, "kind", None) or "tenant") if org else "tenant",
    )


@router.post(
    "/agents/{relay_id}/disable",
    response_model=AdminAgentOut,
    dependencies=[Depends(require_permission("relay-agents", "manage"))],
)
async def admin_disable_agent(relay_id: str, request: Request, db: DB, user: AdminUser):
    return await admin_update_agent(
        relay_id,
        AdminAgentUpdate(status="disabled"),
        request,
        db,
        user,
    )


@router.post(
    "/agents/{relay_id}/enable",
    response_model=AdminAgentOut,
    dependencies=[Depends(require_permission("relay-agents", "manage"))],
)
async def admin_enable_agent(relay_id: str, request: Request, db: DB, user: AdminUser):
    return await admin_update_agent(
        relay_id,
        AdminAgentUpdate(status="offline"),
        request,
        db,
        user,
    )


@router.delete(
    "/agents/{relay_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("relay-agents", "delete"))],
)
async def admin_delete_agent(relay_id: str, request: Request, db: DB, user: AdminUser):
    row = await _agent_or_404(db, relay_id, user)
    org_id = row.org_id
    await db.delete(row)
    ip, ua = _client_meta(request)
    await emit_security_event(
        db,
        action="agent.deleted",
        user_id=user.id,
        org_id=org_id,
        entity_type="relay_agent",
        entity_id=relay_id,
        ip_address=ip,
        user_agent=ua,
        details={"serial_count": len(row.serials or [])},
    )
    await db.commit()
    return None


def _device_out(
    row: Device,
    workspace_name: str | None = None,
    state: str = "unknown",
    managed_workspace_name: str | None = None,
) -> AdminDeviceOut:
    return AdminDeviceOut(
        id=row.id,
        serial=row.serial,
        device_serial=row.device_serial,
        name=row.name,
        workspaceId=row.org_id,
        workspaceName=workspace_name,
        managedByWorkspaceId=row.managed_by_org_id,
        managedByWorkspaceName=managed_workspace_name,
        user_id=row.user_id,
        brand=row.brand,
        model=row.model,
        android_version=row.android_version,
        adb_serial=row.adb_serial,
        relay_serial=row.relay_serial,
        adb_ip=row.adb_ip,
        adb_port=row.adb_port,
        status=row.status,
        state=state,
        assigned=bool(row.user_id),
        pooled=row.managed_by_org_id is None
        or str(row.org_id) == str(row.managed_by_org_id),
        last_seen=row.last_seen,
        paired_at=row.paired_at,
        unpaired_at=row.unpaired_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _device_out_from_mapping(
    row: Any,
    workspace_name: str | None = None,
    managed_workspace_name: str | None = None,
    transferable: bool = True,
) -> AdminDeviceOut:
    return AdminDeviceOut(
        id=row["id"],
        serial=row["serial"],
        device_serial=row["device_serial"],
        name=row["name"],
        workspaceId=row["org_id"],
        workspaceName=workspace_name,
        managedByWorkspaceId=row["managed_by_org_id"],
        managedByWorkspaceName=managed_workspace_name,
        user_id=row["user_id"],
        brand=row["brand"],
        model=row["model"],
        android_version=row["android_version"],
        adb_serial=row["adb_serial"],
        relay_serial=row["relay_serial"],
        adb_ip=row["adb_ip"],
        adb_port=row["adb_port"],
        status=row["status"],
        state=row["state"] or "unknown",
        assigned=bool(row["user_id"]),
        transferable=transferable,
        pooled=row["managed_by_org_id"] is None
        or str(row["org_id"]) == str(row["managed_by_org_id"]),
        last_seen=row["last_seen"],
        paired_at=row["paired_at"],
        unpaired_at=row["unpaired_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.get(
    "/devices",
    response_model=AdminDeviceListOut,
    dependencies=[Depends(require_permission("devices", "read"))],
)
async def admin_list_devices(
    db: DB,
    user: AdminUser,
    search: str | None = None,
    workspace_id: str | None = Query(None, alias="workspaceId"),
    status_: str | None = Query(None, alias="status"),
    assigned: bool | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    safe_limit = min(max(limit, 1), 100)
    safe_offset = max(offset, 0)
    device_table = Device.__table__
    state_table = DeviceFsmSnapshot.__table__
    stmt = (
        select(
            device_table,
            state_table.c.state.label("state"),
        )
        .select_from(
            device_table.outerjoin(
                state_table,
                state_table.c.device_id == device_table.c.id,
            )
        )
    )
    # A phone a tenant registered on its own relay still belongs in this
    # inventory — it is only not the admin's to move, which `transferable`
    # says per row and the assignment endpoint enforces with a 409.
    if workspace_id:
        visible_ids = await _visible_workspace_ids(db, user, workspace_id)
        stmt = stmt.where(
            or_(
                device_table.c.org_id.in_(visible_ids),
                device_table.c.managed_by_org_id.in_(visible_ids),
            )
        )
    elif not is_superadmin(user):
        visible_ids = await _visible_workspace_ids(db, user)
        stmt = stmt.where(
            or_(
                device_table.c.org_id.in_(visible_ids),
                device_table.c.managed_by_org_id.in_(visible_ids),
            )
        )
    search_clause = _search_filter(
        [
            device_table.c.serial,
            device_table.c.device_serial,
            device_table.c.name,
            device_table.c.model,
            device_table.c.brand,
        ],
        search,
    )
    if search_clause is not None:
        stmt = stmt.where(search_clause)
    if status_:
        stmt = stmt.where(device_table.c.status == status_)
    if assigned is not None:
        stmt = stmt.where(
            device_table.c.user_id.is_not(None)
            if assigned
            else device_table.c.user_id.is_(None)
        )
    total = int(
        (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        or 0
    )
    rows = (
        await db.execute(
            stmt.order_by(device_table.c.created_at.desc())
            .offset(safe_offset)
            .limit(safe_limit)
        )
    ).mappings().all()
    org_ids = {str(row["org_id"]) for row in rows if row["org_id"]}
    org_ids.update(str(row["managed_by_org_id"]) for row in rows if row["managed_by_org_id"])
    orgs = await _workspace_name_map(db, org_ids)
    pool_ids = {
        str(org_id)
        for org_id in (
            await db.execute(
                select(Organization.id)
                .where(Organization.id.in_(org_ids))
                .where(Organization.kind == POOL_WORKSPACE_KIND)
            )
        ).scalars()
    }
    return AdminDeviceListOut(
        items=[
            _device_out_from_mapping(
                row,
                orgs.get(str(row["org_id"])),
                orgs.get(str(row["managed_by_org_id"])) if row["managed_by_org_id"] else None,
                transferable=str(row["managed_by_org_id"] or row["org_id"]) in pool_ids,
            )
            for row in rows
        ],
        total=total,
        offset=safe_offset,
        limit=safe_limit,
    )


@router.put(
    "/devices/{device_id}/assignment",
    response_model=AdminDeviceOut,
    dependencies=[Depends(require_permission("devices", "manage"))],
)
async def admin_transfer_device_workspace(
    device_id: str,
    body: AdminDeviceTransfer,
    request: Request,
    db: DB,
    user: AdminUser,
):
    device = await _managed_device_or_404(db, device_id, user)
    controlling_org_id = device.managed_by_org_id or device.org_id
    await _require_visible_workspace_scope(db, user, str(controlling_org_id))
    manager = await _workspace_by_id_or_404(db, str(controlling_org_id))
    if (getattr(manager, "kind", "tenant") or "tenant") != POOL_WORKSPACE_KIND:
        # Same rule as the list: only pool phones are the admin's to move.
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DEVICE_NOT_IN_POOL_WORKSPACE",
                "workspaceId": str(controlling_org_id),
            },
        )
    target_org_id = body.workspaceId or device.org_id
    target = await _workspace_by_id_or_404(db, target_org_id)
    old_org_id = device.org_id
    if device.managed_by_org_id is None:
        device.managed_by_org_id = controlling_org_id
    requested_user_id = body.userId.strip() if body.userId is not None else None
    clear_user = (old_org_id != target_org_id and body.userId is None) or (
        body.userId is not None and not requested_user_id
    )
    cleanup_counts = await move_device_to_workspace(
        db,
        device,
        target_org_id=target_org_id,
        clear_user=clear_user,
    )
    if body.userId is not None:
        if requested_user_id:
            target_user = await repo.get_user(db, requested_user_id)
            if target_user is None:
                raise HTTPException(status_code=404, detail={"code": "USER_NOT_FOUND"})
            role = await repo.get_organization_role_for_user(db, target_user.id, target_org_id)
            if role is None:
                raise HTTPException(status_code=409, detail={"code": "USER_NOT_IN_WORKSPACE"})
            device.user_id = target_user.id
        else:
            device.user_id = None
    ip, ua = _client_meta(request)
    await emit_security_event(
        db,
        action="device.workspace_transferred",
        user_id=user.id,
        org_id=target_org_id,
        entity_type="device",
        entity_id=device.id,
        ip_address=ip,
        user_agent=ua,
        details={
            "from_workspace_id": old_org_id,
            "to_workspace_id": target_org_id,
            "cleanup": cleanup_counts,
        },
    )
    await db.commit()
    state_row = await db.get(DeviceFsmSnapshot, device.id)
    orgs = await _workspace_name_map(
        db,
        {org_id for org_id in [target_org_id, device.managed_by_org_id] if org_id},
    )
    return _device_out(
        device,
        target.business_name,
        state_row.state if state_row else "unknown",
        orgs.get(str(device.managed_by_org_id)) if device.managed_by_org_id else None,
    )


@router.get(
    "/audit-log",
    response_model=ActivityLogListOut,
    dependencies=[Depends(require_permission("analytics", "read"))],
)
async def admin_audit_log(
    db: DB,
    user: AdminUser,
    action: str | None = None,
    resource_type: str | None = Query(None, alias="resourceType"),
    resource_id: str | None = Query(None, alias="resourceId"),
    workspace_id: str | None = Query(None, alias="workspaceId"),
    actor: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    stmt = select(ActivityLog)
    if workspace_id or not is_superadmin(user):
        visible_ids = await _visible_workspace_ids(db, user, workspace_id)
        stmt = stmt.where(ActivityLog.org_id.in_(visible_ids))
    if action:
        stmt = stmt.where(ActivityLog.action == action)
    if resource_type:
        stmt = stmt.where(ActivityLog.entity_type == resource_type)
    if resource_id:
        stmt = stmt.where(ActivityLog.entity_id == resource_id)
    if actor:
        stmt = stmt.where(ActivityLog.user_id == actor)
    total = int((await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one() or 0)
    rows = (
        await db.execute(
            stmt.order_by(ActivityLog.created_at.desc()).offset(offset).limit(limit)
        )
    ).scalars().all()
    return ActivityLogListOut(
        total=total,
        offset=offset,
        limit=limit,
        activities=[ActivityLogOut.model_validate(row) for row in rows],
    )
