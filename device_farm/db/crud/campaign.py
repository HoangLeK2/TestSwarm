from __future__ import annotations

from typing import Optional

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Campaign, CampaignDevice, Device, Scenario


async def create_campaign(
    db: AsyncSession,
    name: str,
    user_id: str,
    description: str = "",
    scenario: dict | None = None,
    variables: dict | None = None,
    target_group_id: str | None = None,
) -> Campaign:
    campaign = Campaign(
        name=name,
        user_id=user_id,
        description=description,
        scenario=scenario or {},
        variables=variables or {},
        target_group_id=target_group_id,
    )
    db.add(campaign)
    await db.flush()
    return campaign


async def get_campaign(db: AsyncSession, campaign_id: str) -> Optional[Campaign]:
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    return result.scalar_one_or_none()


async def list_campaigns(db: AsyncSession, user_id: Optional[str] = None) -> list[Campaign]:
    q = select(Campaign).order_by(Campaign.created_at.desc())
    if user_id:
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
) -> Scenario:
    s = Scenario(
        campaign_id=campaign_id,
        name=name,
        instructions=instructions,
        steps=steps or [],
        variables=variables or {},
        order=order,
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

