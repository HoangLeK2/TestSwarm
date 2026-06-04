"""Epic 04 DF-T-04-010: execution runtime (Temporal + fallback)."""
from __future__ import annotations

import pytest

pytest_plugins = ["tests.test_epic04_scenario_entity"]

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.campaign.dispatcher import FanOutExecutionView, FanOutResult
from services.campaign.execution_runtime import (
    DISPATCH_SOURCE_FALLBACK,
    DISPATCH_SOURCE_TEMPORAL,
    build_runtime_scenario_dict,
    build_sequence_steps,
    start_execution_runtime,
    workflow_id_for_execution,
)


def test_workflow_id_for_execution():
    assert workflow_id_for_execution("abc-123") == "exec_abc-123"


def test_build_runtime_scenario_dict_includes_execution_capture_context():
    from temporal.shared import ScenarioInput

    inp = ScenarioInput(
        campaign_id="",
        device_serial="SN1",
        steps=[{"type": "extract", "strategy": "fb_posts"}],
        variables={"kw": "x"},
        campaign_vars={"__USER_ID__": "u1", "__ORG_ID__": "org1"},
        capture_steps=True,
        scenario_config={"capture_steps": True, "preview_collection": "preview_org1"},
        execution_id="exec-99",
        run_id="exec-99",
    )
    scenario = build_runtime_scenario_dict(
        inp,
        "exec-99",
        org_id="org1",
        scenario_name="FB Group Crawl",
    )
    assert scenario["execution_id"] == "exec-99"
    assert scenario["_execution_id"] == "exec-99"
    assert scenario["_run_hash_scope"] == "exec-99"
    assert scenario["capture_steps"] is True
    assert scenario["_campaign_vars"]["__ORG_ID__"] == "org1"
    assert scenario["preview_collection"] == "preview_org1"
    assert scenario["scenario_name"] == "FB Group Crawl"


def test_build_sequence_steps_run_scenario_chain():
    refs = [{"scenario_id": "s1"}, {"scenario_id": "s2"}]
    steps = build_sequence_steps(
        refs,
        device_index=1,
        effective_vars={"kw": "x"},
        account_vars={"__ACCOUNT_ID__": "a1"},
    )
    assert len(steps) == 2
    assert steps[0]["type"] == "run_scenario"
    assert steps[0]["scenario_id"] == "s1"
    assert steps[0]["variables"]["DEVICE_INDEX"] == "1"
    assert steps[0]["variables"]["__ACCOUNT_ID__"] == "a1"


@pytest.mark.asyncio
async def test_start_runtime_uses_temporal_when_available(session_factory):
    await _seed_orgs(session_factory)
    campaign_id, execution_id = await _seed_campaign_execution(session_factory)

    fan_out = FanOutResult(
        dispatch_id="d1",
        campaign_id=campaign_id,
        dispatch_strategy="parallel",
        executions=[
            FanOutExecutionView(
                execution_id=execution_id,
                device_id="dev-1",
                status="running",
                effective_vars={"kw": "v"},
            )
        ],
    )

    temporal_client = SimpleNamespace(start_workflow=AsyncMock())
    temporal_config = SimpleNamespace(enabled=True, task_queue="device-scenario")

    with patch(
        "services.campaign.execution_runtime.prepare_scenario_input",
        new=AsyncMock(
            return_value=SimpleNamespace(
                device_serial="SN1",
                steps=[{"type": "run_scenario", "scenario_id": "sc1"}],
            )
        ),
    ):
        from tenancy.context import set_current_org_id

        set_current_org_id("org-runtime")
        async with session_factory() as db:
            campaign = await _load_campaign(db, campaign_id)
            stats = await start_execution_runtime(
                db,
                fan_out=fan_out,
                campaign=campaign,
                org_id=campaign.org_id,
                actor_user_id="user-owner",
                temporal_client=temporal_client,
                temporal_config=temporal_config,
                manager=None,
            )
            execution = await _load_execution(db, execution_id)

    assert stats["temporal"] == 1
    assert stats["fallback"] == 0
    temporal_client.start_workflow.assert_awaited_once()
    assert execution.meta.get("dispatch_source") == DISPATCH_SOURCE_TEMPORAL
    assert execution.meta.get("workflow_id") == workflow_id_for_execution(execution.id)


