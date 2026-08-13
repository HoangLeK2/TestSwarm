from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.crud.execution import create_execution
from db.crud.execution_steps import upsert_execution_step
from db.database import Base
from db.models import Account, Campaign, Device, ExecutionDevice, Organization, User
from db.models.execution_dlq import ExecutionDLQ
from db.crud.execution_events import insert_execution_event
from services.execution.event_publisher import enqueue_execution_event
from services.execution_trace import build_campaign_monitor, build_execution_task_log
from tenancy.context import tenant_context


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    finally:
        await engine.dispose()


async def _seed_trace_fixture(session_factory) -> str:
    now = datetime.now(timezone.utc)
    async with session_factory() as db:
        with tenant_context("org-trace"):
            db.add(Organization(id="org-trace", business_name="Trace Org"))
            db.add(
                User(
                    id="user-trace",
                    email="trace@example.com",
                    name="Trace User",
                    hashed_password="x",
                    default_org_id="org-trace",
                )
            )
            db.add(
                Campaign(
                    id="camp-trace",
                    name="Trace Campaign",
                    name_lower="trace campaign",
                    user_id="user-trace",
                    org_id="org-trace",
                    created_at=now,
                )
            )
            device = Device(
                id="dev-trace",
                org_id="org-trace",
                serial="phone-001",
                name="Pixel 8",
                status="paired",
            )
            account = Account(
                id="acc-trace",
                org_id="org-trace",
                platform="facebook",
                username="fb-user@example.com",
                display_name="FB Trace",
            )
            db.add_all([device, account])
            execution = await create_execution(
                db,
                run_type="campaign_device",
                campaign_id="camp-trace",
                device_config={"device_serial": "fallback-phone"},
                meta={"workflow_id": "exec_trace_workflow"},
                user_id="user-trace",
                account_id=account.id,
                status="running",
                org_id="org-trace",
            )
            db.add(ExecutionDevice(execution_id=execution.id, device_id=device.id))
            await upsert_execution_step(
                db,
                execution_id=execution.id,
                org_id="org-trace",
                device_id=device.id,
                step_index=0,
                step_id="open-feed",
                step_type="open_app",
                status="completed",
                message="opened",
            )
            await upsert_execution_step(
                db,
                execution_id=execution.id,
                org_id="org-trace",
                device_id=device.id,
                step_index=1,
                step_id="like-post",
                step_type="social_like",
                status="running",
                effective_config_json={"result": {"counters": {"liked": 1}}},
                message="liking",
            )
            await enqueue_execution_event(
                db,
                event_type="step.completed",
                execution_id=execution.id,
                organization_id="org-trace",
                campaign_id="camp-trace",
                step_id="like-post",
                payload={
                    "step_index": 1,
                    "step_type": "social_like",
                    "action": "liked",
                    "message": "liked",
                },
                execution=execution,
            )
            db.add(
                ExecutionDLQ(
                    org_id="org-trace",
                    execution_id=execution.id,
                    device_serial=device.serial,
                    error="selector timeout",
                    status="pending",
                    failed_step_id="like-post",
                    failure_reason="timeout",
                    failed_at=now,
                    campaign_id="camp-trace",
                )
            )
            execution_id = execution.id
        await db.commit()
    return execution_id


@pytest.mark.asyncio
async def test_execution_task_log_enriches_phone_account_and_steps(session_factory):
    execution_id = await _seed_trace_fixture(session_factory)

    async with session_factory() as db:
        trace = await build_execution_task_log(db, execution_id, event_limit=50)

    assert trace["execution_id"] == execution_id
    assert trace["context"]["device_serial"] == "phone-001"
    assert trace["context"]["device_name"] == "Pixel 8"
    assert trace["context"]["account_label"] == "FB Trace"
    assert trace["context"]["account_platform"] == "facebook"
    assert trace["summary"]["total_steps"] == 2
    assert trace["summary"]["completed_steps"] == 1
    assert trace["summary"]["running_steps"] == 1
    assert trace["summary"]["counters"]["liked"] == 1
    assert trace["events"][0]["payload"]["context"]["device_serial"] == "phone-001"
    assert trace["events"][0]["payload"]["context"]["account_label"] == "FB Trace"
    assert trace["dlq"]["failed_step_id"] == "like-post"


@pytest.mark.asyncio
async def test_campaign_monitor_uses_batched_execution_snapshot(session_factory):
    execution_id = await _seed_trace_fixture(session_factory)

    async with session_factory() as db:
        snapshot = await build_campaign_monitor(db, "camp-trace", limit=20)

    assert snapshot["campaign_id"] == "camp-trace"
    assert snapshot["total"] == 1
    row = snapshot["executions"][0]
    assert row["execution_id"] == execution_id
    assert row["context"]["device_serial"] == "phone-001"
    assert row["context"]["account_label"] == "FB Trace"
    assert row["summary"]["total_steps"] == 2
    assert row["summary"]["running_steps"] == 1
    assert row["current_step_type"] == "social_like"


@pytest.mark.asyncio
async def test_execution_task_log_detects_more_events_at_500_limit(session_factory):
    execution_id = await _seed_trace_fixture(session_factory)

    async with session_factory() as db:
        for index in range(500):
            await insert_execution_event(
                db,
                event_type="step.completed",
                organization_id="org-trace",
                campaign_id="camp-trace",
                execution_id=execution_id,
                payload={"step_index": index + 2, "step_type": "noop"},
            )
            await upsert_execution_step(
                db,
                execution_id=execution_id,
                org_id="org-trace",
                step_index=index + 2,
                step_id=f"noop-{index}",
                step_type="noop",
                status="completed",
            )
        await db.commit()

    async with session_factory() as db:
        trace = await build_execution_task_log(db, execution_id, event_limit=500)

    assert len(trace["events"]) == 500
    assert trace["has_more_events"] is True
    assert trace["events"][0]["payload"]["step_index"] == 2
    assert trace["events"][-1]["payload"]["step_index"] == 501
    assert len(trace["steps"]) == 500
    assert trace["has_more_steps"] is True
    assert trace["summary"]["total_steps"] == 502
