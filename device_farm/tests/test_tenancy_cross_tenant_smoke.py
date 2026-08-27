"""Cross-tenant smoke tests (DF-T-01-004 AC-1, AC-2, AC-5).

Creates two organizations with sample resources and verifies list/get isolation.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

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
async def test_list_campaigns_searches_name_and_description_within_org(
    tenancy_session_factory,
):
    app = build_tenancy_api_app(tenancy_session_factory)
    await seed_two_org_fixture(tenancy_session_factory)

    async with tenancy_session_factory() as session:
        from db.models.campaign import Campaign

        await session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS casbin_policy_revision "
                "(id INTEGER PRIMARY KEY, revision INTEGER NOT NULL)"
            )
        )
        await session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS casbin_rule ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, ptype VARCHAR(32) NOT NULL, "
                "v0 VARCHAR(255), v1 VARCHAR(255), v2 VARCHAR(255), "
                "v3 VARCHAR(255), v4 VARCHAR(255), v5 VARCHAR(255))"
            )
        )
        await session.execute(
            text(
                "INSERT INTO casbin_policy_revision (id, revision) VALUES (1, 1) "
                "ON CONFLICT(id) DO NOTHING"
            )
        )
        from api.auth.rbac import _load_seed_policy_rows

        for row in _load_seed_policy_rows():
            await session.execute(
                text(
                    "INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, v4, v5) "
                    "VALUES (:ptype, :v0, :v1, :v2, :v3, :v4, :v5)"
                ),
                {
                    "ptype": row[0],
                    "v0": row[1],
                    "v1": row[2],
                    "v2": row[3],
                    "v3": row[4],
                    "v4": row[5],
                    "v5": row[6],
                },
            )
        session.add(
            Campaign(
                id="campaign-acme-description-match",
                name="Nightly checks",
                name_lower="nightly checks",
                description="Verify Facebook login flow",
                user_id=USER_A,
                org_id=ORG_A,
                status="draft",
            )
        )
        await session.commit()

    async with api_client_for_user(app, USER_A, ORG_A) as client:
        by_name = await client.get("/api/campaigns", params={"search": "ACME"})
        by_description = await client.get(
            "/api/campaigns", params={"search": "facebook LOGIN"}
        )
        wildcard = await client.get("/api/campaigns", params={"search": "%"})

    assert {item["name"] for item in by_name.json()} == {"Acme campaign"}
    assert {item["name"] for item in by_description.json()} == {"Nightly checks"}
    assert wildcard.json() == []


@pytest.mark.asyncio
async def test_campaign_page_returns_total_and_requested_slice(tenancy_session_factory):
    app = build_tenancy_api_app(tenancy_session_factory)
    await seed_two_org_fixture(tenancy_session_factory)

    async with tenancy_session_factory() as session:
        from db.models.campaign import Campaign

        for index in range(12):
            session.add(
                Campaign(
                    id=f"campaign-page-{index}",
                    name=f"Paged campaign {index:02d}",
                    name_lower=f"paged campaign {index:02d}",
                    description="pagination fixture",
                    user_id=USER_A,
                    org_id=ORG_A,
                    status="draft",
                )
            )
        await session.commit()

    async with api_client_for_user(app, USER_A, ORG_A) as client:
        response = await client.get(
            "/api/campaigns/page",
            params={"search": "Paged campaign", "limit": 5, "offset": 5},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 12
    assert len(payload["items"]) == 5


@pytest.mark.asyncio
async def test_ac2_get_campaign_other_org_returns_404(tenancy_session_factory):
    app = build_tenancy_api_app(tenancy_session_factory)
    fx = await seed_two_org_fixture(tenancy_session_factory)

    async with api_client_for_user(app, USER_A, ORG_A) as client:
        resp = await client.get(f"/api/campaigns/{fx['campaign_b']}")
        assert resp.status_code == 404
        assert resp.json().get("detail") == "Campaign not found"


@pytest.mark.asyncio
async def test_ac2_get_account_other_org_returns_404(tenancy_session_factory):
    from db.models.account import Account

    app = build_tenancy_api_app(tenancy_session_factory)
    fx = await seed_two_org_fixture(tenancy_session_factory)
    async with tenancy_session_factory() as session:
        session.add(
            Account(
                id="acct-beta-1",
                platform="facebook",
                username="beta_user",
                user_id=fx["user_b"],
                org_id=fx["org_b"],
            )
        )
        await session.commit()

    async with api_client_for_user(app, USER_A, ORG_A) as client:
        resp = await client.get("/api/accounts/acct-beta-1")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_ac5_bob_sees_only_beta_devices(tenancy_session_factory):
    app = build_tenancy_api_app(tenancy_session_factory)
    await seed_two_org_fixture(tenancy_session_factory)

    async with api_client_for_user(app, USER_B, "org-beta") as client:
        resp = await client.get("/api/devices")
        assert resp.status_code == 200
        assert len(resp.json()) == 3
        assert {d["serial"] for d in resp.json()} == {"BETA-1", "BETA-2", "BETA-3"}
