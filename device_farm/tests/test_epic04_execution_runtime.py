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
    _scenario_refs_with_recovery_refs,
    build_runtime_scenario_dict,
    build_sequence_steps,
    prepare_scenario_input,
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
        scenario_config={
            "capture_steps": True,
            "preview_collection": "preview_org1",
            "recovery_policy": {
                "enabled": True,
                "rules": [
                    {
                        "incident_type": "facebook_popup",
                        "scenario_id": "recovery-1",
                    }
                ],
            },
        },
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
    assert scenario["recovery_policy"]["enabled"] is True
    assert scenario["recovery_policy"]["rules"][0]["scenario_id"] == "recovery-1"
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


def test_build_sequence_steps_keeps_device_vars_scoped_per_scenario():
    refs = [{"scenario_id": "s1"}, {"scenario_id": "s2"}]
    steps = build_sequence_steps(
        refs,
        device_index=0,
        effective_vars={"shared": "campaign"},
        account_vars={},
        scenario_device_vars={
            "s1": {"kw": "scenario-one"},
            "s2": {"kw": "scenario-two"},
        },
    )

    assert steps[0]["variables"]["shared"] == "campaign"
    assert steps[0]["variables"]["kw"] == "scenario-one"
    assert steps[1]["variables"]["shared"] == "campaign"
    assert steps[1]["variables"]["kw"] == "scenario-two"


def test_build_sequence_steps_does_not_promote_campaign_globals_to_scenario_overrides():
    refs = [{"scenario_id": "s1"}]
    steps = build_sequence_steps(
        refs,
        device_index=0,
        campaign_vars={
            "GROUP_NAME": "openclaw vn",
            "GROUP_TEXT": "OpenClaw VN",
            "SAVE_COLLECTION": "fb_group_posts",
        },
        effective_vars={
            "GROUP_NAME": "openclaw vn",
            "GROUP_TEXT": "OpenClaw VN",
            "SAVE_COLLECTION": "custom_collection",
            "DEVICE_ONLY": "device-value",
        },
        account_vars={"__ACCOUNT_ID__": "acct-1"},
        scenario_device_vars={"s1": {"GROUP_TEXT": "device text"}},
    )

    step_vars = steps[0]["variables"]
    assert "GROUP_NAME" not in step_vars
    assert step_vars["GROUP_TEXT"] == "device text"
    assert step_vars["SAVE_COLLECTION"] == "custom_collection"
    assert step_vars["DEVICE_ONLY"] == "device-value"
    assert step_vars["__ACCOUNT_ID__"] == "acct-1"


def test_recovery_refs_extend_registry_refs_without_sequence_refs():
    main_refs = [{"scenario_id": "main-1"}]
    registry_refs = _scenario_refs_with_recovery_refs(
        main_refs,
        {
            "enabled": True,
            "rules": [
                {"scenario_id": "recovery-1"},
                {"scenario_id": "main-1"},
                {"scenario_id": ""},
            ],
        },
    )

    assert main_refs == [{"scenario_id": "main-1"}]
    assert registry_refs == [
        {"scenario_id": "main-1"},
        {"scenario_id": "recovery-1"},
    ]


@pytest.mark.asyncio
async def test_prepare_scenario_input_defaults_campaign_capture_to_error_only(session_factory):
    await _seed_orgs(session_factory)
    campaign_id, execution_id = await _seed_campaign_execution(session_factory)

    async with session_factory() as db:
        campaign = await _load_campaign(db, campaign_id)
        execution = await _load_execution(db, execution_id)
        scenario_input = await prepare_scenario_input(
            db,
            execution=execution,
            campaign=campaign,
            org_id=campaign.org_id,
            device_serial="SN1",
            effective_vars={},
            account_vars={},
        )

    assert scenario_input is not None
    assert scenario_input.scenario_config["capture_mode"] == "error_only"


@pytest.mark.asyncio
async def test_prepare_scenario_input_loads_org_scenario_device_vars_per_step(session_factory):
    await _seed_orgs(session_factory)
    campaign_id, execution_id = await _seed_campaign_execution(session_factory)

    from db.models.org_scenario import CampaignOrgScenarioRef, OrgScenario
    from db.models.scenario_device_variable import CampaignOrgScenarioDeviceVariable

    async with session_factory() as db:
        db.add(
            OrgScenario(
                id="sc-2",
                org_id="org-runtime",
                name="WaitTwo",
                name_lower="waittwo",
                body_json={
                    "steps": [{"id": "w2", "type": "input_wait.wait", "config": {"seconds": 1}}]
                },
            )
        )
        db.add(
            CampaignOrgScenarioRef(
                id="ref-2",
                campaign_id=campaign_id,
                org_scenario_id="sc-2",
                order_index=1,
                pinned_version=1,
            )
        )
        db.add(
            CampaignOrgScenarioDeviceVariable(
                campaign_id=campaign_id,
                org_scenario_id="sc-1",
                device_id="dev-1",
                vars={"kw": "s1-device"},
            )
        )
        db.add(
            CampaignOrgScenarioDeviceVariable(
                campaign_id=campaign_id,
                org_scenario_id="sc-2",
                device_id="dev-1",
                vars={"kw": "s2-device"},
            )
        )
        await db.commit()

    async with session_factory() as db:
        campaign = await _load_campaign(db, campaign_id)
        execution = await _load_execution(db, execution_id)
        scenario_input = await prepare_scenario_input(
            db,
            execution=execution,
            campaign=campaign,
            org_id=campaign.org_id,
            device_serial="SN1",
            effective_vars={"kw": "campaign"},
            account_vars={},
            device_id="dev-1",
        )

    assert scenario_input is not None
    assert [step["scenario_id"] for step in scenario_input.steps] == ["sc-1", "sc-2"]
    assert scenario_input.steps[0]["variables"]["kw"] == "s1-device"
    assert scenario_input.steps[1]["variables"]["kw"] == "s2-device"


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
