"""Epic 04 DF-T-04-008: campaign device binding & fan-out."""
from __future__ import annotations

import pytest

pytest_plugins = ["tests.test_epic04_scenario_entity"]

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from db.crud import campaign_entity as campaign_repo
from db.crud.device import create_device
from db.crud.device_group import add_devices_to_group, create_group
from db.crud.device_reserve_session import get_active_session
from db.models.campaign import CampaignTarget
from db.models.enums import CampaignStatus, DeviceFsmEvent
from db.models.execution import Execution
from services.campaign.dispatcher import dispatch_campaign
from services.campaign.override_resolver import merge_effective_vars
from services.device_reserve.service import claim_device_session
from services.device_state.service import DeviceStateService
from services.scenario_dsl.variable_resolver import EffectiveVariableResolver
from tenancy.context import set_current_org_id
from tests.test_epic04_scenario_entity import (
    ORG_A,
    ORG_B,
    USER_OWNER,
    _build_app,
    _seed_orgs,
)


def _sequence_step(step_id: str, step_type: str, **config):
    return {"id": step_id, "type": step_type, "config": config}


async def _create_org_scenario(client, *, name: str) -> str:
    created = await client.post(
        "/api/scenarios",
        json={"name": name, "kind": "sequence"},
    )
    scenario_id = created.json()["id"]
    await client.post(
        f"/api/scenarios/{scenario_id}/body",
        json={"steps": [_sequence_step("w", "input_wait.wait", seconds=1)]},
    )
    return scenario_id


async def _create_campaign(client, *, name: str = "FanOutCampaign", **extra) -> str:
    scenario_id = await _create_org_scenario(client, name=f"{name}-scenario")
    payload = {
        "name": name,
        "scenario_refs": [{"scenario_id": scenario_id}],
        "vars": extra.pop("vars", {"kw": "global"}),
        **extra,
    }
    resp = await client.post("/api/campaigns", json=payload)
    assert resp.status_code == 201
    return resp.json()["id"]


async def _online_device(session_factory, *, org_id: str = ORG_A, serial: str) -> str:
    set_current_org_id(org_id)
    svc = DeviceStateService()
    async with session_factory() as db:
        device = await create_device(db, serial, user_id=USER_OWNER, org_id=org_id)
        device.device_serial = serial
        device.adb_serial = f"{serial}:5555"
        await db.flush()
        await svc.apply_event(
            db, device.id, event=DeviceFsmEvent.ATTACHED.value, source="agent", event_id=f"{serial}-1"
        )
        await svc.apply_event(
            db, device.id, event=DeviceFsmEvent.ONLINE.value, source="agent", event_id=f"{serial}-2"
        )
        await db.commit()
        return device.id


async def _offline_device(session_factory, *, org_id: str = ORG_A, serial: str) -> str:
    set_current_org_id(org_id)
    async with session_factory() as db:
        device = await create_device(db, serial, user_id=USER_OWNER, org_id=org_id)
        device.device_serial = serial
        await db.commit()
        return device.id


async def _device_group(session_factory, device_ids: list[str], *, org_id: str = ORG_A) -> str:
    set_current_org_id(org_id)
    async with session_factory() as db:
        group = await create_group(db, "Fleet-A", user_id=USER_OWNER, org_id=org_id)
        if device_ids:
            await add_devices_to_group(db, group.id, device_ids, org_id=org_id)
        await db.commit()
        return group.id


