"""Temporal adapter for one immutable AI Device Lab farm job."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from db.models.ai_device_lab import AppBuild, RunAttempt, ScenarioApproval, ServiceCampaign
from db.models.ai_device_lab_delivery import FarmJob
from db.models.ai_device_lab_fleet import DeviceReservation
from db.models.device import Device
from db.models.execution import Execution
from db.models.scenario_version import ScenarioVersion
from services.ai_device_lab.delivery import AcceptFarmEvent, FarmDeliveryError, accept_farm_event
from services.ai_device_lab.intake import scenario_version_content_hash
from services.campaign.execution_runtime import schedule_fallback_runtime
from services.temporal_orchestrator import (
    TemporalExecutionOrchestrator,
    TemporalWorkflowMetadata,
)
from temporal.shared import ScenarioInput
from temporal.workflows import ScenarioWorkflow
from tenancy.context import tenant_context

_MAX_TEMPORAL_INPUT_BYTES = 500_000
_TERMINAL_EXECUTION_STATES = frozenset({"completed", "failed", "cancelled"})
_TERMINAL_ATTEMPT_STATES = frozenset({"passed", "failed", "blocked", "cancelled"})
_FARM_EVENT_SCHEMA_VERSION = "adl-farm-event-v1"

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _PreparedFarmDispatch:
    org_id: str
    job_id: str
    execution_id: str
    run_attempt_id: str
    actor_user_id: str
    idempotency_key: str
    deadline_at: datetime
    package_name: str
    observed_build: dict[str, str]
    scenario_input: ScenarioInput


def _device_health_freshness_seconds() -> int:
    try:
        raw = int(os.getenv("AI_DEVICE_LAB_DEVICE_HEALTH_FRESHNESS_SECONDS", "120"))
    except ValueError:
        return 120
    return max(30, min(3_600, raw))


def _required_text(payload: dict, key: str, *, max_chars: int = 255) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value or len(value) > max_chars:
        raise FarmDeliveryError("FARM_JOB_PAYLOAD_INVALID")
    if any(ord(char) < 32 for char in value):
        raise FarmDeliveryError("FARM_JOB_PAYLOAD_INVALID")
    return value


def _parse_observed_build(output: str) -> dict[str, str]:
    version_name = re.search(r"(?m)^\s*versionName=([^\s]+)", output)
    version_code = re.search(r"(?m)^\s*versionCode=([^\s]+)", output)
    if version_name is None or version_code is None:
        raise FarmDeliveryError("OBSERVED_BUILD_UNAVAILABLE")
    return {
        "version_name": version_name.group(1),
        "version_code": version_code.group(1),
    }


async def _observe_installed_build(
    manager: Any,
    *,
    serial: str,
    package_name: str,
) -> dict[str, str]:
    def _read() -> str:
        if re.fullmatch(r"emulator-[0-9]{4,5}", serial):
            config = getattr(manager, "config", None)
            adb_config = getattr(config, "adb", None)
            adb = str(getattr(adb_config, "path", "adb") or "adb")
            try:
                return subprocess.run(
                    [adb, "-s", serial, "shell", "dumpsys", "package", package_name],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=15,
                ).stdout
            except (OSError, subprocess.SubprocessError) as exc:
                raise FarmDeliveryError("OBSERVED_BUILD_UNAVAILABLE") from exc
        client = manager.get_device(serial) if hasattr(manager, "get_device") else None
        if client is None or not hasattr(client, "shell_sync"):
            raise FarmDeliveryError("OBSERVED_BUILD_UNAVAILABLE")
        return str(client.shell_sync(f"dumpsys package {package_name}", timeout=15.0) or "")

    return _parse_observed_build(await asyncio.to_thread(_read))


class TemporalFarmJobSink:
    """Dispatch a referenced approved snapshot through the existing Temporal worker."""

    def __init__(
        self,
        *,
        temporal_client: Any,
        session_factory: async_sessionmaker[AsyncSession],
        task_queue: str,
        manager: Any,
        completion_poll_seconds: float = 0.25,
        cancellation_drain_seconds: float = 10.0,
    ) -> None:
        if temporal_client is None:
            raise ValueError("temporal client is required")
        if not task_queue.strip():
            raise ValueError("temporal task queue is required")
        self._temporal_client = temporal_client
        self._session_factory = session_factory
        self._task_queue = task_queue.strip()
        self._manager = manager
        self._completion_poll_seconds = max(0.01, min(5.0, completion_poll_seconds))
        self._cancellation_drain_seconds = max(0.1, min(60.0, cancellation_drain_seconds))
        self._completion_tasks: set[asyncio.Task[None]] = set()
        self._prepared_by_execution: dict[str, _PreparedFarmDispatch] = {}

    async def deliver(self, payload: dict) -> None:
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != "adl-farm-job-v1"
        ):
            raise FarmDeliveryError("UNSUPPORTED_SCHEMA_VERSION")
        if payload.get("secret_capability_ref") is not None:
            raise FarmDeliveryError("SECRET_CAPABILITY_RUNTIME_UNAVAILABLE")

        prepared = await self._prepare(payload)
        orchestrator = TemporalExecutionOrchestrator(self._temporal_client)
        workflow_id: str
        try:
            workflow_id = await orchestrator.start_scenario_workflow(
                workflow_run=ScenarioWorkflow.run,
                scenario_input=prepared.scenario_input,
                execution_id=prepared.execution_id,
                task_queue=self._task_queue,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                metadata=TemporalWorkflowMetadata(
                    workflow_kind="ai_device_lab",
                    execution_id=prepared.execution_id,
                    campaign_id=prepared.scenario_input.campaign_id,
                    org_id=prepared.org_id,
                    device_serial=prepared.scenario_input.device_serial,
                    dispatch_id=prepared.idempotency_key,
                ),
            )
        except WorkflowAlreadyStartedError:
            workflow_id = f"exec_{prepared.execution_id}"
        except FarmDeliveryError:
            raise
        except Exception as exc:
            raise FarmDeliveryError("TEMPORAL_DELIVERY_UNAVAILABLE") from exc

        await self._record_dispatch(prepared, workflow_id)
        if prepared.execution_id in self._prepared_by_execution:
            return
        self._prepared_by_execution[prepared.execution_id] = prepared
        task = asyncio.create_task(
            self._monitor_temporal_completion(prepared, workflow_id),
            name=f"adl-farm-temporal-monitor-{prepared.execution_id}",
        )
        self._track_completion_task(task)

    async def _prepare(self, payload: dict) -> _PreparedFarmDispatch:
        org_id = _required_text(payload, "org_id", max_chars=36)
        service_campaign_id = _required_text(
            payload, "service_campaign_id", max_chars=36
        )
        run_attempt_id = _required_text(payload, "run_attempt_id", max_chars=36)
        reservation_id = _required_text(payload, "reservation_id", max_chars=36)
        execution_id = _required_text(payload, "execution_id", max_chars=36)
        scenario_version_id = _required_text(
            payload, "scenario_version_id", max_chars=36
        )
        scenario_hash = _required_text(payload, "scenario_hash", max_chars=64)
        policy_version = _required_text(payload, "policy_version", max_chars=64)
        package_name = _required_text(payload, "package_name")
        device_id = _required_text(payload, "device_id", max_chars=36)
        lane_id = _required_text(payload, "lane_id", max_chars=36)
        slot_id = _required_text(payload, "slot_id", max_chars=36)
        idempotency_key = _required_text(payload, "idempotency_key", max_chars=128)
        allowed_operations = payload.get("allowed_operations")
        if not isinstance(allowed_operations, list) or not all(
            isinstance(item, str) for item in allowed_operations
        ):
            raise FarmDeliveryError("FARM_JOB_PAYLOAD_INVALID")

        with tenant_context(org_id):
            async with self._session_factory() as db:
                campaign = (
                    await db.execute(
                        select(ServiceCampaign).where(
                            ServiceCampaign.id == service_campaign_id,
                            ServiceCampaign.org_id == org_id,
                        )
                    )
                ).scalar_one_or_none()
                attempt = (
                    await db.execute(
                        select(RunAttempt).where(
                            RunAttempt.id == run_attempt_id,
                            RunAttempt.org_id == org_id,
                        )
                    )
                ).scalar_one_or_none()
                reservation = (
                    await db.execute(
                        select(DeviceReservation).where(
                            DeviceReservation.id == reservation_id,
                            DeviceReservation.org_id == org_id,
                            DeviceReservation.state == "active",
                        )
                    )
                ).scalar_one_or_none()
                approval = (
                    await db.execute(
                        select(ScenarioApproval).where(
                            ScenarioApproval.org_id == org_id,
                            ScenarioApproval.scenario_version_id == scenario_version_id,
                            ScenarioApproval.content_hash == scenario_hash,
                            ScenarioApproval.policy_version == policy_version,
                        )
                    )
                ).scalar_one_or_none()
                execution = (
                    await db.execute(
                        select(Execution).where(
                            Execution.id == execution_id,
                            Execution.org_id == org_id,
                        )
                    )
                ).scalar_one_or_none()
                device = (
                    await db.execute(
                        select(Device).where(
                            Device.id == device_id,
                            Device.org_id == org_id,
                        )
                    )
                ).scalar_one_or_none()
                version = await db.get(ScenarioVersion, scenario_version_id)
                build = await db.get(AppBuild, attempt.app_build_id) if attempt is not None else None
                job = (
                    await db.execute(
                        select(FarmJob).where(
                            FarmJob.org_id == org_id,
                            FarmJob.run_attempt_id == run_attempt_id,
                            FarmJob.idempotency_key == idempotency_key,
                        )
                    )
                ).scalar_one_or_none()

                if None in (
                    campaign,
                    attempt,
                    reservation,
                    approval,
                    execution,
                    device,
                    version,
                    build,
                    job,
                ):
                    raise FarmDeliveryError("FARM_JOB_SCOPE_INVALID")
                if (
                    attempt.service_campaign_id != campaign.id
                    or attempt.lane_id != lane_id
                    or attempt.slot_id != slot_id
                    or attempt.execution_id != execution.id
                    or attempt.scenario_version_id != version.id
                    or reservation.service_campaign_id != campaign.id
                    or reservation.lane_id != lane_id
                    or reservation.device_id != device.id
                    or execution.campaign_id != campaign.runtime_campaign_id
                    or execution.scenario_version_id != version.id
                    or approval.package_name != package_name
                    or approval.allowed_operations != allowed_operations
                    or scenario_version_content_hash(version) != scenario_hash
                    or build.id != payload.get("app_build_id")
                    or build.package_name != package_name
                ):
                    raise FarmDeliveryError("FARM_JOB_SCOPE_INVALID")
                if execution.status in _TERMINAL_EXECUTION_STATES or attempt.status in (
                    _TERMINAL_ATTEMPT_STATES
                ):
                    raise FarmDeliveryError("FARM_JOB_TERMINAL")
                last_seen = device.last_seen
                if last_seen is None:
                    raise FarmDeliveryError("DEVICE_HEALTH_STALE")
                if last_seen.tzinfo is None:
                    last_seen = last_seen.replace(tzinfo=UTC)
                freshness = timedelta(seconds=_device_health_freshness_seconds())
                if last_seen.astimezone(UTC) < datetime.now(UTC) - freshness:
                    raise FarmDeliveryError("DEVICE_HEALTH_STALE")
                if not isinstance(version.steps, list) or not version.steps:
                    raise FarmDeliveryError("SCENARIO_STEPS_INVALID")

                observed_build = await _observe_installed_build(
                    self._manager,
                    serial=device.serial,
                    package_name=package_name,
                )
                observed_build["package_name"] = package_name
                observed_build["target_app_build_id"] = build.id
                attempt.observed_build = observed_build
                await db.commit()
                if (
                    observed_build["version_name"] != build.version_name
                    or observed_build["version_code"] != build.version_code
                ):
                    raise FarmDeliveryError("OBSERVED_BUILD_MISMATCH")

                scenario_input = ScenarioInput(
                    campaign_id=campaign.runtime_campaign_id,
                    device_serial=device.serial,
                    steps=list(version.steps),
                    variables=dict(version.variables or {}),
                    campaign_vars={
                        "__ORG_ID__": org_id,
                        "__PACKAGE_NAME__": package_name,
                    },
                    scenario_registry={},
                    execution_id=execution.id,
                    run_id=execution.id,
                    capture_steps=True,
                    scenario_config={
                        "scenario_name": "AI Device Lab approved scenario",
                        "capture_mode": "all",
                    },
                )
                encoded = json.dumps(
                    {
                        "steps": scenario_input.steps,
                        "variables": scenario_input.variables,
                        "campaign_vars": scenario_input.campaign_vars,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                if len(encoded) > _MAX_TEMPORAL_INPUT_BYTES:
                    raise FarmDeliveryError("SCENARIO_PAYLOAD_TOO_LARGE")
                return _PreparedFarmDispatch(
                    org_id=org_id,
                    job_id=job.id,
                    execution_id=execution.id,
                    run_attempt_id=attempt.id,
                    actor_user_id=execution.user_id,
                    idempotency_key=idempotency_key,
                    deadline_at=job.deadline_at,
                    package_name=package_name,
                    observed_build=observed_build,
                    scenario_input=scenario_input,
                )

    async def _record_dispatch(
        self,
        prepared: _PreparedFarmDispatch,
        workflow_id: str,
        *,
        runtime_engine: str = "temporal",
    ) -> None:
        with tenant_context(prepared.org_id):
            async with self._session_factory() as db:
                execution = (
                    await db.execute(
                        select(Execution)
                        .where(
                            Execution.id == prepared.execution_id,
                            Execution.org_id == prepared.org_id,
                        )
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                attempt = (
                    await db.execute(
                        select(RunAttempt)
                        .where(
                            RunAttempt.id == prepared.run_attempt_id,
                            RunAttempt.org_id == prepared.org_id,
                        )
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if execution is None or attempt is None:
                    raise FarmDeliveryError("FARM_JOB_SCOPE_INVALID")
                if execution.status not in _TERMINAL_EXECUTION_STATES:
                    meta = dict(execution.meta or {})
                    meta.update(
                        {
                            "dispatch_source": "ai_device_lab_farm_outbox",
                            "runtime_engine": runtime_engine,
                            "workflow_id": workflow_id,
                            "workflow_ids": [workflow_id],
                        }
                    )
                    execution.meta = meta
                    execution.status = "running"
                    execution.started_at = execution.started_at or datetime.now(UTC)
                if attempt.status not in _TERMINAL_ATTEMPT_STATES:
                    attempt.status = "dispatched"
                    attempt.started_at = attempt.started_at or datetime.now(UTC)
                await db.commit()

    def _track_completion_task(self, task: asyncio.Task[None]) -> None:
        self._completion_tasks.add(task)

        def _done(completed: asyncio.Task[None]) -> None:
            self._completion_tasks.discard(completed)
            if completed.cancelled():
                return
            error = completed.exception()
            if error is not None:
                log.error("AI Device Lab completion monitor failed: %s", error)

        task.add_done_callback(_done)

    async def _monitor_temporal_completion(
        self,
        prepared: _PreparedFarmDispatch,
        workflow_id: str,
    ) -> None:
        deadline = prepared.deadline_at
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        deadline = deadline.astimezone(UTC)
        handle = self._temporal_client.get_workflow_handle(workflow_id)
        remaining = max(0.0, (deadline - datetime.now(UTC)).total_seconds())
        try:
            result = await asyncio.wait_for(handle.result(), timeout=remaining)
            await self._record_terminal(
                prepared,
                status="completed" if bool(getattr(result, "success", False)) else "failed",
                source="temporal-runtime",
            )
        except TimeoutError:
            await handle.cancel()
            try:
                await asyncio.wait_for(
                    handle.result(), timeout=self._cancellation_drain_seconds
                )
            except TimeoutError:
                await self._record_terminal(
                    prepared,
                    status="uncertain",
                    source="temporal-runtime",
                    reason_code="CANCEL_DRAIN_UNCONFIRMED",
                )
            except Exception:  # cancellation is still confirmed by terminal result
                await self._record_terminal(
                    prepared,
                    status="deadline",
                    source="temporal-runtime",
                )
            else:
                await self._record_terminal(
                    prepared,
                    status="deadline",
                    source="temporal-runtime",
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            await self._record_terminal(
                prepared,
                status="failed",
                source="temporal-runtime",
                reason_code="TEMPORAL_EXECUTION_FAILED",
            )
        finally:
            self._prepared_by_execution.pop(prepared.execution_id, None)

    async def _record_terminal(
        self,
        prepared: _PreparedFarmDispatch,
        *,
        status: str,
        source: str,
        reason_code: str | None = None,
    ) -> None:
        now = datetime.now(UTC)
        if status == "completed":
            event_type = "completed"
            assertion_passed: bool | None = True
            reason_code = reason_code or "ASSERTIONS_PASSED"
            execution_status = "completed"
        elif status == "cancelled":
            event_type = "cancelled"
            assertion_passed = None
            reason_code = reason_code or "CANCELLED"
            execution_status = "cancelled"
        elif status == "deadline":
            event_type = "deadline"
            assertion_passed = None
            reason_code = reason_code or "DEADLINE_EXCEEDED"
            execution_status = "failed"
        elif status == "uncertain":
            event_type = "uncertain"
            assertion_passed = None
            reason_code = reason_code or "CANCEL_DRAIN_UNCONFIRMED"
            execution_status = "failed"
        else:
            event_type = "assertion"
            assertion_passed = False
            reason_code = reason_code or "FARM_EXECUTION_FAILED"
            execution_status = "failed"

        with tenant_context(prepared.org_id):
            async with self._session_factory() as db:
                await accept_farm_event(
                    db,
                    AcceptFarmEvent(
                        org_id=prepared.org_id,
                        job_id=prepared.job_id,
                        schema_version=_FARM_EVENT_SCHEMA_VERSION,
                        execution_id=prepared.execution_id,
                        source=source,
                        event_id=f"{source}-terminal:{prepared.execution_id}:{status}",
                        event_type=event_type,
                        occurred_at=now,
                        reason_code=reason_code,
                        assertion_passed=assertion_passed,
                    ),
                )
                execution = await db.get(Execution, prepared.execution_id)
                if execution is None:
                    raise FarmDeliveryError("FARM_JOB_SCOPE_INVALID")
                if execution.status not in _TERMINAL_EXECUTION_STATES:
                    execution.status = execution_status
                    execution.finished_at = execution.finished_at or now
                await db.commit()

    async def aclose(self) -> None:
        tasks = tuple(self._completion_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._prepared_by_execution.clear()


class FallbackFarmJobSink(TemporalFarmJobSink):
    """Dispatch through the existing in-process runtime without blind replay."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        manager: Any,
        completion_poll_seconds: float = 0.25,
        cancellation_drain_seconds: float = 10.0,
    ) -> None:
        self._session_factory = session_factory
        self._manager = manager
        self._completion_poll_seconds = max(0.01, min(5.0, completion_poll_seconds))
        self._cancellation_drain_seconds = max(0.1, min(60.0, cancellation_drain_seconds))
        self._completion_tasks: set[asyncio.Task[None]] = set()
        self._prepared_by_execution: dict[str, _PreparedFarmDispatch] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._runtime_tasks: dict[str, asyncio.Task[None]] = {}

    async def deliver(self, payload: dict) -> None:
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != "adl-farm-job-v1"
        ):
            raise FarmDeliveryError("UNSUPPORTED_SCHEMA_VERSION")
        if payload.get("secret_capability_ref") is not None:
            raise FarmDeliveryError("SECRET_CAPABILITY_RUNTIME_UNAVAILABLE")

        prepared = await self._prepare(payload)
        with tenant_context(prepared.org_id):
            async with self._session_factory() as db:
                execution = await db.get(Execution, prepared.execution_id)
                meta = dict(execution.meta or {}) if execution is not None else {}
                if (
                    meta.get("dispatch_source") == "ai_device_lab_farm_outbox"
                    and meta.get("runtime_engine") == "fallback"
                ):
                    raise FarmDeliveryError("FALLBACK_DISPATCH_UNCERTAIN")

        workflow_id = f"fallback_exec_{prepared.execution_id}"
        await self._record_dispatch(
            prepared,
            workflow_id,
            runtime_engine="fallback",
        )
        self._prepared_by_execution[prepared.execution_id] = prepared
        cancel_event = threading.Event()
        self._cancel_events[prepared.execution_id] = cancel_event
        runtime_task = schedule_fallback_runtime(
            scenario_input=prepared.scenario_input,
            execution_id=prepared.execution_id,
            org_id=prepared.org_id,
            actor_user_id=prepared.actor_user_id,
            manager=self._manager,
            cancel_event=cancel_event,
        )
        if runtime_task is None:
            raise FarmDeliveryError("FALLBACK_DISPATCH_UNAVAILABLE")
        self._runtime_tasks[prepared.execution_id] = runtime_task
        task = asyncio.create_task(
            self._monitor_completion(prepared),
            name=f"adl-farm-fallback-monitor-{prepared.execution_id}",
        )
        self._track_completion_task(task)

    async def _monitor_completion(self, prepared: _PreparedFarmDispatch) -> None:
        deadline = prepared.deadline_at
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        else:
            deadline = deadline.astimezone(UTC)
        while datetime.now(UTC) < deadline:
            await asyncio.sleep(self._completion_poll_seconds)
            with tenant_context(prepared.org_id):
                async with self._session_factory() as db:
                    execution = await db.get(Execution, prepared.execution_id)
                    status = execution.status if execution is not None else "failed"
            if status in _TERMINAL_EXECUTION_STATES:
                if status == "cancelled":
                    cancel_event = self._cancel_events.get(prepared.execution_id)
                    if cancel_event is not None:
                        cancel_event.set()
                await self._record_terminal(
                    prepared, status=status, source="fallback-runtime"
                )
                self._prepared_by_execution.pop(prepared.execution_id, None)
                self._cancel_events.pop(prepared.execution_id, None)
                self._runtime_tasks.pop(prepared.execution_id, None)
                return
        cancel_event = self._cancel_events.get(prepared.execution_id)
        if cancel_event is not None:
            cancel_event.set()
        runtime_task = self._runtime_tasks.get(prepared.execution_id)
        try:
            if runtime_task is not None:
                await asyncio.wait_for(
                    asyncio.shield(runtime_task),
                    timeout=self._cancellation_drain_seconds,
                )
        except TimeoutError:
            await self._record_terminal(
                prepared,
                status="uncertain",
                source="fallback-runtime",
                reason_code="CANCEL_DRAIN_UNCONFIRMED",
            )
        else:
            await self._record_terminal(
                prepared, status="deadline", source="fallback-runtime"
            )
        finally:
            self._prepared_by_execution.pop(prepared.execution_id, None)
            self._cancel_events.pop(prepared.execution_id, None)
            self._runtime_tasks.pop(prepared.execution_id, None)

    async def aclose(self) -> None:
        for cancel_event in self._cancel_events.values():
            cancel_event.set()
        runtime_tasks = tuple(self._runtime_tasks.values())
        if runtime_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*runtime_tasks, return_exceptions=True),
                    timeout=self._cancellation_drain_seconds,
                )
            except TimeoutError:
                log.error("AI Device Lab fallback runtime did not drain before shutdown")
        await super().aclose()
        self._cancel_events.clear()
        self._runtime_tasks.clear()