@pytest.mark.asyncio
async def test_start_runtime_fallback_when_temporal_disabled(session_factory):
    await _seed_orgs(session_factory)
    campaign_id, execution_id = await _seed_campaign_execution(session_factory)

    fan_out = FanOutResult(
        dispatch_id="d2",
        campaign_id=campaign_id,
        dispatch_strategy="parallel",
        executions=[
            FanOutExecutionView(
                execution_id=execution_id,
                device_id="dev-1",
                status="running",
                effective_vars={},
            )
        ],
    )

    scenario_input = SimpleNamespace(device_serial="SN1", steps=[])

    with patch(
        "services.campaign.execution_runtime.prepare_scenario_input",
        new=AsyncMock(return_value=scenario_input),
    ), patch(
        "services.campaign.execution_runtime.schedule_fallback_runtime",
    ) as schedule_mock:
        from tenancy.context import set_current_org_id

        set_current_org_id("org-runtime")
        async with session_factory() as db:
            campaign = await _load_campaign(db, campaign_id)
            stats = await start_execution_runtime(
                db,
                fan_out=fan_out,
                campaign=campaign,
                org_id=campaign.org_id,
                actor_user_id="user-owner",
                temporal_client=None,
                temporal_config=SimpleNamespace(enabled=False),
                manager=MagicMock(),
            )
            execution = await _load_execution(db, execution_id)

    assert stats["fallback"] == 1
    assert execution.meta.get("dispatch_source") == DISPATCH_SOURCE_FALLBACK
    schedule_mock.assert_called_once()


async def _seed_orgs(session_factory):
    from datetime import datetime, timezone

    from db.models import Organization, User

    NOW = datetime.now(timezone.utc)
    async with session_factory() as db:
        db.add(
            Organization(
                id="org-runtime",
                business_name="Runtime Org",
                business_email="r@org.local",
                status="active",
                plan="standard",
                created_at=NOW,
            )
        )
        db.add(
            User(
                id="user-owner",
                email="owner@org.local",
                name="Owner",
                hashed_password="x",
                org_id="org-runtime",
            )
        )
        await db.commit()


async def _seed_campaign_execution(session_factory):
    from datetime import datetime, timezone

    from db.crud.execution import add_device_to_execution, create_execution
    from db.models.campaign import Campaign
    from db.models.org_scenario import CampaignOrgScenarioRef, OrgScenario
    from db.models.device import Device

    NOW = datetime.now(timezone.utc)
    async with session_factory() as db:
        db.add(
            OrgScenario(
                id="sc-1",
                org_id="org-runtime",
                name="Wait",
                name_lower="wait",
                body_json={
                    "steps": [{"id": "w", "type": "input_wait.wait", "config": {"seconds": 1}}]
                },
            )
        )
        campaign = Campaign(
            id="camp-runtime-1",
            org_id="org-runtime",
            name="Runtime Camp",
            name_lower="runtime camp",
            description="",
            status="running",
            user_id="user-owner",
            created_by="user-owner",
            variables={"kw": "global"},
            created_at=NOW,
            updated_at=NOW,
        )
        db.add(campaign)
        db.add(
            CampaignOrgScenarioRef(
                id="ref-1",
                campaign_id=campaign.id,
                org_scenario_id="sc-1",
                order_index=0,
                pinned_version=1,
            )
        )
        device = Device(
            id="dev-1",
            serial="SN1",
            user_id="user-owner",
            org_id="org-runtime",
        )
        db.add(device)
        execution = await create_execution(
            db,
            run_type="campaign_device",
            campaign_id=campaign.id,
            user_id="user-owner",
            status="running",
            device_config={"effective_vars": {"kw": "v"}, "device_serial": "SN1"},
            meta={"dispatch_id": "d1", "dispatch_strategy": "parallel"},
        )
        await add_device_to_execution(db, execution.id, device.id)
        await db.commit()
        return campaign.id, execution.id


async def _load_campaign(db, campaign_id: str):
    from db.crud import campaign_entity as campaign_entity_repo

    campaign = await campaign_entity_repo.get_campaign_entity(db, campaign_id)
    assert campaign is not None
    return campaign


async def _load_execution(db, execution_id: str):
    from db.crud.execution import get_execution

    execution = await get_execution(db, execution_id)
    assert execution is not None
    return execution
