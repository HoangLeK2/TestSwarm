"""
tests/test_execution_integration.py — Unit tests for Execution coordinator integration (DF-011).

Covers:
  1. campaign_dispatch creates Execution record and adds devices
  2. ScenarioInput carries execution_id
  3. finalize_campaign saves ExecutionResult when execution_id present
  4. finalize_campaign skips ExecutionResult when execution_id absent (backward compat)
  5. execute_save_extraction passes execution_id to save_content_item
  6. SaveExtractionInput carries execution_id

Run: pytest tests/test_execution_integration.py -v
"""
from __future__ import annotations

import asyncio
from contextlib import ExitStack
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from fastapi import HTTPException

from temporal.shared import (
    SaveExtractionInput,
    ScenarioInput,
    StepsInput,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _make_db_mock():
    """Reusable async context-manager DB mock."""
    mock_db = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)
    return mock_db


def _make_campaign(campaign_id="camp-1", user_id="user-1"):
    m = MagicMock()
    m.id = campaign_id
    m.user_id = user_id
    m.variables = {"__PLATFORM__": "facebook"}
    m.target_group_id = None
    return m


def _make_device(device_id="dev-1", serial="SN001"):
    d = MagicMock()
    d.id = device_id
    d.serial = serial
    return d


def _make_scenario(scen_id="scen-1", steps=None):
    s = MagicMock()
    s.id = scen_id
    s.steps = steps if steps is not None else [{"type": "tap", "x": 100, "y": 200}]
    s.variables = {}
    s.name = "test_scenario"
    return s


@pytest.mark.asyncio
async def test_add_devices_to_execution_uses_one_flush_for_many_devices():
    from db.crud.execution import add_devices_to_execution

    db = SimpleNamespace(add_all=MagicMock(), flush=AsyncMock())

    links = await add_devices_to_execution(db, "exec-1", ["dev-1", "dev-2", "dev-3"])

    assert [link.execution_id for link in links] == ["exec-1", "exec-1", "exec-1"]
    assert [link.device_id for link in links] == ["dev-1", "dev-2", "dev-3"]
    db.add_all.assert_called_once()
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_add_devices_to_execution_empty_list_skips_flush():
    from db.crud.execution import add_devices_to_execution

    db = SimpleNamespace(add_all=MagicMock(), flush=AsyncMock())

    links = await add_devices_to_execution(db, "exec-1", [])

    assert links == []
    db.add_all.assert_not_called()
    db.flush.assert_not_awaited()


# ═══════════════════════════════════════════════════════════════════════════════
# Part 1: Shared dataclasses carry execution_id
# ═══════════════════════════════════════════════════════════════════════════════


class TestSharedDataclasses:
    """ScenarioInput, StepsInput, SaveExtractionInput all carry execution_id."""

    def test_scenario_input_has_execution_id_default_none(self):
        inp = ScenarioInput(
            campaign_id="c1",
            device_serial="SN001",
            steps=[],
        )
        assert inp.execution_id is None

    def test_scenario_input_accepts_execution_id(self):
        inp = ScenarioInput(
            campaign_id="c1",
            device_serial="SN001",
            steps=[],
            execution_id="exec-abc",
        )
        assert inp.execution_id == "exec-abc"

    def test_steps_input_has_execution_id_default_none(self):
        inp = StepsInput(device_serial="SN001", steps=[])
        assert inp.execution_id is None

    def test_steps_input_accepts_execution_id(self):
        inp = StepsInput(device_serial="SN001", steps=[], execution_id="exec-xyz")
        assert inp.execution_id == "exec-xyz"

    def test_save_extraction_input_has_execution_id_default_none(self):
        inp = SaveExtractionInput(device_serial="SN001", step={})
        assert inp.execution_id is None

    def test_save_extraction_input_accepts_execution_id(self):
        inp = SaveExtractionInput(
            device_serial="SN001",
            step={},
            execution_id="exec-123",
            account_id="account-123",
        )
        assert inp.execution_id == "exec-123"
        assert inp.account_id == "account-123"


# ═══════════════════════════════════════════════════════════════════════════════
# Part 2: campaign_dispatch creates Execution and threads execution_id
# ═══════════════════════════════════════════════════════════════════════════════