@pytest.mark.asyncio
async def test_ac1_fan_out_by_device_ids(session_factory):
    await _seed_orgs(session_factory)
    d1 = await _online_device(session_factory, serial="D1")
    d2 = await _online_device(session_factory, serial="D2")
    d3 = await _online_device(session_factory, serial="D3")

    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        campaign_id = await _create_campaign(client)
        resp = await client.post(
            f"/api/campaigns/{campaign_id}/dispatch",
            json={"target": {"device_ids": [d1, d2, d3]}},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["target_count"] == 3
    assert len(data["executions"]) == 3
    device_ids = {item["device_id"] for item in data["executions"]}
    assert device_ids == {d1, d2, d3}

    async with session_factory() as db:
        row = await campaign_repo.get_campaign_entity(db, campaign_id)
        assert row.status == CampaignStatus.RUNNING.value
        for device_id in [d1, d2, d3]:
            session = await get_active_session(db, device_id)
            assert session is not None
            assert session.owner_type == "campaign"
            assert session.owner_id == campaign_id


@pytest.mark.asyncio
async def test_ac2_fan_out_by_device_group_snapshot(session_factory):
    await _seed_orgs(session_factory)
    d1 = await _online_device(session_factory, serial="G-D1")
    d2 = await _online_device(session_factory, serial="G-D2")
    group_id = await _device_group(session_factory, [d1, d2])

    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        campaign_id = await _create_campaign(client, name="GroupCampaign")
        resp = await client.post(
            f"/api/campaigns/{campaign_id}/dispatch",
            json={"target": {"device_group_ids": [group_id]}},
        )
        assert resp.status_code == 200
        dispatch_id = resp.json()["dispatch_id"]

        d3 = await _online_device(session_factory, serial="G-D3")
        async with session_factory() as db:
            await add_devices_to_group(db, group_id, [d3], org_id=ORG_A)
            await db.commit()

        # FSM (DF-T-04-007) blocks a second dispatch while the same campaign is running.
        # AC-2 "next dispatch sees D3" means a new dispatch after group membership changed —
        # use a fresh campaign to snapshot the expanded group without double-dispatch.
        campaign_id_2 = await _create_campaign(client, name="GroupCampaign-2")
        resp2 = await client.post(
            f"/api/campaigns/{campaign_id_2}/dispatch",
            json={"target": {"device_group_ids": [group_id]}},
        )
        assert resp2.status_code == 200
        assert resp2.json()["target_count"] == 3
        device_ids_wave2 = {item["device_id"] for item in resp2.json()["executions"]}
        assert device_ids_wave2 == {d1, d2, d3}

    async with session_factory() as db:
        first_targets = (
            await db.execute(
                select(CampaignTarget.device_id).where(CampaignTarget.dispatch_id == dispatch_id)
            )
        ).scalars().all()
        assert set(first_targets) == {d1, d2}


@pytest.mark.asyncio
async def test_ac3_per_device_override_resolve(session_factory):
    await _seed_orgs(session_factory)
    d1 = await _online_device(session_factory, serial="O-D1")
    d2 = await _online_device(session_factory, serial="O-D2")

    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        campaign_id = await _create_campaign(client, name="OverrideCampaign", vars={"kw": "global"})
        await client.patch(
            f"/api/campaigns/{campaign_id}",
            json={"per_device_overrides": {d1: {"kw": "d1-kw"}}},
        )
        resp = await client.post(
            f"/api/campaigns/{campaign_id}/dispatch?include_vars=true",
            json={"target": {"device_ids": [d1, d2]}},
        )

    assert resp.status_code == 200
    by_device = {item["device_id"]: item["effective_vars"] for item in resp.json()["executions"]}
    assert by_device[d1]["kw"] == "d1-kw"
    assert by_device[d2]["kw"] == "global"

    resolver_d1 = EffectiveVariableResolver.for_campaign_device(
        campaign_vars={"kw": "global"},
        per_device_overrides={d1: {"kw": "d1-kw"}},
        device_id=d1,
    )
    assert resolver_d1.resolve("${kw}") == "d1-kw"


@pytest.mark.asyncio
async def test_ac4_reject_empty_target(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        campaign_id = await _create_campaign(client, name="EmptyTarget")
        resp = await client.post(
            f"/api/campaigns/{campaign_id}/dispatch",
            json={"target": {"device_ids": []}},
        )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "EMPTY_DISPATCH_TARGET"

    async with session_factory() as db:
        row = await campaign_repo.get_campaign_entity(db, campaign_id)
        assert row.status == CampaignStatus.DRAFT.value


@pytest.mark.asyncio
async def test_ac5_device_offline_strict_reject(session_factory):
    await _seed_orgs(session_factory)
    d1 = await _online_device(session_factory, serial="ON-D1")
    d2 = await _offline_device(session_factory, serial="OFF-D2")

    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        campaign_id = await _create_campaign(client, name="OfflineStrict")
        resp = await client.post(
            f"/api/campaigns/{campaign_id}/dispatch",
            json={
                "target": {"device_ids": [d1, d2]},
                "require_online": True,
                "allow_partial": False,
            },
        )

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "DEVICE_OFFLINE"
    assert d2 in detail["device_ids"]


@pytest.mark.asyncio
async def test_ac5_allow_partial_offline(session_factory):
    await _seed_orgs(session_factory)
    d1 = await _online_device(session_factory, serial="P-D1")
    d2 = await _offline_device(session_factory, serial="P-D2")

    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        campaign_id = await _create_campaign(client, name="PartialDispatch")
        resp = await client.post(
            f"/api/campaigns/{campaign_id}/dispatch",
            json={
                "target": {"device_ids": [d1, d2]},
                "allow_partial": True,
            },
        )

    assert resp.status_code == 200
    assert resp.json()["target_count"] == 1
    assert resp.json()["executions"][0]["device_id"] == d1


@pytest.mark.asyncio
async def test_ac6_device_claim_fail(session_factory):
    await _seed_orgs(session_factory)
    d1 = await _online_device(session_factory, serial="C-D1")
    d2 = await _online_device(session_factory, serial="C-D2")

    set_current_org_id(ORG_A)
    async with session_factory() as db:
        await claim_device_session(
            db,
            device_id=d1,
            org_id=ORG_A,
            actor_user_id=USER_OWNER,
            owner_type="manual",
            owner_id="other-campaign",
        )
        await db.commit()

    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        campaign_id = await _create_campaign(client, name="ClaimFail")
        resp = await client.post(
            f"/api/campaigns/{campaign_id}/dispatch",
            json={"target": {"device_ids": [d1, d2]}},
        )

    assert resp.status_code == 200
    by_device = {item["device_id"]: item for item in resp.json()["executions"]}
    assert by_device[d1]["status"] == "failed"
    assert by_device[d1]["failure_reason"] == "device_claim_failed"
    assert by_device[d2]["status"] == "running"


@pytest.mark.asyncio
async def test_single_busy_device_dispatch_marks_campaign_failed(session_factory):
    await _seed_orgs(session_factory)
    d1 = await _online_device(session_factory, serial="BUSY-D1")

    set_current_org_id(ORG_A)
    async with session_factory() as db:
        await claim_device_session(
            db,
            device_id=d1,
            org_id=ORG_A,
            actor_user_id=USER_OWNER,
            owner_type="manual",
            owner_id="other-campaign",
        )
        await db.commit()

    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        campaign_id = await _create_campaign(client, name="AllClaimFail")
        resp = await client.post(
            f"/api/campaigns/{campaign_id}/dispatch",
            json={"target": {"device_ids": [d1]}},
        )

    assert resp.status_code == 200
    execution = resp.json()["executions"][0]
    assert execution["status"] == "failed"
    assert execution["failure_reason"] == "device_claim_failed"

    async with session_factory() as db:
        row = await campaign_repo.get_campaign_entity(db, campaign_id)
    assert row.status == CampaignStatus.FAILED.value


@pytest.mark.asyncio
async def test_sequential_dispatch_promotes_next_device_when_first_claim_fails(session_factory):
    await _seed_orgs(session_factory)
    d1 = await _online_device(session_factory, serial="SEQ-BUSY-D1")
    d2 = await _online_device(session_factory, serial="SEQ-BUSY-D2")

    set_current_org_id(ORG_A)
    async with session_factory() as db:
        await claim_device_session(
            db,
            device_id=d1,
            org_id=ORG_A,
            actor_user_id=USER_OWNER,
            owner_type="manual",
            owner_id="other-campaign",
        )
        await db.commit()

    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        campaign_id = await _create_campaign(client, name="SequentialPromote")
        resp = await client.post(
            f"/api/campaigns/{campaign_id}/dispatch",
            json={
                "target": {"device_ids": [d1, d2]},
                "dispatch_strategy": "sequential",
            },
        )

    assert resp.status_code == 200
    by_device = {item["device_id"]: item for item in resp.json()["executions"]}
    assert by_device[d1]["status"] == "failed"
    assert by_device[d1]["failure_reason"] == "device_claim_failed"
    assert by_device[d2]["status"] == "running"

    async with session_factory() as db:
        row = await campaign_repo.get_campaign_entity(db, campaign_id)
        session = await get_active_session(db, d2)
    assert row.status == CampaignStatus.RUNNING.value
    assert session is not None
    assert session.owner_id == campaign_id


@pytest.mark.asyncio
async def test_ac7_cross_org_device_reject(session_factory):
    await _seed_orgs(session_factory)
    d5 = await _online_device(session_factory, org_id=ORG_B, serial="ORG-B-D5")

    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        campaign_id = await _create_campaign(client, name="CrossOrg")
        resp = await client.post(
            f"/api/campaigns/{campaign_id}/dispatch",
            json={"target": {"device_ids": [d5]}},
        )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "DEVICE_NOT_FOUND"


@pytest.mark.asyncio
async def test_merge_effective_vars_unit():
    assert merge_effective_vars(
        campaign_vars={"kw": "global", "x": 1},
        per_device_overrides={"d1": {"kw": "d1-kw"}},
        device_id="d1",
    ) == {"kw": "d1-kw", "x": 1}
    assert merge_effective_vars(
        campaign_vars={"kw": "global"},
        per_device_overrides={"d1": {"kw": "d1-kw"}},
        device_id="d2",
    ) == {"kw": "global"}


@pytest.mark.asyncio
async def test_empty_device_group_rejected(session_factory):
    await _seed_orgs(session_factory)
    group_id = await _device_group(session_factory, [])

    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        campaign_id = await _create_campaign(client, name="EmptyGroup")
        resp = await client.post(
            f"/api/campaigns/{campaign_id}/dispatch",
            json={"target": {"device_group_ids": [group_id]}},
        )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "EMPTY_DISPATCH_TARGET"


@pytest.mark.asyncio
async def test_dispatch_rejected_when_campaign_running(session_factory):
    await _seed_orgs(session_factory)
    d1 = await _online_device(session_factory, serial="R-D1")

    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        campaign_id = await _create_campaign(client, name="DoubleDispatch")
        first = await client.post(
            f"/api/campaigns/{campaign_id}/dispatch",
            json={"target": {"device_ids": [d1]}},
        )
        assert first.status_code == 200

        second = await client.post(
            f"/api/campaigns/{campaign_id}/dispatch",
            json={"target": {"device_ids": [d1]}},
        )

    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "CAMPAIGN_ALREADY_RUNNING"


@pytest.mark.asyncio
async def test_dispatch_slim_response_omits_vars_by_default(session_factory):
    await _seed_orgs(session_factory)
    d1 = await _online_device(session_factory, serial="S-D1")

    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        campaign_id = await _create_campaign(client, name="SlimResponse")
        resp = await client.post(
            f"/api/campaigns/{campaign_id}/dispatch",
            json={"target": {"device_ids": [d1]}},
        )

    assert resp.status_code == 200
    item = resp.json()["executions"][0]
    assert item["execution_id"]
    assert item["device_id"] == d1
    assert item.get("effective_vars") in (None, {})


@pytest.mark.asyncio
async def test_dispatch_target_limit(session_factory, monkeypatch):
    await _seed_orgs(session_factory)
    monkeypatch.setattr(
        "services.campaign.dispatcher.MAX_DISPATCH_TARGETS",
        2,
    )
    d1 = await _online_device(session_factory, serial="L-D1")
    d2 = await _online_device(session_factory, serial="L-D2")
    d3 = await _online_device(session_factory, serial="L-D3")

    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        campaign_id = await _create_campaign(client, name="LimitCampaign")
        resp = await client.post(
            f"/api/campaigns/{campaign_id}/dispatch",
            json={"target": {"device_ids": [d1, d2, d3]}},
        )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "DISPATCH_TARGET_TOO_LARGE"


@pytest.mark.asyncio
async def test_dispatch_creates_execution_records(session_factory):
    await _seed_orgs(session_factory)
    d1 = await _online_device(session_factory, serial="E-D1")

    set_current_org_id(ORG_A)
    async with session_factory() as db:
        campaign = await campaign_repo.create_campaign_entity(
            db,
            org_id=ORG_A,
            name="DirectDispatch",
            variables={"kw": "g"},
            created_by=USER_OWNER,
        )
        await db.commit()
        campaign_id = campaign.id

        result = await dispatch_campaign(
            db,
            campaign_id=campaign_id,
            org_id=ORG_A,
            actor_user_id=USER_OWNER,
            device_ids=[d1],
        )
        await db.commit()

    assert len(result.executions) == 1
    async with session_factory() as db:
        count = (
            await db.execute(select(func.count()).select_from(Execution))
        ).scalar_one()
        assert count == 1
