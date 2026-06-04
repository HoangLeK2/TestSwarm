"""Epic 04 DF-T-04-001: org-scoped scenario library entity + CRUD."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.crud.router import api_router
from api.deps import _get_current_user, _get_db
from db.crud.campaign import create_campaign
from db.crud.org_scenario import add_campaign_scenario_ref
from db.database import Base
from db.models import Organization, User
from db.models.activity import ActivityLog
from db.models.enums import CampaignStatus, OrgScenarioStatus
from tenancy.context import set_current_org_id


ORG_A = "org-scenario-a"
ORG_B = "org-scenario-b"
USER_OWNER = "user-owner"
USER_MEMBER = "user-member"
USER_OTHER = "user-other-org"
NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _clear_rbac_policy_cache():
    from api.auth.rbac import clear_rbac_cache

    clear_rbac_cache()
    yield
    clear_rbac_cache()


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _build_app(session_factory, *, user_id: str = USER_OWNER, org_id: str = ORG_A, org_role: str = "owner"):
    app = FastAPI()
    app.include_router(api_router, prefix="/api")

    async def _db_override():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def _user_override():
        set_current_org_id(org_id)
        return SimpleNamespace(
            id=user_id,
            email=f"{user_id}@example.com",
            name=user_id,
            role="operator",
            org_role=org_role,
            is_active=True,
            org_id=org_id,
        )

    app.dependency_overrides[_get_db] = _db_override
    app.dependency_overrides[_get_current_user] = _user_override
    return app


async def _seed_orgs(session_factory):
    async with session_factory() as db:
        db.add(
            Organization(
                id=ORG_A,
                business_name="Org A",
                business_email="a@org.local",
                status="active",
                plan="standard",
                created_at=NOW,
            )
        )
        db.add(
            Organization(
                id=ORG_B,
                business_name="Org B",
                business_email="b@org.local",
                status="active",
                plan="standard",
                created_at=NOW,
            )
        )
        db.add(
            User(
                id=USER_OWNER,
                email="owner@org.local",
                name="Owner",
                hashed_password="x",
                org_id=ORG_A,
            )
        )
        db.add(
            User(
                id=USER_MEMBER,
                email="member@org.local",
                name="Member",
                hashed_password="x",
                org_id=ORG_A,
            )
        )
        db.add(
            User(
                id=USER_OTHER,
                email="other@org.local",
                name="Other",
                hashed_password="x",
                org_id=ORG_B,
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_create_scenario_success(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/scenarios",
            json={
                "name": "FB-CrawlComments",
                "kind": "sequence",
                "description": "Crawl FB comments",
                "tags": ["facebook", "crawl"],
            },
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "FB-CrawlComments"
    assert data["scenario_version"] == 1
    assert data["status"] == "draft"
    assert data["organization_id"] == ORG_A
    assert "facebook" in data["tags"]

    async with session_factory() as db:
        rows = (
            await db.execute(
                select(ActivityLog).where(ActivityLog.action == "scenario.created")
            )
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].entity_id == data["id"]


@pytest.mark.asyncio
async def test_duplicate_name_case_insensitive(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post(
            "/api/scenarios",
            json={"name": "FB-CrawlComments", "kind": "sequence"},
        )
        assert first.status_code == 201
        second = await client.post(
            "/api/scenarios",
            json={"name": "fb-crawlcomments", "kind": "sequence"},
        )
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "SCENARIO_NAME_DUPLICATE"


@pytest.mark.asyncio
async def test_cross_org_isolation_returns_404(session_factory):
    await _seed_orgs(session_factory)
    owner_app = _build_app(session_factory)
    transport = ASGITransport(app=owner_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/scenarios",
            json={"name": "Secret", "kind": "sequence"},
        )
        scenario_id = created.json()["id"]

    other_app = _build_app(
        session_factory,
        user_id=USER_OTHER,
        org_id=ORG_B,
        org_role="owner",
    )
    transport = ASGITransport(app=other_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/scenarios/{scenario_id}")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "SCENARIO_NOT_FOUND"


@pytest.mark.asyncio
async def test_soft_delete_and_include_archived(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/scenarios",
            json={"name": "ToArchive", "kind": "graph"},
        )
        scenario_id = created.json()["id"]
        deleted = await client.delete(f"/api/scenarios/{scenario_id}")
        assert deleted.status_code == 200
        assert deleted.json()["status"] == "archived"

        listed = await client.get("/api/scenarios")
        assert all(item["id"] != scenario_id for item in listed.json())

        listed_archived = await client.get("/api/scenarios?include_archived=true")
        archived_ids = {item["id"] for item in listed_archived.json()}
        assert scenario_id in archived_ids

        got = await client.get(f"/api/scenarios/{scenario_id}")
        assert got.status_code == 200
        assert got.json()["status"] == "archived"


@pytest.mark.asyncio
async def test_delete_blocked_when_referenced_by_running_campaign(session_factory):
    await _seed_orgs(session_factory)
    set_current_org_id(ORG_A)
    async with session_factory() as db:
        campaign = await create_campaign(db, "RunningCamp", USER_OWNER, org_id=ORG_A)
        campaign.status = CampaignStatus.RUNNING.value
        from services.org_scenario.service import create_scenario

        view = await create_scenario(
            db,
            org_id=ORG_A,
            name="InUse",
            kind="sequence",
            created_by=USER_OWNER,
        )
        await add_campaign_scenario_ref(
            db,
            campaign_id=campaign.id,
            org_scenario_id=view.id,
        )
        await db.commit()
        scenario_id = view.id

    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete(f"/api/scenarios/{scenario_id}")
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["code"] == "SCENARIO_IN_USE"
    assert detail["referenced_by"][0]["campaign_id"]

    async with session_factory() as db:
        from db.crud.org_scenario import get_org_scenario

        row = await get_org_scenario(db, scenario_id)
        assert row is not None
        assert row.status != OrgScenarioStatus.ARCHIVED.value


@pytest.mark.asyncio
async def test_member_cannot_create_scenario(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory, user_id=USER_MEMBER, org_role="member")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/scenarios",
            json={"name": "Denied", "kind": "sequence"},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_body_save_bumps_scenario_version(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/scenarios",
            json={"name": "Versioned", "kind": "sequence"},
        )
        scenario_id = created.json()["id"]
        assert created.json()["scenario_version"] == 1

        saved = await client.post(
            f"/api/scenarios/{scenario_id}/body",
            json={
                "steps": [
                    {"id": "wait1", "type": "input_wait.wait", "config": {"seconds": 1}},
                ]
            },
        )
    assert saved.status_code == 200
    assert saved.json()["scenario_version"] == 2

    async with session_factory() as db:
        updated_rows = (
            await db.execute(
                select(ActivityLog).where(ActivityLog.action == "scenario.updated")
            )
        ).scalars().all()
    assert len(updated_rows) >= 1


@pytest.mark.asyncio
async def test_patch_rejects_body_json(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/scenarios",
            json={"name": "NoPatchBody", "kind": "sequence"},
        )
        scenario_id = created.json()["id"]
        patched = await client.patch(
            f"/api/scenarios/{scenario_id}",
            json={"body_json": {"steps": []}},
        )
    assert patched.status_code == 422
    assert patched.json()["detail"]["code"] == "USE_BODY_ENDPOINT"


@pytest.mark.asyncio
async def test_concurrent_create_same_name_only_one_succeeds(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)

    async def _attempt(client: AsyncClient):
        return await client.post(
            "/api/scenarios",
            json={"name": "RaceName", "kind": "sequence"},
        )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        results = await asyncio.gather(*[_attempt(client) for _ in range(10)])
    ok = [r for r in results if r.status_code == 201]
    dup = [r for r in results if r.status_code == 409]
    assert len(ok) == 1
    assert len(dup) == 9