class TestCampaignDispatchExecution:
    """enqueue_campaign_run_temporal creates Execution + passes execution_id."""

    def setup_method(self):
        self.campaign = _make_campaign()
        self.device = _make_device()
        self.scenario = _make_scenario()

        self.mock_run = MagicMock()
        self.mock_run.id = "run-001"

        self.mock_execution = MagicMock()
        self.mock_execution.id = "exec-001"

    @pytest.mark.asyncio
    async def test_create_execution_called_on_dispatch(self):
        """create_execution must be called when a campaign run is dispatched."""
        db_mock = _make_db_mock()
        mock_temporal = AsyncMock()
        mock_temporal.start_workflow = AsyncMock()

        create_execution_mock = AsyncMock(return_value=self.mock_execution)
        add_devices_mock = AsyncMock()
        create_run_mock = AsyncMock(return_value=self.mock_run)

        with ExitStack() as stack:
            stack.enter_context(patch(
                "services.campaign_dispatch.activity_session", return_value=db_mock
            ))
            stack.enter_context(patch(
                "services.campaign_dispatch.repo.get_campaign",
                return_value=self.campaign,
            ))
            stack.enter_context(patch(
                "services.campaign_dispatch.repo.list_campaign_devices",
                return_value=[self.device],
            ))
            stack.enter_context(patch(
                "services.campaign_dispatch.repo.list_scenarios",
                return_value=[self.scenario],
            ))
            stack.enter_context(patch(
                "services.campaign_dispatch.repo.update_campaign_status",
                new_callable=AsyncMock,
            ))
            # list_templates is imported inside the function → patch at source
            stack.enter_context(patch(
                "db.crud.scenario_template.list_templates",
                new_callable=AsyncMock, return_value=[],
            ))
            stack.enter_context(patch(
                "db.crud.execution.create_execution",
                create_execution_mock,
            ))
            stack.enter_context(patch(
                "db.crud.execution.add_devices_to_execution",
                add_devices_mock,
            ))
            stack.enter_context(patch(
                "db.crud.execution.update_execution",
                AsyncMock(),
            ))
            stack.enter_context(patch(
                "services.campaign_dispatch._get_device_account_vars",
                new_callable=AsyncMock, return_value={},
            ))

            from services.campaign_dispatch import enqueue_campaign_run_temporal
            result, status = await enqueue_campaign_run_temporal("camp-1", mock_temporal)

        assert status == 200
        create_execution_mock.assert_awaited_once()
        call_kwargs = create_execution_mock.call_args.kwargs
        assert call_kwargs["run_type"] == "campaign_run"
        assert call_kwargs["campaign_id"] == "camp-1"
        assert call_kwargs["status"] == "running"

    @pytest.mark.asyncio
    async def test_add_devices_to_execution_called_with_device_ids(self):
        """add_devices_to_execution links all devices in one bulk call."""
        db_mock = _make_db_mock()
        mock_temporal = AsyncMock()
        mock_temporal.start_workflow = AsyncMock()

        create_execution_mock = AsyncMock(return_value=self.mock_execution)
        add_devices_mock = AsyncMock()

        with ExitStack() as stack:
            stack.enter_context(patch(
                "services.campaign_dispatch.activity_session", return_value=db_mock
            ))
            stack.enter_context(patch(
                "services.campaign_dispatch.repo.get_campaign",
                return_value=self.campaign,
            ))
            stack.enter_context(patch(
                "services.campaign_dispatch.repo.list_campaign_devices",
                return_value=[self.device],
            ))
            stack.enter_context(patch(
                "services.campaign_dispatch.repo.list_scenarios",
                return_value=[self.scenario],
            ))
            stack.enter_context(patch(
                "services.campaign_dispatch.repo.update_campaign_status",
                new_callable=AsyncMock,
            ))
            stack.enter_context(patch(
                "db.crud.scenario_template.list_templates",
                new_callable=AsyncMock, return_value=[],
            ))
            stack.enter_context(patch(
                "db.crud.execution.create_execution",
                create_execution_mock,
            ))
            stack.enter_context(patch(
                "db.crud.execution.add_devices_to_execution",
                add_devices_mock,
            ))
            stack.enter_context(patch(
                "db.crud.execution.update_execution",
                AsyncMock(),
            ))
            stack.enter_context(patch(
                "services.campaign_dispatch._get_device_account_vars",
                new_callable=AsyncMock, return_value={},
            ))

            from services.campaign_dispatch import enqueue_campaign_run_temporal
            result, status = await enqueue_campaign_run_temporal("camp-1", mock_temporal)

        assert status == 200
        add_devices_mock.assert_awaited_once_with(db_mock, "exec-001", [self.device.id])

    @pytest.mark.asyncio
    async def test_execution_id_in_response(self):
        """Response dict must include execution_id."""
        db_mock = _make_db_mock()
        mock_temporal = AsyncMock()
        mock_temporal.start_workflow = AsyncMock()

        with ExitStack() as stack:
            stack.enter_context(patch(
                "services.campaign_dispatch.activity_session", return_value=db_mock
            ))
            stack.enter_context(patch(
                "services.campaign_dispatch.repo.get_campaign",
                return_value=self.campaign,
            ))
            stack.enter_context(patch(
                "services.campaign_dispatch.repo.list_campaign_devices",
                return_value=[self.device],
            ))
            stack.enter_context(patch(
                "services.campaign_dispatch.repo.list_scenarios",
                return_value=[self.scenario],
            ))
            stack.enter_context(patch(
                "services.campaign_dispatch.repo.update_campaign_status",
                new_callable=AsyncMock,
            ))
            stack.enter_context(patch(
                "db.crud.scenario_template.list_templates",
                new_callable=AsyncMock, return_value=[],
            ))
            stack.enter_context(patch(
                "db.crud.execution.create_execution",
                AsyncMock(return_value=self.mock_execution),
            ))
            stack.enter_context(patch(
                "db.crud.execution.add_devices_to_execution",
                AsyncMock(),
            ))
            stack.enter_context(patch(
                "db.crud.execution.update_execution",
                AsyncMock(),
            ))
            stack.enter_context(patch(
                "services.campaign_dispatch._get_device_account_vars",
                new_callable=AsyncMock, return_value={},
            ))

            from services.campaign_dispatch import enqueue_campaign_run_temporal
            result, status = await enqueue_campaign_run_temporal("camp-1", mock_temporal)

        assert status == 200
        assert result["execution_id"] == "exec-001"

    @pytest.mark.asyncio
    async def test_scenario_input_receives_execution_id(self):
        """ScenarioWorkflow must be started with execution_id in ScenarioInput."""
        db_mock = _make_db_mock()
        mock_temporal = AsyncMock()
        started_args: list[Any] = []

        async def capture_start(fn, inp, **kwargs):
            started_args.append(inp)

        mock_temporal.start_workflow = capture_start

        with ExitStack() as stack:
            stack.enter_context(patch(
                "services.campaign_dispatch.activity_session", return_value=db_mock
            ))
            stack.enter_context(patch(
                "services.campaign_dispatch.repo.get_campaign",
                return_value=self.campaign,
            ))
            stack.enter_context(patch(
                "services.campaign_dispatch.repo.list_campaign_devices",
                return_value=[self.device],
            ))
            stack.enter_context(patch(
                "services.campaign_dispatch.repo.list_scenarios",
                return_value=[self.scenario],
            ))
            stack.enter_context(patch(
                "services.campaign_dispatch.repo.update_campaign_status",
                new_callable=AsyncMock,
            ))
            stack.enter_context(patch(
                "db.crud.scenario_template.list_templates",
                new_callable=AsyncMock, return_value=[],
            ))
            stack.enter_context(patch(
                "db.crud.execution.create_execution",
                AsyncMock(return_value=self.mock_execution),
            ))
            stack.enter_context(patch(
                "db.crud.execution.add_devices_to_execution",
                AsyncMock(),
            ))
            stack.enter_context(patch(
                "db.crud.execution.update_execution",
                AsyncMock(),
            ))
            stack.enter_context(patch(
                "services.campaign_dispatch._get_device_account_vars",
                new_callable=AsyncMock, return_value={},
            ))

            from services.campaign_dispatch import enqueue_campaign_run_temporal
            await enqueue_campaign_run_temporal("camp-1", mock_temporal)

        assert len(started_args) == 1
        assert isinstance(started_args[0], ScenarioInput)
        assert started_args[0].execution_id == "exec-001"
        assert started_args[0].run_id == "exec-001"


