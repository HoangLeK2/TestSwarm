"""The reaper's queries must survive TENANCY_STRICT_MODE.

The first deployed version of this worker failed on every single iteration with
`TENANCY_STRICT_MODE: attempted tenant-scoped SELECT without current_org_id`,
and the only sign was an ERROR line in the container log — the loop swallowed it
and slept, so nothing was ever reaped and the fleet stayed stuck. Mock-based
tests could not catch it: the guard is a SQLAlchemy ORM event, so it only fires
against a real session. These run against one.

Campaign is tenant-scoped; Execution and Organization are not. That asymmetry is
the whole reason the sweep is per-org, and it is what these tests pin.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.database import Base
from db.models import Organization
from db.models.campaign import Campaign
from db.models.execution import Execution
from services.campaign.orphan_execution_reaper import (
    _list_executions_with_open_results,
    _list_org_ids,
    _list_stale_continuous_crawls,
    _list_stale_executions,
)
from tenancy.context import use_tenant_scope
from tenancy.sqlalchemy import init_tenant_scoping

ORG = "org-reaper"
OTHER_ORG = "org-other"


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    # The guard is installed process-wide by the app; make sure it is on here
    # too, otherwise this file would pass while production still raises.
    os.environ["TENANCY_STRICT_MODE"] = "true"
    init_tenant_scoping()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as db:
        db.add_all(
            [
                Organization(
                    id=ORG,
                    business_name="Reaper Org",
                    status="active",
                    plan="standard",
                ),
                Organization(
                    id=OTHER_ORG,
                    business_name="Other Org",
                    status="active",
                    plan="standard",
                ),
            ]
        )
        await db.commit()
        yield db
    await engine.dispose()


async def _add_crawl_campaign(
    db: AsyncSession, *, campaign_id: str, org_id: str, active: bool
) -> None:
    db.add(
        Campaign(
            id=campaign_id,
            org_id=org_id,
            name=campaign_id,
            status="running",
            variables={
                "_continuous_crawl": {
                    "active": active,
                    "dispatch_id": "disp-1",
                    "workflow_id": f"campaign:{campaign_id}:crawl:disp-1",
                }
            },
        )
    )
    await db.commit()


@pytest.mark.asyncio
async def test_org_enumeration_needs_no_tenant_scope(session):
    """Organization is the tenant, not a tenant-scoped row — safe to sweep."""
    assert sorted(await _list_org_ids(session)) == sorted([ORG, OTHER_ORG])


@pytest.mark.asyncio
async def test_stale_execution_sweep_needs_no_tenant_scope(session):
    """Execution is not tenant-scoped; the global sweep must not raise."""
    old = datetime.now(timezone.utc) - timedelta(hours=1)
    session.add(
        Execution(
            id="exec-old",
            run_type="campaign_run",
            kind="campaign",
            status="running",
            org_id=ORG,
            created_at=old,
            started_at=old,
        )
    )
    await session.commit()

    rows = await _list_stale_executions(
        session, cutoff=datetime.now(timezone.utc) - timedelta(minutes=5), limit=10
    )

    assert [row.id for row in rows] == ["exec-old"]


@pytest.mark.asyncio
async def test_open_result_rows_of_a_finished_execution_are_found(session):
    """The row the run-stats spinner reads, left behind by a finished execution."""
    from db.models.execution import ExecutionResult

    now = datetime.now(timezone.utc)
    session.add_all(
        [
            Execution(
                id="exec-done",
                run_type="campaign_run",
                kind="campaign",
                status="failed",
                org_id=ORG,
                started_at=now,
                finished_at=now,
            ),
            Execution(
                id="exec-live",
                run_type="campaign_run",
                kind="campaign",
                status="running",
                org_id=ORG,
                started_at=now,
            ),
        ]
    )
    session.add_all(
        [
            ExecutionResult(
                id="er-ghost",
                org_id=ORG,
                execution_id="exec-done",
                device_id="dev-1",
                status="running",
            ),
            ExecutionResult(
                id="er-live",
                org_id=ORG,
                execution_id="exec-live",
                device_id="dev-2",
                status="running",
            ),
        ]
    )
    await session.commit()

    rows = await _list_executions_with_open_results(session, limit=10)

    # An execution that is still running owns its open row — leave it be.
    assert rows == [("exec-done", "failed")]


@pytest.mark.asyncio
async def test_crawl_sweep_raises_without_tenant_scope(session):
    """Pins the failure the first deployment hit, so it cannot come back quietly."""
    await _add_crawl_campaign(session, campaign_id="camp-1", org_id=ORG, active=True)

    with pytest.raises(RuntimeError, match="TENANCY_STRICT_MODE"):
        await _list_stale_continuous_crawls(session, org_id=ORG, limit=10)


@pytest.mark.asyncio
async def test_crawl_sweep_works_inside_tenant_scope(session):
    await _add_crawl_campaign(session, campaign_id="camp-1", org_id=ORG, active=True)

    with use_tenant_scope(ORG):
        rows = await _list_stale_continuous_crawls(session, org_id=ORG, limit=10)

    assert [row.id for row in rows] == ["camp-1"]


@pytest.mark.asyncio
async def test_finished_crawl_is_not_a_candidate(session):
    """`active: false` means the root workflow already finalized — leave it."""
    await _add_crawl_campaign(session, campaign_id="camp-done", org_id=ORG, active=False)

    with use_tenant_scope(ORG):
        rows = await _list_stale_continuous_crawls(session, org_id=ORG, limit=10)

    assert rows == []


@pytest.mark.asyncio
async def test_sweep_of_one_org_never_returns_another_orgs_campaign(session):
    await _add_crawl_campaign(session, campaign_id="camp-mine", org_id=ORG, active=True)
    await _add_crawl_campaign(
        session, campaign_id="camp-theirs", org_id=OTHER_ORG, active=True
    )

    with use_tenant_scope(ORG):
        rows = await _list_stale_continuous_crawls(session, org_id=ORG, limit=10)

    assert [row.id for row in rows] == ["camp-mine"]
