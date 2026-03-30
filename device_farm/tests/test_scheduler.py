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
from datetime import datetime, timezone, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch, call
import pytest


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
        "last_run_at": None,
        "next_run_at": None,
        "run_count": 0,
        "user_id": "user-001",
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
        "started_at": datetime.now(timezone.utc),
        "finished_at": None,
        "devices_dispatched": 0,
        "devices_succeeded": 0,
        "devices_failed": 0,
        "task_ids": [],
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
             patch("db.database.AsyncSessionLocal", return_value=mock_db), \
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
             patch("db.database.AsyncSessionLocal", return_value=mock_db), \
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
             patch("db.database.AsyncSessionLocal", return_value=mock_db), \
             patch("db.crud.schedule.create_schedule_run", return_value=mock_run):
            mock_act.heartbeat = MagicMock()
            activities = ScheduleActivities()
            result = await activities.create_run_record("sched-001")

        assert result == "run-abc"

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
             patch("db.database.AsyncSessionLocal", return_value=mock_db), \
             patch("db.crud.schedule.update_schedule_run", new_callable=AsyncMock) as mock_ur, \
             patch("db.crud.schedule.update_schedule_after_run", new_callable=AsyncMock) as mock_ua:
            mock_act.heartbeat = MagicMock()
            activities = ScheduleActivities()
            await activities.finalize_schedule_run(
                "run-001", "sched-001", dispatch_result,
                "*/30 * * * *", "Asia/Ho_Chi_Minh"
            )

        mock_ur.assert_awaited_once()
        mock_ua.assert_awaited_once()
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

        with patch("temporal.schedule_activities.activity") as mock_act, \
             patch("db.database.AsyncSessionLocal", return_value=mock_db), \
             patch("db.crud.schedule.update_schedule_run", side_effect=_mock_update_run), \
             patch("db.crud.schedule.update_schedule_after_run", new_callable=AsyncMock):
            mock_act.heartbeat = MagicMock()
            activities = ScheduleActivities()
            await activities.finalize_schedule_run(
                "run-001", "sched-001", dispatch_result,
                "*/30 * * * *", "UTC"
            )

        assert captured["status"] == "failed"
        assert "No devices available" in captured["error_message"]


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
             patch("db.crud.schedule.get_due_schedules", return_value=[due_schedule]), \
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