# ═══════════════════════════════════════════════════════════════════════════════
# Part 3: finalize_campaign saves ExecutionResult
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_finish_fan_out_reuses_finished_execution_and_device_id():
    from services.campaign.dispatcher import finish_fan_out_execution

    execution = SimpleNamespace(id="exec-1", campaign_id=None)
    db = AsyncMock()
    finish = AsyncMock()
    release = AsyncMock()

    with (
        patch("services.campaign.dispatcher.finish_execution", finish),
        patch(
            "services.campaign.dispatcher.release_execution_device_claim",
            release,
        ),
    ):
        await finish_fan_out_execution(
            db,
            execution,
            org_id="org-1",
            actor_user_id="user-1",
            status="completed",
            execution_already_finished=True,
            device_id="device-1",
        )

    finish.assert_not_awaited()
    db.execute.assert_awaited_once()
    assignment_update = db.execute.await_args.args[0]
    assert assignment_update.compile().params["status"] == "completed"
    release.assert_awaited_once_with(
        db,
        execution,
        org_id="org-1",
        actor_user_id="user-1",
        device_id="device-1",
    )


class TestFinalizeCampaignExecutionResult:
    """finalize_campaign upserts ExecutionResult when execution_id provided."""

    def _make_activities(self):
        from temporal.activities import DeviceActivities
        acts = DeviceActivities.__new__(DeviceActivities)
        acts._manager = MagicMock()
        return acts

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        (
            "dispatch_strategy",
            "initial_status",
            "expected_status",
            "campaign_lookup_count",
            "promotion_count",
        ),
        [
            ("parallel", "running", "completed", 0, 0),
            ("sequential", "running", "completed", 1, 1),
            ("parallel", "failed", "failed", 0, 0),
        ],
    )
    async def test_fan_out_finalize_reuses_loaded_rows(
        self,
        dispatch_strategy,
        initial_status,
        expected_status,
        campaign_lookup_count,
        promotion_count,
    ):
        acts = self._make_activities()
        db_mock = _make_db_mock()
        execution = SimpleNamespace(
            id="exec-fast-finalize",
            status=initial_status,
            meta={
                "dispatch_source": "temporal",
                "dispatch_strategy": dispatch_strategy,
            },
            org_id="org-test",
            campaign_id="camp-1",
            user_id="user-1",
            device_config={"claim_session_id": "claim-1"},
        )
        device = SimpleNamespace(id="dev-db-1")
        finish_fan_out = AsyncMock()
        campaign_lookup = AsyncMock(return_value=SimpleNamespace(id="camp-1"))
        upsert_result = AsyncMock()
        update_execution = AsyncMock()
        promote = AsyncMock()

        inp = {
            "campaign_id": "camp-1",
            "execution_id": execution.id,
            "device_serial": "SN-FAST",
            "org_id": "org-test",
            "success": True,
            "step_results": [
                {"index": 0, "type": "capacity_probe", "ok": True}
            ],
        }

        with ExitStack() as stack:
            stack.enter_context(patch("temporal.activities.activity"))
            stack.enter_context(
                patch("db.database.activity_session", return_value=db_mock)
            )
            stack.enter_context(
                patch(
                    "db.crud.execution.get_execution",
                    AsyncMock(return_value=execution),
                )
            )
            stack.enter_context(
                patch(
                    "db.crud.execution.update_execution",
                    update_execution,
                )
            )
            stack.enter_context(
                patch(
                    "db.crud.execution.upsert_execution_result",
                    upsert_result,
                )
            )
            stack.enter_context(
                patch(
                    "db.crud.device.get_device_by_serial",
                    AsyncMock(return_value=device),
                )
            )
            stack.enter_context(
                patch(
                    "services.execution.step_store.persist_execution_steps_from_results",
                    AsyncMock(),
                )
            )
            stack.enter_context(
                patch(
                    "services.execution.event_publisher.enqueue_execution_event",
                    AsyncMock(),
                )
            )
            stack.enter_context(
                patch(
                    "db.crud.campaign_entity.get_campaign_entity",
                    campaign_lookup,
                )
            )
            stack.enter_context(
                patch(
                    "services.campaign.dispatcher.finish_fan_out_execution",
                    finish_fan_out,
                )
            )
            stack.enter_context(
                patch(
                    "services.campaign.execution_runtime.maybe_promote_sequential_execution",
                    promote,
                )
            )
            stack.enter_context(patch("temporal.activities._temporal_config", None))

            await acts.finalize_campaign(inp)

        assert campaign_lookup.await_count == campaign_lookup_count
        update_execution.assert_not_awaited()
        assert promote.await_count == promotion_count
        assert execution.status == expected_status
        assert isinstance(execution.finished_at, datetime)
        upsert_result.assert_awaited_once()
        assert upsert_result.await_args.kwargs["status"] == (
            "failed" if expected_status == "failed" else "passed"
        )
        finish_fan_out.assert_awaited_once()
        assert finish_fan_out.await_args.kwargs["status"] == expected_status
        assert finish_fan_out.await_args.kwargs["execution_already_finished"] is True
        assert finish_fan_out.await_args.kwargs["device_id"] == device.id

    @pytest.mark.asyncio
    async def test_upsert_execution_result_called_on_success(self):
        acts = self._make_activities()
        db_mock = _make_db_mock()
        db_mock.add = MagicMock()
        mock_device = MagicMock()
        mock_device.id = "dev-db-1"

        inp = {
            "campaign_id": "",
            "run_id": None,
            "success": True,
            "execution_id": "exec-001",
            "device_serial": "SN001",
            "org_id": "org-test",
            "step_results": [
                {"index": 0, "type": "tap", "ok": True, "message": ""},
                {"index": 1, "type": "swipe", "ok": True, "message": ""},
            ],
        }

        upsert_mock = AsyncMock()
        get_execution_mock = AsyncMock(
            return_value=SimpleNamespace(
                status="running",
                meta={},
                org_id="org-test",
                campaign_id="camp-1",
                device_config={},
            )
        )
        update_execution_mock = AsyncMock()
        get_device_mock = AsyncMock(return_value=mock_device)
        inline_publish = AsyncMock()

        with ExitStack() as stack:
            stack.enter_context(patch("temporal.activities.activity"))
            # Imports inside finalize_campaign → patch at source modules
            stack.enter_context(patch(
                "db.database.activity_session", return_value=db_mock
            ))
            stack.enter_context(patch(
                "db.crud.device.get_device_by_serial", get_device_mock
            ))
            stack.enter_context(patch(
                "db.crud.execution.get_execution", get_execution_mock
            ))
            stack.enter_context(patch(
                "db.crud.execution.update_execution", update_execution_mock
            ))
            stack.enter_context(patch(
                "db.crud.execution.upsert_execution_result", upsert_mock
            ))
            stack.enter_context(patch(
                "services.execution.step_store.persist_execution_steps_from_results",
                AsyncMock(),
            ))
            stack.enter_context(patch(
                "services.execution.event_publisher.process_outbox_batch",
                inline_publish,
            ))
            stack.enter_context(patch(
                "services.webhook_dispatcher.dispatch_webhook",
                AsyncMock(),
            ))
            # Patch campaign-idle check to avoid Temporal client call
            stack.enter_context(patch(
                "temporal.activities._temporal_config", None
            ))

            await acts.finalize_campaign(inp)

        upsert_mock.assert_awaited_once()
        kwargs = upsert_mock.call_args.kwargs
        assert kwargs["execution_id"] == "exec-001"
        assert kwargs["device_id"] == "dev-db-1"
        assert kwargs["status"] == "passed"
        assert len(kwargs["passed_steps"]) == 2
        assert kwargs["failed_steps"] == []
        inline_publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_upsert_execution_result_called_on_failure(self):
        acts = self._make_activities()
        db_mock = _make_db_mock()
        mock_device = MagicMock()
        mock_device.id = "dev-db-1"

        inp = {
            "campaign_id": "",
            "run_id": None,
            "success": False,
            "execution_id": "exec-002",
            "device_serial": "SN002",
            "org_id": "org-test",
            "step_results": [
                {"index": 0, "type": "tap", "ok": True, "message": ""},
                {"index": 1, "type": "tap", "ok": False, "message": "Element not found"},
            ],
        }

        upsert_mock = AsyncMock()
        get_execution_mock = AsyncMock(return_value=SimpleNamespace(status="running", meta={}))
        update_execution_mock = AsyncMock()
        get_device_mock = AsyncMock(return_value=mock_device)

        with ExitStack() as stack:
            stack.enter_context(patch("temporal.activities.activity"))
            stack.enter_context(patch(
                "db.database.activity_session", return_value=db_mock
            ))
            stack.enter_context(patch(
                "db.crud.device.get_device_by_serial", get_device_mock
            ))
            stack.enter_context(patch(
                "db.crud.execution.get_execution", get_execution_mock
            ))
            stack.enter_context(patch(
                "db.crud.execution.update_execution", update_execution_mock
            ))
            stack.enter_context(patch(
                "db.crud.execution.upsert_execution_result", upsert_mock
            ))
            stack.enter_context(patch(
                "services.execution.step_store.persist_execution_steps_from_results",
                AsyncMock(),
            ))
            stack.enter_context(patch(
                "temporal.activities._temporal_config", None
            ))

            await acts.finalize_campaign(inp)

        kwargs = upsert_mock.call_args.kwargs
        assert kwargs["status"] == "failed"
        assert len(kwargs["passed_steps"]) == 1
        assert len(kwargs["failed_steps"]) == 1
        assert kwargs["failed_steps"][0]["message"] == "Element not found"

    @pytest.mark.asyncio
    async def test_cancelled_finalize_marks_cancelled_without_opening_dlq(self):
        acts = self._make_activities()
        db_mock = _make_db_mock()
        mock_device = MagicMock()
        mock_device.id = "dev-db-1"

        inp = {
            "campaign_id": "",
            "run_id": None,
            "success": False,
            "execution_id": "exec-cancelled",
            "device_serial": "SN-CANCEL",
            "org_id": "org-test",
            "step_results": [],
            "failed_message": "Workflow error: Child Workflow execution cancelled",
        }

        upsert_mock = AsyncMock(return_value=None)
        get_execution_mock = AsyncMock(return_value=SimpleNamespace(status="running", meta={}))
        update_execution_mock = AsyncMock()
        cancel_execution_record_mock = AsyncMock(
            return_value=(SimpleNamespace(status="cancelled", meta={}), True)
        )
        get_device_mock = AsyncMock(return_value=mock_device)
        open_dlq_mock = AsyncMock()

        with ExitStack() as stack:
            stack.enter_context(patch("temporal.activities.activity"))
            stack.enter_context(patch(
                "db.database.activity_session", return_value=db_mock
            ))
            stack.enter_context(patch(
                "db.crud.device.get_device_by_serial", get_device_mock
            ))
            stack.enter_context(patch(
                "db.crud.execution.get_execution", get_execution_mock
            ))
            stack.enter_context(patch(
                "db.crud.execution.update_execution", update_execution_mock
            ))
            stack.enter_context(patch(
                "db.crud.execution.cancel_execution_record",
                cancel_execution_record_mock,
            ))
            stack.enter_context(patch(
                "db.crud.execution.upsert_execution_result", upsert_mock
            ))
            stack.enter_context(patch(
                "services.execution.step_store.persist_execution_steps_from_results",
                AsyncMock(),
            ))
            stack.enter_context(patch(
                "db.crud.execution_steps.list_execution_steps",
                AsyncMock(return_value=[]),
            ))
            stack.enter_context(patch(
                "services.campaign.dlq_service.open_dlq_for_failed_execution",
                open_dlq_mock,
            ))
            stack.enter_context(patch(
                "services.webhook_dispatcher.dispatch_webhook",
                AsyncMock(),
            ))
            stack.enter_context(patch(
                "temporal.activities._temporal_config", None
            ))

            await acts.finalize_campaign(inp)

        kwargs = upsert_mock.call_args.kwargs
        assert kwargs["status"] == "failed"
        cancel_execution_record_mock.assert_awaited_once_with(
            db_mock,
            "exec-cancelled",
            reason="Workflow error: Child Workflow execution cancelled",
        )
        open_dlq_mock.assert_not_awaited()
        update_execution_mock.assert_not_awaited()

    def test_failed_finalize_uses_persisted_step_results_when_workflow_has_none(self):
        from temporal.activities import (
            _finalize_error_message,
            _finalize_is_cancelled,
            _finalize_step_results,
        )

        persisted = [
            {"index": 0, "type": "tap_selector", "ok": False, "message": "recovery failed"}
        ]

        step_results = _finalize_step_results(
            success=False,
            step_results=[],
            persisted_step_results=persisted,
        )
        error_msg = _finalize_error_message(
            failed_steps=step_results,
            workflow_failed_message="Workflow error: Child Workflow execution failed",
        )

        assert step_results == persisted
        assert error_msg == "recovery failed"
        assert _finalize_is_cancelled(
            failed_steps=[],
            workflow_failed_message="Workflow error: Child Workflow execution cancelled",
        )
        assert _finalize_is_cancelled(
            failed_steps=[
                {
                    "index": 0,
                    "type": "tap",
                    "ok": False,
                    "message": "tap: cancelled by user",
                }
            ],
            workflow_failed_message=None,
        )
        assert not _finalize_is_cancelled(
            failed_steps=[],
            workflow_failed_message="Workflow error: Child Workflow execution failed",
        )

    @pytest.mark.asyncio
    async def test_no_execution_result_when_execution_id_absent(self):
        """Backward compat: old callers without execution_id must not break."""
        acts = self._make_activities()
        db_mock = _make_db_mock()

        inp = {
            "campaign_id": "",
            "run_id": None,
            "success": True,
            # NO execution_id
        }

        upsert_mock = AsyncMock()

        with ExitStack() as stack:
            stack.enter_context(patch("temporal.activities.activity"))
            stack.enter_context(patch(
                "db.database.activity_session", return_value=db_mock
            ))
            stack.enter_context(patch(
                "db.crud.execution.upsert_execution_result", upsert_mock
            ))
            stack.enter_context(patch(
                "temporal.activities._temporal_config", None
            ))

            await acts.finalize_campaign(inp)

        upsert_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_execution_result_when_device_not_found(self):
        """If device serial not in DB, skip gracefully — don't crash."""
        acts = self._make_activities()
        db_mock = _make_db_mock()

        inp = {
            "campaign_id": "",
            "run_id": None,
            "success": True,
            "execution_id": "exec-003",
            "device_serial": "UNKNOWN_SERIAL",
            "org_id": "org-test",
            "step_results": [],
        }

        upsert_mock = AsyncMock()
        get_execution_mock = AsyncMock(return_value=SimpleNamespace(status="running", meta={}))
        get_device_mock = AsyncMock(return_value=None)  # device not found

        with ExitStack() as stack:
            stack.enter_context(patch("temporal.activities.activity"))
            stack.enter_context(patch(
                "db.database.activity_session", return_value=db_mock
            ))
            stack.enter_context(patch(
                "db.crud.device.get_device_by_serial", get_device_mock
            ))
            stack.enter_context(patch(
                "db.crud.execution.get_execution", get_execution_mock
            ))
            stack.enter_context(patch(
                "db.crud.execution.upsert_execution_result", upsert_mock
            ))
            stack.enter_context(patch(
                "services.webhook_dispatcher.dispatch_webhook",
                AsyncMock(),
            ))
            stack.enter_context(patch(
                "temporal.activities._temporal_config", None
            ))

            # Must not raise
            await acts.finalize_campaign(inp)

        upsert_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_old_str_payload_backward_compat(self):
        """Old str payload (pre-dict format) must not break finalize_campaign."""
        acts = self._make_activities()
        db_mock = _make_db_mock()
        upsert_mock = AsyncMock()

        with ExitStack() as stack:
            stack.enter_context(patch("temporal.activities.activity"))
            stack.enter_context(patch(
                "db.database.activity_session", return_value=db_mock
            ))
            stack.enter_context(patch(
                "db.crud.execution.upsert_execution_result", upsert_mock
            ))
            stack.enter_context(patch(
                "temporal.activities._temporal_config", None
            ))

            # Old format: just campaign_id string
            await acts.finalize_campaign("old-campaign-id")

        upsert_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_campaign_idle_skips_caller_workflow_in_running_count(self):
        """Parent ScenarioWorkflow is still Running while finalize_campaign runs; exclude it."""
        acts = self._make_activities()
        db_mock = _make_db_mock()
        update_status_mock = AsyncMock()

        class _WfRow:
            def __init__(self, wf_id: str) -> None:
                self.id = wf_id

        async def _list_only_caller(_query: str):
            yield _WfRow("campaign:c1:device:dev1:scenario:sc1")

        mock_client = MagicMock()
        mock_client.list_workflows = lambda q: _list_only_caller(q)

        mock_info = MagicMock()
        mock_info.workflow_id = "campaign:c1:device:dev1:scenario:sc1"

        cfg = MagicMock()

        with ExitStack() as stack:
            stack.enter_context(patch("temporal.activities.activity.heartbeat", MagicMock()))
            stack.enter_context(patch("temporal.activities.activity.info", return_value=mock_info))
            stack.enter_context(patch("temporal.activities._temporal_config", cfg))
            stack.enter_context(patch(
                "temporal.worker.get_temporal_client", AsyncMock(return_value=mock_client),
            ))
            stack.enter_context(patch(
                "db.database.activity_session", return_value=db_mock,
            ))
            stack.enter_context(patch(
                "db.crud.campaign.update_campaign_status", update_status_mock,
            ))
            stack.enter_context(patch(
                "db.crud.campaign_entity.lookup_campaign_org_id",
                AsyncMock(return_value="org-test"),
            ))

            await acts.finalize_campaign({"campaign_id": "c1", "run_id": None, "success": True})

        update_status_mock.assert_awaited_once()
        assert update_status_mock.await_args[0] == (db_mock, "c1", "idle")


