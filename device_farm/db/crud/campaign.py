from __future__ import annotations

from typing import Optional

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Campaign, CampaignDevice, Device, Scenario


async def create_campaign(
    db: AsyncSession,
    name: str,
    user_id: str,
    org_id: str | None = None,
    description: str = "",
    variables: dict | None = None,
    target_group_id: str | None = None,
) -> Campaign:
    campaign = Campaign(
        name=name,
        user_id=user_id,
        org_id=org_id,  # type: ignore[arg-type]
        description=description,
        variables=variables or {},
        target_group_id=target_group_id,
    )
    db.add(campaign)
    await db.flush()
    return campaign


async def get_campaign_by_name(
    db: AsyncSession,
    *,
    org_id: str,
    name: str,
) -> Optional[Campaign]:
    result = await db.execute(
        select(Campaign)
        .where(Campaign.org_id == org_id, Campaign.name == name)
        .order_by(Campaign.created_at.desc())
        .limit(1)
    )
    return result.scalars().first()


async def get_campaign(db: AsyncSession, campaign_id: str) -> Optional[Campaign]:
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    return result.scalar_one_or_none()


async def list_campaigns(
    db: AsyncSession, *, org_id: Optional[str] = None, user_id: Optional[str] = None
) -> list[Campaign]:
    q = select(Campaign).order_by(Campaign.created_at.desc())
    if org_id:
        q = q.where(Campaign.org_id == org_id)
    elif user_id:
        q = q.where(Campaign.user_id == user_id)
    result = await db.execute(q)
    return list(result.scalars().all())


async def update_campaign_status(db: AsyncSession, campaign_id: str, status: str) -> None:
    await db.execute(
        update(Campaign).where(Campaign.id == campaign_id).values(status=status)
    )


async def add_device_to_campaign(
    db: AsyncSession, campaign_id: str, device_id: str
) -> CampaignDevice:
    cd = CampaignDevice(campaign_id=campaign_id, device_id=device_id)
    db.add(cd)
    await db.flush()
    return cd


async def remove_device_from_campaign(
    db: AsyncSession, campaign_id: str, device_id: str
) -> None:
    await db.execute(
        delete(CampaignDevice).where(
            CampaignDevice.campaign_id == campaign_id,
            CampaignDevice.device_id == device_id,
        )
    )


async def list_campaign_devices(db: AsyncSession, campaign_id: str) -> list[Device]:
    result = await db.execute(
        select(Device)
        .join(CampaignDevice, CampaignDevice.device_id == Device.id)
        .where(CampaignDevice.campaign_id == campaign_id)
    )
    return list(result.scalars().all())


# ── Scenario CRUD ──────────────────────────────────────────────────────────────

async def create_scenario(
    db: AsyncSession,
    campaign_id: str,
    name: str = "Scenario",
    instructions: str = "",
    steps: list | None = None,
    variables: dict | None = None,
    order: int = 0,
    account_group_id: str | None = None,
) -> Scenario:
    s = Scenario(
        campaign_id=campaign_id,
        name=name,
        instructions=instructions,
        steps=steps or [],
        variables=variables or {},
        order=order,
        account_group_id=account_group_id or None,
    )
    db.add(s)
    await db.flush()
    return s


async def list_scenarios(db: AsyncSession, campaign_id: str) -> list[Scenario]:
    result = await db.execute(
        select(Scenario)
        .where(Scenario.campaign_id == campaign_id)
        .order_by(Scenario.order)
    )
    return list(result.scalars().all())


async def get_scenario(db: AsyncSession, scenario_id: str) -> Scenario | None:
    result = await db.execute(select(Scenario).where(Scenario.id == scenario_id))
    return result.scalar_one_or_none()


async def update_scenario(db: AsyncSession, scenario_id: str, **kwargs) -> None:
    await db.execute(update(Scenario).where(Scenario.id == scenario_id).values(**kwargs))


async def delete_scenario(db: AsyncSession, scenario_id: str) -> None:
    await db.execute(delete(Scenario).where(Scenario.id == scenario_id))


async def reorder_scenarios(
    db: AsyncSession, campaign_id: str, ordered_ids: list[str]
) -> list[Scenario]:
    existing = await list_scenarios(db, campaign_id)
    existing_ids = {s.id for s in existing}
    if len(ordered_ids) != len(existing_ids) or set(ordered_ids) != existing_ids:
        raise ValueError("ordered_ids must contain exactly the campaign's scenario ids")
    for idx, sid in enumerate(ordered_ids):
        await db.execute(
            update(Scenario).where(Scenario.id == sid).values(order=idx)
        )
    return await list_scenarios(db, campaign_id)

