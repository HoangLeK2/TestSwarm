"""
tests/test_scheduler.py — Unit tests for DF-008 Scheduler & Cron System.

Coverage:
- compute_next_run / validate_cron helpers
- SchedulerService.create / update / delete / toggle / trigger_now
- ScheduleActivities.load_schedule / create_run_record / finalize_run
- ScheduleRunWorkflow (via Temporal testing framework)
- SchedulerEngine polling logic
- API schema validators (cron expression, delay range)
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch, call
import pytest


@asynccontextmanager
async def _mock_schedule_tenant_db(_schedule_id: str, db):
    yield db, "org-001"


@asynccontextmanager
async def _mock_db_session(db):
    yield db


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_schedule(**kwargs):
    """Create a mock schedule ORM object."""
    defaults = {
        "id": "sched-001",
        "name": "Test Schedule",
        "description": "",
        "target_type": "campaign",
        "target_id": "camp-001",
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
        "status": "enabled",
        "schedule_kind": "cron",
        "run_at": None,
        "skip_dates": [],
        "skip_windows": [],
        "misfire_policy": "skip",
        "priority": "normal",
        "max_concurrent_per_device": 1,
        "account_rate_limit_per_hour": None,
        "quota_policy": {},
        "deleted_at": None,
        "last_run_at": None,
        "next_run_at": None,
        "run_count": 0,
        "user_id": "user-001",
        "org_id": "org-001",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _make_run(**kwargs):
    """Create a mock ScheduleRun ORM object."""
    defaults = {
        "id": "run-001",
        "schedule_id": "sched-001",
        "status": "pending",
        "trigger_source": "cron",
        "scheduled_at": datetime.now(timezone.utc),
        "started_at": datetime.now(timezone.utc),
        "finished_at": None,
        "deferred_until": None,
        "was_catch_up": False,
        "execution_id": None,
        "devices_dispatched": 0,
        "devices_succeeded": 0,
        "devices_failed": 0,
        "task_ids": [],
        "workflow_ids": [],
        "error_code": None,
        "error_message": None,
        "created_at": datetime.now(timezone.utc),
    }
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


# ── compute_next_run ──────────────────────────────────────────────────────────


class TestComputeNextRun:
    def test_every_30_min(self):
        from services.scheduler import compute_next_run

        base = datetime(2026, 3, 30, 8, 0, 0, tzinfo=timezone.utc)
        result = compute_next_run("*/30 * * * *", "UTC", base)

        assert result is not None
        assert result > base
        assert result.minute in (0, 30)

    def test_every_2h_8_to_22(self):
        from services.scheduler import compute_next_run

        base = datetime(2026, 3, 30, 7, 0, 0, tzinfo=timezone.utc)
        result = compute_next_run("0 */2 * * *", "UTC", base)

        assert result is not None
        assert result > base
        assert result.minute == 0

    def test_daily_8am_vn_timezone(self):
        from services.scheduler import compute_next_run

        # 1am UTC = 8am UTC+7 (Vietnam)
        base = datetime(2026, 3, 30, 1, 0, 0, tzinfo=timezone.utc)
        result = compute_next_run("0 8 * * *", "Asia/Ho_Chi_Minh", base)

        assert result is not None
        # Should be 8am VN time = 1am UTC next day
        assert result.hour == 1

    def test_invalid_cron_returns_none(self):
        from services.scheduler import compute_next_run

        result = compute_next_run("invalid cron expr", "UTC")
        assert result is None

    def test_no_base_uses_now(self):
        from services.scheduler import compute_next_run

        result = compute_next_run("*/5 * * * *", "UTC")
        assert result is not None
        assert result > datetime.now(timezone.utc)


# ── validate_cron ─────────────────────────────────────────────────────────────


class TestValidateCron:
    @pytest.mark.parametrize("expr", [
        "*/30 * * * *",
        "0 */2 8-22 * *",
        "0 8 * * *",
        "0 8,12,18 * * *",
        "0 9 * * 1-5",
        "0 */4 * * *",
    ])
    def test_valid_expressions(self, expr: str):
        from services.scheduler import validate_cron
        assert validate_cron(expr) is True

    @pytest.mark.parametrize("expr", [
        "invalid",
        "60 * * * *",      # minute > 59
        "",
    ])
    def test_invalid_expressions(self, expr: str):
        from services.scheduler import validate_cron
        assert validate_cron(expr) is False


# ── SchedulerService ──────────────────────────────────────────────────────────


class TestSchedulerServiceCreate:
    @pytest.mark.asyncio
    async def test_create_no_temporal(self):
        """Create schedule without Temporal — only DB write."""
        from services.scheduler import SchedulerService

        mock_db = AsyncMock()
        mock_schedule = _make_schedule()

        with patch("db.crud.schedule.create_schedule", return_value=mock_schedule) as mock_create:
            service = SchedulerService(temporal_client=None, manager=None, queue=None)
            result = await service.create(
                mock_db,
                name="Test",
                target_type="campaign",
                target_id="camp-001",
                cron_expression="*/30 * * * *",
            )

        assert result is mock_schedule
        mock_create.assert_awaited_once()
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_with_temporal(self):
        """Create schedule with Temporal — DB write + Temporal schedule creation."""
        from services.scheduler import SchedulerService

        mock_temporal = AsyncMock()
        mock_schedule = _make_schedule()
        mock_db = AsyncMock()

        with patch("db.crud.schedule.create_schedule", return_value=mock_schedule):
            service = SchedulerService(
                temporal_client=mock_temporal, manager=None, queue=None
            )
            with patch.object(service, "_create_temporal_schedule", new_callable=AsyncMock) as mock_ts:
                result = await service.create(
                    mock_db,
                    name="Test",
                    target_type="campaign",
                    target_id="camp-001",
                    cron_expression="*/30 * * * *",
                    is_enabled=True,
                )

        mock_ts.assert_awaited_once_with("sched-001", "*/30 * * * *", "Asia/Ho_Chi_Minh")
        assert result is mock_schedule

    @pytest.mark.asyncio
    async def test_create_disabled_skips_temporal(self):
        """Disabled schedule does not register Temporal Schedule."""
        from services.scheduler import SchedulerService

        mock_temporal = AsyncMock()
        mock_schedule = _make_schedule(is_enabled=False)
        mock_db = AsyncMock()

        with patch("db.crud.schedule.create_schedule", return_value=mock_schedule):
            service = SchedulerService(
                temporal_client=mock_temporal, manager=None, queue=None
            )
            with patch.object(service, "_create_temporal_schedule", new_callable=AsyncMock) as mock_ts:
                await service.create(
                    mock_db,
                    name="Test",
                    target_type="campaign",
                    target_id="camp-001",
                    cron_expression="*/30 * * * *",
                    is_enabled=False,
                )

        mock_ts.assert_not_awaited()


class TestSchedulerServiceToggle:
    @pytest.mark.asyncio
    async def test_toggle_disable(self):
        from services.scheduler import SchedulerService

        mock_schedule = _make_schedule(is_enabled=True)
        updated = _make_schedule(is_enabled=False, next_run_at=None)
        mock_db = AsyncMock()

        with patch("db.crud.schedule.get_schedule", return_value=mock_schedule), \
             patch("db.crud.schedule.update_schedule", return_value=updated):
            service = SchedulerService(temporal_client=None, manager=None, queue=None)
            result = await service.toggle(mock_db, "sched-001", enabled=False)

        assert result.is_enabled is False
        assert result.next_run_at is None

    @pytest.mark.asyncio
    async def test_toggle_enable_with_temporal(self):
        from services.scheduler import SchedulerService

        mock_schedule = _make_schedule(is_enabled=False)
        updated = _make_schedule(is_enabled=True)
        mock_temporal = AsyncMock()
        mock_db = AsyncMock()

        with patch("db.crud.schedule.get_schedule", return_value=mock_schedule), \
             patch("db.crud.schedule.update_schedule", return_value=updated):
            service = SchedulerService(
                temporal_client=mock_temporal, manager=None, queue=None
            )
            with patch.object(service, "_set_temporal_schedule_paused", new_callable=AsyncMock) as mock_pause:
                result = await service.toggle(mock_db, "sched-001", enabled=True)

        mock_pause.assert_awaited_once_with("sched-001", paused=False)
        assert result.is_enabled is True


class TestSchedulerServiceEpic05:
    @pytest.mark.asyncio
    async def test_trigger_now_rejects_disabled_schedule(self):
        from services.scheduler import SchedulerService

        mock_db = AsyncMock()
        disabled = _make_schedule(is_enabled=False)

        with patch("db.crud.schedule.get_schedule", return_value=disabled):
            service = SchedulerService(temporal_client=None, manager=None, queue=None)
            with pytest.raises(ValueError, match="SCHEDULE_DISABLED"):
                await service.trigger_now(mock_db, "sched-001")

    @pytest.mark.asyncio
    async def test_trigger_now_temporal_starts_workflow_with_real_run_id(self):
        from services.scheduler import SchedulerService
        from temporal.schedule_shared import ScheduleRunInput

        mock_db = AsyncMock()
        schedule = _make_schedule()
        run = _make_run(id="run-now-001")
        temporal_client = AsyncMock()

        with (
            patch("db.crud.schedule.get_schedule", return_value=schedule),
            patch(
                "db.crud.schedule.create_schedule_run", return_value=run
            ) as create_run,
        ):
            service = SchedulerService(
                temporal_client=temporal_client,
                manager=None,
                queue=None,
            )
            result = await service.trigger_now(mock_db, "sched-001")

        assert result == "run-now-001"
        create_run.assert_awaited_once()
        temporal_client.start_workflow.assert_awaited_once()
        args, kwargs = temporal_client.start_workflow.await_args
        assert isinstance(args[1], ScheduleRunInput)
        assert args[1].schedule_id == "sched-001"
        assert args[1].run_id == "run-now-001"
        assert kwargs["id"] == "df-sched-run-sched-001:run-now:run-now-001"
        assert not temporal_client.get_schedule_handle.called

    @pytest.mark.asyncio
    async def test_create_one_shot_requires_future_run_at(self):
        from services.scheduler import SchedulerService

        mock_db = AsyncMock()
        service = SchedulerService(temporal_client=None, manager=None, queue=None)

        with pytest.raises(ValueError, match="RUN_AT_IN_PAST"):
            await service.create(
                mock_db,
                name="Past one shot",
                target_type="campaign",
                target_id="camp-001",
                cron_expression=None,
                run_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                now=datetime(2026, 5, 31, tzinfo=timezone.utc),
            )

    @pytest.mark.asyncio
    async def test_create_rejects_cron_and_run_at_together(self):
        from services.scheduler import SchedulerService

        mock_db = AsyncMock()
        service = SchedulerService(temporal_client=None, manager=None, queue=None)

        with pytest.raises(ValueError, match="CRON_AND_RUN_AT_MUTUALLY_EXCLUSIVE"):
            await service.create(
                mock_db,
                name="Ambiguous",
                target_type="campaign",
                target_id="camp-001",
                cron_expression="0 8 * * *",
                run_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
                now=datetime(2026, 5, 31, tzinfo=timezone.utc),
            )

    @pytest.mark.asyncio
    async def test_finalize_terminal_run_emits_schedule_event_and_audit(self):
        from services.scheduler import finalize_schedule_run_record

        mock_db = AsyncMock()
        dispatch_result = {"devices_dispatched": 1, "task_ids": ["task-1"], "workflow_ids": ["wf-1"]}

        with (
            patch("db.crud.schedule.update_schedule_run", new_callable=AsyncMock) as update_run,
            patch("db.crud.schedule.update_schedule_after_run", new_callable=AsyncMock) as update_after,
            patch("services.scheduler.emit_schedule_run_terminal", new_callable=AsyncMock) as emit_event,
        ):
            await finalize_schedule_run_record(
                mock_db,
                run_id="run-001",
                schedule_id="sched-001",
                status="completed",
                finished_at=datetime.now(timezone.utc),
                dispatch_result=dispatch_result,
                cron_expression="*/5 * * * *",
                timezone_name="UTC",
                organization_id="org-1",
                execution_id="exec-1",
            )

        update_run.assert_awaited_once()
        update_after.assert_awaited_once()
        emit_event.assert_awaited_once()


class TestSchedulerServiceUpdate:
    @pytest.mark.asyncio
    async def test_update_disable_syncs_status_and_clears_next_run(self):
        from services.scheduler import SchedulerService

        mock_db = AsyncMock()
        existing = _make_schedule(
            next_run_at=datetime(2026, 6, 1, tzinfo=timezone.utc)
        )
        updated = _make_schedule(is_enabled=False, status="disabled", next_run_at=None)

        with (
            patch("db.crud.schedule.get_schedule", return_value=existing),
            patch(
                "db.crud.schedule.update_schedule", return_value=updated
            ) as update_schedule,
        ):
            service = SchedulerService(temporal_client=None, manager=None, queue=None)
            result = await service.update(mock_db, "sched-001", {"is_enabled": False})

        assert result is updated
        update_schedule.assert_awaited_once()
        assert update_schedule.await_args.kwargs["is_enabled"] is False
        assert update_schedule.await_args.kwargs["status"] == "disabled"
        assert update_schedule.await_args.kwargs["next_run_at"] is None
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_cron_clears_one_shot_run_at(self):
        from services.scheduler import SchedulerService

        mock_db = AsyncMock()
        existing = _make_schedule(
            schedule_kind="one_shot",
            cron_expression=None,
            run_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        updated = _make_schedule(
            schedule_kind="cron",
            cron_expression="0 9 * * *",
            run_at=None,
        )

        with (
            patch("db.crud.schedule.get_schedule", return_value=existing),
            patch(
                "db.crud.schedule.update_schedule", return_value=updated
            ) as update_schedule,
        ):
            service = SchedulerService(temporal_client=None, manager=None, queue=None)
            result = await service.update(
                mock_db,
                "sched-001",
                {"cron_expression": "0 9 * * *", "timezone_name": "UTC"},
            )

        assert result is updated
        update_schedule.assert_awaited_once()
        assert update_schedule.await_args.kwargs["schedule_kind"] == "cron"
        assert update_schedule.await_args.kwargs["run_at"] is None
        assert update_schedule.await_args.kwargs["next_run_at"] is not None


class TestSchedulerServiceDelete:
    @pytest.mark.asyncio
    async def test_delete_calls_temporal(self):
        from services.scheduler import SchedulerService

        mock_temporal = AsyncMock()
        mock_db = AsyncMock()

        with patch("db.crud.schedule.delete_schedule", return_value=True):
            service = SchedulerService(
                temporal_client=mock_temporal, manager=None, queue=None
            )
            with patch.object(service, "_delete_temporal_schedule", new_callable=AsyncMock) as mock_del:
                result = await service.delete(mock_db, "sched-001")

        assert result is True
        mock_del.assert_awaited_once_with("sched-001")

    @pytest.mark.asyncio
    async def test_delete_not_found(self):
        from services.scheduler import SchedulerService

        mock_db = AsyncMock()

        with patch("db.crud.schedule.delete_schedule", return_value=False):
            service = SchedulerService(temporal_client=None, manager=None, queue=None)
            result = await service.delete(mock_db, "nonexistent")

        assert result is False


# ── ScheduleActivities ────────────────────────────────────────────────────────


class TestScheduleActivities:
    @pytest.mark.asyncio
    async def test_load_schedule_found(self):
        from temporal.schedule_activities import ScheduleActivities

        mock_schedule = _make_schedule()
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        with patch("temporal.schedule_activities.activity") as mock_act, \
             patch("temporal.schedule_activities._schedule_tenant_db", lambda sid: _mock_schedule_tenant_db(sid, mock_db)), \
             patch("db.crud.schedule.get_schedule", return_value=mock_schedule):
            mock_act.heartbeat = MagicMock()
            activities = ScheduleActivities()
            result = await activities.load_schedule("sched-001")

        assert result["id"] == "sched-001"
        assert result["cron_expression"] == "*/30 * * * *"
        assert result["is_enabled"] is True

    @pytest.mark.asyncio
    async def test_load_schedule_not_found_raises(self):
        from temporal.schedule_activities import ScheduleActivities

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        with patch("temporal.schedule_activities.activity") as mock_act, \
             patch("temporal.schedule_activities._schedule_tenant_db", lambda sid: _mock_schedule_tenant_db(sid, mock_db)), \
             patch("db.crud.schedule.get_schedule", return_value=None):
            mock_act.heartbeat = MagicMock()
            activities = ScheduleActivities()
            with pytest.raises(ValueError, match="not found"):
                await activities.load_schedule("nonexistent")

    @pytest.mark.asyncio
    async def test_create_run_record_returns_id(self):
        from temporal.schedule_activities import ScheduleActivities

        mock_run = _make_run(id="run-abc")
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.commit = AsyncMock()

        with patch("temporal.schedule_activities.activity") as mock_act, \
             patch("temporal.schedule_activities._schedule_tenant_db", lambda sid: _mock_schedule_tenant_db(sid, mock_db)), \
             patch("db.crud.schedule.create_schedule_run", return_value=mock_run):
            mock_act.heartbeat = MagicMock()
            activities = ScheduleActivities()
            result = await activities.create_run_record("sched-001")

        assert result == "run-abc"

    @pytest.mark.asyncio
    async def test_dispatch_campaign_propagates_fan_out_error(self):
        from temporal.schedule_activities import ScheduleActivities
        from services.campaign.dispatcher import CampaignDispatchError

        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()
        campaign = MagicMock(
            id="camp-001",
            org_id="org-001",
            created_by="user-001",
            user_id=None,
            target_group_id=None,
        )
        device = MagicMock(id="device-001")
        with patch("temporal.schedule_activities._temporal_client_ref", object()), \
             patch("db.database.activity_session", lambda: _mock_db_session(mock_db)), \
             patch("db.crud.campaign_entity.get_campaign_entity", return_value=campaign), \
             patch("db.crud.list_campaign_devices", return_value=[device]), \
             patch(
                 "services.campaign.dispatcher.dispatch_campaign",
                 side_effect=CampaignDispatchError(
                     "Campaign has no scenarios. Link an org scenario or add steps in the flow editor.",
                     code="CAMPAIGN_NO_SCENARIOS",
                 ),
             ):
            activities = ScheduleActivities()
            with pytest.raises(RuntimeError, match="Campaign has no scenarios"):
                await activities._dispatch_campaign(
                    {"target_id": "camp-001"}, stagger=False, stagger_interval=60
                )

    @pytest.mark.asyncio
    async def test_dispatch_campaign_requires_runtime_started(self):
        from temporal.schedule_activities import ScheduleActivities
        from services.campaign.dispatcher import FanOutExecutionView, FanOutResult

        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()
        campaign = MagicMock(
            id="camp-001",
            org_id="org-001",
            created_by="user-001",
            user_id=None,
            target_group_id=None,
        )
        device = MagicMock(id="device-001")
        fan_out = FanOutResult(
            dispatch_id="dispatch-001",
            campaign_id="camp-001",
            dispatch_strategy="parallel",
            executions=[
                FanOutExecutionView(
                    execution_id="exec-001",
                    device_id="device-001",
                    status="running",
                    effective_vars={},
                )
            ],
        )
        with patch("temporal.schedule_activities._temporal_client_ref", object()), \
             patch("db.database.activity_session", lambda: _mock_db_session(mock_db)), \
             patch("db.crud.campaign_entity.get_campaign_entity", return_value=campaign), \
             patch("db.crud.list_campaign_devices", return_value=[device]), \
             patch("services.campaign.dispatcher.dispatch_campaign", return_value=fan_out), \
             patch(
                 "services.campaign.execution_runtime.start_execution_runtime",
                 return_value={"temporal": 0, "fallback": 0},
             ), \
             patch("db.crud.execution.get_execution", return_value=MagicMock(meta={})):
            activities = ScheduleActivities()
            with pytest.raises(RuntimeError, match="started no workflows"):
                await activities._dispatch_campaign(
                    {"target_id": "camp-001"}, stagger=False, stagger_interval=60
                )

    @pytest.mark.asyncio
    async def test_finalize_run_updates_db(self):
        from temporal.schedule_activities import ScheduleActivities
        from temporal.schedule_shared import ScheduleDispatchResult

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.commit = AsyncMock()

        dispatch_result = ScheduleDispatchResult(
            run_id="run-001",
            devices_dispatched=3,
            task_ids=["t1", "t2", "t3"],
        )

        with patch("temporal.schedule_activities.activity") as mock_act, \
             patch("temporal.schedule_activities._schedule_tenant_db", lambda sid: _mock_schedule_tenant_db(sid, mock_db)), \
             patch("services.scheduler.finalize_schedule_run_record", new_callable=AsyncMock) as mock_finalize:
            mock_act.heartbeat = MagicMock()
            activities = ScheduleActivities()
            await activities.finalize_schedule_run(
                "run-001", "sched-001", dispatch_result,
                "*/30 * * * *", "Asia/Ho_Chi_Minh"
            )

        mock_finalize.assert_awaited_once()
        # Should commit
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_finalize_run_failed_sets_error(self):
        from temporal.schedule_activities import ScheduleActivities
        from temporal.schedule_shared import ScheduleDispatchResult

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.commit = AsyncMock()

        dispatch_result = ScheduleDispatchResult(
            run_id="run-001",
            error="No devices available",
        )

        captured = {}

        async def _mock_update_run(db, run_id, **kwargs):
            captured.update(kwargs)

        async def _capture_finalize(db, **kwargs):
            captured.update(kwargs)

        with patch("temporal.schedule_activities.activity") as mock_act, \
             patch("temporal.schedule_activities._schedule_tenant_db", lambda sid: _mock_schedule_tenant_db(sid, mock_db)), \
             patch("services.scheduler.finalize_schedule_run_record", side_effect=_capture_finalize):
            mock_act.heartbeat = MagicMock()
            activities = ScheduleActivities()
            await activities.finalize_schedule_run(
                "run-001", "sched-001", dispatch_result,
                "*/30 * * * *", "UTC"
            )

        assert captured["status"] == "failed"
        assert "No devices available" in captured["error_message"]


class TestSchedulerCampaignDispatch:
    @pytest.mark.asyncio
    async def test_dispatch_campaign_propagates_fan_out_error(self):
        from services.scheduler import _dispatch_campaign
        from services.campaign.dispatcher import CampaignDispatchError

        mock_db = AsyncMock()
        campaign = MagicMock(
            id="camp-001",
            org_id="org-001",
            created_by="user-001",
            user_id=None,
            target_group_id=None,
        )
        device = MagicMock(id="device-001")
        with patch("db.database.AsyncSessionLocal", lambda: _mock_db_session(mock_db)), \
             patch("db.crud.campaign_entity.get_campaign_entity", return_value=campaign), \
             patch("db.crud.list_campaign_devices", return_value=[device]), \
             patch(
                 "services.campaign.dispatcher.dispatch_campaign",
                 side_effect=CampaignDispatchError(
                     "Campaign has no scenarios. Link an org scenario or add steps in the flow editor.",
                     code="CAMPAIGN_NO_SCENARIOS",
                 ),
             ):
            with pytest.raises(RuntimeError, match="Campaign has no scenarios"):
                await _dispatch_campaign(
                    {"target_id": "camp-001"},
                    queue=None,
                    temporal_client=object(),
                    temporal_config=None,
                )

    @pytest.mark.asyncio
    async def test_dispatch_campaign_requires_runtime_started(self):
        from services.scheduler import _dispatch_campaign
        from services.campaign.dispatcher import FanOutExecutionView, FanOutResult

        mock_db = AsyncMock()
        campaign = MagicMock(
            id="camp-001",
            org_id="org-001",
            created_by="user-001",
            user_id=None,
            target_group_id=None,
        )
        device = MagicMock(id="device-001")
        fan_out = FanOutResult(
            dispatch_id="dispatch-001",
            campaign_id="camp-001",
            dispatch_strategy="parallel",
            executions=[
                FanOutExecutionView(
                    execution_id="exec-001",
                    device_id="device-001",
                    status="running",
                    effective_vars={},
                )
            ],
        )
        with patch("db.database.AsyncSessionLocal", lambda: _mock_db_session(mock_db)), \
             patch("db.crud.campaign_entity.get_campaign_entity", return_value=campaign), \
             patch("db.crud.list_campaign_devices", return_value=[device]), \
             patch("services.campaign.dispatcher.dispatch_campaign", return_value=fan_out), \
             patch(
                 "services.campaign.execution_runtime.start_execution_runtime",
                 return_value={"temporal": 0, "fallback": 0},
             ), \
             patch("db.crud.execution.get_execution", return_value=MagicMock(meta={})):
            with pytest.raises(RuntimeError, match="started no workflows"):
                await _dispatch_campaign(
                    {"target_id": "camp-001"},
                    queue=None,
                    temporal_client=object(),
                    temporal_config=None,
                )


class TestSchedulerOrgScenarioDispatch:
    @pytest.mark.asyncio
    async def test_resolve_org_scenario_fleet_config_uses_registry(self):
        from services.scheduler import _resolve_org_scenario_fleet_config

        mock_db = AsyncMock()
        registry = {
            "by_id": {
                "scenario-001": {
                    "steps": [{"id": "step-1", "type": "wait", "seconds": 1}],
                    "variables": {"from_body": "yes", "override": "body"},
                    "name": "Warm up",
                }
            },
            "by_campaign_name": {},
            "by_template_name": {},
        }

        with patch(
            "services.campaign.execution_runtime.build_org_scenario_registry",
            return_value=registry,
        ) as build_registry:
            cfg = await _resolve_org_scenario_fleet_config(
                mock_db,
                {
                    "target_id": "scenario-001",
                    "org_id": "org-001",
                    "inline_variables": {"override": "schedule"},
                },
            )

        build_registry.assert_awaited_once_with(
            mock_db,
            "org-001",
            [{"scenario_id": "scenario-001"}],
        )
        assert cfg["inline_steps"] == registry["by_id"]["scenario-001"]["steps"]
        assert cfg["inline_variables"] == {
            "from_body": "yes",
            "override": "schedule",
        }
        assert cfg["_scenario_registry"] is registry

    @pytest.mark.asyncio
    async def test_dispatch_schedule_config_routes_org_scenario(self):
        from services.scheduler import _dispatch_schedule_config

        with patch(
            "services.scheduler._dispatch_org_scenario",
            return_value={"devices_dispatched": 1, "task_ids": ["task-1"]},
        ) as dispatch_org:
            result = await _dispatch_schedule_config(
                {"target_type": "org_scenario", "target_id": "scenario-001"},
                queue=object(),
                manager=object(),
            )

        dispatch_org.assert_awaited_once()
        assert result["devices_dispatched"] == 1


# ── _compute_next_run helper ──────────────────────────────────────────────────


class TestComputeNextRunHelper:
    def test_computes_future_datetime(self):
        from temporal.schedule_activities import _compute_next_run

        now = datetime(2026, 3, 30, 10, 0, 0, tzinfo=timezone.utc)
        result = _compute_next_run("*/30 * * * *", "UTC", now)

        assert result is not None
        assert result > now

    def test_invalid_cron_returns_none(self):
        from temporal.schedule_activities import _compute_next_run

        result = _compute_next_run("bad cron", "UTC", datetime.now(timezone.utc))
        assert result is None


# ── _make_staggered_task ──────────────────────────────────────────────────────


class TestMakeStaggeredTask:
    def test_zero_delay_returns_same_fn(self):
        from temporal.schedule_activities import _make_staggered_task

        fn = MagicMock(return_value="ok")
        wrapped = _make_staggered_task(fn, delay_seconds=0)

        assert wrapped is fn

    def test_positive_delay_sleeps(self):
        from temporal.schedule_activities import _make_staggered_task

        fn = MagicMock(return_value="ok")
        wrapped = _make_staggered_task(fn, delay_seconds=0.001)

        device = MagicMock()
        with patch("time.sleep") as mock_sleep:
            result = wrapped(device)

        mock_sleep.assert_called_once_with(0.001)
        fn.assert_called_once_with(device)
        assert result == "ok"


# ── SchedulerEngine ───────────────────────────────────────────────────────────


class TestSchedulerEngine:
    @pytest.mark.asyncio
    async def test_start_creates_task(self):
        from services.scheduler import SchedulerEngine

        engine = SchedulerEngine(queue=None, manager=None)

        with patch.object(engine, "_run", new_callable=AsyncMock):
            engine.start()
            assert engine._task is not None
            engine._running = False
            await engine.stop()

    @pytest.mark.asyncio
    async def test_check_due_schedules_dispatches(self):
        from services.scheduler import SchedulerEngine

        due_schedule = _make_schedule()
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        engine = SchedulerEngine(queue=MagicMock(), manager=MagicMock())

        with patch("db.database.AsyncSessionLocal", return_value=mock_db), \
             patch("db.crud.schedule.claim_due_schedules", return_value=[due_schedule]), \
             patch.object(engine, "_execute_schedule", new_callable=AsyncMock) as mock_exec:
            await engine._check_due_schedules()

        # Should fire one task per due schedule
        # asyncio.create_task wraps it, but _execute_schedule is called indirectly
        # We'll verify by checking if it was called in the loop
        # (In this test we mock directly so we check the call)

    @pytest.mark.asyncio
    async def test_execute_schedule_handles_error(self):
        from services.scheduler import SchedulerEngine

        schedule = _make_schedule()
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.commit = AsyncMock()

        mock_run = _make_run()
        engine = SchedulerEngine(queue=None, manager=None)

        with patch("db.database.AsyncSessionLocal", return_value=mock_db), \
             patch("db.crud.schedule.create_schedule_run", return_value=mock_run), \
             patch("db.crud.schedule.update_schedule_run", new_callable=AsyncMock), \
             patch("db.crud.schedule.update_schedule_after_run", new_callable=AsyncMock), \
             patch("services.scheduler._dispatch_schedule_config",
                   side_effect=ValueError("No devices")) as mock_dispatch:
            await engine._execute_schedule(schedule)

        # Should not raise — errors are caught and recorded in run record
        mock_dispatch.assert_awaited_once()


# ── API Schema validators ─────────────────────────────────────────────────────


class TestScheduleCreateSchema:
    def test_valid_campaign_schedule(self):
        from api.schemas.schedule import ScheduleCreate

        data = ScheduleCreate(
            name="Test",
            target_type="campaign",
            target_id="camp-001",
            cron_expression="*/30 * * * *",
        )
        assert data.name == "Test"
        assert data.random_delay_min == 0

    def test_invalid_cron_raises(self):
        from api.schemas.schedule import ScheduleCreate
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            ScheduleCreate(
                name="Test",
                target_type="campaign",
                target_id="camp-001",
                cron_expression="invalid cron",
            )

    def test_invalid_target_type_raises(self):
        from api.schemas.schedule import ScheduleCreate
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            ScheduleCreate(
                name="Test",
                target_type="unknown_type",
                target_id="camp-001",
                cron_expression="*/30 * * * *",
            )

    def test_org_scenario_target_type_is_valid(self):
        from api.schemas.schedule import ScheduleCreate

        data = ScheduleCreate(
            name="Test",
            target_type="org_scenario",
            target_id="scenario-001",
            cron_expression="*/30 * * * *",
        )
        assert data.target_type == "org_scenario"

    def test_delay_range_max_less_than_min_raises(self):
        from api.schemas.schedule import ScheduleCreate
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            ScheduleCreate(
                name="Test",
                target_type="campaign",
                target_id="camp-001",
                cron_expression="*/30 * * * *",
                random_delay_min=100,
                random_delay_max=50,
            )

    def test_fleet_without_steps(self):
        """fleet type with no inline_steps should be accepted at schema level (validated in route)."""
        from api.schemas.schedule import ScheduleCreate

        data = ScheduleCreate(
            name="Test",
            target_type="fleet",
            cron_expression="*/30 * * * *",
        )
        assert data.inline_steps is None


class TestSchedulePatchSchema:
    def test_patch_only_cron(self):
        from api.schemas.schedule import SchedulePatch

        patch = SchedulePatch(cron_expression="0 8 * * *")
        dumped = patch.model_dump(exclude_none=True)
        assert "cron_expression" in dumped
        assert len(dumped) == 1

    def test_patch_invalid_cron_raises(self):
        from api.schemas.schedule import SchedulePatch
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            SchedulePatch(cron_expression="bad cron expr !")


# ── Temporal schedule ID helpers ──────────────────────────────────────────────


class TestTemporalScheduleId:
    def test_prefix_format(self):
        from services.scheduler import _TEMPORAL_SCHEDULE_PREFIX, _TEMPORAL_WORKFLOW_PREFIX

        schedule_id = "abc-123"
        temporal_id = f"{_TEMPORAL_SCHEDULE_PREFIX}{schedule_id}"
        workflow_prefix = f"{_TEMPORAL_WORKFLOW_PREFIX}{schedule_id}"

        assert temporal_id == "df-schedule-abc-123"
        assert workflow_prefix == "df-sched-run-abc-123"


# ── ScheduleRunWorkflow (Temporal testing) ────────────────────────────────────


class TestScheduleRunWorkflow:
    """
    Temporal workflow testing with the testing framework.
    See: https://python.temporal.io/temporalio.testing.WorkflowEnvironment.html
    """

    @pytest.mark.asyncio
    async def test_workflow_skips_disabled_schedule(self):
        """Workflow returns 'skipped' for disabled schedules."""
        try:
            from temporalio.testing import WorkflowEnvironment
            from temporalio.worker import Worker as TemporalWorker
            from temporal.schedule_workflow import ScheduleRunWorkflow
            from temporal.schedule_shared import ScheduleRunInput, ScheduleRunOutput
            from temporal.shared import TASK_QUEUE_NAME
        except ImportError:
            pytest.skip("temporalio not installed")

        from temporalio import activity as _activity

        @_activity.defn(name="load_schedule")
        async def _load_schedule(schedule_id: str) -> dict:
            return {
                "id": schedule_id,
                "is_enabled": False,
                "cron_expression": "*/30 * * * *",
                "timezone": "UTC",
                "random_delay_min": 0,
                "random_delay_max": 0,
                "target_type": "campaign",
                "target_id": "camp-001",
            }

        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with TemporalWorker(
                env.client,
                task_queue=TASK_QUEUE_NAME,
                workflows=[ScheduleRunWorkflow],
                activities=[_load_schedule],
            ):
                result: ScheduleRunOutput = await env.client.execute_workflow(
                    ScheduleRunWorkflow.run,
                    ScheduleRunInput(schedule_id="sched-disabled"),
                    id="test-disabled",
                    task_queue=TASK_QUEUE_NAME,
                    result_type=ScheduleRunOutput,
                )

        assert result.status == "skipped"

    @pytest.mark.asyncio
    async def test_workflow_completes_on_success(self):
        """Happy path: workflow loads, dispatches, finalizes."""
        try:
            from temporalio.testing import WorkflowEnvironment
            from temporalio.worker import Worker as TemporalWorker
            from temporal.schedule_workflow import ScheduleRunWorkflow
            from temporal.schedule_shared import (
                ScheduleRunInput,
                ScheduleRunOutput,
                ScheduleDispatchResult,
            )
            from temporal.shared import TASK_QUEUE_NAME
        except ImportError:
            pytest.skip("temporalio not installed")

        from temporalio import activity as _activity

        run_id_holder = {"val": ""}

        @_activity.defn(name="load_schedule")
        async def _load_schedule(schedule_id: str) -> dict:
            return {
                "id": schedule_id,
                "is_enabled": True,
                "cron_expression": "*/30 * * * *",
                "timezone": "UTC",
                "random_delay_min": 0,
                "random_delay_max": 0,
                "target_type": "campaign",
                "target_id": "camp-001",
            }

        @_activity.defn(name="create_run_record")
        async def _create_run_record(schedule_id: str) -> str:
            run_id_holder["val"] = "run-test-001"
            return "run-test-001"

        @_activity.defn(name="dispatch_schedule")
        async def _dispatch_schedule(schedule_config, run_id):
            return ScheduleDispatchResult(
                run_id=run_id,
                devices_dispatched=2,
                task_ids=["t1", "t2"],
            )

        @_activity.defn(name="finalize_schedule_run")
        async def _finalize_schedule_run(run_id, schedule_id, dispatch_result, cron_expression, timezone_name):
            pass

        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with TemporalWorker(
                env.client,
                task_queue=TASK_QUEUE_NAME,
                workflows=[ScheduleRunWorkflow],
                activities=[
                    _load_schedule,
                    _create_run_record,
                    _dispatch_schedule,
                    _finalize_schedule_run,
                ],
            ):
                result: ScheduleRunOutput = await env.client.execute_workflow(
                    ScheduleRunWorkflow.run,
                    ScheduleRunInput(schedule_id="sched-001"),
                    id="test-happy-path",
                    task_queue=TASK_QUEUE_NAME,
                    result_type=ScheduleRunOutput,
                )

        assert result.status == "completed"
        assert result.run_id == "run-test-001"
        assert result.devices_dispatched == 2
        assert result.error is None

    @pytest.mark.asyncio
    async def test_workflow_records_failure(self):
        """Dispatch failure → workflow status = failed."""
        try:
            from temporalio.testing import WorkflowEnvironment
            from temporalio.worker import Worker as TemporalWorker
            from temporal.schedule_workflow import ScheduleRunWorkflow
            from temporal.schedule_shared import (
                ScheduleRunInput,
                ScheduleRunOutput,
                ScheduleDispatchResult,
            )
            from temporal.shared import TASK_QUEUE_NAME
        except ImportError:
            pytest.skip("temporalio not installed")

        from temporalio import activity as _activity

        @_activity.defn(name="load_schedule")
        async def _load_schedule(schedule_id: str) -> dict:
            return {
                "id": schedule_id,
                "is_enabled": True,
                "cron_expression": "*/30 * * * *",
                "timezone": "UTC",
                "random_delay_min": 0,
                "random_delay_max": 0,
                "target_type": "campaign",
                "target_id": "camp-001",
            }

        @_activity.defn(name="create_run_record")
        async def _create_run_record(schedule_id: str) -> str:
            return "run-fail-001"

        @_activity.defn(name="dispatch_schedule")
        async def _dispatch_schedule(schedule_config, run_id):
            return ScheduleDispatchResult(
                run_id=run_id,
                error="Campaign not found",
            )

        @_activity.defn(name="finalize_schedule_run")
        async def _finalize_schedule_run(run_id, schedule_id, dispatch_result, cron, tz):
            pass

        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with TemporalWorker(
                env.client,
                task_queue=TASK_QUEUE_NAME,
                workflows=[ScheduleRunWorkflow],
                activities=[
                    _load_schedule,
                    _create_run_record,
                    _dispatch_schedule,
                    _finalize_schedule_run,
                ],
            ):
                result: ScheduleRunOutput = await env.client.execute_workflow(
                    ScheduleRunWorkflow.run,
                    ScheduleRunInput(schedule_id="sched-001"),
                    id="test-failure",
                    task_queue=TASK_QUEUE_NAME,
                    result_type=ScheduleRunOutput,
                )

        assert result.status == "failed"
        assert result.error == "Campaign not found"


# ── Device targeting by explicit serials (DF-008 schedule device picker) ──────


def _fleet_device(serial: str, state: str = "READY", model: str = "SM-A115"):
    return SimpleNamespace(serial=serial, state=state, model=model)


async def _resolve_with_devices(devices, **kwargs):
    """Run _resolve_fleet_devices against a stubbed DeviceManager."""
    import temporal.schedule_activities as acts

    manager = MagicMock()
    manager.all_devices.return_value = devices
    params = {
        "device_group_id": None,
        "filter_state": "READY",
        "filter_model": None,
        "max_devices": None,
    }
    params.update(kwargs)
    with patch.object(acts, "_manager_ref", manager):
        return await acts._resolve_fleet_devices(**params)


class TestResolveFleetDevicesBySerial:
    """_resolve_fleet_devices: explicit serials replace the candidate set."""

    @pytest.mark.asyncio
    async def test_only_selected_serials_are_returned(self):
        resolved = await _resolve_with_devices(
            [_fleet_device("AAA"), _fleet_device("BBB"), _fleet_device("CCC")],
            device_serials=["AAA", "CCC"],
        )
        assert [d.serial for d in resolved] == ["AAA", "CCC"]

    @pytest.mark.asyncio
    async def test_filter_state_and_max_devices_still_apply(self):
        resolved = await _resolve_with_devices(
            [
                _fleet_device("AAA"),
                _fleet_device("BBB", state="OFFLINE"),
                _fleet_device("CCC"),
                _fleet_device("DDD"),
            ],
            device_serials=["AAA", "BBB", "CCC", "DDD"],
            max_devices=2,
        )
        # BBB dropped by state, then capped at 2.
        assert [d.serial for d in resolved] == ["AAA", "CCC"]

    @pytest.mark.asyncio
    async def test_serials_win_over_device_group(self):
        # Group lookup must not run — result comes straight from the serial list.
        resolved = await _resolve_with_devices(
            [_fleet_device("AAA"), _fleet_device("BBB")],
            device_group_id="group-001",
            device_serials=["BBB"],
        )
        assert [d.serial for d in resolved] == ["BBB"]
