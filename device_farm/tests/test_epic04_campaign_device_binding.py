"""Epic 04 DF-T-04-008: campaign device binding & fan-out."""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest_plugins = ["tests.test_epic04_scenario_entity"]

from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, select, update

from db.crud import campaign_entity as campaign_repo
from db.crud.device import create_device
from db.crud.device_group import add_devices_to_group, create_group
from db.crud.device_reserve_session import get_active_session
from db.models.campaign import CampaignTarget
from db.models.enums import CampaignStatus, DeviceFsmEvent
from db.models.execution import Execution, ExecutionDevice, ExecutionResult
from db.models.external_entity import ExecutionEntityAssignment
from db.crud.external_entity import upsert_external_entity
from services.campaign.dispatcher import (
    FanOutExecutionView,
    FanOutResult,
    dispatch_campaign,
)
from services.campaign.execution_runtime import start_execution_runtime
from services.campaign.override_resolver import merge_effective_vars
from services.device_reserve.service import claim_device_session
from services.device_state.service import DeviceStateService
from services.scenario_dsl.variable_resolver import EffectiveVariableResolver
from temporal.shared import DeviceActionBatchInput
from tenancy.context import set_current_org_id, tenant_context
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
async def test_fan_out_assigns_one_external_entity_per_device_and_freezes_vars(
    session_factory,
):
    await _seed_orgs(session_factory)
    d1 = await _online_device(session_factory, serial="ENTITY-D1")
    d2 = await _online_device(session_factory, serial="ENTITY-D2")

    set_current_org_id(ORG_A)
    async with session_factory() as db:
        first, _ = await upsert_external_entity(
            db,
            org_id=ORG_A,
            platform="facebook",
            entity_type="group",
            display_name="Group One",
            external_id="group-1",
            attributes={
                "locator": {
                    "kind": "facebook_group_search_result",
                    "version": 1,
                    "search_query": "Group One",
                    "selector": {
                        "by": "descriptionStartsWith",
                        "value": "Group One,",
                    },
                    "fallback_selector": {
                        "by": "descriptionContains",
                        "value": "Group One",
                    },
                }
            },
        )
        second, _ = await upsert_external_entity(
            db,
            org_id=ORG_A,
            platform="facebook",
            entity_type="group",
            display_name="Group Two",
            external_id="group-2",
        )
        await db.commit()
        entity_ids = [first.id, second.id]

    app = _build_app(session_factory)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        campaign_id = await _create_campaign(client, name="EntityFanOut")
        with patch(
            "services.campaign.execution_runtime.start_execution_runtime",
            AsyncMock(
                return_value={
                    "temporal": 0,
                    "fallback": 0,
                    "failed": 0,
                    "skipped": 2,
                }
            ),
        ):
            response = await client.post(
                f"/api/campaigns/{campaign_id}/dispatch?include_vars=true",
                json={
                    "target": {
                        "device_ids": [d1, d2],
                        "external_entity_ids": entity_ids,
                    }
                },
            )

    assert response.status_code == 200, response.text
    rows = response.json()["executions"]
    assert [row["external_entity_id"] for row in rows] == entity_ids
    assert [row["effective_vars"]["TARGET_NAME"] for row in rows] == [
        "Group One",
        "Group Two",
    ]
    assert [row["effective_vars"]["TARGET_EXTERNAL_ID"] for row in rows] == [
        "group-1",
        "group-2",
    ]
    assert [row["effective_vars"]["TARGET_GROUP_NAME"] for row in rows] == [
        "Group One",
        "Group Two",
    ]
    assert [row["effective_vars"]["GROUP_NAME"] for row in rows] == [
        "Group One",
        "Group Two",
    ]
    assert [row["effective_vars"]["TARGET_SEARCH_QUERY"] for row in rows] == [
        "Group One",
        "Group Two",
    ]
    assert [row["effective_vars"]["TARGET_SELECTOR_BY"] for row in rows] == [
        "descriptionStartsWith",
        "descriptionStartsWith",
    ]
    assert [row["effective_vars"]["TARGET_SELECTOR_VALUE"] for row in rows] == [
        "Group One,",
        "Group Two,",
    ]

    async with session_factory() as db:
        assignments = (
            await db.execute(
                select(ExecutionEntityAssignment).order_by(
                    ExecutionEntityAssignment.assigned_at,
                    ExecutionEntityAssignment.execution_id,
                )
            )
        ).scalars().all()
        assert len(assignments) == 2
        assert {row.device_id for row in assignments} == {d1, d2}
        assert {row.external_entity_id for row in assignments} == set(entity_ids)


