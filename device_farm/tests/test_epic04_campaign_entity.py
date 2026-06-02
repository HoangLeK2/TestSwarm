"""Epic 04 DF-T-04-006: org-scoped campaign entity + CRUD."""
from __future__ import annotations

import pytest

pytest_plugins = ["tests.test_epic04_scenario_entity"]

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from db.crud import campaign_entity as campaign_repo
from db.models.campaign import Campaign
from db.models.enums import CampaignStatus
from db.models.activity import ActivityLog
from tests.test_epic04_scenario_entity import (
    ORG_A,
    ORG_B,
    USER_OWNER,
    USER_OTHER,
    _build_app,
    _seed_orgs,
)


def _sequence_step(step_id: str, step_type: str, **config):
    return {
        "id": step_id,
        "type": step_type,
        "config": config,
    }


async def _create_org_scenario(client, *, name: str, steps: list | None = None) -> str:
    created = await client.post(
        "/api/scenarios",
        json={"name": name, "kind": "sequence"},
    )
    scenario_id = created.json()["id"]
    if steps:
        await client.post(
            f"/api/scenarios/{scenario_id}/body",
            json={"steps": steps},
        )
    return scenario_id


async def _count_campaigns(session_factory, org_id: str) -> int:
    async with session_factory() as db:
        result = await db.execute(
            select(func.count()).select_from(Campaign).where(Campaign.org_id == org_id)
        )
        return int(result.scalar_one())