# ═══════════════════════════════════════════════════════════════════════════════
# Part 4: execute_save_extraction passes execution_id to save_content_item
# ═══════════════════════════════════════════════════════════════════════════════

class TestSaveExtractionExecutionId:
    """execute_save_extraction must forward execution_id to persistence facade."""

    def _make_activities(self):
        from temporal.activities import DeviceActivities
        acts = DeviceActivities.__new__(DeviceActivities)
        acts._manager = MagicMock()
        mock_device = MagicMock()
        mock_device.serial = "SN001"
        acts._manager.get_device = MagicMock(return_value=mock_device)
        return acts

    @pytest.mark.asyncio
    async def test_execution_id_forwarded_to_persist_data_items(self):
        acts = self._make_activities()

        posts = [{"content": "hello world", "author": "user1"}]
        inp = SaveExtractionInput(
            device_serial="SN001",
            step={
                "type": "save_extraction",
                "data_var": "posts",
                "collection": "test",
                "platform": "facebook",
                "content_type": "fb_post",
            },
            step_index=0,
            context={"posts": posts},
            campaign_id="camp-1",
            run_id="run-001",
            execution_id="exec-001",
            account_id="account-001",
        )

        from services.extraction_usecase import PersistReport

        persist_mock = AsyncMock(return_value=(PersistReport(saved_count=1, processed_count=1), {}))

        with ExitStack() as stack:
            stack.enter_context(patch("temporal.activities.activity"))
            stack.enter_context(patch(
                "temporal.activities.persist_data_items", persist_mock
            ))
            stack.enter_context(patch(
                "services.content.campaign_ref.resolve_persist_campaign_id",
                AsyncMock(return_value="camp-1"),
            ))
            stack.enter_context(patch(
                "db.database.activity_session", return_value=_make_db_mock()
            ))

            from temporal.activities import DeviceActivities
            result = await acts.execute_save_extraction(inp)

        persist_mock.assert_awaited_once()
        call_kwargs = persist_mock.call_args.kwargs
        assert call_kwargs["execution_id"] == "exec-001"
        assert call_kwargs["account_id"] == "account-001"
        assert call_kwargs["campaign_id"] == "camp-1"
        assert call_kwargs["data_var"] == "posts"
        assert result.ok is True

    @pytest.mark.asyncio
    async def test_execution_id_none_still_saves(self):
        """Without execution_id (old runs), save_extraction must still work."""
        acts = self._make_activities()

        posts = [{"content": "hello", "author": "x"}]
        inp = SaveExtractionInput(
            device_serial="SN001",
            step={
                "type": "save_extraction",
                "data_var": "posts",
                "collection": "col",
                "platform": "facebook",
                "content_type": "fb_post",
            },
            step_index=0,
            context={"posts": posts},
            campaign_id="camp-2",
            run_id="run-002",
            execution_id=None,
        )

        from services.extraction_usecase import PersistReport

        persist_mock = AsyncMock(return_value=(PersistReport(saved_count=1, processed_count=1), {}))

        with ExitStack() as stack:
            stack.enter_context(patch("temporal.activities.activity"))
            stack.enter_context(patch(
                "temporal.activities.persist_data_items", persist_mock
            ))
            stack.enter_context(patch(
                "services.content.campaign_ref.resolve_persist_campaign_id",
                AsyncMock(return_value="camp-2"),
            ))
            stack.enter_context(patch(
                "db.database.activity_session", return_value=_make_db_mock()
            ))

            result = await acts.execute_save_extraction(inp)

        persist_mock.assert_awaited_once()
        call_kwargs = persist_mock.call_args.kwargs
        assert call_kwargs["execution_id"] is None
        assert result.ok is True