@pytest.mark.asyncio
async def test_fan_out_rejects_entity_count_different_from_valid_device_count(
    session_factory,
):
    await _seed_orgs(session_factory)
    d1 = await _online_device(session_factory, serial="ENTITY-COUNT-D1")
    d2 = await _online_device(session_factory, serial="ENTITY-COUNT-D2")

    set_current_org_id(ORG_A)
    async with session_factory() as db:
        entity, _ = await upsert_external_entity(
            db,
            org_id=ORG_A,
            platform="facebook",
            entity_type="group",
            display_name="Only Group",
            external_id="only-group",
        )
        await db.commit()

    app = _build_app(session_factory)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        campaign_id = await _create_campaign(client, name="EntityCount")
        response = await client.post(
            f"/api/campaigns/{campaign_id}/dispatch",
            json={
                "target": {
                    "device_ids": [d1, d2],
                    "external_entity_ids": [entity.id],
                }
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "ENTITY_ASSIGNMENT_COUNT_MISMATCH"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload_version",
    ["current", "legacy_campaign_id", "legacy_run_id"],
)
async def test_campaign_activity_does_not_touch_phone_after_claim_is_lost(
    session_factory,
    payload_version,
):
    await _seed_orgs(session_factory)
    device_id = await _online_device(session_factory, serial="CLAIM-LOST-1")
    app = _build_app(session_factory)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        campaign_id = await _create_campaign(client, name="ClaimLost")
        with patch(
            "services.campaign.execution_runtime.start_execution_runtime",
            AsyncMock(
                return_value={
                    "temporal": 0,
                    "fallback": 0,
                    "failed": 0,
                    "skipped": 1,
                }
            ),
        ):
            response = await client.post(
                f"/api/campaigns/{campaign_id}/dispatch",
                json={"target": {"device_ids": [device_id]}},
            )
    assert response.status_code == 200
    execution_id = response.json()["executions"][0]["execution_id"]

    async with session_factory() as db:
        session = await get_active_session(db, device_id)
        assert session is not None
        session.released_at = datetime.now(timezone.utc)
        await db.commit()

    @asynccontextmanager
    async def _activity_session():
        async with session_factory() as db:
            yield db

    phone = MagicMock()
    phone.model = "mock-phone"
    phone.screen_width = 1080
    phone.screen_height = 1920
    phone._batch_enabled.return_value = True
    phone.u2_batch.return_value = [{"op": "click", "ok": True}]

    from temporal.activities import DeviceActivities, set_device_registry

    inp = DeviceActionBatchInput(
        device_serial="CLAIM-LOST-1",
        steps=[{"type": "tap_position", "pos": "middle_center"}],
        step_indices=[0],
        run_id=execution_id if payload_version == "legacy_run_id" else None,
        execution_id=None if payload_version == "legacy_run_id" else execution_id,
        campaign_id=campaign_id if payload_version == "current" else None,
    )
    set_device_registry(
        SimpleNamespace(
            get_device=lambda serial: phone if serial == "CLAIM-LOST-1" else None
        )
    )
    try:
        with (
            patch("db.database.activity_session", _activity_session),
            patch("temporal.activities.activity") as mock_activity,
            patch(
                "services.execution_pause_flags.is_execution_cancelled_async",
                AsyncMock(return_value=False),
            ),
            patch(
                "services.execution_pause_flags.is_execution_paused_async",
                AsyncMock(return_value=False),
            ),
        ):
            mock_activity.heartbeat = MagicMock()
            mock_activity.is_cancelled = MagicMock(return_value=False)
            with pytest.raises(RuntimeError, match="campaign device claim"):
                await DeviceActivities().execute_device_action_batch(inp)
    finally:
        set_device_registry(None)

    phone.u2_batch.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("heartbeat_age", "should_renew"),
    [
        (timedelta(minutes=10), True),
        (timedelta(minutes=31), False),
    ],
)
async def test_campaign_keepalive_activity_requires_live_multi_day_device_claim(
    session_factory,
    heartbeat_age,
    should_renew,
):
    await _seed_orgs(session_factory)
    device_id = await _online_device(session_factory, serial="CLAIM-MULTI-DAY-1")
    app = _build_app(session_factory)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        campaign_id = await _create_campaign(client, name="ClaimMultiDay")
        with patch(
            "services.campaign.execution_runtime.start_execution_runtime",
            AsyncMock(
                return_value={
                    "temporal": 0,
                    "fallback": 0,
                    "failed": 0,
                    "skipped": 1,
                }
            ),
        ):
            response = await client.post(
                f"/api/campaigns/{campaign_id}/dispatch",
                json={"target": {"device_ids": [device_id]}},
            )
    assert response.status_code == 200
    execution_id = response.json()["executions"][0]["execution_id"]
    now = datetime.now(timezone.utc)
    previous_heartbeat = now - heartbeat_age

    async with session_factory() as db:
        session = await get_active_session(db, device_id)
        assert session is not None
        session.claimed_at = now - timedelta(days=3)
        session.last_heartbeat = previous_heartbeat
        await db.commit()

    @asynccontextmanager
    async def _activity_session():
        async with session_factory() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    from temporal.activities import CampaignDeviceClaimLostError, DeviceActivities

    with tenant_context(None), patch("db.database.activity_session", _activity_session):
        payload = {
            "campaign_id": campaign_id,
            "execution_id": execution_id,
            "device_serial": "CLAIM-MULTI-DAY-1",
        }
        if should_renew:
            recommended_interval = (
                await DeviceActivities().heartbeat_campaign_device_claim(payload)
            )
        else:
            with pytest.raises(CampaignDeviceClaimLostError, match="claim expired"):
                await DeviceActivities().heartbeat_campaign_device_claim(payload)

    async with session_factory() as db:
        renewed_session = await get_active_session(db, device_id)

    assert renewed_session is not None
    renewed_heartbeat = renewed_session.last_heartbeat
    if renewed_heartbeat.tzinfo is None:
        renewed_heartbeat = renewed_heartbeat.replace(tzinfo=timezone.utc)
    if should_renew:
        assert recommended_interval == 600
        assert renewed_heartbeat > previous_heartbeat
    else:
        assert renewed_heartbeat == previous_heartbeat


