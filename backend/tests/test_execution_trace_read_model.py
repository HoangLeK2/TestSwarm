from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.crud.execution import create_execution
from db.crud.execution_steps import upsert_execution_step
from db.database import Base
from db.models import Account, Campaign, Device, ExecutionDevice, Organization, User
from db.models.account_action import AccountAction
from db.models.execution_dlq import ExecutionDLQ
from db.crud.execution_events import insert_execution_event
from services.execution.event_publisher import enqueue_execution_event
from services.execution_trace import (
    _actions_for_step,
    _build_account_action_index,
    build_campaign_monitor,
    build_execution_task_log,
)
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
                platform="instagram",
                username="platform-user@example.com",
                display_name="FB Trace",
            )
            db.add_all([device, account])
            execution = await create_execution(
                db,
                run_type="campaign_device",
                campaign_id="camp-trace",
                device_config={"device_serial": "fallback-phone"},
                meta={
                    "workflow_id": "exec_trace_workflow",
                    "dispatch_id": "dispatch-trace",
                    "scenario_plan": [{"scenario_id": "scenario-trace", "repeat_count": 1}],
                },
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
                effective_config_json={
                    "trace": {
                        "scenario_id": "scenario-trace",
                        "scenario_name": "Fanpage Warmup",
                        "device_serial": device.serial,
                        "account_id": account.id,
                        "action": {
                            "account_action_id": "action-like-1",
                            "outcome": "applied",
                            "action_performed": True,
                        },
                    },
                    "result": {"counters": {"liked": 1}},
                },
                message="liking",
            )
            db.add(
                AccountAction(
                    id="action-like-1",
                    org_id="org-trace",
                    account_id=account.id,
                    execution_id=execution.id,
                    step_id="like-post",
                    action_key="trace-like-1",
                    action_type="like",
                    platform="instagram",
                    status="succeeded",
                    status_rank=4,
                    target={"target_type": "post", "target_id": "post-1", "display_name": "Trace Post"},
                    result={"outcome": "applied", "action_performed": True},
                    started_at=now,
                    completed_at=now,
                    last_transition_at=now,
                    created_at=now,
                    updated_at=now,
                )
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
    assert trace["context"]["dispatch_id"] == "dispatch-trace"
    assert trace["context"]["scenario_plan"][0]["scenario_id"] == "scenario-trace"
    assert trace["context"]["device_name"] == "Pixel 8"
    assert trace["context"]["account_label"] == "FB Trace"
    assert trace["context"]["account_platform"] == "instagram"
    assert trace["summary"]["total_steps"] == 2
    assert trace["summary"]["completed_steps"] == 1
    assert trace["summary"]["running_steps"] == 1
    assert trace["summary"]["counters"]["liked"] == 1
    assert trace["events"][0]["payload"]["context"]["device_serial"] == "phone-001"
    assert trace["events"][0]["payload"]["context"]["account_label"] == "FB Trace"
    assert trace["steps"][1]["trace"]["scenario_name"] == "Fanpage Warmup"
    assert trace["steps"][1]["account_actions"][0]["id"] == "action-like-1"
    assert trace["account_actions"][0]["id"] == "action-like-1"
    assert trace["account_actions"][0]["target"]["display_name"] == "Trace Post"
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


def test_account_action_step_lookup_is_indexed_for_large_task_logs():
    actions = [
        SimpleNamespace(
            id=f"action-{index}",
            org_id="org-trace",
            account_id="acc-trace",
            execution_id="exec-trace",
            step_id=f"step-{index}",
            action_key=f"key-{index}",
            action_type="like",
            platform="instagram",
            status="succeeded",
            target={},
            result={},
            artifact_refs=[],
            started_at=None,
            completed_at=None,
            last_transition_at=None,
            created_at=None,
            updated_at=None,
        )
        for index in range(2000)
    ]
    steps = [
        SimpleNamespace(step_id=f"step-{index}")
        for index in range(2000)
    ]
    action_index = _build_account_action_index(actions)

    started = perf_counter()
    total = sum(
        len(_actions_for_step(step, action_index, {}))
        for step in steps
    )
    elapsed_ms = (perf_counter() - started) * 1000

    assert total == 2000
    assert elapsed_ms < 50
