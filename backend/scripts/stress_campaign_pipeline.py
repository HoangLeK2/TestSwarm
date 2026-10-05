#!/usr/bin/env python3
"""Local full-pipeline campaign benchmark.

The harness runs the real FastAPI dispatch route against PostgreSQL and starts
real Temporal workflows, but replaces physical device work with a deterministic
capacity probe. The probe workflow still executes the existing
``finalize_campaign`` activity and the harness drains the transactional outbox.

This process-level harness does not reproduce a multi-process production worker
topology. Pair it with ``stress_temporal_capacity.py --production-120`` and a
real-device canary before making a production performance claim.

Use a dedicated disposable database. The command refuses a shared-looking
database name unless ``--allow-shared-db`` is explicitly provided.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import subprocess
import sys
import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit, urlunsplit


try:
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
except Exception:
    pass


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = max(0.0, min(1.0, p)) * (len(ordered) - 1)
    index = int(pos)
    fraction = pos - index
    if index >= len(ordered) - 1:
        return ordered[-1]
    return ordered[index] + (ordered[index + 1] - ordered[index]) * fraction


def _database_name(database_url: str) -> str:
    return urlsplit(database_url).path.rsplit("/", 1)[-1].lower()


def _database_is_isolated(database_url: str) -> bool:
    name = _database_name(database_url)
    return any(marker in name for marker in ("benchmark", "bench", "perf", "loadtest"))


def _redact_database_url(database_url: str) -> str:
    parsed = urlsplit(database_url)
    if parsed.password is None:
        return database_url
    username = parsed.username or ""
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    auth = f"{username}:***@" if username else "***@"
    return urlunsplit(
        (parsed.scheme, f"{auth}{host}{port}", parsed.path, parsed.query, parsed.fragment)
    )


def _asyncpg_database_url(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


@dataclass
class PipelineWaveResult:
    target_count: int
    repeat: int
    warmup: bool
    http_status: int
    http_s: float
    terminal_s: float
    total_s: float
    execution_count: int
    completed: int
    failed: int
    schedule_to_start_ms: list[float] = field(default_factory=list)
    finalization_schedule_to_start_ms: list[float] = field(default_factory=list)
    finalization_duration_ms: list[float] = field(default_factory=list)
    finalization_sql_count: list[int] = field(default_factory=list)
    finalization_sql_duration_ms: list[float] = field(default_factory=list)
    finalization_sql_statements: dict[str, int] = field(default_factory=dict)
    outbox_lag_ms: list[float] = field(default_factory=list)
    phase_s: dict[str, float] = field(default_factory=dict)
    sql_count: int = 0
    sql_duration_s: float = 0.0
    sql_by_verb: dict[str, int] = field(default_factory=dict)
    sql_executemany_calls: int = 0
    pool_peak: int = 0
    pool_timeouts: int = 0
    db_peak_connections: int = 0
    db_max_connections: int = 0
    events_total: int = 0
    events_published: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _aggregate_results(results: list[PipelineWaveResult]) -> dict[str, dict[str, Any]]:
    grouped: dict[int, list[PipelineWaveResult]] = {}
    for result in results:
        if result.warmup:
            continue
        grouped.setdefault(result.target_count, []).append(result)

    summary: dict[str, dict[str, Any]] = {}
    for target_count, waves in sorted(grouped.items()):
        schedule_values = [
            value for wave in waves for value in wave.schedule_to_start_ms
        ]
        finalization_schedule_values = [
            value
            for wave in waves
            for value in wave.finalization_schedule_to_start_ms
        ]
        finalization_duration_values = [
            value for wave in waves for value in wave.finalization_duration_ms
        ]
        finalization_sql_counts = [
            value for wave in waves for value in wave.finalization_sql_count
        ]
        finalization_sql_durations = [
            value for wave in waves for value in wave.finalization_sql_duration_ms
        ]
        finalization_sql_statements: Counter[str] = Counter()
        for wave in waves:
            finalization_sql_statements.update(wave.finalization_sql_statements)
        outbox_values = [value for wave in waves for value in wave.outbox_lag_ms]
        http_values = [wave.http_s for wave in waves]
        terminal_values = [wave.terminal_s for wave in waves]
        total_values = [wave.total_s for wave in waves]
        db_max = max((wave.db_max_connections for wave in waves), default=0)
        db_peak = max((wave.db_peak_connections for wave in waves), default=0)
        summary[str(target_count)] = {
            "runs": len(waves),
            "http_p50_s": _percentile(http_values, 0.50),
            "http_p95_s": _percentile(http_values, 0.95),
            "http_p99_s": _percentile(http_values, 0.99),
            "terminal_p95_s": _percentile(terminal_values, 0.95),
            "total_p95_s": _percentile(total_values, 0.95),
            "schedule_to_start_p95_ms": _percentile(schedule_values, 0.95),
            "finalization_schedule_to_start_p95_ms": _percentile(
                finalization_schedule_values,
                0.95,
            ),
            "finalization_duration_p95_ms": _percentile(
                finalization_duration_values,
                0.95,
            ),
            "finalization_sql_count_mean": (
                statistics.fmean(finalization_sql_counts)
                if finalization_sql_counts
                else 0.0
            ),
            "finalization_sql_count_p95": _percentile(
                [float(value) for value in finalization_sql_counts],
                0.95,
            ),
            "finalization_sql_duration_p95_ms": _percentile(
                finalization_sql_durations,
                0.95,
            ),
            "finalization_sql_top": dict(
                finalization_sql_statements.most_common(15)
            ),
            "outbox_lag_p95_ms": _percentile(outbox_values, 0.95),
            "failed": sum(wave.failed for wave in waves),
            "pool_timeouts": sum(wave.pool_timeouts for wave in waves),
            "events_total": sum(wave.events_total for wave in waves),
            "events_published": sum(wave.events_published for wave in waves),
            "outbox_samples": len(outbox_values),
            "sql_count_mean": (
                statistics.fmean(wave.sql_count for wave in waves) if waves else 0.0
            ),
            "sql_duration_mean_s": (
                statistics.fmean(wave.sql_duration_s for wave in waves)
                if waves
                else 0.0
            ),
            "db_peak_connections": db_peak,
            "db_max_connections": db_max,
            "db_peak_percent": (db_peak * 100.0 / db_max) if db_max else 0.0,
        }
    return summary


def _check(status: bool, value: Any, budget: Any) -> dict[str, Any]:
    return {
        "status": "passed" if status else "failed",
        "value": value,
        "budget": budget,
    }


def _evaluate_gates(
    summary: dict[str, dict[str, Any]],
    *,
    target_count: int,
    baseline_summary: dict[str, dict[str, Any]] | None,
) -> dict[str, Any]:
    target = summary.get(str(target_count))
    if target is None:
        return {
            "passed": False,
            "checks": {
                "target_present": {
                    "status": "failed",
                    "value": None,
                    "budget": target_count,
                }
            },
        }

    checks = {
        "http_p95_s": _check(target["http_p95_s"] <= 5.0, target["http_p95_s"], 5.0),
        "schedule_to_start_p95_ms": _check(
            target["schedule_to_start_p95_ms"] <= 2_000.0,
            target["schedule_to_start_p95_ms"],
            2_000.0,
        ),
        "finalization_schedule_to_start_p95_ms": _check(
            target["finalization_schedule_to_start_p95_ms"] <= 1_000.0,
            target["finalization_schedule_to_start_p95_ms"],
            1_000.0,
        ),
        "finalization_duration_p95_ms": _check(
            target["finalization_duration_p95_ms"] <= 2_000.0,
            target["finalization_duration_p95_ms"],
            2_000.0,
        ),
        "outbox_lag_p95_ms": _check(
            target["outbox_lag_p95_ms"] <= 2_000.0,
            target["outbox_lag_p95_ms"],
            2_000.0,
        ),
        "failed": _check(target["failed"] == 0, target["failed"], 0),
        "event_delivery": _check(
            target["events_total"] >= target_count * target["runs"]
            and target["events_published"] == target["events_total"]
            and target["outbox_samples"] == target["events_published"],
            {
                "total": target["events_total"],
                "published": target["events_published"],
                "lag_samples": target["outbox_samples"],
            },
            {
                "minimum_total": target_count * target["runs"],
                "all_published": True,
                "lag_for_every_event": True,
            },
        ),
        "pool_timeouts": _check(
            target["pool_timeouts"] == 0,
            target["pool_timeouts"],
            0,
        ),
        "db_peak_percent": _check(
            target["db_peak_percent"] < 85.0,
            target["db_peak_percent"],
            85.0,
        ),
    }

    baseline_target = (
        baseline_summary.get(str(target_count)) if baseline_summary else None
    )
    baseline_http_p95 = (
        float(baseline_target.get("http_p95_s", 0.0))
        if baseline_target
        else 0.0
    )
    if baseline_http_p95 > 0:
        improvement = max(
            0.0,
            (baseline_http_p95 - target["http_p95_s"])
            * 100.0
            / baseline_http_p95,
        )
        checks["improvement_30_percent"] = {
            "status": "passed" if improvement >= 30.0 else "failed",
            "value_percent": round(improvement, 3),
            "budget_percent": 30.0,
            "baseline_http_p95_s": baseline_http_p95,
            "current_http_p95_s": target["http_p95_s"],
        }
    else:
        checks["improvement_30_percent"] = {
            "status": "not_evaluated",
            "value_percent": None,
            "budget_percent": 30.0,
        }

    return {
        "passed": all(check["status"] == "passed" for check in checks.values()),
        "checks": checks,
    }


def _operational_gates_passed(gates: dict[str, Any]) -> bool:
    checks = gates.get("checks", {})
    return bool(checks) and all(
        check.get("status") == "passed"
        for name, check in checks.items()
        if name != "improvement_30_percent"
    )


class _SQLTracker:
    def __init__(self) -> None:
        self.count = 0
        self.duration_s = 0.0
        self.by_verb: Counter[str] = Counter()
        self.executemany_calls = 0
        self.pool_current = 0
        self.pool_peak = 0
        self.pool_timeouts = 0
        self._engines: list[Any] = []
        self._probe_before = None
        self._probe_after = None

    def _before(self, _conn, _cursor, statement, _parameters, context, executemany):
        context._campaign_pipeline_sql_started = time.perf_counter()
        self.count += 1
        verb = str(statement).lstrip().split(None, 1)[0].upper() if statement else "OTHER"
        self.by_verb[verb] += 1
        if executemany:
            self.executemany_calls += 1
        if self._probe_before is not None:
            self._probe_before(context, statement)

    def _after(self, _conn, _cursor, _statement, _parameters, context, _executemany):
        started = getattr(context, "_campaign_pipeline_sql_started", None)
        if started is not None:
            self.duration_s += max(0.0, time.perf_counter() - started)
        if self._probe_after is not None:
            self._probe_after(context)

    def _checkout(self, *_args):
        self.pool_current += 1
        self.pool_peak = max(self.pool_peak, self.pool_current)

    def _checkin(self, *_args):
        self.pool_current = max(0, self.pool_current - 1)

    def start(self, *engines: Any) -> None:
        from sqlalchemy import event
        from temporal.capacity_probe import (
            record_finalize_probe_sql_after,
            record_finalize_probe_sql_before,
        )

        self._probe_before = record_finalize_probe_sql_before
        self._probe_after = record_finalize_probe_sql_after

        for engine in dict.fromkeys(engines):
            sync_engine = engine.sync_engine
            event.listen(sync_engine, "before_cursor_execute", self._before)
            event.listen(sync_engine, "after_cursor_execute", self._after)
            event.listen(sync_engine.pool, "checkout", self._checkout)
            event.listen(sync_engine.pool, "checkin", self._checkin)
            self._engines.append(sync_engine)

    def stop(self) -> None:
        from sqlalchemy import event

        for sync_engine in self._engines:
            event.remove(sync_engine, "before_cursor_execute", self._before)
            event.remove(sync_engine, "after_cursor_execute", self._after)
            event.remove(sync_engine.pool, "checkout", self._checkout)
            event.remove(sync_engine.pool, "checkin", self._checkin)
        self._engines.clear()
        self._probe_before = None
        self._probe_after = None


class _PostgresSampler:
    def __init__(self, database_url: str) -> None:
        self.database_url = _asyncpg_database_url(database_url)
        self.peak_connections = 0
        self.max_connections = 0
        self._stop = asyncio.Event()

    async def run(self) -> None:
        import asyncpg

        connection = await asyncpg.connect(self.database_url)
        try:
            self.max_connections = int(
                await connection.fetchval("SHOW max_connections")
            )
            while not self._stop.is_set():
                current = int(
                    await connection.fetchval(
                        "SELECT count(*) FROM pg_stat_activity"
                    )
                )
                self.peak_connections = max(self.peak_connections, current)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=0.05)
                except TimeoutError:
                    pass
        finally:
            await connection.close()

    def stop(self) -> None:
        self._stop.set()


def _is_pool_timeout(message: str) -> bool:
    lowered = message.lower()
    return (
        "queuepool limit" in lowered
        or "pool timeout" in lowered
        or "too many clients" in lowered
        or "remaining connection slots are reserved" in lowered
    )


def _metric_snapshot() -> dict[str, float]:
    from web.metrics import (
        campaign_dispatch_http_duration_seconds,
        campaign_dispatch_phase_duration_seconds,
    )

    snapshot: dict[str, float] = {}
    for metric in (
        campaign_dispatch_http_duration_seconds,
        campaign_dispatch_phase_duration_seconds,
    ):
        for family in metric.collect():
            for sample in family.samples:
                if not sample.name.endswith("_sum"):
                    continue
                phase = sample.labels.get("phase", "http")
                snapshot[phase] = float(sample.value)
    return snapshot


def _metric_delta(before: dict[str, float], after: dict[str, float]) -> dict[str, float]:
    return {
        phase: max(0.0, value - before.get(phase, 0.0))
        for phase, value in after.items()
    }


async def _seed_benchmark_identity(
    session_factory,
    *,
    run_tag: str,
) -> tuple[str, str]:
    from db.models.organization import Organization, OrganizationMember
    from db.models.user import User

    org_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    async with session_factory() as db:
        db.add(
            Organization(
                id=org_id,
                business_name=f"Campaign benchmark {run_tag}",
                business_email=f"{run_tag}@benchmark.invalid",
                slug=f"campaign-benchmark-{run_tag}",
                status="active",
                plan="standard",
            )
        )
        db.add(
            User(
                id=user_id,
                email=f"{run_tag}@benchmark.invalid",
                name="Campaign pipeline benchmark",
                hashed_password="benchmark-disabled-login",
                role="system",
                default_org_id=org_id,
                is_active=True,
            )
        )
        db.add(
            OrganizationMember(
                organization_id=org_id,
                user_id=user_id,
                role="owner",
                status="active",
                joined_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
    return org_id, user_id


async def _seed_benchmark_policy(engine) -> None:
    """Seed the checked-in RBAC policy into an already initialized schema."""
    import importlib

    policy_migration = importlib.import_module("db.migrations.084_casbin_policy_db")
    revision_migration = importlib.import_module(
        "db.migrations.085_casbin_policy_revision"
    )
    async with engine.begin() as connection:
        await policy_migration.upgrade(connection)
        await revision_migration.upgrade(connection)


async def _seed_devices(
    session_factory,
    *,
    org_id: str,
    user_id: str,
    run_tag: str,
    count: int,
) -> list[str]:
    from db.crud.device import create_device
    from db.models.enums import DeviceFsmEvent
    from services.device_state.service import DeviceStateService
    from tenancy.context import set_current_org_id

    set_current_org_id(org_id)
    state_service = DeviceStateService()
    device_ids: list[str] = []
    async with session_factory() as db:
        for index in range(count):
            serial = f"PIPE-{run_tag}-{index:04d}"
            device = await create_device(
                db,
                serial,
                user_id=user_id,
                org_id=org_id,
            )
            device.device_serial = serial
            device.adb_serial = f"{serial}:5555"
            await state_service.apply_event(
                db,
                device.id,
                event=DeviceFsmEvent.ATTACHED.value,
                source="campaign_pipeline_benchmark",
                event_id=f"{run_tag}-{index}-attached",
            )
            await state_service.apply_event(
                db,
                device.id,
                event=DeviceFsmEvent.ONLINE.value,
                source="campaign_pipeline_benchmark",
                event_id=f"{run_tag}-{index}-online",
            )
            device_ids.append(device.id)
        await db.commit()
    return device_ids


def _build_benchmark_app(
    session_factory,
    *,
    config: Any,
    temporal_client: Any,
    org_id: str,
    user_id: str,
):
    from fastapi import FastAPI

    from api.crud.router import api_router
    from api.deps import _get_current_user, _get_db
    from tenancy.context import set_current_org_id

    app = FastAPI()
    app.include_router(api_router, prefix="/api")
    app.state.config = config
    app.state.temporal_client = temporal_client
    app.state.manager = None

    async def _db_override():
        async with session_factory() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    async def _user_override():
        set_current_org_id(org_id)
        return SimpleNamespace(
            id=user_id,
            email=f"{user_id}@benchmark.invalid",
            name="Campaign benchmark",
            role="system",
            org_role="owner",
            is_active=True,
            org_id=org_id,
        )

    app.dependency_overrides[_get_db] = _db_override
    app.dependency_overrides[_get_current_user] = _user_override
    return app


def _install_pipeline_probe_runtime(delay_ms: int, *, org_id: str):
    """Replace the Temporal start seam inside this benchmark process only."""
    import services.campaign.execution_runtime as execution_runtime
    from temporal.campaign_pipeline_probe import CampaignPipelineProbeWorkflow
    from temporalio.common import WorkflowIDReusePolicy

    original = execution_runtime._try_start_temporal
    original_fallback = execution_runtime.schedule_fallback_runtime

    async def _start_probe(
        temporal_client: Any,
        temporal_config: Any,
        scenario_input: Any,
        execution_id: str,
    ) -> str:
        workflow_id = execution_runtime.workflow_id_for_execution(execution_id)
        task_queue = (
            getattr(temporal_config, "task_queue", None)
            or execution_runtime.TASK_QUEUE_NAME
        )
        await temporal_client.start_workflow(
            CampaignPipelineProbeWorkflow.run,
            {
                "campaign_id": scenario_input.campaign_id,
                "execution_id": execution_id,
                "device_serial": scenario_input.device_serial,
                "org_id": org_id,
                "delay_ms": max(0, min(60_000, int(delay_ms))),
            },
            id=workflow_id,
            task_queue=task_queue,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        )
        return workflow_id

    execution_runtime._try_start_temporal = _start_probe

    def _refuse_fallback(**_kwargs: Any) -> None:
        raise RuntimeError(
            "campaign pipeline benchmark refuses physical-device fallback"
        )

    execution_runtime.schedule_fallback_runtime = _refuse_fallback

    def _restore() -> None:
        execution_runtime._try_start_temporal = original
        execution_runtime.schedule_fallback_runtime = original_fallback

    return _restore


async def _create_scenario(client, *, run_tag: str) -> str:
    response = await client.post(
        "/api/scenarios",
        json={
            "name": f"Pipeline benchmark scenario {run_tag}",
            "kind": "sequence",
            "description": "Synthetic Temporal probe; never touches a physical device",
            "tags": ["benchmark", "pipeline-probe"],
        },
    )
    response.raise_for_status()
    scenario_id = str(response.json()["id"])
    body_response = await client.post(
        f"/api/scenarios/{scenario_id}/body",
        json={
            "steps": [
                {
                    "id": "pipeline-probe-placeholder",
                    "type": "input_wait.wait",
                    "config": {"seconds": 0},
                }
            ]
        },
    )
    body_response.raise_for_status()
    return scenario_id


async def _create_campaign(client, *, scenario_id: str, name: str) -> str:
    response = await client.post(
        "/api/campaigns",
        json={
            "name": name,
            "scenario_refs": [{"scenario_id": scenario_id}],
            "vars": {},
            "tags": ["benchmark", "pipeline-probe"],
        },
    )
    response.raise_for_status()
    return str(response.json()["id"])


async def _publish_outbox_until_drained(
    session_factory,
    *,
    campaign_id: str,
    expected_events: int,
    terminal_event: asyncio.Event,
    timeout_s: float,
) -> tuple[list[float], int, int]:
    from sqlalchemy import select

    from db.models.execution_event import ExecutionEvent
    from services.execution.event_publisher import process_outbox_batch

    deadline = time.monotonic() + timeout_s
    while True:
        async with session_factory() as db:
            await process_outbox_batch(db, limit=max(200, expected_events * 2))
        async with session_factory() as db:
            rows = list(
                (
                    await db.execute(
                        select(ExecutionEvent).where(
                            ExecutionEvent.campaign_id == campaign_id
                        )
                    )
                )
                .scalars()
                .all()
            )
        published = [row for row in rows if row.published_at is not None]
        if (
            terminal_event.is_set()
            and len(published) >= expected_events
            and len(published) == len(rows)
        ):
            lags = [
                max(
                    0.0,
                    (row.published_at - row.occurred_at).total_seconds() * 1000.0,
                )
                for row in published
            ]
            return lags, len(rows), len(published)
        if time.monotonic() >= deadline:
            raise TimeoutError(
                "outbox did not drain before timeout "
                f"(campaign_id={campaign_id}, total={len(rows)}, "
                f"published={len(published)}, expected={expected_events})"
            )
        await asyncio.sleep(0.05)


async def _run_wave(
    *,
    client,
    temporal_client,
    session_factory,
    web_engine,
    activity_engine,
    device_ids: list[str],
    scenario_id: str,
    run_tag: str,
    target_count: int,
    repeat: int,
    warmup: bool,
    timeout_s: float,
) -> PipelineWaveResult:
    campaign_id = await _create_campaign(
        client,
        scenario_id=scenario_id,
        name=f"Pipeline benchmark {run_tag}-{target_count}-{repeat}-{'warm' if warmup else 'run'}",
    )
    tracker = _SQLTracker()
    sampler = _PostgresSampler(os.environ["ANDROID_PLATFORM_TESTER_DATABASE_URL"])
    metric_before = _metric_snapshot()
    tracker.start(web_engine, activity_engine)
    sampler_task = asyncio.create_task(sampler.run())
    wall_started = time.perf_counter()
    errors: list[str] = []
    workflow_results: list[dict[str, Any]] = []
    http_status = 0
    response_payload: dict[str, Any] = {}
    http_s = 0.0
    terminal_s = 0.0
    lags: list[float] = []
    events_total = 0
    events_published = 0
    terminal_event = asyncio.Event()
    outbox_task: asyncio.Task[tuple[list[float], int, int]] | None = None
    try:
        http_started = time.perf_counter()
        response = await client.post(
            f"/api/campaigns/{campaign_id}/dispatch",
            json={
                "target": {
                    "device_ids": device_ids[:target_count],
                },
                "dispatch_strategy": "parallel",
                "allow_partial": False,
                "require_online": True,
            },
        )
        http_s = time.perf_counter() - http_started
        http_status = response.status_code
        if response.status_code != 200:
            errors.append(f"dispatch_http_{response.status_code}: {response.text[:500]}")
        else:
            response_payload = response.json()
            workflow_ids = [
                row.get("workflow_id")
                for row in response_payload.get("executions", [])
                if row.get("workflow_id")
            ]
            handles = [
                temporal_client.get_workflow_handle(workflow_id)
                for workflow_id in workflow_ids
            ]
            outbox_task = asyncio.create_task(
                _publish_outbox_until_drained(
                    session_factory,
                    campaign_id=campaign_id,
                    expected_events=len(workflow_ids),
                    terminal_event=terminal_event,
                    timeout_s=min(timeout_s, 30.0),
                )
            )
            try:
                outcomes = await asyncio.wait_for(
                    asyncio.gather(
                        *(handle.result() for handle in handles),
                        return_exceptions=True,
                    ),
                    timeout=timeout_s,
                )
            finally:
                terminal_event.set()
            for outcome in outcomes:
                if isinstance(outcome, BaseException):
                    errors.append(f"{type(outcome).__name__}: {outcome}")
                elif isinstance(outcome, dict):
                    workflow_results.append(outcome)
            terminal_s = time.perf_counter() - wall_started
            lags, events_total, events_published = await outbox_task
    except Exception as exc:  # noqa: BLE001 - keep the report on benchmark failure
        errors.append(f"{type(exc).__name__}: {exc}")
    finally:
        terminal_event.set()
        if outbox_task is not None and not outbox_task.done():
            outbox_task.cancel()
            await asyncio.gather(outbox_task, return_exceptions=True)
        sampler.stop()
        sampler_outcome = await asyncio.gather(sampler_task, return_exceptions=True)
        if sampler_outcome and isinstance(sampler_outcome[0], BaseException):
            errors.append(
                "postgres_sampler: "
                f"{type(sampler_outcome[0]).__name__}: {sampler_outcome[0]}"
            )
        tracker.stop()

    total_s = time.perf_counter() - wall_started
    metric_after = _metric_snapshot()
    execution_count = len(response_payload.get("executions", []))
    completed = sum(1 for result in workflow_results if result.get("ok"))
    failed = max(0, target_count - completed) + len(errors)
    finalization_sql_statements: Counter[str] = Counter()
    for result in workflow_results:
        statements = result.get("finalization_sql_statements")
        if isinstance(statements, dict):
            finalization_sql_statements.update(
                {str(key): int(value) for key, value in statements.items()}
            )
    return PipelineWaveResult(
        target_count=target_count,
        repeat=repeat,
        warmup=warmup,
        http_status=http_status,
        http_s=http_s,
        terminal_s=terminal_s,
        total_s=total_s,
        execution_count=execution_count,
        completed=completed,
        failed=failed,
        schedule_to_start_ms=[
            float(result.get("schedule_to_start_ms", 0.0))
            for result in workflow_results
        ],
        finalization_schedule_to_start_ms=[
            float(result.get("finalization_schedule_to_start_ms", 0.0))
            for result in workflow_results
        ],
        finalization_duration_ms=[
            float(result.get("finalization_duration_ms", 0.0))
            for result in workflow_results
        ],
        finalization_sql_count=[
            int(result.get("finalization_sql_count", 0))
            for result in workflow_results
        ],
        finalization_sql_duration_ms=[
            float(result.get("finalization_sql_duration_ms", 0.0))
            for result in workflow_results
        ],
        finalization_sql_statements=dict(finalization_sql_statements),
        outbox_lag_ms=lags,
        phase_s=_metric_delta(metric_before, metric_after),
        sql_count=tracker.count,
        sql_duration_s=tracker.duration_s,
        sql_by_verb=dict(tracker.by_verb),
        sql_executemany_calls=tracker.executemany_calls,
        pool_peak=tracker.pool_peak,
        pool_timeouts=tracker.pool_timeouts
        + sum(1 for error in errors if _is_pool_timeout(error)),
        db_peak_connections=sampler.peak_connections,
        db_max_connections=sampler.max_connections,
        events_total=events_total,
        events_published=events_published,
        errors=errors,
    )


def _print_wave(result: PipelineWaveResult) -> None:
    label = "warmup" if result.warmup else f"repeat={result.repeat}"
    finalization_sql_mean = (
        statistics.fmean(result.finalization_sql_count)
        if result.finalization_sql_count
        else 0.0
    )
    print(
        f"target={result.target_count:>3} {label:<10} "
        f"http={result.http_s:6.3f}s terminal={result.terminal_s:6.3f}s "
        f"total={result.total_s:6.3f}s completed={result.completed:>3}/"
        f"{result.target_count:<3} sql={result.sql_count:<5} "
        f"db_peak={result.db_peak_connections}/{result.db_max_connections} "
        f"schedule_p95={_percentile(result.schedule_to_start_ms, 0.95):7.1f}ms "
        "finalize_queue_p95="
        f"{_percentile(result.finalization_schedule_to_start_ms, 0.95):7.1f}ms "
        "finalize_run_p95="
        f"{_percentile(result.finalization_duration_ms, 0.95):7.1f}ms "
        f"finalize_sql_mean={finalization_sql_mean:5.1f} "
        f"outbox_p95={_percentile(result.outbox_lag_ms, 0.95):7.1f}ms"
    )
    for error in result.errors:
        print(f"  ! {error}")


def _load_baseline(path: str | None) -> dict[str, dict[str, Any]] | None:
    if not path:
        return None
    payload = json.loads(Path(path).read_text())
    return payload.get("summary") or payload


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


async def async_main(args: argparse.Namespace) -> int:
    database_url = args.database_url or os.environ.get("BENCH_DATABASE_URL", "")
    if not database_url:
        raise SystemExit("--database-url or BENCH_DATABASE_URL is required")
    if not _database_is_isolated(database_url) and not args.allow_shared_db:
        raise SystemExit(
            "Refusing non-benchmark database. Use a dedicated DB name containing "
            "benchmark/bench/perf, or explicitly pass --allow-shared-db."
        )

    os.environ["ANDROID_PLATFORM_TESTER_DATABASE_URL"] = database_url
    run_tag = uuid.uuid4().hex[:10]
    task_queue = f"{args.task_queue}-{run_tag}"
    started_at = datetime.now(timezone.utc)

    from httpx import ASGITransport, AsyncClient
    from temporalio.client import Client
    from temporalio.worker import Worker

    from core.config import TemporalConfig
    from db.database import (
        AsyncSessionLocal,
        _engine_for_loop,
        engine,
        init_db,
    )
    from temporal.activities import set_temporal_config
    from temporal.campaign_pipeline_probe import CampaignPipelineProbeWorkflow
    from temporal.capacity_probe import capacity_probe, finalize_campaign_probe

    if not args.skip_init_db:
        await init_db()
    await _seed_benchmark_policy(engine)
    temporal_client = await Client.connect(
        args.temporal_server,
        namespace=args.temporal_namespace,
    )
    temporal_config = TemporalConfig(
        enabled=True,
        server_url=args.temporal_server,
        namespace=args.temporal_namespace,
        task_queue=task_queue,
        worker_count=1,
        worker_max_concurrent_activities=max(20, args.max_target),
        worker_max_concurrent_workflows=max(60, args.max_target),
    )
    set_temporal_config(temporal_config)
    worker = Worker(
        temporal_client,
        task_queue=task_queue,
        workflows=[CampaignPipelineProbeWorkflow],
        activities=[capacity_probe, finalize_campaign_probe],
        max_concurrent_activities=max(20, args.max_target),
        max_concurrent_workflow_tasks=max(60, args.max_target),
    )

    org_id, user_id = await _seed_benchmark_identity(
        AsyncSessionLocal,
        run_tag=run_tag,
    )
    device_ids = await _seed_devices(
        AsyncSessionLocal,
        org_id=org_id,
        user_id=user_id,
        run_tag=run_tag,
        count=args.max_target,
    )
    app = _build_benchmark_app(
        AsyncSessionLocal,
        config=SimpleNamespace(temporal=temporal_config),
        temporal_client=temporal_client,
        org_id=org_id,
        user_id=user_id,
    )
    activity_engine, _ = _engine_for_loop(asyncio.get_running_loop())
    results: list[PipelineWaveResult] = []
    restore_runtime = _install_pipeline_probe_runtime(
        args.probe_delay_ms,
        org_id=org_id,
    )

    try:
        async with worker:
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://campaign-pipeline-benchmark",
                timeout=args.timeout_s,
            ) as client:
                scenario_id = await _create_scenario(client, run_tag=run_tag)
                for target_count in args.levels:
                    for warmup_index in range(args.warmups):
                        result = await _run_wave(
                            client=client,
                            temporal_client=temporal_client,
                            session_factory=AsyncSessionLocal,
                            web_engine=engine,
                            activity_engine=activity_engine,
                            device_ids=device_ids,
                            scenario_id=scenario_id,
                            run_tag=run_tag,
                            target_count=target_count,
                            repeat=warmup_index + 1,
                            warmup=True,
                            timeout_s=args.timeout_s,
                        )
                        results.append(result)
                        _print_wave(result)
                    for repeat in range(1, args.repeats + 1):
                        result = await _run_wave(
                            client=client,
                            temporal_client=temporal_client,
                            session_factory=AsyncSessionLocal,
                            web_engine=engine,
                            activity_engine=activity_engine,
                            device_ids=device_ids,
                            scenario_id=scenario_id,
                            run_tag=run_tag,
                            target_count=target_count,
                            repeat=repeat,
                            warmup=False,
                            timeout_s=args.timeout_s,
                        )
                        results.append(result)
                        _print_wave(result)
    finally:
        restore_runtime()

    summary = _aggregate_results(results)
    baseline_summary = _load_baseline(args.baseline_json)
    gates = _evaluate_gates(
        summary,
        target_count=args.max_target,
        baseline_summary=baseline_summary,
    )
    report = {
        "schema_version": 1,
        "run_id": run_tag,
        "git_sha": _git_sha(),
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "database_url": _redact_database_url(database_url),
            "temporal_server": args.temporal_server,
            "temporal_namespace": args.temporal_namespace,
            "task_queue": task_queue,
            "probe_delay_ms": args.probe_delay_ms,
            "observer_connections": 1,
            "org_id": org_id,
        },
        "config": {
            "levels": args.levels,
            "warmups": args.warmups,
            "repeats": args.repeats,
            "timeout_s": args.timeout_s,
        },
        "waves": [result.to_dict() for result in results],
        "summary": summary,
        "gates": gates,
    }
    output = Path(args.json_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"summary": summary, "gates": gates}, indent=2, sort_keys=True))
    print(f"wrote report: {output}")
    if gates["passed"]:
        return 0
    if args.capture_baseline and _operational_gates_passed(gates):
        return 0
    return 2


def _parse_levels(raw: str) -> list[int]:
    values = sorted({int(value.strip()) for value in raw.split(",") if value.strip()})
    if not values or any(value <= 0 or value > 500 for value in values):
        raise argparse.ArgumentTypeError("levels must contain integers in [1, 500]")
    return values


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("BENCH_DATABASE_URL", ""))
    parser.add_argument(
        "--allow-shared-db",
        action="store_true",
        help="Explicitly allow writes to a DB whose name is not benchmark/perf-like",
    )
    parser.add_argument("--skip-init-db", action="store_true")
    parser.add_argument(
        "--temporal-server",
        default=os.environ.get("TEMPORAL_SERVER_URL", "localhost:7233"),
    )
    parser.add_argument(
        "--temporal-namespace",
        default=os.environ.get("TEMPORAL_NAMESPACE", "default"),
    )
    parser.add_argument("--task-queue", default="campaign-pipeline-benchmark")
    parser.add_argument("--levels", type=_parse_levels, default=[20, 60, 120])
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--probe-delay-ms", type=int, default=250)
    parser.add_argument("--timeout-s", type=float, default=180.0)
    parser.add_argument("--baseline-json")
    parser.add_argument(
        "--capture-baseline",
        action="store_true",
        help=(
            "Write a baseline report and return success when operational gates pass; "
            "the improvement gate remains not_evaluated"
        ),
    )
    parser.add_argument(
        "--json-output",
        default="tmp/campaign-pipeline-benchmark.json",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.warmups < 0 or args.repeats < 1:
        parser.error("warmups must be >= 0 and repeats must be >= 1")
    if not 0 <= args.probe_delay_ms <= 60_000:
        parser.error("probe-delay-ms must be in [0, 60000]")
    args.max_target = max(args.levels)
    if args.capture_baseline and args.baseline_json:
        parser.error("--capture-baseline and --baseline-json are mutually exclusive")
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