@pytest.mark.asyncio
async def test_dispatch_response_bulk_loads_execution_metadata(session_factory, engine):
    await _seed_orgs(session_factory)
    device_ids = [
        await _online_device(session_factory, serial=f"BULK-{idx:02d}")
        for idx in range(12)
    ]
    app = _build_app(session_factory)
    capture_response_queries = False
    individual_execution_reads = 0

    def _before_cursor_execute(_conn, _cursor, statement, _params, _context, _many):
        nonlocal individual_execution_reads
        normalized = " ".join(statement.split())
        if (
            capture_response_queries
            and "FROM executions" in normalized
            and "WHERE executions.id =" in normalized
        ):
            individual_execution_reads += 1

    async def _runtime_stub(db, *, fan_out, **_kwargs):
        nonlocal capture_response_queries
        execution_ids = [view.execution_id for view in fan_out.executions]
        await db.execute(
            update(Execution)
            .where(Execution.id.in_(execution_ids))
            .values(
                meta={
                    "dispatch_source": "temporal",
                    "workflow_id": "workflow-bulk",
                }
            )
        )
        capture_response_queries = True
        return {"temporal": 0, "fallback": 0, "failed": 0, "skipped": 12}

    event.listen(engine.sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            campaign_id = await _create_campaign(client, name="BulkResponse")
            with patch(
                "services.campaign.execution_runtime.start_execution_runtime",
                side_effect=_runtime_stub,
            ):
                response = await client.post(
                    f"/api/campaigns/{campaign_id}/dispatch",
                    json={"target": {"device_ids": device_ids}},
                )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _before_cursor_execute)

    assert response.status_code == 200
    payload = response.json()
    assert payload["target_count"] == 12
    assert {
        (row["dispatch_source"], row["workflow_id"])
        for row in payload["executions"]
    } == {("temporal", "workflow-bulk")}
    assert individual_execution_reads == 0