# ═══════════════════════════════════════════════════════════════════════════════
# Part 5: CRUD — create_execution + upsert_execution_result
# ═══════════════════════════════════════════════════════════════════════════════


class TestExecutionCRUD:
    """Basic CRUD contract tests (no real DB — mock AsyncSession)."""

    @pytest.mark.asyncio
    async def test_create_execution_sets_fields(self):
        from db.crud.execution import create_execution
        from db.models.execution import Execution

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        result = await create_execution(
            db,
            run_type="campaign_run",
            campaign_id="camp-1",
            user_id="user-1",
            status="running",
            device_config={"max_devices": 2},
            loop_config={"loop_count": 3},
            error_config={"stop_on_first_failure": True},
        )

        assert isinstance(result, Execution)
        assert result.run_type == "campaign_run"
        assert result.campaign_id == "camp-1"
        assert result.status == "running"
        assert result.device_config == {"max_devices": 2}
        assert result.loop_config == {"loop_count": 3}
        assert result.error_config == {"stop_on_first_failure": True}
        db.add.assert_called_once_with(result)
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_upsert_execution_result_creates_new(self):
        from db.crud.execution import upsert_execution_result
        from db.models.execution import ExecutionResult

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        # scalar_one_or_none returns None → create path
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(return_value=mock_result)

        er = await upsert_execution_result(
            db,
            execution_id="exec-1",
            device_id="dev-1",
            status="passed",
            passed_steps=[{"index": 0}],
            failed_steps=[],
        )

        assert isinstance(er, ExecutionResult)
        assert er.status == "passed"
        assert er.passed_steps == [{"index": 0}]
        db.add.assert_called_once_with(er)

    @pytest.mark.asyncio
    async def test_upsert_execution_result_updates_existing(self):
        from db.crud.execution import upsert_execution_result
        from db.models.execution import ExecutionResult

        existing = ExecutionResult(
            execution_id="exec-1",
            device_id="dev-1",
            status="pending",
            passed_steps=[],
            failed_steps=[],
        )

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=existing)
        db.execute = AsyncMock(return_value=mock_result)

        er = await upsert_execution_result(
            db,
            execution_id="exec-1",
            device_id="dev-1",
            status="failed",
            passed_steps=[{"index": 0}],
            failed_steps=[{"index": 1, "message": "err"}],
        )

        # Must return same object, updated
        assert er is existing
        assert er.status == "failed"
        assert er.passed_steps == [{"index": 0}]
        assert er.failed_steps == [{"index": 1, "message": "err"}]
        # Should NOT call db.add for existing records
        db.add.assert_not_called()


