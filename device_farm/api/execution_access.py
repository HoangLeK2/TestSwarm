"""Org-scoped access checks for execution records (multi-tenancy)."""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from db import crud as repo
from db.crud.campaign import get_campaign
from db.crud.execution import get_execution
from db.models.execution import Execution
from db.models.user import User
from api.org_scope import org_member_user_ids
from tenancy.enforce import enforce_tenant


async def get_execution_for_user(
    db: AsyncSession,
    execution_id: str,
    user: User,
) -> Execution:
    """Return execution if visible to user's org (404 if missing or cross-tenant)."""
    ex = await get_execution(db, execution_id)
    if ex is None:
        raise HTTPException(status_code=404, detail="Execution not found")

    user_org = getattr(user, "org_id", None) or await repo.get_user_org_id(db, user.id)

    if ex.campaign_id:
        campaign = await get_campaign(db, ex.campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="Execution not found")
        if user_org and campaign.org_id != user_org:
            raise HTTPException(status_code=404, detail="Execution not found")
        return ex

    if user_org:
        member_ids = await org_member_user_ids(db, user_org)
        if ex.user_id and str(ex.user_id) in member_ids:
            return ex
        raise HTTPException(status_code=404, detail="Execution not found")
    if ex.user_id != user.id:
        raise HTTPException(status_code=404, detail="Execution not found")
    return ex


async def get_campaign_for_user(
    db: AsyncSession,
    campaign_id: str,
    user: User,
):
    """Same visibility rules as campaigns router."""
    campaign = await repo.get_campaign(db, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    user_org = getattr(user, "org_id", None) or await repo.get_user_org_id(db, user.id)
    if user_org and campaign.org_id != user_org:
        raise HTTPException(status_code=404, detail="Campaign not found")
    enforce_tenant(campaign, user)
    return campaign