@pytest.mark.asyncio
async def test_dispatch_batches_persistence_and_preserves_response_order(
    session_factory,
    engine,
):
    await _seed_orgs(session_factory)
    device_ids = [
        await _online_device(session_factory, serial=f"PERSIST-{idx:02d}")
        for idx in range(120)
    ]
    requested_device_ids = list(reversed(device_ids))
    app = _build_app(session_factory)
    inserted_statements: list[str] = []
    claimed_device_ids: list[str] = []

    def _before_cursor_execute(_conn, _cursor, statement, _params, _context, _many):
        normalized = " ".join(statement.split())
        if normalized.startswith(
            (
                "INSERT INTO executions ",
                "INSERT INTO execution_devices ",
                "INSERT INTO execution_results ",
            )
        ):
            inserted_statements.append(normalized)

    async def _claim_stub(_db, *, device_id: str, **_kwargs):
        claimed_device_ids.append(device_id)
        return SimpleNamespace(session_id=f"claim-{device_id}")

    event.listen(engine.sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            campaign_id = await _create_campaign(client, name="BatchedPersistence")
            with (
                patch(
                    "services.campaign.dispatcher.claim_device_session",
                    side_effect=_claim_stub,
                ),
                patch(
                    "services.campaign.execution_runtime.start_execution_runtime",
                    return_value={
                        "temporal": 0,
                        "fallback": 0,
                        "failed": 0,
                        "skipped": 120,
                    },
                ),
            ):
                response = await client.post(
                    f"/api/campaigns/{campaign_id}/dispatch",
                    json={"target": {"device_ids": requested_device_ids}},
                )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _before_cursor_execute)

    assert response.status_code == 200
    assert claimed_device_ids == sorted(requested_device_ids)
    assert [
        row["device_id"] for row in response.json()["executions"]
    ] == requested_device_ids
    # 120 rows at chunk size 25 => five statements per persistence table.
    assert len(inserted_statements) == 15
    execution_ids = [
        row["execution_id"] for row in response.json()["executions"]
    ]
    async with session_factory() as db:
        execution_count = await db.scalar(
            select(func.count(Execution.id)).where(Execution.id.in_(execution_ids))
        )
        link_count = await db.scalar(
            select(func.count(ExecutionDevice.id)).where(
                ExecutionDevice.execution_id.in_(execution_ids)
            )
        )
        result_count = await db.scalar(
            select(func.count(ExecutionResult.id)).where(
                ExecutionResult.execution_id.in_(execution_ids)
            )
        )
    assert (execution_count, link_count, result_count) == (120, 120, 120)


