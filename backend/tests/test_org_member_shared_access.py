"""Org members should see shared org resources, not only rows they created."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from tests.tenancy_test_support import (
    build_tenancy_api_app,
    api_client_for_user,
)


ORG_TEAM = "org-team"
USER_OWNER = "user-owner"
USER_MEMBER = "user-member"


async def _seed_team_org(session_factory) -> None:
    from db.models import Organization, OrganizationMember, User
    from db.models.campaign import Campaign
    from db.models.device import Device
    from db.models.device_group import DeviceGroup

    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        session.add(
            Organization(
                id=ORG_TEAM,
                business_name="Acme Team",
                business_email="team@acme.example",
                status="active",
                plan="standard",
                created_at=now,
            )
        )
        owner = User(
            id=USER_OWNER,
            email="owner@acme.example",
            name="Owner",
            hashed_password="hashed",
            org_id=ORG_TEAM,
        )
        member = User(
            id=USER_MEMBER,
            email="member@acme.example",
            name="Member",
            hashed_password="hashed",
            org_id=ORG_TEAM,
        )
        session.add_all([owner, member])
        await session.flush()
        session.add_all(
            [
                OrganizationMember(
                    id="mem-owner",
                    organization_id=ORG_TEAM,
                    user_id=USER_OWNER,
                    role="owner",
                    created_at=now,
                ),
                OrganizationMember(
                    id="mem-member",
                    organization_id=ORG_TEAM,
                    user_id=USER_MEMBER,
                    role="member",
                    created_at=now,
                ),
            ]
        )
        session.add(
            Device(
                id="dev-1",
                serial="TEAM-1",
                name="Team phone",
                user_id=USER_OWNER,
                org_id=ORG_TEAM,
                created_at=now,
            )
        )
        session.add(
            Campaign(
                id="camp-1",
                name="Team campaign",
                user_id=USER_OWNER,
                org_id=ORG_TEAM,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            DeviceGroup(
                id="grp-1",
                name="Team group",
                user_id=USER_OWNER,
                org_id=ORG_TEAM,
                created_at=now,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_org_member_sees_owner_devices_campaigns_groups(tenancy_session_factory):
    app = build_tenancy_api_app(tenancy_session_factory)
    await _seed_team_org(tenancy_session_factory)

    async with api_client_for_user(app, USER_MEMBER, ORG_TEAM) as client:
        devices = await client.get("/api/devices")
        assert devices.status_code == 200, devices.text
        assert {d["serial"] for d in devices.json()} == {"TEAM-1"}

        campaigns = await client.get("/api/campaigns")
        assert campaigns.status_code == 200, campaigns.text
        assert {c["name"] for c in campaigns.json()} == {"Team campaign"}

        groups = await client.get("/api/device-groups")
        assert groups.status_code == 200, groups.text
        assert {g["name"] for g in groups.json()} == {"Team group"}

        devices_get = await client.get("/api/devices/dev-1")
        assert devices_get.status_code == 200, devices_get.text
        assert devices_get.json()["serial"] == "TEAM-1"