@pytest.mark.asyncio
async def test_ac1_create_campaign_pins_current_versions(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        s1 = await _create_org_scenario(
            client,
            name="S1",
            steps=[_sequence_step("w", "input_wait.wait", seconds=1)],
        )
        s2 = await _create_org_scenario(
            client,
            name="S2",
            steps=[_sequence_step("w2", "input_wait.wait", seconds=2)],
        )
        v1 = (await client.get(f"/api/scenarios/{s1}")).json()["scenario_version"]
        v2 = (await client.get(f"/api/scenarios/{s2}")).json()["scenario_version"]

        resp = await client.post(
            "/api/campaigns",
            json={
                "name": "FridayCrawl",
                "scenario_refs": [{"scenario_id": s1}, {"scenario_id": s2}],
                "vars": {"kw": "news"},
            },
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "draft"
    assert data["vars"] == {"kw": "news"}
    refs = {r["scenario_id"]: r["scenario_version"] for r in data["scenario_refs"]}
    assert refs[s1] == v1
    assert refs[s2] == v2

    async with session_factory() as db:
        events = (
            await db.execute(
                select(func.count())
                .select_from(ActivityLog)
                .where(ActivityLog.action == "campaign.created")
            )
        ).scalar_one()
    assert events >= 1


@pytest.mark.asyncio
async def test_ac2_explicit_pin_version(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        s1 = await _create_org_scenario(
            client,
            name="VersionedS1",
            steps=[_sequence_step("w", "input_wait.wait", seconds=1)],
        )
        current = (await client.get(f"/api/scenarios/{s1}")).json()["scenario_version"]
        assert current >= 1
        pinned = max(1, current - 1)

        resp = await client.post(
            "/api/campaigns",
            json={
                "name": "PinnedCampaign",
                "scenario_refs": [{"scenario_id": s1, "scenario_version": pinned}],
            },
        )
    assert resp.status_code == 201
    assert resp.json()["scenario_refs"][0]["scenario_version"] == pinned


@pytest.mark.asyncio
async def test_ac3_cross_org_scenario_rejected(session_factory):
    await _seed_orgs(session_factory)
    app_b = _build_app(session_factory, org_id=ORG_B, user_id=USER_OTHER)
    transport_b = ASGITransport(app=app_b)
    async with AsyncClient(transport=transport_b, base_url="http://test") as client_b:
        foreign = await _create_org_scenario(
            client_b,
            name="OrgBScenario",
            steps=[_sequence_step("w", "input_wait.wait", seconds=1)],
        )

    app_a = _build_app(session_factory)
    transport_a = ASGITransport(app=app_a)
    async with AsyncClient(transport=transport_a, base_url="http://test") as client_a:
        before = await _count_campaigns(session_factory, ORG_A)
        resp = await client_a.post(
            "/api/campaigns",
            json={
                "name": "CrossOrg",
                "scenario_refs": [{"scenario_id": foreign}],
            },
        )
        after = await _count_campaigns(session_factory, ORG_A)
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "SCENARIO_NOT_FOUND"
    assert after == before


@pytest.mark.asyncio
async def test_ac4_delete_running_campaign_rejected(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        s1 = await _create_org_scenario(
            client,
            name="RunS",
            steps=[_sequence_step("w", "input_wait.wait", seconds=1)],
        )
        created = await client.post(
            "/api/campaigns",
            json={"name": "RunningC", "scenario_refs": [{"scenario_id": s1}]},
        )
        campaign_id = created.json()["id"]
        async with session_factory() as db:
            row = await campaign_repo.get_campaign_entity(db, campaign_id)
            row.status = CampaignStatus.RUNNING.value
            await db.commit()

        deleted = await client.delete(f"/api/campaigns/{campaign_id}")
    assert deleted.status_code == 409
    assert deleted.json()["detail"]["code"] == "CAMPAIGN_RUNNING"


@pytest.mark.asyncio
async def test_ac5_invalid_pinned_version(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        s1 = await _create_org_scenario(
            client,
            name="BadPin",
            steps=[_sequence_step("w", "input_wait.wait", seconds=1)],
        )
        resp = await client.post(
            "/api/campaigns",
            json={
                "name": "BadVersion",
                "scenario_refs": [{"scenario_id": s1, "scenario_version": 99}],
            },
        )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "SCENARIO_VERSION_NOT_FOUND"


@pytest.mark.asyncio
async def test_create_campaign_requires_scenario_refs(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/campaigns",
            json={"name": "NoScenario", "scenario_refs": []},
        )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "SCENARIO_REQUIRED"


@pytest.mark.asyncio
async def test_duplicate_name_case_insensitive(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        s1 = await _create_org_scenario(
            client,
            name="DupRef",
            steps=[_sequence_step("w", "input_wait.wait", seconds=1)],
        )
        first = await client.post(
            "/api/campaigns",
            json={"name": "Friday", "scenario_refs": [{"scenario_id": s1}]},
        )
        second = await client.post(
            "/api/campaigns",
            json={"name": "friday", "scenario_refs": [{"scenario_id": s1}]},
        )
    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "CAMPAIGN_NAME_DUPLICATE"


@pytest.mark.asyncio
async def test_patch_vars_without_version_change(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        s1 = await _create_org_scenario(
            client,
            name="PatchRef",
            steps=[_sequence_step("w", "input_wait.wait", seconds=1)],
        )
        created = await client.post(
            "/api/campaigns",
            json={"name": "PatchMe", "scenario_refs": [{"scenario_id": s1}], "vars": {"a": 1}},
        )
        campaign_id = created.json()["id"]
        refs_before = created.json()["scenario_refs"]
        patched = await client.patch(
            f"/api/campaigns/{campaign_id}",
            json={"vars": {"a": 2, "b": "x"}},
        )
    assert patched.status_code == 200
    assert patched.json()["vars"] == {"a": 2, "b": "x"}
    assert patched.json()["scenario_refs"] == refs_before


@pytest.mark.asyncio
async def test_archive_draft_campaign(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        s1 = await _create_org_scenario(
            client,
            name="ArchiveRef",
            steps=[_sequence_step("w", "input_wait.wait", seconds=1)],
        )
        created = await client.post(
            "/api/campaigns",
            json={"name": "ToArchive", "scenario_refs": [{"scenario_id": s1}]},
        )
        campaign_id = created.json()["id"]
        deleted = await client.delete(f"/api/campaigns/{campaign_id}")
        listed = await client.get("/api/campaigns")
        listed_archived = await client.get("/api/campaigns?include_archived=true")
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "archived"
    assert campaign_id not in {item["id"] for item in listed.json()}
    assert campaign_id in {item["id"] for item in listed_archived.json()}
