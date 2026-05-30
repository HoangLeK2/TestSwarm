"""Cross-tenant smoke tests (DF-T-01-004 AC-1, AC-2, AC-5).

Creates two organizations with sample resources and verifies list/get isolation.
"""

from __future__ import annotations

import pytest

from tests.tenancy_test_support import (
    ORG_A,
    USER_A,
    USER_B,
    build_tenancy_api_app,
    api_client_for_user,
    seed_two_org_fixture,
)


@pytest.mark.asyncio
async def test_ac1_list_devices_only_own_org(tenancy_session_factory):
    app = build_tenancy_api_app(tenancy_session_factory)
    await seed_two_org_fixture(tenancy_session_factory)

    async with api_client_for_user(app, USER_A, ORG_A) as client:
        resp = await client.get("/api/devices")
        assert resp.status_code == 200, resp.text
        serials = {d["serial"] for d in resp.json()}
        assert len(serials) == 5
        assert all(s.startswith("ACME-") for s in serials)
        assert not any(s.startswith("BETA-") for s in serials)


@pytest.mark.asyncio
async def test_ac2_get_device_other_org_returns_404(tenancy_session_factory):
    app = build_tenancy_api_app(tenancy_session_factory)
    fx = await seed_two_org_fixture(tenancy_session_factory)

    async with api_client_for_user(app, USER_A, ORG_A) as client:
        resp = await client.get(f"/api/devices/{fx['device_b_first']}")
        assert resp.status_code == 404
        assert resp.json().get("detail") == "Device not found"


@pytest.mark.asyncio
async def test_ac1_list_campaigns_only_own_org(tenancy_session_factory):
    app = build_tenancy_api_app(tenancy_session_factory)
    await seed_two_org_fixture(tenancy_session_factory)

    async with api_client_for_user(app, USER_A, ORG_A) as client:
        resp = await client.get("/api/campaigns")
        assert resp.status_code == 200, resp.text
        names = {c["name"] for c in resp.json()}
        assert names == {"Acme campaign"}


@pytest.mark.asyncio
async def test_ac2_get_campaign_other_org_returns_404(tenancy_session_factory):
    app = build_tenancy_api_app(tenancy_session_factory)
    fx = await seed_two_org_fixture(tenancy_session_factory)

    async with api_client_for_user(app, USER_A, ORG_A) as client:
        resp = await client.get(f"/api/campaigns/{fx['campaign_b']}")
        assert resp.status_code == 404
        assert resp.json().get("detail") == "Campaign not found"


@pytest.mark.asyncio
async def test_ac5_bob_sees_only_beta_devices(tenancy_session_factory):
    app = build_tenancy_api_app(tenancy_session_factory)
    await seed_two_org_fixture(tenancy_session_factory)

    async with api_client_for_user(app, USER_B, "org-beta") as client:
        resp = await client.get("/api/devices")
        assert resp.status_code == 200
        assert len(resp.json()) == 3
        assert {d["serial"] for d in resp.json()} == {"BETA-1", "BETA-2", "BETA-3"}