class TestDlqRetryReenqueue:
    """DLQ retry endpoint should enqueue campaign run and update status."""

    @pytest.mark.asyncio
    async def test_retry_dlq_success_marks_resolved(self):
        from api.routes import executions as executions_route

        db = AsyncMock()
        user = MagicMock()
        user.id = "user-1"
        user.org_id = "org-1"
        entry = MagicMock()
        entry.id = "dlq-1"
        entry.execution_id = "exec-1"
        entry.device_serial = "SN001"
        entry.error = "timeout"
        entry.retry_count = 1
        entry.status = "resolved"
        entry.last_attempt_at = None
        entry.created_at = datetime.now(timezone.utc)
        execution = MagicMock()
        execution.id = "exec-1"
        execution.user_id = "user-1"
        execution.campaign_id = "camp-1"
        entry.replayed_to_execution_id = None
        entry.campaign_id = None
        entry.failed_step_id = None
        entry.failure_reason = None
        entry.closed_by = None
        entry.closed_at = None
        entry.close_reason = None
        entry.artifact_refs = {}
        entry.display_message = ""
        execution.meta = {}
        request = MagicMock()
        request.app.state.scheduler = MagicMock()
        request.app.state.scheduler._client = AsyncMock()
        request.app.state.scheduler._cfg = MagicMock()
        request.app.state.manager = None

        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "db.crud.execution_dlq.get_dlq_entry_for_user",
                    AsyncMock(return_value=entry),
                )
            )
            stack.enter_context(
                patch("api.execution_access.get_execution_for_user", AsyncMock(return_value=execution))
            )
            legacy_mock = stack.enter_context(
                patch(
                    "services.campaign.dlq_service.legacy_retry_dlq_entry",
                    AsyncMock(return_value=entry),
                )
            )

            out = await executions_route.retry_dlq("dlq-1", request, db, user)

        legacy_mock.assert_awaited_once()
        assert out.id == "dlq-1"

    @pytest.mark.asyncio
    async def test_retry_dlq_idempotent_when_already_retrying(self):
        from api.routes import executions as executions_route
        from services.campaign.dlq_errors import DLQRetryInProgressError

        db = AsyncMock()
        user = MagicMock()
        user.id = "user-1"
        user.org_id = "org-1"
        entry = MagicMock()
        entry.id = "dlq-1"
        entry.execution_id = "exec-1"
        entry.device_serial = "SN001"
        entry.error = "timeout"
        entry.retry_count = 1
        entry.status = "retrying"
        entry.last_attempt_at = None
        entry.created_at = datetime.now(timezone.utc)
        execution = MagicMock()
        execution.id = "exec-1"
        execution.user_id = "user-1"
        execution.campaign_id = "camp-1"
        entry.replayed_to_execution_id = None
        entry.campaign_id = None
        entry.failed_step_id = None
        entry.failure_reason = None
        entry.closed_by = None
        entry.closed_at = None
        entry.close_reason = None
        entry.artifact_refs = {}
        execution.meta = {}
        request = MagicMock()
        request.app.state.scheduler = MagicMock()
        request.app.state.scheduler._client = AsyncMock()
        request.app.state.scheduler._cfg = MagicMock()
        request.app.state.manager = None

        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "db.crud.execution_dlq.get_dlq_entry_for_user",
                    AsyncMock(return_value=entry),
                )
            )
            stack.enter_context(
                patch("api.execution_access.get_execution_for_user", AsyncMock(return_value=execution))
            )
            stack.enter_context(
                patch(
                    "services.campaign.dlq_service.legacy_retry_dlq_entry",
                    AsyncMock(side_effect=DLQRetryInProgressError()),
                )
            )

            with pytest.raises(HTTPException) as exc:
                await executions_route.retry_dlq("dlq-1", request, db, user)

        assert exc.value.status_code == 409
        assert exc.value.detail["code"] == "DLQ_RETRY_IN_PROGRESS"

    @pytest.mark.asyncio
    async def test_retry_dlq_not_owned_returns_404_without_mutation(self):
        from api.routes import executions as executions_route

        db = AsyncMock()
        user = MagicMock()
        user.id = "user-1"
        user.org_id = "org-1"
        request = MagicMock()
        request.app.state.scheduler = MagicMock()
        request.app.state.scheduler._client = AsyncMock()
        request.app.state.scheduler._cfg = MagicMock()

        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "db.crud.execution_dlq.get_dlq_entry_for_user",
                    AsyncMock(return_value=None),
                )
            )
            legacy_mock = stack.enter_context(
                patch("services.campaign.dlq_service.legacy_retry_dlq_entry", AsyncMock())
            )

            with pytest.raises(HTTPException) as exc:
                await executions_route.retry_dlq("dlq-not-owned", request, db, user)
        assert exc.value.status_code == 404

        legacy_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_retry_dlq_epic04_forwards_full_rerun_flag(self):
        from api.routes import executions as executions_route
        from api.routes.executions import DLQRetryBody
        from services.campaign.execution_runtime import DISPATCH_SOURCE_TEMPORAL

        db = AsyncMock()
        user = MagicMock()
        user.id = "user-1"
        user.org_id = "org-1"
        entry = MagicMock()
        entry.id = "dlq-1"
        entry.execution_id = "exec-1"
        entry.device_serial = "SN001"
        entry.error = "timeout"
        entry.retry_count = 1
        entry.status = "replayed"
        entry.last_attempt_at = None
        entry.created_at = datetime.now(timezone.utc)
        entry.replayed_to_execution_id = "exec-replay-1"
        entry.campaign_id = "camp-1"
        entry.failed_step_id = None
        entry.failure_reason = None
        entry.closed_by = None
        entry.closed_at = None
        entry.close_reason = None
        entry.artifact_refs = {}
        entry.display_message = ""
        execution = MagicMock()
        execution.id = "exec-1"
        execution.user_id = "user-1"
        execution.campaign_id = "camp-1"
        execution.meta = {"dispatch_source": DISPATCH_SOURCE_TEMPORAL}
        request = MagicMock()
        request.app.state.scheduler = MagicMock()
        request.app.state.scheduler._client = AsyncMock()
        request.app.state.scheduler._cfg = MagicMock()
        request.app.state.manager = None

        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "db.crud.execution_dlq.get_dlq_entry_for_user",
                    AsyncMock(return_value=entry),
                )
            )
            stack.enter_context(
                patch("api.execution_access.get_execution_for_user", AsyncMock(return_value=execution))
            )
            replay_mock = stack.enter_context(
                patch(
                    "services.campaign.dlq_service.replay_dlq_entry",
                    AsyncMock(return_value=(entry, MagicMock(), True)),
                )
            )
            legacy_mock = stack.enter_context(
                patch("services.campaign.dlq_service.legacy_retry_dlq_entry", AsyncMock())
            )

            out = await executions_route.retry_dlq(
                "dlq-1",
                request,
                db,
                user,
                DLQRetryBody(from_checkpoint=False),
            )

        replay_mock.assert_awaited_once()
        assert replay_mock.await_args.kwargs["from_checkpoint"] is False
        legacy_mock.assert_not_awaited()
        assert out.id == "dlq-1"