@pytest.mark.asyncio
async def test_dispatch_rolls_back_claims_and_first_chunk_when_later_chunk_fails(
    session_factory,
    engine,
):
    await _seed_orgs(session_factory)
    device_ids = [
        await _online_device(session_factory, serial=f"ROLLBACK-{idx:02d}")
        for idx in range(26)
    ]
    app = _build_app(session_factory)
    execution_insert_count = 0

    def _fail_second_execution_batch(
        _conn,
        _cursor,
        statement,
        _params,
        _context,
        _many,
    ):
        nonlocal execution_insert_count
        normalized = " ".join(statement.split())
        if not normalized.startswith("INSERT INTO executions "):
            return
        execution_insert_count += 1
        if execution_insert_count == 2:
            raise RuntimeError("forced second-chunk persistence failure")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        campaign_id = await _create_campaign(client, name="RollbackBatch")
        event.listen(
            engine.sync_engine,
            "before_cursor_execute",
            _fail_second_execution_batch,
        )
        try:
            with patch(
                "services.campaign.execution_runtime.start_execution_runtime"
            ) as runtime_start:
                with pytest.raises(
                    RuntimeError,
                    match="forced second-chunk persistence failure",
                ):
                    await client.post(
                        f"/api/campaigns/{campaign_id}/dispatch",
                        json={"target": {"device_ids": device_ids}},
                    )
                runtime_start.assert_not_awaited()
        finally:
            event.remove(
                engine.sync_engine,
                "before_cursor_execute",
                _fail_second_execution_batch,
            )

    assert execution_insert_count == 2
    async with session_factory() as db:
        execution_count = await db.scalar(
            select(func.count(Execution.id)).where(
                Execution.campaign_id == campaign_id
            )
        )
        target_count = await db.scalar(
            select(func.count(CampaignTarget.id)).where(
                CampaignTarget.campaign_id == campaign_id
            )
        )
        active_sessions = [
            await get_active_session(db, device_id) for device_id in device_ids
        ]
    assert (execution_count, target_count) == (0, 0)
    assert active_sessions == [None] * len(device_ids)


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
async def test_promoted_sequential_phone_keeps_original_device_index(session_factory):
    await _seed_orgs(session_factory)
    d1 = await _online_device(session_factory, serial="SEQ-INDEX-D1")
    d2 = await _online_device(session_factory, serial="SEQ-INDEX-D2")

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
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        campaign_id = await _create_campaign(client, name="SequentialIndex")
        with patch(
            "services.campaign.execution_runtime.start_execution_runtime",
            AsyncMock(
                return_value={
                    "temporal": 0,
                    "fallback": 0,
                    "failed": 0,
                    "skipped": 2,
                }
            ),
        ):
            response = await client.post(
                f"/api/campaigns/{campaign_id}/dispatch",
                json={
                    "target": {"device_ids": [d1, d2]},
                    "dispatch_strategy": "sequential",
                },
            )
    assert response.status_code == 200
    promoted = next(
        row for row in response.json()["executions"] if row["device_id"] == d2
    )
    assert promoted["status"] == "running"

    temporal_client = SimpleNamespace(start_workflow=AsyncMock())
    async with session_factory() as db:
        campaign = await campaign_repo.get_campaign_entity(db, campaign_id)
        assert campaign is not None
        await start_execution_runtime(
            db,
            fan_out=FanOutResult(
                dispatch_id="sequential-index",
                campaign_id=campaign_id,
                dispatch_strategy="sequential",
                executions=[
                    FanOutExecutionView(
                        execution_id=promoted["execution_id"],
                        device_id=d2,
                        status="running",
                        effective_vars={},
                    )
                ],
            ),
            campaign=campaign,
            org_id=ORG_A,
            actor_user_id=USER_OWNER,
            temporal_client=temporal_client,
            temporal_config=SimpleNamespace(
                enabled=True,
                task_queue="device-scenario",
            ),
            manager=None,
        )

    scenario_input = temporal_client.start_workflow.await_args.args[1]
    assert scenario_input.device_serial == "SEQ-INDEX-D2"
    assert scenario_input.steps[0]["variables"]["DEVICE_INDEX"] == "1"


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

    app = _build_app(session_factory)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        campaign_id = await _create_campaign(client, name="DirectDispatch")

    set_current_org_id(ORG_A)
    async with session_factory() as db:
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
