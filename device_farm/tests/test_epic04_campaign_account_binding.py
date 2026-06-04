"""Epic 04 DF-T-04-009: campaign account binding & no-implicit-account guard."""
from __future__ import annotations

import pytest

pytest_plugins = ["tests.test_epic04_scenario_entity"]

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from db.crud.account import assign_account_to_device, create_account
from db.crud.account_group import add_members, create_group
from db.crud.device import create_device
from db.models.activity import ActivityLog
from db.models.enums import AccountState, DeviceFsmEvent
from db.models.execution import Execution
from services.campaign.account_resolver import scenario_requires_account
from services.device_state.service import DeviceStateService
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


async def _create_org_scenario(client, *, name: str, steps: list | None = None) -> str:
    created = await client.post(
        "/api/scenarios",
        json={"name": name, "kind": "sequence"},
    )
    scenario_id = created.json()["id"]
    body_steps = steps or [_sequence_step("w", "input_wait.wait", seconds=1)]
    await client.post(
        f"/api/scenarios/{scenario_id}/body",
        json={"steps": body_steps},
    )
    return scenario_id


async def _create_campaign(client, *, name: str = "AcctCampaign", **extra) -> str:
    scenario_id = await _create_org_scenario(client, name=f"{name}-scenario")
    payload = {
        "name": name,
        "scenario_refs": [{"scenario_id": scenario_id}],
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


async def _account(session_factory, username: str, *, org_id: str = ORG_A, state: str = AccountState.ACTIVE.value):
    set_current_org_id(org_id)
    async with session_factory() as db:
        acc = await create_account(
            db,
            platform="facebook",
            username=username,
            user_id=USER_OWNER,
            org_id=org_id,
        )
        acc.state = state
        acc.status = state
        await db.commit()
        return acc


async def _account_group(session_factory, account_ids: list[str], *, org_id: str = ORG_A) -> str:
    set_current_org_id(org_id)
    async with session_factory() as db:
        group = await create_group(
            db,
            user_id=USER_OWNER,
            name=f"AG-{account_ids[0][:8]}",
            platform="facebook",
            org_id=org_id,
        )
        if account_ids:
            await add_members(db, group=group, account_ids=account_ids)
        await db.commit()
        return group.id


@pytest.mark.asyncio
async def test_ac1_account_group_fan_out(session_factory):
    await _seed_orgs(session_factory)
    d1 = await _online_device(session_factory, serial="A-D1")
    d2 = await _online_device(session_factory, serial="A-D2")
    d3 = await _online_device(session_factory, serial="A-D3")
    a1 = await _account(session_factory, "acct-a1")
    a2 = await _account(session_factory, "acct-a2")
    a3 = await _account(session_factory, "acct-a3")
    group_id = await _account_group(session_factory, [a1.id, a2.id, a3.id])

    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        campaign_id = await _create_campaign(client, name="GroupBind")
        bind = await client.post(
            f"/api/campaigns/{campaign_id}/accounts",
            json={"account_group_id": group_id},
        )
        assert bind.status_code == 200
        resp = await client.post(
            f"/api/campaigns/{campaign_id}/dispatch",
            json={"target": {"device_ids": [d1, d2, d3]}},
        )

    assert resp.status_code == 200
    by_device = {item["device_id"]: item for item in resp.json()["executions"]}
    account_ids = {by_device[d]["account_id"] for d in [d1, d2, d3]}
    assert account_ids == {a1.id, a2.id, a3.id}

    async with session_factory() as db:
        rows = (await db.execute(select(Execution.account_id))).scalars().all()
        assert set(rows) == {a1.id, a2.id, a3.id}


@pytest.mark.asyncio
async def test_ac2_per_device_override(session_factory):
    await _seed_orgs(session_factory)
    d1 = await _online_device(session_factory, serial="O-D1")
    d2 = await _online_device(session_factory, serial="O-D2")
    a99 = await _account(session_factory, "acct-a99")
    a1 = await _account(session_factory, "acct-g1")
    a2 = await _account(session_factory, "acct-g2")
    group_id = await _account_group(session_factory, [a1.id, a2.id])

    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        campaign_id = await _create_campaign(client, name="OverrideAcct")
        await client.post(
            f"/api/campaigns/{campaign_id}/accounts",
            json={
                "account_group_id": group_id,
                "per_device_accounts": {d1: a99.id},
            },
        )
        resp = await client.post(
            f"/api/campaigns/{campaign_id}/dispatch",
            json={"target": {"device_ids": [d1, d2]}},
        )

    assert resp.status_code == 200
    by_device = {item["device_id"]: item["account_id"] for item in resp.json()["executions"]}
    assert by_device[d1] == a99.id
    assert by_device[d2] in {a1.id, a2.id}
    assert by_device[d2] != a99.id


@pytest.mark.asyncio
async def test_ac3_account_not_bound_no_fallback(session_factory):
    await _seed_orgs(session_factory)
    d1 = await _online_device(session_factory, serial="NF-D1")
    primary = await _account(session_factory, "primary-on-device")
    set_current_org_id(ORG_A)
    async with session_factory() as db:
        await assign_account_to_device(db, d1, primary.id, is_primary=True)
        await db.commit()

    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        scenario_id = await _create_org_scenario(
            client,
            name="LoginScenario",
            steps=[_sequence_step("login", "platform_specific.fb_login")],
        )
        resp_create = await client.post(
            "/api/campaigns",
            json={
                "name": "NoBindLogin",
                "scenario_refs": [{"scenario_id": scenario_id}],
            },
        )
        assert resp_create.status_code == 201
        campaign_id = resp_create.json()["id"]
        resp = await client.post(
            f"/api/campaigns/{campaign_id}/dispatch",
            json={"target": {"device_ids": [d1]}},
        )

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "ACCOUNT_NOT_BOUND"
    assert "hint" in detail

    async with session_factory() as db:
        count = (await db.execute(select(func.count()).select_from(Execution))).scalar_one()
        assert count == 0


@pytest.mark.asyncio
async def test_fr04_20_guard_unit_no_primary_fallback(session_factory):
    """Second FR-04-20 guard: social step + primary on device must not dispatch."""
    await _seed_orgs(session_factory)
    d1 = await _online_device(session_factory, serial="GUARD-D1")
    primary = await _account(session_factory, "guard-primary")
    async with session_factory() as db:
        set_current_org_id(ORG_A)
        await assign_account_to_device(db, d1, primary.id, is_primary=True)
        await db.commit()

    steps = [_sequence_step("s1", "fb_post.create")]
    assert scenario_requires_account(steps)

    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        scenario_id = await _create_org_scenario(
            client,
            name="SocialOnly",
            steps=[_sequence_step("login", "platform_specific.fb_login")],
        )
        campaign = await client.post(
            "/api/campaigns",
            json={"name": "GuardCampaign", "scenario_refs": [{"scenario_id": scenario_id}]},
        )
        campaign_id = campaign.json()["id"]
        resp = await client.post(
            f"/api/campaigns/{campaign_id}/dispatch",
            json={"target": {"device_ids": [d1]}},
        )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "ACCOUNT_NOT_BOUND"


@pytest.mark.asyncio
async def test_ac4_cross_org_account_reject(session_factory):
    await _seed_orgs(session_factory)
    a5 = await _account(session_factory, "orgb-acct", org_id=ORG_B)

    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        campaign_id = await _create_campaign(client, name="CrossOrgAcct")
        resp = await client.post(
            f"/api/campaigns/{campaign_id}/accounts",
            json={"scenario_account_id": a5.id},
        )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "ACCOUNT_NOT_FOUND"


@pytest.mark.asyncio
async def test_ac5_suspended_account_partial_fail(session_factory):
    await _seed_orgs(session_factory)
    d1 = await _online_device(session_factory, serial="S-D1")
    d2 = await _online_device(session_factory, serial="S-D2")
    suspended = await _account(session_factory, "suspended-a", state=AccountState.SUSPENDED.value)
    active = await _account(session_factory, "active-a")

    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        campaign_id = await _create_campaign(client, name="SuspendedMix")
        await client.post(
            f"/api/campaigns/{campaign_id}/accounts",
            json={"per_device_accounts": {d1: suspended.id, d2: active.id}},
        )
        resp = await client.post(
            f"/api/campaigns/{campaign_id}/dispatch",
            json={"target": {"device_ids": [d1, d2]}},
        )

    assert resp.status_code == 200
    by_device = {item["device_id"]: item for item in resp.json()["executions"]}
    assert by_device[d1]["status"] == "failed"
    assert by_device[d1]["failure_reason"] == "account_unavailable"
    assert by_device[d2]["status"] == "running"
    assert by_device[d2]["account_id"] == active.id


@pytest.mark.asyncio
async def test_fb_extract_without_bind_dispatches(session_factory):
    """Read-only FB extract/crawl must not require campaign account binding."""
    await _seed_orgs(session_factory)
    d1 = await _online_device(session_factory, serial="EXT-D1")
    steps = [
        _sequence_step("x1", "extract", strategy="fb_posts"),
        _sequence_step("x2", "tap_fb_comment_button"),
    ]
    assert not scenario_requires_account(steps)

    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        scenario_id = await _create_org_scenario(
            client,
            name="FbExtractOnly",
            steps=steps,
        )
        campaign_id = (
            await client.post(
                "/api/campaigns",
                json={
                    "name": "FbExtractCampaign",
                    "scenario_refs": [{"scenario_id": scenario_id}],
                },
            )
        ).json()["id"]
        resp = await client.post(
            f"/api/campaigns/{campaign_id}/dispatch",
            json={"target": {"device_ids": [d1]}},
        )

    assert resp.status_code == 200
    assert resp.json()["executions"][0]["account_id"] is None


@pytest.mark.asyncio
async def test_ac6_ocr_scenario_no_bind_ok(session_factory):
    await _seed_orgs(session_factory)
    d1 = await _online_device(session_factory, serial="OCR-D1")

    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        campaign_id = await _create_campaign(client, name="OcrOnly")
        resp = await client.post(
            f"/api/campaigns/{campaign_id}/dispatch",
            json={"target": {"device_ids": [d1]}},
        )

    assert resp.status_code == 200
    execution = resp.json()["executions"][0]
    assert execution["account_id"] is None

    async with session_factory() as db:
        row = (await db.execute(select(Execution.account_id))).scalar_one()
        assert row is None


@pytest.mark.asyncio
async def test_ac7_audit_log_account_bound(session_factory):
    await _seed_orgs(session_factory)
    acc = await _account(session_factory, "audit-acct")

    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        campaign_id = await _create_campaign(client, name="AuditBind")
        await client.post(
            f"/api/campaigns/{campaign_id}/accounts",
            json={"scenario_account_id": acc.id},
        )

    async with session_factory() as db:
        logs = (
            await db.execute(
                select(ActivityLog).where(
                    ActivityLog.action == "account.bound",
                    ActivityLog.entity_id == campaign_id,
                )
            )
        ).scalars().all()
        assert len(logs) >= 1
        details = logs[0].details or {}
        assert details.get("target_account") == acc.id
        blob = str(details)
        assert "password" not in blob.lower()


@pytest.mark.asyncio
async def test_scenario_account_shared(session_factory):
    await _seed_orgs(session_factory)
    d1 = await _online_device(session_factory, serial="SH-D1")
    d2 = await _online_device(session_factory, serial="SH-D2")
    shared = await _account(session_factory, "shared-acct")

    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        campaign_id = await _create_campaign(client, name="SharedAcct")
        await client.post(
            f"/api/campaigns/{campaign_id}/accounts",
            json={"scenario_account_id": shared.id},
        )
        resp = await client.post(
            f"/api/campaigns/{campaign_id}/dispatch?include_vars=true",
            json={"target": {"device_ids": [d1, d2]}},
        )

    assert resp.status_code == 200
    account_ids = {item["account_id"] for item in resp.json()["executions"]}
    assert account_ids == {shared.id}
    for item in resp.json()["executions"]:
        assert item["effective_vars"].get("__ACCOUNT_ID__") == shared.id


@pytest.mark.asyncio
async def test_unbind_clears_accounts(session_factory):
    await _seed_orgs(session_factory)
    acc = await _account(session_factory, "unbind-acct")

    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        campaign_id = await _create_campaign(client, name="Unbind")
        await client.post(
            f"/api/campaigns/{campaign_id}/accounts",
            json={"scenario_account_id": acc.id},
        )
        cleared = await client.delete(f"/api/campaigns/{campaign_id}/accounts")
        assert cleared.status_code == 200
        body = cleared.json()
        assert body["scenario_account_id"] is None
        assert body["per_device_accounts"] == {}
