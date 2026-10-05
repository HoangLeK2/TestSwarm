"""Epic 04 DF-T-04-018: preview execution surface."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

pytest_plugins = ["tests.test_epic04_scenario_entity"]

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from db.crud.content import create_content_item
from db.crud.execution import create_execution
from db.models.content import ContentItem
from db.models.enums import DeviceFsmEvent, ExecutionKind, ExecutionStatus
from db.models.execution import Execution
from db.models.execution_step import ExecutionStep
from services.execution.preview_collection import preview_collection_name
from services.execution.preview_purge import purge_stale_preview_artifacts
from services.device_state.service import DeviceStateService
from tenancy.context import set_current_org_id
from tests.test_epic04_scenario_entity import (
    ORG_A,
    USER_OWNER,
    _build_app,
    _seed_orgs,
)


def _wait_step(step_id: str = "w"):
    return {"id": step_id, "type": "input_wait.wait", "config": {"seconds": 1}}


async def _create_scenario(client: AsyncClient, *, steps: list[dict], name: str = "PreviewScenario") -> str:
    created = await client.post("/api/scenarios", json={"name": name, "kind": "sequence"})
    assert created.status_code == 201, created.text
    scenario_id = created.json()["id"]
    body = await client.post(
        f"/api/scenarios/{scenario_id}/body",
        json={"steps": steps},
    )
    assert body.status_code == 200, body.text
    return scenario_id


async def _online_device(session_factory, *, serial: str = "preview-dev-1") -> str:
    from db.crud.device import create_device

    set_current_org_id(ORG_A)
    svc = DeviceStateService()
    async with session_factory() as db:
        device = await create_device(db, serial, user_id=USER_OWNER, org_id=ORG_A)
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


@pytest.mark.asyncio
async def test_preview_start_success(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    device_id = await _online_device(session_factory)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        scenario_id = await _create_scenario(client, steps=[_wait_step()])
        with patch(
            "services.execution.preview_runtime.start_preview_runtime",
            new=AsyncMock(
                return_value={
                    "started": True,
                    "dispatch_source": "fallback",
                    "workflow_id": "exec_test",
                }
            ),
        ):
            resp = await client.post(
                f"/api/scenarios/{scenario_id}/preview",
                json={"device_id": device_id},
            )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["kind"] == "preview"
    assert data["status"] == ExecutionStatus.RUNNING.value
    assert data["warnings"] == []

    async with session_factory() as db:
        execution = await db.get(Execution, data["execution_id"])
        assert execution is not None
        assert execution.kind == ExecutionKind.PREVIEW.value
        assert execution.campaign_id is None
        assert execution.org_id == ORG_A


@pytest.mark.asyncio
async def test_list_preview_executions(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        scenario_id = await _create_scenario(client, steps=[_wait_step()], name="ListPreview")
        with patch(
            "services.execution.preview_runtime.start_preview_runtime",
            new=AsyncMock(
                return_value={"started": True, "dispatch_source": "fallback", "workflow_id": "exec_y"}
            ),
        ):
            for serial in ("preview-dev-5a", "preview-dev-5b", "preview-dev-5c"):
                dev_id = await _online_device(session_factory, serial=serial)
                resp = await client.post(
                    f"/api/scenarios/{scenario_id}/preview",
                    json={"device_id": dev_id},
                )
                assert resp.status_code == 200

        listed = await client.get(f"/api/preview?user={USER_OWNER}")

    assert listed.status_code == 200
    payload = listed.json()
    assert payload["total"] >= 3
    assert all(item["kind"] == "preview" for item in payload["items"])


@pytest.mark.asyncio
async def test_preview_not_in_campaign_runs(session_factory):
    await _seed_orgs(session_factory)
    app = _build_app(session_factory)
    device_id = await _online_device(session_factory, serial="preview-dev-6")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        scenario_id = await _create_scenario(client, steps=[_wait_step()], name="CampIso")
        campaign = await client.post(
            "/api/campaigns",
            json={"name": "CampIso", "scenario_refs": [{"scenario_id": scenario_id}]},
        )
        assert campaign.status_code == 201
        campaign_id = campaign.json()["id"]

        with patch(
            "services.execution.preview_runtime.start_preview_runtime",
            new=AsyncMock(
                return_value={"started": True, "dispatch_source": "fallback", "workflow_id": "exec_z"}
            ),
        ):
            preview = await client.post(
                f"/api/scenarios/{scenario_id}/preview",
                json={"device_id": device_id},
            )
        assert preview.status_code == 200

        runs = await client.get(f"/api/campaigns/{campaign_id}/runs")
        assert runs.status_code == 200
        run_ids = {item["id"] for item in runs.json()["items"]}
        assert preview.json()["execution_id"] not in run_ids


@pytest.mark.asyncio
async def test_preview_purge_clears_artifacts_keeps_execution(session_factory):
    await _seed_orgs(session_factory)
    old_time = datetime.now(timezone.utc) - timedelta(days=8)

    async with session_factory() as db:
        execution = await create_execution(
            db,
            run_type="preview",
            kind=ExecutionKind.PREVIEW.value,
            organization_id=ORG_A,
            user_id=USER_OWNER,
            status=ExecutionStatus.COMPLETED.value,
            meta={"org_scenario_id": "sc-old", "preview": True},
        )
        execution.created_at = old_time
        collection = preview_collection_name(ORG_A)
        await create_content_item(
            db,
            content_hash="hash-preview-1",
            collection=collection,
            platform="fb",
            content_type="post",
            execution_id=execution.id,
            user_id=USER_OWNER,
            org_id=ORG_A,
        )
        db.add(
            ExecutionStep(
                id="step-preview-1",
                org_id=ORG_A,
                execution_id=execution.id,
                step_index=0,
                status="completed",
                artifacts_json=[{"type": "screenshot", "path": "/tmp/x.png"}],
            )
        )
        await db.commit()

        purged = await purge_stale_preview_artifacts(db, retention_days=7)
        await db.commit()
        assert purged == 1

        refreshed = await db.get(Execution, execution.id)
        assert refreshed is not None
        assert refreshed.meta.get("artifacts_purged") is True

        set_current_org_id(ORG_A)
        items = await db.execute(
            select(ContentItem).where(ContentItem.execution_id == execution.id)
        )
        assert list(items.scalars().all()) == []

        step = await db.execute(
            select(ExecutionStep).where(ExecutionStep.execution_id == execution.id)
        )
        step_row = step.scalar_one()
        assert step_row.artifacts_json == []


@pytest.mark.asyncio
async def test_preview_finish_does_not_re_evaluate_campaign(session_factory):
    await _seed_orgs(session_factory)
    set_current_org_id(ORG_A)

    with patch(
        "services.campaign.aggregator_scheduler.request_campaign_status_evaluation",
        new=AsyncMock(),
    ) as mock_eval:
        async with session_factory() as db:
            execution = await create_execution(
                db,
                run_type="preview",
                kind=ExecutionKind.PREVIEW.value,
                organization_id=ORG_A,
                user_id=USER_OWNER,
                status=ExecutionStatus.RUNNING.value,
            )
            from services.campaign.dispatcher import finish_fan_out_execution

            await finish_fan_out_execution(
                db,
                execution,
                org_id=ORG_A,
                actor_user_id=USER_OWNER,
                status="completed",
            )
            await db.commit()

    mock_eval.assert_not_called()


def test_resolve_content_collection_for_preview():
    from services.execution.preview_collection import resolve_content_collection

    coll = resolve_content_collection(
        {"collection": "default"},
        campaign_vars={"__PREVIEW_COLLECTION__": "preview:org-a"},
    )
    assert coll == "preview:org-a"
