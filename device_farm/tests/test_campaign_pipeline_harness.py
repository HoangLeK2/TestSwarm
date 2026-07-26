from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts.stress_campaign_pipeline import (
    PipelineWaveResult,
    _aggregate_results,
    _database_is_isolated,
    _evaluate_gates,
    _install_pipeline_probe_runtime,
    _operational_gates_passed,
    _publish_outbox_until_drained,
    _redact_database_url,
)


def _wave(*, target_count: int = 120, http_s: float = 3.0) -> PipelineWaveResult:
    return PipelineWaveResult(
        target_count=target_count,
        repeat=1,
        warmup=False,
        http_status=200,
        http_s=http_s,
        terminal_s=4.0,
        total_s=4.5,
        execution_count=target_count,
        completed=target_count,
        failed=0,
        schedule_to_start_ms=[250.0] * target_count,
        finalization_schedule_to_start_ms=[100.0] * target_count,
        finalization_duration_ms=[600.0] * target_count,
        finalization_sql_count=[12] * target_count,
        finalization_sql_duration_ms=[40.0] * target_count,
        finalization_sql_statements={"SELECT executions": target_count},
        outbox_lag_ms=[500.0] * target_count,
        sql_count=42,
        pool_peak=20,
        pool_timeouts=0,
        db_peak_connections=60,
        db_max_connections=100,
        events_total=target_count,
        events_published=target_count,
    )


def test_database_guard_requires_dedicated_benchmark_database():
    assert _database_is_isolated(
        "postgresql://postgres:secret@localhost:5433/device_farm_benchmark"
    )
    assert _database_is_isolated(
        "postgresql+asyncpg://postgres:secret@localhost:5433/perf_campaign"
    )
    assert not _database_is_isolated(
        "postgresql://postgres:secret@localhost:5433/device_farm"
    )
    assert (
        _redact_database_url(
            "postgresql://postgres:secret@localhost:5433/device_farm_benchmark"
        )
        == "postgresql://postgres:***@localhost:5433/device_farm_benchmark"
    )


def test_pipeline_summary_reports_p95_for_each_measured_phase():
    summary = _aggregate_results(
        [
            _wave(http_s=2.0),
            _wave(http_s=4.0),
        ]
    )

    target = summary["120"]
    assert target["runs"] == 2
    assert target["http_p95_s"] == 3.9
    assert target["schedule_to_start_p95_ms"] == 250.0
    assert target["finalization_schedule_to_start_p95_ms"] == 100.0
    assert target["finalization_duration_p95_ms"] == 600.0
    assert target["finalization_sql_count_mean"] == 12.0
    assert target["finalization_sql_count_p95"] == 12.0
    assert target["finalization_sql_duration_p95_ms"] == 40.0
    assert target["finalization_sql_top"] == {"SELECT executions": 240}
    assert target["outbox_lag_p95_ms"] == 500.0


def test_pipeline_gate_requires_baseline_before_claiming_improvement():
    summary = _aggregate_results([_wave(http_s=3.0)])

    without_baseline = _evaluate_gates(
        summary,
        target_count=120,
        baseline_summary=None,
    )
    assert not without_baseline["passed"]
    assert _operational_gates_passed(without_baseline)
    assert without_baseline["checks"]["improvement_30_percent"]["status"] == "not_evaluated"

    baseline = {"120": {"http_p95_s": 5.0}}
    with_baseline = _evaluate_gates(
        summary,
        target_count=120,
        baseline_summary=baseline,
    )
    assert with_baseline["passed"]
    assert with_baseline["checks"]["improvement_30_percent"]["value_percent"] == 40.0


def test_pipeline_gate_fails_when_event_delivery_is_incomplete():
    wave = _wave()
    wave.events_published -= 1

    gates = _evaluate_gates(
        _aggregate_results([wave]),
        target_count=120,
        baseline_summary={"120": {"http_p95_s": 5.0}},
    )

    assert not gates["passed"]
    assert gates["checks"]["event_delivery"]["status"] == "failed"


@pytest.mark.asyncio
async def test_probe_runtime_patch_is_process_local_and_restorable():
    import services.campaign.execution_runtime as execution_runtime

    original = execution_runtime._try_start_temporal
    original_fallback = execution_runtime.schedule_fallback_runtime
    temporal_client = SimpleNamespace(start_workflow=AsyncMock())
    restore = _install_pipeline_probe_runtime(250, org_id="org-1")
    try:
        workflow_id = await execution_runtime._try_start_temporal(
            temporal_client,
            SimpleNamespace(task_queue="benchmark-q"),
            SimpleNamespace(
                campaign_id="campaign-1",
                device_serial="PIPE-0001",
                campaign_vars={"__ORG_ID__": "org-1"},
            ),
            "execution-1",
        )
    finally:
        restore()

    assert workflow_id == execution_runtime.workflow_id_for_execution("execution-1")
    assert execution_runtime._try_start_temporal is original
    assert execution_runtime.schedule_fallback_runtime is original_fallback
    payload = temporal_client.start_workflow.await_args.args[1]
    assert payload["delay_ms"] == 250
    assert payload["org_id"] == "org-1"
    assert temporal_client.start_workflow.await_args.kwargs["task_queue"] == "benchmark-q"


@pytest.mark.asyncio
async def test_outbox_timeout_raises_instead_of_reporting_zero_lag(monkeypatch):
    class _Rows:
        def scalars(self):
            return self

        def all(self):
            return []

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def execute(self, _statement):
            return _Rows()

    async def _process(_db, *, limit):
        assert limit == 200

    monkeypatch.setattr(
        "services.execution.event_publisher.process_outbox_batch",
        _process,
    )
    terminal = asyncio.Event()
    terminal.set()

    with pytest.raises(TimeoutError, match="outbox did not drain"):
        await _publish_outbox_until_drained(
            lambda: _Session(),
            campaign_id="campaign-timeout",
            expected_events=1,
            terminal_event=terminal,
            timeout_s=0.0,
        )
