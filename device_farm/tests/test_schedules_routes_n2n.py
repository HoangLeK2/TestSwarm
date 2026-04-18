from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.deps import _get_current_user, _get_db
from api.routes.schedules import router as schedules_router


def _fake_schedule(**overrides):
    now = datetime.now(timezone.utc)
    payload = {
        "id": "sched-1",
        "name": "Nightly",
        "description": "",
        "target_type": "campaign",
        "target_id": "camp-1",
        "inline_steps": None,
        "inline_variables": {},
        "device_group_id": None,
        "filter_state": "READY",
        "filter_model": None,
        "max_devices": None,
        "cron_expression": "*/30 * * * *",
        "timezone": "Asia/Ho_Chi_Minh",
        "random_delay_min": 0,
        "random_delay_max": 0,
        "stagger_devices": False,
        "stagger_interval_seconds": 60,
        "is_enabled": True,
        "last_run_at": None,
        "next_run_at": None,
        "run_count": 0,
        "user_id": "user-1",
        "created_at": now,
        "updated_at": now,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _build_app(scheduler: MagicMock) -> FastAPI:
    app = FastAPI()
    app.include_router(schedules_router, prefix="/api")
    app.state.scheduler = scheduler

    async def _db_override():
        yield AsyncMock()

    async def _user_override():
        return SimpleNamespace(id="user-1", role="user", is_active=True)

    app.dependency_overrides[_get_db] = _db_override
    app.dependency_overrides[_get_current_user] = _user_override
    return app


@pytest.mark.asyncio
async def test_create_fleet_requires_inline_steps():
    scheduler = MagicMock()
    app = _build_app(scheduler)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/api/schedules",
            json={
                "name": "Fleet runner",
                "target_type": "fleet",
                "cron_expression": "*/15 * * * *",
            },
        )
    assert resp.status_code == 400
    assert "inline_steps is required" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_patch_schedule_remaps_timezone_to_timezone_name():
    scheduler = MagicMock()
    scheduler.update = AsyncMock(return_value=_fake_schedule(timezone="UTC"))
    app = _build_app(scheduler)

    with patch("api.routes.schedules.get_schedule", new=AsyncMock(return_value=_fake_schedule())):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.patch("/api/schedules/sched-1", json={"timezone": "UTC"})

    assert resp.status_code == 200
    scheduler.update.assert_awaited_once()
    call = scheduler.update.await_args
    patch_payload = call.args[2] if len(call.args) >= 3 else call.kwargs["patch"]
    assert "timezone" not in patch_payload
    assert patch_payload["timezone_name"] == "UTC"


@pytest.mark.asyncio
async def test_run_now_returns_400_when_trigger_raises_value_error():
    scheduler = MagicMock()
    scheduler.trigger_now = AsyncMock(side_effect=ValueError("schedule is disabled"))
    app = _build_app(scheduler)

    with patch("api.routes.schedules.get_schedule", new=AsyncMock(return_value=_fake_schedule())):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/api/schedules/sched-1/run-now")

    assert resp.status_code == 400
    assert resp.json()["detail"] == "schedule is disabled"


@pytest.mark.asyncio
async def test_get_run_returns_404_when_run_belongs_to_other_schedule():
    scheduler = MagicMock()
    app = _build_app(scheduler)
    run = SimpleNamespace(
        id="run-1",
        schedule_id="sched-other",
        status="done",
        started_at=datetime.now(timezone.utc),
        finished_at=None,
        devices_dispatched=0,
        devices_succeeded=0,
        devices_failed=0,
        task_ids=[],
        error_message=None,
        created_at=datetime.now(timezone.utc),
    )

    with (
        patch("api.routes.schedules.get_schedule", new=AsyncMock(return_value=_fake_schedule(id="sched-1"))),
        patch("api.routes.schedules.get_schedule_run", new=AsyncMock(return_value=run)),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/schedules/sched-1/runs/run-1")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Run not found"
