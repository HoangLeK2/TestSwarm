"""Epic 04 DF-T-04-007: campaign lifecycle FSM."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest_plugins = ["tests.test_epic04_scenario_entity"]

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from db.crud import campaign_entity as campaign_repo
from db.crud.execution import create_execution
from db.crud.execution_dlq import create_dlq_entry
from db.models.activity import ActivityLog
from db.models.enums import CampaignStatus, DLQStatus, ExecutionStatus
from db.models.execution import Execution
from services.campaign.aggregator import (
    compute_terminal_campaign_status,
    compute_terminal_from_counts,
    evaluate_campaign_status,
)
from services.campaign.fsm import (
    all_transition_pairs,
    can_dispatch,
    can_transition,
    normalize_status,
)
from services.campaign.lifecycle import apply_campaign_transition
from tenancy.context import set_current_org_id
from tests.test_epic04_campaign_device_binding import (
    _create_campaign,
    _online_device,
)
from tests.test_epic04_scenario_entity import (
    ORG_A,
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


def _build_superadmin_app(session_factory):
    app = _build_app(session_factory)
    from api.deps import _get_current_user

    async def _superadmin_override():
        from tenancy.context import set_current_org_id

        set_current_org_id(ORG_A)
        return SimpleNamespace(
            id="super-1",
            email="super@example.com",
            name="super",
            role="superadmin",
            org_role="owner",
            is_active=True,
            org_id=ORG_A,
        )

    app.dependency_overrides[_get_current_user] = _superadmin_override
    return app


@pytest.mark.parametrize(
    ("src", "dst", "allowed"),
    [
        (CampaignStatus.DRAFT, CampaignStatus.RUNNING, True),
        (CampaignStatus.DRAFT, CampaignStatus.SCHEDULED, True),
        (CampaignStatus.SCHEDULED, CampaignStatus.RUNNING, True),
        (CampaignStatus.RUNNING, CampaignStatus.COMPLETED, True),
        (CampaignStatus.RUNNING, CampaignStatus.FAILED, True),
        (CampaignStatus.RUNNING, CampaignStatus.CANCELLED, True),
        (CampaignStatus.COMPLETED, CampaignStatus.CANCELLED, False),
        (CampaignStatus.COMPLETED, CampaignStatus.ARCHIVED, True),
        (CampaignStatus.CANCELLED, CampaignStatus.ARCHIVED, True),
        (CampaignStatus.ARCHIVED, CampaignStatus.DRAFT, False),
    ],
)
def test_fsm_transition_table(src, dst, allowed):
    assert can_transition(src, dst) is allowed


def test_fsm_all_pairs_cover_enum():
    pairs = all_transition_pairs()
    assert pairs
    for src, dst, allowed in pairs:
        assert can_transition(src, dst) is allowed


@pytest.mark.parametrize(
    ("status", "allowed"),
    [
        (CampaignStatus.DRAFT, True),
        (CampaignStatus.IDLE, True),
        (CampaignStatus.SCHEDULED, True),
        (CampaignStatus.RUNNING, False),
        (CampaignStatus.PAUSED, False),
        (CampaignStatus.COMPLETED, False),
        (CampaignStatus.FAILED, False),
        (CampaignStatus.CANCELLED, True),
        (CampaignStatus.ARCHIVED, False),
    ],
)
def test_can_dispatch(status, allowed):
    assert can_dispatch(status) is allowed


@pytest.mark.asyncio
async def test_ac1_dispatch_transitions_draft_to_running(session_factory):
    await _seed_orgs(session_factory)
    device_id = await _online_device(session_factory, serial="FSM-D1")

    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        campaign_id = await _create_campaign(client, name="FsmDispatch")
        resp = await client.post(
            f"/api/campaigns/{campaign_id}/dispatch",
            json={"target": {"device_ids": [device_id]}},
        )
        assert resp.status_code == 200

    async with session_factory() as db:
        row = await campaign_repo.get_campaign_entity(db, campaign_id)
        assert row.status == CampaignStatus.RUNNING.value
        assert row.started_at is not None
        events = (
            await db.execute(
                select(func.count())
                .select_from(ActivityLog)
                .where(
                    ActivityLog.action == "campaign.status.changed",
                    ActivityLog.entity_id == campaign_id,
                )
            )
        ).scalar_one()
    assert events >= 1


@pytest.mark.asyncio
async def test_ac2_aggregator_running_to_completed(session_factory):
    await _seed_orgs(session_factory)
    async with session_factory() as db:
        row = await campaign_repo.create_campaign_entity(
            db,
            org_id=ORG_A,
            name="AggComplete",
            status=CampaignStatus.RUNNING.value,
            created_by=USER_OWNER,
        )
        row.started_at = row.created_at
        await db.flush()
        for idx in range(8):
            await create_execution(
                db,
                run_type="campaign_device",
                campaign_id=row.id,
                status=ExecutionStatus.COMPLETED.value,
                user_id=USER_OWNER,
            )
        for idx in range(2):
            ex = await create_execution(
                db,
                run_type="campaign_device",
                campaign_id=row.id,
                status=ExecutionStatus.FAILED.value,
                user_id=USER_OWNER,
            )
            dlq = await create_dlq_entry(
                db,
                execution_id=ex.id,
                device_serial=f"dev-{idx}",
                error="failed",
            )
            dlq.status = DLQStatus.RESOLVED.value
            await db.flush()
        await db.commit()
        campaign_id = row.id

    async with session_factory() as db:
        set_current_org_id(ORG_A)
        result = await evaluate_campaign_status(
            db,
            org_id=ORG_A,
            campaign_id=campaign_id,
            user_id=USER_OWNER,
        )
        row = await campaign_repo.get_campaign_entity(db, campaign_id)
        await db.commit()

    assert result is not None
    assert result.changed is True
    assert result.to_status == CampaignStatus.COMPLETED.value
    assert row.status == CampaignStatus.COMPLETED.value
    assert row.completed_at is not None


@pytest.mark.asyncio
async def test_ac3_aggregator_running_to_failed(session_factory):
    await _seed_orgs(session_factory)
    async with session_factory() as db:
        row = await campaign_repo.create_campaign_entity(
            db,
            org_id=ORG_A,
            name="AggFailed",
            status=CampaignStatus.RUNNING.value,
            created_by=USER_OWNER,
        )
        row.started_at = row.created_at
        await db.flush()
        for idx in range(5):
            ex = await create_execution(
                db,
                run_type="campaign_device",
                campaign_id=row.id,
                status=ExecutionStatus.FAILED.value,
                user_id=USER_OWNER,
            )
            await create_dlq_entry(
                db,
                execution_id=ex.id,
                device_serial=f"fail-{idx}",
                error="boom",
            )
        await db.commit()
        campaign_id = row.id

    async with session_factory() as db:
        set_current_org_id(ORG_A)
        result = await evaluate_campaign_status(
            db,
            org_id=ORG_A,
            campaign_id=campaign_id,
            user_id=USER_OWNER,
        )
        row = await campaign_repo.get_campaign_entity(db, campaign_id)
        await db.commit()

    assert result is not None
    assert result.to_status == CampaignStatus.FAILED.value
    assert row.status == CampaignStatus.FAILED.value


def test_compute_terminal_mixed_completed_and_closed_dlq():
    assert (
        compute_terminal_from_counts(
            total=2,
            active_count=0,
            completed_count=1,
            open_dlq_count=0,
        )
        == CampaignStatus.COMPLETED
    )


def test_compute_terminal_all_dlq_open_is_failed():
    assert (
        compute_terminal_from_counts(
            total=2,
            active_count=0,
            completed_count=0,
            open_dlq_count=2,
        )
        == CampaignStatus.FAILED
    )


@pytest.mark.asyncio
async def test_ac4_cancel_completed_rejected(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        scenario_id = await _create_org_scenario(client, name="CancelDone")
        created = await client.post(
            "/api/campaigns",
            json={"name": "DoneC", "scenario_refs": [{"scenario_id": scenario_id}]},
        )
        campaign_id = created.json()["id"]
        async with session_factory() as db:
            row = await campaign_repo.get_campaign_entity(db, campaign_id)
            row.status = CampaignStatus.COMPLETED.value
            await db.commit()

        resp = await client.post(f"/api/campaigns/{campaign_id}/cancel", json={"reason": "nope"})
        async with session_factory() as db:
            row = await campaign_repo.get_campaign_entity(db, campaign_id)

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "INVALID_TRANSITION"
    assert row.status == CampaignStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_ac5_cancel_running(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        scenario_id = await _create_org_scenario(client, name="CancelRun")
        created = await client.post(
            "/api/campaigns",
            json={"name": "RunC", "scenario_refs": [{"scenario_id": scenario_id}]},
        )
        campaign_id = created.json()["id"]
        async with session_factory() as db:
            row = await campaign_repo.get_campaign_entity(db, campaign_id)
            row.status = CampaignStatus.RUNNING.value
            await create_execution(
                db,
                run_type="campaign_device",
                campaign_id=campaign_id,
                status=ExecutionStatus.RUNNING.value,
                user_id=USER_OWNER,
            )
            await db.commit()

        resp = await client.post(
            f"/api/campaigns/{campaign_id}/cancel",
            json={"reason": "emergency"},
        )
        async with session_factory() as db:
            row = await campaign_repo.get_campaign_entity(db, campaign_id)

    assert resp.status_code == 200
    assert resp.json()["status"] == CampaignStatus.CANCELLED.value
    assert row.status == CampaignStatus.CANCELLED.value
    assert row.cancelled_at is not None


@pytest.mark.asyncio
async def test_ac6_patch_body_locked_when_running(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        s1 = await _create_org_scenario(client, name="LockS1")
        s2 = await _create_org_scenario(client, name="LockS2")
        created = await client.post(
            "/api/campaigns",
            json={"name": "Locked", "scenario_refs": [{"scenario_id": s1}]},
        )
        campaign_id = created.json()["id"]
        async with session_factory() as db:
            row = await campaign_repo.get_campaign_entity(db, campaign_id)
            row.status = CampaignStatus.RUNNING.value
            await db.commit()

        patched = await client.patch(
            f"/api/campaigns/{campaign_id}",
            json={"scenario_refs": [{"scenario_id": s2}]},
        )

    assert patched.status_code == 409
    assert patched.json()["detail"]["code"] == "CAMPAIGN_LOCKED"


@pytest.mark.asyncio
async def test_cancel_idempotent_second_request(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        scenario_id = await _create_org_scenario(client, name="IdemCancel")
        created = await client.post(
            "/api/campaigns",
            json={"name": "IdemC", "scenario_refs": [{"scenario_id": scenario_id}]},
        )
        campaign_id = created.json()["id"]
        async with session_factory() as db:
            set_current_org_id(ORG_A)
            row = await campaign_repo.get_campaign_entity(db, campaign_id)
            row.status = CampaignStatus.RUNNING.value
            await db.commit()

        r1 = await client.post(
            f"/api/campaigns/{campaign_id}/cancel",
            json={"reason": "dup"},
        )
        r2 = await client.post(
            f"/api/campaigns/{campaign_id}/cancel",
            json={"reason": "dup"},
        )

    assert r1.status_code == 200
    assert r2.status_code == 200
    async with session_factory() as db:
        set_current_org_id(ORG_A)
        events = (
            await db.execute(
                select(func.count())
                .select_from(ActivityLog)
                .where(
                    ActivityLog.action == "campaign.status.changed",
                    ActivityLog.entity_id == campaign_id,
                )
            )
        ).scalar_one()
    assert events == 1


@pytest.mark.asyncio
async def test_force_transition_requires_superadmin(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        scenario_id = await _create_org_scenario(client, name="ForceS")
        created = await client.post(
            "/api/campaigns",
            json={"name": "ForceC", "scenario_refs": [{"scenario_id": scenario_id}]},
        )
        campaign_id = created.json()["id"]
        resp = await client.post(
            f"/api/campaigns/{campaign_id}/force-transition",
            json={"to_status": "running", "reason": "recovery"},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_force_transition_superadmin(session_factory):
    await _seed_orgs(session_factory)
    app = _build_superadmin_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        scenario_id = await _create_org_scenario(client, name="ForceOk")
        created = await client.post(
            "/api/campaigns",
            json={"name": "ForceOkC", "scenario_refs": [{"scenario_id": scenario_id}]},
        )
        campaign_id = created.json()["id"]
        resp = await client.post(
            f"/api/campaigns/{campaign_id}/force-transition",
            json={"to_status": "running", "reason": "recovery"},
        )
    assert resp.status_code == 200
    assert resp.json()["to_status"] == "running"
    assert resp.json()["changed"] is True


@pytest.mark.asyncio
async def test_archive_cancelled_campaign(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        scenario_id = await _create_org_scenario(client, name="ArchCancel")
        created = await client.post(
            "/api/campaigns",
            json={"name": "ArchC", "scenario_refs": [{"scenario_id": scenario_id}]},
        )
        campaign_id = created.json()["id"]
        async with session_factory() as db:
            row = await campaign_repo.get_campaign_entity(db, campaign_id)
            row.status = CampaignStatus.CANCELLED.value
            row.cancelled_at = row.updated_at
            await db.commit()

        resp = await client.post(f"/api/campaigns/{campaign_id}/archive")
    assert resp.status_code == 200
    assert resp.json()["status"] == CampaignStatus.ARCHIVED.value


@pytest.mark.asyncio
async def test_apply_transition_increments_lock_version(session_factory):
    await _seed_orgs(session_factory)
    async with session_factory() as db:
        row = await campaign_repo.create_campaign_entity(
            db,
            org_id=ORG_A,
            name="LockVer",
            status=CampaignStatus.DRAFT.value,
            created_by=USER_OWNER,
        )
        await db.commit()
        campaign_id = row.id

    async with session_factory() as db:
        set_current_org_id(ORG_A)
        row = await campaign_repo.get_campaign_entity(db, campaign_id)
        assert row is not None
        await apply_campaign_transition(
            db,
            row,
            CampaignStatus.RUNNING,
            org_id=ORG_A,
            user_id=USER_OWNER,
            reason="test",
        )
        await db.commit()

    async with session_factory() as db:
        set_current_org_id(ORG_A)
        row = await campaign_repo.get_campaign_entity(db, campaign_id)
        assert row.lock_version >= 1
        assert normalize_status(row.status) == CampaignStatus.RUNNING
